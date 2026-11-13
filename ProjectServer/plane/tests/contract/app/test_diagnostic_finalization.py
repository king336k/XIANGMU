"""Read-only product review reproductions; copied source only."""

from uuid import uuid4
import pytest
from plane.db.models import Project, ProjectMember, User, WorkspaceMember, Notification
from plane.quality.models import Defect, DiagnosticJob, BusinessRole, ProjectRolePolicy
from plane.quality.tasks import run_diagnostic
from plane.tests.contract.app.test_defect_verification import configure
from plane.tests.contract.app.test_defect_verification import verification as verification
from plane.tests.contract.app.test_module_owners import bind, ready_job, route
from plane.tests.contract.app.test_module_owners import routing as routing

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def diagnostic(workspace, create_user, mocker):
    project = Project.objects.create(workspace=workspace, name="Review", identifier="REVIEW")
    ProjectMember.objects.create(project=project, member=create_user, role=15)
    ProjectRolePolicy.objects.create(project=project, enabled=True)
    BusinessRole.objects.create(project=project, user=create_user, role="TECHNICIAN")
    defect = Defect.objects.create(project=project, created_by=create_user, assignee=create_user, title="Review")
    job = DiagnosticJob.objects.create(
        project=project,
        defect=defect,
        created_by=create_user,
        request_id=uuid4(),
        mode="llm",
        result={"trigger": "manual"},
    )
    mocker.patch("plane.quality.tasks.inspect", return_value=("observed error", [], []))
    mocker.patch("plane.knowledge.assistant.provider_config", return_value={"configured": True})
    mocker.patch("plane.quality.tasks.search", return_value=[])
    mocker.patch("plane.quality.tasks.assistant.reference_payload", return_value=[])
    mocker.patch("plane.quality.diagnostic_context.diagnostic_context", return_value=[])
    mocker.patch("plane.quality.tasks.run_diagnostic.apply_async")
    return project, job


def test_preprocessing_timeout_requeues(workspace, create_user, mocker):
    project, job = diagnostic(workspace, create_user, mocker)
    mocker.patch("plane.quality.tasks.time.monotonic", side_effect=[100, 121, 122])
    run_diagnostic(job.id)
    job.refresh_from_db()
    assert job.status == "queued", (job.status, job.result)
    assert job.result["model_error_code"] == "MODEL_TIMEOUT"


def test_role_revoked_during_provider_call_does_not_publish(workspace, create_user, mocker):
    project, job = diagnostic(workspace, create_user, mocker)

    def answer(*args):
        BusinessRole.objects.filter(project=project, user=create_user).update(role="REGRESSION_TESTER")
        return {"answer": "late answer", "citations": []}

    mocker.patch("plane.quality.tasks.analyze_diagnostic", side_effect=answer)
    run_diagnostic(job.id)
    job.refresh_from_db()
    assert job.status == "failed" and job.error_code == "ACCESS_REVOKED", (job.status, job.error_code, job.result)
    assert "answer" not in job.result


def test_assignee_changed_during_provider_call_does_not_publish(workspace, create_user, mocker):
    project, job = diagnostic(workspace, create_user, mocker)

    def answer(*args):
        Defect.objects.filter(pk=job.defect_id).update(assignee=None)
        return {"answer": "late answer", "citations": []}

    mocker.patch("plane.quality.tasks.analyze_diagnostic", side_effect=answer)
    run_diagnostic(job.id)
    job.refresh_from_db()
    assert job.status == "failed" and job.error_code == "ACCESS_REVOKED"
    assert "answer" not in job.result


def test_same_config_reassignment_notifies_old_tester(session_client, verification):
    base, cases, defects, tester, manager = verification
    defect = defects[0]
    row = configure(session_client, base, defect, assignee_id=str(tester.id)).data["current"]
    second = User.objects.create(username="review-second", email="review-second@test.invalid")
    WorkspaceMember.objects.create(workspace=defect.project.workspace, member=second, role=15)
    ProjectMember.objects.create(project=defect.project, member=second, role=15)
    Notification.objects.all().delete()
    changed = configure(session_client, base, defect, assignee_id=str(second.id))
    assert changed.status_code == 200, changed.content
    assert changed.data["current"]["id"] == row["id"]
    assert Notification.objects.filter(receiver=second).exists()
    assert Notification.objects.filter(receiver=tester).exists(), "Old tester lost task without reassignment notice"


def test_unproven_initial_module_returns_to_one_triager(routing):
    from plane.quality.module_routing import initial_assign

    assert bind(routing).status_code == 200
    job = ready_job(routing, "INFO all observed components healthy", "问题范围：daq")
    initial = initial_assign(job.defect, routing[3])
    assert initial.assignment_origin == "initial" and initial.assignee_id == routing[4][0].id
    defect = route(job)
    assert defect.assignment_origin == "triage", (defect.assignment_origin, defect.assignment_reason)
    assert defect.assignee_id == routing[3].id


def test_cancel_during_provider_call_does_not_publish_or_retry(workspace, create_user, mocker):
    project, job = diagnostic(workspace, create_user, mocker)

    def answer(*args):
        DiagnosticJob.objects.filter(pk=job.pk).update(status="cancelled")
        raise TimeoutError()

    mocker.patch("plane.quality.tasks.analyze_diagnostic", side_effect=answer)
    dispatch = mocker.patch("plane.quality.tasks.run_diagnostic.apply_async")
    run_diagnostic(job.id)
    job.refresh_from_db()
    assert job.status == "cancelled"
    assert "answer" not in job.result and "retry" not in job.result
    dispatch.assert_not_called()
