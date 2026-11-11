"""API regression boundaries: exact functional fix identities and China trend days."""

from datetime import datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone
from freezegun import freeze_time

from plane.db.models import Project, ProjectMember
from plane.quality.models import Defect, DefectEvent

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def functional_case(session_client, workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="功能边界161", identifier="FB161")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/"

    def new_case(title):
        response = session_client.post(
            base + "cases/", {"title": title, "steps": [{"action": "实际操作", "expected": "成功"}]},
            format="json",
        )
        assert response.status_code == 201, response.content
        return response.data

    case = new_case("当前修复对应的用例")
    other_case = new_case("其他用例")
    response = session_client.post(
        base + "plans/",
        {"name": "边界回归", "build": "fix-v161", "environment": "隔离", "case_ids": [case["id"]], "managed": True},
        format="json",
    )
    assert response.status_code == 201, response.content
    plan = response.data

    def action(current, verb, **values):
        result = session_client.post(
            base + f"plans/{current['id']}/workflow/",
            {"action": verb, "expected_version": current["workflow_version"], **values}, format="json",
        )
        assert result.status_code == 200, result.content
        return result.data

    plan = action(plan, "assign", assignee_id=str(create_user.id))
    plan = action(plan, "claim")
    assert plan["status"] == "running"

    def execute(result):
        response = session_client.post(
            base + f"items/{plan['items'][0]['id']}/executions/",
            {"request_id": str(uuid4()), "result": result, "actual_result": f"实际记录{result}"},
            format="json",
        )
        assert response.status_code == 201, response.content
        return response.data

    return project, base, case, other_case, plan, action, execute


@pytest.mark.parametrize("mismatch", ["project", "case", "build", "execution_before_repair", "same_timestamp", "archived"])
def test_failed_submission_only_reopens_exact_current_unarchived_fix(
    session_client, functional_case, workspace, create_user, mismatch,
):
    project, _, case, other_case, plan, action, execute = functional_case
    failed_at = timezone.now()
    matching = Defect.objects.create(
        project=project, created_by=create_user, case_id=case["id"], title="唯一有效修复",
        status="resolved", fixed_build=plan["build"], resolved_at=failed_at - timedelta(seconds=2),
        verification_scope="functional",
    )
    fields = dict(
        project=project, created_by=create_user, case_id=case["id"], title="不可误动的其他修复",
        status="resolved", fixed_build=plan["build"], resolved_at=failed_at - timedelta(seconds=2),
        verification_scope="functional",
    )
    if mismatch == "project":
        # A defensive legacy row can contain the same case UUID with a foreign
        # project. Project isolation must hold even for inconsistent old data.
        fields["project"] = Project.objects.create(workspace=workspace, name="其他项目", identifier="FBOUT")
    elif mismatch == "case":
        fields["case_id"] = other_case["id"]
    elif mismatch == "build":
        fields["fixed_build"] = "older-build"
    elif mismatch == "execution_before_repair":
        fields["resolved_at"] = failed_at + timedelta(seconds=2)
    elif mismatch == "same_timestamp":
        fields["resolved_at"] = failed_at
    else:
        fields["archived_at"] = failed_at - timedelta(seconds=1)
    untouched = Defect.objects.create(**fields)
    original = {key: getattr(untouched, key) for key in ["status", "resolved_at", "edit_version", "archived_at"]}
    execution = execute("failed")
    from plane.quality.models import TestExecution as Execution

    Execution.objects.filter(pk=execution["id"]).update(created_at=failed_at)
    submitted = action(plan, "submit")
    assert submitted["status"] == "review"
    matching.refresh_from_db()
    untouched.refresh_from_db()
    assert matching.status == "open", f"{mismatch}: exact current fix must reopen, id={matching.id}"
    assert matching.resolved_at is None and matching.regression_execution_id is None
    assert {key: getattr(untouched, key) for key in original} == original
    event = DefectEvent.objects.get(defect=matching, previous_status="resolved", status="open")
    assert str(execution["id"]) in event.note
    assert not DefectEvent.objects.filter(defect=untouched).exists()


def test_archived_exact_match_remains_untouched_when_no_active_fix_exists(functional_case, create_user):
    project, _, case, _, plan, action, execute = functional_case
    moment = timezone.now() - timedelta(seconds=2)
    archived = Defect.objects.create(
        project=project, created_by=create_user, case_id=case["id"], title="历史归档修复",
        status="resolved", fixed_build=plan["build"], resolved_at=moment,
        archived_at=moment, verification_scope="functional",
    )
    execute("failed")
    action(plan, "submit")
    archived.refresh_from_db()
    assert archived.status == "resolved"
    assert archived.resolved_at == moment and archived.archived_at == moment
    assert archived.edit_version == 1
    assert not DefectEvent.objects.filter(defect=archived).exists()


