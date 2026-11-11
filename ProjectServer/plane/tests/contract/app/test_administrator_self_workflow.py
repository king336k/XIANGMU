"""Administrators may complete their own approval; ordinary contributors may not."""

from uuid import uuid4
import pytest
from django.utils import timezone
from plane.db.models import Project, ProjectMember
from plane.license.models import Instance, InstanceAdmin
from plane.quality.models import BusinessRole, ProjectRolePolicy, Defect, Solution, SolutionRevision, SolutionReview

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.mark.parametrize("identity", ["canonical", "legacy", "manager"])
def test_administrator_can_submit_and_review_own_solution_without_second_admin(
    session_client, workspace, create_user, identity
):
    actor = create_user
    project = Project.objects.create(workspace=workspace, name="自己闭环", identifier="SELF")
    ProjectMember.objects.create(project=project, member=actor, role=15)
    ProjectRolePolicy.objects.create(project=project, enabled=True)
    instance = Instance.objects.create(
        instance_name="管理员", instance_id=str(uuid4()), current_version="test", last_checked_at=timezone.now()
    )
    if identity == "canonical":
        InstanceAdmin.objects.create(instance=instance, user=actor)
    else:
        BusinessRole.objects.create(
            project=project,
            user=actor,
            role="PLATFORM_ADMIN" if identity == "legacy" else "PROJECT_MANAGER",
            additional_roles=["TECHNICIAN"] if identity == "manager" else [],
        )
    defect = Defect.objects.create(project=project, title="自己的缺陷", assignee=actor, created_by=actor)
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/"
    solution = session_client.post(
        base + "solutions/",
        {
            "defect_id": str(defect.id),
            "title": "自己的方案",
            "root_cause": "原因",
            "steps": "修复",
            "verification": "验证",
        },
        format="json",
    )
    assert solution.status_code == 201, solution.data
    sid = solution.data["id"]
    submitted = session_client.post(
        base + f"solutions/{sid}/submit/",
        {"expected_version": 1, "reviewer_ids": [str(actor.id)], "required_count": 1},
        format="json",
    )
    if identity == "manager":
        assert submitted.status_code == 400
        return
    assert submitted.status_code == 200, submitted.data
    revision = submitted.data["revisions"][0]
    approved = session_client.post(
        base + f"solutions/{sid}/review/", {"revision_id": revision["id"], "decision": "approve"}, format="json"
    )
    assert approved.status_code == 200, approved.data
    assert approved.data["status"] == "approved"
    assert Solution.objects.get(pk=sid).created_by_id == actor.id
    assert SolutionRevision.objects.get(pk=revision["id"]).created_by_id == actor.id
    assert SolutionReview.objects.get(revision_id=revision["id"]).created_by_id == actor.id
