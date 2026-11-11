"""Importers discover ready Feishu connection identifiers without configuration secrets."""
import json
from uuid import uuid4

import pytest
from django.utils import timezone

from plane.db.models import Project, ProjectMember, WorkspaceMember
from plane.license.models import Instance, InstanceAdmin, InstanceConfiguration
from plane.quality.models import BusinessRole, ProjectRolePolicy

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def options(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="飞书连接选项", identifier="FSOPT")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    return f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/document-imports/feishu/connections/", project


def configure(name, **changes):
    config = {
        "kind": "feishu", "base_url": "https://open.feishu.cn", "service_token": "synthetic-service-canary",
        "bridge_secret": "synthetic-bridge-canary", "bridge_key_id": "private-key-id",
        "allowed_hosts": ["private.invalid"], "login_role_map": {"Admin": "PLATFORM_ADMIN"},
    }
    config.update(changes)
    return InstanceConfiguration.objects.create(key="QUALITY_SOURCE:" + name, value=json.dumps(config), is_encrypted=False)


def test_empty_options_explain_administrator_without_configuration_details(session_client, options):
    response = session_client.get(options[0])
    assert response.status_code == 200
    assert response.data["results"] == [] and response.data["count"] == 0
    assert response.data["can_configure"] is False
    assert "管理员" in response.data["notice"] and "实例管理员" not in response.data["notice"]


def test_ready_options_are_identifiers_only_and_read_only_without_network(session_client, options, mocker):
    configure("feishu-main")
    network = mocker.patch("requests.sessions.Session.request", side_effect=AssertionError("discovery cannot call network"))
    before = list(InstanceConfiguration.objects.values_list("key", "value", "is_encrypted"))
    response = session_client.get(options[0])
    assert response.status_code == 200
    assert response.data["results"] == [{"source_instance": "feishu-main", "label": "feishu-main"}]
    assert response.data["count"] == 1
    text = json.dumps(response.data)
    assert all(value not in text for value in ["synthetic-service-canary", "synthetic-bridge-canary", "private.invalid", "private-key-id", "token_present", "base_url", "login_role_map"])
    assert before == list(InstanceConfiguration.objects.values_list("key", "value", "is_encrypted"))
    network.assert_not_called()


def test_encrypted_ready_connection_is_listed_but_invalid_ciphertext_is_ignored(session_client, options):
    from plane.license.utils.encryption import encrypt_data
    row = configure("encrypted-ready")
    row.value = encrypt_data(row.value)
    row.is_encrypted = True
    row.save()
    InstanceConfiguration.objects.create(key="QUALITY_SOURCE:bad-ciphertext", value="not-valid-ciphertext", is_encrypted=True)
    response = session_client.get(options[0])
    assert response.status_code == 200
    assert response.data["results"] == [{"source_instance": "encrypted-ready", "label": "encrypted-ready"}]


def test_discovery_endpoint_cannot_write_configurations(session_client, options):
    configure("fs-main")
    before = list(InstanceConfiguration.objects.values_list("key", "value"))
    response = session_client.post(options[0], {"source_instance": "new-source", "service_token": "must-not-save"}, format="json")
    assert response.status_code in [403, 405]
    assert before == list(InstanceConfiguration.objects.values_list("key", "value"))


def test_platform_admin_flag_requires_instance_role_twenty(session_client, options, create_user):
    instance = Instance.objects.create(instance_name="options fixture", instance_id=str(uuid4()), current_version="test", last_checked_at=timezone.now())
    admin = InstanceAdmin.objects.create(instance=instance, user=create_user, role=15)
    assert session_client.get(options[0]).data["can_configure"] is False
    admin.role = 20
    admin.save()
    assert session_client.get(options[0]).data["can_configure"] is True


