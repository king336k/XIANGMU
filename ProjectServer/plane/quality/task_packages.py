# SPDX-License-Identifier: AGPL-3.0-only
"""Quarantine unsigned legacy RTP task snapshots as new native plans, never import verdicts."""

import hashlib
import io
import json
import stat
import zipfile
from uuid import UUID
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from .models import TaskPackageImport, TestCase, TestPlan, PlanItem
from .serializers import PlanSerializer
from .imports import validate_rows
from .views import QualityView, Conflict, add_revision, plan_queryset

LIMIT = 20 * 1024 * 1024


def parse_archive(raw):
    if len(raw) > LIMIT:
        raise ValidationError({"file": "任务包不能超过20MB。"})
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            if sorted(row.filename for row in infos) != ["data/task.json", "manifest.json"]:
                raise ValueError("任务包只能包含manifest.json和data/task.json。")
            for row in infos:
                if (
                    row.flag_bits & 1
                    or stat.S_IFMT(row.external_attr >> 16) not in {0, stat.S_IFREG}
                    or row.file_size > 4 * 1024 * 1024
                    or row.file_size / max(1, row.compress_size) > 100
                ):
                    raise ValueError("成员类型、大小或压缩比不合法。")
            manifest = json.loads(archive.read("manifest.json"))
            task_raw = archive.read("data/task.json")
            payload = json.loads(task_raw)
        if not isinstance(manifest, dict) or not isinstance(payload, dict):
            raise ValueError("JSON结构无效。")
        if (
            manifest.get("format") != "release-test-platform-task-package"
            or manifest.get("manifest_version") != 1
            or manifest.get("source_signed") is not False
        ):
            raise ValueError("任务包格式不兼容。")
        package_uuid = UUID(str(manifest["package_uuid"]))
        entry = manifest["entries"]["data/task.json"]
        if (
            entry.get("sha256") != hashlib.sha256(task_raw).hexdigest()
            or entry.get("size") != len(task_raw)
            or entry.get("media_type") != "application/json"
        ):
            raise ValueError("任务包清单哈希、大小或类型校验失败。")
        task = payload.get("task")
        if not isinstance(task, dict):
            raise ValueError("缺少任务快照。")
        UUID(str(task.get("task_uuid")))
        cases = task.get("cases")
        if not isinstance(cases, list) or not 0 < len(cases) <= 500:
            raise ValueError("任务包须有1至500条用例。")
        rows = []
        for case in cases:
            if not isinstance(case, dict):
                raise ValueError("用例结构无效。")
            steps = case.get("steps") or []
            if not isinstance(steps, list):
                raise ValueError("测试步骤必须为数组。")
            normalized = []
            for step in steps:
                if isinstance(step, str):
                    normalized.append({"action": step, "expected": case.get("expected_result") or "符合验收标准"})
                elif isinstance(step, dict):
                    normalized.append(
                        {
                            "action": step.get("action") or step.get("step") or step.get("description") or "",
                            "expected": step.get("expected")
                            or step.get("expected_result")
                            or case.get("expected_result")
                            or "",
                        }
                    )
                else:
                    raise ValueError("测试步骤结构无效。")
            rows.append(
                {
                    "title": case.get("scenario") or case.get("title") or "导入验证场景",
                    "module": case.get("module") or "",
                    "preconditions": case.get("prerequisites") or "",
                    "priority": {
                        "P0": "high",
                        "P1": "high",
                        "P2": "medium",
                        "P3": "low",
                        1: "high",
                        2: "medium",
                        3: "low",
                    }.get(
                        case.get("priority"),
                        case.get("priority") if case.get("priority") in ["high", "medium", "low"] else "medium",
                    ),
                    "steps": normalized,
                }
            )
        return package_uuid, payload, rows
    except (
        ValueError,
        KeyError,
        TypeError,
        UnicodeDecodeError,
        zipfile.BadZipFile,
        RuntimeError,
        NotImplementedError,
    ) as exc:
        raise ValidationError({"file": str(exc)[:300] or "任务包不可解析。"})


def preview(row):
    task = row.payload["task"]
    return {
        "id": str(row.id),
        "status": row.status,
        "package_uuid": str(row.package_uuid),
        "source_signed": False,
        "name": task.get("name") or "导入测试任务",
        "case_count": len(row.rows),
        "warnings": ["此包没有可信签名，只导入验证场景；原执行结果、准入结论和权限不继承。"],
        "plan": PlanSerializer(plan_queryset().get(pk=row.plan_id)).data if row.plan_id else None,
    }


class TaskPackages(QualityView):
    def get(self, request, **kwargs):
        return Response([preview(row) for row in TaskPackageImport.objects.filter(project=self.project())[:100]])

    @transaction.atomic
    def post(self, request, **kwargs):
        upload = request.FILES.get("file") or request.FILES.get("package")
        if not upload or upload.size > LIMIT:
            raise ValidationError({"file": "请选择20MB以内的任务ZIP包。"})
        raw = upload.read(LIMIT + 1)
        package_uuid, payload, rows = parse_archive(raw)
        errors, normalized = validate_rows(rows, self.project_id)
        if errors:
            raise ValidationError({"rows": errors})
        project = self.project()
        type(project).objects.select_for_update().get(pk=project.pk)
        digest = hashlib.sha256(raw).hexdigest()
        existing = TaskPackageImport.objects.filter(project=project, package_uuid=package_uuid).first()
        if existing:
            if existing.sha256 != digest:
                raise Conflict("相同包编号对应不同内容，拒绝覆盖。")
            return Response(preview(existing))
        existing = TaskPackageImport.objects.filter(project=project, sha256=digest).first()
        if existing:
            return Response(preview(existing))
        row = TaskPackageImport.objects.create(
            project=project,
            created_by=request.user,
            package_uuid=package_uuid,
            sha256=digest,
            payload=payload,
            rows=rows,
        )
        return Response(preview(row), status=201)


class ConfirmInput(serializers.Serializer):
    acknowledged = serializers.BooleanField()
    build = serializers.CharField(max_length=120, required=False)
    environment = serializers.CharField(max_length=255, default="导入后待确认")


class TaskPackageConfirm(QualityView):
    @transaction.atomic
    def post(self, request, pk, **kwargs):
        data = self.input(ConfirmInput)
        if not data["acknowledged"]:
            raise ValidationError({"acknowledged": "确认不继承原始执行与准入结论后再导入。"})
        row = get_object_or_404(TaskPackageImport.objects.select_for_update(), pk=pk, project_id=self.project_id)
        if row.status == "imported":
            return Response(preview(row))
        errors, rows = validate_rows(row.rows, self.project_id)
        if errors:
            raise ValidationError({"rows": errors})
        task = row.payload["task"]
        build = data.get("build") or str(task.get("target_version") or "待确认版本")[:120]
        plan = TestPlan.objects.create(
            project=row.project,
            created_by=request.user,
            name=str(task.get("name") or "导入测试任务")[:255],
            build=build,
            environment=data["environment"],
            description=f"来自任务包{row.package_uuid}；来源结论仅留在原包审计，不作为新版通过依据。",
            managed=True,
        )
        for values in rows:
            case = TestCase.objects.create(project=row.project, created_by=request.user, **values)
            revision = add_revision(case, request.user)
            PlanItem.objects.create(
                project=row.project, created_by=request.user, plan=plan, case=case, revision=revision
            )
        row.plan = plan
        row.status = "imported"
        row.confirmed_at = timezone.now()
        row.save()
        return Response(preview(row), status=201)
