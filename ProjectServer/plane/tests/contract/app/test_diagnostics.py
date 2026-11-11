"""Background diagnostics are cancellable and never claim a model result when not configured."""

from uuid import uuid4
import pytest
from plane.db.models import Project, ProjectMember

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def diagnostics(session_client, workspace, create_user):
    p = Project.objects.create(workspace=workspace, name="后台诊断", identifier="DIAG")
    ProjectMember.objects.create(project=p, member=create_user, role=20)
    base = f"/api/workspaces/{workspace.slug}/projects/{p.id}/quality/"
    d = session_client.post(
        base + "defects/",
        {"title": "连接失败", "description": "记录包含 timeout 及 connection refused 错误"},
        format="json",
    ).data
    return base, p, d


def test_rule_diagnostic_keeps_provenance_and_retry_request_is_idempotent(session_client, diagnostics, mocker):
    base, p, d = diagnostics
    mocker.patch("plane.quality.diagnostics.enqueue")
    request = {"request_id": str(uuid4()), "mode": "rules"}
    created = session_client.post(base + f"defects/{d['id']}/diagnostics/", request, format="json")
    assert created.status_code == 201, created.content
    repeated = session_client.post(base + f"defects/{d['id']}/diagnostics/", request, format="json")
    assert repeated.status_code == 200 and repeated.data["id"] == created.data["id"]
    from plane.quality.tasks import run_diagnostic

    run_diagnostic(created.data["id"])
    result = session_client.get(base + f"diagnostics/{created.data['id']}/")
    assert result.status_code == 200 and result.data["status"] == "completed", result.content
    assert result.data["result"]["method"] == "rules" and "模型" in result.data["result"]["notice"]
    assert result.data["result"]["findings"]


def test_cancelled_task_never_gets_completed_by_late_worker(session_client, diagnostics, mocker):
    base, p, d = diagnostics
    mocker.patch("plane.quality.diagnostics.enqueue")
    created = session_client.post(
        base + f"defects/{d['id']}/diagnostics/", {"request_id": str(uuid4()), "mode": "rules"}, format="json"
    ).data
    cancel = session_client.post(base + f"diagnostics/{created['id']}/", {"action": "cancel"}, format="json")
    assert cancel.status_code == 200 and cancel.data["status"] == "cancelled"
    from plane.quality.tasks import run_diagnostic

    run_diagnostic(created["id"])
    assert session_client.get(base + f"diagnostics/{created['id']}/").data["status"] == "cancelled"


def test_llm_mode_without_config_stays_explicitly_unconfigured(session_client, diagnostics, mocker):
    base, p, d = diagnostics
    mocker.patch("plane.knowledge.assistant.provider_config", return_value={"configured": False})
    created = session_client.post(
        base + f"defects/{d['id']}/diagnostics/", {"request_id": str(uuid4()), "mode": "llm"}, format="json"
    )
    assert created.status_code == 201 and created.data["status"] == "unconfigured", created.content
    assert created.data["result"] == {}


def test_background_task_rechecks_revoked_project_access(session_client, diagnostics, mocker, create_user):
    base, p, d = diagnostics
    mocker.patch("plane.quality.diagnostics.enqueue")
    job = session_client.post(
        base + f"defects/{d['id']}/diagnostics/", {"request_id": str(uuid4()), "mode": "rules"}, format="json"
    ).data
    ProjectMember.objects.filter(project=p, member=create_user).update(is_active=False)
    from plane.quality.tasks import run_diagnostic

    run_diagnostic(job["id"])
    from plane.quality.models import DiagnosticJob

    row = DiagnosticJob.objects.get(pk=job["id"])
    assert row.status == "failed" and row.error_code == "ACCESS_REVOKED"


def test_private_key_block_is_not_retained_in_diagnostic_sample():
    from plane.quality.tasks import redact

    value = redact("error\n-----BEGIN PRIVATE KEY-----\nsecret-body-data\n-----END PRIVATE KEY-----\ntimeout")
    assert "secret-body-data" not in value and "timeout" in value


def test_cancellation_during_worker_does_not_get_overwritten_by_completed_result(session_client, diagnostics, mocker):
    base, p, d = diagnostics
    mocker.patch("plane.quality.diagnostics.enqueue")
    job = session_client.post(
        base + f"defects/{d['id']}/diagnostics/", {"request_id": str(uuid4()), "mode": "rules"}, format="json"
    ).data
    from plane.quality.models import DiagnosticJob

    def cancelled_midflight(current):
        DiagnosticJob.objects.filter(pk=current.id).update(status="cancelled")
        return "timeout", [], []

    mocker.patch("plane.quality.tasks.inspect", side_effect=cancelled_midflight)
    from plane.quality.tasks import run_diagnostic

    run_diagnostic(job["id"])
    assert DiagnosticJob.objects.get(pk=job["id"]).status == "cancelled"


