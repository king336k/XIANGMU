"""Optional embeddings retain publication/project boundaries and fall back without network."""

from uuid import uuid4
import pytest
from plane.db.models import Project, ProjectMember
from plane.knowledge.models import Article, PublishedRevision

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def test_embedding_explicit_dns_origin_is_supported_without_loosening_chat_hosts(mocker):
    from plane.knowledge.semantic_provider import valid_embedding_url
    from plane.knowledge.assistant import valid_provider_url

    mocker.patch.dict("os.environ", {"KNOWLEDGE_EMBEDDING_ALLOWED_HTTP_ORIGINS": "http://engramproject-embedding:18885"})
    assert valid_embedding_url("http://engramproject-embedding:18885/v1")
    assert not valid_provider_url("http://engramproject-embedding:18885/v1")
    for url in ["http://other:18885/v1", "http://engramproject-embedding:18886/v1",
                "http://user@engramproject-embedding:18885/v1", "http://engramproject-embedding:18885/v1?secret=1",
                "http://engramproject-embedding:18885/v1#x"]:
        assert not valid_embedding_url(url)


@pytest.fixture
def semantic_case(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="语义测试", identifier="SEMANTIC")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    article = Article.objects.create(
        project=project,
        created_by=create_user,
        title="网卡链路排查",
        content="检查以太网接口，确认物理链路。",
        status="published",
        publication_active=True,
        published_version=1,
    )
    revision = PublishedRevision.objects.create(
        project=project, article=article, version=1, title=article.title, content=article.content
    )
    return project, article, revision


def config():
    return {
        "enabled": True,
        "configured": True,
        "model": "embedding-fixture",
        "base_url": "https://api.openai.com/v1",
        "api_key": "fixture-only",
        "fingerprint": "f" * 64,
    }


def test_disabled_does_not_call_provider_or_create_indexes(semantic_case, mocker):
    from plane.knowledge import semantic

    provider = mocker.patch("plane.knowledge.semantic_provider.embed")
    mocker.patch(
        "plane.knowledge.semantic_provider.configuration", return_value={"enabled": False, "configured": False}
    )
    assert semantic.ranked_ids(semantic_case[0], "设备无法联网") is None
    provider.assert_not_called()


def test_index_idempotent_version_and_offline_revocation(semantic_case, mocker):
    from plane.knowledge import semantic
    from plane.knowledge.semantic_models import SemanticRevisionIndex

    project, article, revision = semantic_case
    mocker.patch("plane.knowledge.semantic_provider.configuration", side_effect=lambda: config())
    embed = mocker.patch(
        "plane.knowledge.semantic_provider.embed", side_effect=lambda texts, cfg: [[1.0, 0.0] for _ in texts]
    )
    job = semantic.request_build(project)
    assert semantic.run_build(project.id, job.token)["status"] == "completed"
    assert SemanticRevisionIndex.objects.filter(revision=revision).count() == 1
    assert semantic.ranked_ids(project, "设备无法联网") == [revision.id]
    calls = embed.call_count
    job = semantic.request_build(project)
    semantic.run_build(project.id, job.token)
    assert embed.call_count == calls
    other = Project.objects.create(workspace=project.workspace, name="其他", identifier="OTHERSEM")
    assert semantic.ranked_ids(other, "设备无法联网") is None
    article.publication_active = False
    article.save()
    assert semantic.ranked_ids(project, "设备无法联网") is None
    assert embed.call_count == calls


def test_sensitive_queries_and_published_content_never_leave_boundary(semantic_case, mocker):
    from plane.knowledge import semantic

    project, article, revision = semantic_case
    mocker.patch("plane.knowledge.semantic_provider.configuration", side_effect=lambda: config())
    embed = mocker.patch("plane.knowledge.semantic_provider.embed")
    assert semantic.ranked_ids(project, "password=private-fixture") is None
    revision.content = "api_key=fixture-private"
    revision.save()
    job = semantic.request_build(project)
    assert semantic.run_build(project.id, job.token)["status"] == "failed"
    embed.assert_not_called()


def test_semantic_failure_preserves_literal_keyword_matches(semantic_case, mocker):
    from plane.knowledge.retrieval import search

    mocker.patch("plane.knowledge.semantic.ranked_ids", return_value=[])
    assert list(search(semantic_case[0], "网卡").values_list("id", flat=True)) == [semantic_case[2].id]
    mocker.patch("plane.knowledge.semantic.ranked_ids", side_effect=RuntimeError("provider unavailable"))
    assert list(search(semantic_case[0], "网卡").values_list("id", flat=True)) == [semantic_case[2].id]


def test_invalid_vectors_and_zero_norm_rejected():
    from plane.knowledge.semantic import normalized_vector, cosine

    for value in [[0.0, 0.0], [float("nan"), 1], [], [True, 1], ["1", 2]]:
        with pytest.raises(ValueError):
            normalized_vector(value)
    assert cosine([1.0, 0.0], [1.0, 0.0]) == 1
    with pytest.raises(ValueError):
        cosine([1.0], [1.0, 0.0])


