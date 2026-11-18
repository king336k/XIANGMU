import json
from uuid import uuid4

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from plane.db.models import Workspace, WorkspaceMember
from plane.knowledge.assistant import provider_config
from plane.license.models import Instance, InstanceAdmin, InstanceConfiguration

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def model_client(workspace, create_user, monkeypatch):
    instance = Instance.objects.create(
        instance_name="profiles",
        instance_id=str(uuid4()),
        current_version="test",
        last_checked_at=timezone.now(),
    )
    InstanceAdmin.objects.create(instance=instance, user=create_user)
    monkeypatch.setenv("KNOWLEDGE_LLM_ALLOWED_HTTP_ORIGINS", "http://10.10.10.193:3000")
    client = APIClient()
    client.force_authenticate(create_user)
    return client, f"/api/workspaces/{workspace.slug}/model-configuration/"


def test_add_switch_and_edit_profiles_preserve_each_key(model_client, workspace):
    client, path = model_client
    original = {"model": "original", "base_url": "https://api.openai.com/v1", "api_key": "synthetic-original"}
    assert client.patch(path, original, format="json").status_code == 200
    response = client.patch(
        path,
        {
            "profile_action": "create",
            "model": "cx/gpt-6.1-sol",
            "base_url": "http://10.10.10.193:3000/v1",
            "api_key": "synthetic-local",
        },
        format="json",
    )
    assert response.status_code == 200, response.content
    assert len(response.data["profiles"]) == 2
    old_id, new_id = [p["id"] for p in response.data["profiles"]]
    assert response.data["active_profile_id"] == new_id
    assert provider_config(workspace.id)["api_key"] == "synthetic-local"
    assert "synthetic-" not in json.dumps(response.data)
    assert (
        client.patch(path, {"profile_action": "activate", "profile_id": old_id}, format="json").status_code
        == 200
    )
    assert provider_config(workspace.id)["api_key"] == "synthetic-original"
    assert provider_config(workspace.id)["model"] == "original"
    assert client.patch(path, {"model": "original-edited", "api_key": ""}, format="json").status_code == 200
    assert (
        client.patch(path, {"profile_action": "activate", "profile_id": new_id}, format="json").status_code
        == 200
    )
    assert provider_config(workspace.id)["api_key"] == "synthetic-local"
    assert (
        client.patch(path, {"profile_action": "activate", "profile_id": old_id}, format="json").status_code
        == 200
    )
    assert provider_config(workspace.id)["model"] == "original-edited"
    saved = InstanceConfiguration.objects.get(key=f"WS:{workspace.id}:KNOWLEDGE_MODEL_PROFILES")
    assert saved.is_encrypted and "synthetic-" not in saved.value


def test_creation_requires_own_key_and_activation_revalidates_origin(model_client, workspace, monkeypatch):
    client, path = model_client
    assert client.patch(path, {"model": "old", "api_key": "synthetic-old"}, format="json").status_code == 200
    response = client.patch(
        path,
        {"profile_action": "create", "model": "new", "base_url": "http://10.10.10.193:3000/v1"},
        format="json",
    )
    assert response.status_code == 400
    assert provider_config(workspace.id)["api_key"] == "synthetic-old"
    response = client.patch(
        path,
        {
            "profile_action": "create",
            "model": "new",
            "base_url": "http://10.10.10.193:3000/v1",
            "api_key": "synthetic-new",
        },
        format="json",
    )
    new_id = response.data["active_profile_id"]
    old_id = response.data["profiles"][0]["id"]
    assert (
        client.patch(path, {"profile_action": "activate", "profile_id": old_id}, format="json").status_code
        == 200
    )
    monkeypatch.setenv("KNOWLEDGE_LLM_ALLOWED_HTTP_ORIGINS", "")
    assert (
        client.patch(path, {"profile_action": "activate", "profile_id": new_id}, format="json").status_code
        == 400
    )
    assert provider_config(workspace.id)["model"] == "old"


def test_profile_ids_are_workspace_scoped_and_mixed_actions_rejected(model_client, workspace, create_user):
    client, path = model_client
    assert (
        client.patch(path, {"model": "private", "api_key": "synthetic-private"}, format="json").status_code
        == 200
    )
    profile_id = client.get(path).data["active_profile_id"]
    other = Workspace.objects.create(name="Other", slug="other-profiles", owner=create_user)
    WorkspaceMember.objects.create(workspace=other, member=create_user, role=20)
    other_path = f"/api/workspaces/{other.slug}/model-configuration/"
    assert (
        client.patch(
            other_path, {"profile_action": "activate", "profile_id": profile_id}, format="json"
        ).status_code
        == 400
    )
    assert (
        client.patch(
            path,
            {"profile_action": "activate", "profile_id": profile_id, "model": "unexpected"},
            format="json",
        ).status_code
        == 400
    )
    client.force_authenticate(None)
    assert client.patch(
        path, {"profile_action": "activate", "profile_id": profile_id}, format="json"
    ).status_code in {401, 403}


def test_clearing_one_key_does_not_clear_other_profiles(model_client, workspace):
    client, path = model_client
    first = client.patch(path, {"model": "first", "api_key": "synthetic-first"}, format="json").data[
        "active_profile_id"
    ]
    second = client.patch(
        path,
        {
            "profile_action": "create",
            "model": "second",
            "base_url": "https://api.openai.com/v1",
            "api_key": "synthetic-second",
        },
        format="json",
    ).data["active_profile_id"]
    assert client.patch(path, {"clear_key": True}, format="json").status_code == 200
    assert provider_config(workspace.id)["api_key"] == ""
    assert (
        client.patch(path, {"profile_action": "activate", "profile_id": first}, format="json").status_code
        == 200
    )
    assert provider_config(workspace.id)["api_key"] == "synthetic-first"
    assert (
        client.patch(path, {"profile_action": "activate", "profile_id": second}, format="json").status_code
        == 200
    )
    assert provider_config(workspace.id)["api_key"] == ""


