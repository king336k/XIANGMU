"""Read-only product audit: actual API operations after changes under an unchanged session."""

from uuid import uuid4
from django.utils import timezone
from django.conf import settings
import pytest
from rest_framework.test import APIClient
from plane.db.models import Project, ProjectMember, WorkspaceMember, User
from plane.license.models import Instance, InstanceAdmin
from plane.quality.models import BusinessRole, ProjectRolePolicy, TestPlan, TestExecution
from plane.knowledge.models import Article

pytestmark = [pytest.mark.django_db]


@pytest.fixture
def scenario(workspace, create_user):
    instance = Instance.objects.create(
        instance_name="role-changes", instance_id=str(uuid4()), current_version="test", last_checked_at=timezone.now()
    )
    InstanceAdmin.objects.create(instance=instance, user=create_user)
    project = Project.objects.create(workspace=workspace, name="改岗权限", identifier="SWITCH")
    ProjectRolePolicy.objects.create(project=project, enabled=True)
    ProjectMember.objects.create(project=project, member=create_user, role=15)
    target = User.objects.create(username="changing-role", email="changing-role@audit.invalid", display_name="改岗成员")
    WorkspaceMember.objects.create(workspace=workspace, member=target, role=15)
    ProjectMember.objects.create(project=project, member=target, role=15)
    BusinessRole.objects.create(project=project, user=target, role="REPORTER")
    other = User.objects.create(username="other-person", email="other@audit.invalid")
    WorkspaceMember.objects.create(workspace=workspace, member=other, role=15)
    ProjectMember.objects.create(project=project, member=other, role=15)
    BusinessRole.objects.create(project=project, user=other, role="REPORTER")
    admin = APIClient()
    admin.force_login(create_user)
    client = APIClient()
    client.force_login(target)
    cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/"
    rows = []

    def call(name, method, path, data=None, expected=200, who=None):
        response = getattr(who or client, method)(path, data, format="json")
        rows.append(
            {
                "action": name,
                "expected": expected,
                "actual": response.status_code,
                "passed": response.status_code == expected,
            }
        )
        assert response.status_code == expected, (name, response.data)
        if who is None:
            assert client.cookies[settings.SESSION_COOKIE_NAME].value == cookie
        return response.data

    def roles(wanted):
        return call(
            "admin_changes_roles", "post", base + "roles/", {"user_id": str(target.id), "roles": wanted}, who=admin
        )

    yield project, target, other, admin, client, base, call, roles


def test_reporter_to_tester_applies_new_case_plan_and_execution_on_same_cookie(scenario):
    project, target, other, admin, client, base, call, roles = scenario
    call("reporter_case_denied", "post", base + "cases/", {"title": "不得创建"}, 403)
    roles(["REGRESSION_TESTER"])
    context = call("new_tester_context", "get", base + "context/")
    assert context["business_roles"] == ["REGRESSION_TESTER"]
    assert (
        context["capabilities"]["manage_case"]
        and context["capabilities"]["manage_test_plan"]
        and context["capabilities"]["execute"]
    )
    case = call(
        "tester_case_created",
        "post",
        base + "cases/",
        {"title": "改岗后用例", "steps": [{"action": "操作", "expected": "通过"}]},
        201,
    )
    plan = call(
        "tester_plan_created",
        "post",
        base + "plans/",
        {"name": "改岗后计划", "build": "v1", "environment": "local", "case_ids": [case["id"]]},
        201,
    )
    execution = call(
        "tester_executes_new_plan",
        "post",
        base + f"items/{plan['items'][0]['id']}/executions/",
        {"request_id": str(uuid4()), "result": "passed"},
        201,
    )
    assert TestExecution.objects.get(pk=execution["id"]).created_by_id == target.id