def test_index_api_requires_reviewer_and_explicit_optin(session_client, semantic_case, mocker, create_user, workspace):
    from plane.knowledge.semantic_models import SemanticProjectIndex

    project, article, revision = semantic_case
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/knowledge/"
    mocker.patch("plane.knowledge.semantic_provider.configuration", side_effect=lambda: config())
    mocker.patch("plane.knowledge.semantic.enqueue")
    state = session_client.get(base + "semantic-index/")
    assert state.status_code == 200 and state.data["indexed_count"] == 0 and state.data["eligible_count"] == 1
    assert state.data["status"] == "idle" and state.data["can_build"] is True
    assert not SemanticProjectIndex.objects.exists()
    # Explicit opt-in, with duplicate attempts using the same queued work token.
    response = session_client.post(base + "semantic-index/", {"action": "build"}, format="json")
    assert response.status_code == 202
    token = SemanticProjectIndex.objects.get(project=project).token
    assert session_client.post(base + "semantic-index/", {"action": "build"}, format="json").status_code == 202
    assert SemanticProjectIndex.objects.get(project=project).token == token
    ProjectMember.objects.filter(project=project, member=create_user).update(role=15)
    from plane.db.models import WorkspaceMember

    WorkspaceMember.objects.filter(workspace=workspace, member=create_user).update(role=15)
    assert session_client.post(base + "semantic-index/", {"action": "build"}, format="json").status_code == 403


def test_semantic_configuration_is_admin_only_and_default_off(
    session_client, semantic_case, mocker, create_user, workspace
):
    from plane.license.models import Instance, InstanceAdmin, InstanceConfiguration
    from django.utils import timezone

    project, _, _ = semantic_case
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/knowledge/"
    assert session_client.get(base + "configuration/").data["semantic_enabled"] is False
    assert (
        session_client.patch(
            base + "configuration/", {"semantic_enabled": True, "embedding_model": "test-embedding"}, format="json"
        ).status_code
        == 403
    )
    instance = Instance.objects.create(
        instance_name="semantic", instance_id=str(uuid4()), current_version="test", last_checked_at=timezone.now()
    )
    InstanceAdmin.objects.create(instance=instance, user=create_user, role=20)
    result = session_client.patch(
        base + "configuration/", {"semantic_enabled": True, "embedding_model": "test-embedding"}, format="json"
    )
    assert (
        result.status_code == 200
        and result.data["semantic_enabled"] is True
        and result.data["embedding_model"] == "test-embedding"
    )
    assert InstanceConfiguration.objects.get(key="KNOWLEDGE_SEMANTIC_ENABLED").value == "true"
    assert "api_key" not in result.data and "api_key" not in result.data["semantic"]


def test_provider_failure_falls_back_and_revoked_index_cannot_be_used(semantic_case, mocker):
    from plane.knowledge import semantic
    from plane.knowledge.retrieval import search

    project, article, revision = semantic_case
    mocker.patch("plane.knowledge.semantic_provider.configuration", side_effect=lambda: config())
    embed = mocker.patch(
        "plane.knowledge.semantic_provider.embed", side_effect=lambda texts, cfg: [[1.0, 0.0] for _ in texts]
    )
    job = semantic.request_build(project)
    semantic.run_build(project.id, job.token)
    embed.side_effect = TimeoutError("sensitive upstream details must not be exposed")
    assert list(search(project, "网卡").values_list("id", flat=True)) == [revision.id]
    article.published_version = 2
    article.save()
    assert list(search(project, "网卡")) == []


def test_stale_index_task_and_revoked_reviewer_cannot_call_provider(semantic_case, mocker, create_user):
    from plane.knowledge import semantic

    project, _, _ = semantic_case
    mocker.patch("plane.knowledge.semantic_provider.configuration", side_effect=lambda: config())
    embed = mocker.patch("plane.knowledge.semantic_provider.embed")
    job = semantic.request_build(project, create_user)
    assert semantic.run_build(project.id, uuid4())["status"] == "stale"
    ProjectMember.objects.filter(project=project, member=create_user).update(is_active=False)
    assert semantic.run_build(project.id, job.token)["status"] == "failed"
    embed.assert_not_called()


def test_provider_is_bounded_and_validates_embeddings(mocker):
    from types import SimpleNamespace
    from plane.knowledge import semantic_provider

    client = mocker.patch("plane.knowledge.semantic_provider.OpenAI")
    client.return_value.__enter__.return_value.embeddings.create.return_value = SimpleNamespace(
        data=[SimpleNamespace(index=0, embedding=[3.0, 4.0])]
    )
    assert semantic_provider.embed(["合成网络排查文本"], config()) == [[0.6, 0.8]]
    for texts in [[], ["a"] * 17, ["x" * 2001], ["password=fixture-private"]]:
        with pytest.raises(ValueError):
            semantic_provider.embed(texts, config())
    assert client.call_count == 1
    client.return_value.__enter__.return_value.embeddings.create.return_value = SimpleNamespace(
        data=[SimpleNamespace(index=0, embedding=[float("nan"), 1])]
    )
    with pytest.raises(ValueError):
        semantic_provider.embed(["合成测试"], config())


