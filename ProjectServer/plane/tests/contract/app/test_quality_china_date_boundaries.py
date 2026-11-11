"""List filters and statistics use the same China calendar, regardless of account timezone."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from plane.db.models import Project, ProjectMember
from plane.quality.models import Defect

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.mark.parametrize("user_zone", ["UTC", "America/Los_Angeles", "Asia/Shanghai"])
def test_defect_date_filters_and_statistics_include_entire_china_day(session_client, workspace, create_user, user_zone):
    create_user.user_timezone = user_zone
    create_user.save(update_fields=["user_timezone"])
    project = Project.objects.create(workspace=workspace, name="中国日期边界", identifier="CN160")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    ids = []
    for timestamp in ["2026-10-30T23:59:59", "2026-10-31T00:00:00", "2026-10-31T23:59:59", "2026-11-01T00:00:00"]:
        row = Defect.objects.create(project=project, title=timestamp)
        Defect.objects.filter(pk=row.pk).update(created_at=datetime.fromisoformat(timestamp).replace(tzinfo=ZoneInfo("Asia/Shanghai")))
        ids.append(str(row.id))
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/"
    with timezone.override(user_zone):
        for query, expected in [
            ({"created_after": "2026-10-31", "created_before": "2026-10-31"}, ids[1:3]),
            ({"created_after": "2026-10-31"}, ids[1:]),
            ({"created_before": "2026-10-31"}, ids[:3]),
        ]:
            listed = session_client.get(base + "defects/", query)
            assert listed.status_code == 200, listed.content
            assert {row["id"] for row in listed.data["results"]} == set(expected)
            stats = session_client.get(base + "defect-statistics/", query)
            assert stats.status_code == 200 and stats.data["total"] == len(expected), stats.content
        for query, count in [
            ({"start": "2026-10-31", "end": "2026-10-31"}, 2),
            ({"start": "2026-10-31"}, 3),
            ({"end": "2026-10-31"}, 3),
        ]:
            stats = session_client.get(base + "defect-statistics/", query)
            assert stats.status_code == 200 and stats.data["total"] == count, stats.content
