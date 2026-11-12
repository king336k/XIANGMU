"""Only the execution actually used to close a functional defect is exposed."""

from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from plane.db.models import Project, User
from plane.quality.models import (
    CaseRevision,
    Defect,
    DefectEvent,
    PlanItem,
    TestCase as QualityCase,
    TestExecution as QualityExecution,
    TestPlan as QualityPlan,
)
from plane.tests.contract.app import test_daq_reporting
from plane.tests.contract.app.test_daq_reporting import call

reporting = test_daq_reporting.reporting

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def functional_report(reporting):
    project, user, payload, state = reporting
    created = call("/api/quality-auth/daq-reports/", {**payload, "hubProjectId": str(project.id)}, "POST")
    assert created.status_code == 201
    defect = Defect.objects.get(pk=created.data["issueId"])
    tester = User.objects.create(
        username="functional-tester", email="functional@test.invalid", display_name="功能测试员"
    )
    case = QualityCase.objects.create(project=project, title="内部功能用例", steps=[])
    revision = CaseRevision.objects.create(project=project, case=case, version=1, title=case.title, snapshot={})
    plan = QualityPlan.objects.create(
        project=project, name="内部功能计划", build="fixed-v1", environment="local", status="completed"
    )
    item = PlanItem.objects.create(project=project, plan=plan, case=case, revision=revision)
    defect.case = case
    defect.fixed_build = "fixed-v1"
    defect.verification_scope = "functional"
    defect.resolved_at = timezone.now() - timedelta(minutes=1)
    DefectEvent.objects.create(
        project=project, defect=defect, created_by=user, previous_status="in_progress", status="resolved"
    )
    execution = QualityExecution.objects.create(
        project=project,
        item=item,
        created_by=tester,
        request_id=uuid4(),
        result="passed",
        actual_result="private-functional-actual",
        evidence="private-functional-evidence",
    )
    defect.regression_execution = execution
    defect.status = "closed"
    defect.save()
    DefectEvent.objects.create(
        project=project, defect=defect, created_by=user, previous_status="resolved", status="closed"
    )
    return project, defect, case, revision, plan, item, execution


def timeline(defect):
    response = call(f"/api/quality-auth/daq-reports/{defect.id}/")
    assert response.status_code == 200, response.content
    assert b"private-functional-" not in response.content
    return response.data["timeline"]


def test_functional_closure_shows_its_final_testers_action_only(functional_report):
    project, defect, case, revision, plan, item, execution = functional_report
    other = QualityExecution.objects.create(
        project=project, item=item, created_by=execution.created_by, request_id=uuid4(), result="passed"
    )
    rows = timeline(defect)
    results = [row for row in rows if row["actor"] == "功能测试员"]
    assert len(results) == 1
    assert results[0]["id"] == "execution:" + str(execution.id)
    assert results[0]["action"] == "回归通过"
    assert results[0]["status"] == "resolved"
    assert all(row["id"] != "execution:" + str(other.id) for row in rows)
    assert rows[-1]["action"] == "验收关闭"


@pytest.mark.parametrize(
    "boundary",
    [
        "execution_project",
        "item_project",
        "plan_project",
        "case_project",
        "different_case",
        "different_revision_case",
        "build",
        "old_execution",
        "failed",
        "unclosed",
    ],
)
def test_functional_timeline_rejects_corrupt_or_unrelated_final_execution(functional_report, boundary):
    project, defect, case, revision, plan, item, execution = functional_report
    other = Project.objects.create(workspace=project.workspace, name="other", identifier="FUNCOTHER")
    if boundary == "execution_project":
        QualityExecution.objects.filter(pk=execution.id).update(project=other)
    elif boundary == "item_project":
        PlanItem.objects.filter(pk=item.id).update(project=other)
    elif boundary == "plan_project":
        QualityPlan.objects.filter(pk=plan.id).update(project=other)
    elif boundary == "case_project":
        QualityCase.objects.filter(pk=case.id).update(project=other)
    elif boundary == "different_case":
        replacement = QualityCase.objects.create(project=project, title="另一个用例", steps=[])
        Defect.objects.filter(pk=defect.id).update(case=replacement)
    elif boundary == "different_revision_case":
        replacement = QualityCase.objects.create(project=project, title="另一个版本用例", steps=[])
        CaseRevision.objects.filter(pk=revision.id).update(case=replacement)
    elif boundary == "build":
        QualityPlan.objects.filter(pk=plan.id).update(build="another-fix")
    elif boundary == "old_execution":
        QualityExecution.objects.filter(pk=execution.id).update(created_at=defect.resolved_at - timedelta(seconds=1))
    elif boundary == "failed":
        QualityExecution.objects.filter(pk=execution.id).update(result="failed")
    else:
        Defect.objects.filter(pk=defect.id).update(status="resolved")
    assert not any(row["id"] == "execution:" + str(execution.id) for row in timeline(defect))
