"""Administrator scope edits are explicit, atomic, and independent between projects."""

import sys
import types
from uuid import uuid4
from django.urls import path, include, clear_url_caches
from django.utils import timezone
import pytest
from rest_framework.test import APIClient
from plane.db.models import User, Workspace, WorkspaceMember, Project, ProjectMember
from plane.license.models import Instance, InstanceAdmin
from plane.quality.models import BusinessRole, PlatformAccount, ProjectRolePolicy
from plane.quality.permissions import capable

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def scopes(workspace, create_user, settings):
    from plane.quality.member_scopes import MemberScopes

    module = types.ModuleType("member_scope_test_urls")
    module.urlpatterns = [
        path("api/quality-auth/member-scopes/<uuid:user_id>/", MemberScopes.as_view()),
        path("", include("plane.urls")),
    ]
    sys.modules[module.__name__] = module
    settings.ROOT_URLCONF = module.__name__
    clear_url_caches()
    instance = Instance.objects.create(
        instance_name="scope", instance_id=str(uuid4()), current_version="test", last_checked_at=timezone.now()
    )
    InstanceAdmin.objects.create(instance=instance, user=create_user)
    target = User.objects.create(username="scope-target", email="scope-target@example.invalid")
    other = Workspace.objects.create(name="第二空间", slug="second-scope", owner=create_user)
    projects = [
        Project.objects.create(workspace=w, name=name, identifier=key)
        for w, name, key in [(workspace, "项目A", "SCOPEA"), (workspace, "项目B", "SCOPEB"), (other, "项目C", "SCOPEC")]
    ]
    for project in projects:
        ProjectRolePolicy.objects.create(project=project, enabled=True)
        WorkspaceMember.objects.get_or_create(workspace=project.workspace, member=create_user, defaults={"role": 15})
        ProjectMember.objects.create(project=project, member=create_user, role=15)
    client = APIClient()
    client.force_login(create_user)
    return client, target, [workspace, other], projects, create_user


def url(target):
    return f"/api/quality-auth/member-scopes/{target.id}/"


def rows(client, target, kind="workspace", workspace=None):
    query = {"kind": kind}
    if workspace:
        query["workspace_id"] = str(workspace.id)
    response = client.get(url(target), query)
    assert response.status_code == 200, response.content
    return response.data["results"]


def change(row, role, roles=None):
    result = {"kind": row["kind"], "id": row["id"], "access_role": role, "expected_revision": row["revision"]}
    if roles is not None:
        result["roles"] = roles
    return result


def save(client, target, changes):
    return client.post(url(target), {"changes": changes}, format="json")


def test_workspace_only_does_not_grant_projects(scopes):
    client, target, spaces, projects, actor = scopes
    response = save(client, target, [change(rows(client, target)[0], 15)])
    assert response.status_code == 200, response.content
    assert WorkspaceMember.objects.filter(member=target, is_active=True).count() == 1
    assert not ProjectMember.objects.filter(member=target).exists()
    assert not InstanceAdmin.objects.filter(user=target).exists()


def test_grant_multiple_spaces_and_projects_with_independent_duties(scopes):
    client, target, spaces, projects, actor = scopes
    assert save(client, target, [change(row, 15) for row in rows(client, target)]).status_code == 200
    choices = [row for w in spaces for row in rows(client, target, "project", w)]
    changes = [
        change(row, 15, ["TECHNICIAN"] if row["identifier"] == "SCOPEA" else ["PROJECT_MANAGER", "REGRESSION_TESTER"])
        for row in choices
    ]
    response = save(client, target, changes)
    assert response.status_code == 200, response.content
    a, b, c = projects
    assert capable(a.id, target.id, "solution")
    assert not capable(a.id, target.id, "review")
    assert capable(b.id, target.id, "review") and capable(b.id, target.id, "execute")
    assert capable(c.id, target.id, "review")
    arow = next(row for row in rows(client, target, "project", spaces[0]) if row["id"] == str(a.id))
    assert save(client, target, [change(arow, 15, ["REGRESSION_TESTER"])]).status_code == 200
    assert not capable(a.id, target.id, "solution") and capable(a.id, target.id, "execute")
    assert capable(b.id, target.id, "review")


def test_remove_one_project_leaves_other_scope_unchanged(scopes):
    client, target, spaces, projects, actor = scopes
    save(client, target, [change(row, 15) for row in rows(client, target)])
    choices = rows(client, target, "project", spaces[0])
    save(client, target, [change(row, 15, ["TECHNICIAN"]) for row in choices])
    arow = next(row for row in rows(client, target, "project", spaces[0]) if row["id"] == str(projects[0].id))
    response = save(client, target, [change(arow, 0)])
    assert response.status_code == 200, response.content
    assert not capable(projects[0].id, target.id, "solution")
    assert capable(projects[1].id, target.id, "solution")
    assert WorkspaceMember.objects.filter(member=target, workspace=spaces[0], is_active=True).exists()


