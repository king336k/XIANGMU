import pytest
from plane.db.models import Issue, Project, ProjectMember
from plane.quality.models import Requirement

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def kinds(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="需求与任务区分", identifier="KIND")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    task = Issue.objects.create(project=project, workspace=workspace, name="普通任务")
    issue = Issue.objects.create(project=project, workspace=workspace, name="正式需求")
    Requirement.objects.create(project=project, issue=issue)
    return f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/work-item-kinds/", project, task, issue


def test_requirement_badges_classify_by_registered_identity_not_title(session_client, kinds):
    url, project, task, issue = kinds
    Issue.objects.filter(pk=task.pk).update(name="标题带需求但仍是任务")
    response = session_client.get(url)
    assert response.status_code == 200, response.content
    assert {key: value for key, value in response.data.items() if key != "requirement_numbers"} == {
        "total": 2,
        "requirements": 1,
        "tasks": 1,
        "requirement_sequences": [issue.sequence_id],
    }
    assert Issue.objects.filter(project=project).count() == 2


def test_kind_counts_do_not_include_foreign_project(session_client, kinds, workspace):
    url, _, _, issue = kinds
    other = Project.objects.create(workspace=workspace, name="其他项目", identifier="OTHERK")
    foreign = Issue.objects.create(project=other, workspace=workspace, name="其他需求")
    Requirement.objects.create(project=other, issue=foreign)
    response = session_client.get(url)
    assert response.data["requirement_sequences"] == [issue.sequence_id]
    assert response.data["total"] == 2


def test_kind_index_requires_active_membership(session_client, kinds, create_user):
    url, project, _, _ = kinds
    ProjectMember.objects.filter(project=project, member=create_user).update(is_active=False)
    assert session_client.get(url).status_code == 403


def test_kind_summary_matches_active_work_items_not_archives_or_drafts(session_client, kinds):
    from django.utils import timezone

    url, project, task, issue = kinds
    Issue.objects.create(project=project, workspace=project.workspace, name="草稿", is_draft=True)
    Issue.objects.filter(pk=task.pk).update(archived_at=timezone.now())
    response = session_client.get(url)
    assert {key: value for key, value in response.data.items() if key != "requirement_numbers"} == {
        "total": 1,
        "requirements": 1,
        "tasks": 0,
        "requirement_sequences": [issue.sequence_id],
    }


def test_restricted_guest_counts_only_own_work_items(session_client, kinds, create_user):
    url, project, task, issue = kinds
    project.guest_view_all_features = False
    project.save(update_fields=["guest_view_all_features"])
    ProjectMember.objects.filter(project=project, member=create_user).update(role=5)
    Issue.objects.filter(pk=task.pk).update(created_by=create_user)
    response = session_client.get(url)
    assert response.status_code == 200
    assert {key: value for key, value in response.data.items() if key != "requirement_numbers"} == {
        "total": 1,
        "requirements": 0,
        "tasks": 1,
        "requirement_sequences": [],
    }


def test_archived_requirement_keeps_its_badge_but_not_active_count(session_client, kinds):
    from django.utils import timezone

    url, _, _, issue = kinds
    Issue.objects.filter(pk=issue.pk).update(archived_at=timezone.now())
    response = session_client.get(url)
    assert {key: value for key, value in response.data.items() if key != "requirement_numbers"} == {
        "total": 1,
        "requirements": 0,
        "tasks": 1,
        "requirement_sequences": [issue.sequence_id],
    }
