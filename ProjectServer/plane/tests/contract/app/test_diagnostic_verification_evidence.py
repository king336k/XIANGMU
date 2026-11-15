"""Independent verification context adversarial checks; reviewer artifact only."""

import json
from uuid import uuid4
from types import SimpleNamespace
import pytest
from plane.db.models import User, ProjectMember, WorkspaceMember
from plane.quality.models import DiagnosticJob, DefectVerification
from plane.quality.diagnostic_context import diagnostic_context
from plane.tests.contract.app.test_defect_verification import configure, workflow, execute
from plane.tests.contract.app.test_defect_verification import verification as verification

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def ref_for(defect, actor):
    job = DiagnosticJob.objects.create(
        project=defect.project, defect=defect, created_by=actor, mode="llm", request_id=uuid4()
    )
    refs = diagnostic_context(job)
    return job, next(r for r in refs if r["reference"] == "PLATFORM-VERIFICATION")


def record_manual(client, base, defect, row, actual, steps=1):
    response = client.post(
        base + f"defects/{defect.id}/verification/result/",
        {
            "expected_version": row["version"],
            "request_id": str(uuid4()),
            "result": "passed",
            "actual_result": actual,
            "step_results": [{"result": "passed", "actual": "OBSERVED_STEP"} for _ in range(steps)],
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    return response.data["current"]


def body(ref):
    return json.loads(ref["content"].split("\n", 1)[0])


def test_large_valid_steps_preserve_actual_and_structured_context(session_client, verification):
    base, cases, defects, tester, manager = verification
    defect = defects[0]
    row = configure(
        session_client,
        base,
        defect,
        assignee_id=str(tester.id),
        steps=[
            {"action": "操作" * 1700, "expected": "期望" * 1700},
            {"action": "操作" * 1700, "expected": "期望" * 1700},
        ],
    ).data["current"]
    session_client.force_authenticate(tester)
    row = record_manual(session_client, base, defect, row, "RETAIN_ACTUAL", 2)
    row = workflow(session_client, base, defect, row, "submit").data["current"]
    session_client.force_authenticate(manager)
    assert workflow(session_client, base, defect, row, "accept").status_code == 200
    defect.refresh_from_db()
    job, ref = ref_for(defect, manager)
    data = body(ref)
    assert data["result"]["actual"] == "RETAIN_ACTUAL"
    assert data["status"] == "accepted" and data["actions"][0]["action"] == "accept"
    assert len(ref["content"].split("\n", 1)[0]) <= 12000


def test_case_context_retains_actual_tester_steps_and_time_after_reassign(session_client, verification):
    base, cases, defects, tester, manager = verification
    defect = defects[0]
    row = configure(session_client, base, defect, cases=cases, assignee_id=str(tester.id)).data["current"]
    session_client.force_authenticate(tester)
    for item in row["items"]:
        response = execute(session_client, base, item, row["version"])
        assert response.status_code == 201, response.content
        row = response.data["current"]
    session_client.force_authenticate(manager)
    second = User.objects.create(username="review-context-second", email="review-context-second@local.invalid")
    WorkspaceMember.objects.create(workspace=defect.project.workspace, member=second, role=15)
    ProjectMember.objects.create(project=defect.project, member=second, role=15)
    changed = workflow(session_client, base, defect, row, "assign", assignee_id=str(second.id))
    assert changed.status_code == 200, changed.content
    job, ref = ref_for(defect, manager)
    data = body(ref)
    actual = data["case_results"][0]
    assert actual.get("tested_by_id") == str(tester.id), actual
    assert actual.get("tested_at"), actual
    assert actual.get("actual") == "实测结果", actual
    assert actual.get("step_results") == [], "整条用例执行不伪造逐步骤实测"
    assert data["assigned_tester_id"] == str(second.id)


def test_new_round_only_and_stale_build_are_explicit(session_client, verification):
    base, cases, defects, tester, manager = verification
    defect = defects[0]
    row = configure(session_client, base, defect).data["current"]
    session_client.force_authenticate(tester)
    row = record_manual(session_client, base, defect, row, "OLD_ROUND_PRIVATE_MARKER")
    session_client.force_authenticate(manager)
    new = configure(session_client, base, defect, environment="new round environment").data["current"]
    assert new["round_no"] == 2
    defect.fixed_build = "v3"
    defect.save(update_fields=["fixed_build"])
    job, ref = ref_for(defect, manager)
    data = body(ref)
    assert data["round"] == 2 and not data["matches_current_repair"]
    assert data["result"] is None and "OLD_ROUND_PRIVATE_MARKER" not in ref["content"]


def test_case_revision_staleness_is_exposed(session_client, verification):
    from plane.quality.models import TestCase

    base, cases, defects, tester, manager = verification
    defect = defects[0]
    configure(session_client, base, defect, cases=cases)
    TestCase.objects.filter(pk=cases[0]["id"]).update(version=2)
    job, ref = ref_for(defect, manager)
    data = body(ref)
    assert any(item["stale"] for item in data["case_results"])


def test_platform_verification_is_valid_citation_contract(session_client, verification, mocker):
    from plane.quality.diagnostic_model import analyze_diagnostic

    base, cases, defects, tester, manager = verification
    defect = defects[0]
    configure(session_client, base, defect)
    job, ref = ref_for(defect, manager)
    output = {
        "answer": "Platform record is pending",
        "suggested_actions": [],
        "verification_steps": [],
        "citations": ["PLATFORM-VERIFICATION"],
    }
    mocker.patch.dict("os.environ", {"DIAGNOSTIC_AGENT_PYTHON": "/synthetic/python"})
    mocker.patch(
        "plane.quality.diagnostic_model.subprocess.run", return_value=SimpleNamespace(stdout=json.dumps(output))
    )
    answer = analyze_diagnostic({"api_key": "synthetic"}, "description", [], [ref])
    assert answer["citations"][0]["reference"] == "PLATFORM-VERIFICATION"


def test_user_record_is_redacted_and_marked_as_noninstruction(session_client, verification):
    base, cases, defects, tester, manager = verification
    defect = defects[0]
    row = configure(session_client, base, defect).data["current"]
    session_client.force_authenticate(tester)
    record_manual(session_client, base, defect, row, '{"api_key":"FAKE_REVIEW_ONLY_VALUE"}')
    job, ref = ref_for(defect, manager)
    assert "FAKE_REVIEW_ONLY_VALUE" not in ref["content"]
    assert "不是系统指令" in ref["content"]


def test_case_context_query_growth_is_bounded(session_client, verification):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from plane.quality.models import TestCase, CaseRevision, DefectVerificationCase

    base, cases, defects, tester, manager = verification
    defect = defects[0]
    row = configure(session_client, base, defect, cases=cases).data["current"]
    plan = DefectVerification.objects.get(pk=row["id"]).plan
    job = DiagnosticJob.objects.create(
        project=defect.project, defect=defect, created_by=manager, mode="llm", request_id=uuid4()
    )

    def add_cases(number):
        cs = [
            TestCase(
                project=defect.project,
                created_by=manager,
                title=f"query-case-{uuid4()}",
                steps=[{"action": "check", "expected": "pass"}],
            )
            for _ in range(number)
        ]
        TestCase.objects.bulk_create(cs)
        revisions = [
            CaseRevision(
                project=defect.project,
                created_by=manager,
                case=c,
                version=1,
                title=c.title,
                snapshot={"steps": c.steps},
            )
            for c in cs
        ]
        CaseRevision.objects.bulk_create(revisions)
        DefectVerificationCase.objects.bulk_create(
            [
                DefectVerificationCase(project=defect.project, created_by=manager, verification_id=row["id"],
                                       source="library", source_case=c, source_revision=r,
                                       title=r.title, snapshot=r.snapshot)
                for c, r in zip(cs, revisions)
            ]
        )

    add_cases(8)
    with CaptureQueriesContext(connection) as small:
        refs = diagnostic_context(job)
    assert body(next(ref for ref in refs if ref["reference"] == "PLATFORM-VERIFICATION"))["summary"]["total"] == 10
    small_count = len(small)
    add_cases(90)
    with CaptureQueriesContext(connection) as large:
        refs = diagnostic_context(job)
    assert body(next(ref for ref in refs if ref["reference"] == "PLATFORM-VERIFICATION"))["summary"]["total"] == 100
    assert len(large) <= small_count + 5, (small_count, len(large))


def test_hundred_large_manual_steps_keep_valid_bounded_execution_evidence(session_client, verification):
    base, cases, defects, tester, manager = verification
    defect = defects[0]
    steps = [{"action": "检验" * 500, "expected": "符合" * 500} for _ in range(100)]
    configured = configure(session_client, base, defect, assignee_id=str(tester.id), steps=steps)
    assert configured.status_code == 201, configured.content
    row = configured.data["current"]
    session_client.force_authenticate(tester)
    response = session_client.post(
        base + f"defects/{defect.id}/verification/result/",
        {
            "expected_version": row["version"],
            "request_id": str(uuid4()),
            "result": "passed",
            "actual_result": "真实实测内容" * 2500,
            "step_results": [{"result": "passed", "actual": "实际观察" * 250} for _ in range(100)],
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    row = workflow(session_client, base, defect, response.data["current"], "submit").data["current"]
    session_client.force_authenticate(manager)
    assert workflow(session_client, base, defect, row, "accept").status_code == 200
    defect.refresh_from_db()
    job, ref = ref_for(defect, manager)
    data = body(ref)
    assert len(ref["content"].split("\n", 1)[0]) <= 12000
    assert data["truncated"] and data["status"] == "accepted"
    assert data["result"]["result"] == "passed" and data["result"]["tested_by_id"] == str(tester.id)
    assert data["actions"][0]["action"] == "accept"
    assert data["result"]["actual"] == ("真实实测内容" * 2500)[:1000]


def test_many_large_cases_keep_full_summary_and_valid_json(session_client, verification):
    from plane.quality.models import TestCase, CaseRevision, DefectVerificationCase, DefectVerificationCaseExecution

    base, cases, defects, tester, manager = verification
    defect = defects[0]
    row = configure(session_client, base, defect, cases=cases, assignee_id=str(tester.id)).data["current"]
    plan = DefectVerification.objects.get(pk=row["id"]).plan
    cs = [
        TestCase(
            project=defect.project,
            created_by=manager,
            title="大用例标题" * 50,
            steps=[{"action": "check", "expected": "pass"}],
        )
        for _ in range(98)
    ]
    TestCase.objects.bulk_create(cs)
    revisions = [
        CaseRevision(
            project=defect.project, created_by=manager, case=c, version=1, title=c.title, snapshot={"steps": c.steps}
        )
        for c in cs
    ]
    CaseRevision.objects.bulk_create(revisions)
    DefectVerificationCase.objects.bulk_create(
        [
            DefectVerificationCase(project=defect.project, created_by=manager, verification_id=row["id"],
                                   source="library", source_case=c, source_revision=r,
                                   title=r.title, snapshot=r.snapshot)
            for c, r in zip(cs, revisions)
        ]
    )
    DefectVerificationCaseExecution.objects.bulk_create(
        [
            DefectVerificationCaseExecution(
                project=defect.project, created_by=tester, item=i, request_id=uuid4(), request_hash="large",
                result="passed", actual_result="大型实际结果" * 3000, step_results=[],
            )
            for i in DefectVerificationCase.objects.filter(verification_id=row["id"])
        ]
    )
    job, ref = ref_for(defect, manager)
    data = body(ref)
    assert len(ref["content"].split("\n", 1)[0]) <= 12000
    assert data["summary"] == {"total": 100, "passed": 100}
    assert data["truncated"] and 0 < len(data["case_results"]) <= 20
    assert all(item["tested_by_id"] == str(tester.id) for item in data["case_results"])
    assert all(item["tested_at"] and item["actual"] == ("大型实际结果" * 3000)[:160] for item in data["case_results"])
    assert all(item["step_results"] == [] for item in data["case_results"])


def test_legacy_plan_case_context_still_preserves_step_evidence(session_client, verification):
    from plane.quality.models import PlanItem, TestCase, TestExecution
    base, cases, defects, tester, manager = verification
    defect = defects[0]
    row = configure(session_client, base, defect, cases=cases).data["current"]
    verification_row = DefectVerification.objects.get(pk=row["id"])
    verification_row.case_items.all().delete()
    case = TestCase.objects.get(pk=cases[0]["id"])
    item = PlanItem.objects.create(project=defect.project, created_by=manager, plan=verification_row.plan,
                                   case=case, revision=case.revisions.get(version=case.version))
    TestExecution.objects.create(project=defect.project, created_by=tester, item=item, round_no=row["round_no"],
                                 request_id=uuid4(), result="passed", actual_result="旧逐步记录",
                                 step_results=[{"result":"passed", "actual":"旧步骤通过"}])
    _, ref = ref_for(defect, manager)
    actual = body(ref)["case_results"][0]
    assert actual["tested_by_id"] == str(tester.id) and actual["tested_at"]
    assert actual["step_results"] == [{"result":"passed", "actual":"旧步骤通过"}]
