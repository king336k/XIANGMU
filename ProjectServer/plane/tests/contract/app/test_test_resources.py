"""Optional execution resources gate readiness, never fabricate an execution result."""

from uuid import uuid4
import pytest
from plane.db.models import Project, ProjectMember
from plane.quality.models import TestExecution

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def resources(session_client, workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="执行资源", identifier="RES")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/"
    case = session_client.post(
        base + "cases/", {"title": "资源检查", "steps": [{"action": "检查", "expected": "可用"}]}, format="json"
    ).data
    plan = session_client.post(
        base + "plans/",
        {"name": "资源计划", "build": "v1", "environment": "本地验收", "managed": True, "case_ids": [case["id"]]},
        format="json",
    ).data
    return base, project, plan


def test_plan_resources_preflight_and_real_results_keep_resource_snapshot(session_client, resources):
    base, project, plan = resources
    resource = session_client.post(
        base + "test-resources/",
        {"name": "上传环境", "kind": "environment", "build": "v1", "status": "offline"},
        format="json",
    )
    assert resource.status_code == 201, resource.content
    attached = session_client.post(
        base + f"plans/{plan['id']}/resources/",
        {"expected_version": plan["workflow_version"], "resource_ids": [resource.data["id"]]},
        format="json",
    )
    assert attached.status_code == 200, attached.content
    check = session_client.get(base + f"plans/{plan['id']}/preflight/")
    assert (
        check.status_code == 200
        and not check.data["ready"]
        and not TestExecution.objects.filter(project=project).exists()
    )
    assert (
        session_client.post(
            base + f"plans/{plan['id']}/workflow/",
            {"action": "claim", "expected_version": attached.data["workflow_version"]},
            format="json",
        ).status_code
        == 400
    )
    updated = session_client.patch(
        base + f"test-resources/{resource.data['id']}/", {"expected_version": 1, "status": "available"}, format="json"
    )
    assert updated.status_code == 200
    assert session_client.get(base + f"plans/{plan['id']}/preflight/").data["ready"]
    started = session_client.post(
        base + f"plans/{plan['id']}/workflow/",
        {"action": "claim", "expected_version": attached.data["workflow_version"]},
        format="json",
    )
    assert started.status_code == 200, started.content
    result = session_client.post(
        base + f"items/{plan['items'][0]['id']}/executions/",
        {"request_id": str(uuid4()), "result": "passed", "actual_result": "环境可用并完成实际检查"},
        format="json",
    )
    assert result.status_code == 201, result.content
    assert result.data["resource_snapshot"]["resources"][0]["name"] == "上传环境"


def test_unavailable_resource_allows_truthful_blocked_result_but_not_passed(session_client, resources):
    base, project, plan = resources
    row = session_client.post(base + "test-resources/", {"name": "采集设备", "kind": "robot"}, format="json")
    assert row.status_code == 201, row.content
    attached = session_client.post(
        base + f"plans/{plan['id']}/resources/",
        {"expected_version": 1, "resource_ids": [row.data["id"]]},
        format="json",
    ).data
    assert (
        session_client.post(
            base + f"plans/{plan['id']}/workflow/",
            {"action": "claim", "expected_version": attached["workflow_version"]},
            format="json",
        ).status_code
        == 200
    )
    session_client.patch(
        base + f"test-resources/{row.data['id']}/", {"expected_version": 1, "status": "maintenance"}, format="json"
    )
    path = base + f"items/{plan['items'][0]['id']}/executions/"
    assert session_client.post(path, {"request_id": str(uuid4()), "result": "passed"}, format="json").status_code == 400
    blocked = session_client.post(
        path, {"request_id": str(uuid4()), "result": "blocked", "actual_result": "设备正在维护"}, format="json"
    )
    assert blocked.status_code == 201, blocked.content
    assert not blocked.data["resource_snapshot"]["ready"]


def test_resource_administration_checks_role_and_cross_project_agent(session_client, resources, create_user, workspace):
    from plane.quality.models import FieldAgent

    base, project, plan = resources
    other = Project.objects.create(workspace=workspace, name="其他资源", identifier="ORES")
    agent = FieldAgent.objects.create(project=other, owner=create_user, name="外项目代理")
    assert (
        session_client.post(
            base + "test-resources/",
            {"name": "非法代理", "kind": "daq_station", "agent_id": str(agent.id)},
            format="json",
        ).status_code
        == 400
    )
    ProjectMember.objects.filter(project=project, member=create_user).update(role=15)
    assert (
        session_client.post(base + "test-resources/", {"name": "越权登记", "kind": "robot"}, format="json").status_code
        == 403
    )


