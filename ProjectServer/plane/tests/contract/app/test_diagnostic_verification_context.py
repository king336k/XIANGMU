"""Platform regression records are scoped evidence, never a hardware-health verdict."""

import json
from uuid import uuid4
import pytest
from plane.quality.diagnostic_context import diagnostic_context
from plane.quality.models import DiagnosticJob
from plane.tests.contract.app.test_defect_verification import configure, workflow
from plane.tests.contract.app.test_defect_verification import verification as verification

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def test_completed_manual_verification_is_available_to_next_diagnostic(session_client, verification):
    base, cases, defects, tester, manager = verification
    defect = defects[0]
    row = configure(session_client, base, defect, assignee_id=str(tester.id)).data["current"]
    session_client.force_authenticate(tester)
    response = session_client.post(
        base + f"defects/{defect.id}/verification/result/",
        {
            "expected_version": row["version"],
            "request_id": str(uuid4()),
            "result": "passed",
            "actual_result": "feedback files received; no robot movement tested",
            "step_results": [{"result": "passed", "actual": "feedback files received"}],
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    row = response.data["current"]
    row = workflow(session_client, base, defect, row, "submit").data["current"]
    session_client.force_authenticate(manager)
    response = workflow(session_client, base, defect, row, "accept")
    assert response.status_code == 200, response.data
    defect.refresh_from_db()
    job = DiagnosticJob.objects.create(
        project=defect.project, defect=defect, created_by=manager, mode="llm", request_id=uuid4()
    )
    refs = diagnostic_context(job)
    verified = next(r for r in refs if r["reference"] == "PLATFORM-VERIFICATION")
    assert "accepted" in verified["content"] and "closed" in verified["content"]
    assert "feedback files received; no robot movement tested" in verified["content"]
    assert "v2" in verified["content"]
    assert str(manager.id) in verified["content"] and str(tester.id) in verified["content"]
    assert all(r["reference"] != "PLATFORM-VERIFICATION" for r in diagnostic_context(job, report_only=True))


def test_other_defect_verification_is_never_used(session_client, verification):
    base, cases, defects, tester, manager = verification
    configure(session_client, base, defects[0])
    job = DiagnosticJob.objects.create(
        project=defects[1].project, defect=defects[1], created_by=manager, mode="llm", request_id=uuid4()
    )
    assert "PLATFORM-VERIFICATION" not in json.dumps(diagnostic_context(job))
