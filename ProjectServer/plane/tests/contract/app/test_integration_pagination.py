import pytest
from plane.db.models import Project, ProjectMember, Issue
from plane.quality.models import PlatformProject, DaqBinding, PlatformIdentity

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def test_source_inventory_paginates_and_searches_without_dropping_tail(session_client, workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="集成分页", identifier="IPAGE")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    PlatformProject.objects.bulk_create(
        [
            PlatformProject(project=project, source_instance="test", external_project_id=i + 1, name=f"来源项目{i + 1}")
            for i in range(125)
        ]
    )
    issue = Issue.objects.create(project=project, workspace=workspace, name="采集任务")
    DaqBinding.objects.bulk_create(
        [
            DaqBinding(
                project=project,
                issue=issue,
                source_instance="test",
                platform_task_id=i + 1,
                source_record_id=f"session-{i + 1}",
                package_id=f"pkg-{i + 1}",
            )
            for i in range(125)
        ]
    )
    endpoint = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/integrations/"
    for group in ["project", "binding"]:
        page = session_client.get(endpoint, {"kind": group, "page": 7, "per_page": 20})
        assert page.status_code == 200
        assert page.data["count"] == 125
        assert len(page.data["results"]) == 5
    found = session_client.get(endpoint, {"kind": "binding", "search": "session-125", "per_page": 20})
    assert found.data["count"] == 1 and found.data["results"][0]["session_id"] == "session-125"
    assert len(session_client.get(endpoint).data["bindings"]) == 100


def test_inventory_page_kind_is_validated_and_permissions_preserved(session_client, workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="集成权限", identifier="IPERM")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    endpoint = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/integrations/"
    assert session_client.get(endpoint, {"kind": "invalid"}).status_code == 400
    ProjectMember.objects.filter(project=project, member=create_user).update(role=15)
    assert session_client.get(endpoint, {"kind": "identity", "page": 1}).status_code == 403
