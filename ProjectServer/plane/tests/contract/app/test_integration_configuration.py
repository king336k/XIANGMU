"""Connection credentials are instance-admin-only, encrypted, redacted and inherited by existing bridges."""

import pytest
from django.utils import timezone
from uuid import uuid4
from plane.db.models import Project, ProjectMember
from plane.license.models import Instance, InstanceAdmin, InstanceConfiguration
from plane.quality import platform

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def configuration(workspace, create_user):
    p = Project.objects.create(workspace=workspace, name="连接配置", identifier="CONN")
    ProjectMember.objects.create(project=p, member=create_user, role=20)
    instance = Instance.objects.create(
        instance_name="配置测试", instance_id=str(uuid4()), current_version="test", last_checked_at=timezone.now()
    )
    InstanceAdmin.objects.create(instance=instance, user=create_user)
    return f"/api/workspaces/{workspace.slug}/projects/{p.id}/quality/", p


def test_config_saved_encrypted_and_runtime_reads_it_without_echo(session_client, configuration):
    base, p = configuration
    response = session_client.post(
        base + "integrations/connections/",
        {
            "source_instance": "test-source",
            "kind": "data_platform",
            "base_url": "https://platform.example",
            "timezone": "Asia/Shanghai",
            "service_token": "not-real-test-service",
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    assert "not-real-test-service" not in str(response.data)
    cfg = platform.configuration("test-source")
    assert cfg["service_token"] == "not-real-test-service" and cfg["allowed_hosts"] == ["platform.example"]
    row = InstanceConfiguration.objects.get(key="QUALITY_SOURCE:test-source")
    assert row.is_encrypted and "not-real-test-service" not in row.value
    listed = session_client.get(base + "integrations/connections/")
    assert listed.status_code == 200 and "not-real-test-service" not in str(listed.data)


def test_non_instance_manager_cannot_save_connections(session_client, configuration, create_user):
    base, p = configuration
    InstanceAdmin.objects.filter(user=create_user).delete()
    assert (
        session_client.post(
            base + "integrations/connections/",
            {"source_instance": "bad", "kind": "data_platform", "base_url": "https://platform.example"},
            format="json",
        ).status_code
        == 403
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254",
        "http://127.0.0.1:1",
        "https://user:password@platform.example",
        "https://platform.example/path",
        "file:///etc/passwd",
    ],
)
def test_connection_rejects_metadata_loopback_credentials_and_nonorigin_urls(session_client, configuration, url):
    base, _ = configuration
    response = session_client.post(
        base + "integrations/connections/",
        {"source_instance": "bad", "kind": "data_platform", "base_url": url, "allow_private_http": True},
        format="json",
    )
    assert response.status_code == 400, response.content
