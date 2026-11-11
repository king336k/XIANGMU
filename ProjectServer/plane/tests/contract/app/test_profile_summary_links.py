import json
from datetime import date
import pytest
from rest_framework.test import APIClient
from plane.db.models import Issue, IssueAssignee, IssueSubscriber, Project, ProjectMember, State, User

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def summary_records(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="Summary", identifier="SUM")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    state = State.objects.create(project=project, name="Done", group="completed")
    issue = Issue.objects.create(project=project, name="Visible", state=state, priority="high", created_by=create_user)
    IssueAssignee.objects.create(project=project, issue=issue, assignee=create_user)
    other = User.objects.create(username="another-assignee", email="another@example.test")
    IssueAssignee.objects.create(project=project, issue=issue, assignee=other)
    IssueSubscriber.objects.create(project=project, issue=issue, subscriber=create_user)
    hidden = Issue.objects.create(
        project=project, name="Archived", state=state, created_by=create_user, archived_at=date.today()
    )
    IssueSubscriber.objects.create(project=project, issue=hidden, subscriber=create_user)
    Issue.objects.filter(project=project).update(created_by=create_user)
    client = APIClient()
    client.force_authenticate(create_user)
    return client, project, issue


def test_subscribed_summary_matches_active_filtered_list(workspace, create_user, summary_records):
    client, project, issue = summary_records
    stats = client.get(f"/api/workspaces/{workspace.slug}/user-stats/{create_user.id}/")
    assert stats.status_code == 200
    assert stats.data["subscribed_issues"] == 1
    assert stats.data["assigned_issues"] == 1
    response = client.get(
        f"/api/workspaces/{workspace.slug}/user-issues/{create_user.id}/",
        {"subscriber": str(create_user.id), "per_page": 20},
    )
    assert response.status_code == 200
    assert response.data["total_count"] == 1


def test_project_breakdown_counts_unique_active_items_and_completed_state(workspace, create_user, summary_records):
    client, project, issue = summary_records
    response = client.get(f"/api/workspaces/{workspace.slug}/user-profile/{create_user.id}/")
    assert response.status_code == 200
    row = next(row for row in response.data["project_data"] if row["id"] == project.id)
    assert row["created_issues"] == 1
    assert row["assigned_issues"] == 1
    assert row["completed_issues"] == 1
    assert row["pending_issues"] == 0


@pytest.mark.parametrize("filters", [{"state_group__exact": "completed"}, {"priority__exact": "high"}])
def test_summary_filter_matches_counts(workspace, create_user, summary_records, filters):
    client, project, issue = summary_records
    response = client.get(
        f"/api/workspaces/{workspace.slug}/user-issues/{create_user.id}/",
        {"assignees": str(create_user.id), "filters": json.dumps(filters), "per_page": 20},
    )
    assert response.status_code == 200
    assert response.data["total_count"] == 1


def test_profile_cycle_summary_excludes_projects_not_joined_by_viewer(workspace, create_user):
    from datetime import timedelta
    from django.utils import timezone
    from plane.db.models import Cycle, CycleIssue

    project = Project.objects.create(workspace=workspace, name="Private cycle", identifier="PRVC")
    state = State.objects.create(project=project, name="Backlog", group="backlog")
    issue = Issue.objects.create(project=project, name="Private cycle issue", state=state)
    IssueAssignee.objects.create(project=project, issue=issue, assignee=create_user)
    now = timezone.now()
    cycle = Cycle.objects.create(
        project=project,
        name="Private scheduled cycle",
        start_date=now + timedelta(days=2),
        end_date=now + timedelta(days=4),
        owned_by=create_user,
    )
    CycleIssue.objects.create(project=project, issue=issue, cycle=cycle)
    client = APIClient()
    client.force_authenticate(create_user)
    response = client.get(f"/api/workspaces/{workspace.slug}/user-stats/{create_user.id}/")
    assert response.status_code == 200
    assert list(response.data["upcoming_cycles"]) == []
