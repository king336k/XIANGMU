"""45100 five business roles are independent of generic workspace access."""

from uuid import uuid4
import pytest
from plane.db.models import Project, ProjectMember, WorkspaceMember, User

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def business(session_client, workspace, create_user):
    from django.utils import timezone
    from plane.license.models import Instance, InstanceAdmin

    instance = Instance.objects.create(
        instance_name="统一管理员", instance_id=str(uuid4()), current_version="test", last_checked_at=timezone.now()
    )
    InstanceAdmin.objects.create(instance=instance, user=create_user)
    p = Project.objects.create(workspace=workspace, name="五角色项目", identifier="BIZ")
    ProjectMember.objects.create(project=p, member=create_user, role=20)
    base = f"/api/workspaces/{workspace.slug}/projects/{p.id}/quality/"
    people = {}
    for role in ["PLATFORM_ADMIN", "PROJECT_MANAGER", "TECHNICIAN", "REGRESSION_TESTER", "REPORTER"]:
        person = User.objects.create(
            email=f"{role.lower()}@roles.local", username=f"role-{role.lower()}", display_name=role
        )
        WorkspaceMember.objects.create(workspace=workspace, member=person, role=15)
        ProjectMember.objects.create(project=p, member=person, role=15)
        if role == "PLATFORM_ADMIN":
            response = session_client.patch(
                "/api/quality-auth/accounts/", {"user_id": str(person.id), "administrator": True}, format="json"
            )
            assert response.status_code == 200, response.content
            people[role] = person
            continue
        response = session_client.post(
            base + "roles/", {"user_id": str(person.pk), "roles": [] if role == "REPORTER" else [role]}, format="json"
        )
        assert response.status_code == 200, response.content
        people[role] = person
    enabled = session_client.post(base + "role-policy/", {"enabled": True}, format="json")
    assert enabled.status_code == 200, enabled.content
    return base, p, people, create_user


def test_collector_is_reporter_and_cannot_execute_or_assign(session_client, business):
    base, project, people, admin = business
    session_client.force_authenticate(user=people["REPORTER"])
    context = session_client.get(base + "context/")
    assert context.status_code == 200
    assert context.data["business_role"] is None
    assert context.data["capabilities"]["report"] and not context.data["capabilities"]["execute"]
    defect = session_client.post(base + "defects/", {"title": "采集异常"}, format="json")
    assert defect.status_code == 201
    assert (
        session_client.post(
            base + "cases/", {"title": "不允许", "steps": [{"action": "执行", "expected": "成功"}]}, format="json"
        ).status_code
        == 403
    )
    assert (
        session_client.patch(
            base + f"defects/{defect.data['id']}/", {"status": "in_progress"}, format="json"
        ).status_code
        == 403
    )
    assert (
        session_client.post(
            base + f"defects/{defect.data['id']}/collaboration/", {"action": "claim"}, format="json"
        ).status_code
        == 403
    )
    assert (
        session_client.post(
            base + "roles/", {"user_id": str(admin.id), "role": "PROJECT_MANAGER"}, format="json"
        ).status_code
        == 403
    )


def test_manager_assigns_only_technician_and_tester_executes(session_client, business):
    base, project, people, admin = business
    session_client.force_authenticate(user=people["PROJECT_MANAGER"])
    case = session_client.post(
        base + "cases/", {"title": "回归验证", "steps": [{"action": "验证", "expected": "成功"}]}, format="json"
    )
    assert case.status_code == 201, case.content
    payload = {"name": "受管回归", "build": "v1", "environment": "本地", "case_ids": [case.data["id"]], "managed": True}
    plan = session_client.post(base + "plans/", payload, format="json")
    assert plan.status_code == 201
    workflow = base + f"plans/{plan.data['id']}/workflow/"
    assert (
        session_client.post(
            workflow,
            {"action": "assign", "expected_version": 1, "assignee_id": str(people["TECHNICIAN"].id)},
            format="json",
        ).status_code
        == 400
    )
    assigned = session_client.post(
        workflow,
        {"action": "assign", "expected_version": 1, "assignee_id": str(people["REGRESSION_TESTER"].id)},
        format="json",
    )
    assert assigned.status_code == 200
    session_client.force_authenticate(user=people["PROJECT_MANAGER"])
    assert session_client.post(workflow, {"action": "claim", "expected_version": 2}, format="json").status_code == 403
    session_client.force_authenticate(user=people["REGRESSION_TESTER"])
    assert session_client.post(workflow, {"action": "claim", "expected_version": 2}, format="json").status_code == 200
    executed = session_client.post(
        base + f"items/{plan.data['items'][0]['id']}/executions/",
        {"request_id": str(uuid4()), "result": "passed"},
        format="json",
    )
    assert executed.status_code == 201
    session_client.force_authenticate(user=people["PLATFORM_ADMIN"])
    assert session_client.post(base + "defects/", {"title": "管理员拥有全部业务能力"}, format="json").status_code == 201
    assert session_client.post(workflow, {"action": "approve", "expected_version": 3}, format="json").status_code == 409