@pytest.mark.parametrize("native_role,workspace_role", [(15, 15), (20, 15), (15, 20)])
def test_pm_to_tester_revokes_manager_and_knowledge_publish_on_same_cookie(scenario, native_role, workspace_role):
    project, target, other, admin, client, base, call, roles = scenario
    ProjectMember.objects.filter(project=project, member=target).update(role=native_role)
    WorkspaceMember.objects.filter(workspace=project.workspace, member=target).update(role=workspace_role)
    roles(["PROJECT_MANAGER"])
    before = call("manager_context_before", "get", base + "context/")
    assert before["capabilities"]["manage_test"] and before["can_review_knowledge"]
    roles(["REGRESSION_TESTER"])
    after = call("tester_context_after", "get", base + "context/")
    assert not after["capabilities"]["manage_test"] and after["capabilities"]["execute"]
    plan = TestPlan.objects.create(project=project, name="最终验收必须拒绝", managed=True, status="review")
    call(
        "tester_final_approve_denied",
        "post",
        base + f"plans/{plan.id}/workflow/",
        {"action": "approve", "expected_version": 1},
        403,
    )
    call(
        "tester_changes_other_role_denied",
        "post",
        base + "roles/",
        {"user_id": str(other.id), "roles": ["TECHNICIAN"]},
        403,
    )
    article = Article.objects.create(
        project=project, title="改岗不能残留审核", content="检查连接状态。", created_by=target, scanned_version=1
    )
    call(
        "tester_publish_denied",
        "post",
        base.replace("/quality/", "/knowledge/") + f"articles/{article.id}/workflow/",
        {"action": "publish", "expected_version": 1},
        403,
    )
    assert not after["can_review_knowledge"]


@pytest.mark.parametrize("wanted", [["PROJECT_MANAGER", "REGRESSION_TESTER"], ["REGRESSION_TESTER", "PROJECT_MANAGER"]])
def test_multiple_roles_are_union_independent_of_primary_order(scenario, wanted):
    project, target, other, admin, client, base, call, roles = scenario
    roles(wanted)
    context = call("union_context", "get", base + "context/")
    assert set(context["business_roles"]) == set(wanted)
    assert all(
        context["capabilities"][cap] for cap in ["manage_test", "manage_case", "manage_test_plan", "execute", "review"]
    )
    case = call(
        "union_creates_case",
        "post",
        base + "cases/",
        {"title": "多岗用例", "steps": [{"action": "操作", "expected": "通过"}]},
        201,
    )
    plan = call(
        "union_creates_plan",
        "post",
        base + "plans/",
        {
            "name": "多岗计划",
            "build": "v1",
            "environment": "local",
            "case_ids": [case["id"]],
            "managed": True,
            "assignee_id": str(target.id),
        },
        201,
    )
    workflow = base + f"plans/{plan['id']}/workflow/"
    call("union_claims", "post", workflow, {"action": "claim", "expected_version": 1})
    call(
        "union_executes",
        "post",
        base + f"items/{plan['items'][0]['id']}/executions/",
        {"request_id": str(uuid4()), "result": "passed"},
        201,
    )
    call("union_submits", "post", workflow, {"action": "submit", "expected_version": 2})
    call("union_manager_accepts", "post", workflow, {"action": "approve", "expected_version": 3})
    assert TestPlan.objects.get(pk=plan["id"]).reviewed_by_id == target.id


def test_remove_tester_keeps_manager_but_loses_execution(scenario):
    project, target, other, admin, client, base, call, roles = scenario
    roles(["PROJECT_MANAGER", "REGRESSION_TESTER"])
    roles(["PROJECT_MANAGER"])
    context = call("manager_only_context", "get", base + "context/")
    assert context["capabilities"]["manage_test"] and not context["capabilities"]["execute"]
    case = call(
        "manager_creates_case",
        "post",
        base + "cases/",
        {"title": "经理可维护", "steps": [{"action": "操作", "expected": "通过"}]},
        201,
    )
    plan = call(
        "manager_creates_plan",
        "post",
        base + "plans/",
        {"name": "经理计划", "build": "v1", "environment": "local", "case_ids": [case["id"]]},
        201,
    )
    call(
        "former_tester_execution_denied",
        "post",
        base + f"items/{plan['items'][0]['id']}/executions/",
        {"request_id": str(uuid4()), "result": "passed"},
        403,
    )
    call("manager_assigns_other_role", "post", base + "roles/", {"user_id": str(other.id), "roles": ["TECHNICIAN"]})


