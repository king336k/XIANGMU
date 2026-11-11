import pytest
from plane.db.models import Project, ProjectMember

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def test_project_menu_visibility_is_shared_and_keeps_existing_features(session_client, workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="无需测试的项目", identifier="MENU", cycle_view=True)
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    path = f"/api/workspaces/{workspace.slug}/projects/{project.id}/"
    response = session_client.patch(path, {"hidden_menu_items": ["quality", "versions"]}, format="json")
    assert response.status_code == 200, response.content
    assert response.data["hidden_menu_items"] == ["quality", "versions"]
    project.refresh_from_db()
    assert project.hidden_menu_items == ["quality", "versions"] and project.cycle_view
    assert session_client.get(path).data["hidden_menu_items"] == ["quality", "versions"]
    assert session_client.patch(path, {"hidden_menu_items": []}, format="json").status_code == 200


@pytest.mark.parametrize(
    "hidden",
    [
        ["unknown"],
        ["quality", "quality"],
        ["requirements", "work_items", "defects", "quality", "versions", "knowledge"],
    ],
)
def test_project_menu_settings_reject_invalid_or_empty_menu(session_client, workspace, create_user, hidden):
    project = Project.objects.create(workspace=workspace, name="菜单校验", identifier="MENUVAL")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    response = session_client.patch(
        f"/api/workspaces/{workspace.slug}/projects/{project.id}/", {"hidden_menu_items": hidden}, format="json"
    )
    assert response.status_code == 400, response.content
