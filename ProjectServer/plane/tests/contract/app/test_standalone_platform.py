"""Independent accounts and DAQ feedback must work with no data-platform service."""

import json
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from plane.db.models import Project, User
from plane.license.models import Instance, InstanceAdmin, InstanceConfiguration
from plane.quality.models import PlatformAccount, PlatformIdentity, PlatformProject, Defect
from plane.tests.contract.app.test_daq_incidents import signature

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def standalone(workspace, settings, mocker):
    # Accepted feedback now requires a configured, legal triage administrator.
    admin = User.objects.create(username="standalone-triage", email="standalone-triage@test.invalid")
    instance = Instance.objects.create(
        instance_name="standalone-triage",
        instance_id=str(uuid4()),
        current_version="test",
        last_checked_at=timezone.now(),
        is_setup_done=True,
    )
    InstanceAdmin.objects.create(instance=instance, user=admin)
    project = Project.objects.create(workspace=workspace, name="独立反馈项目", identifier="SOLO")
    settings.QUALITY_DAQ_REPORT_KEYS = {
        "test-incidents": {
            "secret": "synthetic-incidents-only",
            "audience": "plane-quality",
            "source_instance": "daq-device",
            "projects": [str(project.id)],
        }
    }
    InstanceConfiguration.objects.create(
        key="QUALITY_DAQ_PROJECT_GRANTS", value=json.dumps({"projects": [str(project.id)], "revision": 1})
    )
    upstream = mocker.patch("plane.quality.platform.fetch", side_effect=AssertionError("no upstream calls"))
    return project, upstream


def call(path, payload=None, actor=16):
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) if payload is not None else ""
    method = "POST" if payload is not None else "GET"
    return getattr(APIClient(), method.lower())(
        path,
        body if payload is not None else None,
        content_type="application/json",
        **signature(path, body, actor=actor, method=method),
    )


def report(project):
    return {
        "hubProjectId": str(project.id),
        "eventId": str(uuid4()),
        "kind": "startup_failure",
        "occurredAt": timezone.now().isoformat(),
        "title": "独立DAQ故障",
        "description": "未选择采集任务时也可上报；包含完整现场描述",
        "device": "robot-1",
    }


def test_daq_report_preserves_actor_without_creating_login_identity(standalone):
    project, upstream = standalone
    before = User.objects.filter(is_bot=False).count()
    response = call("/api/quality-auth/daq-reports/", report(project))
    assert response.status_code == 201, response.content
    assert response.data["reporter"]["username"] == "test-collector"
    assert User.objects.filter(is_bot=False).count() == before
    assert not PlatformAccount.objects.exists()
    assert not PlatformIdentity.objects.exists()
    assert not PlatformProject.objects.exists()
    defect = Defect.objects.get(pk=response.data["issueId"])
    assert defect.created_by.is_bot and not defect.created_by.has_usable_password()
    assert response.data["capabilities"]["canLoginPlatform"] is False
    upstream.assert_not_called()


def test_daq_history_is_isolated_by_signed_actor(standalone):
    project, upstream = standalone
    created = call("/api/quality-auth/daq-reports/", report(project))
    assert created.status_code == 201, created.content
    detail = f"/api/quality-auth/daq-reports/{created.data['issueId']}/"
    assert call(detail).status_code == 200
    assert call(detail, actor=17).status_code in {403, 404}
    assert call("/api/quality-auth/daq-reports/").data["count"] == 1
    assert call("/api/quality-auth/daq-reports/", actor=17).data["count"] == 0
    upstream.assert_not_called()


def test_daq_key_only_allows_configured_destinations(standalone):
    project, upstream = standalone
    other = Project.objects.create(workspace=project.workspace, name="不可见", identifier="OTHER")
    assert call("/api/quality-auth/daq-reports/", report(other)).status_code == 403
    options = call("/api/quality-auth/daq-project-options/")
    assert options.status_code == 200, options.content
    assert [row["hubProjectId"] for row in options.data["results"]] == [str(project.id)]
    upstream.assert_not_called()


