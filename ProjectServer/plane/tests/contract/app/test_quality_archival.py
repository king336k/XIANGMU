"""Bulk archival is reversible and cannot bypass active test or defect state."""

import pytest
from plane.db.models import Project, ProjectMember

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def archival(session_client, workspace, create_user):
    p = Project.objects.create(workspace=workspace, name="归档维护", identifier="ARCH")
    ProjectMember.objects.create(project=p, member=create_user, role=20)
    base = f"/api/workspaces/{workspace.slug}/projects/{p.id}/quality/"
    rows = []
    for title in ["用例一", "用例二"]:
        rows.append(
            session_client.post(
                base + "cases/", {"title": title, "steps": [{"action": "操作", "expected": "预期"}]}, format="json"
            ).data
        )
    return base, p, rows


def test_cases_bulk_priority_version_guard_and_reversible_archive(session_client, archival):
    base, p, rows = archival
    request = {
        "resource": "cases",
        "action": "priority",
        "items": [{"id": row["id"], "version": row["version"]} for row in rows],
        "priority": "high",
        "reason": "提升回归重要性",
    }
    updated = session_client.post(base + "bulk-actions/", request, format="json")
    assert updated.status_code == 200 and len(updated.data["items"]) == 2, updated.content
    assert session_client.post(base + "bulk-actions/", request, format="json").status_code == 409
    latest = updated.data["items"]
    archived = session_client.post(
        base + "bulk-actions/",
        {
            "resource": "cases",
            "action": "archive",
            "items": [{"id": row["id"], "version": row["version"]} for row in latest],
            "reason": "旧版用例归档",
        },
        format="json",
    )
    assert archived.status_code == 200
    assert session_client.get(base + "cases/").data["count"] == 0
    archived_rows = session_client.get(base + "cases/?archived=true").data["results"]
    assert len(archived_rows) == 2
    restored = session_client.post(
        base + "bulk-actions/",
        {
            "resource": "cases",
            "action": "restore",
            "items": [{"id": row["id"], "version": row["version"]} for row in archived_rows],
            "reason": "恢复复用",
        },
        format="json",
    )
    assert restored.status_code == 200 and session_client.get(base + "cases/").data["count"] == 2


def test_running_plan_and_open_defect_cannot_be_archived(session_client, archival):
    base, p, rows = archival
    plan = session_client.post(
        base + "plans/",
        {"name": "尚未结束", "build": "v1", "environment": "local", "managed": True, "case_ids": [rows[0]["id"]]},
        format="json",
    ).data
    response = session_client.post(
        base + "bulk-actions/",
        {
            "resource": "plans",
            "action": "archive",
            "items": [{"id": plan["id"], "version": plan["workflow_version"]}],
            "reason": "不得跳过执行",
        },
        format="json",
    )
    assert response.status_code == 409, response.content
    defect = session_client.post(base + "defects/", {"title": "未完成缺陷"}, format="json").data
    denied = session_client.post(
        base + "bulk-actions/",
        {
            "resource": "defects",
            "action": "archive",
            "items": [{"id": defect["id"], "version": defect["edit_version"]}],
            "reason": "未关闭不可归档",
        },
        format="json",
    )
    assert denied.status_code == 409


def test_cross_project_bulk_is_atomic_and_cannot_modify_partial_items(session_client, archival):
    from uuid import uuid4

    base, p, rows = archival
    response = session_client.post(
        base + "bulk-actions/",
        {
            "resource": "cases",
            "action": "priority",
            "items": [{"id": rows[0]["id"], "version": 1}, {"id": str(uuid4()), "version": 1}],
            "priority": "high",
            "reason": "非法跨项目",
        },
        format="json",
    )
    assert response.status_code == 400
    assert session_client.get(base + f"cases/{rows[0]['id']}/").data["version"] == 1
