"""Cards, owner totals and paged records share the same execution sources."""
from uuid import uuid4
import pytest
from django.utils import timezone
from plane.db.models import Project, ProjectMember
from plane.quality.models import (
    TestCase, CaseRevision, TestPlan, PlanItem, TestExecution, Defect,
    DefectVerification, DefectVerificationCase, DefectVerificationCaseExecution,
)

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def mixed_executions(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="统一执行统计", identifier="UEXEC")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    case = TestCase.objects.create(project=project, created_by=create_user, title="复用定义", steps=[])
    revision = CaseRevision.objects.create(project=project, created_by=create_user, case=case, version=1, title=case.title, snapshot={"steps": []})
    ordinary = TestPlan.objects.create(project=project, created_by=create_user, name="普通计划", build="v2", environment="local", assignee=create_user)
    old_item = PlanItem.objects.create(project=project, created_by=create_user, plan=ordinary, case=case, revision=revision)
    old = TestExecution.objects.create(project=project, created_by=create_user, item=old_item, request_id=uuid4(), result="passed", actual_result="普通通过")
    defect = Defect.objects.create(project=project, created_by=create_user, title="轮次缺陷", status="resolved", fixed_build="v2", resolved_at=timezone.now())
    plan = TestPlan.objects.create(project=project, created_by=create_user, name="缺陷计划", build="v2", environment="local", assignee=create_user, status="running")
    round_ = DefectVerification.objects.create(project=project, created_by=create_user, defect=defect, plan=plan, round_no=1, mode="cases", status="testing", fixed_build="v2", environment="local", resolved_at=defect.resolved_at, request_id=uuid4(), request_hash="round")
    frozen = DefectVerificationCase.objects.create(project=project, created_by=create_user, verification=round_, source="library", source_case=case, source_revision=revision, title=revision.title, snapshot=revision.snapshot)
    DefectVerificationCase.objects.create(project=project, created_by=create_user, verification=round_, source="round", title="待执行临时用例", snapshot={"steps": []})
    new = DefectVerificationCaseExecution.objects.create(project=project, created_by=create_user, item=frozen, request_id=uuid4(), request_hash="new", result="passed", actual_result="轮次通过")
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/"
    return project, base, create_user, case, old, new, frozen, round_


def test_current_cards_history_records_and_owner_drilldowns_include_both_sources(session_client, mixed_executions):
    project, base, actor, _, old, new, _, round_ = mixed_executions
    report = session_client.get(base + "report/")
    assert report.status_code == 200
    assert report.data["summary"]["total"] == 3
    assert report.data["summary"]["passed"] == 2 and report.data["summary"]["pending"] == 1
    assert report.data["execution_count"] == 2
    page = session_client.get(base + "executions/", {"per_page": 1})
    assert page.status_code == 200 and page.data["count"] == 2, page.content
    other = session_client.get(base + "executions/", {"per_page": 1, "page": 2})
    assert {str(row["id"]) for row in page.data["results"] + other.data["results"]} == {str(old.id), str(new.id)}
    current = session_client.get(base + "executions/", {"current_only": "true", "result": "passed"})
    assert current.data["count"] == report.data["summary"]["passed"]
    row = next(x for x in current.data["results"] if str(x["id"]) == str(new.id))
    assert row["defect_id"] == str(round_.defect_id) and row["plan_id"] == str(round_.plan_id)
    for suffix, expected in [("total", 3), ("passed", 2), ("pending", 1)]:
        owners = session_client.get(base + "owner-statistics/", {"source": "quality", "metric": "summary_" + suffix})
        assert owners.status_code == 200 and owners.data["total"] == expected, owners.content
        details = session_client.get(base + "owner-statistics/", {"source": "quality", "metric": "summary_" + suffix, "owner_id": str(actor.id)})
        assert details.status_code == 200 and details.data["count"] == expected, details.content


def test_updated_library_revision_excludes_stale_round_in_every_current_projection(session_client, mixed_executions):
    _, base, _, case, _, _, _, _ = mixed_executions
    case.version = 2
    case.save(update_fields=["version"])
    report = session_client.get(base + "report/").data
    assert report["summary"]["total"] == report["summary"]["passed"] == 1
    assert session_client.get(base + "executions/", {"current_only": "true"}).data["count"] == 1
    assert session_client.get(base + "owner-statistics/", {"source": "quality", "metric": "summary_total"}).data["total"] == 1
    assert session_client.get(base + "owner-statistics/", {"source": "quality", "metric": "verification_case_total"}).data["total"] == 0


def test_period_combined_distribution_and_personal_drilldowns_share_total(session_client, mixed_executions):
    _, base, actor, _, old, new, _, _ = mixed_executions
    today = timezone.localdate().isoformat()
    params = {"start": today, "end": today}
    report = session_client.get(base + "project-report/", params)
    assert report.status_code == 200
    assert report.data["test_results"]["passed"] == 2
    detail = session_client.get(base + "project-report/", {**params, "detail": "all_test_executions", "result": "passed"})
    assert detail.status_code == 200 and detail.data["count"] == 2, detail.content
    assert {row["id"] for row in detail.data["results"]} == {str(old.id), str(new.id)}
    owners = session_client.get(base + "owner-statistics/", {**params, "source": "period", "metric": "all_test_executions", "owner_id": str(actor.id)})
    assert owners.status_code == 200 and owners.data["count"] == 2, owners.content


def test_legacy_snapshot_copy_counts_once_and_current_result_follows_snapshot(session_client, mixed_executions):
    project, base, actor, _, old, _, _, round_ = mixed_executions
    legacy_defect = Defect.objects.create(project=project, created_by=actor, title="旧计划迁移", status="resolved", fixed_build="v2", resolved_at=timezone.now())
    legacy_round = DefectVerification.objects.create(
        project=project, created_by=actor, defect=legacy_defect, plan=old.item.plan, round_no=1,
        mode="cases", status="testing", fixed_build="v2", environment="local",
        resolved_at=legacy_defect.resolved_at, request_id=uuid4(), request_hash="legacy-round",
    )
    copied = DefectVerificationCase.objects.create(
        project=project, created_by=actor, verification=legacy_round, source="library",
        source_case=old.item.case, source_revision=old.item.revision, source_plan_item=old.item,
        title="旧计划快照", snapshot=old.item.revision.snapshot,
    )
    DefectVerificationCaseExecution.objects.create(
        project=project, created_by=actor, item=copied, source_execution=old,
        request_id=uuid4(), request_hash="copy", result="passed", actual_result="原有通过",
    )
    assert session_client.get(base + "executions/").data["count"] == 2
    assert session_client.get(base + "owner-statistics/", {"source": "quality", "metric": "execution_count"}).data["total"] == 2
    new_result = DefectVerificationCaseExecution.objects.create(
        project=project, created_by=actor, item=copied, request_id=uuid4(), request_hash="retest",
        result="failed", actual_result="新轮次复测失败",
    )
    page = session_client.get(base + "executions/", {"current_only": "true", "result": "failed"})
    assert page.status_code == 200 and page.data["count"] == 1, page.content
    assert page.data["results"][0]["id"] == str(new_result.id)
    assert session_client.get(base + "owner-statistics/", {"source": "quality", "metric": "summary_failed"}).data["total"] == 1
    assert session_client.get(base + "executions/").data["count"] == 3
