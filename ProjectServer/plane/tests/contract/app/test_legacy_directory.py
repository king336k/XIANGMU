"""The real old hub uses V2-signed directory reads, with no password or role import."""

import base64
import hashlib
import hmac
import json
from uuid import uuid4
import pytest
from django.test import override_settings
from django.utils import timezone
from plane.db.models import Project, ProjectMember
from plane.license.models import Instance, InstanceAdmin
from plane.quality import platform
from plane.quality.connection_settings import ConnectionInput

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def signed_config():
    return {
        "kind": "legacy_hub",
        "base_url": "https://legacy.example",
        "allowed_hosts": ["legacy.example"],
        "directory_auth": "trusted_v2",
        "directory_key_id": "test-key",
        "directory_user_id": 6,
        "directory_username": "hub.admin",
        "login_enabled": True,
    }


def test_directory_fetch_uses_signed_exact_get_without_bearer(mocker):
    mocker.patch("plane.quality.platform.configuration", return_value=signed_config())
    response = mocker.MagicMock()
    response.status_code = 200
    response.iter_content.return_value = [b'{"code":1,"data":{"items":[]}}']
    get = mocker.patch("plane.quality.platform.requests.get")
    get.return_value.__enter__.return_value = response
    with override_settings(
        QUALITY_BRIDGE_KEYS={
            "test-key": {
                "secret": "test-only-signing-secret",
                "audience": "old-hub",
                "directory_origins": ["https://legacy.example"],
                "directory_user_id": 6,
            }
        }
    ):
        assert platform.fetch("old", "/api/admin/users", {"page": 1, "size": 100}) == {"items": []}
    headers = get.call_args.kwargs["headers"]
    assert "Authorization" not in headers

    def encode(value):
        return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")

    canonical = "\n".join(
        [
            "ISSUE-IDENTITY-V2",
            encode("old-hub"),
            encode("test-key"),
            headers["X-Issue-Principal-Timestamp"],
            encode(headers["X-Issue-Principal-Nonce"]),
            "GET",
            encode("/api/admin/users?page=1&size=100"),
            "-",
            encode(headers["X-Issue-Principal"]),
        ]
    )
    expected = (
        base64.urlsafe_b64encode(hmac.new(b"test-only-signing-secret", canonical.encode(), hashlib.sha256).digest())
        .decode()
        .rstrip("=")
    )
    assert headers["X-Issue-Principal-Signature"] == expected
    assert json.loads(headers["X-Issue-Principal"])["id"] == 6
    assert "test-only-signing-secret" not in str(headers)


@pytest.mark.parametrize("path", ["/api/admin/users/1", "/api/auth/login", "/api/other", "/api/admin/users?x=y"])
def test_directory_signature_is_not_available_for_other_endpoints(mocker, path):
    mocker.patch("plane.quality.platform.configuration", return_value=signed_config())
    get = mocker.patch("plane.quality.platform.requests.get")
    with override_settings(QUALITY_BRIDGE_KEYS={"test-key": {"secret": "test-only", "audience": "old"}}):
        with pytest.raises(platform.PlatformUnavailable):
            platform.fetch("old", path)
    get.assert_not_called()


def test_signing_connection_fields_are_validated():
    payload = {"source_instance": "old", "base_url": "https://legacy.example", **signed_config()}
    parsed = ConnectionInput(data=payload)
    assert parsed.is_valid(), parsed.errors
    assert parsed.validated_data["directory_auth"] == "trusted_v2"
    for changes in [
        {"kind": "data_platform"},
        {"directory_user_id": 0},
        {"directory_key_id": ""},
        {"directory_username": ""},
    ]:
        invalid = ConnectionInput(data={**payload, **changes})
        assert not invalid.is_valid(), changes


@pytest.fixture
def directory(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="旧账号目录预检", identifier="DIRECT")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    instance = Instance.objects.create(
        instance_name="目录检查", instance_id=str(uuid4()), current_version="test", last_checked_at=timezone.now()
    )
    InstanceAdmin.objects.create(instance=instance, user=create_user)
    return f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/", project