def test_knowledge_editorial_is_business_scoped(session_client, business, workspace):
    base, project, people, admin = business
    knowledge = base.replace("/quality/", "/knowledge/")
    session_client.force_authenticate(user=people["REPORTER"])
    assert session_client.get(knowledge + "articles/").status_code == 403
    assert session_client.get(knowledge + "search/?q=采集").status_code == 200
    session_client.force_authenticate(user=people["TECHNICIAN"])
    article = session_client.post(
        knowledge + "articles/", {"title": "排查知识", "content": "检查网络", "tags": []}, format="json"
    )
    assert article.status_code == 201
    session_client.force_authenticate(user=people["REGRESSION_TESTER"])
    assert (
        session_client.post(
            knowledge + f"articles/{article.data['id']}/workflow/",
            {"action": "publish", "expected_version": 1},
            format="json",
        ).status_code
        == 403
    )
    WorkspaceMember.objects.filter(workspace=workspace, member=people["TECHNICIAN"]).update(is_active=False)
    session_client.force_authenticate(user=people["TECHNICIAN"])
    assert session_client.get(base + "context/").status_code == 403


def test_knowledge_business_reviewer_can_publish_own_clean_draft(session_client, business):
    base, project, people, admin = business
    knowledge = base.replace("/quality/", "/knowledge/")
    session_client.force_authenticate(user=people["PROJECT_MANAGER"])
    article = session_client.post(
        knowledge + "articles/", {"title": "审核员整理", "content": "采集前检查网络。", "tags": []}, format="json"
    )
    assert article.status_code == 201, article.data
    workflow = knowledge + f"articles/{article.data['id']}/workflow/"
    scanned = session_client.post(workflow, {"action": "scan", "expected_version": 1}, format="json")
    assert scanned.status_code == 200, scanned.data
    published = session_client.post(
        workflow, {"action": "publish", "expected_version": scanned.data["edit_version"]}, format="json"
    )
    assert published.status_code == 200, published.data
    assert published.data["status"] == "published" and published.data["published_version"] == 1
    assert session_client.get(knowledge + "search/?q=采集").data["count"] == 1


@pytest.mark.parametrize(
    "admin_kind", ["platform", "project", "workspace", "instance", "manager", "additional_platform"]
)
@pytest.mark.parametrize("action", ["publish", "reject"])
def test_strict_business_roles_control_knowledge_review_without_native_role_residue(
    session_client, business, workspace, admin_kind, action
):
    from django.utils import timezone
    from plane.license.models import Instance, InstanceAdmin
    from plane.quality.models import BusinessRole

    base, project, people, owner = business
    knowledge = base.replace("/quality/", "/knowledge/")
    writer = people["TECHNICIAN"]
    session_client.force_authenticate(user=writer)
    article = session_client.post(
        knowledge + "articles/",
        {"title": "其他成员提交的知识", "content": "采集前检查网络。", "tags": []},
        format="json",
    )
    assert article.status_code == 201, article.data
    workflow = knowledge + f"articles/{article.data['id']}/workflow/"
    scanned = session_client.post(workflow, {"action": "scan", "expected_version": 1}, format="json")
    submitted = session_client.post(
        workflow, {"action": "submit", "expected_version": scanned.data["edit_version"]}, format="json"
    )
    assert submitted.status_code == 200, submitted.data
    reviewer = people["PLATFORM_ADMIN"] if admin_kind == "platform" else people["REGRESSION_TESTER"]
    if admin_kind == "manager":
        reviewer = people["PROJECT_MANAGER"]
    elif admin_kind == "project":
        ProjectMember.objects.filter(project=project, member=reviewer).update(role=20)
    elif admin_kind == "workspace":
        WorkspaceMember.objects.filter(workspace=workspace, member=reviewer).update(role=20)
    elif admin_kind == "instance":
        instance = Instance.objects.create(
            instance_name="知识管理员验收",
            instance_id=str(uuid4()),
            current_version="test",
            last_checked_at=timezone.now(),
        )
        InstanceAdmin.objects.create(instance=instance, user=reviewer)
    elif admin_kind == "additional_platform":
        BusinessRole.objects.filter(project=project, user=reviewer).update(additional_roles=["PLATFORM_ADMIN"])
    session_client.force_authenticate(user=reviewer)
    context = session_client.get(base + "context/")
    can_review = admin_kind not in {"project", "workspace"}
    assert context.data.get("can_review_knowledge") is can_review, context.data
    pending = session_client.get(knowledge + "articles/?status=review")
    assert pending.status_code == 200, pending.data
    assert [row["id"] for row in pending.data["results"]] == [article.data["id"]]
    result = session_client.post(
        workflow,
        {"action": action, "expected_version": submitted.data["edit_version"], "comment": "核对内容后处理"},
        format="json",
    )
    if not can_review:
        assert result.status_code == 403, result.data
        assert session_client.get(knowledge + "articles/?status=review").data["count"] == 1
        return
    assert result.status_code == 200, result.data
    assert result.data["status"] == ("published" if action == "publish" else "draft")
    assert session_client.get(knowledge + "articles/?status=review").data["count"] == 0
    if admin_kind in {"manager", "platform", "additional_platform"}:
        assert context.data["capabilities"]["review"] is True
        assert context.data["capabilities"]["manage_test"] is True
    else:
        assert context.data["capabilities"]["review"] is (admin_kind == "instance")
        assert context.data["capabilities"]["manage_test"] is (admin_kind == "instance")


