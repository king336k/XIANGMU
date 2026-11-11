"""Legacy records remain drafts, immutable under retries and inaccessible across projects."""

from copy import deepcopy

import pytest
from plane.db.models import Project, ProjectMember, User, WorkspaceMember
from plane.knowledge.legacy_migration import build_plan, import_plan
from plane.knowledge.models import Article, ArticleEvent, PublishedRevision
from plane.knowledge.retrieval import search

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def migration_scope(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="157隔离复核", identifier="MIG157", network=0)
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    data = {
        "schema": "hub-knowledge-export-v1",
        "source": {"host": "10.10.10.157", "database": "legacy", "source_verified": True, "runtime_active": False},
        "tables": {
            "knowledge_drafts": [
                {
                    "id": 1,
                    "title": "采集诊断",
                    "content": "已脱敏的历史经验",
                    "status": "PUBLISHED",
                    "source_issue_id": 12,
                }
            ],
            "knowledge_versions": [
                {
                    "id": 1,
                    "source_draft_id": 1,
                    "version_no": 2,
                    "title": "采集依据v2",
                    "content_snapshot": {"content": "旧版根因"},
                    "status": "ACTIVE",
                }
            ],
            "issue_tickets": [{"id": 12, "project_id": 9}],
        },
    }
    return project, create_user, build_plan(data)


def test_migration_retains_legacy_version_but_never_enters_retrieval(migration_scope, session_client):
    project, user, plan = migration_scope
    report = import_plan(plan, {"9": str(project.id)}, user)
    assert report["created"] == report["versions_created"] == 1
    article = Article.objects.get(pk=plan[0]["id"])
    assert article.source_issue_id is None and article.source_defect_id is None and article.source_regression_id is None
    assert article.status == "draft" and not article.publication_active
    assert article.published_version == 2
    assert not search(project, "采集").exists()
    assert PublishedRevision.objects.get(article=article).version == 2
    assert "PUBLISHED" in article.content and "source_issue_id" in article.content
    base = f"/api/workspaces/{project.workspace.slug}/projects/{project.id}/knowledge/"
    assert session_client.get(base + "articles/").data["count"] == 1
    assert session_client.get(base + "search/?q=采集").data["count"] == 0
    outsider = User.objects.create(email="migration-outsider@example.test", username="migration-outsider")
    WorkspaceMember.objects.create(workspace=project.workspace, member=outsider, role=15)
    session_client.force_authenticate(user=outsider)
    assert session_client.get(base + "articles/").status_code == 403
    assert session_client.get(base + f"articles/{article.id}/").status_code == 403
    assert session_client.get(base + "search/?q=采集").status_code == 403


def test_retry_is_idempotent_and_refuses_changed_source_or_target(migration_scope):
    project, user, plan = migration_scope
    mapping = {"9": str(project.id)}
    import_plan(plan, mapping, user)
    assert import_plan(plan, mapping, user)["unchanged"] == 1
    assert Article.objects.count() == PublishedRevision.objects.count() == ArticleEvent.objects.count() == 1
    changed = deepcopy(plan)
    changed[0]["digest"] = "changed"
    with pytest.raises(ValueError, match="changed"):
        import_plan(changed, mapping, user)
    Article.objects.filter(pk=plan[0]["id"]).update(content="审核员修改")
    with pytest.raises(ValueError, match="edited"):
        import_plan(plan, mapping, user)
    assert Article.objects.get().content == "审核员修改"


@pytest.mark.parametrize("breach", ["public", "member", "unmapped", "history"])
def test_unsafe_targets_and_tampered_history_are_rejected_atomically(migration_scope, breach):
    project, user, plan = migration_scope
    mapping = {"9": str(project.id)}
    if breach == "public":
        project.network = 2
        project.save()
    elif breach == "member":
        extra = User.objects.create(email="extra@example.test", username="migration-extra")
        ProjectMember.objects.create(project=project, member=extra, role=15)
    elif breach == "unmapped":
        mapping = {}
    else:
        import_plan(plan, mapping, user)
        PublishedRevision.objects.filter(article_id=plan[0]["id"]).update(content="篡改历史")
    with pytest.raises(ValueError):
        import_plan(plan, mapping, user)
    assert Article.objects.count() == (1 if breach == "history" else 0)
