"""Knowledge governance keeps published history and merged sources auditable."""

import pytest
from plane.db.models import Project, ProjectMember, WorkspaceMember
from plane.knowledge.models import Article, PublishedRevision

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def governance(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="知识治理", identifier="GOV")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    source = Article.objects.create(
        project=project,
        created_by=create_user,
        title="采集连接排查",
        content="检查网络和Topic",
        status="published",
        publication_active=True,
        published_version=1,
    )
    target = Article.objects.create(
        project=project,
        created_by=create_user,
        title="采集连接排查",
        content="检查网络和Topic",
        status="published",
        publication_active=True,
        published_version=1,
    )
    for row in [source, target]:
        PublishedRevision.objects.create(
            project=project,
            created_by=create_user,
            article=row,
            version=1,
            title=row.title,
            content=row.content,
            tags=[],
        )
    return f"/api/workspaces/{workspace.slug}/projects/{project.id}/knowledge/", project, source, target


def test_duplicate_candidates_merge_creates_draft_preserves_history_and_disables_source(session_client, governance):
    base, project, source, target = governance
    candidates = session_client.get(base + "governance/")
    assert candidates.status_code == 200 and len(candidates.data["candidates"]) == 1, candidates.content
    merged = session_client.post(
        base + "governance/merge/",
        {
            "source_id": str(source.id),
            "target_id": str(target.id),
            "source_version": 1,
            "target_version": 1,
            "reason": "重复知识归并",
        },
        format="json",
    )
    assert merged.status_code == 200, merged.content
    source.refresh_from_db()
    target.refresh_from_db()
    assert source.status == "offline" and not source.publication_active and source.merged_into_id == target.id
    assert target.status == "draft" and target.edit_version == 2
    assert PublishedRevision.objects.filter(article=source, version=1, content="检查网络和Topic").exists()
    assert (
        session_client.post(
            base + f"articles/{source.id}/workflow/",
            {"action": "scan", "expected_version": source.edit_version},
            format="json",
        ).status_code
        == 409
    )


def test_batch_offline_is_atomic_and_version_checked(session_client, governance):
    base, project, source, target = governance
    response = session_client.post(
        base + "governance/offline/",
        {
            "articles": [{"id": str(source.id), "version": 1}, {"id": str(target.id), "version": 99}],
            "reason": "版本检查",
        },
        format="json",
    )
    assert response.status_code == 409, response.content
    source.refresh_from_db()
    assert source.publication_active
    good = session_client.post(
        base + "governance/offline/",
        {
            "articles": [{"id": str(source.id), "version": 1}, {"id": str(target.id), "version": 1}],
            "reason": "旧版知识停用",
        },
        format="json",
    )
    assert good.status_code == 200
    source.refresh_from_db()
    target.refresh_from_db()
    assert not source.publication_active and not target.publication_active


def test_member_cannot_merge_and_foreign_article_cannot_be_target(session_client, governance, create_user, workspace):
    base, project, source, target = governance
    ProjectMember.objects.filter(project=project, member=create_user).update(role=15)
    WorkspaceMember.objects.filter(workspace=workspace, member=create_user).update(role=15)
    response = session_client.post(
        base + "governance/merge/",
        {
            "source_id": str(source.id),
            "target_id": str(target.id),
            "source_version": 1,
            "target_version": 1,
            "reason": "不可越权",
        },
        format="json",
    )
    assert response.status_code == 403
