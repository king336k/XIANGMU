# SPDX-License-Identifier: AGPL-3.0-only
import base64
import os
import uuid
from pathlib import Path
from django.conf import settings
from django.http import FileResponse
from rest_framework.exceptions import PermissionDenied
import hashlib
import json
import re
from urllib.parse import urlsplit
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
import requests
from .models import DocumentImport, DocumentFile, Requirement, Release
from .views import QualityView, Conflict
from .requirements import RequirementInput, snapshot
from .connection_settings import read_connection
from .platform import PlatformUnavailable
from plane.knowledge.models import Article
from plane.knowledge.serializers import ArticleInput
from plane.knowledge.retrieval import scan_content
from plane.db.models import Issue
from html import escape
from .permissions import capable, writable_member
from .document_parser import extract_local, MAX_UPLOAD


class VersionInput(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    version = serializers.CharField(max_length=120)
    description = serializers.CharField(max_length=10000, allow_blank=True, default="")


def sensitive_content(value):
    # Scan both JSON key/value semantics and actual string lines: JSON's literal
    # \\n before a credential key must not hide the key behind a word character.
    if scan_content(json.dumps(value, ensure_ascii=False)):
        return True
    if isinstance(value, str):
        return bool(scan_content(value))
    if isinstance(value, dict):
        return any(sensitive_content(item) for item in value.values())
    if isinstance(value, list):
        return any(sensitive_content(item) for item in value)
    return False


def extracted_parts(extraction):
    for segment in extraction.get("segments", []):
        if not segment["text"].strip():
            continue
        if extraction.get("format") == "feishu_docx":
            locator = segment.get("locator") or f"飞书内容块 {segment.get('block_id', '')}"
        elif "page" in segment:
            locator = f"PDF 第{segment['page']}页"
        elif segment.get("part") and segment.get("paragraph"):
            locator = f"DOCX {segment['part']}，第{segment['paragraph']}段"
            if segment.get("source_image"):
                locator += f"，{segment['source_image']}"
        else:
            locator = f"图片 {segment.get('source_image', '原件')}"
        if segment.get("method") == "ocr_reviewed":
            locator += " · OCR人工核对"
        yield locator, segment["text"]


def extracted_content(extraction):
    return "\n\n".join(f"【来源：{locator}】\n{text}" for locator, text in extracted_parts(extraction))


def validate(resource, rows):
    errors = []
    normalized = []
    schema = {
        "requirements": RequirementInput,
        "knowledge": ArticleInput,
        "versions": VersionInput,
    }[resource]
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            errors.append({"row": index, "error": "条目必须是JSON对象。"})
            continue
        if sensitive_content(row):
            errors.append({"row": index, "error": "文档中含疑似敏感信息，请脱敏后重新导入。"})
            continue
        validator = schema(data=row)
        unknown = set(row) - set(validator.fields)
        if unknown:
            errors.append(
                {
                    "row": index,
                    "error": "条目含不支持的字段：" + ",".join(sorted(unknown)),
                }
            )
            continue
        if not validator.is_valid():
            errors.append({"row": index, "fields": validator.errors})
            continue
        data = validator.validated_data
        data.pop("expected_version", None)
        if data.get("source_issue_id"):
            errors.append(
                {
                    "row": index,
                    "error": "文档导入不自动关联已有工作项，请导入后明确设置。",
                }
            )
            continue
        normalized.append(data)
    return errors, json.loads(json.dumps(normalized, default=str))


def file_representation(row):
    project = row.project
    base = f"/api/workspaces/{project.workspace.slug}/projects/{project.id}/quality/document-files/{row.id}/"
    return {
        "id": str(row.id),
        "name": row.name,
        "kind": row.kind,
        "size": row.size,
        "sha256": row.sha256,
        "download_url": base,
        "preview_url": base + "?preview=1" if row.kind == "image" or row.name.lower().endswith(".png") else None,
    }


def representation(row):
    return {
        "id": str(row.id),
        "resource": row.resource,
        "name": row.name,
        "source_url": row.source_url,
        "valid": not row.errors,
        "errors": row.errors,
        "rows": row.rows,
        "status": row.status,
        "object_ids": row.object_ids,
        "extraction": row.extraction,
        "files": [file_representation(f) for f in row.files.all()],
    }


def save_preview(view, resource, name, rows, source_url="", original=None, extraction=None):
    if resource not in ["requirements", "knowledge", "versions"]:
        raise ValidationError({"resource": "不支持的文档目标模块。"})
    if not isinstance(rows, list) or len(rows) > 500 or (not rows and not extraction):
        raise ValidationError({"file": "文档须包含1至500条内容。"})
    errors, normalized = validate(resource, rows)
    if extraction:
        errors.extend(
            {
                "row": 1,
                "error": f["error"],
                "range": {k: v for k, v in f.items() if k != "error"},
            }
            for f in extraction.get("failures", [])
        )
    if resource == "versions":
        for index, item in enumerate(normalized, 1):
            if Release.objects.filter(project_id=view.project_id, version=item["version"]).exists():
                errors.append({"row": index, "error": "当前项目已存在此版本，请在原版本中维护。"})
    project = view.project()
    type(project).objects.select_for_update().get(pk=project.pk)
    digest = hashlib.sha256(
        json.dumps(
            {
                "rows": normalized,
                "errors": errors,
                "source_url": source_url,
                "original_sha256": (hashlib.sha256(original).hexdigest() if original is not None else None),
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()
    existing = DocumentImport.objects.filter(project=project, resource=resource, sha256=digest).first()
    if existing:
        return Response(representation(existing))
    row = DocumentImport.objects.create(
        project=project,
        created_by=view.request.user,
        resource=resource,
        name=name[:255],
        source_url=source_url,
        rows=normalized,
        errors=errors,
        sha256=digest,
        extraction={key: value for key, value in (extraction or {}).items() if key != "attachments"},
    )
    if original is not None:
        entries = [{"name": name, "kind": "original", "raw": original}]
        entries.extend(
            {"name": a["name"], "kind": a["kind"], "raw": base64.b64decode(a["data"])}
            for a in (extraction or {}).get("attachments", [])
        )
        save_files(row, view.request.user, entries)
    return Response(representation(row), status=201)


def private_directory():
    root = Path(getattr(settings, "QUALITY_ATTACHMENT_ROOT", "/code/quality-attachments")) / "document-imports"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root.resolve()


def safe_name(name):
    return re.sub(r"[\x00-\x1f\x7f/\\]", "_", name).strip(". ")[:255] or "document.bin"


def save_files(row, user, entries):
    paths = []
    try:
        for item in entries:
            key = uuid.uuid4().hex + ".bin"
            path = private_directory() / key
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            paths.append(path)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(item["raw"])
                handle.flush()
                os.fsync(handle.fileno())
            DocumentFile.objects.create(
                project=row.project,
                created_by=user,
                document_import=row,
                name=safe_name(item["name"]),
                kind=item["kind"],
                size=len(item["raw"]),
                sha256=hashlib.sha256(item["raw"]).hexdigest(),
                storage_key=key,
            )
    except BaseException:
        for path in paths:
            path.unlink(missing_ok=True)
        raise


def require_document_editor(view, resource):
    capability = "knowledge_edit" if resource == "knowledge" else "manage_test"
    if not writable_member(view.project_id, view.request.user.id, view.workspace_slug) or not capable(
        view.project_id, view.request.user.id, capability
    ):
        raise PermissionDenied("当前业务角色不允许访问此文档原件。")


class DocumentImports(QualityView):
    def get(self, request, **kwargs):
        rows = DocumentImport.objects.filter(project=self.project())
        resources = [
            r
            for r in ("knowledge", "requirements", "versions")
            if writable_member(self.project_id, request.user.id, self.workspace_slug)
            and capable(
                self.project_id,
                request.user.id,
                "knowledge_edit" if r == "knowledge" else "manage_test",
            )
        ]
        return Response([representation(row) for row in rows.filter(resource__in=resources)[:100]])

    @transaction.atomic
    def post(self, request, **kwargs):
        upload = request.FILES.get("file")
        resource = request.data.get("resource")
        if resource not in ["knowledge", "requirements", "versions"]:
            raise ValidationError({"resource": "不支持的文档目标模块。"})
        extension = Path(upload.name).suffix.lower() if upload else ""
        limit = MAX_UPLOAD if resource == "knowledge" and extension in {".docx", ".pdf", ".png"} else 2 * 1024 * 1024
        if not upload or upload.size > limit:
            raise ValidationError({"file": "DOCX/PDF最大20MiB，文本/JSON最大2MiB。"})
        raw = upload.read(limit + 1)
        if len(raw) > limit:
            raise ValidationError({"file": "文件超过允许大小。"})
        extraction = None
        if resource == "knowledge" and extension == ".png":
            from .attachments import image_type

            if image_type(raw[:16], upload.name) != "image/png":
                raise ValidationError({"file": "文件不是有效的PNG图片。"})
            extraction = {
                "format": "png",
                "safe_for_ocr": True,
                "segments": [],
                "attachments": [],
                "image_count": 1,
                "attachment_count": 0,
                "failures": [{"range": "document", "error": "请识别图片文字并核对后再导入。"}],
            }
            rows = []
        elif resource == "knowledge" and extension in {".docx", ".pdf"}:
            extraction = extract_local(raw, extension)
            extraction["image_count"] = sum(a["kind"] == "image" for a in extraction.get("attachments", []))
            extraction["attachment_count"] = sum(a["kind"] == "attachment" for a in extraction.get("attachments", []))
            text = extracted_content(extraction)
            rows = [{"title": Path(upload.name).stem[:255], "content": text}] if text.strip() else []
        else:
            try:
                text = raw.decode("utf-8-sig")
                if extension == ".json":
                    rows = json.loads(text)
                elif resource == "knowledge" and extension in {".txt", ".md"}:
                    title = next(
                        (line.lstrip("# ").strip() for line in text.splitlines() if line.strip()),
                        upload.name,
                    )[:255]
                    rows = [{"title": title, "content": text}]
                else:
                    raise ValidationError(
                        {
                            "file": "知识支持DOCX、PDF、Markdown、TXT、JSON；需求和版本使用JSON数组。"
                            "旧DOC暂不支持；扫描PDF或PNG可预检后识别图片文字。"
                        }
                    )
            except (ValueError, UnicodeDecodeError):
                raise ValidationError({"file": "文件不是有效的UTF-8文本或JSON。"})
        return save_preview(self, resource, upload.name, rows, original=raw, extraction=extraction)


def verified_file_handle(row):
    path = private_directory() / row.storage_key
    if path.parent != private_directory() or path.is_symlink():
        raise Conflict("文档原件存储位置无效。")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        handle = os.fdopen(descriptor, "rb")
    except OSError:
        raise Conflict("文档原件暂不可用。")
    try:
        digest = hashlib.sha256()
        size = 0
        for block in iter(lambda: handle.read(64 * 1024), b""):
            size += len(block)
            digest.update(block)
        if size != row.size or digest.hexdigest() != row.sha256:
            raise Conflict("文档文件完整性校验失败，请重新导入。")
        handle.seek(0)
        return handle
    except BaseException:
        handle.close()
        raise


class DocumentFileDownload(QualityView):
    def get(self, request, pk, **kwargs):
        row = self.obj(DocumentFile, pk)
        require_document_editor(self, row.document_import.resource)
        handle = verified_file_handle(row)
        kind = None
        if request.query_params.get("preview") == "1":
            from .attachments import image_type

            kind = (
                image_type(handle.read(16), row.name)
                if row.kind == "image" or row.name.lower().endswith(".png")
                else None
            )
            handle.seek(0)
            if not kind:
                handle.close()
                raise ValidationError({"file": "此附件仅支持下载核对。"})
        response = FileResponse(
            handle,
            as_attachment=not bool(kind),
            filename=safe_name(row.name),
            content_type=kind or "application/octet-stream",
        )
        response["X-Content-Type-Options"] = "nosniff"
        response["Cache-Control"] = "private, no-store"
        response["Content-Security-Policy"] = "default-src 'none'; sandbox"
        return response


class DocumentConfirm(QualityView):
    @transaction.atomic
    def post(self, request, pk, **kwargs):
        row = get_object_or_404(
            DocumentImport.objects.select_for_update(),
            pk=pk,
            project_id=self.project_id,
        )
        if row.status == "confirmed":
            return Response(representation(row))
        if row.extraction.get("ocr", {}).get("requires_review"):
            raise ValidationError({"ocr": "请先对照原件核对识别文字并采用核对结果。"})
        errors, rows = validate(row.resource, row.rows)
        if row.errors or errors:
            raise ValidationError({"errors": row.errors or errors})
        for source_file in row.files.all():
            verified_file_handle(source_file).close()
        ids = []
        for item in rows:
            if row.resource == "knowledge":
                obj = Article.objects.create(project=row.project, created_by=request.user, **item)
            elif row.resource == "requirements":
                title = item.pop("title")
                description = item.pop("description")
                priority = item.pop("priority")
                issue = Issue.objects.create(
                    project=row.project,
                    workspace=row.project.workspace,
                    created_by=request.user,
                    name=title,
                    description_html="<p>" + escape(description).replace("\n", "<br>\n") + "</p>",
                    priority=priority,
                )
                obj = Requirement.objects.create(project=row.project, created_by=request.user, issue=issue, **item)
                snapshot(obj, request.user, "create", "文档导入：" + row.name)
            else:
                if Release.objects.filter(project=row.project, version=item["version"]).exists():
                    raise ValidationError({"version": "此版本已在导入预检后被创建，请重新核对。"})
                obj = Release.objects.create(project=row.project, created_by=request.user, **item)
            ids.append(str(obj.issue_id if row.resource == "requirements" else obj.id))
        row.object_ids = ids
        row.status = "confirmed"
        row.save()
        return Response(representation(row), status=201)


class FeishuInput(serializers.Serializer):
    resource = serializers.ChoiceField(choices=["knowledge", "requirements"])
    source_instance = serializers.RegexField(r"^[a-zA-Z0-9_-]{1,80}$")
    url = serializers.CharField(max_length=1000)

    def validate_url(self, value):
        parts = urlsplit(value)
        if (
            parts.scheme != "https"
            or not parts.hostname
            or not parts.hostname.endswith(".feishu.cn")
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
            or not re.fullmatch(r"/(?:wiki|docx)/[a-zA-Z0-9]+/?", parts.path)
        ):
            raise ValidationError("请输入飞书官方知识库或新版文档链接，不接受任意地址。")
        return value


def feishu_get(config, path):
    if not re.fullmatch(
        r"/open-apis/(?:wiki/v2/spaces/get_node\?token=[a-zA-Z0-9]+|"
        r"docx/v1/documents/[a-zA-Z0-9]+(?:/blocks(?:/[a-zA-Z0-9_-]+/children)?|/raw_content)"
        r"(?:\?[a-zA-Z0-9_=&%.-]+)?)",
        path,
    ):
        raise PlatformUnavailable("飞书读取路径无效。")
    try:
        with requests.get(
            "https://open.feishu.cn" + path,
            headers={"Authorization": "Bearer " + config["service_token"]},
            timeout=(3, 8),
            allow_redirects=False,
            stream=True,
        ) as response:
            if response.status_code != 200:
                raise PlatformUnavailable()
            raw = bytearray()
            for chunk in response.iter_content(65536):
                raw.extend(chunk)
                if len(raw) > 2 * 1024 * 1024:
                    raise PlatformUnavailable()
        payload = json.loads(raw)
        if not isinstance(payload, dict) or payload.get("code") != 0 or not isinstance(payload.get("data"), dict):
            raise PlatformUnavailable()
        return payload["data"]
    except (requests.RequestException, ValueError, TypeError, KeyError):
        raise PlatformUnavailable("飞书文档读取失败，请核对连接凭据和文档授权。")


class FeishuDocumentImport(QualityView):
    @transaction.atomic
    def post(self, request, **kwargs):
        data = self.input(FeishuInput)
        config = read_connection(data["source_instance"])
        if (
            not config
            or config.get("kind") != "feishu"
            or urlsplit(config.get("base_url", "")).hostname != "open.feishu.cn"
            or not config.get("service_token")
        ):
            raise PlatformUnavailable("飞书读取连接尚未配置或未授权，可先导入导出的文本/Markdown文件。")
        parts = urlsplit(data["url"])
        token = parts.path.strip("/").split("/")[-1]
        title = "飞书导入文档"
        if "/wiki/" in parts.path:
            node = feishu_get(config, "/open-apis/wiki/v2/spaces/get_node?token=" + token).get("node")
            if not isinstance(node, dict):
                raise PlatformUnavailable("飞书文档定位结果无效，请核对授权。")
            if node.get("obj_type") != "docx":
                raise ValidationError({"url": "当前支持飞书新版文档；其他类型请先导出文本。"})
            token = node.get("obj_token", "")
            title = str(node.get("title") or title)[:255]
        if not isinstance(token, str) or not re.fullmatch(r"[a-zA-Z0-9]+", token):
            raise PlatformUnavailable()
        from .feishu_document_blocks import read_document, FeishuTransport

        transport = FeishuTransport(config["service_token"])
        try:
            document = read_document(token, transport.get_json, transport.download)
        finally:
            transport.close()
        failures = list(document.get("failures", []))
        extraction = {k: document[k] for k in ["format", "document_id", "segments"] if k in document}
        extraction.update(
            format="feishu_docx",
            blocks_read=len(document.get("blocks", [])),
            segment_count=len(document.get("segments", [])),
            failures=failures,
            image_count=0,
            attachment_count=0,
            attachments=[],
            safe_for_ocr=False,
        )
        media = []
        extraction["segments"] = [
            {k: s[k] for k in ["block_id", "kind", "locator", "text"] if k in s} for s in document.get("segments", [])
        ]
        for item in document.get("attachments", []):
            raw = item["raw"]
            if not isinstance(raw, bytes) or not 0 < len(raw) <= 20 * 1024 * 1024:
                raise ValidationError({"file": "飞书素材未完整读取。"})
            digest = hashlib.sha256(raw).hexdigest()
            if item.get("size") != len(raw) or item.get("sha256") != digest:
                raise ValidationError({"file": "飞书素材完整性校验失败。"})
            kind = item.get("kind")
            if kind not in {"image", "attachment"}:
                raise ValidationError({"file": "飞书素材类型无效。"})
            name = safe_name(item.get("name", "document.bin"))
            if kind == "image":
                signatures = [
                    (".png", lambda: raw.startswith(b"\x89PNG\r\n\x1a\n")),
                    (".jpg", lambda: raw.startswith(b"\xff\xd8\xff")),
                    (".gif", lambda: raw.startswith((b"GIF87a", b"GIF89a"))),
                    (".webp", lambda: raw[:4] == b"RIFF" and raw[8:12] == b"WEBP"),
                ]
                suffix = next((suffix for suffix, check in signatures if check()), None)
                if not suffix:
                    failures.append(
                        {
                            "block_id": item.get("block_id", ""),
                            "stage": "image",
                            "error": "图片格式未能安全确认，请下载原件核对。",
                        }
                    )
                    kind = "attachment"
                elif not name.lower().endswith(suffix):
                    name += suffix
            extraction["image_count" if kind == "image" else "attachment_count"] += 1
            extraction["attachments"].append({"name": name, "kind": kind, "data": base64.b64encode(raw).decode()})
            media.append(
                {"block_id": item.get("block_id"), "kind": kind, "name": name, "size": len(raw), "sha256": digest}
            )
        if sum(x["size"] for x in media) > 40 * 1024 * 1024:
            raise ValidationError({"file": "飞书素材总量超过40MiB，请拆分文档。"})
        extraction["files_complete"] = not failures

        # Persist a canonical credential-free source snapshot. Media bytes/token
        # never enter a public preview; their identities cover the import digest.
        def sanitized(value):
            if isinstance(value, dict):
                return {
                    key: sanitized(child)
                    for key, child in value.items()
                    if key not in {"token", "file_token", "image_token", "raw", "service_token", "authorization"}
                }
            if isinstance(value, list):
                return [sanitized(child) for child in value]
            return value

        snapshot = sanitized(
            {
                "format": "feishu_docx",
                "document_id": token,
                "blocks": document.get("blocks", []),
                "segments": document.get("segments", []),
                "media": media,
                "failures": failures,
            }
        )
        if sensitive_content(snapshot):
            raise ValidationError({"file": "飞书文档含疑似敏感信息，请脱敏后重新读取。"})
        snapshot_bytes = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        content = extracted_content(extraction)
        if not content.strip() and not failures:
            raise ValidationError({"url": "文档没有可导入的文字。"})
        if data["resource"] == "requirements" and len(content) > 20000:
            raise ValidationError({"url": "需求文档超过20000字，请按章节导出为多个需求条目，避免丢失内容。"})
        rows = (
            [{"title": title, "content": content}]
            if data["resource"] == "knowledge"
            else [{"title": title, "description": content[:20000], "acceptance": ""}]
        )
        return save_preview(
            self, data["resource"], title, rows, data["url"], original=snapshot_bytes, extraction=extraction
        )
