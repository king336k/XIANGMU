"""Current counterexamples for visible statistics outside quality report cards."""

import pytest
from plane.db.models import Project, ProjectMember, WorkspaceMember, Issue, IssueAssignee, State, User
from plane.quality.models import ProjectRolePolicy, Requirement, ProjectVersion
from plane.quality.project_versions import blockers

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def audit_scope(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="全局统计反例", identifier="GLOBALSTAT")
    ProjectMember.objects.create(project=project, member=create_user, role=15)
    state = State.objects.create(project=project, workspace=workspace, name="进行中", group="started")
    return project, state


def task(project, state, actor, title="统计任务"):
    issue = Issue.objects.create(
        project=project, workspace=project.workspace, name=title, state=state, created_by=actor
    )
    IssueAssignee.objects.create(project=project, workspace=project.workspace, issue=issue, assignee=actor)
    return issue


def test_home_todo_includes_actionable_inherited_workspace_technician(
    session_client, audit_scope, workspace, create_user
):
    project, state = audit_scope
    ProjectRolePolicy.objects.create(project=project, enabled=True)
    WorkspaceMember.objects.filter(workspace=workspace, member=create_user).update(
        has_workspace_access=True, business_roles=["TECHNICIAN"]
    )
    issue = task(project, state, create_user)
    response = session_client.get("/api/quality-auth/my-todos/", {"workspace": workspace.slug})
    assert response.status_code == 200, response.content
    assert response.data["count"] == 1, response.data
    assert response.data["results"][0]["id"] == str(issue.id)


def test_profile_assigned_count_and_distribution_do_not_multiply_other_assignees(
    session_client, audit_scope, workspace, create_user
):
    project, state = audit_scope
    issue = task(project, state, create_user)
    other = User.objects.create(username="other-stats-owner", email="other-stats-owner@local.test")
    WorkspaceMember.objects.create(workspace=workspace, member=other, role=15)
    ProjectMember.objects.create(project=project, member=other, role=15)
    IssueAssignee.objects.create(project=project, workspace=workspace, issue=issue, assignee=other)
    response = session_client.get(f"/api/workspaces/{workspace.slug}/user-stats/{create_user.id}/")
    assert response.status_code == 200, response.content
    assert response.data["assigned_issues"] == 1, response.data
    assert sum(row["state_count"] for row in response.data["state_distribution"]) == 1, response.data


def test_version_archived_requirement_is_not_counted_as_unfinished_blocker(audit_scope):
    project, state = audit_scope
    issue = Issue.objects.create(project=project, workspace=project.workspace, name="已归档需求", state=state)
    Requirement.objects.create(project=project, issue=issue, target_build="vstat", status="archived")
    version = ProjectVersion.objects.create(project=project, name="统计版本", version="vstat")
    assert not any("需求尚未验收" in reason for reason in blockers(version)), blockers(version)


@pytest.mark.parametrize(
    "boundary",
    ["unassigned", "workspace_readonly", "workspace_inactive", "project_inactive", "project_archived", "no_duty"],
)
def test_inherited_home_todo_keeps_assignment_and_current_permission_boundaries(
    session_client, audit_scope, workspace, create_user, boundary
):
    project, state = audit_scope
    ProjectRolePolicy.objects.create(project=project, enabled=True)
    WorkspaceMember.objects.filter(workspace=workspace, member=create_user).update(
        has_workspace_access=True, business_roles=["TECHNICIAN"]
    )
    issue = task(project, state, create_user)
    if boundary == "unassigned":
        IssueAssignee.objects.filter(issue=issue).delete()
    if boundary == "workspace_readonly":
        WorkspaceMember.objects.filter(workspace=workspace, member=create_user).update(role=5)
    if boundary == "workspace_inactive":
        WorkspaceMember.objects.filter(workspace=workspace, member=create_user).update(is_active=False)
    if boundary == "project_inactive":
        ProjectMember.objects.filter(project=project, member=create_user).update(is_active=False)
    if boundary == "project_archived":
        from django.utils import timezone

        Project.objects.filter(pk=project.id).update(archived_at=timezone.now())
    if boundary == "no_duty":
        WorkspaceMember.objects.filter(workspace=workspace, member=create_user).update(business_roles=[])
    response = session_client.get("/api/quality-auth/my-todos/", {"workspace": workspace.slug})
    if boundary == "workspace_inactive":
        assert response.status_code == 403
    else:
        assert response.status_code == 200 and response.data["count"] == 0, response.data


