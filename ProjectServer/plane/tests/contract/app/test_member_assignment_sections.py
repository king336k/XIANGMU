"""Account creation and scope assignment are separate, atomic management operations."""

from uuid import uuid4
import pytest
from plane.db.models import User, WorkspaceMember, ProjectMember, Project
from plane.quality.models import BusinessRole
from plane.quality.permissions import capable
from .test_member_scopes import scopes as scope_fixture, rows, change, save, url  # noqa: F401


scopes = scope_fixture


pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def test_project_grant_creates_minimal_workspace_without_other_project_access(scopes):
    client, target, spaces, projects, actor = scopes
    row = rows(client, target, "project", spaces[0])[0]
    response = save(client, target, [change(row, 15, [])])
    assert response.status_code == 200, response.content
    membership = WorkspaceMember.objects.get(member=target, workspace=spaces[0])
    assert not membership.has_workspace_access and membership.business_roles == []
    assert ProjectMember.objects.filter(member=target, is_active=True).count() == 1
    assert capable(row["id"], target.id, "report")
    other = next(project for project in projects[:2] if str(project.id) != row["id"])
    assert not capable(other.id, target.id, "report")
    assert not BusinessRole.objects.filter(user=target).exists()


def test_workspace_grant_without_duties_covers_current_and_future_projects(scopes):
    client, target, spaces, projects, actor = scopes
    row = next(row for row in rows(client, target) if row["id"] == str(spaces[0].id))
    response = save(client, target, [change(row, 15, [])])
    assert response.status_code == 200, response.content
    assert WorkspaceMember.objects.get(member=target).has_workspace_access
    assert all(capable(project.id, target.id, "report") for project in projects[:2])
    future = Project.objects.create(workspace=spaces[0], name="Future", identifier="FUTURE")
    assert ProjectMember.objects.filter(project=future, member=target, is_active=True).exists()
    assert capable(future.id, target.id, "report")
    assert not capable(projects[2].id, target.id, "report")
    assert not capable(projects[0].id, target.id, "solution")


def test_account_creation_optional_project_grants_are_atomic(scopes):
    client, target, spaces, projects, actor = scopes
    payload = {
        "username": "create-with-project",
        "password": "test-only-password",
        "grant_mode": "project",
        "grants": [{"id": str(projects[0].id), "roles": ["TECHNICIAN"]}],
    }
    response = client.post("/api/quality-auth/accounts/", payload, format="json")
    assert response.status_code == 201, response.content
    user = User.objects.get(id=response.data["id"])
    assert capable(projects[0].id, user.id, "solution")
    assert not capable(projects[1].id, user.id, "report")
    payload["username"] = "create-invalid-project"
    payload["grants"].append({"id": str(uuid4()), "roles": []})
    assert client.post("/api/quality-auth/accounts/", payload, format="json").status_code == 404
    assert not User.objects.filter(username=payload["username"]).exists()


def test_account_creation_workspace_grant_has_no_project_picker_or_admin_duty(scopes):
    client, target, spaces, projects, actor = scopes
    payload = {
        "username": "create-with-workspace",
        "password": "test-only-password",
        "grant_mode": "workspace",
        "grants": [{"id": str(spaces[0].id), "roles": ["REGRESSION_TESTER"]}],
    }
    response = client.post("/api/quality-auth/accounts/", payload, format="json")
    assert response.status_code == 201, response.content
    assert all(capable(project.id, response.data["id"], "execute") for project in projects[:2])
    payload["username"] = "bad-duty"
    payload["grants"][0]["roles"] = ["REPORTER"]
    assert client.post("/api/quality-auth/accounts/", payload, format="json").status_code == 400
    assert not User.objects.filter(username="bad-duty").exists()


