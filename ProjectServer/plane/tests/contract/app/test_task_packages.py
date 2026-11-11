"""Unsigned legacy task archives are quarantined and never import trusted test verdicts."""

import hashlib
import io
import json
import zipfile
from uuid import uuid4
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from plane.db.models import Project, ProjectMember
from plane.quality.models import TestPlan

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def package(task=None, extra=None, corrupt=False):
    task = task or {
        "task_uuid": str(uuid4()),
        "name": "现场任务",
        "target_version": "v2",
        "cases": [
            {
                "scenario": "上传验证",
                "module": "采集",
                "steps": ["打开上传页", "提交日志"],
                "expected_result": "提交成功",
                "priority": "P1",
                "result": "PASS",
                "actual_result": "旧环境结果",
            }
        ],
    }
    payload = json.dumps(
        {"task": task, "issues": []}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    manifest = {
        "format": "release-test-platform-task-package",
        "manifest_version": 1,
        "package_uuid": str(uuid4()),
        "source_signed": False,
        "entries": {
            "data/task.json": {
                "sha256": ("0" * 64 if corrupt else hashlib.sha256(payload).hexdigest()),
                "size": len(payload),
                "media_type": "application/json",
            }
        },
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, sort_keys=True, separators=(",", ":")))
        archive.writestr("data/task.json", payload)
        if extra:
            archive.writestr(extra, b"not-executed")
    return SimpleUploadedFile("task.zip", output.getvalue(), content_type="application/zip")


@pytest.fixture
def packages(workspace, create_user):
    p = Project.objects.create(workspace=workspace, name="任务包导入", identifier="PKG")
    ProjectMember.objects.create(project=p, member=create_user, role=20)
    return f"/api/workspaces/{workspace.slug}/projects/{p.id}/quality/", p


def test_task_package_preflight_confirm_is_idempotent_and_old_results_not_trusted(session_client, packages):
    base, project = packages
    preview = session_client.post(base + "task-packages/", {"file": package()}, format="multipart")
    assert preview.status_code == 201, preview.content
    assert preview.data["status"] == "validated" and preview.data["source_signed"] is False
    assert TestPlan.objects.filter(project=project).count() == 0
    confirmed = session_client.post(
        base + f"task-packages/{preview.data['id']}/confirm/", {"acknowledged": True}, format="json"
    )
    assert confirmed.status_code == 201, confirmed.content
    plan = confirmed.data["plan"]
    assert plan["summary"]["executed"] == 0 and plan["status"] == "pending"
    assert plan["items"][0]["revision"]["snapshot"]["steps"][0]["action"] == "打开上传页"
    retry = session_client.post(
        base + f"task-packages/{preview.data['id']}/confirm/", {"acknowledged": True}, format="json"
    )
    assert retry.status_code == 200 and retry.data["plan"]["id"] == plan["id"]


@pytest.mark.parametrize("extra,corrupt", [("../evil.py", False), ("script.py", False), (None, True)])
def test_bad_archives_rejected_without_importing_data(session_client, packages, extra, corrupt):
    base, project = packages
    response = session_client.post(
        base + "task-packages/", {"file": package(extra=extra, corrupt=corrupt)}, format="multipart"
    )
    assert response.status_code == 400, response.content
    assert TestPlan.objects.filter(project=project).count() == 0


def test_guest_cannot_upload_or_confirm_unsigned_task_archive(session_client, packages, create_user):
    base, project = packages
    ProjectMember.objects.filter(project=project, member=create_user).update(role=5)
    assert session_client.post(base + "task-packages/", {"file": package()}, format="multipart").status_code == 403