@pytest.mark.parametrize(
    "restriction", ["project_removed", "workspace_removed", "project_guest", "workspace_guest", "archived"]
)
def test_former_admin_knowledge_review_respects_project_access(session_client, business, workspace, restriction):
    base, project, people, owner = business
    reviewer = people["PLATFORM_ADMIN"]
    from plane.license.models import InstanceAdmin

    InstanceAdmin.objects.filter(user=reviewer).delete()
    if restriction == "project_removed":
        ProjectMember.objects.filter(project=project, member=reviewer).update(is_active=False)
    elif restriction == "workspace_removed":
        WorkspaceMember.objects.filter(workspace=workspace, member=reviewer).update(is_active=False)
    elif restriction == "project_guest":
        ProjectMember.objects.filter(project=project, member=reviewer).update(role=5)
    elif restriction == "workspace_guest":
        WorkspaceMember.objects.filter(workspace=workspace, member=reviewer).update(role=5)
    else:
        from django.utils import timezone

        project.archived_at = timezone.now()
        project.save(update_fields=["archived_at"])
    session_client.force_authenticate(user=reviewer)
    knowledge = base.replace("/quality/", "/knowledge/")
    assert session_client.get(knowledge + "articles/").status_code == 403
    assert (
        session_client.post(
            knowledge + "articles/", {"title": "越权", "content": "不可写入"}, format="json"
        ).status_code
        == 403
    )
    context = session_client.get(base + "context/")
    if context.status_code == 200:
        assert context.data.get("can_review_knowledge") is False


@pytest.mark.parametrize(
    "role_name", ["PLATFORM_ADMIN", "PROJECT_MANAGER", "TECHNICIAN", "REGRESSION_TESTER", "REPORTER"]
)
def test_role_menu_permissions_match_admin_api_and_project_boundaries(session_client, business, workspace, role_name):
    base, project, people, owner = business
    user = people[role_name]
    session_client.force_authenticate(user=user)
    context = session_client.get(base + "context/")
    assert context.status_code == 200, context.data
    admin = role_name in {"PLATFORM_ADMIN", "PROJECT_MANAGER"}
    assert context.data["can_review_knowledge"] is admin
    assert context.data["can_configure_model"] is (role_name == "PLATFORM_ADMIN")
    for resource in ["roles/"]:
        assert session_client.get(base + resource).status_code == (200 if admin else 403)
    assert session_client.get(base + "collaboration-settings/").status_code == 200
    assert session_client.post(base + "collaboration-settings/", {}, format="json").status_code == (
        400 if admin else 403
    )
    for resource in ["cases/", "plans/", "defects/", "report/"]:
        assert session_client.get(base + resource).status_code == 200
    knowledge = base.replace("/quality/", "/knowledge/")
    assert session_client.get(knowledge + "articles/").status_code == (403 if role_name == "REPORTER" else 200)
    assert session_client.patch(
        knowledge + "configuration/", {"model": "blocked-model"}, format="json"
    ).status_code == (200 if role_name == "PLATFORM_ADMIN" else 403)
    other = Project.objects.create(workspace=workspace, name="无项目权限", identifier="NOPERM")
    other_base = base.replace(str(project.id), str(other.id))
    for resource in ["context/", "cases/", "plans/", "defects/", "report/", "roles/", "collaboration-settings/"]:
        assert session_client.get(other_base + resource).status_code == (200 if role_name == "PLATFORM_ADMIN" else 403)
    assert session_client.get(other_base.replace("/quality/", "/knowledge/") + "search/").status_code == (
        200 if role_name == "PLATFORM_ADMIN" else 403
    )


