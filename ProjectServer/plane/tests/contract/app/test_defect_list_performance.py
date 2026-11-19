"""Defect lists batch related data and defer full histories until a detail request."""
from django.db import connection
from django.test.utils import CaptureQueriesContext
import pytest
from rest_framework.test import APIClient
from plane.db.models import Project, ProjectMember
from plane.quality.models import Defect, DefectEvent, DefectCollaborator, SourceLink

pytestmark = [pytest.mark.contract, pytest.mark.django_db]

@pytest.fixture
def collection(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="List performance", identifier="FAST")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    for index in range(20):
        defect = Defect.objects.create(project=project, created_by=create_user, title=f"Defect {index}")
        DefectEvent.objects.create(project=project, defect=defect, created_by=create_user,
            status="open", note="Actual historical observation " * 100)
        DefectCollaborator.objects.create(project=project, defect=defect, user=create_user)
        SourceLink.objects.create(project=project, defect=defect, source_system="ENGRAM_DAQ",
            source_instance="unsigned-test", record_type="daq_incident", record_id=str(index))
    client = APIClient(); client.force_authenticate(create_user)
    return client, f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/defects/"

def test_summary_defers_history_but_detail_and_default_list_preserve_it(collection):
    client, url = collection
    summary = client.get(url, {"summary": "true", "per_page": 20})
    assert summary.status_code == 200
    row = summary.data["results"][0]
    assert row["events"] == []
    assert row["collaborators"] and row["code"].startswith("FAST-D-")
    assert not row.get("reporter"), "unsigned sources must never become trusted reporters"
    detail = client.get(url + row["id"] + "/")
    assert detail.status_code == 200 and len(detail.data["events"]) == 1
    normal = client.get(url, {"per_page": 20})
    assert normal.status_code == 200 and len(normal.data["results"][0]["events"]) == 1

def test_list_query_count_does_not_grow_with_page_size(collection):
    client, url = collection
    counts = []
    for size in (5, 20):
        with CaptureQueriesContext(connection) as queries:
            response = client.get(url, {"summary": "true", "per_page": size})
            assert response.status_code == 200 and len(response.data["results"]) == size
        counts.append(len(queries))
    assert counts[1] <= counts[0] + 2, counts
    assert counts[1] <= 30, counts
