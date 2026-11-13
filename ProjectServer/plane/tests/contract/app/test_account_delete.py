"""Deleting a managed account revokes access while preserving authored audit records."""

import pytest
from plane.db.models import ProjectMember, WorkspaceMember
from plane.quality.models import Defect, ModuleCatalog, ModuleOwner
from plane.tests.contract.app.test_module_owners import routing as routing_fixture

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture(name="routing")
def account_context(session_client, workspace, create_user):
    return routing_fixture.__wrapped__(session_client, workspace, create_user)


def test_administrator_deletes_account_from_directory_without_removing_authored_history(routing):
    client, workspace, project, administrator, users = routing
    target = users[0]
    closed = Defect.objects.create(
        project=project, created_by=target, assignee=target, title="保留历史", status="closed"
    )
    response = client.delete("/api/quality-auth/accounts/", {"user_id": str(target.id)}, format="json")
    assert response.status_code == 200, response.content
    target.refresh_from_db()
    closed.refresh_from_db()
    assert not target.is_active and not target.has_usable_password()
    assert closed.created_by_id == closed.assignee_id == target.id
    assert not ProjectMember.objects.filter(member=target, is_active=True).exists()
    assert not WorkspaceMember.objects.filter(member=target, is_active=True).exists()
    assert str(target.id) not in {row["id"] for row in client.get("/api/quality-auth/accounts/").data["results"]}
    client.force_authenticate(target)
    assert client.get(f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/defects/").status_code in {
        401,
        403,
    }


@pytest.mark.parametrize("blocker", ["self", "open_defect", "module_owner", "not_admin"])
def test_delete_protects_current_admin_and_untransferred_responsibilities(routing, blocker):
    client, workspace, project, administrator, users = routing
    target = administrator if blocker == "self" else users[0]
    if blocker == "open_defect":
        Defect.objects.create(project=project, assignee=target, title="先移交")
    if blocker == "module_owner":
        ModuleOwner.objects.create(
            workspace=workspace,
            module=ModuleCatalog.objects.get_or_create(key="daq", defaults={"name": "DAQ"})[0],
            user=target,
            created_by=administrator,
        )
    if blocker == "not_admin":
        client.force_authenticate(users[1])
    response = client.delete("/api/quality-auth/accounts/", {"user_id": str(target.id)}, format="json")
    assert response.status_code in ({403} if blocker == "not_admin" else {400, 409}), response.content
    target.refresh_from_db()
    assert target.is_active