def test_business_manager_cannot_disable_policy_or_grant_platform_authority(session_client, business):
    base, project, people, admin = business
    session_client.force_authenticate(user=people["PROJECT_MANAGER"])
    assert session_client.post(base + "role-policy/", {"enabled": False}, format="json").status_code == 403
    assert (
        session_client.post(
            base + "roles/", {"user_id": str(people["PROJECT_MANAGER"].id), "role": "PLATFORM_ADMIN"}, format="json"
        ).status_code
        == 403
    )
    session_client.force_authenticate(user=people["REPORTER"])
    data = session_client.get(base + "context/").data
    assert not data["is_manager"] and data["capabilities"]["report"]


def test_technician_can_save_unchanged_assignment_and_cannot_reassign(session_client, business):
    base, project, people, admin = business
    session_client.force_authenticate(user=people["PROJECT_MANAGER"])
    defect = session_client.post(
        base + "defects/", {"title": "保存修复", "assignee_id": str(people["TECHNICIAN"].id)}, format="json"
    ).data
    session_client.force_authenticate(user=people["TECHNICIAN"])
    url = base + f"defects/{defect['id']}/"
    good = session_client.patch(
        url,
        {
            "assignee_id": str(people["TECHNICIAN"].id),
            "status": "resolved",
            "fixed_build": "v1",
            "resolution": "修复完成",
        },
        format="json",
    )
    assert good.status_code == 200, good.content
    assert (
        session_client.patch(url, {"assignee_id": str(people["REGRESSION_TESTER"].id)}, format="json").status_code
        == 403
    )


def test_policy_cannot_lock_out_managers_or_be_downgraded(session_client, business):
    from plane.quality.models import BusinessRole, ProjectRolePolicy

    base, project, people, admin = business
    session_client.force_authenticate(user=people["PLATFORM_ADMIN"])
    assert (
        session_client.post(
            base + "roles/", {"user_id": str(people["PLATFORM_ADMIN"].id), "roles": []}, format="json"
        ).status_code
        == 403
    )
    assert (
        session_client.post(
            base + "roles/", {"user_id": str(people["PROJECT_MANAGER"].id), "roles": []}, format="json"
        ).status_code
        == 200
    )
    assert session_client.post(base + "role-policy/", {"enabled": False}, format="json").status_code == 409
    ProjectRolePolicy.objects.filter(project=project).update(enabled=False)
    BusinessRole.objects.filter(project=project, role="PLATFORM_ADMIN").delete()
    session_client.force_authenticate(user=admin)
    assert session_client.post(base + "role-policy/", {"enabled": True}, format="json").status_code == 400


def test_reporter_cannot_assign_via_failed_execution_and_solution_author_retains_ownership(session_client, business):
    from plane.quality.models import TestCase, CaseRevision, TestPlan, PlanItem, TestExecution, Defect, Solution

    base, project, people, admin = business
    case = TestCase.objects.create(project=project, title="用例", steps=[{"action": "验证", "expected": "通过"}])
    rev = CaseRevision.objects.create(
        project=project, case=case, title=case.title, version=1, snapshot={"title": case.title, "steps": case.steps}
    )
    plan = TestPlan.objects.create(project=project, name="测试", build="v1", environment="本地")
    item = PlanItem.objects.create(project=project, plan=plan, case=case, revision=rev)
    execution = TestExecution.objects.create(project=project, item=item, request_id=uuid4(), result="failed")
    session_client.force_authenticate(user=people["REPORTER"])
    assert (
        session_client.post(
            base + f"executions/{execution.id}/defect/", {"assignee_id": str(people["REPORTER"].id)}, format="json"
        ).status_code
        == 403
    )
    defect = Defect.objects.create(project=project, title="转派", assignee=people["TECHNICIAN"])
    solution = Solution.objects.create(
        project=project,
        defect=defect,
        title="旧方案",
        created_by=people["TECHNICIAN"],
        root_cause="原因",
        steps="步骤",
        verification="验证",
    )
    defect.assignee = people["REGRESSION_TESTER"]
    defect.save()
    session_client.force_authenticate(user=people["TECHNICIAN"])
    assert (
        session_client.patch(
            base + f"solutions/{solution.id}/", {"title": "作者仍可维护", "expected_version": 1}, format="json"
        ).status_code
        == 200
    )
    assert (
        session_client.post(
            base + f"solutions/{solution.id}/submit/",
            {"expected_version": 2, "reviewer_ids": [str(people["PROJECT_MANAGER"].id)], "required_count": 1},
            format="json",
        ).status_code
        == 200
    )


