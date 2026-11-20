"""High-frequency transport keeps current authorization without repeated projections."""

from unittest.mock import patch
import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from plane.db.models import ProjectMember
from plane.quality.remote_models import RemoteTerminal
from plane.tests.contract.app.test_remote_diagnostics import BASE, heartbeat

pytest_plugins = ["plane.tests.contract.app.test_remote_diagnostics"]
pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def opened(remote):
    client, edge, device, _ = remote
    assert heartbeat(edge).status_code == 200
    response = client.post(BASE, {"action": "open", "device_id": device}, format="json")
    assert response.status_code == 201
    return response.data["id"]


def test_terminal_poll_does_not_resynchronize_unrelated_admin_memberships(remote):
    sid = opened(remote)
    client, _, _, _ = remote
    with patch(
        "plane.quality.administrator_access.synchronize_administrator_access",
        side_effect=AssertionError("not terminal authorization"),
    ):
        response = client.get(BASE + "sessions/" + sid + "/")
    assert response.status_code == 200


def test_terminal_poll_query_budget_retains_current_device_relations(remote):
    sid = opened(remote)
    client, _, _, _ = remote
    with CaptureQueriesContext(connection) as queries:
        response = client.get(BASE + "sessions/" + sid + "/")
    assert response.status_code == 200
    assert len(queries) <= 17, f"terminal poll repeated {len(queries)} queries"


def test_exchange_reuses_one_owner_permission_decision_within_request_only(remote):
    sid = opened(remote)
    _, edge, _, _ = remote
    from plane.quality.remote_diagnostics import permitted

    with patch("plane.quality.remote_exchange.permitted", wraps=permitted) as decision:
        assert heartbeat(edge).status_code == 200
    assert decision.call_count == 2  # Credential validation and locked current-device check.
    row = RemoteTerminal.objects.get(pk=sid)
    ProjectMember.objects.filter(project=row.workstation.agent.project, member=row.owner).update(is_active=False)
    assert heartbeat(edge).status_code == 401  # No authorization survives into the next request.


def test_terminal_poll_cannot_restore_revoked_project_membership(remote):
    sid = opened(remote)
    client, _, _, project = remote
    row = RemoteTerminal.objects.get(pk=sid)
    ProjectMember.objects.filter(project=project, member=row.owner).update(is_active=False)
    response = client.get(BASE + "sessions/" + sid + "/")
    assert response.status_code == 403
    row.refresh_from_db()
    assert row.status == "closed"


def test_exchange_checks_a_different_terminal_owners_current_permission(remote):
    from uuid import uuid4
    from django.utils import timezone
    from datetime import timedelta
    from plane.db.models import User, WorkspaceMember
    from plane.license.models import Instance, InstanceAdmin
    from plane.quality.remote_models import RemoteWorkstation

    _, edge, device, project = remote
    heartbeat(edge)
    other = User.objects.create(username="terminal-other-" + uuid4().hex, email=uuid4().hex + "@invalid.test")
    WorkspaceMember.objects.create(workspace=project.workspace, member=other, role=20)
    membership = ProjectMember.objects.create(project=project, member=other, role=20)
    InstanceAdmin.objects.create(instance=Instance.objects.first(), user=other)
    terminal = RemoteTerminal.objects.create(
        workstation=RemoteWorkstation.objects.get(pk=device),
        owner=other,
        expires_at=timezone.now() + timedelta(minutes=1),
        last_read_at=timezone.now(),
    )
    assert heartbeat(edge).status_code == 200
    terminal.refresh_from_db()
    assert terminal.status == "open"
    membership.is_active = False
    membership.save(update_fields=["is_active"])
    assert heartbeat(edge).status_code == 200  # Station owner remains authorized.
    terminal.refresh_from_db()
    assert terminal.status == "closed"  # Another user's decision was not borrowed.
