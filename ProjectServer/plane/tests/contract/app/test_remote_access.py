"""Shared device policy stays usable independently of the HTTP view module."""

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.contrib.auth.models import AnonymousUser
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APIRequestFactory

from plane.db.models import ProjectMember, User, WorkspaceMember
from plane.quality.models import BusinessRole
from plane.quality.remote_models import RemoteWorkstation

pytest_plugins = ["plane.tests.contract.app.test_remote_diagnostics"]
pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def test_policy_loads_without_remote_http_views():
    # A fresh interpreter catches an accidental dependency on the view module,
    # even when Django URL loading already imported it in this test process.
    import os
    import subprocess
    import sys

    check = subprocess.run(
        [sys.executable, "-c", """
import django
import sys
django.setup()
sys.modules['plane.quality.remote_diagnostics'] = None
sys.modules['plane.quality.views'] = None
from plane.quality.remote_access import permitted, identity_key, browser_boundary
assert callable(permitted) and callable(identity_key) and callable(browser_boundary)
"""],
        env=os.environ.copy(), capture_output=True, text=True, timeout=30,
    )
    assert check.returncode == 0, check.stderr


@pytest.mark.parametrize("revocation", [
    "station", "agent", "user", "project_member", "workspace_member", "project_archive",
])
def test_administrator_device_access_requires_current_membership(remote, revocation):
    from plane.quality.remote_access import permitted, station_for

    _, _, device, project = remote
    station = RemoteWorkstation.objects.select_related("agent__project__workspace", "agent__owner").get(pk=device)
    owner = station.agent.owner
    assert permitted(owner, station)
    if revocation == "station":
        station.enabled = False
        station.save(update_fields=["enabled"])
    elif revocation == "agent":
        station.agent.enabled = False
        station.agent.save(update_fields=["enabled"])
    elif revocation == "user":
        owner.is_active = False
        owner.save(update_fields=["is_active"])
    elif revocation == "project_member":
        ProjectMember.objects.filter(project=project, member=owner).update(is_active=False)
    elif revocation == "workspace_member":
        WorkspaceMember.objects.filter(workspace=project.workspace, member=owner).update(is_active=False)
    else:
        project.archived_at = timezone.now()
        project.save(update_fields=["archived_at"])
    assert not permitted(owner, station)
    with pytest.raises(PermissionDenied):
        station_for(owner, device)


def test_only_device_owner_technician_can_connect_without_administrator_role(remote):
    from plane.quality.remote_access import permitted

    _, _, device, project = remote
    station = RemoteWorkstation.objects.select_related("agent__project__workspace").get(pk=device)
    technician = User.objects.create(username="device-tech", email="device-tech@invalid.test")
    WorkspaceMember.objects.create(workspace=project.workspace, member=technician, role=15)
    ProjectMember.objects.create(project=project, member=technician, role=15)
    role = BusinessRole.objects.create(project=project, user=technician, role="TECHNICIAN")
    assert not permitted(technician, station)
    station.agent.owner = technician
    station.agent.save(update_fields=["owner"])
    assert permitted(technician, station)
    role.delete()
    assert not permitted(technician, station)
    assert not permitted(AnonymousUser(), station)


@pytest.mark.parametrize("field", ["boot_id", "hostname", "username", "robot_revision"])
def test_execution_identity_changes_when_execution_target_changes(field):
    from plane.quality.remote_access import identity_key

    station = SimpleNamespace(pk="device-id", boot_id="boot1", hostname="operator", username="user",
        capabilities={"robot": {
            "connected": True, "username": "robot", "host": "10.0.0.2", "target_revision": "a" * 64,
        }})
    before = identity_key(station)
    if field == "robot_revision":
        station.capabilities["robot"]["target_revision"] = "b" * 64
    else:
        setattr(station, field, "changed")
    assert identity_key(station) != before


def test_execution_identity_ignores_metadata_but_detects_robot_disconnect():
    from plane.quality.remote_access import identity_key

    station = SimpleNamespace(pk="device-id", boot_id="boot1", hostname="operator", username="user",
        capabilities={"robot": {
            "connected": True, "username": "robot", "host": "10.0.0.2", "target_revision": "a" * 64,
        }})
    before = identity_key(station)
    station.capabilities = deepcopy(station.capabilities)
    station.capabilities.update({"network": {"ip_address": "10.0.0.99"}, "daq": {"version": "new"}})
    assert identity_key(station) == before
    station.capabilities["robot"]["connected"] = False
    assert identity_key(station) != before


@pytest.mark.parametrize("age,expected", [(None, False), (19, True), (20, False), (30, False)])
def test_online_uses_the_existing_twenty_second_boundary(age, expected):
    from plane.quality.remote_access import online

    station = SimpleNamespace(last_seen_at=None if age is None else timezone.now() - timedelta(seconds=age))
    assert online(station) is expected


@pytest.mark.parametrize("headers,exception", [
    ({}, None),
    ({"HTTP_ORIGIN": "http://testserver"}, None),
    ({"HTTP_ORIGIN": "https://elsewhere.invalid"}, PermissionDenied),
    ({"HTTP_ORIGIN": "ftp://testserver"}, PermissionDenied),
    ({"HTTP_SEC_FETCH_SITE": "cross-site"}, PermissionDenied),
    ({"HTTP_SEC_FETCH_SITE": "same-site"}, PermissionDenied),
])
def test_browser_writes_retain_json_and_same_origin_boundary(headers, exception):
    from plane.quality.remote_access import browser_boundary

    request = APIRequestFactory().post("/", {}, format="json", **headers)
    if exception:
        with pytest.raises(exception):
            browser_boundary(request)
    else:
        browser_boundary(request)
    with pytest.raises(ValidationError):
        browser_boundary(APIRequestFactory().post("/", {}, format="multipart"))
    browser_boundary(APIRequestFactory().get("/", HTTP_ORIGIN="https://elsewhere.invalid"))
