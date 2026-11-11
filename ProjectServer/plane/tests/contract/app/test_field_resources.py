"""Field snapshots produce review candidates, never automatic test-pass evidence."""

import pytest
from uuid import uuid4
from plane.db.models import Project, ProjectMember, WorkspaceMember, User

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def resources(session_client, workspace, create_user):
    p = Project.objects.create(workspace=workspace, name="现场资源", identifier="FIELD")
    ProjectMember.objects.create(project=p, member=create_user, role=20)
    collector = User.objects.create(email="field-collector@local.test", username="field-collector")
    WorkspaceMember.objects.create(workspace=workspace, member=collector, role=15)
    ProjectMember.objects.create(project=p, member=collector, role=15)
    base = f"/api/workspaces/{workspace.slug}/projects/{p.id}/quality/"
    return base, p, collector, create_user


def test_scoped_field_install_package_has_ids_and_code_but_never_credentials(session_client, resources):
    import io
    import json
    import zipfile

    base, project, collector, manager = resources
    response = session_client.post(
        base + "field-agents/", {"name": "采集工作站安装包", "owner_id": str(collector.id)}, format="json"
    )
    assert response.status_code == 201, response.content
    agent = response.data
    package = session_client.get(base + f"field-agents/{agent['id']}/install-package/")
    assert package.status_code == 200, package.content
    with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
        assert sorted(archive.namelist()) == [
            "README.md",
            "connection.json",
            "field_agent_client.py",
            "run_observer.py",
        ]
        config = json.loads(archive.read("connection.json"))
        assert config["project"] == str(project.id) and config["agent"] == agent["id"]
        assert not any(key in config for key in ["token", "secret", "password", "cookie"])
        compile(archive.read("run_observer.py"), "run_observer.py", "exec")
        assert "FIELD_AGENT_TOKEN" in archive.read("README.md").decode()
    session_client.force_authenticate(user=collector)
    assert session_client.get(base + f"field-agents/{agent['id']}/install-package/").status_code == 403


def test_field_agent_heartbeat_snapshot_and_disabled_agent_rejection(session_client, resources):
    base, p, collector, manager = resources
    created = session_client.post(
        base + "field-agents/", {"name": "采集工作站", "owner_id": str(collector.id)}, format="json"
    )
    assert created.status_code == 201, created.content
    agent = created.data
    session_client.force_authenticate(user=collector)
    heartbeat = session_client.post(
        base + f"field-agents/{agent['id']}/heartbeat/",
        {
            "request_id": str(uuid4()),
            "snapshot": {"device": "robot-1", "daq": {"status": "recording"}, "performance": {"cpu": 23}},
        },
        format="json",
    )
    assert heartbeat.status_code == 201, heartbeat.content
    assert heartbeat.data["trusted_as_test_result"] is False
    session_client.force_authenticate(user=manager)
    state = session_client.get(base + f"field-agents/{agent['id']}/")
    assert state.status_code == 200 and state.data["latest_snapshot"]["snapshot"]["device"] == "robot-1"
    assert (
        session_client.patch(
            base + f"field-agents/{agent['id']}/", {"enabled": False, "expected_version": 1}, format="json"
        ).status_code
        == 200
    )
    session_client.force_authenticate(user=collector)
    assert (
        session_client.post(
            base + f"field-agents/{agent['id']}/heartbeat/", {"request_id": str(uuid4()), "snapshot": {}}, format="json"
        ).status_code
        == 403
    )


def test_snapshot_cannot_contain_credentials_or_nonfinite_values(session_client, resources):
    base, p, collector, manager = resources
    agent = session_client.post(
        base + "field-agents/", {"name": "现场采集", "owner_id": str(collector.id)}, format="json"
    ).data
    session_client.force_authenticate(user=collector)
    response = session_client.post(
        base + f"field-agents/{agent['id']}/heartbeat/",
        {"request_id": str(uuid4()), "snapshot": {"api_key": "private-not-real-test"}},
        format="json",
    )
    assert response.status_code == 400, response.content