def test_canonical_admin_without_explicit_business_role_gets_only_own_todos(
    session_client, audit_scope, workspace, create_user
):
    from uuid import uuid4
    from django.utils import timezone
    from plane.license.models import Instance, InstanceAdmin

    project, state = audit_scope
    instance = Instance.objects.create(
        instance_name="stats admin", instance_id=str(uuid4()), current_version="test", last_checked_at=timezone.now()
    )
    InstanceAdmin.objects.create(instance=instance, user=create_user)
    ProjectRolePolicy.objects.create(project=project, enabled=True)
    mine = task(project, state, create_user)
    other = User.objects.create(username="other-admin-todo", email="other-admin-todo@local.test")
    task(project, state, other)
    response = session_client.get("/api/quality-auth/my-todos/", {"workspace": workspace.slug})
    assert response.status_code == 200 and response.data["count"] == 1, response.data
    assert response.data["results"][0]["id"] == str(mine.id)


def test_knowledge_index_counter_excludes_stale_hash_not_usable_by_retrieval(session_client, audit_scope, mocker):
    from plane.knowledge.models import Article, PublishedRevision
    from plane.knowledge.semantic_models import SemanticRevisionIndex

    project, _ = audit_scope
    article = Article.objects.create(
        project=project, title="有效知识", content="正文", publication_active=True, published_version=1
    )
    revision = PublishedRevision.objects.create(
        project=project, article=article, version=1, title=article.title, content=article.content
    )
    SemanticRevisionIndex.objects.create(
        project=project, revision=revision, fingerprint="f" * 64, content_hash="outdated", vectors=[]
    )
    mocker.patch(
        "plane.knowledge.semantic_provider.configuration", return_value={"fingerprint": "f" * 64, "configured": True}
    )
    mocker.patch("plane.knowledge.semantic_provider.public_status", return_value={"configured": True, "status": "idle"})
    response = session_client.get(
        f"/api/workspaces/{project.workspace.slug}/projects/{project.id}/knowledge/semantic-index/"
    )
    assert response.status_code == 200, response.content
    assert response.data["eligible_count"] == 1, response.data
    assert response.data["indexed_count"] == 0, response.data
    cached = SemanticRevisionIndex.objects.get(revision=revision)
    from plane.knowledge.semantic import content_hash

    cached.content_hash = content_hash(revision)
    cached.save(update_fields=["content_hash"])
    assert (
        session_client.get(
            f"/api/workspaces/{project.workspace.slug}/projects/{project.id}/knowledge/semantic-index/"
        ).data["indexed_count"]
        == 0
    )
    cached.vectors = [[1.0, 0.0]]
    cached.save(update_fields=["vectors"])
    assert (
        session_client.get(
            f"/api/workspaces/{project.workspace.slug}/projects/{project.id}/knowledge/semantic-index/"
        ).data["indexed_count"]
        == 1
    )
    article.publication_active = False
    article.save(update_fields=["publication_active"])
    data = session_client.get(
        f"/api/workspaces/{project.workspace.slug}/projects/{project.id}/knowledge/semantic-index/"
    ).data
    assert data["indexed_count"] == data["eligible_count"] == 0


def test_profile_stats_require_active_workspace_membership(session_client, audit_scope, workspace, create_user):
    project, state = audit_scope
    task(project, state, create_user)
    WorkspaceMember.objects.filter(workspace=workspace, member=create_user).update(is_active=False)
    response = session_client.get(f"/api/workspaces/{workspace.slug}/user-stats/{create_user.id}/")
    assert response.status_code == 403, response.data


def test_native_overview_intake_chart_counts_unique_issues_like_card_and_drilldown(
    session_client, audit_scope, create_user
):
    from plane.db.models import Intake, IntakeIssue

    project, state = audit_scope
    issue = task(project, state, create_user)
    for index in range(2):
        intake = Intake.objects.create(project=project, workspace=project.workspace, name=f"反馈入口{index}")
        IntakeIssue.objects.create(project=project, workspace=project.workspace, intake=intake, issue=issue)
    base = f"/api/workspaces/{project.workspace.slug}/"
    card = session_client.get(base + "advance-analytics/", {"tab": "overview", "project_ids": str(project.id)})
    chart = session_client.get(base + "advance-analytics-charts/", {"type": "projects", "project_ids": str(project.id)})
    detail = session_client.get(
        base + "advance-analytics/", {"tab": "overview", "project_ids": str(project.id), "detail": "total_intake"}
    )
    assert card.status_code == chart.status_code == detail.status_code == 200
    chart_count = next(row["count"] for row in chart.data if row["key"] == "intake")
    assert card.data["total_intake"]["count"] == detail.data["count"] == chart_count == 1, {
        "card": card.data,
        "chart": chart.data,
        "detail": detail.data,
    }


