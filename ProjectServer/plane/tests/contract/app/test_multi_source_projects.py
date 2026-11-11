import pytest
from plane.db.models import Project, ProjectMember
from plane.quality.models import PlatformProject, PlatformIdentity, DaqBinding, DataRegression
from plane.quality.platform import verify_identity, verify_binding

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def test_multiple_projects_share_native_project_without_changing_source(session_client, workspace, create_user, mocker):
    p = Project.objects.create(workspace=workspace, name="统筹项目", identifier="MULTISRC")
    ProjectMember.objects.create(project=p, member=create_user, role=20)
    base = f"/api/workspaces/{workspace.slug}/projects/{p.id}/quality/"
    for external in (3, 8):
        response = session_client.post(base + "daq/project-mapping/", {"source_instance": "test", "external_project_id": external, "name": f"来源{external}"}, format="json")
        assert response.status_code == 201
    assert len(session_client.get(base + "integrations/").data["projects"]) == 2
    identity = PlatformIdentity.objects.create(project=p, user=create_user, source_instance="test", external_user_id=16)
    mocker.patch("plane.quality.platform.fetch", side_effect=[{"id": 16, "active": True, "role": "Collector"}, {"projects": [{"id": 8}]}])
    assert verify_identity(identity).external_project_id == 8
    assert PlatformProject.objects.filter(project=p).count() == 2