def test_stale_revision_rolls_back_whole_batch(scopes):
    client, target, spaces, projects, actor = scopes
    stale = rows(client, target)
    save(client, target, [change(stale[0], 15)])
    response = save(client, target, [change(stale[1], 15), change(stale[0], 5)])
    assert response.status_code == 409, response.content
    assert not WorkspaceMember.objects.filter(member=target, workspace_id=stale[1]["id"]).exists()


def test_nonadmin_cannot_list_or_modify_any_scope(scopes):
    client, target, spaces, projects, actor = scopes
    InstanceAdmin.objects.filter(user=actor).delete()
    assert client.get(url(target)).status_code == 403
    assert save(client, target, []).status_code == 403


def test_project_requires_explicit_workspace_and_no_admin_duty(scopes):
    client, target, spaces, projects, actor = scopes
    row = rows(client, target, "project", spaces[0])[0]
    assert save(client, target, [change(row, 15, ["TECHNICIAN"])]).status_code == 400
    save(client, target, [change(rows(client, target)[0], 15)])
    row = rows(client, target, "project", spaces[0])[0]
    assert save(client, target, [change(row, 15, ["PLATFORM_ADMIN"])]).status_code == 400
    assert not ProjectMember.objects.filter(member=target).exists()


def test_source_account_revocation_cannot_be_overridden(scopes, mocker):
    client, target, spaces, projects, actor = scopes
    from plane.quality import platform

    upstream = mocker.patch.object(platform, "fetch", side_effect=AssertionError("no external authority"))
    PlatformAccount.objects.create(
        user=target,
        source_instance="retired",
        external_user_id=78,
        source_username="collector",
        source_role="Collector",
    )
    response = save(client, target, [change(rows(client, target)[0], 15)])
    assert response.status_code == 403, response.content
    assert not WorkspaceMember.objects.filter(member=target).exists()
    assert not ProjectMember.objects.filter(member=target).exists()
    upstream.assert_not_called()


def test_remove_workspace_does_not_revive_projects_when_readded(scopes):
    client, target, spaces, projects, actor = scopes
    save(client, target, [change(row, 15) for row in rows(client, target)])
    save(client, target, [change(row, 15, ["TECHNICIAN"]) for row in rows(client, target, "project", spaces[0])])
    wsrow = next(row for row in rows(client, target) if row["id"] == str(spaces[0].id))
    response = save(client, target, [change(wsrow, 0)])
    assert response.status_code == 200, response.content
    assert not ProjectMember.objects.filter(member=target, workspace=spaces[0], is_active=True).exists()
    wsrow = next(row for row in rows(client, target) if row["id"] == str(spaces[0].id))
    assert save(client, target, [change(wsrow, 15)]).status_code == 200
    assert not ProjectMember.objects.filter(member=target, workspace=spaces[0], is_active=True).exists()


def test_search_and_pagination_do_not_include_archived_or_other_workspace_projects(scopes):
    client, target, spaces, projects, actor = scopes
    projects[1].archived_at = timezone.now()
    projects[1].save()
    response = client.get(
        url(target), {"kind": "project", "workspace_id": str(spaces[0].id), "search": "SCOPEA", "per_page": 1}
    )
    assert response.status_code == 200, response.content
    assert response.data["count"] == 1 and response.data["results"][0]["id"] == str(projects[0].id)
    assert client.get(url(target), {"kind": "project"}).status_code == 400
    assert client.get(url(target), {"page": 0}).status_code == 400
    assert client.get(url(target), {"per_page": 500}).status_code == 400


def test_project_assignment_outside_admin_current_membership_does_not_join_actor(scopes):
    client, target, spaces, projects, actor = scopes
    ProjectMember.objects.filter(project=projects[2], member=actor).update(is_active=False)
    WorkspaceMember.objects.filter(workspace=spaces[1], member=actor).update(is_active=False)
    wsrow = next(row for row in rows(client, target) if row["id"] == str(spaces[1].id))
    assert save(client, target, [change(wsrow, 15)]).status_code == 200
    prow = rows(client, target, "project", spaces[1])[0]
    response = save(client, target, [change(prow, 15, ["TECHNICIAN", "REGRESSION_TESTER"])])
    assert response.status_code == 200, response.content
    assert not ProjectMember.objects.filter(project=projects[2], member=actor, is_active=True).exists()
    assert capable(projects[2].id, target.id, "solution")