@pytest.mark.parametrize("change", [
    {"kind": "data_platform"}, {"kind": "ota"}, {"service_token": ""}, {"service_token": "  "},
    {"service_token": None}, {"service_token": True}, {"service_token": ["not-a-token"]},
    {"base_url": "http://open.feishu.cn"}, {"base_url": "https://open.feishu.cn.invalid"},
    {"base_url": "https://open.feishu.cn:443"}, {"base_url": "https://user:password@open.feishu.cn"},
    {"base_url": "https://open.feishu.cn/path"}, {"base_url": "https://open.feishu.cn?token=private"},
    {"base_url": "https://open.feishu.cn#private"}, {"base_url": "https://[invalid"}, {"base_url": None},
    {"base_url": " https://open.feishu.cn"}, {"base_url": "https://open.feishu.cn\n"},
])
def test_only_official_origin_with_configured_string_token_is_listed(session_client, options, change):
    configure("hidden", **change)
    assert session_client.get(options[0]).data["results"] == []


def test_invalid_json_non_object_and_invalid_identifier_are_ignored(session_client, options):
    for name, raw in [("malformed", "{"), ("list", "[]"), ("null", "null")]:
        InstanceConfiguration.objects.create(key="QUALITY_SOURCE:" + name, value=raw, is_encrypted=False)
    configure("not/a/source")
    configure("official", base_url="https://open.feishu.cn/")
    response = session_client.get(options[0])
    assert response.status_code == 200
    assert response.data["results"] == [{"source_instance": "official", "label": "official"}]


def test_options_are_sorted_paginated_and_searchable(session_client, options):
    for index in range(23):
        configure(f"fs-{index:02}")
    response = session_client.get(options[0], {"page": 2, "per_page": 20})
    assert response.status_code == 200
    assert response.data["count"] == 23 and response.data["page"] == 2 and response.data["page_size"] == 20
    assert [item["source_instance"] for item in response.data["results"]] == ["fs-20", "fs-21", "fs-22"]
    searched = session_client.get(options[0], {"search": "FS-22", "per_page": 1})
    assert searched.data["count"] == 1 and searched.data["results"][0]["source_instance"] == "fs-22"


@pytest.mark.parametrize("query", [{"page": 0}, {"page": "invalid"}, {"per_page": 51}, {"per_page": 0}, {"search": "x" * 81}])
def test_pagination_input_is_bounded(session_client, options, query):
    assert session_client.get(options[0], query).status_code == 400


@pytest.mark.parametrize("boundary", ["project_guest", "workspace_guest", "project_inactive", "workspace_inactive", "user_inactive", "cross_project", "no_business_capability"])
def test_non_importers_cannot_discover_any_connections(session_client, options, workspace, create_user, boundary):
    endpoint, project = options
    configure("hidden-from-non-importer")
    if boundary == "project_guest":
        ProjectMember.objects.filter(project=project, member=create_user).update(role=5)
    elif boundary == "workspace_guest":
        WorkspaceMember.objects.filter(workspace=workspace, member=create_user).update(role=5)
    elif boundary == "project_inactive":
        ProjectMember.objects.filter(project=project, member=create_user).update(is_active=False)
    elif boundary == "workspace_inactive":
        WorkspaceMember.objects.filter(workspace=workspace, member=create_user).update(is_active=False)
    elif boundary == "user_inactive":
        create_user.is_active = False
        create_user.save()
    elif boundary == "cross_project":
        ProjectMember.objects.filter(project=project, member=create_user).delete()
    else:
        ProjectRolePolicy.objects.create(project=project, enabled=True)
        BusinessRole.objects.create(project=project, user=create_user, role="REPORTER")
        ProjectMember.objects.filter(project=project, member=create_user).update(role=15)
        WorkspaceMember.objects.filter(workspace=workspace, member=create_user).update(role=15)
    response = session_client.get(endpoint)
    assert response.status_code == 403
    assert "hidden-from-non-importer" not in str(response.data)


def test_unauthenticated_client_cannot_list_connections(api_client, options):
    assert api_client.get(options[0]).status_code in [401, 403]


@pytest.mark.parametrize("capability", ["knowledge_edit", "manage_test"])
def test_either_import_capability_allows_discovery(session_client, options, mocker, capability):
    configure("fs-main")
    mocker.patch("plane.quality.connection_settings.capable", side_effect=lambda project, user, name: name == capability)
    response = session_client.get(options[0])
    assert response.status_code == 200 and response.data["count"] == 1
