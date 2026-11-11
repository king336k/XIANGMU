import pytest
from plane.db.models import Project, ProjectMember, Issue

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def test_work_item_options_search_old_records_and_page_with_project_scope(session_client, workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="任务选择", identifier="SEL")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    first = Issue.objects.create(project=project, workspace=workspace, name="旧任务重点")
    for n in range(205):
        Issue.objects.create(project=project, workspace=workspace, name=f"最新任务{n}")
    endpoint = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/work-item-options/"
    response = session_client.get(endpoint, {"search": "旧任务重点", "per_page": 20})
    assert response.status_code == 200
    assert response.data["count"] == 1 and response.data["results"][0]["id"] == str(first.id)
    assert response.data["results"][0]["code"] == "SEL-T-1"
    page = session_client.get(endpoint, {"page": 11, "per_page": 20})
    assert page.data["count"] == 206 and len(page.data["results"]) == 6
    other = Project.objects.create(workspace=workspace, name="其他项目", identifier="OTHERSEL")
    Issue.objects.create(project=other, workspace=workspace, name="外部私有")
    assert session_client.get(endpoint, {"search": "外部私有"}).data["count"] == 0
