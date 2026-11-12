"""OTA is directory configuration only; no remote install, discovery or filesystem reads."""

import pytest
from uuid import uuid4
from django.utils import timezone
from plane.db.models import Project, ProjectMember
from plane.license.models import Instance, InstanceAdmin, InstanceConfiguration
from plane.quality.connection_settings import read_connection

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture(autouse=True)
def enabled_directory_configuration(settings):
    settings.QUALITY_OTA_DIRECTORY_CONFIGURATION_ENABLED = True


@pytest.fixture
def ota_config(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="安装目录设置", identifier="OTADIR")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    instance = Instance.objects.create(
        instance_name="配置测试", instance_id=str(uuid4()), current_version="test", last_checked_at=timezone.now()
    )
    InstanceAdmin.objects.create(instance=instance, user=create_user)
    return f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/integrations/connections/", project


def payload(**changes):
    return {
        "source_instance": "ota-config",
        "kind": "ota",
        "base_url": "https://ota.example",
        "portal_url": "https://ota.example/settings",
        "roots": ["/home/operator/OTA", "/srv/升级包"],
        "expected_revision": 0,
        **changes,
    }


def test_ota_directory_roundtrip_is_encrypted_and_does_not_contact_external_or_read_disk(
    session_client, ota_config, monkeypatch
):
    url, _ = ota_config
    monkeypatch.setattr("requests.request", lambda *a, **k: pytest.fail("must not send external requests"))
    response = session_client.post(url, payload(service_token="not-real-service-test"), format="json")
    assert response.status_code == 201, response.content
    assert response.data["roots"] == payload()["roots"] and response.data["revision"] == 1
    config = read_connection("ota-config")
    assert config["roots"] == payload()["roots"] and config["service_token"] == "not-real-service-test"
    row = InstanceConfiguration.objects.get(key="QUALITY_SOURCE:ota-config")
    assert row.is_encrypted and "/home/operator/OTA" not in row.value
    listed = session_client.get(url).data["results"][0]
    assert listed["roots"] == payload()["roots"] and listed["revision"] == 1
    assert "not-real-service-test" not in str(listed)
    assert listed["portal_url"] == payload()["portal_url"]


@pytest.mark.parametrize(
    "roots",
    [
        [],
        ["relative/OTA"],
        ["/srv/../etc"],
        ["/"],
        ["//server/OTA"],
        ["/srv/./OTA"],
        ["/srv/OTA\nother"],
        ["/srv/OTA\n"],
        ["/srv/OTA", "/srv/OTA/"],
        ["/srv/a"] * 21,
        [1],
        "not-an-array",
    ],
)
def test_ota_invalid_roots_are_rejected_without_saving(session_client, ota_config, roots):
    url, _ = ota_config
    response = session_client.post(url, payload(roots=roots), format="json")
    assert response.status_code == 400, response.content
    assert not InstanceConfiguration.objects.filter(key="QUALITY_SOURCE:ota-config").exists()


def test_ota_stale_revision_conflicts_and_blank_secret_preserves_original(session_client, ota_config):
    url, _ = ota_config
    assert session_client.post(url, payload(service_token="not-real-service-test"), format="json").status_code == 201
    changed = session_client.post(
        url, payload(roots=["/srv/new"], expected_revision=1, service_token=""), format="json"
    )
    assert changed.status_code == 201 and changed.data["revision"] == 2
    stale = session_client.post(url, payload(expected_revision=1), format="json")
    assert stale.status_code == 409
    assert read_connection("ota-config")["roots"] == ["/srv/new"]
    assert read_connection("ota-config")["service_token"] == "not-real-service-test"


def test_ota_unauthorized_user_cannot_read_or_modify_global_directories(session_client, ota_config, create_user):
    url, project = ota_config
    InstanceAdmin.objects.filter(user=create_user).delete()
    assert session_client.post(url, payload(), format="json").status_code == 403
    assert session_client.get(url).data["results"] == []
    ProjectMember.objects.filter(project=project, member=create_user).delete()
    assert session_client.get(url).status_code == 403


def test_retired_data_platform_connection_is_rejected(session_client, ota_config):
    url, _ = ota_config
    response = session_client.post(
        url, {"source_instance": "data", "kind": "data_platform", "base_url": "https://platform.example"}, format="json"
    )
    assert response.status_code == 400
    assert not read_connection("data")
