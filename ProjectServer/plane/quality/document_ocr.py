"""Local OCR candidates: exact source, queued extraction, explicit human review, draft only."""

import hashlib
import json
import os
import re
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import requests
from celery import shared_task
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from rest_framework.response import Response

from .models import DocumentImport
from .permissions import capable, writable_member
from .views import QualityView, Conflict
from .document_imports import (
    verified_file_handle,
    representation,
    extracted_content,
    validate,
    sensitive_content,
)
from .document_parser import extract_local, MAX_UPLOAD


class OcrUnavailable(APIException):
    status_code = 503
    default_detail = "图片文字识别服务未配置或暂不可用。"


def configuration():
    base = os.environ.get("DOCUMENT_OCR_BASE_URL", "").strip().rstrip("/")
    key = os.environ.get("DOCUMENT_OCR_API_KEY", "")
    allowed = {
        x.strip().rstrip("/") for x in os.environ.get("DOCUMENT_OCR_ALLOWED_HTTP_ORIGINS", "").split(",") if x.strip()
    }
    try:
        parts = urlsplit(base)
        valid = (
            parts.scheme == "http"
            and base in allowed
            and parts.path == ""
            and parts.port is not None
            and 1 <= parts.port <= 65535
            and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9.-]*", parts.hostname or "")
            and not parts.username
            and not parts.password
            and not parts.query
            and not parts.fragment
        )
    except ValueError:
        valid = False
    if not valid or len(key) < 16:
        raise OcrUnavailable()
    return base, key


def permitted(row, actor):
    return bool(
        actor
        and actor.is_active
        and writable_member(row.project_id, actor.id, row.project.workspace.slug)
        and capable(row.project_id, actor.id, "knowledge_edit")
    )


def editable(view, pk):
    row = get_object_or_404(
        DocumentImport.objects.select_for_update().select_related("project__workspace"),
        pk=pk,
        project_id=view.project_id,
        resource="knowledge",
    )
    if not permitted(row, view.request.user):
        raise PermissionDenied("当前权限不能识别或核对知识文字。")
    if row.status == "confirmed":
        raise Conflict("已确认导入的内容不能被识别任务覆盖，请重新导入原件。")
    return row


def original(row):
    files = list(row.files.filter(kind="original"))
    if len(files) != 1 or not 0 < files[0].size <= MAX_UPLOAD:
        raise ValidationError({"file": "原件缺失或超出20MiB，请重新导入。"})
    extension = Path(row.name).suffix.lower()
    if extension not in {".png", ".pdf", ".docx"}:
        raise ValidationError({"file": "当前支持PNG图片、PDF和DOCX中的图片文字。"})
    return files[0], extension


def public_state(row):
    state = row.extraction.get("ocr", {})
    return {
        k: state[k]
        for k in ["token", "status", "segments", "failures", "requires_review", "reviewed", "error"]
        if k in state
    } or {
        "token": "",
        "status": "idle",
        "segments": [],
        "failures": [],
        "requires_review": False,
        "reviewed": False,
    }


def enqueue_ocr(row_id, token, delay=0):
    try:
        process_ocr.apply_async(args=[str(row_id), token], queue="celery", expires=600, countdown=delay)
    except Exception:
        finish(row_id, token, {"status": "failed", "error": "识别任务暂时无法排队，请稍后重试。"})


class DocumentOcr(QualityView):
    @transaction.atomic
    def get(self, request, pk, **kwargs):
        row = editable(self, pk)
        state = row.extraction.get("ocr", {})
        requested = state.get("requested_at")
        if (
            state.get("status") in {"queued", "running"}
            and isinstance(requested, (int, float))
            and timezone.now().timestamp() - requested > 600
        ):
            row.extraction = {
                **row.extraction,
                "ocr": {**state, "status": "failed", "error": "识别等待超时，请稍后重新发起。"},
            }
            row.save(update_fields=["extraction"])
        return Response(public_state(row))

    @transaction.atomic
    def post(self, request, pk, **kwargs):
        if request.data:
            raise ValidationError({"ocr": "识别请求不接受额外参数。"})
        row = editable(self, pk)
        return request_ocr(row, request.user)


