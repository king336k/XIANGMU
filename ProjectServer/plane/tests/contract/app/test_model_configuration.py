"""Model settings expose safe metadata and reuse encrypted instance configuration."""

import pytest
from plane.db.models import Project, ProjectMember
from plane.license.models import Instance, InstanceAdmin, InstanceConfiguration
from plane.knowledge import assistant
from django.utils import timezone
from uuid import uuid4

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def test_chat_only_save_preserves_builtin_mode_and_encrypted_embedding_config(
    session_client, model_project, create_user
):
    instance = Instance.objects.create(
        instance_name="内置配置保护", instance_id=str(uuid4()), current_version="test", last_checked_at=timezone.now()
    )
    InstanceAdmin.objects.create(instance=instance, user=create_user, role=20)
    for key, value in [
        ("KNOWLEDGE_EMBEDDING_MODE", "builtin"),
        ("KNOWLEDGE_SEMANTIC_ENABLED", "true"),
        ("KNOWLEDGE_EMBEDDING_MODEL", "bge-small-zh-v1.5"),
    ]:
        InstanceConfiguration.objects.create(key=key, value=value, category="KNOWLEDGE")
    before = list(InstanceConfiguration.objects.filter(key__startswith="KNOWLEDGE_EMBEDDING").values())
    base, _ = model_project
    response = session_client.patch(
        base + "configuration/",
        {"model": "chat-new", "base_url": "https://api.openai.com/v1", "api_key": ""},
        format="json",
    )
    assert response.status_code == 200, response.content
    assert list(InstanceConfiguration.objects.filter(key__startswith="KNOWLEDGE_EMBEDDING").values()) == before
    assert InstanceConfiguration.objects.get(key="KNOWLEDGE_SEMANTIC_ENABLED").value == "true"


@pytest.fixture
def model_project(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="模型配置", identifier="MODELCFG")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    return f"/api/workspaces/{workspace.slug}/projects/{project.id}/knowledge/", project


def test_project_manager_can_read_status_but_not_change_global_model(session_client, model_project):
    base, _ = model_project
    state = session_client.get(base + "configuration/")
    assert state.status_code == 200, state.content
    assert state.data["can_configure"] is False
    assert "api_key" not in state.data
    assert session_client.patch(base + "configuration/", {"model": "demo-model"}, format="json").status_code == 403


def test_instance_admin_saves_encrypted_key_and_never_receives_key(session_client, model_project, create_user):
    base, _ = model_project
    instance = Instance.objects.create(
        instance_name="模型配置测试", instance_id=str(uuid4()), current_version="test", last_checked_at=timezone.now()
    )
    InstanceAdmin.objects.create(instance=instance, user=create_user, role=20)
    response = session_client.patch(
        base + "configuration/",
        {
            "api_key": "test-key-only-not-real",
            "model": "configured-test-model",
            "base_url": "https://api.openai.com/v1",
        },
        format="json",
    )
    assert response.status_code == 200, response.content
    assert response.data["configured"] is True and response.data["key_present"] is True
    assert "test-key-only-not-real" not in str(response.data)
    row = InstanceConfiguration.objects.get(key=f"WS:{model_project[1].workspace_id}:KNOWLEDGE_API_KEY")
    assert row.is_encrypted and row.value != "test-key-only-not-real"
    config = assistant.provider_config(model_project[1].workspace_id)
    assert config["api_key"] == "test-key-only-not-real" and config["model"] == "configured-test-model"
    assert (
        session_client.patch(
            base + "configuration/", {"api_key": "", "model": "renamed-model"}, format="json"
        ).status_code
        == 200
    )
    assert assistant.provider_config(model_project[1].workspace_id)["api_key"] == "test-key-only-not-real"
    cleared = session_client.patch(base + "configuration/", {"clear_key": True}, format="json")
    assert cleared.status_code == 200 and cleared.data["configured"] is False


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000/v1",
        "https://unknown.example/v1",
        "https://api.openai.com@unknown.example/v1",
        "https://api.openai.com/v1?key=bad",
    ],
)
def test_model_base_url_must_use_admin_allowed_destination(session_client, model_project, create_user, url):
    base, _ = model_project
    instance = Instance.objects.create(
        instance_name="模型配置测试", instance_id=str(uuid4()), current_version="test", last_checked_at=timezone.now()
    )
    InstanceAdmin.objects.create(instance=instance, user=create_user, role=20)
    response = session_client.patch(base + "configuration/", {"base_url": url}, format="json")
    assert response.status_code == 400, response.content


def test_private_model_relay_requires_exact_deployment_allowlist(monkeypatch):
    from plane.knowledge.assistant import valid_provider_url

    monkeypatch.setenv("KNOWLEDGE_LLM_ALLOWED_HTTP_ORIGINS", "http://10.10.10.193:3000")
    assert valid_provider_url("http://10.10.10.193:3000/v1")
    for url in [
        "http://10.10.10.194:3000/v1",
        "http://10.10.10.193:3001/v1",
        "http://10.10.10.193:3000.evil.invalid/v1",
        "http://10.10.10.193:3000/v1?key=bad",
        "http://name:password@10.10.10.193:3000/v1",
    ]:
        assert not valid_provider_url(url)
    monkeypatch.setenv("KNOWLEDGE_LLM_ALLOWED_HTTP_ORIGINS", "http://8.8.8.8:3000,http://169.254.169.254")
    assert not valid_provider_url("http://8.8.8.8:3000/v1")
    assert not valid_provider_url("http://169.254.169.254/v1")