def test_preflight_rejects_stale_agent_and_version_mismatch_without_losing_history(
    session_client, resources, create_user
):
    from datetime import timedelta
    from django.utils import timezone
    from plane.quality.models import FieldAgent, TestResource, PlanResource, TestPlan

    base, project, plan = resources
    agent = FieldAgent.objects.create(
        project=project, owner=create_user, name="离线代理", last_seen_at=timezone.now() - timedelta(minutes=10)
    )
    row = TestResource.objects.create(project=project, name="采集设备", kind="daq_station", build="v2", agent=agent)
    PlanResource.objects.create(project=project, plan_id=plan["id"], resource=row)
    check = session_client.get(base + f"plans/{plan['id']}/preflight/")
    assert not check.data["ready"] and len(check.data["errors"]) == 2
    row.build = "v1"
    row.save()
    agent.last_seen_at = timezone.now()
    agent.save()
    assert session_client.get(base + f"plans/{plan['id']}/preflight/").data["ready"]
    assert (
        session_client.post(
            base + f"plans/{plan['id']}/resources/", {"expected_version": 99, "resource_ids": []}, format="json"
        ).status_code
        == 409
    )
    TestPlan.objects.filter(pk=plan["id"]).update(status="running")
    assert (
        session_client.post(
            base + f"plans/{plan['id']}/resources/", {"expected_version": 1, "resource_ids": []}, format="json"
        ).status_code
        == 409
    )


def test_copy_plan_preserves_resource_requirements_instead_of_silently_dropping_gate(session_client, resources):
    from plane.quality.models import TestResource, PlanResource

    base, project, plan = resources
    row = TestResource.objects.create(project=project, name="需维护设备", kind="robot", status="maintenance")
    PlanResource.objects.create(project=project, plan_id=plan["id"], resource=row)
    copied = session_client.post(
        base + f"plans/{plan['id']}/copy/", {"expected_version": 1, "name": "资源计划新一轮"}, format="json"
    )
    assert copied.status_code == 201, copied.content
    check = session_client.get(base + f"plans/{copied.data['id']}/preflight/")
    assert not check.data["ready"] and check.data["resources"][0]["id"] == str(row.id)


def test_recent_external_agent_heartbeat_does_not_override_revoked_identity(
    session_client, resources, create_user, mocker
):
    from django.utils import timezone
    from plane.quality.models import FieldAgent, TestResource, PlanResource, PlatformIdentity
    from rest_framework.exceptions import AuthenticationFailed

    base, project, plan = resources
    agent = FieldAgent.objects.create(
        project=project,
        owner=create_user,
        name="外部现场代理",
        last_seen_at=timezone.now(),
        source_instance="test-authority",
    )
    row = TestResource.objects.create(project=project, name="现场设备", kind="daq_station", agent=agent)
    PlanResource.objects.create(project=project, plan_id=plan["id"], resource=row)
    identity = PlatformIdentity.objects.create(
        project=project, source_instance="test-authority", external_user_id=16, user=create_user, active=False
    )
    assert not session_client.get(base + f"plans/{plan['id']}/preflight/").data["ready"]
    identity.active = True
    identity.save()
    mocker.patch("plane.quality.platform.verify_identity", side_effect=AuthenticationFailed())
    assert not session_client.get(base + f"plans/{plan['id']}/preflight/").data["ready"]


@pytest.mark.django_db(transaction=True)
def test_passed_execution_holds_resource_lock_until_snapshot_is_saved(resources, session_client, create_user, mocker):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from django.db import close_old_connections, transaction, OperationalError
    from rest_framework.test import APIClient
    from plane.quality.models import TestResource, PlanResource
    from plane.quality import test_resources

    base, project, plan = resources
    row = TestResource.objects.create(project=project, name="并发资源", kind="environment")
    PlanResource.objects.create(project=project, plan_id=plan["id"], resource=row)
    assert (
        session_client.post(
            base + f"plans/{plan['id']}/workflow/", {"action": "claim", "expected_version": 1}, format="json"
        ).status_code
        == 200
    )
    checked, release = Event(), Event()
    original = test_resources.require_ready

    def observe(value):
        result = original(value)
        checked.set()
        assert release.wait(timeout=5)
        return result

    mocker.patch("plane.quality.test_resources.require_ready", side_effect=observe)

    def execute():
        close_old_connections()
        try:
            client = APIClient()
            client.force_authenticate(user=create_user)
            return client.post(
                base + f"items/{plan['items'][0]['id']}/executions/",
                {"request_id": str(uuid4()), "result": "passed", "actual_result": "资源快照已核对"},
                format="json",
            ).status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(execute)
        try:
            assert checked.wait(timeout=5)
            with pytest.raises(OperationalError):
                with transaction.atomic():
                    TestResource.objects.select_for_update(nowait=True).get(pk=row.pk)
        finally:
            release.set()
        assert future.result(timeout=5) == 201
