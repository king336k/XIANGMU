"""Action hints must reflect the same scope, current owner and revision as writes."""

from uuid import uuid4
import pytest
from django.utils import timezone
from plane.db.models import Project, ProjectMember, User, WorkspaceMember
from plane.quality.models import BusinessRole, ProjectRolePolicy, Defect, Solution, SolutionRevision, SolutionReview

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def solution_scope(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="方案权限", identifier="SFLAGS")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    ProjectRolePolicy.objects.create(project=project, enabled=True)
    BusinessRole.objects.create(project=project, user=create_user, role="PROJECT_MANAGER")
    people = {}
    for key, duty in [("old", "TECHNICIAN"), ("new", "TECHNICIAN"), ("reviewer", "PROJECT_MANAGER")]:
        user = User.objects.create(email=f"{key}@solution-flags.local", username=f"sflags-{key}")
        WorkspaceMember.objects.create(workspace=workspace, member=user, role=15)
        ProjectMember.objects.create(project=project, member=user, role=15)
        BusinessRole.objects.create(project=project, user=user, role=duty)
        people[key] = user
    defect = Defect.objects.create(project=project, created_by=create_user, title="缺陷", assignee=people["new"])
    solution = Solution.objects.create(
        project=project,
        defect=defect,
        created_by=people["old"],
        title="方案",
        root_cause="原因",
        steps="修复",
        verification="验证",
    )
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/"
    return project, base, people, defect, solution, create_user


def detail(client, base, solution):
    return client.get(base + f"solutions/{solution.id}/")


def test_reassigned_owner_flags_match_real_author_rule_and_readonly_boundaries(session_client, solution_scope):
    project, base, people, defect, solution, manager = solution_scope
    session_client.force_authenticate(people["old"])
    old = detail(session_client, base, solution)
    assert old.status_code == 200 and old.data["can_edit"] and old.data["can_submit"]
    edited = session_client.patch(
        base + f"solutions/{solution.id}/", {"expected_version": 1, "title": "作者继续维护"}, format="json"
    )
    assert edited.status_code == 200 and edited.data["can_edit"]
    session_client.force_authenticate(people["new"])
    current = detail(session_client, base, solution).data
    assert not current["can_edit"] and not current["can_submit"] and not current["can_review"]
    listing = session_client.get(base + "solutions/", {"defect_id": str(defect.id)})
    assert listing.status_code == 200 and listing.data["can_create"]
    denied = session_client.patch(
        base + f"solutions/{solution.id}/", {"expected_version": 2, "title": "接手不改他人方案"}, format="json"
    )
    assert denied.status_code == 403
    ProjectRolePolicy.objects.filter(project=project).update(enabled=False)
    ProjectMember.objects.filter(project=project, member=people["new"]).update(role=5)
    readonly = detail(session_client, base, solution).data
    assert not any(readonly[key] for key in ["can_edit", "can_submit", "can_review"])
    assert not session_client.get(base + "solutions/", {"defect_id": str(defect.id)}).data["can_create"]


def test_current_revision_selected_by_version_and_review_flag_disappears_after_vote(session_client, solution_scope):
    project, base, people, defect, solution, manager = solution_scope
    solution.status, solution.submitted_version = "review", 2
    solution.save()
    current = SolutionRevision.objects.create(
        project=project,
        solution=solution,
        created_by=people["new"],
        version=2,
        snapshot={"contributor_ids": [str(people["new"].id)]},
        reviewer_ids=[str(people["reviewer"].id), str(manager.id)],
        required_count=2,
    )
    old = SolutionRevision.objects.create(
        project=project,
        solution=solution,
        created_by=people["old"],
        version=1,
        snapshot={},
        reviewer_ids=[str(people["reviewer"].id)],
        required_count=1,
    )
    session_client.force_authenticate(people["reviewer"])
    before = detail(session_client, base, solution).data
    assert before["current_revision_id"] == str(current.id) and before["revisions"][0]["id"] == str(current.id)
    assert before["can_review"] and not before["can_edit"]
    assert (
        session_client.post(
            base + f"solutions/{solution.id}/review/",
            {"revision_id": str(old.id), "decision": "approve"},
            format="json",
        ).status_code
        == 409
    )
    vote = {"revision_id": str(current.id), "decision": "approve", "comment": "通过"}
    reviewed = session_client.post(base + f"solutions/{solution.id}/review/", vote, format="json")
    assert reviewed.status_code == 200 and reviewed.data["status"] == "review" and not reviewed.data["can_review"]
    assert session_client.post(base + f"solutions/{solution.id}/review/", vote, format="json").status_code == 200
    assert (
        session_client.post(
            base + f"solutions/{solution.id}/review/", {**vote, "decision": "reject", "comment": "改投"}, format="json"
        ).status_code
        == 409
    )
    assert SolutionReview.objects.filter(revision=current, created_by=people["reviewer"]).count() == 1
    solution.refresh_from_db()
    solution.submitted_version = 1
    solution.save()
    assert detail(session_client, base, solution).data["current_revision_id"] is None
    assert (
        session_client.post(
            base + f"solutions/{solution.id}/review/",
            {"revision_id": str(old.id), "decision": "approve"},
            format="json",
        ).status_code
        == 409
    )


