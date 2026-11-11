"""Recent visits page all visible rows by visit time before slicing."""

import pytest
from datetime import timedelta
from django.utils import timezone
from plane.db.models import Project, ProjectMember, Issue, UserRecentVisit

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def recent_context(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="最近记录", identifier="RECENTS")
    ProjectMember.objects.create(project=project, workspace=workspace, member=create_user, role=20)
    return project, f"/api/workspaces/{workspace.slug}/recent-visits/"


def test_recent_pagination_reaches_older_visits_and_orders_by_visit(
    session_client, recent_context, create_user, workspace
):
    project, url = recent_context
    rows = []
    for index in range(25):
        issue = Issue.objects.create(project=project, workspace=workspace, name=f"最近{index}")
        row = UserRecentVisit.objects.create(
            workspace=workspace, user=create_user, entity_name="issue", entity_identifier=issue.id
        )
        UserRecentVisit.objects.filter(pk=row.pk).update(visited_at=timezone.now() - timedelta(days=index))
        rows.append(row)
    first = session_client.get(url + "?page=1&per_page=10")
    last = session_client.get(url + "?page=3&per_page=10")
    assert first.status_code == 200 and last.status_code == 200
    assert first.data["count"] == 25 and len(last.data["results"]) == 5
    assert str(first.data["results"][0]["id"]) == str(rows[0].id)
    assert set(row["id"] for row in first.data["results"]).isdisjoint(row["id"] for row in last.data["results"])


def test_hidden_or_missing_entities_are_excluded_before_page_count(
    session_client, recent_context, create_user, workspace
):
    project, url = recent_context
    hidden = Project.objects.create(workspace=workspace, name="不可见", identifier="RHIDDEN")
    secret = Issue.objects.create(project=hidden, workspace=workspace, name="不能泄漏")
    own = Issue.objects.create(project=project, workspace=workspace, name="可见")
    import uuid

    for entity in [secret.id, own.id, uuid.uuid4()]:
        UserRecentVisit.objects.create(
            workspace=workspace, user=create_user, entity_name="issue", entity_identifier=entity
        )
    result = session_client.get(url + "?page=1&per_page=10")
    assert result.status_code == 200 and result.data["count"] == 1
    assert result.data["results"][0]["entity_data"]["name"] == "可见"


def test_recent_legacy_array_contract_is_preserved(session_client, recent_context, create_user, workspace):
    project, url = recent_context
    issue = Issue.objects.create(project=project, workspace=workspace, name="兼容旧调用")
    UserRecentVisit.objects.create(
        workspace=workspace, user=create_user, entity_name="issue", entity_identifier=issue.id
    )
    result = session_client.get(url)
    assert result.status_code == 200 and isinstance(result.data, list)