def test_telemetry_candidate_requires_manager_review_and_never_writes_execution(session_client, resources):
    base, p, collector, manager = resources
    agent = session_client.post(
        base + "field-agents/", {"name": "候选来源", "owner_id": str(collector.id)}, format="json"
    ).data
    session_client.force_authenticate(user=collector)
    snapshot = session_client.post(
        base + f"field-agents/{agent['id']}/heartbeat/",
        {"request_id": str(uuid4()), "snapshot": {"result": "PASS", "device": "robot-1"}},
        format="json",
    ).data
    from plane.quality.models import TestExecution

    assert not TestExecution.objects.filter(project=p).exists()
    assert (
        session_client.post(
            base + f"telemetry/{snapshot['id']}/review/",
            {"decision": "accept", "note": "采集员不可自行采纳"},
            format="json",
        ).status_code
        == 403
    )
    session_client.force_authenticate(user=manager)
    reviewed = session_client.post(
        base + f"telemetry/{snapshot['id']}/review/",
        {"decision": "accept", "note": "仅采纳现场观察，不代表测试通过"},
        format="json",
    )
    assert reviewed.status_code == 200 and reviewed.data["review_status"] == "accepted", reviewed.content
    assert not TestExecution.objects.filter(project=p).exists()


def test_field_heartbeat_wrong_owner_and_request_id_replay_are_bounded(session_client, resources):
    base, p, collector, manager = resources
    agent = session_client.post(
        base + "field-agents/", {"name": "幂等资源", "owner_id": str(collector.id)}, format="json"
    ).data
    identifier = str(uuid4())
    url = base + f"field-agents/{agent['id']}/heartbeat/"
    assert session_client.post(url, {"request_id": identifier, "snapshot": {}}, format="json").status_code == 403
    session_client.force_authenticate(user=collector)
    first = session_client.post(url, {"request_id": identifier, "snapshot": {"device": "r1"}}, format="json")
    assert first.status_code == 201
    repeated = session_client.post(url, {"request_id": identifier, "snapshot": {"device": "r1"}}, format="json")
    assert repeated.status_code == 200 and repeated.data["id"] == first.data["id"]
    assert (
        session_client.post(url, {"request_id": identifier, "snapshot": {"device": "r2"}}, format="json").status_code
        == 409
    )
    ProjectMember.objects.filter(project=p, member=collector).update(is_active=False)
    assert session_client.post(url, {"request_id": str(uuid4()), "snapshot": {}}, format="json").status_code == 403


def test_agent_credential_only_authorizes_its_heartbeat_and_rotation_revokes_old_value(
    session_client, resources, api_client
):
    base, p, collector, manager = resources
    agent = session_client.post(
        base + "field-agents/", {"name": "限权代理", "owner_id": str(collector.id)}, format="json"
    ).data
    token = session_client.post(
        base + f"field-agents/{agent['id']}/credential/", {"expected_version": 1}, format="json"
    )
    assert token.status_code == 201
    raw = token.data["token"]
    api_client.force_authenticate(user=None)
    response = api_client.post(
        base + f"field-agents/{agent['id']}/heartbeat/",
        {"request_id": str(uuid4()), "snapshot": {"device": "r1"}},
        format="json",
        HTTP_AUTHORIZATION="Bearer " + raw,
    )
    assert response.status_code == 201, response.content
    assert api_client.post(
        base + "defects/", {"title": "令牌不得发起缺陷"}, format="json", HTTP_AUTHORIZATION="Bearer " + raw
    ).status_code in [401, 403]
    from plane.quality.models import FieldAgent

    row = FieldAgent.objects.get(pk=agent["id"])
    assert row.credential_hash and row.credential_hash != raw
    row.enabled = False
    row.save(update_fields=["enabled"])
    assert api_client.post(
        base + f"field-agents/{agent['id']}/heartbeat/",
        {"request_id": str(uuid4()), "snapshot": {}},
        format="json",
        HTTP_AUTHORIZATION="Bearer " + raw,
    ).status_code in [401, 403]


def test_distributed_client_reports_failure_without_runtime_identity(monkeypatch):
    import os
    import subprocess
    import sys

    runtime = dict(os.environ)
    for name in ["FIELD_AGENT_TOKEN", "PLANE_RUNTIME_COOKIE"]:
        runtime.pop(name, None)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "plane.quality.field_agent_client",
            "--server",
            "http://127.0.0.1:1",
            "--allow-private-http",
            "--workspace",
            "test",
            "--project",
            str(uuid4()),
            "--agent",
            str(uuid4()),
            "--device",
            "test",
            "--once",
        ],
        env=runtime,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 1 and "Heartbeat failed: ValueError" in result.stdout