def request_ocr(row, actor):
    configuration()
    file, _ = original(row)
    with verified_file_handle(file):
        pass
    if row.extraction.get("safe_for_ocr") is not True:
        raise ValidationError({"file": "原件未通过安全解析，不能改用图片识别绕过；请重新导入有效文件。"})
    prior = row.extraction.get("ocr", {})
    if prior.get("status") in {"queued", "running"}:
        requested = prior.get("requested_at")
        if isinstance(requested, (int, float)) and timezone.now().timestamp() - requested > 600:
            prior = {**prior, "status": "failed"}
    if prior.get("status") in {"queued", "running"}:
        return Response(public_state(row), status=202)
    if prior.get("status") == "completed" and prior.get("requires_review"):
        return Response(public_state(row))
    token = uuid4().hex
    row.extraction = {
        **row.extraction,
        "ocr": {
            "token": token,
            "status": "queued",
            "segments": [],
            "failures": [],
            "requires_review": True,
            "reviewed": False,
            "actor_id": str(actor.id),
            "source_sha256": file.sha256,
            "requested_at": timezone.now().timestamp(),
        },
    }
    row.save(update_fields=["extraction"])
    transaction.on_commit(lambda: enqueue_ocr(row.id, token))
    return Response(public_state(row), status=202)


def finish(row_id, token, values):
    with transaction.atomic():
        row = DocumentImport.objects.select_for_update().filter(pk=row_id).first()
        if not row or row.status == "confirmed" or row.extraction.get("ocr", {}).get("token") != token:
            return
        if row.extraction["ocr"].get("reviewed") or row.extraction["ocr"].get("status") not in {"queued", "running"}:
            return
        state = {**row.extraction["ocr"], **values}
        row.extraction = {**row.extraction, "ocr": state}
        row.save(update_fields=["extraction"])


