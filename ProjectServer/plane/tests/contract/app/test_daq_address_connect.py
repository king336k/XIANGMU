import json
from uuid import uuid4
import pytest
from rest_framework.test import APIClient
from plane.db.models import Project, User
from plane.license.models import InstanceConfiguration
from plane.tests.contract.app.test_daq_incidents import signature

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def connected():
    response = APIClient().post("/api/quality-auth/daq-connect/", {"device_id": str(uuid4())}, format="json")
    assert response.status_code == 200, response.content
    return response


def signed(config, path, payload=None):
    import base64, hashlib, hmac, time

    body = json.dumps(payload, separators=(",", ":")) if payload is not None else ""
    method = "POST" if payload is not None else "GET"
    stamp = str(int(time.time()))
    nonce = uuid4().hex
    actor = json.dumps({"id": 7, "username": "cj002"}, separators=(",", ":"))
    enc = lambda text: base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")
    digest = hashlib.sha256(body.encode()).hexdigest() if payload is not None else "-"
    canonical = "\n".join(
        [
            "ISSUE-IDENTITY-V2",
            enc(config["audience"]),
            enc(config["key_id"]),
            stamp,
            enc(nonce),
            method,
            enc(path),
            digest,
            enc(actor),
        ]
    )
    headers = {
        "HTTP_X_ISSUE_IDENTITY_VERSION": "2",
        "HTTP_X_ISSUE_KEY_ID": config["key_id"],
        "HTTP_X_ISSUE_AUDIENCE": config["audience"],
        "HTTP_X_ISSUE_PRINCIPAL": actor,
        "HTTP_X_ISSUE_PRINCIPAL_TIMESTAMP": stamp,
        "HTTP_X_ISSUE_PRINCIPAL_NONCE": nonce,
        "HTTP_X_ISSUE_CONTENT_SHA256": digest,
        "HTTP_X_ISSUE_PRINCIPAL_SIGNATURE": base64.urlsafe_b64encode(
            hmac.new(config["secret"].encode(), canonical.encode(), hashlib.sha256).digest()
        )
        .decode()
        .rstrip("="),
    }
    return (
        APIClient().post(path, body, content_type="application/json", **headers)
        if payload is not None
        else APIClient().get(path, **headers)
    )


def test_address_connection_only_returns_report_credentials_never_a_platform_session(workspace):
    project = Project.objects.create(workspace=workspace, name="可反馈", identifier="URLDAQ")
    row = InstanceConfiguration.objects.create(
        key="QUALITY_DAQ_PROJECT_GRANTS", value=json.dumps({"projects": [str(project.id)], "revision": 1})
    )
    response = connected()
    config = response.data
    assert config["capabilities"] == {"can_report": True, "can_login": False}
    assert "session-id" not in response.cookies
    assert signed(config, "/api/quality-auth/daq-project-options/").data["count"] == 1
    assert signed(config, "/api/users/me/").status_code in {401, 403}
    row.value = json.dumps({"projects": [], "revision": 2})
    row.save()
    assert signed(config, "/api/quality-auth/daq-project-options/").data["count"] == 0
    row.value = json.dumps({"projects": [str(project.id)], "revision": 3})
    row.save()
    from django.utils import timezone

    project.archived_at = timezone.now()
    project.save()
    assert signed(config, "/api/quality-auth/daq-project-options/").data["count"] == 0


def test_connection_ticket_is_not_forgeable_and_creates_no_login_user(workspace):
    before = User.objects.filter(is_bot=False).count()
    config = connected().data
    assert User.objects.filter(is_bot=False).count() == before
    config = {**config, "key_id": config["key_id"] + "x"}
    assert signed(config, "/api/quality-auth/daq-project-options/").status_code in {401, 403}


def test_invalid_device_identifier_is_rejected_without_issuing_credentials():
    response = APIClient().post("/api/quality-auth/daq-connect/", {"device_id": "invalid"}, format="json")
    assert response.status_code == 400
