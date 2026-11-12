import pytest
from uuid import uuid4
from django.utils import timezone
from rest_framework.test import APIClient
from plane.db.models import Workspace, WorkspaceMember, Project, ProjectMember, User
from plane.license.models import Instance, InstanceAdmin, InstanceConfiguration
from plane.quality.models import ProjectRolePolicy
from plane.quality.permissions import roles_for, capable
from plane.knowledge.assistant import provider_config

from plane.tests.contract.app import test_member_scopes

scopes = test_member_scopes.scopes

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def test_workspace_model_shared_with_projects_but_isolated_from_other_workspace(workspace, create_user):
    instance = Instance.objects.create(
        instance_name="scope", instance_id=str(uuid4()), current_version="test", last_checked_at=timezone.now()
    )
    InstanceAdmin.objects.create(instance=instance, user=create_user)
    other = Workspace.objects.create(name="其他区", slug="other-model", owner=create_user)
    WorkspaceMember.objects.create(workspace=other, member=create_user, role=20)
    project = Project.objects.create(workspace=workspace, name="A", identifier="A")
    another = Project.objects.create(workspace=workspace, name="B", identifier="B")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    ProjectMember.objects.create(project=another, member=create_user, role=20)
    client = APIClient()
    client.force_authenticate(create_user)
    path = f"/api/workspaces/{workspace.slug}/model-configuration/"
    response = client.patch(
        path,
        {"model": "workspace-model-a", "base_url": "https://api.openai.com/v1", "api_key": "synthetic-workspace-key"},
        format="json",
    )
    assert response.status_code == 200, response.content
    assert response.data["workspace_id"] == str(workspace.id)
    assert "synthetic-workspace-key" not in str(response.data)
    assert provider_config(workspace.id)["model"] == "workspace-model-a"
    assert provider_config(other.id)["model"] != "workspace-model-a"
    for row in [project, another]:
        r = client.get(f"/api/workspaces/{workspace.slug}/projects/{row.id}/knowledge/configuration/")
        assert r.status_code == 200 and r.data["model"] == "workspace-model-a"
    saved = InstanceConfiguration.objects.get(key=f"WS:{workspace.id}:KNOWLEDGE_API_KEY")
    assert saved.is_encrypted and saved.value != "synthetic-workspace-key"


def test_workspace_duties_apply_to_existing_and_future_projects_and_revoke(workspace, create_user):
    instance = Instance.objects.create(
        instance_name="scope", instance_id=str(uuid4()), current_version="test", last_checked_at=timezone.now()
    )
    InstanceAdmin.objects.create(instance=instance, user=create_user)
    target = User.objects.create(username="workspace-tester", email="tester@invalid.example")
    first = Project.objects.create(workspace=workspace, name="A", identifier="A")
    ProjectRolePolicy.objects.create(project=first, enabled=True)
    client = APIClient()
    client.force_authenticate(create_user)
    path = f"/api/quality-auth/member-scopes/{target.id}/"
    scope = next(r for r in client.get(path).data["results"] if r["id"] == str(workspace.id))
    r = client.post(
        path,
        {
            "changes": [
                {
                    "kind": "workspace",
                    "id": str(workspace.id),
                    "access_role": 15,
                    "roles": ["REGRESSION_TESTER"],
                    "expected_revision": scope["revision"],
                }
            ]
        },
        format="json",
    )
    assert r.status_code == 200, r.content
    assert roles_for(first.id, target.id) == {"REGRESSION_TESTER"}
    assert capable(first.id, target.id, "execute")
    later = Project.objects.create(workspace=workspace, name="B", identifier="B")
    ProjectRolePolicy.objects.create(project=later, enabled=True)
    assert ProjectMember.objects.filter(project=later, member=target, is_active=True).exists()
    assert roles_for(later.id, target.id) == {"REGRESSION_TESTER"}
    scope = next(r for r in client.get(path).data["results"] if r["id"] == str(workspace.id))
    r = client.post(
        path,
        {
            "changes": [
                {
                    "kind": "workspace",
                    "id": str(workspace.id),
                    "access_role": 15,
                    "roles": [],
                    "expected_revision": scope["revision"],
                }
            ]
        },
        format="json",
    )
    assert r.status_code == 200, r.content
    assert not capable(first.id, target.id, "execute")
    assert not capable(later.id, target.id, "execute")


def test_workspace_grant_preserves_existing_project_admin(scopes):
    from plane.tests.contract.app.test_member_scopes import rows, save, change

    client, target, spaces, projects, actor = scopes
    WorkspaceMember.objects.create(workspace=spaces[0], member=target, role=15)
    ProjectMember.objects.create(project=projects[0], member=target, role=20)
    scope = next(row for row in rows(client, target) if row["id"] == str(spaces[0].id))
    response = save(client, target, [change(scope, 15, ["TECHNICIAN"])])
    assert response.status_code == 200, response.content
    assert ProjectMember.objects.get(project=projects[0], member=target).role == 20


def test_global_admin_can_remove_workspace_duty_without_losing_management(scopes):
    from plane.tests.contract.app.test_member_scopes import rows, save, change

    client, target, spaces, projects, actor = scopes
    scope = next(row for row in rows(client, target) if row["id"] == str(spaces[0].id))
    assert save(client, target, [change(scope, 15, ["PROJECT_MANAGER"])]).status_code == 200
    ProjectMember.objects.filter(project=projects[0], member=actor).update(is_active=False)
    scope = next(row for row in rows(client, target) if row["id"] == str(spaces[0].id))
    response = save(client, target, [change(scope, 15, [])])
    assert response.status_code == 200, response.content
    assert not capable(projects[0].id, target.id, "review")
    assert capable(projects[0].id, actor.id, "review")


def test_project_scope_displays_inherited_roles_and_accepts_no_override(scopes):
    from plane.tests.contract.app.test_member_scopes import rows, save, change

    client, target, spaces, projects, actor = scopes
    scope = next(row for row in rows(client, target) if row["id"] == str(spaces[0].id))
    assert save(client, target, [change(scope, 15, ["REGRESSION_TESTER"])]).status_code == 200
    row = next(row for row in rows(client, target, "project", spaces[0]) if row["id"] == str(projects[0].id))
    assert row["inherited_roles"] == ["REGRESSION_TESTER"]
    response = save(client, target, [change(row, 15, [])])
    assert response.status_code == 200, response.content
    assert capable(projects[0].id, target.id, "execute")


def test_global_admin_can_change_model_despite_old_readonly_membership(workspace, create_user):
    instance = Instance.objects.create(
        instance_name="readonly", instance_id=str(uuid4()), current_version="test", last_checked_at=timezone.now()
    )
    InstanceAdmin.objects.create(instance=instance, user=create_user)
    WorkspaceMember.objects.filter(workspace=workspace, member=create_user).update(role=5)
    client = APIClient()
    client.force_authenticate(create_user)
    response = client.patch(
        f"/api/workspaces/{workspace.slug}/model-configuration/", {"model": "must-not-save"}, format="json"
    )
    assert response.status_code == 200
