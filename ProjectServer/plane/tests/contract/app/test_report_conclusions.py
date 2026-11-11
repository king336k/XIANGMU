"""A manager's signed conclusion annotates an immutable report, without forging results."""

from uuid import uuid4
import pytest
from plane.db.models import Project, ProjectMember
from plane.quality.models import SavedReport

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def report(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="报告结论", identifier="CONC")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    row = SavedReport.objects.create(
        project=project,
        created_by=create_user,
        name="未执行报告",
        request_id=uuid4(),
        snapshot={
            "summary": {"total": 1, "pending": 1, "failed": 0, "blocked": 0, "skipped": 0, "passed": 0},
            "plans": [],
            "definitions": "保存当时真实结果",
        },
    )
    return f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/", project, row


def test_final_conclusion_is_immutable_and_does_not_change_execution_snapshot(session_client, report):
    base, project, row = report
    original = row.snapshot.copy()
    url = base + f"reports/{row.id}/conclusion/"
    payload = {
        "expected_version": 1,
        "result": "blocked",
        "summary": "缺少真实采集证据，暂不通过。",
        "risks": "须补充新Session。",
    }
    response = session_client.post(url, payload, format="json")
    assert response.status_code == 201, response.content
    row.refresh_from_db()
    assert row.snapshot == original
    assert response.data["result"] == "blocked" and response.data["reviewed_at"]
    assert session_client.post(url, payload, format="json").status_code == 200
    changed = session_client.post(url, {**payload, "summary": "改写已签结论"}, format="json")
    assert changed.status_code == 409


def test_passed_conclusion_rejects_pending_or_failed_snapshot(session_client, report):
    base, project, row = report
    response = session_client.post(
        base + f"reports/{row.id}/conclusion/",
        {"expected_version": 1, "result": "passed", "summary": "不能忽略未执行"},
        format="json",
    )
    assert response.status_code == 400, response.content


def test_only_project_manager_can_sign_report_and_cross_project_is_denied(session_client, report, create_user):
    base, project, row = report
    ProjectMember.objects.filter(project=project, member=create_user).update(role=15)
    response = session_client.post(
        base + f"reports/{row.id}/conclusion/",
        {"expected_version": 1, "result": "blocked", "summary": "普通成员不能签署"},
        format="json",
    )
    assert response.status_code == 403, response.content


def test_passed_conclusion_requires_manager_review_and_closed_defects(session_client, report):
    base, project, row = report
    row.snapshot["summary"].update(pending=0, passed=1)
    row.snapshot["plans"] = [{"managed": True, "status": "review", "reviewed_at": None}]
    row.save()
    payload = {"expected_version": 1, "result": "passed", "summary": "全部验证通过，经理确认。"}
    url = base + f"reports/{row.id}/conclusion/"
    assert session_client.post(url, payload, format="json").status_code == 400
    row.snapshot["plans"] = [{"managed": True, "status": "completed", "reviewed_at": "2026-11-07T10:00:00+08:00"}]
    row.snapshot["defects"] = [{"status": "open"}]
    row.save()
    assert session_client.post(url, payload, format="json").status_code == 400
    row.snapshot["defects"] = [{"status": "closed"}]
    row.save()
    response = session_client.post(url, payload, format="json")
    assert response.status_code == 201, response.content
    detail = session_client.get(base + f"reports/{row.id}/")
    assert detail.data["conclusion"]["summary"] == payload["summary"]


def test_conclusion_cannot_be_attached_across_project_or_stale_report_version(
    session_client, report, workspace, create_user
):
    base, project, row = report
    payload = {"expected_version": 99, "result": "blocked", "summary": "旧版本签署应拒绝"}
    assert session_client.post(base + f"reports/{row.id}/conclusion/", payload, format="json").status_code == 409
    other = Project.objects.create(workspace=workspace, name="另一项目", identifier="OTC")
    ProjectMember.objects.create(project=other, member=create_user, role=20)
    other_base = f"/api/workspaces/{workspace.slug}/projects/{other.id}/quality/"
    assert session_client.post(other_base + f"reports/{row.id}/conclusion/", payload, format="json").status_code == 404
