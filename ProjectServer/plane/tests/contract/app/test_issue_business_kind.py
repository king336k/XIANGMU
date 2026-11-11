"""Optional project collection kind filtering precedes all pages and group counts."""

from datetime import date
from uuid import uuid4
import pytest
from plane.db.models import Issue, Project, ProjectMember, WorkspaceMember, State, User, Label
from plane.quality.models import Requirement

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def mixed(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="三任务两需求", identifier="KIND")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    states = [
        State.objects.create(project=project, workspace=workspace, name=x, group=g)
        for x, g in [("TODO", "unstarted"), ("Doing", "started")]
    ]
    tasks = []
    requirements = []
    for index in range(5):
        row = Issue(
            name=f"Item {index}",
            project=project,
            workspace=workspace,
            state=states[index % 2],
            priority="high" if index % 2 else "low",
        )
        row.save(created_by_id=create_user.id)
        if index < 3:
            tasks.append(row)
        else:
            Requirement.objects.create(project=project, issue=row, acceptance="核验需求")
            requirements.append(row)
    Issue.objects.create(
        project=project, workspace=workspace, name="Archived", state=states[0], archived_at=date.today()
    )
    Issue.objects.create(project=project, workspace=workspace, name="Draft", state=states[0], is_draft=True)
    other = Project.objects.create(workspace=workspace, name="不允许项目", identifier="HIDDENK")
    foreign = Issue.objects.create(
        project=other,
        workspace=workspace,
        name="Other",
        state=State.objects.create(project=other, workspace=workspace, name="Todo", group="unstarted"),
    )
    Requirement.objects.create(project=other, issue=foreign)
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/"
    return project, states, tasks, requirements, base


def identifiers(value):
    if isinstance(value, list):
        return [str(row["id"]) for row in value if isinstance(row, dict) and "id" in row]
    if isinstance(value, dict):
        if "results" in value:
            return identifiers(value["results"])
        return [identifier for row in value.values() for identifier in identifiers(row)]
    return []


@pytest.mark.parametrize("endpoint", ["issues/", "issues-detail/", "v2/issues/"])
@pytest.mark.parametrize("kind,expected", [("task", 3), ("requirement", 2), ("all", 5), (None, 5)])
def test_kind_scope_matches_counts_and_every_page(session_client, mixed, endpoint, kind, expected):
    project, states, tasks, requirements, base = mixed
    seen = []
    wanted = (
        {str(row.id) for row in tasks if kind == "task"}
        if kind == "task"
        else {str(row.id) for row in requirements}
        if kind == "requirement"
        else {str(row.id) for row in tasks + requirements}
    )
    for page in range(5):
        params = {"per_page": 2, "cursor": f"2:{page}:0", "order_by": "sequence_id"}
        if kind is not None:
            params["business_kind"] = kind
        response = session_client.get(base + endpoint, params)
        assert response.status_code == 200, response.data
        assert response.data.get("total_count", response.data.get("total_results")) == expected
        seen += identifiers(response.data["results"])
        if not response.data["next_page_results"]:
            break
    assert set(seen) == wanted
    assert len(seen) == len(set(seen)) == expected


@pytest.mark.parametrize("group,subgroup", [("priority", None), ("state_id", None), ("state_id", "priority")])
def test_task_group_and_board_counts_use_filtered_scope(session_client, mixed, group, subgroup):
    project, states, tasks, requirements, base = mixed
    seen = []
    for page in range(5):
        params = {
            "business_kind": "task",
            "per_page": 1,
            "cursor": f"1:{page}:0",
            "group_by": group,
            "order_by": "state__name,-sequence_id",
        }
        if subgroup:
            params["sub_group_by"] = subgroup
        response = session_client.get(base + "issues/", params)
        assert response.status_code == 200, response.data
        assert response.data["total_count"] == 3
        expected_groups = {
            str(getattr(row, group)): sum(getattr(candidate, group) == getattr(row, group) for candidate in tasks)
            for row in tasks
        }
        for key, bucket in response.data["results"].items():
            assert bucket["total_results"] == expected_groups.get(key, 0)
            if subgroup:
                for subkey, subbucket in bucket["results"].items():
                    assert subbucket["total_results"] == sum(
                        str(getattr(row, group)) == key and str(getattr(row, subgroup)) == subkey for row in tasks
                    )
        seen += identifiers(response.data["results"])
        if not response.data["next_page_results"]:
            break
    assert len(seen) == len(set(seen)) == 3
    assert set(seen) == {str(row.id) for row in tasks}


