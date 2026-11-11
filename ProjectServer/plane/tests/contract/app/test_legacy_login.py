"""Legacy passwords are verified upstream and never imported into native accounts."""

from uuid import uuid4
import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from plane.db.models import Project, ProjectMember
from plane.license.models import Instance, InstanceAdmin
from plane.quality.models import PlatformIdentity, PlatformProject

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def legacy(workspace, create_user, mocker):
    from django.core.cache import cache
    from plane.quality.legacy_login import LoginThrottle

    key = LoginThrottle.cache_format % {"scope": LoginThrottle.scope, "ident": "127.0.0.1"}
    cache.delete(key)
    project = Project.objects.create(workspace=workspace, name="原账号登录", identifier="LEG")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    instance = Instance.objects.create(
        instance_name="原账号验收", instance_id=str(uuid4()), current_version="test", last_checked_at=timezone.now()
    )
    InstanceAdmin.objects.create(instance=instance, user=create_user)
    identity = PlatformIdentity.objects.create(
        project=project, created_by=create_user, source_instance="old-hub", external_user_id=16, user=create_user
    )
    PlatformProject.objects.create(project=project, source_instance="old-hub", external_project_id=3)
    mocker.patch(
        "plane.quality.legacy_login.read_connection",
        return_value={
            "kind": "legacy_hub",
            "login_enabled": True,
            "base_url": "https://legacy.example",
            "allowed_hosts": ["legacy.example"],
            "service_token": "test-directory-only",
        },
    )
    mocker.patch(
        "plane.quality.legacy_login.upstream_login",
        return_value={"id": 16, "active": True, "username": "original-name"},
    )
    mocker.patch(
        "plane.quality.platform.configuration",
        return_value={
            "kind": "legacy_hub",
            "login_enabled": True,
            "base_url": "https://legacy.example",
            "allowed_hosts": ["legacy.example"],
            "service_token": "test-directory-only",
        },
    )
    mocker.patch(
        "plane.quality.platform.fetch",
        return_value={
            "items": [
                {
                    "id": 16,
                    "active": True,
                    "projectMemberships": [{"projectId": 3, "active": True, "roles": ["PROJECT_ADMIN"]}],
                }
            ],
            "total": 1,
            "page": 1,
            "size": 100,
        },
    )
    yield project, identity
    cache.delete(key)


def test_legacy_login_requires_csrf_then_uses_native_cookie_without_storing_password(legacy, mocker):
    project, identity = legacy
    client = APIClient(enforce_csrf_checks=True)
    payload = {
        "source_instance": "old-hub",
        "username": "original-name",
        "password": "test-only-input",
        "project_id": str(project.id),
    }
    endpoint = "/api/quality-auth/legacy-login/"
    assert client.post(endpoint, payload, format="json").status_code == 403
    token = client.get("/auth/get-csrf-token/").data["csrf_token"]
    before = identity.user.password
    response = client.post(endpoint, payload, format="json", HTTP_X_CSRFTOKEN=token)
    assert response.status_code == 200, response.content
    assert response.data["next"].startswith(f"/{project.workspace.slug}/projects/{project.id}/")
    assert "test-only-input" not in str(dict(client.session)) and "test-only-input" not in str(response.data)
    identity.user.refresh_from_db()
    assert identity.user.password == before
    assert str(identity.id) == client.session["quality_bridge_identity"]
    assert (
        client.get(f"/api/workspaces/{project.workspace.slug}/projects/{project.id}/quality/context/").status_code
        == 200
    )
    identity.active = False
    identity.save()
    assert (
        client.get(f"/api/workspaces/{project.workspace.slug}/projects/{project.id}/quality/context/").status_code
        == 401
    )


def test_same_username_never_creates_or_grants_a_native_identity(legacy, mocker):
    project, identity = legacy
    identity.delete()
    client = APIClient()
    response = client.post(
        "/api/quality-auth/legacy-login/",
        {
            "source_instance": "old-hub",
            "username": "original-name",
            "password": "test-only-input",
            "project_id": str(project.id),
        },
        format="json",
    )
    assert response.status_code in [401, 403], response.content
    assert not PlatformIdentity.objects.filter(project=project).exists()


def test_legacy_login_rejects_foreign_origin_and_unapproved_mapping(legacy):
    project, identity = legacy
    client = APIClient()
    payload = {
        "source_instance": "old-hub",
        "username": "original-name",
        "password": "test-only-input",
        "project_id": str(project.id),
    }
    assert (
        client.post(
            "/api/quality-auth/legacy-login/", payload, format="json", HTTP_ORIGIN="https://foreign.invalid"
        ).status_code
        == 403
    )
    identity.created_by = None
    identity.save()
    assert client.post("/api/quality-auth/legacy-login/", payload, format="json").status_code in [401, 403]