def test_encryption_failure_keeps_original_configuration(model_client, workspace, monkeypatch):
    client, path = model_client
    assert (
        client.patch(path, {"model": "original", "api_key": "synthetic-original"}, format="json").status_code
        == 200
    )
    monkeypatch.setattr("plane.knowledge.configuration.encrypt_data", lambda _: "")
    response = client.patch(
        path,
        {
            "profile_action": "create",
            "model": "failed",
            "base_url": "https://api.openai.com/v1",
            "api_key": "synthetic-new",
        },
        format="json",
    )
    assert response.status_code == 400
    assert provider_config(workspace.id)["model"] == "original"
    assert len(client.get(path).data["profiles"]) == 1


def test_edit_inactive_profile_preserves_active_model_and_both_keys(model_client, workspace):
    client, path = model_client
    original = client.patch(path, {"model": "original", "api_key": "synthetic-original"}, format="json").data[
        "active_profile_id"
    ]
    current = client.patch(
        path,
        {
            "profile_action": "create",
            "model": "current",
            "base_url": "https://api.openai.com/v1",
            "api_key": "synthetic-current",
        },
        format="json",
    ).data["active_profile_id"]
    response = client.patch(
        path,
        {
            "profile_id": original,
            "model": "renamed",
            "base_url": "http://10.10.10.193:3000/v1",
            "api_key": "",
        },
        format="json",
    )
    assert response.status_code == 200, response.content
    assert response.data["active_profile_id"] == current
    assert provider_config(workspace.id)["model"] == "current"
    assert provider_config(workspace.id)["api_key"] == "synthetic-current"
    assert (
        client.patch(path, {"profile_action": "activate", "profile_id": original}, format="json").status_code
        == 200
    )
    assert provider_config(workspace.id)["model"] == "renamed"
    assert provider_config(workspace.id)["base_url"] == "http://10.10.10.193:3000/v1"
    assert provider_config(workspace.id)["api_key"] == "synthetic-original"
    assert (
        client.patch(
            path, {"profile_id": current, "api_key": "synthetic-replacement"}, format="json"
        ).status_code
        == 200
    )
    assert provider_config(workspace.id)["api_key"] == "synthetic-original"
    assert (
        client.patch(path, {"profile_action": "activate", "profile_id": current}, format="json").status_code
        == 200
    )
    assert provider_config(workspace.id)["api_key"] == "synthetic-replacement"
    assert "synthetic-" not in json.dumps(client.get(path).data)


def test_inactive_edit_cannot_change_shared_embedding_settings(model_client, workspace):
    client, path = model_client
    original = client.patch(path, {"model": "original", "api_key": "synthetic-original"}, format="json").data[
        "active_profile_id"
    ]
    client.patch(
        path,
        {
            "profile_action": "create",
            "model": "current",
            "base_url": "https://api.openai.com/v1",
            "api_key": "synthetic-current",
        },
        format="json",
    )
    assert (
        client.patch(path, {"profile_id": original, "embedding_mode": "builtin"}, format="json").status_code
        == 400
    )
    assert (
        client.patch(
            path, {"profile_id": original, "base_url": "http://10.10.10.194:3000/v1"}, format="json"
        ).status_code
        == 400
    )
    assert (
        client.patch(path, {"profile_id": str(uuid4()), "model": "foreign"}, format="json").status_code == 400
    )
    assert provider_config(workspace.id)["model"] == "current"


def test_delete_inactive_profile_preserves_active_configuration(model_client,workspace):
    client,path=model_client
    first=client.patch(path,{"model":"original","base_url":"https://api.openai.com/v1","api_key":"synthetic-original"},format="json")
    original=first.data["active_profile_id"]
    added=client.patch(path,{"profile_action":"create","model":"second","base_url":"https://api.openai.com/v1","api_key":"synthetic-second"},format="json")
    active=added.data["active_profile_id"]
    assert client.patch(path,{"profile_action":"delete","profile_id":active},format="json").status_code==400
    response=client.patch(path,{"profile_action":"delete","profile_id":original},format="json")
    assert response.status_code==200,response.content
    assert response.data["active_profile_id"]==active and len(response.data["profiles"])==1
    assert provider_config(workspace.id)["api_key"]=="synthetic-second"
    assert "synthetic-original" not in str(response.data) and "synthetic-second" not in str(response.data)
    assert client.patch(path,{"profile_action":"delete","profile_id":original},format="json").status_code == 400


def test_delete_requires_exact_profile_payload_and_cannot_change_active_fields(model_client,workspace):
    client, path = model_client
    first = client.patch(path, {"model":"original","base_url":"https://api.openai.com/v1","api_key":"synthetic-original"}, format="json")
    original = first.data["active_profile_id"]
    client.patch(path, {"profile_action":"create","model":"second","base_url":"https://api.openai.com/v1","api_key":"synthetic-second"}, format="json")
    for payload in [
        {"profile_action":"delete"},
        {"profile_action":"delete","profile_id":original,"model":"injected"},
        {"profile_action":"delete","profile_id":original,"clear_key":True},
    ]:
        assert client.patch(path, payload, format="json").status_code == 400
    assert len(client.get(path).data["profiles"]) == 2
    assert provider_config(workspace.id)["model"] == "second"
