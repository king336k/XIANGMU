import pytest
from plane.db.models import Project, ProjectMember

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def test_saved_view_preserves_layout_and_renames_with_conflict_guard(session_client, workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="视图管理", identifier="VLAY")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/saved-views/"
    created = session_client.post(
        base,
        {"resource": "defects", "name": "待修复看板", "filters": {"layout": "board", "status": "open"}},
        format="json",
    )
    assert created.status_code == 201, created.content
    url = base + str(created.data["id"]) + "/"
    renamed = session_client.patch(url, {"name": "我的缺陷看板", "expected_name": "待修复看板"}, format="json")
    assert renamed.status_code == 200 and renamed.data["filters"]["layout"] == "board"
    assert session_client.patch(url, {"name": "覆盖", "expected_name": "待修复看板"}, format="json").status_code == 409
    bad = session_client.post(
        base, {"resource": "requirements", "name": "无效布局", "filters": {"layout": "external-url"}}, format="json"
    )
    assert bad.status_code == 400
