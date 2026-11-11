"""Recoverable deletion is distinct from archive and does not erase frozen evidence."""

import pytest
from plane.db.models import Project, ProjectMember

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def recycling(session_client, workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="用例回收", identifier="RECYCLE")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/"
    case = session_client.post(
        base + "cases/", {"title": "可恢复用例", "steps": [{"action": "打开", "expected": "可见"}]}, format="json"
    ).data
    suite = session_client.post(base + "suites/", {"name": "回归集", "case_ids": [case["id"]]}, format="json").data
    plan = session_client.post(
        base + "plans/",
        {"name": "历史计划", "build": "v1", "environment": "local", "case_ids": [case["id"]]},
        format="json",
    ).data
    return base, case, suite, plan


@pytest.mark.parametrize("kind", ["cases", "suites"])
def test_trash_restore_preserves_case_and_plan_history(session_client, recycling, kind):
    base, case, suite, plan = recycling
    row = case if kind == "cases" else suite
    version = row["version"] if kind == "cases" else row["edit_version"]
    trashed = session_client.post(
        base + "bulk-actions/",
        {
            "resource": kind,
            "action": "trash",
            "items": [{"id": row["id"], "version": version}],
            "reason": "删除误建记录",
        },
        format="json",
    )
    assert trashed.status_code == 200, trashed.content
    assert session_client.get(base + kind + "/").data["count"] == 0
    deleted = session_client.get(base + kind + "/?deleted=true")
    assert deleted.status_code == 200 and deleted.data["count"] == 1
    current = deleted.data["results"][0]
    assert session_client.get(base + f"plans/{plan['id']}/").data["items"][0]["revision"]["version"] == 1
    restored = session_client.post(
        base + "bulk-actions/",
        {
            "resource": kind,
            "action": "untrash",
            "items": [{"id": row["id"], "version": current["version" if kind == "cases" else "edit_version"]}],
            "reason": "恢复误删记录",
        },
        format="json",
    )
    assert restored.status_code == 200, restored.content
    assert session_client.get(base + kind + "/").data["count"] == 1


def test_trashed_case_cannot_be_picked_or_added_to_new_plan(session_client, recycling):
    base, case, suite, plan = recycling
    response = session_client.post(
        base + "bulk-actions/",
        {"resource": "cases", "action": "trash", "items": [{"id": case["id"], "version": 1}], "reason": "移入回收站"},
        format="json",
    )
    assert response.status_code == 200, response.content
    assert session_client.get(base + "case-options/").data["count"] == 0
    created = session_client.post(
        base + "plans/",
        {"name": "不该成功", "build": "v2", "environment": "local", "case_ids": [case["id"]]},
        format="json",
    )
    assert created.status_code == 400, created.content