def checked_result(result, file, extension, source=None):
    if (
        not isinstance(result, dict)
        or result.get("source_sha256") != file.sha256
        or result.get("status") != "completed"
        or result.get("engine") != "tesseract"
        or result.get("requires_review") is not True
    ):
        raise ValueError("source mismatch")
    rows = result.get("segments")
    failures = result.get("failures")
    if not isinstance(rows, list) or not isinstance(failures, list) or len(rows) > 20 or len(failures) > 40:
        raise ValueError("invalid ranges")
    selected = []
    keys, locators = set(), set()
    for index, value in enumerate(rows, 1):
        text = value.get("text") if isinstance(value, dict) else None
        if not isinstance(text, str) or not text.strip() or len(text) > 100000 or sensitive_content(text):
            raise ValueError("invalid text")
        if (
            not isinstance(value.get("key"), str)
            or not re.fullmatch(r"ocr-[1-9][0-9]{0,2}", value["key"])
            or value["key"] in keys
        ):
            raise ValueError("invalid segment key")
        keys.add(value["key"])
        segment = {"key": f"ocr-{index}", "text": text, "method": "ocr"}
        if extension == ".pdf":
            if type(value.get("page")) is not int or not 1 <= value["page"] <= 20:
                raise ValueError("invalid page")
            segment["page"] = value["page"]
        elif extension == ".docx":
            if (
                not isinstance(value.get("part"), str)
                or not re.fullmatch(r"word/[a-zA-Z0-9_.-]+\.xml", value["part"])
                or type(value.get("paragraph")) is not int
                or value["paragraph"] < 1
                or not isinstance(value.get("source_image"), str)
                or not re.fullmatch(r"word/media/[a-zA-Z0-9_.-]+", value["source_image"])
            ):
                raise ValueError("invalid document locator")
            segment.update({k: value[k] for k in ["part", "paragraph", "source_image"]})
        else:
            segment["source_image"] = file.name
        locator = (segment.get("page"), segment.get("part"), segment.get("paragraph"), segment.get("source_image"))
        if locator in locators:
            raise ValueError("duplicate source range")
        locators.add(locator)
        for name in ["width", "height"]:
            number = value.get(name)
            if type(number) is not int or not 0 < number <= 3508:
                raise ValueError("invalid dimensions")
            segment[name] = number
        if segment["width"] * segment["height"] > 9000000:
            raise ValueError("invalid pixel budget")
        selected.append(segment)
    if sum(len(s["text"]) for s in selected) > 100000:
        raise ValueError("text budget")
    if sum(s["width"] * s["height"] for s in selected) > 60000000:
        raise ValueError("total pixel budget")
    if failures:
        for failure in failures:
            if not isinstance(failure, dict):
                raise ValueError("invalid failure")
            if "page" in failure and (type(failure["page"]) is not int or not 1 <= failure["page"] <= 20):
                raise ValueError("invalid failed page")
            if any(
                not isinstance(failure[k], str) or len(failure[k]) > 300
                for k in ["part", "source_image"]
                if k in failure
            ):
                raise ValueError("invalid failed locator")
            if failure.get("part") and not re.fullmatch(r"word/[a-zA-Z0-9_.-]+\.xml", failure["part"]):
                raise ValueError("invalid failed part")
            if failure.get("source_image") and not re.fullmatch(r"word/media/[a-zA-Z0-9_.-]+", failure["source_image"]):
                raise ValueError("invalid failed image")
            if sensitive_content({k: failure[k] for k in ["part", "source_image"] if k in failure}):
                raise ValueError("sensitive failed locator")
        # Do not copy arbitrary service diagnostics or user data into an error message.
        failures = [
            {
                **{k: f[k] for k in ["page", "part", "source_image"] if k in f},
                "error": "此范围文字识别未完成，请核对原件后重新提供清晰文件。",
            }
            for f in failures
            if isinstance(f, dict)
        ]
        if not failures:
            raise ValueError("invalid failures")
    if not selected and not failures:
        failures = [{"error": "没有识别到可核对的文字。"}]
    if source and selected and not failures:
        if extension == ".pdf":
            if {s["page"] for s in selected} != set(range(1, source["page_count"] + 1)):
                raise ValueError("OCR did not cover every page")
        elif extension == ".docx":
            expected = {(s["part"], s["paragraph"], s["source_image"]) for s in source.get("image_locations", [])}
            actual = {(s["part"], s["paragraph"], s["source_image"]) for s in selected}
            if not expected or actual != expected:
                raise ValueError("OCR image locations do not match original")
    return selected, failures


