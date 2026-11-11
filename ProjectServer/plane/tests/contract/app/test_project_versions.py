"""Project versions connect existing work without inventing approval or test completion."""

import pytest
from plane.db.models import Project, ProjectMember, State, Issue
from plane.quality.models import Defect

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def version_project(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="版本管理", identifier="VERSION")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    return project, f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/versions/"


def create_version(client, url, **extra):
    return client.post(
        url,
        {"name": "日志体验改版", "version": "v2.0", "start_date": "2026-11-01", "target_date": "2026-11-30", **extra},
        format="json",
    )


def test_version_create_read_edit_conflicts_and_project_isolation(session_client, version_project, workspace):
    project, url = version_project
    response = create_version(session_client, url)
    assert response.status_code == 201, response.content
    version = response.data
    assert version["status"] == "planning" and version["automation_enabled"] is False
    assert create_version(session_client, url).status_code == 409
    assert (
        session_client.patch(
            url + version["id"] + "/", {"expected_version": 999, "name": "覆盖"}, format="json"
        ).status_code
        == 409
    )
    other = Project.objects.create(workspace=workspace, name="不可见", identifier="VISO")
    hidden = url.replace(str(project.id), str(other.id)) + version["id"] + "/"
    assert session_client.get(hidden).status_code == 403


def test_version_flow_rejects_cycle_and_cross_project_record(session_client, version_project, workspace):
    project, url = version_project
    response = create_version(
        session_client,
        url,
        flow_nodes=[
            {"id": "a", "name": "分支A", "kind": "milestone", "depends_on": ["b"]},
            {"id": "b", "name": "汇总B", "kind": "milestone", "depends_on": ["a"]},
        ],
    )
    assert response.status_code == 400, response.content
    other = Project.objects.create(workspace=workspace, name="其他", identifier="VOTHER")
    defect = Defect.objects.create(project=other, title="外项目")
    response = create_version(
        session_client, url, flow_nodes=[{"id": "a", "name": "错误关联", "kind": "defect", "object_id": str(defect.id)}]
    )
    assert response.status_code == 400


def test_version_milestones_and_release_cannot_skip_requirements_or_defects(session_client, version_project):
    project, url = version_project
    root = url.removesuffix("versions/")
    requirement = session_client.post(
        root + "requirements/", {"title": "上线需求", "acceptance": "文字可见", "target_build": "v2.0"}, format="json"
    )
    assert requirement.status_code == 201
    created = create_version(session_client, url)
    assert created.status_code == 201, created.content
    pk = created.data["id"]
    for state in ["development", "testing", "ready"]:
        updated = session_client.post(
            url + pk + "/workflow/",
            {"action": "advance", "expected_version": created.data["edit_version"], "note": "经理确认进入下一阶段"},
            format="json",
        )
        assert updated.status_code == 200, updated.content
        assert updated.data["status"] == state
        created = updated
    release = session_client.post(
        url + pk + "/workflow/",
        {"action": "advance", "expected_version": created.data["edit_version"], "note": "准备发布"},
        format="json",
    )
    assert release.status_code == 409
    assert "需求" in str(release.data)


def test_automatic_parallel_join_waits_for_all_and_does_not_complete_actual_work(
    session_client, version_project, create_user
):
    project, url = version_project
    done = State.objects.create(project=project, workspace=project.workspace, name="已完成", group="completed")
    todo = State.objects.create(project=project, workspace=project.workspace, name="待办", group="backlog")
    tasks = [
        Issue.objects.create(project=project, workspace=project.workspace, name=label, state=todo)
        for label in ["A模块", "B模块", "F汇总"]
    ]
    nodes = [
        {"id": "a", "name": "A模块", "kind": "issue", "object_id": str(tasks[0].id), "owner_id": str(create_user.id)},
        {"id": "b", "name": "B模块", "kind": "issue", "object_id": str(tasks[1].id), "owner_id": str(create_user.id)},
        {
            "id": "f",
            "name": "F汇总",
            "kind": "issue",
            "object_id": str(tasks[2].id),
            "owner_id": str(create_user.id),
            "depends_on": ["a", "b"],
            "join": "all",
        },
    ]
    created = create_version(session_client, url, flow_nodes=nodes)
    assert created.status_code == 201, created.content
    pk = created.data["id"]
    activated = session_client.post(
        url + pk + "/workflow/",
        {"action": "enable_automation", "expected_version": created.data["edit_version"], "note": "按既有职责自动分派"},
        format="json",
    )
    assert activated.status_code == 200, activated.content
    tasks[0].state = done
    tasks[0].save()
    response = session_client.post(url + pk + "/sync/", {}, format="json")
    assert response.status_code == 200, response.content
    assert response.data["flow_state"]["f"]["status"] == "waiting"
    assert not tasks[2].assignees.exists()
    tasks[1].state = done
    tasks[1].save()
    response = session_client.post(url + pk + "/sync/", {}, format="json")
    assert response.status_code == 200, response.content
    assert response.data["flow_state"]["f"]["status"] == "ready"
    tasks[2].refresh_from_db()
    assert tasks[2].state_id == todo.id and tasks[2].assignees.filter(id=create_user.id).exists()
    assert len(response.data["events"]) >= 2