def test_feedback_is_persisted_with_reviewer_and_used_by_next_diagnostic(session_client, diagnostics, mocker):
    base, project, defect = diagnostics
    mocker.patch('plane.quality.diagnostics.enqueue')
    first = session_client.post(base + f"defects/{defect['id']}/diagnostics/", {'request_id': str(uuid4()), 'mode': 'rules'}, format='json').data
    from plane.quality.tasks import run_diagnostic
    from plane.quality.models import DiagnosticJob
    run_diagnostic(first['id'])
    response = session_client.post(base + f"diagnostics/{first['id']}/", {'action': 'feedback', 'feedback': 'unhelpful', 'note': '请区分正常验收与故障，并检查平台接收回执。'}, format='json')
    assert response.status_code == 200, response.data
    assert response.data['feedback'] == 'unhelpful'
    first_job = DiagnosticJob.objects.get(pk=first['id'])
    assert first_job.result['feedback_review']['actor_id']
    second = session_client.post(base + f"defects/{defect['id']}/diagnostics/", {'request_id': str(uuid4()), 'mode': 'rules'}, format='json').data
    from plane.quality.diagnostic_context import diagnostic_context
    references = diagnostic_context(DiagnosticJob.objects.get(pk=second['id']))
    assert references[0]['reference'] == 'PLATFORM-RECEIPT'
    assert references[1]['reference'] == f"REVIEW-{first['id']}"
    assert '接收回执' in references[1]['content']


def test_no_reference_to_review_from_another_project(session_client, diagnostics, mocker, create_user):
    base, project, defect = diagnostics
    from plane.quality.models import Defect, DiagnosticJob
    from plane.quality.diagnostic_context import diagnostic_context
    other = Project.objects.create(workspace=project.workspace, name='其他项目', identifier='OTHERDIAG')
    other_defect = Defect.objects.create(project=other, created_by=create_user, title=defect['title'], description=defect['description'])
    DiagnosticJob.objects.create(project=other, defect=other_defect, created_by=create_user, status='completed', mode='rules', request_id=uuid4(), feedback='helpful', feedback_note='不应泄露其他项目', result={'feedback_review': {'actor_id': str(create_user.id)}})
    mocker.patch('plane.quality.diagnostics.enqueue')
    current = session_client.post(base + f"defects/{defect['id']}/diagnostics/", {'request_id': str(uuid4()), 'mode': 'rules'}, format='json').data
    references = diagnostic_context(DiagnosticJob.objects.get(pk=current['id']))
    assert len(references) == 1


def test_repeat_verification_arrangement_keeps_actual_note(session_client, diagnostics):
    base, project, defect = diagnostics
    detail = session_client.get(base + f"defects/{defect['id']}/").data
    first = session_client.patch(base + f"defects/{defect['id']}/", {'verification_scope': 'functional', 'verification_scope_reason': '先检查启动按钮', 'expected_version': detail['edit_version']}, format='json')
    assert first.status_code == 200, first.data
    response = session_client.patch(base + f"defects/{defect['id']}/", {'verification_scope': 'functional', 'verification_scope_reason': '追加核对PICO与录制文件', 'expected_version': first.data['edit_version']}, format='json')
    assert response.status_code == 200, response.data
    assert '追加核对' in response.data['events'][0]['note']


def test_report_only_review_context_never_uses_other_collector(session_client, diagnostics, mocker, create_user):
    base, project, defect = diagnostics
    from plane.quality.models import DiagnosticJob, Defect
    from plane.quality.diagnostic_context import diagnostic_context
    other_user = type(create_user).objects.create_user(email='other-reviewer@example.test', username='other-reviewer')
    other_defect = Defect.objects.create(project=project, created_by=other_user, title=defect['title'], description=defect['description'])
    DiagnosticJob.objects.create(project=project, defect=other_defect, created_by=other_user, status='completed', mode='rules', request_id=uuid4(), feedback='unhelpful', feedback_note='另一采集员私有材料', result={'feedback_review': {'actor_id': str(create_user.id)}})
    mocker.patch('plane.quality.diagnostics.enqueue')
    current = session_client.post(base + f"defects/{defect['id']}/diagnostics/", {'request_id': str(uuid4()), 'mode': 'rules'}, format='json').data
    assert len(diagnostic_context(DiagnosticJob.objects.get(pk=current['id']), report_only=True)) == 1