def test_remove_manager_keeps_tester_but_loses_manager_unique_capabilities(scenario):
    project, target, other, admin, client, base, call, roles = scenario
    roles(["PROJECT_MANAGER", "REGRESSION_TESTER"])
    roles(["REGRESSION_TESTER"])
    context = call("tester_only_context", "get", base + "context/")
    assert context["capabilities"]["execute"] and context["capabilities"]["manage_test_plan"]
    assert (
        not context["capabilities"]["manage_test"]
        and not context["capabilities"]["manage_roles"]
        and not context["can_review_knowledge"]
    )
    call("former_pm_roles_denied", "post", base + "roles/", {"user_id": str(other.id), "roles": ["TECHNICIAN"]}, 403)


def test_administrator_has_all_capabilities_without_multiple_business_roles(scenario):
    project, target, other, admin, client, base, call, roles = scenario
    context = call("administrator_all_context", "get", base + "context/", who=admin)
    assert context["is_administrator"] and all(context["capabilities"].values())


def test_source_relogin_preserves_primary_and_additional_roles(scenario, mocker):
    from django.core.cache import cache
    from plane.quality.models import PlatformAccount, PlatformProject

    project, target, other, admin, client, base, call, roles = scenario
    config = {
        "kind": "data_platform",
        "base_url": "https://source.example",
        "allowed_hosts": ["source.example"],
        "login_enabled": True,
        "login_auto_provision": True,
        "configured_by": str(InstanceAdmin.objects.first().user_id),
        "service_token": "test-only",
    }
    info = {"id": 42, "username": "source-multi", "status": "Active", "role": "Auditor"}
    PlatformProject.objects.create(project=project, source_instance="source", external_project_id=7)
    mocker.patch("plane.quality.data_accounts.read_connection", return_value=config)
    mocker.patch("plane.quality.data_accounts.authenticate_upstream", return_value=(info, "test-access-only"))
    mocker.patch("plane.quality.data_accounts.source_user", return_value=info)
    mocker.patch(
        "plane.quality.data_accounts.authority_request", return_value={"projects": [{"id": 7}], "administrator": False}
    )
    mocker.patch(
        "plane.quality.platform.fetch",
        side_effect=lambda name, path, *a, **kw: (
            {"id": 42, "active": True, "role": "Auditor"} if "/issue-users/" in path else {"projects": [{"id": 7}]}
        ),
    )
    cache.clear()
    source = APIClient()
    first = source.post(
        "/api/quality-auth/data-login/",
        {"source_instance": "source", "username": "source-multi", "password": "test-input-only"},
        format="json",
    )
    assert first.status_code == 200, first.data
    account = PlatformAccount.objects.get(source_instance="source", external_user_id=42)
    changed = admin.post(
        base + "roles/",
        {"user_id": str(account.user_id), "roles": ["REGRESSION_TESTER", "PROJECT_MANAGER"]},
        format="json",
    )
    assert changed.status_code == 200, changed.data
    cache.clear()
    again = APIClient()
    response = again.post(
        "/api/quality-auth/data-login/",
        {"source_instance": "source", "username": "source-multi", "password": "test-input-only"},
        format="json",
    )
    assert response.status_code == 200, response.data
    context = again.get(base + "context/")
    assert context.status_code == 200, context.data
    assert set(context.data["business_roles"]) == {"REGRESSION_TESTER", "PROJECT_MANAGER"}
    binding = BusinessRole.objects.get(project=project, user=account.user)
    assert binding.role == "REGRESSION_TESTER" and binding.additional_roles == ["PROJECT_MANAGER"]