def test_version_nonmanager_cannot_write_or_enable_auto(session_client, version_project, create_user):
    project, url = version_project
    ProjectMember.objects.filter(project=project, member=create_user).update(role=15)
    assert create_version(session_client, url).status_code == 403


def test_auto_flow_revoked_enabler_cannot_assign_next_node(session_client, version_project, create_user):
    from plane.quality.models import ProjectVersion
    from plane.quality.project_versions import dispatch_ready
    from django.db import transaction

    project, url = version_project
    issue = Issue.objects.create(project=project, workspace=project.workspace, name="等待分派")
    response = create_version(
        session_client,
        url,
        flow_nodes=[
            {
                "id": "task",
                "name": "研发任务",
                "kind": "issue",
                "object_id": str(issue.id),
                "owner_id": str(create_user.id),
            }
        ],
    )
    row = ProjectVersion.objects.get(pk=response.data["id"])
    row.automation_enabled = True
    row.automation_by = create_user
    row.save()
    ProjectMember.objects.filter(project=project, member=create_user).update(role=15)
    with transaction.atomic():
        dispatch_ready(row)
    assert not row.automation_enabled and not issue.assignees.exists()


def test_auto_join_any_and_repeat_sync_do_not_duplicate_assignment(session_client, version_project, create_user):
    from plane.quality.models import ProjectVersionEvent

    project, url = version_project
    done = State.objects.create(project=project, workspace=project.workspace, name="完成", group="completed")
    todo = State.objects.create(project=project, workspace=project.workspace, name="待办", group="backlog")
    a = Issue.objects.create(project=project, workspace=project.workspace, name="A完成", state=done)
    b = Issue.objects.create(project=project, workspace=project.workspace, name="B待办", state=todo)
    f = Issue.objects.create(project=project, workspace=project.workspace, name="汇合", state=todo)
    nodes = [
        {"id": "a", "name": "A", "kind": "issue", "object_id": str(a.id)},
        {"id": "b", "name": "B", "kind": "issue", "object_id": str(b.id), "required": False},
        {
            "id": "f",
            "name": "F",
            "kind": "issue",
            "object_id": str(f.id),
            "owner_id": str(create_user.id),
            "depends_on": ["a", "b"],
            "join": "any",
        },
    ]
    response = create_version(session_client, url, flow_nodes=nodes)
    assert response.status_code == 201, response.content
    pk = response.data["id"]
    enabled = session_client.post(
        url + pk + "/workflow/",
        {"action": "enable_automation", "expected_version": 1, "note": "任一分支完成分派"},
        format="json",
    )
    assert enabled.status_code == 200, enabled.content
    for _ in range(2):
        assert session_client.post(url + pk + "/sync/", {}, format="json").status_code == 200
    assert f.assignees.count() == 1
    assert ProjectVersionEvent.objects.filter(version_id=pk, action="dispatch").count() == 1


def test_milestone_cannot_complete_while_prerequisite_incomplete(session_client, version_project):
    project, url = version_project
    response = create_version(
        session_client,
        url,
        flow_nodes=[
            {"id": "a", "name": "需求确认", "kind": "milestone"},
            {"id": "b", "name": "发布", "kind": "milestone", "depends_on": ["a"]},
        ],
    )
    assert response.status_code == 201
    endpoint = url + response.data["id"] + "/workflow/"
    blocked = session_client.post(
        endpoint,
        {"action": "complete_node", "expected_version": 1, "node_id": "b", "note": "未满足前置"},
        format="json",
    )
    assert blocked.status_code == 409
    approved = session_client.post(
        endpoint,
        {"action": "complete_node", "expected_version": 1, "node_id": "a", "note": "需求已确认"},
        format="json",
    )
    assert approved.status_code == 200 and approved.data["flow_state"]["a"]["status"] == "completed"