def test_legacy_authority_checks_exact_external_id_and_membership(legacy, mocker):
    from plane.quality.legacy_login import verify_legacy_identity
    from rest_framework.exceptions import AuthenticationFailed

    project, identity = legacy
    mocker.patch(
        "plane.quality.platform.fetch",
        return_value={
            "items": [
                {
                    "id": 16,
                    "active": True,
                    "projectMemberships": [{"projectId": 3, "active": True, "roles": ["PROJECT_ADMIN"]}],
                }
            ],
            "total": 1,
            "page": 1,
            "size": 100,
        },
    )
    verify_legacy_identity(identity)
    mocker.patch(
        "plane.quality.platform.fetch",
        return_value={
            "items": [{"id": 999, "username": "original-name", "active": True}],
            "total": 1,
            "page": 1,
            "size": 100,
        },
    )
    with pytest.raises(AuthenticationFailed):
        verify_legacy_identity(identity)


def test_disabling_original_login_revokes_existing_native_session(legacy, mocker):
    project, identity = legacy
    client = APIClient()
    response = client.post(
        "/api/quality-auth/legacy-login/",
        {
            "source_instance": "old-hub",
            "username": "original-name",
            "password": "test-only-input",
            "project_id": str(project.id),
        },
        format="json",
    )
    assert response.status_code == 200, response.content
    mocker.patch("plane.quality.platform.configuration", return_value={"kind": "legacy_hub", "login_enabled": False})
    assert (
        client.get(f"/api/workspaces/{project.workspace.slug}/projects/{project.id}/quality/context/").status_code
        == 401
    )


def test_original_directory_uses_100_row_server_limit_and_reads_second_page(legacy, mocker):
    from plane.quality.legacy_login import verify_legacy_identity

    project, identity = legacy
    records = [{"id": number, "active": True, "projectMemberships": []} for number in range(1000, 1100)]
    fetch = mocker.patch(
        "plane.quality.platform.fetch",
        side_effect=[
            {"items": records, "total": 150, "page": 1, "size": 100},
            {
                "items": [
                    {
                        "id": 16,
                        "active": True,
                        "projectMemberships": [{"projectId": 3, "active": True, "roles": ["PROJECT_ADMIN"]}],
                    }
                ],
                "total": 150,
                "page": 2,
                "size": 100,
            },
        ],
    )
    verify_legacy_identity(identity)
    assert fetch.call_count == 2 and fetch.call_args.args[2] == {"page": 2, "size": 100}


def test_auth_request_body_never_enters_api_key_logging(legacy, mocker):
    project, identity = legacy
    logs = mocker.patch("plane.middleware.logger.process_logs.delay")
    response = APIClient().post(
        "/api/quality-auth/legacy-login/",
        {
            "source_instance": "old-hub",
            "username": "original-name",
            "password": "sensitive-test-input",
            "project_id": str(project.id),
        },
        format="json",
        HTTP_X_API_KEY="untrusted-header-only",
    )
    assert response.status_code == 200, response.content
    assert "sensitive-test-input" not in str(logs.call_args_list)


@pytest.mark.parametrize("oversize", [False, True])
def test_upstream_gzip_is_decoded_and_bounded_without_token_or_password_storage(oversize):
    import gzip
    import json
    import socket
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from plane.quality.legacy_login import upstream_login
    from plane.quality.platform import PlatformUnavailable

    class Authority(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            payload = {"code": 1, "data": {"token": "phs_synthetic_test_only", "user": {"id": 16, "active": True}}}
            if oversize:
                payload["padding"] = "a" * 70000
            raw = gzip.compress(json.dumps(payload).encode())
            self.send_response(200)
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("0.0.0.0", 0), Authority)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        config = {
            "base_url": f"http://{socket.gethostbyname(socket.gethostname())}:{server.server_port}",
            "allow_http_local": True,
        }
        if oversize:
            with pytest.raises(PlatformUnavailable):
                upstream_login(config, "original-name", "test-only-input")
        else:
            result = upstream_login(config, "original-name", "test-only-input")
            assert result == {"id": 16, "active": True}
    finally:
        server.shutdown()
        server.server_close()


def test_authentication_throttle_still_rejects_excessive_original_login_attempts(legacy):
    project, identity = legacy
    client = APIClient()
    payload = {
        "source_instance": "old-hub",
        "username": "original-name",
        "password": "test-only-input",
        "project_id": str(project.id),
    }
    results = [client.post("/api/quality-auth/legacy-login/", payload, format="json").status_code for _ in range(11)]
    assert results[:10] == [200] * 10 and results[10] == 429


def test_signed_directory_can_verify_existing_login_identity_without_bearer(legacy, mocker):
    from plane.quality.legacy_login import verify_legacy_identity

    _, identity = legacy
    mocker.patch(
        "plane.quality.platform.configuration",
        return_value={"kind": "legacy_hub", "login_enabled": True, "directory_auth": "trusted_v2"},
    )
    assert verify_legacy_identity(identity).external_project_id == 3