def test_native_intake_card_chart_and_detail_exclude_unknown_status_and_unjoined_scope(
    session_client, audit_scope, create_user
):
    from plane.db.models import Intake, IntakeIssue

    project, state = audit_scope
    invalid = task(project, state, create_user, "异常状态反馈")
    intake = Intake.objects.create(project=project, workspace=project.workspace, name="当前入口")
    IntakeIssue.objects.create(project=project, workspace=project.workspace, intake=intake, issue=invalid, status=999)
    other = Project.objects.create(workspace=project.workspace, name="未加入反馈", identifier="HIDINTAKE")
    hidden = Issue.objects.create(project=other, workspace=project.workspace, name="其他项目不可见", state=state)
    hidden_intake = Intake.objects.create(project=other, workspace=project.workspace, name="隐藏入口")
    IntakeIssue.objects.create(project=other, workspace=project.workspace, intake=hidden_intake, issue=hidden)
    base = f"/api/workspaces/{project.workspace.slug}/"
    for selected in [project.id, other.id]:
        query = {"project_ids": str(selected)}
        card = session_client.get(base + "advance-analytics/", {**query, "tab": "overview"})
        chart = session_client.get(base + "advance-analytics-charts/", {**query, "type": "projects"})
        detail = session_client.get(base + "advance-analytics/", {**query, "tab": "overview", "detail": "total_intake"})
        assert card.status_code == chart.status_code == detail.status_code == 200
        assert (
            card.data["total_intake"]["count"]
            == detail.data["count"]
            == next(row["count"] for row in chart.data if row["key"] == "intake")
            == 0
        )
    ProjectMember.objects.filter(project=project, member=create_user).update(is_active=False)
    response = session_client.get(
        base + "advance-analytics-charts/", {"type": "projects", "project_ids": str(project.id)}
    )
    assert response.status_code == 200 and next(row["count"] for row in response.data if row["key"] == "intake") == 0


def test_native_work_counts_match_full_authorized_set_before_pagination(session_client, audit_scope, create_user):
    from django.utils import timezone

    project, state = audit_scope
    for index in range(23):
        task(project, state, create_user, f"分页任务{index}")
    archived = task(project, state, create_user, "归档不计")
    Issue.objects.filter(pk=archived.id).update(archived_at=timezone.now())
    deleted = task(project, state, create_user, "删除不计")
    Issue.objects.filter(pk=deleted.id).update(deleted_at=timezone.now())
    draft = task(project, state, create_user, "草稿不计")
    Issue.objects.filter(pk=draft.id).update(is_draft=True)
    other = Project.objects.create(workspace=project.workspace, name="未加入任务", identifier="HIDTASK")
    Issue.objects.create(project=other, workspace=project.workspace, name="隐藏不计", state=state)
    base = f"/api/workspaces/{project.workspace.slug}/advance-analytics/"
    card = session_client.get(base, {"tab": "work-items"})
    seen = []
    for page in range(1, 5):
        response = session_client.get(
            base, {"tab": "work-items", "detail": "total_work_items", "page": page, "per_page": 7}
        )
        assert response.status_code == 200 and response.data["count"] == 23, response.data
        seen += [row["id"] for row in response.data["results"]]
    assert card.data["total_work_items"]["count"] == len(set(seen)) == len(seen) == 23


def test_knowledge_governance_and_search_count_full_distinct_publications_before_page(session_client, audit_scope):
    from plane.knowledge.models import Article, PublishedRevision

    project, _ = audit_scope
    for index in range(25):
        article = Article.objects.create(
            project=project,
            title=f"知识统计{index}",
            content="审核正文",
            status="published" if index < 12 else "draft",
            publication_active=index < 12,
            published_version=1 if index < 12 else 0,
        )
        if index < 12:
            PublishedRevision.objects.create(
                project=project, article=article, version=1, title=article.title, content=article.content
            )
    base = f"/api/workspaces/{project.workspace.slug}/projects/{project.id}/knowledge/"
    governance = session_client.get(base + "governance/")
    assert governance.status_code == 200 and governance.data["total"] == 25 and governance.data["published"] == 12, (
        governance.data
    )
    seen = []
    for page in range(1, 4):
        response = session_client.get(base + "search/", {"page": page, "per_page": 5})
        assert response.status_code == 200 and response.data["count"] == 12, response.data
        seen += [row["id"] for row in response.data["results"]]
    assert len(set(seen)) == len(seen) == 12