def test_status_only_patch_preserves_legacy_owner_without_reassigning(session_client, business):
    """Old ownership remains readable; status edits must not resubmit a new assignment."""
    from plane.quality.models import Defect

    base, project, people, admin = business
    owner = people["PROJECT_MANAGER"]
    defect = Defect.objects.create(project=project, title="原负责人角色变更后的缺陷", assignee=owner)
    session_client.force_authenticate(user=owner)
    url = base + f"defects/{defect.id}/"
    rejected = session_client.patch(
        url, {"status": "in_progress", "assignee_id": str(owner.id), "expected_version": 1}, format="json"
    )
    assert rejected.status_code == 400
    updated = session_client.patch(url, {"status": "in_progress", "expected_version": 1}, format="json")
    assert updated.status_code == 200, updated.content
    assert updated.data["status"] == "in_progress"
    assert str(updated.data["assignee_id"]) == str(owner.id)
    severity = session_client.patch(url, {"severity": "minor", "expected_version": 2}, format="json")
    assert severity.status_code == 200, severity.content
    assert severity.data["severity"] == "minor"
    assert severity.data["status"] == "in_progress"
    assert str(severity.data["assignee_id"]) == str(owner.id)


def test_administrator_can_perform_technician_duty_without_duplicate_assignment(session_client, business):
    from plane.quality.models import BusinessRole, Defect
    from plane.quality.permissions import capable, has_role

    base, project, people, admin = business
    target = people["PLATFORM_ADMIN"]
    assert not BusinessRole.objects.filter(project=project, user=target).exists()
    assert capable(project.id, target.id, "manage_roles")
    assert capable(project.id, target.id, "manage_defect")
    assert has_role(project.id, target.id, "TECHNICIAN")
    own = Defect.objects.create(project=project, title="自己负责的修复", assignee=target)
    other = Defect.objects.create(project=project, title="其他人的修复", assignee=people["TECHNICIAN"])
    session_client.force_authenticate(user=target)
    assert (
        session_client.patch(base + f"defects/{own.id}/", {"status": "in_progress"}, format="json").status_code == 200
    )
    assert (
        session_client.patch(base + f"defects/{other.id}/", {"status": "in_progress"}, format="json").status_code == 200
    )
    assert session_client.get(base + "roles/").status_code == 200


def test_reporter_can_supplement_own_report_but_not_workflow_or_other_authors(session_client, business):
    from plane.quality.models import Defect

    base, project, people, owner = business
    reporter = people["REPORTER"]
    own = Defect.objects.create(project=project, created_by=reporter, title="本人上报", description="原描述")
    other = Defect.objects.create(project=project, created_by=people["TECHNICIAN"], title="他人上报")
    session_client.force_authenticate(user=reporter)
    url = base + f"defects/{own.id}/report/"
    saved = session_client.patch(
        url, {"expected_version": 1, "description": "新增重现步骤", "affected_build": "v1"}, format="json"
    )
    assert saved.status_code == 200, saved.content
    own.refresh_from_db()
    assert own.description == "新增重现步骤" and own.status == "open" and own.created_by_id == reporter.id
    assert own.events.filter(created_by=reporter, note__contains="上报信息").exists()
    assert session_client.patch(url, {"expected_version": 1, "title": "过期覆盖"}, format="json").status_code == 409
    assert session_client.patch(url, {"expected_version": 2, "status": "closed"}, format="json").status_code == 400
    assert (
        session_client.patch(
            base + f"defects/{other.id}/report/", {"expected_version": 1, "description": "越权修改"}, format="json"
        ).status_code
        == 403
    )
    own.status = "closed"
    own.save(update_fields=["status"])
    assert (
        session_client.patch(url, {"expected_version": 2, "description": "关闭后改写"}, format="json").status_code
        == 409
    )