def test_directory_preview_reports_roles_without_creating_accounts(session_client, directory, mocker):
    from plane.db.models import User
    from plane.quality.models import PlatformIdentity, BusinessRole

    base, _ = directory
    mocker.patch("plane.quality.platform.configuration", return_value=signed_config())
    mocker.patch(
        "plane.quality.platform.fetch",
        return_value={
            "items": [
                {
                    "id": 11,
                    "username": "caiji1",
                    "active": True,
                    "primaryRole": "REPORTER",
                    "platformAdmin": False,
                    "projectMemberships": [{"projectId": 3, "active": True, "roles": ["REPORTER"]}],
                },
                {
                    "id": 12,
                    "username": "disabled",
                    "active": False,
                    "primaryRole": "TECHNICIAN",
                    "platformAdmin": False,
                    "projectMemberships": [],
                },
            ],
            "total": 2,
            "page": 1,
            "size": 100,
        },
    )
    before = (User.objects.count(), PlatformIdentity.objects.count(), BusinessRole.objects.count())
    response = session_client.get(base + "integrations/legacy-directory/?source_instance=old")
    assert response.status_code == 200, response.content
    assert response.data["total"] == 2
    assert response.data["results"][0]["external_user_id"] == 11
    assert response.data["results"][0]["mapping_status"] == "unmapped"
    assert response.data["results"][1]["mapping_status"] == "disabled"
    assert before == (User.objects.count(), PlatformIdentity.objects.count(), BusinessRole.objects.count())


def test_directory_preview_is_instance_admin_only(session_client, directory, create_user, mocker):
    base, _ = directory
    InstanceAdmin.objects.filter(user=create_user).delete()
    fetch = mocker.patch("plane.quality.platform.fetch")
    assert session_client.get(base + "integrations/legacy-directory/?source_instance=old").status_code == 403
    fetch.assert_not_called()


@pytest.mark.parametrize(
    "changes",
    [
        {"directory_origins": ["https://different.example"], "directory_user_id": 6},
        {"directory_origins": ["https://legacy.example"], "directory_user_id": 7},
        {"directory_origins": "https://legacy.example", "directory_user_id": 6},
    ],
)
def test_server_must_authorize_both_origin_and_service_identity(mocker, changes):
    mocker.patch("plane.quality.platform.configuration", return_value=signed_config())
    get = mocker.patch("plane.quality.platform.requests.get")
    with override_settings(
        QUALITY_BRIDGE_KEYS={"test-key": {"secret": "test-key-not-real", "audience": "old", **changes}}
    ):
        with pytest.raises(platform.PlatformUnavailable):
            platform.fetch("old", "/api/admin/users", {"page": 1, "size": 100})
    get.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        {"items": [], "total": 2, "page": 1, "size": 100},
        {
            "items": [
                {
                    "id": 1,
                    "username": "bad",
                    "active": True,
                    "primaryRole": {},
                    "platformAdmin": False,
                    "projectMemberships": [],
                }
            ],
            "total": 1,
            "page": 1,
            "size": 100,
        },
        {
            "items": [
                {
                    "id": 1,
                    "username": "bad",
                    "active": True,
                    "primaryRole": "REPORTER",
                    "platformAdmin": False,
                    "projectMemberships": [{"projectId": 3, "active": True, "roles": [{}]}],
                }
            ],
            "total": 1,
            "page": 1,
            "size": 100,
        },
    ],
)
def test_incomplete_or_malformed_directory_fails_closed(session_client, directory, mocker, payload):
    base, _ = directory
    mocker.patch("plane.quality.platform.configuration", return_value=signed_config())
    mocker.patch("plane.quality.platform.fetch", return_value=payload)
    response = session_client.get(base + "integrations/legacy-directory/?source_instance=old")
    assert response.status_code == 503
