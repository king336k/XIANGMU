"""Simple connection edits preserve advanced configuration and secret boundaries."""

from uuid import uuid4
import pytest
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate
from plane.license.models import Instance, InstanceAdmin
from plane.quality.connection_settings import read_connection

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def administrator(create_user):
    instance = Instance.objects.create(
        instance_name="连接简化", instance_id=str(uuid4()), current_version="test", last_checked_at=timezone.now()
    )
    InstanceAdmin.objects.create(instance=instance, user=create_user)
    return create_user


def request(user, method="post", data=None):
    from plane.quality.connection_settings import GlobalConnectionSettings

    factory = APIRequestFactory()
    raw = getattr(factory, method)("/api/quality-auth/connections/", data or {}, format="json")
    force_authenticate(raw, user)
    return GlobalConnectionSettings.as_view()(raw)


def test_create_needs_only_type_address_and_optional_credential(administrator):
    response = request(
        administrator,
        data={"kind": "data_platform", "base_url": "http://10.20.30.40:6324", "service_token": "synthetic-only"},
    )
    assert response.status_code == 201, response.data
    name = response.data["source_instance"]
    assert name.startswith("data-platform-")
    config = read_connection(name)
    assert config["allow_http_local"] is True
    assert config["portal_url"] == "http://10.20.30.40:6324"
    assert config["bridge_key_id"] and config["bridge_audience"] == "plane-quality"
    assert not config["bridge_secret"]
    assert "synthetic-only" not in str(response.data)


def test_edit_basic_fields_preserves_hidden_configuration_and_secrets(administrator):
    response = request(
        administrator,
        data={
            "source_instance": "existing",
            "kind": "data_platform",
            "base_url": "https://platform.example",
            "service_token": "synthetic-token",
            "bridge_secret": "synthetic-signature",
            "bridge_key_id": "existing-key",
            "bridge_audience": "existing-audience",
            "login_enabled": True,
            "login_auto_provision": True,
            "login_role_map": {"Admin": "PLATFORM_ADMIN", "Collector": "REPORTER"},
            "portal_url": "https://portal.example",
        },
    )
    assert response.status_code == 201, response.data
    before = read_connection("existing")
    response = request(
        administrator,
        data={
            "source_instance": "existing",
            "kind": "data_platform",
            "base_url": "https://new.example",
            "service_token": "",
        },
    )
    assert response.status_code == 201, response.data
    after = read_connection("existing")
    for key in [
        "service_token",
        "bridge_secret",
        "bridge_key_id",
        "bridge_audience",
        "login_enabled",
        "login_auto_provision",
        "login_role_map",
        "portal_url",
    ]:
        assert after[key] == before[key], key
    assert after["base_url"] == "https://new.example"


def test_global_admin_does_not_need_any_project_and_secret_is_never_listed(administrator):
    response = request(
        administrator,
        data={"kind": "data_platform", "base_url": "http://10.20.30.40", "service_token": "synthetic-token"},
    )
    assert response.status_code == 201
    listed = request(administrator, "get")
    assert listed.status_code == 200 and listed.data["can_configure"]
    assert listed.data["results"][0]["allow_private_http"] is True
    assert "synthetic-token" not in str(listed.data)


def test_nonadministrator_cannot_read_or_modify_global_connections(create_user):
    assert request(create_user, "get").status_code == 403
    assert (
        request(create_user, data={"kind": "data_platform", "base_url": "https://platform.example"}).status_code == 403
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://8.8.8.8",
        "http://127.0.0.1",
        "http://169.254.169.254",
        "https://name:secret@platform.example",
        "https://platform.example/path",
    ],
)
def test_simplification_keeps_connection_address_guards(administrator, url):
    response = request(administrator, data={"kind": "data_platform", "base_url": url})
    assert response.status_code == 400, response.data


def test_explicit_disable_and_credential_clear_still_work(administrator):
    first = request(
        administrator,
        data={
            "source_instance": "clearable",
            "kind": "data_platform",
            "base_url": "https://platform.example",
            "service_token": "synthetic-token",
            "login_enabled": True,
        },
    )
    assert first.status_code == 201
    response = request(
        administrator,
        data={
            "source_instance": "clearable",
            "kind": "data_platform",
            "base_url": "https://platform.example",
            "clear_token": True,
            "login_enabled": False,
        },
    )
    assert response.status_code == 201
    config = read_connection("clearable")
    assert config["service_token"] == "" and config["login_enabled"] is False


def test_basic_edit_keeps_legacy_directory_settings(administrator):
    initial = {
        "source_instance": "legacy-preserve",
        "kind": "legacy_hub",
        "base_url": "https://legacy.example",
        "directory_auth": "trusted_v2",
        "directory_key_id": "directory-test",
        "directory_user_id": 19,
        "directory_username": "readonly-test",
    }
    assert request(administrator, data=initial).status_code == 201
    response = request(
        administrator, data={"source_instance": "legacy-preserve", "base_url": "https://updated.example"}
    )
    assert response.status_code == 201, response.data
    stored = read_connection("legacy-preserve")
    for name in ["directory_auth", "directory_key_id", "directory_user_id", "directory_username"]:
        assert stored[name] == initial[name]


def test_same_generated_source_identifier_makes_ui_retry_update_same_connection(administrator):
    from plane.license.models import InstanceConfiguration

    payload = {
        "source_instance": "source-automatic-stable",
        "kind": "data_platform",
        "base_url": "https://platform.example",
    }
    assert request(administrator, data=payload).status_code == 201
    assert request(administrator, data=payload).status_code == 201
    assert InstanceConfiguration.objects.filter(key="QUALITY_SOURCE:source-automatic-stable").count() == 1


def test_edit_cannot_repurpose_an_existing_connection_identity(administrator):
    assert (
        request(
            administrator,
            data={"source_instance": "immutable-type", "kind": "data_platform", "base_url": "https://platform.example"},
        ).status_code
        == 201
    )
    response = request(
        administrator,
        data={"source_instance": "immutable-type", "kind": "feishu", "base_url": "https://open.feishu.cn"},
    )
    assert response.status_code == 400
    assert read_connection("immutable-type")["kind"] == "data_platform"


@pytest.mark.parametrize("data", [{"source_instance": {"bad": "type"}}, {"base_url": "https://[invalid"}])
def test_invalid_basic_input_is_validation_error_without_server_error(administrator, data):
    response = request(administrator, data={"kind": "data_platform", "base_url": "https://platform.example", **data})
    assert response.status_code == 400, response.data
