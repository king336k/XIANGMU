"""Signing out on an allowed application alias must not switch browser sessions."""

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.mark.parametrize("authenticated", [True, False])
def test_same_origin_logout_keeps_current_alias(api_client, create_user, settings, authenticated):
    settings.ALLOWED_HOSTS = ["127.0.0.1", "testserver"]
    settings.WEB_URL = "http://localhost:18880"
    settings.APP_BASE_URL = "http://localhost:18880"
    if authenticated:
        api_client.force_login(create_user)
    response = api_client.post("/auth/sign-out/", HTTP_HOST="127.0.0.1:18880", HTTP_ORIGIN="http://127.0.0.1:18880")
    assert response.status_code == 302
    assert response["Location"] == "/"
    assert "_auth_user_id" not in api_client.session


def test_separate_api_host_logout_preserves_configured_application_destination(api_client, create_user, settings):
    settings.ALLOWED_HOSTS = ["api.example.test"]
    settings.APP_BASE_URL = "https://app.example.test"
    api_client.force_login(create_user)
    response = api_client.post(
        "/auth/sign-out/", HTTP_HOST="api.example.test", HTTP_ORIGIN="https://app.example.test", secure=True
    )
    assert response.status_code == 302 and response["Location"] == "https://app.example.test"
