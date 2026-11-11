import json
import pytest
from django.core.management import call_command
from plane.db.models import Project, ProjectMember, Workspace, WorkspaceMember
from plane.knowledge.models import Article
from plane.knowledge.retrieval import search, published
from plane.license.models import Instance, InstanceAdmin
from django.utils import timezone

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def initial(workspace, create_user):
    Instance.objects.create(
        instance_name="base",
        instance_id="base",
        current_version="test",
        last_checked_at=timezone.now(),
        is_setup_done=True,
    )
    InstanceAdmin.objects.create(user=create_user, instance=Instance.objects.first())
    project = Project.objects.create(workspace=workspace, name="业务项目", identifier="WORK")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    return workspace, create_user, project


def test_base_seed_combines_history_and_guides_searchable_in_existing_and_new_projects(initial):
    workspace, user, project = initial
    call_command("bootstrap_base_knowledge")
    base = Project.objects.get(workspace=workspace, name="平台基础知识")
    assert Article.objects.filter(project=base, publication_active=True).count() == 17
    assert search(project, "上传失败").exists()
    assert published(project).count() == 17
    future = Project.objects.create(workspace=workspace, name="新项目", identifier="NEWBASE")
    assert published(future).count() == 17
    other = Workspace.objects.create(name="别的区", slug="other-base", owner=user)
    foreign = Project.objects.create(workspace=other, name="其他项目", identifier="OTHERBASE")
    assert not published(foreign).exists()


def test_redeploy_does_not_overwrite_edit_reactivate_or_restore_deleted_base_record(initial):
    call_command("bootstrap_base_knowledge")
    row = Article.objects.order_by("title").first()
    row.content = "用户修改保留"
    row.publication_active = False
    row.status = "offline"
    row.save()
    from plane.knowledge.models import ArticleEvent, PublishedRevision

    deleted = Article.objects.exclude(pk=row.pk).first()
    ArticleEvent.objects.filter(article=deleted).delete()
    from plane.knowledge.sharing_models import KnowledgeShare

    KnowledgeShare.objects.filter(article=deleted).delete()
    PublishedRevision.objects.filter(article=deleted).delete()
    pk = deleted.pk
    deleted.delete()
    call_command("bootstrap_base_knowledge")
    row.refresh_from_db()
    assert row.content == "用户修改保留" and not row.publication_active
    assert not Article.objects.filter(pk=pk).exists()


def test_fresh_bootstrap_has_default_knowledge_and_changed_password_survives():
    call_command("bootstrap_project_admin")
    call_command("bootstrap_base_knowledge")
    from plane.db.models import User

    user = User.objects.get(username="admin")
    user.set_password("user-changed-password")
    user.save()
    assert Article.objects.filter(publication_active=True).count() == 17
    call_command("bootstrap_project_admin")
    call_command("bootstrap_base_knowledge")
    user.refresh_from_db()
    assert user.check_password("user-changed-password")
    assert Article.objects.filter(publication_active=True).count() == 17


def test_base_changes_and_new_publications_reach_projects_without_redeploy(initial):
    from rest_framework.test import APIClient

    workspace, user, project = initial
    call_command("bootstrap_base_knowledge")
    base = Project.objects.get(workspace=workspace, name="平台基础知识")
    client = APIClient()
    client.force_authenticate(user)
    path = f"/api/workspaces/{workspace.slug}/projects/{base.id}/knowledge/articles/"
    response = client.post(
        path, {"title": "新增基础排查", "content": "检查电源指示灯和连接状态", "tags": ["基础知识"]}, format="json"
    )
    assert response.status_code == 201, response.content
    row = response.data
    for action in ["scan", "publish"]:
        response = client.post(
            path + row["id"] + "/workflow/", {"action": action, "expected_version": row["edit_version"]}, format="json"
        )
        assert response.status_code == 200, response.content
        row = response.data
    assert search(project, "新增基础排查").exists()


def test_base_project_creation_preserves_inherited_workspace_access(initial):
    workspace, user, project = initial
    WorkspaceMember.objects.filter(workspace=workspace, member=user).update(business_roles=["PROJECT_MANAGER"])
    call_command("bootstrap_base_knowledge")
    base = Project.objects.get(workspace=workspace, name="平台基础知识")
    assert ProjectMember.objects.get(project=base, member=user).role == 20
    assert Article.objects.filter(project=base, publication_active=True).count() == 17
