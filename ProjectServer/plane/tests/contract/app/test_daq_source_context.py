"""Only signed DAQ event context is displayed as a verified upstream project/task."""

import pytest
from plane.quality.models import SourceLink
from plane.quality.sources import SourceSerializer
from plane.tests.contract.app.test_daq_incidents import incident as incident
from plane.tests.contract.app.test_daq_reporting import reporting as reporting, call

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def test_source_card_receives_signed_project_task_context_and_optional_reported_reference(reporting):
    destination, collector, payload, state = reporting
    state["context"].update(projectName="生产采集项目", taskName="机械臂抓取任务")
    response = call(
        "/api/quality-auth/daq-reports/",
        {
            **payload,
            "hubProjectId": str(destination.id),
            "category": "DataAnomaly",
            "sourceReference": "本地未上传Session",
        },
        "POST",
    )
    assert response.status_code == 201, response.content
    link = SourceLink.objects.get(defect_id=response.data["issueId"])
    context = SourceSerializer(link).data.get("source_context")
    assert context == {
        "platformProjectId": 9,
        "platformProjectName": "生产采集项目",
        "platformTaskId": 24,
        "platformTaskName": "机械臂抓取任务",
        "sourceReference": "本地未上传Session",
    }
    assert link.package_id == ""


def test_source_card_ignores_unsigned_or_mutated_event_context(reporting):
    destination, collector, payload, state = reporting
    created = call("/api/quality-auth/daq-reports/", {**payload, "hubProjectId": str(destination.id)}, "POST")
    assert created.status_code == 201
    link = SourceLink.objects.get(defect_id=created.data["issueId"])
    link.record_id = "fake-event-id"
    link.save(update_fields=["record_id"])
    assert SourceSerializer(link).data.get("source_context") is None
    ordinary = SourceLink.objects.create(
        project=destination,
        created_by=collector,
        defect=link.defect,
        source_system="manual",
        source_instance="local",
        record_type="session",
        record_id="user-typed-reference",
        task_id="24",
        package_id="user-typed-package",
    )
    assert SourceSerializer(ordinary).data.get("source_context") is None