def test_native_author_and_strict_role_downgrade_flags_follow_write_permission(session_client, solution_scope):
    project, base, people, defect, solution, manager = solution_scope
    ProjectRolePolicy.objects.filter(project=project).update(enabled=False)
    session_client.force_authenticate(people["old"])
    assert detail(session_client, base, solution).data["can_edit"]
    session_client.force_authenticate(people["new"])
    assert not detail(session_client, base, solution).data["can_edit"]
    ProjectRolePolicy.objects.filter(project=project).update(enabled=True)
    BusinessRole.objects.filter(project=project, user=people["new"]).update(role="REGRESSION_TESTER")
    assert not detail(session_client, base, solution).data["can_edit"]
    assert not session_client.get(base + "solutions/", {"defect_id": str(defect.id)}).data["can_create"]
    assert (
        session_client.patch(
            base + f"solutions/{solution.id}/", {"expected_version": 1, "title": "测试员不改方案"}, format="json"
        ).status_code
        == 403
    )


@pytest.mark.parametrize("state", ["closed", "archived"])
def test_closed_or_archived_defect_keeps_solution_content_readonly(session_client, solution_scope, state):
    project, base, people, defect, solution, manager = solution_scope
    if state == "closed":
        defect.status = "closed"
    else:
        defect.archived_at = timezone.now()
    defect.save()
    session_client.force_authenticate(people["new"])
    data = detail(session_client, base, solution).data
    assert data["title"] == "方案" and not any(data[key] for key in ["can_edit", "can_submit", "can_review"])
    assert not session_client.get(base + "solutions/", {"defect_id": str(defect.id)}).data["can_create"]
    assert (
        session_client.patch(
            base + f"solutions/{solution.id}/", {"expected_version": 1, "title": "关闭后修改"}, format="json"
        ).status_code
        == 409
    )
    assert (
        session_client.post(
            base + f"solutions/{solution.id}/submit/",
            {"expected_version": 1, "reviewer_ids": [str(people["reviewer"].id)], "required_count": 1},
            format="json",
        ).status_code
        == 409
    )
    assert (
        session_client.post(
            base + "solutions/",
            {
                "defect_id": str(defect.id),
                "title": "新增",
                "root_cause": "根因",
                "steps": "修复",
                "verification": "验证",
            },
            format="json",
        ).status_code
        == 409
    )
    revision = SolutionRevision.objects.create(
        project=project,
        solution=solution,
        created_by=people["new"],
        version=1,
        snapshot={},
        reviewer_ids=[str(people["reviewer"].id)],
        required_count=1,
    )
    solution.status, solution.submitted_version = "review", 1
    solution.save()
    session_client.force_authenticate(people["reviewer"])
    assert not detail(session_client, base, solution).data["can_review"]
    assert (
        session_client.post(
            base + f"solutions/{solution.id}/review/",
            {"revision_id": str(revision.id), "decision": "approve"},
            format="json",
        ).status_code
        == 409
    )
    assert SolutionReview.objects.filter(revision=revision).count() == 0


@pytest.mark.parametrize("readonly_scope", ["project", "workspace"])
def test_nonstrict_readonly_author_has_no_solution_write_hints_or_permissions(
    session_client, solution_scope, readonly_scope
):
    project, base, people, defect, solution, manager = solution_scope
    ProjectRolePolicy.objects.filter(project=project).update(enabled=False)
    actor = people["old"]
    session_client.force_authenticate(actor)
    assert detail(session_client, base, solution).data["can_edit"]
    if readonly_scope == "project":
        ProjectMember.objects.filter(project=project, member=actor).update(role=5)
    else:
        WorkspaceMember.objects.filter(workspace=project.workspace, member=actor).update(role=5)
    response = detail(session_client, base, solution)
    assert response.status_code == 200 and not any(response.data[k] for k in ["can_edit", "can_submit", "can_review"])
    assert not session_client.get(base + "solutions/", {"defect_id": str(defect.id)}).data["can_create"]
    assert (
        session_client.patch(
            base + f"solutions/{solution.id}/", {"expected_version": 1, "title": "只读作者"}, format="json"
        ).status_code
        == 403
    )