@pytest.mark.parametrize("path", ["data-login/", "legacy-login/", "data-sources/", "legacy-sources/", "daq-project/"])
def test_external_account_routes_are_removed(path):
    assert APIClient().get("/api/quality-auth/" + path).status_code == 404


def test_bootstrap_admin_is_idempotent_and_keeps_changed_password():
    call_command("bootstrap_project_admin")
    user = User.objects.get(username="admin")
    assert InstanceAdmin.objects.filter(user=user).exists()
    assert Instance.objects.get().is_setup_done
    user.set_password("changed-by-owner")
    user.save()
    call_command("bootstrap_project_admin")
    user.refresh_from_db()
    assert user.check_password("changed-by-owner")
    assert User.objects.filter(username="admin").count() == 1


def test_daq_grants_require_administrator_and_apply_to_every_device(standalone, create_user):
    project, upstream = standalone
    path = "/api/quality-auth/daq-project-grants/"
    client = APIClient()
    client.force_authenticate(create_user)
    assert client.get(path).status_code == 403
    instance = Instance.objects.get()
    InstanceAdmin.objects.create(instance=instance, user=create_user)
    loaded = client.get(path)
    assert loaded.status_code == 200, loaded.content
    revoked = client.post(path, {"projects": [], "expected_revision": loaded.data["revision"]}, format="json")
    assert revoked.status_code == 200, revoked.content
    assert call("/api/quality-auth/daq-project-options/").data["count"] == 0
    assert call("/api/quality-auth/daq-reports/", report(project)).status_code == 403
    assert (
        client.post(
            path, {"projects": [str(project.id)], "expected_revision": loaded.data["revision"]}, format="json"
        ).status_code
        == 409
    )
    assert (
        client.post(
            path, {"projects": [str(project.id)], "expected_revision": revoked.data["revision"]}, format="json"
        ).status_code
        == 200
    )
    assert call("/api/quality-auth/daq-project-options/", actor=17).data["count"] == 1
    upstream.assert_not_called()


def test_local_login_never_queries_external_directories(mocker):
    Instance.objects.create(
        instance_name="独立平台",
        instance_id=str(uuid4()),
        current_version="test",
        last_checked_at=timezone.now(),
        is_setup_done=True,
    )
    user = User.objects.create(username="independent", email="independent@example.invalid", is_active=True)
    user.set_password("local-only-password")
    user.save()
    upstream = mocker.patch("plane.quality.platform.fetch", side_effect=AssertionError("no external directory"))
    client = APIClient()
    response = client.post(
        "/api/quality-auth/login/", {"username": user.username, "password": "local-only-password"}, format="json"
    )
    assert response.status_code == 200, response.content
    assert client.session["_auth_user_id"] == str(user.id)
    upstream.assert_not_called()


def test_signed_actor_cannot_login_or_replay_a_request(standalone):
    project, _ = standalone
    payload = report(project)
    path = "/api/quality-auth/daq-reports/"
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    headers = signature(path, raw)
    client = APIClient()
    assert client.post(path, raw, content_type="application/json", **headers).status_code == 201
    assert client.post(path, raw, content_type="application/json", **headers).status_code == 403
    assert client.get("/api/users/me/", **signature("/api/users/me/", "", method="GET")).status_code in {401, 403}
    assert client.post(
        "/api/quality-auth/login/", {"username": "test-collector", "password": "irrelevant"}, format="json"
    ).status_code in {401, 403}


def test_daq_idempotency_and_actor_snapshot_are_preserved(standalone):
    project, _ = standalone
    payload = report(project)
    first = call("/api/quality-auth/daq-reports/", payload)
    second = call("/api/quality-auth/daq-reports/", payload)
    assert first.status_code == 201 and second.status_code == 200
    assert first.data["issueId"] == second.data["issueId"]
    payload["description"] += " changed"
    assert call("/api/quality-auth/daq-reports/", payload).status_code == 409


