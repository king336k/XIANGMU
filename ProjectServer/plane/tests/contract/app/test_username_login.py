"""Username login reuses native authentication and never grants new permissions."""

import uuid
import pytest
from django.core.cache import cache
from django.test import Client
from django.utils import timezone
from plane.db.models import User
from plane.license.models import Instance

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def account():
    cache.delete_pattern("throttle_authentication_*")
    Instance.objects.create(
        instance_name="Username test",
        instance_id=str(uuid.uuid4()),
        current_version="test",
        last_checked_at=timezone.now(),
        is_setup_done=True,
    )
    user = User.objects.create(username="collector-test", email="collector-login@example.test")
    user.set_password("test-only-input")
    user.save()
    yield user
    cache.delete_pattern("throttle_authentication_*")


def client():
    return Client(HTTP_USER_AGENT="Username regression")


def test_username_password_creates_native_cookie_without_email_in_form(account):
    browser = client()
    response = browser.post("/auth/sign-in/", {"username": account.username, "password": "test-only-input"})
    assert response.status_code == 302 and "error_code" not in response.url
    assert browser.session["_auth_user_id"] == str(account.id)
    assert "test-only-input" not in str(dict(browser.session))
    assert not account.is_superuser


@pytest.mark.parametrize(
    "username,password",
    [("unknown-user", "test-only-input"), ("collector-test", "wrong-password"), ("x" * 256, "test-only-input")],
)
def test_username_errors_do_not_disclose_account_email(account, username, password):
    browser = client()
    response = browser.post("/auth/sign-in/", {"username": username, "password": password})
    assert response.status_code == 302 and "5065" in response.url
    assert account.email not in response.url and "email=" not in response.url
    assert "_auth_user_id" not in browser.session


@pytest.mark.parametrize("disabled,bot", [(True, False), (False, True)])
def test_disabled_or_service_account_cannot_use_username_login(account, disabled, bot):
    account.is_active = not disabled
    account.is_bot = bot
    account.save()
    browser = client()
    browser.post("/auth/sign-in/", {"username": account.username, "password": "test-only-input"})
    assert "_auth_user_id" not in browser.session
    account.refresh_from_db()
    assert account.is_active == (not disabled)


def test_username_email_collision_does_not_pick_an_account(account):
    other = User.objects.create(username=account.email, email="different@example.test")
    other.set_password("test-only-input")
    other.save()
    browser = client()
    response = browser.post("/auth/sign-in/", {"username": account.email, "password": "test-only-input"})
    assert "5065" in response.url and "_auth_user_id" not in browser.session


def test_username_login_keeps_csrf_and_throttle(account):
    browser = Client(enforce_csrf_checks=True, HTTP_USER_AGENT="Username regression")
    payload = {"username": account.username, "password": "test-only-input"}
    browser.post("/auth/sign-in/", payload)
    assert "_auth_user_id" not in browser.session
    token = browser.get("/auth/get-csrf-token/").json()["csrf_token"]
    payload["csrfmiddlewaretoken"] = token
    assert "error_code" not in browser.post("/auth/sign-in/", payload).url
    browser = client()
    for _ in range(10):
        response = browser.post("/auth/sign-in/", {"username": "unknown-user", "password": "wrong"})
    assert "5900" in response.url
