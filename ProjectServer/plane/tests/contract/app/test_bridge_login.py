"""Trusted identity exchange is browser-bound and requires instance-approved account mapping."""

import base64
import hashlib
import hmac
import json
import time
from uuid import uuid4
import pytest
from django.utils import timezone
from plane.db.models import Project, ProjectMember
from plane.license.models import Instance, InstanceAdmin
from plane.quality.models import PlatformIdentity

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def bridge_login(workspace, create_user, settings):
    project = Project.objects.create(workspace=workspace, name="可信登录", identifier="LOGIN")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    instance = Instance.objects.create(
        instance_name="登录验收", instance_id=str(uuid4()), current_version="test", last_checked_at=timezone.now()
    )
    InstanceAdmin.objects.create(instance=instance, user=create_user)
    identity = PlatformIdentity.objects.create(
        project=project, created_by=create_user, source_instance="trusted-test", external_user_id=16, user=create_user
    )
    settings.QUALITY_BRIDGE_KEYS = {
        "test-login": {
            "secret": "test-only-signing-key",
            "audience": "plane-quality",
            "source_instance": "trusted-test",
        }
    }
    return f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/", identity


def signed(path, payload):
    def enc(value):
        return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")

    body = json.dumps(payload, separators=(",", ":"))
    stamp = str(int(time.time()))
    nonce = str(uuid4())
    principal = json.dumps({"id": 16}, separators=(",", ":"))
    digest = hashlib.sha256(body.encode()).hexdigest()
    raw = "\n".join(
        [
            "ISSUE-IDENTITY-V2",
            enc("plane-quality"),
            enc("test-login"),
            stamp,
            enc(nonce),
            "POST",
            enc(path),
            digest,
            enc(principal),
        ]
    )
    signature = (
        base64.urlsafe_b64encode(hmac.new(b"test-only-signing-key", raw.encode(), hashlib.sha256).digest())
        .decode()
        .rstrip("=")
    )
    return body, {
        "HTTP_X_ISSUE_IDENTITY_VERSION": "2",
        "HTTP_X_ISSUE_KEY_ID": "test-login",
        "HTTP_X_ISSUE_AUDIENCE": "plane-quality",
        "HTTP_X_ISSUE_PRINCIPAL": principal,
        "HTTP_X_ISSUE_PRINCIPAL_TIMESTAMP": stamp,
        "HTTP_X_ISSUE_PRINCIPAL_NONCE": nonce,
        "HTTP_X_ISSUE_CONTENT_SHA256": digest,
        "HTTP_X_ISSUE_PRINCIPAL_SIGNATURE": signature,
    }


def test_signed_login_uses_same_browser_challenge_and_rechecks_revocation(api_client, bridge_login, mocker):
    base, identity = bridge_login
    authority = mocker.patch("plane.quality.platform.verify_identity")
    challenge = api_client.get(base + "sso/challenge/")
    assert challenge.status_code == 200, challenge.content
    path = base + "sso/exchange/"
    body, headers = signed(path, {"challenge": challenge.data["challenge"]})
    response = api_client.post(path, body, content_type="application/json", **headers)
    assert response.status_code == 200, response.content
    assert response.data["user_id"] == str(identity.user_id)
    assert authority.called
    native = api_client.get(base + "context/")
    assert native.status_code == 200 and native.data["user_id"] == identity.user_id
    identity.active = False
    identity.save(update_fields=["active"])
    denied = api_client.get(base + "context/")
    assert denied.status_code == 401


def test_signed_login_cannot_be_replayed_in_another_browser_or_unapproved_mapping(api_client, bridge_login, mocker):
    from rest_framework.test import APIClient

    base, identity = bridge_login
    mocker.patch("plane.quality.platform.verify_identity")
    challenge = api_client.get(base + "sso/challenge/").data["challenge"]
    path = base + "sso/exchange/"
    body, headers = signed(path, {"challenge": challenge})
    assert APIClient().post(path, body, content_type="application/json", **headers).status_code in [401, 403]
    identity.created_by = None
    identity.save(update_fields=["created_by"])
    body, headers = signed(path, {"challenge": challenge})
    assert api_client.post(path, body, content_type="application/json", **headers).status_code == 403


def test_login_challenge_rejects_foreign_origin(api_client, bridge_login):
    base, _ = bridge_login
    assert api_client.get(base + "sso/challenge/", HTTP_ORIGIN="https://foreign.invalid").status_code == 403


def test_exchange_challenge_is_single_use_even_after_valid_signed_request(api_client, bridge_login, mocker):
    base, _ = bridge_login
    mocker.patch("plane.quality.platform.verify_identity")
    challenge = api_client.get(base + "sso/challenge/").data["challenge"]
    path = base + "sso/exchange/"
    body, headers = signed(path, {"challenge": challenge})
    assert api_client.post(path, body, content_type="application/json", **headers).status_code == 200
    body, headers = signed(path, {"challenge": challenge})
    assert api_client.post(path, body, content_type="application/json", **headers).status_code in [401, 403]


def test_external_authority_outage_does_not_prevent_native_sign_out(api_client, bridge_login, mocker):
    base, _ = bridge_login
    mocker.patch("plane.quality.platform.verify_identity")
    challenge = api_client.get(base + "sso/challenge/").data["challenge"]
    path = base + "sso/exchange/"
    body, headers = signed(path, {"challenge": challenge})
    assert api_client.post(path, body, content_type="application/json", **headers).status_code == 200
    from plane.quality.platform import PlatformUnavailable

    mocker.patch("plane.quality.platform.verify_identity", side_effect=PlatformUnavailable())
    response = api_client.post("/auth/sign-out/")
    assert response.status_code in [200, 302], response.content