def test_daq_uploads_complete_evidence_without_upstream(standalone, settings, tmp_path, mocker):
    import hashlib
    import io
    import zipfile
    from django.core.files.uploadedfile import SimpleUploadedFile
    from plane.tests.contract.app.test_daq_reporting import upload_part
    from plane.quality.models import PackageFile

    project, upstream = standalone
    settings.QUALITY_ATTACHMENT_ROOT = str(tmp_path)
    mocker.patch("plane.quality.diagnostics.enqueue")
    created = call("/api/quality-auth/daq-reports/", report(project))
    assert created.status_code == 201, created.content
    report_id = created.data["issueId"]
    base = f"/api/quality-auth/daq-reports/{report_id}/"
    version = json.dumps({"eventId": "test", "versions": {"daq": "1.2.3"}}).encode()
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("capture.log", "ERROR camera connection refused")
    files = {"feedback-version-test.json": version, "daq-diagnostic-logs-test.zip": archive.getvalue()}
    package = call(
        base + "packages/",
        {
            "name": "现场材料",
            "defect_id": report_id,
            "source_system": "ENGRAM_DAQ",
            "external_id": str(uuid4()),
            "files": [
                {"path": name, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                for name, raw in files.items()
            ],
        },
    )
    assert package.status_code == 201, package.content
    upload_url = base + f"packages/{package.data['id']}/files/"
    for name, raw in files.items():
        uploaded = upload_part(upload_url, {"file": SimpleUploadedFile(name, raw), "manifest_path": name})
        assert uploaded.status_code == 201, uploaded.content
        assert uploaded.data["uploader"] == "test-collector"
    assert PackageFile.objects.filter(package_id=package.data["id"]).count() == 2
    assert upload_part(
        upload_url, {"file": SimpleUploadedFile("feedback-version-test.json", version)}, actor=17
    ).status_code in {403, 404}
    upstream.assert_not_called()


def test_daq_grant_list_paginates_and_searches_across_workspaces(standalone, create_user):
    from plane.db.models import Workspace

    project, _ = standalone
    other_ws = Workspace.objects.create(name="another", slug="another", owner=create_user)
    other = Project.objects.create(workspace=other_ws, name="跨工作区项目", identifier="CROSS")
    instance = Instance.objects.get()
    InstanceAdmin.objects.create(instance=instance, user=create_user)
    client = APIClient()
    client.force_authenticate(create_user)
    path = "/api/quality-auth/daq-project-grants/"
    found = client.get(path, {"search": "CROSS", "per_page": 20})
    assert found.status_code == 200 and found.data["count"] == 1
    assert found.data["results"][0]["id"] == str(other.id)
    assert (
        client.post(
            path,
            {"projects": [str(other.id), str(project.id)], "expected_revision": found.data["revision"]},
            format="json",
        ).status_code
        == 200
    )
    assert call("/api/quality-auth/daq-project-options/").data["count"] == 2


def test_structured_daq_title_is_shortened_without_losing_overview_fields(standalone):
    from plane.quality.serializers import DefectSerializer

    project, _ = standalone
    payload = report(project)
    payload["title"] = (
        "其他问题：问题范围：遥操与 DAQ 发生阶段：启动 受影响模块：相机 异常类型：连接异常 现场描述：相机画面停止更新"
    )
    payload["description"] = "相机画面停止更新，重连后仍失败。"
    created = call("/api/quality-auth/daq-reports/", payload)
    assert created.status_code == 201, created.content
    defect = Defect.objects.get(pk=created.data["issueId"])
    result = DefectSerializer(defect).data
    assert defect.title == "相机画面停止更新，重连后仍失败。"
    assert result["title"] == "相机画面停止更新，重连后仍失败。"
    assert "问题范围：遥操与 DAQ" in result["description"]
    assert "发生阶段：启动" in result["description"]
    assert "受影响模块：相机" in result["description"]


@pytest.mark.parametrize(
    "suffix",
    [
        "sso/challenge/",
        "sso/exchange/",
        "daq/bindings/",
        "daq/identities/",
        "daq/project-mapping/",
        "daq/reports/",
        "daq/incidents/",
        "integrations/catalog/",
    ],
)
def test_retired_project_bridge_routes_stay_closed(standalone, suffix):
    project, _ = standalone
    path = f"/api/workspaces/{project.workspace.slug}/projects/{project.id}/quality/{suffix}"
    assert APIClient().post(path, {}, format="json").status_code == 404