@shared_task(name="plane.quality.process_import_ocr", soft_time_limit=165, time_limit=180)
def process_ocr(row_id, token):
    with transaction.atomic():
        row = DocumentImport.objects.select_for_update().select_related("project__workspace").filter(pk=row_id).first()
        if not row or row.status == "confirmed" or row.extraction.get("ocr", {}).get("token") != token:
            return
        state = row.extraction["ocr"]
        if state.get("status") != "queued":
            return
        from plane.db.models import User

        actor = User.objects.filter(pk=state.get("actor_id")).first()
        if not permitted(row, actor):
            finish(row_id, token, {"status": "failed", "error": "当前账号的知识维护权限已失效。"})
            return
        row.extraction = {**row.extraction, "ocr": {**state, "status": "running"}}
        row.save(update_fields=["extraction"])
    try:
        base, key = configuration()
        file, extension = original(row)
        parsed = None
        with verified_file_handle(file) as handle:
            if extension in {".pdf", ".docx"}:
                parsed = extract_local(handle.read(MAX_UPLOAD + 1), extension)
                handle.seek(0)
                if parsed.get("safe_for_ocr") is not True:
                    raise ValueError("unsafe original")
            else:
                if handle.read(8) != b"\x89PNG\r\n\x1a\n":
                    raise ValueError("invalid PNG")
                handle.seek(0)
            row.refresh_from_db()
            if (
                row.status == "confirmed"
                or row.extraction.get("ocr", {}).get("token") != token
                or row.extraction.get("ocr", {}).get("status") != "running"
                or not permitted(row, actor)
            ):
                raise ValueError("access or task changed")
            response = requests.post(
                base + "/v1/extract",
                data=handle,
                headers={
                    "Authorization": "Bearer " + key,
                    "Content-Type": "application/octet-stream",
                    "X-Document-Type": extension[1:],
                    "X-Content-SHA256": file.sha256,
                },
                timeout=(5, 125),
                allow_redirects=False,
                stream=True,
            )
            try:
                if response.status_code == 429:
                    with transaction.atomic():
                        current = DocumentImport.objects.select_for_update().get(pk=row_id)
                        status = current.extraction.get("ocr", {})
                        retries = status.get("busy_retries", 0)
                        if (
                            status.get("token") == token
                            and status.get("status") == "running"
                            and type(retries) is int
                            and retries < 20
                        ):
                            current.extraction = {
                                **current.extraction,
                                "ocr": {
                                    **status,
                                    "status": "queued",
                                    "busy_retries": retries + 1,
                                },
                            }
                            current.save(update_fields=["extraction"])
                            transaction.on_commit(lambda: enqueue_ocr(row_id, token, 5))
                            return
                    raise ValueError("OCR queue remains busy")
                if response.status_code != 200:
                    raise ValueError("OCR unavailable")
                raw = bytearray()
                for block in response.iter_content(64 * 1024):
                    raw.extend(block)
                    if len(raw) > 2 * 1024 * 1024:
                        raise ValueError("response budget")
                segments, failures = checked_result(json.loads(raw), file, extension, parsed)
            finally:
                response.close()
        row.refresh_from_db()
        if not permitted(row, actor):
            raise ValueError("access revoked")
        with verified_file_handle(file):
            pass
        finish(
            row_id,
            token,
            {
                "status": "completed",
                "segments": segments,
                "failures": failures,
                "requires_review": True,
                "engine": "tesseract",
                "source_sha256": file.sha256,
            },
        )
    except Exception:
        finish(row_id, token, {"status": "failed", "error": "文字识别未完成，请核对文件、服务配置和账号权限后重试。"})


class ReviewedSegment(serializers.Serializer):
    key = serializers.CharField(max_length=40)
    text = serializers.CharField(max_length=100000, trim_whitespace=False)

    def to_internal_value(self, data):
        if not isinstance(data, dict) or set(data) != {"key", "text"}:
            raise ValidationError({"segments": "核对只允许修改文字，不能改动页码或图片来源。"})
        return super().to_internal_value(data)


class ReviewInput(serializers.Serializer):
    expected_token = serializers.CharField(max_length=64)
    confirmed = serializers.BooleanField()
    segments = ReviewedSegment(many=True, allow_empty=False, max_length=20)

    def to_internal_value(self, data):
        if not isinstance(data, dict) or set(data) != {"expected_token", "confirmed", "segments"}:
            raise ValidationError({"ocr": "核对请求包含不支持的字段。"})
        return super().to_internal_value(data)

    def validate(self, data):
        if not data["confirmed"]:
            raise ValidationError({"confirmed": "请先对照原件核对所有识别文字。"})
        return data


