"""Only signed, currently authorized DAQ incidents can start automatic models."""

from uuid import uuid4
import pytest
from plane.db.models import Project, ProjectMember
from plane.quality.models import Defect, DiagnosticJob, SourceLink

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def incident(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="启动失败", identifier="INCIDENTDIAG")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    defect = Defect.objects.create(project=project, created_by=create_user, title="硬件初始化失败")
    link = SourceLink.objects.create(
        project=project,
        defect=defect,
        created_by=create_user,
        source_system="ENGRAM_DAQ",
        source_instance="isolated",
        record_type="daq_incident",
        record_id="1:" + str(uuid4()),
    )
    return defect, link


def test_signed_incident_material_upload_can_enqueue(incident, create_user, mocker):
    from plane.quality.diagnostics import schedule_automatic

    defect, link = incident
    mocker.patch("plane.quality.daq_incidents.trusted_incident", return_value=link)
    mocker.patch("plane.quality.daq_incidents.verify_incident_authority")
    mocker.patch("plane.quality.diagnostics.enqueue")
    job = schedule_automatic(defect, create_user, "materials_verified")
    assert job and job.status == "queued"


def test_unsigned_source_strings_do_not_enable_automatic_models(incident, create_user, mocker):
    from plane.quality.diagnostics import schedule_automatic

    defect, _ = incident
    mocker.patch("plane.quality.daq_incidents.trusted_incident", return_value=None)
    assert schedule_automatic(defect, create_user, "materials_verified") is None


@pytest.mark.parametrize("revoked", [False, True])
def test_incident_worker_rechecks_authority_before_model(incident, create_user, mocker, revoked):
    from plane.quality.tasks import run_diagnostic

    defect, link = incident
    mocker.patch("plane.quality.daq_incidents.trusted_incident", return_value=link)
    authority = mocker.patch("plane.quality.daq_incidents.verify_incident_authority")
    if revoked:
        authority.side_effect = PermissionError("synthetic revocation")
    job = DiagnosticJob.objects.create(
        project=defect.project,
        defect=defect,
        created_by=create_user,
        mode="auto",
        request_id=uuid4(),
        result={"trigger": "materials_verified", "input": {"files": [str(uuid4())]}},
    )
    mocker.patch(
        "plane.quality.tasks.inspect",
        return_value=(
            "ERROR connection refused",
            [{"file_id": str(uuid4()), "name": "startup.log", "read_bytes": 10}],
            [],
        ),
    )
    mocker.patch("plane.knowledge.assistant.provider_config", return_value={"configured": True})
    model = mocker.patch("plane.quality.tasks.analyze_diagnostic", return_value={"answer": "等待核对", "citations": []})
    run_diagnostic(job.id)
    job.refresh_from_db()
    if revoked:
        assert job.status == "failed" and job.error_code == "ACCESS_REVOKED"
        model.assert_not_called()
    else:
        assert job.status == "completed" and job.result["model_status"] == "completed"
        model.assert_called_once()
    authority.assert_called_with(link)
    assert authority.call_count == (1 if revoked else 2)


def test_incident_revoked_during_model_does_not_publish_late_result(incident, create_user, mocker):
    from plane.quality.tasks import run_diagnostic

    defect, link = incident
    mocker.patch("plane.quality.daq_incidents.trusted_incident", return_value=link)
    mocker.patch(
        "plane.quality.daq_incidents.verify_incident_authority",
        side_effect=[{}, PermissionError("synthetic revocation")],
    )
    job = DiagnosticJob.objects.create(
        project=defect.project,
        defect=defect,
        created_by=create_user,
        mode="auto",
        request_id=uuid4(),
        result={"trigger": "materials_verified", "input": {"files": [str(uuid4())]}},
    )
    mocker.patch(
        "plane.quality.tasks.inspect",
        return_value=(
            "ERROR connection refused",
            [{"file_id": str(uuid4()), "name": "startup.log", "read_bytes": 10}],
            [],
        ),
    )
    mocker.patch("plane.knowledge.assistant.provider_config", return_value={"configured": True})
    mocker.patch(
        "plane.quality.tasks.analyze_diagnostic", return_value={"answer": "late provider report", "citations": []}
    )
    run_diagnostic(job.id)
    job.refresh_from_db()
    assert job.status == "failed" and job.error_code == "ACCESS_REVOKED"
    assert job.result == {}
