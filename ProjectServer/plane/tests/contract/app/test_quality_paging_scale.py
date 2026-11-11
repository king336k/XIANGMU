"""Large result sets stay server-paginated and preserve query filters."""

import pytest
from rest_framework.test import APIClient
from plane.db.models import Project, ProjectMember
from plane.quality.models import Defect

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def test_thousand_defects_can_jump_to_last_page_with_server_limit(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="Paging scale", identifier="PGS")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    Defect.objects.bulk_create(
        [
            Defect(project=project, created_by=create_user, title=f"Paged defect {number}", status="open")
            for number in range(1005)
        ]
    )
    browser = APIClient()
    browser.force_authenticate(create_user)
    endpoint = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/defects/"
    for size, page, expected in [(20, 51, 5), (50, 21, 5), (100, 11, 5)]:
        response = browser.get(endpoint, {"per_page": size, "page": page, "status": "open"})
        assert response.status_code == 200
        assert response.data["count"] == 1005
        assert len(response.data["results"]) == expected
    capped = browser.get(endpoint, {"per_page": 100000})
    assert len(capped.data["results"]) == 100