class DocumentOcrReview(QualityView):
    @transaction.atomic
    def post(self, request, pk, **kwargs):
        schema = ReviewInput(data=request.data)
        schema.is_valid(raise_exception=True)
        data = schema.validated_data
        row = editable(self, pk)
        state = row.extraction.get("ocr", {})
        if state.get("token") != data["expected_token"] or state.get("status") != "completed" or state.get("reviewed"):
            raise Conflict("识别结果已改变或已采用，请重新打开当前结果。")
        if state.get("failures"):
            raise ValidationError({"ocr": "仍有未识别范围，不能将部分内容当作完整知识导入。"})
        original_file, _ = original(row)
        with verified_file_handle(original_file):
            pass
        if state.get("source_sha256") != original_file.sha256:
            raise Conflict("原件与识别结果不一致，请重新导入。")
        values = {s["key"]: s["text"] for s in data["segments"]}
        expected = {s["key"] for s in state.get("segments", [])}
        if not expected or set(values) != expected or len(values) != len(data["segments"]):
            raise ValidationError({"segments": "请完整核对本次所有文字段，不能遗漏、重复或新增来源。"})
        if sum(len(x) for x in values.values()) > 100000 or sensitive_content(values):
            raise ValidationError({"segments": "文字超出允许长度或含疑似敏感信息，请核对后重试。"})
        reviewed = [{**s, "text": values[s["key"]], "method": "ocr_reviewed"} for s in state["segments"]]
        extraction = deepcopy(row.extraction)
        extraction["original_segments"] = extraction.get("original_segments", extraction.get("segments", []))
        # Preserve every native text segment; OCR adds explicit reviewed ranges rather than replacing source text.
        native = extraction["original_segments"]
        if extraction.get("format") == "pdf":
            # Full-page OCR duplicates a native text layer. Keep original native
            # metadata separately and preserve actual page order in the reviewed text.
            pages = {s["page"] for s in reviewed if "page" in s}
            extraction["segments"] = sorted(
                [*[s for s in native if s.get("page") not in pages], *reviewed], key=lambda s: s.get("page", 0)
            )
        elif extraction.get("format") == "docx":
            extraction["segments"] = sorted(
                [*native, *reviewed],
                key=lambda s: (s.get("part", ""), s.get("paragraph", 0), s.get("method") == "ocr_reviewed"),
            )
        else:
            extraction["segments"] = [*native, *reviewed]
        extraction["ocr"] = {
            **state,
            "requires_review": False,
            "reviewed": True,
            "reviewed_segments": reviewed,
            "reviewed_by_id": str(request.user.id),
        }
        extraction["failures"] = []
        content = extracted_content(extraction)
        errors, rows = validate("knowledge", [{"title": Path(row.name).stem[:255], "content": content}])
        if errors:
            raise ValidationError({"errors": errors})
        digest = hashlib.sha256(
            json.dumps(
                {
                    "rows": rows,
                    "errors": errors,
                    "source_url": row.source_url,
                    "original_sha256": original_file.sha256,
                    "ocr_review_token": state["token"],
                },
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            ).encode()
        ).hexdigest()
        if (
            DocumentImport.objects.filter(project=row.project, resource="knowledge", sha256=digest)
            .exclude(pk=row.pk)
            .exists()
        ):
            raise Conflict("相同核对结果已存在，请使用已保存的预检。")
        row.rows, row.errors, row.sha256, row.extraction = rows, errors, digest, extraction
        row.save(update_fields=["rows", "errors", "sha256", "extraction"])
        return Response(representation(row))


def queue_automatic_ocr(row, actor):
    extraction = row.extraction or {}
    if (
        row.resource != "knowledge"
        or row.source_url
        or row.status != "preview"
        or extraction.get("safe_for_ocr") is not True
    ):
        return
    if extraction.get("format") not in {"png", "pdf", "docx"}:
        return
    needs_ocr = (
        extraction.get("format") == "png"
        or extraction.get("image_count", 0) > 0
        or bool(extraction.get("failures"))
        or not any(segment.get("text", "").strip() for segment in extraction.get("segments", []))
    )
    if not needs_ocr or extraction.get("ocr", {}).get("status") in {"queued", "running", "completed", "failed"}:
        return
    if not permitted(row, actor):
        return
    try:
        request_ocr(row, actor)
    except (OcrUnavailable, ValidationError):
        row.extraction = {
            **row.extraction,
            "ocr": {
                "token": "",
                "status": "failed",
                "segments": [],
                "failures": [],
                "requires_review": True,
                "reviewed": False,
                "error": "自动文字识别暂不可用，请稍后重试。",
            },
        }
        row.save(update_fields=["extraction"])