def test_contributors_cannot_self_review_and_role_downgrade_revokes_selected_reviewer(session_client, solution_scope):
    project, base, people, defect, solution, manager = solution_scope
    solution.created_by = people["new"]
    solution.save(update_fields=["created_by"])
    BusinessRole.objects.filter(project=project, user=people["new"]).update(additional_roles=["PROJECT_MANAGER"])
    session_client.force_authenticate(people["new"])
    own = session_client.post(
        base + f"solutions/{solution.id}/submit/",
        {"expected_version": 1, "reviewer_ids": [str(people["new"].id)], "required_count": 1},
        format="json",
    )
    assert own.status_code == 400
    submitted = session_client.post(
        base + f"solutions/{solution.id}/submit/",
        {"expected_version": 1, "reviewer_ids": [str(people["reviewer"].id)], "required_count": 1},
        format="json",
    )
    assert submitted.status_code == 200 and not submitted.data["can_edit"] and not submitted.data["can_submit"]
    revision_id = submitted.data["current_revision_id"]
    session_client.force_authenticate(people["reviewer"])
    assert detail(session_client, base, solution).data["can_review"]
    BusinessRole.objects.filter(project=project, user=people["reviewer"]).update(role="REGRESSION_TESTER")
    assert not detail(session_client, base, solution).data["can_review"]
    assert (
        session_client.post(
            base + f"solutions/{solution.id}/review/",
            {"revision_id": revision_id, "decision": "approve"},
            format="json",
        ).status_code
        == 403
    )


def test_canonical_admin_self_review_only_when_explicitly_selected(session_client, solution_scope):
    from plane.license.models import Instance, InstanceAdmin

    project, base, people, defect, solution, manager = solution_scope
    instance = Instance.objects.create(
        instance_name="测试管理", instance_id=str(uuid4()), current_version="test", last_checked_at=timezone.now()
    )
    solution.created_by = people["new"]
    solution.save(update_fields=["created_by"])
    InstanceAdmin.objects.create(instance=instance, user=people["new"])
    InstanceAdmin.objects.create(instance=instance, user=manager)
    session_client.force_authenticate(people["new"])
    submitted = session_client.post(
        base + f"solutions/{solution.id}/submit/",
        {"expected_version": 1, "reviewer_ids": [str(people["new"].id)], "required_count": 1},
        format="json",
    )
    assert submitted.status_code == 200 and submitted.data["can_review"]
    revision_id = submitted.data["current_revision_id"]
    session_client.force_authenticate(manager)
    assert not detail(session_client, base, solution).data["can_review"]
    assert (
        session_client.post(
            base + f"solutions/{solution.id}/review/",
            {"revision_id": revision_id, "decision": "approve"},
            format="json",
        ).status_code
        == 403
    )
    session_client.force_authenticate(people["new"])
    approved = session_client.post(
        base + f"solutions/{solution.id}/review/", {"revision_id": revision_id, "decision": "approve"}, format="json"
    )
    assert approved.status_code == 200 and approved.data["status"] == "approved" and not approved.data["can_review"]


@pytest.mark.django_db(transaction=True)
def test_concurrent_opposite_votes_cannot_rewrite_first_decision(session_client, solution_scope):
    from concurrent.futures import ThreadPoolExecutor
    from django.db import close_old_connections
    from rest_framework.test import APIClient

    project, base, people, defect, solution, manager = solution_scope
    solution.status, solution.submitted_version = "review", 1
    solution.save()
    revision = SolutionRevision.objects.create(
        project=project,
        solution=solution,
        created_by=people["new"],
        version=1,
        snapshot={},
        reviewer_ids=[str(people["reviewer"].id)],
        required_count=1,
    )

    def vote(decision):
        close_old_connections()
        try:
            client = APIClient()
            client.force_authenticate(people["reviewer"])
            return client.post(
                base + f"solutions/{solution.id}/review/",
                {"revision_id": str(revision.id), "decision": decision, "comment": "并发决定"},
                format="json",
            ).status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(vote, ["approve", "reject"])) == [200, 409]
    assert SolutionReview.objects.filter(revision=revision).count() == 1
