"""Removed data-platform coupling is a closed API surface, including administrator calls."""

import pytest
from plane.db.models import Project, ProjectMember
from plane.quality.models import PlatformIdentity, PlatformProject

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.mark.parametrize(
    "suffix", ["integrations/?page=1", "integrations/?page=101&search=tail", "integrations/?page=invalid"]
)
@pytest.mark.parametrize("method", ["get", "post"])
def test_retired_integration_route_is_closed_without_outbound_or_mutation(
    session_client, workspace, create_user, mocker, suffix, method
):
    project = Project.objects.create(workspace=workspace, name="独立项目", identifier="RETIRE")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    outbound = mocker.patch("plane.quality.platform.fetch", side_effect=AssertionError("No external authority"))
    url = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/" + suffix
    response = getattr(session_client, method)(url)
    assert response.status_code == 404, response.content
    outbound.assert_not_called()
    assert not PlatformIdentity.objects.filter(project=project).exists()
    assert not PlatformProject.objects.filter(project=project).exists()