@pytest.mark.parametrize("endpoint", ["issues/", "issues-detail/", "v2/issues/", "issues/list/"])
@pytest.mark.parametrize("kind", ["bad", "Task", "task,requirement", "", "task;DROP TABLE"])
def test_invalid_kind_is_not_silently_ignored(session_client, mixed, endpoint, kind):
    project, states, tasks, requirements, base = mixed
    params = {"business_kind": kind, "issues": ",".join(str(x.id) for x in tasks + requirements)}
    response = session_client.get(base + endpoint, params)
    assert response.status_code == 400, response.data


def test_explicit_ids_list_is_optional_but_single_detail_is_not_filtered(session_client, mixed):
    project, states, tasks, requirements, base = mixed
    ids = ",".join(str(x.id) for x in tasks + requirements)
    allrows = session_client.get(base + "issues/list/", {"issues": ids})
    assert allrows.status_code == 200, allrows.data
    assert set(identifiers(allrows.data)) == {str(x.id) for x in tasks + requirements}
    filtered = session_client.get(base + "issues/list/", {"issues": ids, "business_kind": "task"})
    assert filtered.status_code == 200, filtered.data
    assert set(identifiers(filtered.data)) == {str(x.id) for x in tasks}
    detail = session_client.get(base + f"issues/{requirements[0].id}/", {"business_kind": "task"})
    assert detail.status_code == 200, detail.data
    assert str(detail.data["id"]) == str(requirements[0].id)


@pytest.mark.parametrize("endpoint", ["issues/", "issues-detail/", "v2/issues/"])
def test_guest_own_scope_and_project_denial_survive_kind_filter(session_client, mixed, workspace, endpoint):
    project, states, tasks, requirements, base = mixed
    guest = User.objects.create(username="guest-kind", email="guest-kind@test.invalid")
    WorkspaceMember.objects.create(workspace=workspace, member=guest, role=5)
    ProjectMember.objects.create(project=project, workspace=workspace, member=guest, role=5)
    own = Issue(name="Guest task", project=project, workspace=workspace, state=states[0])
    own.save(created_by_id=guest.id)
    ownreq = Issue(name="Guest requirement", project=project, workspace=workspace, state=states[1])
    ownreq.save(created_by_id=guest.id)
    Requirement.objects.create(project=project, issue=ownreq)
    session_client.force_authenticate(guest)
    response = session_client.get(base + endpoint, {"business_kind": "task"})
    assert response.status_code == 200, response.data
    assert identifiers(response.data["results"]) == [str(own.id)]
    assert response.data.get("total_count", response.data.get("total_results")) == 1
    outsider = Project.objects.get(identifier="HIDDENK")
    assert (
        session_client.get(
            base.replace(str(project.id), str(outsider.id)) + endpoint, {"business_kind": "task"}
        ).status_code
        == 403
    )


def test_task_filter_does_not_duplicate_m2m_matches_or_change_workspace_default(session_client, mixed, workspace):
    project, states, tasks, requirements, base = mixed
    labels = [Label.objects.create(project=project, workspace=workspace, name=str(uuid4())) for _ in range(2)]
    for row in tasks + requirements:
        row.labels.add(*labels, through_defaults={"project": project, "workspace": workspace})
    response = session_client.get(
        base + "issues/", {"business_kind": "task", "labels": ",".join(str(x.id) for x in labels), "per_page": 100}
    )
    assert response.status_code == 200, response.data
    assert len(identifiers(response.data["results"])) == 3 and response.data["total_count"] == 3
    globalrows = session_client.get(f"/api/workspaces/{workspace.slug}/issues/", {"per_page": 100})
    assert globalrows.status_code == 200, globalrows.data
    assert {str(x.id) for x in requirements}.issubset(set(identifiers(globalrows.data["results"])))


@pytest.mark.parametrize("endpoint", ["issues/", "issues-detail/", "v2/issues/", "issues/list/"])
def test_duplicate_kind_params_are_rejected_before_counting(session_client, mixed, endpoint):
    project, states, tasks, requirements, base = mixed
    query = "business_kind=task&business_kind=all&issues=" + ",".join(str(x.id) for x in tasks + requirements)
    response = session_client.get(base + endpoint + "?" + query)
    assert response.status_code == 400, response.data


def test_create_and_retrieve_ignore_list_kind_without_modifying_requirement_links(session_client, mixed):
    project, states, tasks, requirements, base = mixed
    created = session_client.post(
        base + "issues/?business_kind=requirement", {"name": "新任务", "state": str(states[0].id)}, format="json"
    )
    assert created.status_code == 201, created.data
    assert not Requirement.objects.filter(issue_id=created.data["id"]).exists()
    allrows = session_client.get(base + "issues/", {"business_kind": "task", "per_page": 100})
    assert allrows.status_code == 200, allrows.data
    assert len(identifiers(allrows.data["results"])) == 4
    assert str(created.data["id"]) in identifiers(allrows.data["results"])
    assert Requirement.objects.filter(project=project).count() == 2
