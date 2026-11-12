"""Built-in local retrieval is deployment-managed and independent of chat credentials."""

import pytest
from plane.db.models import Project
from plane.knowledge import semantic_provider, semantic
from plane.knowledge.models import Article, PublishedRevision
from plane.knowledge.semantic_models import SemanticProjectIndex

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def builtin_env(mocker):
    mocker.patch.dict(
        "os.environ",
        {
            "KNOWLEDGE_BUILTIN_EMBEDDING_BASE_URL": "http://builtin-embedding:18885/v1",
            "KNOWLEDGE_BUILTIN_EMBEDDING_API_KEY": "test-only-builtin-secret",
            "KNOWLEDGE_BUILTIN_EMBEDDING_MODEL": "bge-small-zh-v1.5",
            "KNOWLEDGE_EMBEDDING_ALLOWED_HTTP_ORIGINS": "http://builtin-embedding:18885",
        },
    )


def test_builtin_retrieval_is_ready_without_chat_or_manual_embedding_fields(builtin_env, mocker):
    mocker.patch(
        "plane.knowledge.assistant.provider_config",
        return_value={"configured": False, "model": "chat", "base_url": "https://api.openai.com/v1", "api_key": ""},
    )
    value = semantic_provider.configuration()
    assert value["configured"] and value["enabled"]
    assert value["source"] == "builtin" and value["model"] == "bge-small-zh-v1.5"
    assert value["base_url"] == "http://builtin-embedding:18885/v1"
    status = semantic_provider.public_status(value)
    assert status["managed"] is True and status["source"] == "builtin"
    assert "api_key" not in status and "test-only-builtin-secret" not in str(status)


def test_published_knowledge_uses_builtin_index_without_manual_project_optin(builtin_env, workspace, mocker):
    project = Project.objects.create(workspace=workspace, name="内置检索", identifier="KBLOCAL")
    mocker.patch("plane.knowledge.semantic.enqueue")
    semantic.schedule_if_opted_in(project)
    assert SemanticProjectIndex.objects.filter(project=project).exists()


def test_existing_publications_lazily_queue_builtin_index_once(
    builtin_env, workspace, mocker, django_capture_on_commit_callbacks
):
    project = Project.objects.create(workspace=workspace, name="已有知识", identifier="KBREADY")
    article = Article.objects.create(
        project=project,
        title="故障",
        content="端口异常",
        status="published",
        publication_active=True,
        published_version=1,
    )
    PublishedRevision.objects.create(
        project=project, article=article, version=1, title=article.title, content=article.content
    )
    queued = mocker.patch("plane.knowledge.semantic.enqueue")
    with django_capture_on_commit_callbacks(execute=True):
        assert semantic.ranked_ids(project, "连接异常") is None
        assert SemanticProjectIndex.objects.filter(project=project, status="queued").exists()
        semantic.ranked_ids(project, "连接异常")
    assert queued.call_count == 1


def test_explicit_external_connection_remains_preserved_with_builtin_available(builtin_env, mocker):
    values = {
        "KNOWLEDGE_EMBEDDING_MODE": "external",
        "KNOWLEDGE_SEMANTIC_ENABLED": "true",
        "KNOWLEDGE_EMBEDDING_MODEL": "external-vector",
        "KNOWLEDGE_EMBEDDING_BASE_URL": "https://api.openai.com/v1",
        "KNOWLEDGE_EMBEDDING_API_KEY": "external-test-key",
    }
    mocker.patch(
        "plane.knowledge.assistant.model_option",
        side_effect=lambda name, fallback, workspace_id=None: values.get(name, fallback),
    )
    value = semantic_provider.configuration()
    assert value["source"] == "external" and value["model"] == "external-vector"
    assert value["api_key"] == "external-test-key"


def test_legacy_external_endpoint_is_not_silently_replaced(builtin_env, mocker):
    values = {
        "KNOWLEDGE_SEMANTIC_ENABLED": "true",
        "KNOWLEDGE_EMBEDDING_MODEL": "bge-small-zh-v1.5",
        "KNOWLEDGE_EMBEDDING_BASE_URL": "https://api.openai.com/v1",
        "KNOWLEDGE_EMBEDDING_API_KEY": "legacy-custom-key",
    }
    mocker.patch(
        "plane.knowledge.assistant.model_option",
        side_effect=lambda name, fallback, workspace_id=None: values.get(name, fallback),
    )
    config = semantic_provider.configuration()
    assert config["source"] == "external" and config["api_key"] == "legacy-custom-key"


def test_broken_explicit_external_config_never_uses_chat_model(builtin_env, mocker):
    values = {
        "KNOWLEDGE_EMBEDDING_MODE": "external",
        "KNOWLEDGE_SEMANTIC_ENABLED": "true",
        "KNOWLEDGE_EMBEDDING_MODEL": "vector-model",
    }
    mocker.patch(
        "plane.knowledge.assistant.model_option",
        side_effect=lambda name, fallback, workspace_id=None: values.get(name, fallback),
    )
    mocker.patch(
        "plane.knowledge.assistant.provider_config",
        return_value={"base_url": "https://api.openai.com/v1", "api_key": "chat-key", "configured": True},
    )
    config = semantic_provider.configuration()
    assert config["source"] == "external" and config["configured"] is False and not config["api_key"]


def test_public_https_provider_cannot_be_automatically_treated_as_local_builtin(builtin_env, mocker):
    mocker.patch.dict("os.environ", {"KNOWLEDGE_BUILTIN_EMBEDDING_BASE_URL": "https://api.openai.com/v1"})
    config = semantic_provider.configuration()
    assert config["source"] != "builtin" or not config["configured"]
