"""Account and version directories paginate the complete authorized search scope."""

from uuid import uuid4

import pytest
from django.utils import timezone

from plane.db.models import Issue, Project, ProjectMember, User
from plane.license.models import Instance, InstanceAdmin
from plane.quality.models import ProjectVersion

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def directory_project(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="Directory pages", identifier="DIRPAGE")
    ProjectMember.objects.create(project=project, workspace=workspace, member=create_user, role=20)
    return project, f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/versions/"


@pytest.fixture
def directory_admin(create_user):
    instance = Instance.objects.create(
        instance_name="Directory admin",
        instance_id=str(uuid4()),
        current_version="test",
        last_checked_at=timezone.now(),
    )
    InstanceAdmin.objects.create(instance=instance, user=create_user)
    return create_user


def test_version_filters_run_before_count_and_page_with_stable_ties(session_client, directory_project, workspace):
    project, url = directory_project
    rows = [
        ProjectVersion.objects.create(
            project=project,
            name=f"Search {index:02}",
            version=f"v{index:02}",
            status="testing" if index % 2 else "planning",
        )
        for index in range(35)
    ]
    ProjectVersion.objects.filter(project=project).update(created_at=timezone.now())
    other = Project.objects.create(workspace=workspace, name="Hidden versions", identifier="DIRHIDDEN")
    ProjectVersion.objects.create(project=other, name="Search hidden", version="other", status="testing")
    seen = []
    for page in range(1, 5):
        response = session_client.get(
            url, {"search": "Search", "status": "testing", "ordering": "name", "page": page, "per_page": 5}
        )
        assert response.status_code == 200, response.data
        assert response.data["count"] == 17
        seen.extend(row["id"] for row in response.data["results"])
    assert seen == [str(row.id) for row in rows if row.status == "testing"]
    exact = session_client.get(url, {"version": "v34", "per_page": 5})
    assert exact.status_code == 200 and exact.data["count"] == 1
    assert exact.data["results"][0]["id"] == str(rows[34].id)
    assert session_client.get(url.replace(str(project.id), str(other.id))).status_code == 403


@pytest.mark.parametrize("query", [{"status": "invented"}, {"ordering": "owner__password"}, {"owner_id": "bad"}])
def test_version_filters_validate_instead_of_silently_ignoring(session_client, directory_project, query):
    _, url = directory_project
    assert session_client.get(url, query).status_code == 400


def test_version_options_accept_page_size_preserving_search_count_and_shape(
    session_client, directory_project, workspace
):
    project, url = directory_project
    rows = [Issue.objects.create(project=project, workspace=workspace, name=f"Pick {index:02}") for index in range(31)]
    seen = []
    for page in range(1, 8):
        response = session_client.get(
            url + "options/", {"kind": "issue", "search": "Pick", "per_page": 5, "page": page}
        )
        assert response.status_code == 200, response.data
        assert response.data["count"] == 31 and response.data["per_page"] == 5
        assert response.data["next"] == (page + 1 if page < 7 else None)
        assert response.data["previous"] == (page - 1 if page > 1 else None)
        seen.extend(row["id"] for row in response.data["results"])
    assert len(seen) == len(set(seen)) == len(rows)
    default = session_client.get(url + "options/", {"kind": "issue"})
    assert default.data["per_page"] == 25 and len(default.data["results"]) == 25


@pytest.mark.parametrize("size", [0, -1, 101, "invalid"])
def test_version_option_sizes_are_bounded(session_client, directory_project, size):
    _, url = directory_project
    assert session_client.get(url + "options/", {"per_page": size}).status_code == 400


def test_local_directory_pages_beyond_first_hundred_and_counts_filtered_scope(session_client, directory_admin):
    User.objects.bulk_create(
        [
            User(
                email=f"paging-{index}@directory.invalid",
                username=f"paging-{index:03}",
                display_name=f"Paging {index:03}",
            )
            for index in range(125)
        ]
    )
    endpoint = "/api/quality-auth/accounts/"
    seen = []
    for page in range(1, 8):
        response = session_client.get(endpoint, {"search": "paging-", "page": page, "per_page": 20})
        assert response.status_code == 200, response.data
        assert response.data["count"] == 125 and response.data["per_page"] == 20
        assert response.data["next"] == (page + 1 if page < 7 else None)
        seen.extend(row["username"] for row in response.data["results"])
        assert "external_results" in response.data and "sources" in response.data
    assert seen == [f"paging-{index:03}" for index in range(125)]
    legacy = session_client.get(endpoint, {"search": "paging-"})
    assert legacy.data["per_page"] == 100 and len(legacy.data["results"]) == 100
    assert legacy.data["count"] == 125
    exact = session_client.get(endpoint, {"search": "paging-124", "per_page": 5})
    assert exact.data["count"] == 1 and exact.data["results"][0]["username"] == "paging-124"


@pytest.mark.parametrize("query", [{"per_page": 0}, {"per_page": 101}, {"per_page": "bad"}, {"page": 0}])
def test_local_directory_paging_rejects_invalid_input(session_client, directory_admin, query):
    assert session_client.get("/api/quality-auth/accounts/", query).status_code == 400


def test_non_admin_directory_still_hides_accounts(session_client):
    response = session_client.get("/api/quality-auth/accounts/", {"page": 2, "per_page": 5})
    assert response.status_code == 200 and response.data == {"can_manage": False, "results": []}


def test_source_directory_is_not_queried_even_when_client_requests_it(
    session_client, directory_admin, directory_project, workspace, mocker
):
    project, _ = directory_project
    outbound = mocker.patch("plane.quality.platform.fetch", side_effect=AssertionError("no source directory"))
    response = session_client.get(
        "/api/quality-auth/accounts/",
        {
            "source_instance": "source",
            "workspace_slug": workspace.slug,
            "project_id": str(project.id),
            "search": "remote-129",
        },
    )
    assert response.status_code == 400, response.content
    assert not response.data.get("external_results")
    outbound.assert_not_called()
