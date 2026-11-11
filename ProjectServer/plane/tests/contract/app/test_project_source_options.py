import pytest
from django.utils import timezone
from plane.db.models import User
from plane.db.models import Project, ProjectMember
from plane.license.models import Instance, InstanceAdmin

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def test_source_options_show_only_configured_platforms_without_credentials(session_client, workspace, create_user, mocker):
    project = Project.objects.create(workspace=workspace, name="来源选择", identifier="SRCSEL")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    instance = Instance.objects.create(instance_name="本机测试", instance_id="source-select", current_version="test", last_checked_at=timezone.now())
    InstanceAdmin.objects.create(instance=instance, user=create_user)
    config = {"source-a": {"kind": "data_platform", "base_url": "https://source.example", "service_token": "private-value", "configured_by": str(create_user.id)}}
    mocker.patch("plane.quality.source_options.connections", return_value=config)
    mocker.patch("plane.quality.source_options.pages", return_value=([
        {"id": 8, "name": "采集项目", "status": "InProgress"},
        {"id": 9, "name": "已归档", "status": "Archived"},
    ], "stamp"))
    url = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/integrations/project-options/"
    response = session_client.get(url, {"source_instance": "source-a"})
    assert response.status_code == 200
    assert response.data["projects"] == [{"id": 8, "name": "采集项目", "status": "InProgress"}]
    assert "private-value" not in str(response.data)
    assert response.data["sources"][0]["id"] == "source-a"
    assert session_client.get(url, {"source_instance": "unknown"}).status_code == 400


def test_local_project_manager_cannot_enumerate_unrelated_external_projects(session_client, workspace, create_user, mocker):
    project = Project.objects.create(workspace=workspace, name="项目管理", identifier="SRCMGR")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    owner = User.objects.create(username="source-owner", email="source-owner@local.invalid")
    instance = Instance.objects.create(instance_name="本机测试", instance_id="source-manager", current_version="test", last_checked_at=timezone.now())
    InstanceAdmin.objects.create(instance=instance, user=owner)
    mocker.patch("plane.quality.source_options.connections", return_value={"source-a": {"kind": "data_platform", "service_token": "test-only", "configured_by": str(owner.id)}})
    fetch = mocker.patch("plane.quality.source_options.pages")
    response = session_client.get(f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/integrations/project-options/", {"source_instance": "source-a"})
    assert response.status_code == 403
    fetch.assert_not_called()