def test_published_flow_state_is_snapshot_not_rewritten_by_later_work_changes(session_client, version_project):
    project, url = version_project
    done = State.objects.create(project=project, workspace=project.workspace, name="完成", group="completed")
    todo = State.objects.create(project=project, workspace=project.workspace, name="待办", group="backlog")
    issue = Issue.objects.create(project=project, workspace=project.workspace, name="已交付任务", state=done)
    response = create_version(
        session_client, url, flow_nodes=[{"id": "task", "name": "交付", "kind": "issue", "object_id": str(issue.id)}]
    )
    assert response.status_code == 201, response.content
    pk = response.data["id"]
    for _ in range(4):
        response = session_client.post(
            url + pk + "/workflow/",
            {"action": "advance", "expected_version": response.data["edit_version"], "note": "已核对本阶段交付"},
            format="json",
        )
        assert response.status_code == 200, response.content
    assert response.data["status"] == "released"
    issue.state = todo
    issue.save()
    result = session_client.get(url + pk + "/")
    assert result.data["flow_state"]["task"]["status"] == "completed"
    assert result.data["published_snapshot"]["tasks"][0]["title"] == "已交付任务"


def test_background_flow_checks_revocation_before_assignment(session_client, version_project, create_user):
    from plane.quality.models import ProjectVersion
    from plane.quality.tasks import sync_project_versions

    project, url = version_project
    issue = Issue.objects.create(project=project, workspace=project.workspace, name="不应自动分派")
    result = create_version(
        session_client,
        url,
        flow_nodes=[
            {"id": "task", "name": "分派", "kind": "issue", "object_id": str(issue.id), "owner_id": str(create_user.id)}
        ],
    )
    row = ProjectVersion.objects.get(pk=result.data["id"])
    row.automation_enabled = True
    row.automation_by = create_user
    row.save()
    ProjectMember.objects.filter(project=project, member=create_user).update(role=15)
    sync_project_versions()
    row.refresh_from_db()
    assert not row.automation_enabled and not issue.assignees.exists()


def test_version_history_after_100_is_reachable_with_count(session_client, version_project, create_user):
    from plane.quality.models import ProjectVersion, ProjectVersionEvent

    project, url = version_project
    version = ProjectVersion.objects.create(project=project, name="101条版本历史", version="v101", status="testing")
    events = [
        ProjectVersionEvent(
            project=project,
            created_by=create_user,
            version=version,
            action="edit",
            before_status="planning",
            status="planning",
            note=f"event-{i}",
        )
        for i in range(101)
    ]
    ProjectVersionEvent.objects.bulk_create(events)
    first = session_client.get(url + str(version.id) + "/?page=1&per_page=100")
    second = session_client.get(url + str(version.id) + "/?page=2&per_page=100")
    assert first.status_code == second.status_code == 200
    assert first.data["event_pagination"]["count"] == 101
    assert len(first.data["events"]) == 100 and len(second.data["events"]) == 1
    assert {event["id"] for event in first.data["events"]} | {event["id"] for event in second.data["events"]} == {
        str(event.id) for event in events
    }
    assert first.data["status"] == second.data["status"] == "testing"


def test_version_history_pages_keep_existing_project_read_permission(
    session_client, version_project, create_user, workspace
):
    from plane.quality.models import ProjectVersion, ProjectVersionEvent

    project, url = version_project
    version = ProjectVersion.objects.create(project=project, name="仅本项目可读", version="v-history")
    ProjectVersionEvent.objects.bulk_create(
        [ProjectVersionEvent(project=project, version=version, action="edit", status="planning") for i in range(101)]
    )
    foreign = Project.objects.create(workspace=workspace, name="不可见项目", identifier="HIDDENH")
    ProjectMember.objects.create(project=foreign, member=create_user, role=20)
    hidden_url = url.replace(str(project.id), str(foreign.id)) + str(version.id) + "/?page=2&per_page=100"
    assert session_client.get(hidden_url).status_code == 404
    ProjectMember.objects.filter(project=project, member=create_user).update(is_active=False)
    assert session_client.get(url + str(version.id) + "/?page=2&per_page=100").status_code == 403
