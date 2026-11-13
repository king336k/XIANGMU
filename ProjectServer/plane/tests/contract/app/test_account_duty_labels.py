"""Account labels show effective duties rather than treating access membership as a job."""

import pytest
from plane.db.models import Profile, WorkspaceMember, ProjectMember
from plane.quality.models import BusinessRole
from plane.tests.contract.app.test_module_owners import routing as routing_fixture

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture(name="routing")
def routing_context(session_client, workspace, create_user):
    return routing_fixture.__wrapped__(session_client, workspace, create_user)


def test_account_directory_shows_direct_and_inherited_duties_and_excludes_revoked(routing):
    client, workspace, project, _, users = routing
    BusinessRole.objects.filter(project=project, user=users[0]).update(additional_roles=["REGRESSION_TESTER"])
    WorkspaceMember.objects.filter(workspace=workspace, member=users[1]).update(
        has_workspace_access=True, business_roles=["PROJECT_MANAGER"]
    )
    response = client.get("/api/quality-auth/accounts/")
    assert response.status_code == 200
    rows = {row["id"]: row for row in response.data["results"]}
    assert set(rows[str(users[0].id)]["business_roles"]) == {"TECHNICIAN", "REGRESSION_TESTER"}
    assert rows[str(users[0].id)]["role_summary"] == "技术员、测试员"
    assert set(rows[str(users[1].id)]["business_roles"]) == {"TECHNICIAN", "PROJECT_MANAGER"}
    ProjectMember.objects.filter(project=project, member=users[0]).update(is_active=False)
    refreshed = client.get("/api/quality-auth/accounts/")
    row = next(row for row in refreshed.data["results"] if row["id"] == str(users[0].id))
    assert row["business_roles"] == [] and row["role_summary"] == "未分配岗位"


def test_managed_account_creation_skips_both_automatic_tours(routing):
    client, _, _, _, _ = routing
    response = client.post(
        "/api/quality-auth/accounts/",
        {"username": "account-without-auto-guide", "password": "disposable-pass"},
        format="json",
    )
    assert response.status_code == 201
    profile = Profile.objects.get(user_id=response.data["id"])
    assert profile.is_onboarded and profile.is_navigation_tour_completed and profile.is_tour_completed
