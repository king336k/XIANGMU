import pytest
from django.db import IntegrityError, transaction
from plane.db.models import Issue, Project, ProjectMember
from plane.quality.models import Requirement

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def test_requirements_have_independent_stable_numbers(session_client, workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="独立编号", identifier="NUM")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    for index in range(3):
        Issue.objects.create(project=project, workspace=workspace, name=f"普通任务{index}")
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/"
    first = session_client.post(base + "requirements/", {"title": "第一个需求"}, format="json")
    second = session_client.post(base + "requirements/", {"title": "第二个需求"}, format="json")
    assert first.status_code == second.status_code == 201
    assert first.data["number"] == 1 and first.data["code"] == "NUM-R-1"
    assert second.data["number"] == 2 and second.data["code"] == "NUM-R-2"
    assert first.data["sequence_id"] != first.data["number"]
    updated = session_client.patch(
        base + f"requirements/{first.data['id']}/", {"title": "修改需求标题", "expected_version": 1}, format="json"
    )
    assert updated.data["code"] == "NUM-R-1"
    index = session_client.get(base + "work-item-kinds/").data
    assert index["requirement_numbers"][str(first.data["sequence_id"])] == 1
    native = f"/api/workspaces/{workspace.slug}/work-items/"
    assert str(session_client.get(native + "NUM-R-1/").data["id"]) == first.data["id"]
    assert str(session_client.get(native + f"NUM-{first.data['sequence_id']}/").data["id"]) == first.data["id"]
    assert session_client.get(native + f"NUM-T-{first.data['sequence_id']}/").status_code == 404


def test_requirement_number_unique_per_project(workspace):
    project = Project.objects.create(workspace=workspace, name="编号约束", identifier="UNUM")
    first = Issue.objects.create(project=project, workspace=workspace, name="A")
    second = Issue.objects.create(project=project, workspace=workspace, name="B")
    req = Requirement.objects.create(project=project, issue=first)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Requirement.objects.create(project=project, issue=second, number=req.number)