def test_last_manager_cannot_be_removed_by_project_or_workspace_scope(scopes):
    client, target, spaces, projects, actor = scopes
    save(client, target, [change(row, 15) for row in rows(client, target)])
    arow = next(row for row in rows(client, target, "project", spaces[0]) if row["id"] == str(projects[0].id))
    assert save(client, target, [change(arow, 15, ["PROJECT_MANAGER"])]).status_code == 200
    ProjectMember.objects.filter(project=projects[0], member=actor).update(is_active=False)
    arow = next(row for row in rows(client, target, "project", spaces[0]) if row["id"] == str(projects[0].id))
    assert save(client, target, [change(arow, 0)]).status_code == 400
    wsrow = next(row for row in rows(client, target) if row["id"] == str(spaces[0].id))
    assert save(client, target, [change(wsrow, 0)]).status_code == 400
    assert capable(projects[0].id, target.id, "review")


def test_other_invalid_batch_changes_roll_back_prior_valid_grant(scopes):
    client, target, spaces, projects, actor = scopes
    workspace_rows = rows(client, target)
    prow = rows(client, target, "project", spaces[0])[0]
    response = save(client, target, [change(workspace_rows[0], 15), change(prow, 15, [])])
    assert response.status_code == 400, response.content
    assert not WorkspaceMember.objects.filter(member=target).exists()
    assert not ProjectMember.objects.filter(member=target).exists()


def test_source_account_and_project_must_both_be_live_when_granting(scopes, mocker):
    client, target, spaces, projects, actor = scopes
    from plane.quality import platform

    upstream = mocker.patch.object(platform, "fetch", side_effect=AssertionError("no external authority"))
    PlatformAccount.objects.create(
        user=target,
        source_instance="retired",
        external_user_id=78,
        source_username="collector",
        source_role="Collector",
    )
    response = save(client, target, [change(rows(client, target)[0], 15)])
    assert response.status_code == 403, response.content
    assert not WorkspaceMember.objects.filter(member=target).exists()
    assert not ProjectMember.objects.filter(member=target).exists()
    upstream.assert_not_called()


def test_revoked_project_membership_and_duties_are_restored_without_duplicates(scopes):
    client, target, spaces, projects, actor = scopes
    save(client, target, [change(row, 15) for row in rows(client, target)])
    prow = rows(client, target, "project", spaces[0])[0]
    assert save(client, target, [change(prow, 15, ["TECHNICIAN"])]).status_code == 200
    original = ProjectMember.objects.get(project_id=prow["id"], member=target).id
    for role in [0, 15, 0, 15]:
        prow = next(row for row in rows(client, target, "project", spaces[0]) if row["id"] == prow["id"])
        response = save(client, target, [change(prow, role, ["REGRESSION_TESTER"] if role else None)])
        assert response.status_code == 200, response.content
        assert ProjectMember.objects.get(project_id=prow["id"], member=target).id == original
    assert BusinessRole.objects.filter(project_id=prow["id"], user=target).count() == 1
    assert capable(prow["id"], target.id, "execute")


def test_workspace_revision_detects_changed_child_duties(scopes):
    client, target, spaces, projects, actor = scopes
    save(client, target, [change(row, 15) for row in rows(client, target)])
    prow = rows(client, target, "project", spaces[0])[0]
    assert save(client, target, [change(prow, 15, ["TECHNICIAN"])]).status_code == 200
    stale = next(row for row in rows(client, target) if row["id"] == str(spaces[0].id))
    prow = next(row for row in rows(client, target, "project", spaces[0]) if row["id"] == prow["id"])
    assert save(client, target, [change(prow, 15, ["REGRESSION_TESTER"])]).status_code == 200
    response = save(client, target, [change(stale, 0)])
    assert response.status_code == 409, response.content
    assert capable(prow["id"], target.id, "execute")


def test_locally_disabled_source_identity_is_not_silently_reactivated(scopes, mocker):
    client, target, spaces, projects, actor = scopes
    from plane.quality import platform

    upstream = mocker.patch.object(platform, "fetch", side_effect=AssertionError("no external authority"))
    PlatformAccount.objects.create(
        user=target,
        source_instance="retired",
        external_user_id=78,
        source_username="collector",
        source_role="Collector",
    )
    response = save(client, target, [change(rows(client, target)[0], 15)])
    assert response.status_code == 403, response.content
    assert not WorkspaceMember.objects.filter(member=target).exists()
    assert not ProjectMember.objects.filter(member=target).exists()
    upstream.assert_not_called()
