"""Statistics card drilldowns retain full intersection scope before count/pagination."""

from datetime import datetime, timezone
import pytest
from plane.db.models import Project, ProjectMember, User
from plane.quality.models import Defect, SourceLink

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def drilldown(session_client, workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="统计明细", identifier="DRILLSTAT")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    for status in ["open", "in_progress", "resolved", "closed"]:
        defect = Defect.objects.create(
            project=project, title=f"我的{status}", status=status, assignee=create_user, severity="major"
        )
        Defect.objects.filter(pk=defect.id).update(created_at=datetime(2026, 11, 10, 15, 30, tzinfo=timezone.utc))
        for index in range(2):
            SourceLink.objects.create(
                project=project,
                defect=defect,
                source_system="DAQ",
                record_type="defect",
                record_id=f"{status}{index}",
                source_instance="audit",
                device="robot",
            )
    other = User.objects.create(username="drill-other", email="drill-other@local.test")
    Defect.objects.create(project=project, title="不是我的", status="open", assignee=other)
    hidden = Project.objects.create(workspace=workspace, name="别的项目", identifier="DRILLHIDDEN")
    Defect.objects.create(project=hidden, title="无权查看", status="open", assignee=create_user)
    return f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/", project


@pytest.mark.parametrize("status,expected", [(None, 3), ("open", 1), ("resolved", 1), ("closed", 0)])
def test_unclosed_preserves_view_status_date_and_distinct_sources(session_client, drilldown, status, expected):
    base, project = drilldown
    query = {"view": "assigned_to_me", "device": "robot", "created_after": "2026-11-10", "created_before": "2026-11-10"}
    if status:
        query["status"] = status
    stats = session_client.get(base + "defect-statistics/", query)
    detail = session_client.get(base + "defects/", {**query, "exclude_status": "closed", "page": 1, "per_page": 1})
    assert stats.status_code == detail.status_code == 200, (stats.content, detail.content)
    assert stats.data["unclosed"] == detail.data["count"] == expected
    assert len(detail.data["results"]) == min(expected, 1)
    assert session_client.get(base + "defects/", {**query, "exclude_status": "madeup"}).status_code == 400


def test_date_and_revoked_project_scope_stay_closed(session_client, drilldown):
    base, project = drilldown
    empty = session_client.get(
        base + "defects/", {"exclude_status": "closed", "created_after": "2026-11-11", "created_before": "2026-11-11"}
    )
    assert empty.status_code == 200 and empty.data["count"] == 0
    ProjectMember.objects.filter(project=project).update(is_active=False)
    assert session_client.get(base + "defects/", {"exclude_status": "closed"}).status_code == 403


def test_multiple_status_exclusions_keep_intersection(session_client, drilldown):
    base, _ = drilldown
    response = session_client.get(
        base + "defects/?view=assigned_to_me&exclude_status=closed&exclude_status=open&device=robot"
    )
    assert response.status_code == 200 and response.data["count"] == 2, response.data