def test_assignment_directory_only_shows_ordinary_assigned_people_and_ranges(scopes):
    client, target, spaces, projects, actor = scopes
    User.objects.create(username="unassigned-person", email="unassigned@example.invalid")
    row = rows(client, target, "project", spaces[0])[0]
    assert save(client, target, [change(row, 15, ["TECHNICIAN"])]).status_code == 200
    response = client.get("/api/quality-auth/accounts/", {"assignment_kind": "project"})
    assert response.status_code == 200, response.content
    assert [person["id"] for person in response.data["results"]] == [str(target.id)]
    assert [scope["id"] for scope in response.data["results"][0]["scopes"]] == [row["id"]]
    workspace = client.get("/api/quality-auth/accounts/", {"assignment_kind": "workspace"})
    assert not workspace.data["results"]
    picker = client.get("/api/quality-auth/accounts/", {"exclude_administrators": "1"})
    assert str(actor.id) not in [person["id"] for person in picker.data["results"]]


def test_scope_picker_supports_global_project_search_and_assigned_filter(scopes):
    client, target, spaces, projects, actor = scopes
    response = client.get(url(target), {"kind": "project", "search": "SCOPEC"})
    assert response.status_code == 200, response.content
    assert response.data["count"] == 1
    assert response.data["results"][0]["workspace_name"] == spaces[1].name
    assert save(client, target, [change(response.data["results"][0], 15, [])]).status_code == 200
    response = client.get(url(target), {"kind": "project", "assigned_only": "1"})
    assert response.status_code == 200 and response.data["count"] == 1
    assert not client.get(url(target), {"kind": "workspace", "assigned_only": "1"}).data["results"]
    unassigned = client.get(url(target), {"kind": "project", "assignment": "unassigned"})
    assert unassigned.status_code == 200 and unassigned.data["count"] == 2
    assert all(row["access_role"] == 0 for row in unassigned.data["results"])


def test_project_only_account_cannot_self_join_an_unassigned_public_project(scopes):
    client, target, spaces, projects, actor = scopes
    a = next(row for row in rows(client, target, "project", spaces[0]) if row["id"] == str(projects[0].id))
    assert save(client, target, [change(a, 15, [])]).status_code == 200
    public = Project.objects.create(workspace=spaces[0], name="Unassigned public", identifier="PUBJOIN", network=2)
    assert not capable(public.id, target.id, "report")
    client.force_login(target)
    response = client.post(
        f"/api/users/me/workspaces/{spaces[0].slug}/projects/invitations/",
        {"project_ids": [str(public.id)]},
        format="json",
    )
    assert response.status_code == 403, (response.status_code, response.data, capable(public.id, target.id, "report"))
    assert not ProjectMember.objects.filter(project=public, member=target).exists()


def test_generic_native_membership_patch_cannot_write_global_scope_flag(scopes):
    client, target, spaces, projects, actor = scopes
    row = rows(client, target, "project", spaces[0])[0]
    assert save(client, target, [change(row, 15, [])]).status_code == 200
    membership = WorkspaceMember.objects.get(workspace=spaces[0], member=target)
    response = client.patch(
        f"/api/workspaces/{spaces[0].slug}/members/{membership.id}/", {"has_workspace_access": True}, format="json"
    )
    membership.refresh_from_db()
    assert not membership.has_workspace_access, response.data


@pytest.mark.parametrize("with_lead", [False, True])
def test_workspace_inheritance_keeps_new_project_creator_and_lead_admin(scopes, mocker, with_lead):
    client, target, spaces, projects, actor = scopes
    WorkspaceMember.objects.filter(member=actor, workspace=spaces[0]).update(has_workspace_access=True)
    row = next(row for row in rows(client, target) if row["id"] == str(spaces[0].id))
    assert save(client, target, [change(row, 15, [])]).status_code == 200
    mocker.patch("plane.app.views.project.base.model_activity.delay")
    response = client.post(
        f"/api/workspaces/{spaces[0].slug}/projects/",
        {
            "name": "New admin project",
            "identifier": "ADMNEW",
            **({"project_lead": str(target.id)} if with_lead else {}),
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    created = Project.objects.get(id=response.data["id"])
    assert ProjectMember.objects.get(project=created, member=actor).role == 20
    assert ProjectMember.objects.filter(project=created, member=actor).count() == 1
    assert ProjectMember.objects.get(project=created, member=target).role == (20 if with_lead else 15)
    assert capable(created.id, target.id, "report")