def test_previous_round_failed_result_does_not_reopen_repaired_fix_after_current_pass(functional_case, create_user):
    project, _, case, _, plan, action, execute = functional_case
    defect = Defect.objects.create(
        project=project, created_by=create_user, case_id=case["id"], title="第二轮已重新修复",
        status="resolved", fixed_build=plan["build"], resolved_at=timezone.now() - timedelta(seconds=2),
        verification_scope="functional",
    )
    first = execute("failed")
    plan = action(plan, "submit")
    defect.refresh_from_db()
    assert defect.status == "open"
    plan = action(plan, "return", comment="保留第一轮失败，按同一修复版本重新验证")
    assert plan["round_no"] == 2
    repair_time = timezone.now()
    Defect.objects.filter(pk=defect.id).update(status="resolved", resolved_at=repair_time)
    plan = action(plan, "claim")
    second = execute("passed")
    plan = action(plan, "submit")
    assert plan["status"] == "review"
    defect.refresh_from_db()
    assert defect.status == "resolved" and defect.resolved_at == repair_time
    assert DefectEvent.objects.filter(defect=defect, previous_status="resolved", status="open").count() == 1
    from plane.quality.models import TestExecution as Execution

    assert set(Execution.objects.filter(item__plan_id=plan["id"]).values_list("id", "round_no", "result")) == {
        (UUID(first["id"]), 1, "failed"),
        (UUID(second["id"]), 2, "passed"),
    }


@pytest.mark.parametrize("user_zone", ["UTC", "America/Los_Angeles"])
@pytest.mark.parametrize("now_utc", ["2026-11-10T15:59:59.999999+00:00", "2026-11-10T16:00:00+00:00"])
def test_opened_by_day_uses_china_midnight_cutoff_and_exact_day_boundaries(
    session_client, workspace, create_user, user_zone, now_utc,
):
    create_user.user_timezone = user_zone
    create_user.save(update_fields=["user_timezone"])
    project = Project.objects.create(workspace=workspace, name="趋势日界161", identifier="DAY161")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    china = ZoneInfo("Asia/Shanghai")
    today = datetime.fromisoformat(now_utc).astimezone(china).date()
    cutoff = today - timedelta(days=29)
    cutoff_start = datetime.combine(cutoff, datetime.min.time(), tzinfo=china)
    today_start = datetime.combine(today, datetime.min.time(), tzinfo=china)
    stamps = {
        "before_cutoff": cutoff_start - timedelta(microseconds=1),
        "first_in_cutoff": cutoff_start,
        "last_in_cutoff": cutoff_start + timedelta(days=1) - timedelta(microseconds=1),
        "following_midnight": cutoff_start + timedelta(days=1),
        "yesterday_last": today_start - timedelta(microseconds=1),
        "today_first": today_start,
    }
    ids = {}
    for label, stamp in stamps.items():
        row = Defect.objects.create(project=project, title=label)
        Defect.objects.filter(pk=row.id).update(created_at=stamp)
        ids[label] = str(row.id)
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/"

    def buckets(response):
        assert response.status_code == 200, response.content
        return {str(row["date"]): row["count"] for row in response.data["opened_by_day"]}

    with freeze_time(now_utc), timezone.override(user_zone):
        full = session_client.get(base + "defect-statistics/")
        assert buckets(full) == {
            str(cutoff): 2, str(cutoff + timedelta(days=1)): 1,
            str(today - timedelta(days=1)): 1, str(today): 1,
        }
        assert full.data["total"] == 6
        expected_ids = {ids["first_in_cutoff"], ids["last_in_cutoff"]}
        for query in [
            {"created_after": str(cutoff), "created_before": str(cutoff)},
            {"start": str(cutoff), "end": str(cutoff)},
        ]:
            daily = session_client.get(base + "defect-statistics/", query)
            assert buckets(daily) == {str(cutoff): 2}
            assert daily.data["total"] == 2
        listed = session_client.get(base + "defects/", {
            "created_after": str(cutoff), "created_before": str(cutoff),
        })
        assert listed.status_code == 200, listed.content
        assert {row["id"] for row in listed.data["results"]} == expected_ids
        before = session_client.get(base + "defect-statistics/", {"created_before": str(cutoff)})
        assert before.data["total"] == 3 and buckets(before) == {str(cutoff): 2}
        after = session_client.get(base + "defects/", {"created_after": str(cutoff)})
        assert after.status_code == 200, after.content
        assert {row["id"] for row in after.data["results"]} == set(ids.values()) - {ids["before_cutoff"]}