def test_content_change_provider_change_draft_and_queue_failure_fail_closed(semantic_case, mocker):
    from plane.knowledge import semantic

    project, article, revision = semantic_case
    cfg = config()
    mocker.patch("plane.knowledge.semantic_provider.configuration", side_effect=lambda: cfg)
    embed = mocker.patch(
        "plane.knowledge.semantic_provider.embed", side_effect=lambda texts, cfg: [[1.0, 0.0] for _ in texts]
    )
    job = semantic.request_build(project)
    semantic.run_build(project.id, job.token)
    revision.content += " 已变化内容"
    revision.save()
    calls = embed.call_count
    assert semantic.ranked_ids(project, "联网") is None and embed.call_count == calls
    cfg = {**cfg, "fingerprint": "a" * 64}
    assert semantic.ranked_ids(project, "联网") is None
    article.publication_active = False
    article.status = "draft"
    article.save()
    job = semantic.request_build(project)
    assert semantic.run_build(project.id, job.token)["status"] == "completed"
    assert embed.call_count == calls
    job = semantic.request_build(project)
    mocker.patch(
        "plane.knowledge.semantic_tasks.build_semantic_index.delay", side_effect=RuntimeError("broker details")
    )
    semantic.enqueue(project.id, job.token)
    job.refresh_from_db()
    assert job.status == "failed" and job.error_code == "INDEX_QUEUE_UNAVAILABLE"


def test_strict_project_reviewer_can_build_without_generic_unavailable_capability(
    session_client, semantic_case, mocker, workspace, create_user
):
    from plane.quality.models import ProjectRolePolicy, BusinessRole

    project, _, _ = semantic_case
    ProjectRolePolicy.objects.create(project=project, enabled=True)
    mocker.patch("plane.knowledge.semantic_provider.configuration", side_effect=lambda: config())
    mocker.patch("plane.knowledge.semantic.enqueue")
    url = f"/api/workspaces/{workspace.slug}/projects/{project.id}/knowledge/semantic-index/"
    assert session_client.post(url, {"action": "build"}, format="json").status_code == 403
    BusinessRole.objects.create(project=project, user=create_user, role="PROJECT_MANAGER")
    assert session_client.post(url, {"action": "build"}, format="json").status_code == 202


def test_new_publication_snapshot_supersedes_running_task_and_indexes_only_after_optin(semantic_case, mocker):
    from plane.knowledge import semantic
    from plane.knowledge.semantic_models import SemanticProjectIndex

    project, article, revision = semantic_case
    mocker.patch("plane.knowledge.semantic_provider.configuration", side_effect=lambda: config())
    enqueue = mocker.patch("plane.knowledge.semantic.enqueue")
    semantic.schedule_if_opted_in(project)
    assert not SemanticProjectIndex.objects.exists()
    enqueue.assert_not_called()
    first = semantic.request_build(project)
    revision.content += " 新发布资料"
    revision.save()
    second = semantic.request_build(project)
    assert second.token != first.token and second.snapshot_hash != first.snapshot_hash
    assert semantic.run_build(project.id, first.token)["status"] == "stale"


def test_embedding_connection_is_independent_from_chat_configuration(mocker):
    from plane.knowledge.semantic_provider import configuration

    values = {
        "KNOWLEDGE_SEMANTIC_ENABLED": "true",
        "KNOWLEDGE_EMBEDDING_MODEL": "bge-small-zh-v1.5",
        "KNOWLEDGE_EMBEDDING_BASE_URL": "http://10.251.231.23:8000/v1",
        "KNOWLEDGE_EMBEDDING_API_KEY": "test-local-secret",
    }
    mocker.patch(
        "plane.knowledge.assistant.model_option", side_effect=lambda name, fallback: values.get(name, fallback)
    )
    mocker.patch(
        "plane.knowledge.assistant.provider_config",
        return_value={"configured": False, "base_url": "https://chat.invalid/v1", "api_key": "chat-fixture"},
    )
    mocker.patch.dict("os.environ", {"KNOWLEDGE_EMBEDDING_ALLOWED_HTTP_ORIGINS": "http://10.251.231.23:8000"})
    data = configuration()
    assert data["base_url"] == values["KNOWLEDGE_EMBEDDING_BASE_URL"]
    assert data["api_key"] == "test-local-secret" and data["configured"]


def test_chinese_documents_use_bounded_complete_chunks_for_cpu_embedding(semantic_case, mocker):
    from plane.knowledge import semantic

    project, article, revision = semantic_case
    revision.content = "设备连接失败，检查监听服务。" * 80
    revision.save()
    mocker.patch("plane.knowledge.semantic_provider.configuration", side_effect=lambda: config())
    seen = []

    def embed(texts, cfg):
        seen.extend(texts)
        assert all(len(text) <= 350 for text in texts)
        return [[1.0, 0.0] for _ in texts]

    mocker.patch("plane.knowledge.semantic_provider.embed", side_effect=embed)
    job = semantic.request_build(project)
    assert semantic.run_build(project.id, job.token)["status"] == "completed"
    assert "".join(seen) == semantic.document(revision)
