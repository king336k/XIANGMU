"""Reviewer-owned target eligibility checks in a dedicated isolated source/DB."""

import pytest
from plane.db.models import Project, ProjectMember
from plane.quality.models import BusinessRole
from plane.tests.contract.app.test_module_owners import bind, ready_job, route
from plane.tests.contract.app.test_module_owners import routing as routing

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def reassign(routing, target, module="omit"):
    client, workspace, project, admin, users = routing
    assert bind(routing).status_code == 200
    d = route(ready_job(routing))
    assert d.module_id == "daq"
    data = {"expected_version": d.edit_version, "assignee_id": str(target.id), "reason": "isolated reviewer boundary"}
    if module != "omit":
        data["module_key"] = module
    response = client.post(
        f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/defects/{d.id}/reassign/", data, format="json"
    )
    d.refresh_from_db()
    return response, d


@pytest.mark.parametrize("module", ["omit", "daq"])
def test_confirmed_module_does_not_allow_nontech_admin_target(routing, module):
    response, d = reassign(routing, routing[3], module)
    assert response.status_code == 400, response.data
    assert d.module_id == "daq" and d.assignee_id == routing[4][0].id


def test_unconfirmed_module_allows_active_admin_and_records_audit(routing):
    response, d = reassign(routing, routing[3], None)
    assert response.status_code == 200, response.data
    assert d.module_id is None and d.assignee_id == routing[3].id and d.assignment_origin == "manual"
    assert d.events.filter(note__contains="isolated reviewer boundary").exists()


def test_unconfirmed_module_allows_current_project_manager(routing):
    target = routing[4][2]
    BusinessRole.objects.filter(project=routing[2], user=target).update(role="PROJECT_MANAGER")
    response, d = reassign(routing, target, None)
    assert response.status_code == 200, response.data
    assert d.module_id is None and d.assignee_id == target.id


def test_other_project_manager_does_not_gain_current_project_triage_target(routing):
    _, workspace, project, admin, users = routing
    target = users[2]
    other = Project.objects.create(workspace=workspace, name="isolated other", identifier="REVIEWOTHER")
    ProjectMember.objects.create(project=other, member=target, role=15)
    BusinessRole.objects.create(project=other, user=target, role="PROJECT_MANAGER")
    response, d = reassign(routing, target, None)
    assert response.status_code == 400, response.data
    assert d.module_id == "daq"


def test_inactive_project_manager_not_valid_triage_target(routing):
    target = routing[4][2]
    BusinessRole.objects.filter(project=routing[2], user=target).update(role="PROJECT_MANAGER")
    target.is_active = False
    target.save(update_fields=["is_active"])
    response, d = reassign(routing, target, None)
    assert response.status_code == 400, response.data


def test_manager_without_active_current_membership_not_valid_target(routing):
    target = routing[4][2]
    BusinessRole.objects.filter(project=routing[2], user=target).update(role="PROJECT_MANAGER")
    ProjectMember.objects.filter(project=routing[2], member=target).update(is_active=False)
    response, d = reassign(routing, target, None)
    assert response.status_code == 400, response.data


def test_bot_with_misconfigured_manager_role_is_not_human_triage_target(routing):
    target = routing[4][2]
    BusinessRole.objects.filter(project=routing[2], user=target).update(role="PROJECT_MANAGER")
    target.is_bot = True
    target.save(update_fields=["is_bot"])
    response, d = reassign(routing, target, None)
    assert response.status_code == 400, response.data


def test_external_platform_account_with_manager_role_not_human_triage_target(routing):
    from plane.quality.models import PlatformAccount

    target = routing[4][2]
    BusinessRole.objects.filter(project=routing[2], user=target).update(role="PROJECT_MANAGER")
    PlatformAccount.objects.create(
        source_instance="isolated-review", external_user_id=9001, user=target, source_username="synthetic-external"
    )
    response, d = reassign(routing, target, None)
    assert response.status_code == 400, response.data
