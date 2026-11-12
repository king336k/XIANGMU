"""A single login form identifies credentials without granting another same-name identity."""

from uuid import uuid4
import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.exceptions import AuthenticationFailed
from plane.db.models import User
from plane.license.models import Instance
from plane.quality.models import PlatformAccount
from plane.quality.platform import PlatformUnavailable

pytestmark = [pytest.mark.contract, pytest.mark.django_db]
URL = "/api/quality-auth/login/"


@pytest.fixture
def login_env(mocker):
    from plane.quality.legacy_login import LoginThrottle

    key = LoginThrottle.cache_format % {"scope": LoginThrottle.scope, "ident": "127.0.0.1"}
    cache.delete(key)
    Instance.objects.create(
        instance_name="统一登录",
        instance_id=str(uuid4()),
        current_version="test",
        last_checked_at=timezone.now(),
        is_setup_done=True,
    )
    config = {
        "kind": "data_platform",
        "login_enabled": True,
        "login_auto_provision": True,
        "service_token": "test-only-service",
        "login_role_map": {},
    }
    # No production authority is contacted by contract tests.
    mocker.patch("plane.quality.unified_login.configured_sources", return_value=[("data-main", config)], create=True)
    directory = mocker.patch(
        "plane.quality.platform.fetch",
        return_value=[{"id": 42, "username": "same-user", "active": True, "role": "Pending"}],
    )

    def authenticate(_config, username, password):
        if password != "source-password":
            raise AuthenticationFailed("invalid")
        return {"id": 42, "username": "same-user", "status": "Active", "role": "Pending"}, "test-source-session-token"

    source = mocker.patch("plane.quality.data_accounts.authenticate_upstream", side_effect=authenticate)
    mocker.patch("plane.quality.data_accounts.authority_config", return_value=config)
    mocker.patch("plane.quality.data_accounts.authority_request", return_value=True)
    local = User.objects.create(username="same-user", email="same-user@example.invalid", is_active=True)
    local.set_password("local-password")
    local.save()
    yield local, directory, source, config
    cache.delete(key)


def submit(password, username="same-user", client=None, **extra):
    client = client or APIClient()
    r = client.post(URL, {"username": username, "password": password, **extra}, format="json")
    return client, r


def test_same_username_local_password_uses_local_identity(login_env):
    local, directory, source, config = login_env
    c, r = submit("local-password")
    assert r.status_code == 200, r.content
    assert c.session["_auth_user_id"] == str(local.id)
    assert "quality_data_account" not in c.session
    assert not PlatformAccount.objects.exists()
    assert local.email not in str(r.data)


def test_same_username_source_password_never_establishes_local_session(login_env):
    local, directory, source, config = login_env
    c, r = submit("source-password")
    assert r.status_code in {401, 403}, r.content
    assert "_auth_user_id" not in c.session
    assert not PlatformAccount.objects.exists()
    source.assert_not_called()
    directory.assert_not_called()


def test_identical_source_name_cannot_override_local_identity(login_env):
    local, directory, source, config = login_env
    local.set_password("source-password")
    local.save()
    c, r = submit("source-password")
    assert r.status_code == 200, r.content
    assert c.session["_auth_user_id"] == str(local.id)
    assert not PlatformAccount.objects.exists()
    source.assert_not_called()
    directory.assert_not_called()


def test_unknown_username_does_not_forward_password_to_any_authority(login_env):
    local, directory, source, config = login_env
    c, r = submit("must-not-forward", username="unknown")
    assert r.status_code in {401, 403}, r.content
    source.assert_not_called()
    assert "_auth_user_id" not in c.session


def test_retired_authority_failure_does_not_block_local_login(login_env):
    local, directory, source, config = login_env
    source.side_effect = PlatformUnavailable()
    c, r = submit("local-password")
    assert r.status_code == 200, r.content
    assert c.session["_auth_user_id"] == str(local.id)
    source.assert_not_called()
    directory.assert_not_called()


def test_directory_failure_does_not_send_password_to_sources(login_env):
    local, directory, source, config = login_env
    directory.side_effect = PlatformUnavailable()
    c, r = submit("local-password")
    assert r.status_code == 200, r.content
    assert c.session["_auth_user_id"] == str(local.id)
    source.assert_not_called()
    directory.assert_not_called()


def test_wrong_password_and_disabled_local_cannot_create_session(login_env):
    local, directory, source, config = login_env
    for password in ["wrong-password", "local-password"]:
        local.is_active = False
        local.save(update_fields=["is_active"])
        c, r = submit(password)
        assert r.status_code in {401, 403}, r.content
        assert "_auth_user_id" not in c.session


def test_unified_login_keeps_csrf_origin_and_rate_limit(login_env):
    local, directory, source, config = login_env
    c, r = submit("local-password", client=APIClient(enforce_csrf_checks=True))
    assert r.status_code == 403
    c, r = submit("local-password", client=APIClient(HTTP_ORIGIN="https://outside.example"))
    assert r.status_code == 403
    for _ in range(10):
        c, r = submit("wrong")
    assert r.status_code == 429, r.content


def test_client_cannot_choose_source_or_redirect_to_external_host(login_env):
    local, directory, source, config = login_env
    c, r = submit("local-password", source_instance="evil-source", next_path="https://outside.example/")
    assert r.status_code == 200, r.content
    assert r.data["next"].startswith("/") and not r.data["next"].startswith("//")
    assert c.session["_auth_user_id"] == str(local.id)


def test_other_source_password_never_establishes_platform_session(login_env):
    local, directory, source, config = login_env
    c, r = submit("second-password")
    assert r.status_code in {401, 403}, r.content
    assert "_auth_user_id" not in c.session
    assert not PlatformAccount.objects.exists()
    source.assert_not_called()
    directory.assert_not_called()


def test_local_only_login_still_uses_enabled_native_provider(login_env, mocker):
    local, directory, source, config = login_env
    mocker.patch("plane.quality.unified_login.configured_sources", return_value=[])
    c, r = submit("local-password")
    assert r.status_code == 200 and c.session["_auth_user_id"] == str(local.id)
    directory.assert_not_called()
    source.assert_not_called()
