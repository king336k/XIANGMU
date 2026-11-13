from uuid import uuid4

import pytest

from plane.quality.models import Defect, DiagnosticJob
from plane.db.models import ProjectMember
from plane.tests.contract.app.test_diagnostic_severity import incident as incident
from plane.tests.contract.app.test_quality_filters import filtered_project as filtered_project

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def apply(job, result):
    from plane.quality.diagnostic_severity_apply import apply_severity

    return apply_severity(job, result)


def test_verified_grade_updates_defect_version_audit_and_result(incident):
    job, result, _ = incident("ERROR failure_class=raw_failed raw_status=failed")
    defect = job.defect
    defect.severity = ""
    defect.severity_origin = "pending"
    defect.save()
    before = defect.edit_version
    assessed = apply(job, result)
    defect.refresh_from_db()
    assert assessed["severity"] == "major"
    assert defect.severity == "major" and defect.severity_origin == "diagnostic"
    assert defect.severity_job_id == job.id and defect.edit_version == before + 1
    assert defect.events.filter(note__contains="严重程度").exists()
    apply(job, result)
    defect.refresh_from_db()
    assert defect.edit_version == before + 1


@pytest.mark.parametrize("guard", ["manual", "closed", "newer_job"])
def test_automatic_grade_preserves_manual_closed_and_newer_job(incident, guard):
    job, result, _ = incident("ERROR failure_class=raw_failed raw_status=failed")
    defect = job.defect
    defect.severity = "minor"
    defect.severity_origin = "manual" if guard == "manual" else "pending"
    if guard == "closed":
        defect.status = "closed"
    defect.save()
    if guard == "newer_job":
        DiagnosticJob.objects.create(
            project=job.project, defect=defect, created_by=job.created_by, mode="auto", request_id=uuid4()
        )
    before = defect.edit_version
    apply(job, result)
    defect.refresh_from_db()
    assert defect.severity == "minor" and defect.edit_version == before


def test_pending_filter_list_and_statistics_have_same_scope(session_client, filtered_project, create_user):
    base, project = filtered_project
    pending = Defect.objects.create(project=project, title="待评估", severity="", severity_origin="pending")
    Defect.objects.create(project=project, title="人工严重", severity="major")
    response = session_client.get(base + "quality/defects/?severity=unassessed")
    assert response.status_code == 200, response.content
    assert [x["id"] for x in response.data["results"]] == [str(pending.id)]
    stats = session_client.get(base + "quality/defect-statistics/?severity=unassessed")
    assert stats.status_code == 200 and stats.data["total"] == 1
    assert stats.data["by_severity"] == [{"value": "", "count": 1}]


def test_manual_same_grade_is_protected_from_late_automatic_update(session_client, filtered_project):
    base, project = filtered_project
    defect = Defect.objects.create(project=project, title="人工确认", severity="minor", severity_origin="diagnostic")
    response = session_client.patch(
        base + f"quality/defects/{defect.id}/",
        {"severity": "minor", "expected_version": defect.edit_version},
        format="json",
    )
    assert response.status_code == 200, response.content
    defect.refresh_from_db()
    assert defect.severity_origin == "manual" and defect.severity_job_id is None


def test_selecting_pending_allows_the_next_diagnostic_to_assess(session_client, filtered_project):
    base, project = filtered_project
    defect = Defect.objects.create(project=project, title="重新评估", severity="minor", severity_origin="manual")
    response = session_client.patch(
        base + f"quality/defects/{defect.id}/",
        {"severity": "", "expected_version": defect.edit_version}, format="json",
    )
    assert response.status_code == 200, response.content
    defect.refresh_from_db()
    assert defect.severity == "" and defect.severity_origin == "pending" and defect.severity_job_id is None


@pytest.mark.parametrize("manual_during_analysis", [False, True])
def test_task_applies_verified_grade_and_preserves_concurrent_manual_choice(incident, mocker, manual_during_analysis):
    from plane.quality.tasks import run_diagnostic

    job, result, _ = incident("ERROR failure_class=raw_failed raw_status=failed")
    ProjectMember.objects.create(project=job.project, member=job.created_by, role=20)
    Defect.objects.filter(pk=job.defect_id).update(severity="", severity_origin="pending")
    job.status, job.mode = "queued", "llm"
    job.save()
    mocker.patch("plane.quality.tasks.inspect", return_value=(result["sources"][0]["excerpt"], result["sources"], []))
    mocker.patch("plane.knowledge.assistant.provider_config", return_value={"configured": True})
    mocker.patch("plane.quality.tasks.search", return_value=[])
    mocker.patch("plane.quality.tasks.assistant.reference_payload", return_value=[])
    mocker.patch("plane.quality.diagnostic_context.diagnostic_context", return_value=[])

    def model_answer(*args):
        if manual_during_analysis:
            Defect.objects.filter(pk=job.defect_id).update(severity="minor", severity_origin="manual")
        return {**result, "answer": "原始写入完整性失败。"}

    mocker.patch("plane.quality.tasks.analyze_diagnostic", side_effect=model_answer)
    run_diagnostic(job.id)
    job.refresh_from_db()
    job.defect.refresh_from_db()
    assert job.result["model_status"] == "completed"
    assert job.result["severity_assessment"]["severity"] == "major"
    assert job.result["severity_proposal"]["severity"] == "major"
    assert job.defect.severity == ("minor" if manual_during_analysis else "major")
    assert job.defect.severity_origin == ("manual" if manual_during_analysis else "diagnostic")
