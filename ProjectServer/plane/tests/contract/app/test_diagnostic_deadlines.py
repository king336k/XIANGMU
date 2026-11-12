"""Exercise the deployed report-only polling route rather than the retired DAQ routes."""

from datetime import timedelta
from uuid import uuid4
import pytest
from django.utils import timezone
from plane.quality.models import DiagnosticJob, Defect
from plane.tests.contract.app import test_daq_reporting

call = test_daq_reporting.call
reporting_fixture = test_daq_reporting.reporting


@pytest.fixture
def report_scope(reporting_fixture):
    return reporting_fixture


pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.mark.parametrize(
    "status,age,error", [("running", 200, "DIAGNOSTIC_TIMEOUT"), ("queued", 901, "QUEUE_WAIT_TIMEOUT")]
)
def test_report_only_polling_expires_stalled_diagnosis(report_scope, status, age, error):
    project, user, payload, _ = report_scope
    response = call("/api/quality-auth/daq-reports/", {**payload, "hubProjectId": str(project.id)}, method="POST")
    assert response.status_code == 201, response.content
    defect = Defect.objects.get(pk=response.data["issueId"])
    old = timezone.now() - timedelta(seconds=age)
    job = DiagnosticJob.objects.create(
        project=project, defect=defect, created_by=user, mode="auto", status=status, request_id=uuid4()
    )
    DiagnosticJob.objects.filter(pk=job.pk).update(created_at=old, started_at=old if status == "running" else None)
    response = call(f"/api/quality-auth/daq-reports/{defect.id}/")
    assert response.status_code == 200, response.content
    job.refresh_from_db()
    assert job.status == "failed"
    assert job.error_code == error and job.completed_at
    assert response.data["source"]["diagnosticStatus"] == "failed"
