"""A reusable case definition never shares execution state between defects."""

from uuid import uuid4

import pytest
from django.utils import timezone
from plane.db.models import Project, ProjectMember, User, WorkspaceMember
from plane.quality.models import Defect

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def verification(session_client, workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="验证隔离", identifier="VI")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    tester = User.objects.create(email="verify@test.local", username="verify-tester")
    WorkspaceMember.objects.create(workspace=workspace, member=tester, role=15)
    ProjectMember.objects.create(project=project, member=tester, role=15)
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/"
    cases = [
        session_client.post(
            base + "cases/",
            {"title": f"场景{i}", "steps": [{"action": "操作", "expected": "成功"}]},
            format="json",
        ).data
        for i in range(2)
    ]
    defects = [
        Defect.objects.create(
            project=project,
            created_by=create_user,
            title=f"缺陷{i}",
            status="resolved",
            fixed_build="v2",
            resolved_at=timezone.now(),
        )
        for i in range(2)
    ]
    return base, cases, defects, tester, create_user


def configure(client, base, defect, cases=None, **extra):
    defect.refresh_from_db()
    payload = {
        "expected_version": defect.edit_version,
        "request_id": str(uuid4()),
        "mode": "cases" if cases else "manual",
        "fixed_build": "v2",
        "environment": "测试环境",
    }
    payload.update(
        {"case_ids": [c["id"] for c in cases]} if cases else {"steps": [{"action": "操作", "expected": "成功"}]}
    )
    return client.post(base + f"defects/{defect.id}/verification/", {**payload, **extra}, format="json")


def workflow(client, base, defect, current, action, **extra):
    return client.post(
        base + f"defects/{defect.id}/verification/workflow/",
        {"expected_version": current["version"], "request_id": str(uuid4()), "action": action, **extra},
        format="json",
    )


def execute(client, base, item, result="passed"):
    return client.post(
        base + f"items/{item['item_id']}/executions/",
        {
            "request_id": str(uuid4()),
            "result": result,
            "actual_result": "实测结果",
            "evidence": "现场截图",
            "step_results": [{"result": result, "actual": "实测步骤"}],
        },
        format="json",
    )


def test_multiple_case_results_do_not_cross_defects_and_legacy_close_is_gated(session_client, verification):
    base, cases, defects, tester, manager = verification
    a = configure(session_client, base, defects[0], cases)
    assert a.status_code == 201, a.content
    a = a.data["current"]
    b = configure(session_client, base, defects[1], cases).data["current"]
    assert a["plan_id"] != b["plan_id"]
    assert execute(session_client, base, a["items"][0]).status_code == 201
    assert workflow(session_client, base, defects[0], a, "submit").status_code == 400
    assert execute(session_client, base, a["items"][1]).status_code == 201
    a = workflow(session_client, base, defects[0], a, "submit").data["current"]
    session_client.force_authenticate(tester)
    assert workflow(session_client, base, defects[0], a, "accept").status_code == 403
    session_client.force_authenticate(manager)
    bypass = session_client.patch(
        base + f"defects/{defects[0].id}/",
        {"status": "closed", "verification_method": "manual", "verification_note": "绕过"},
        format="json",
    )
    assert bypass.status_code == 409
    assert (
        session_client.post(
            base + f"defects/{defects[0].id}/disposition/",
            {"expected_version": 2, "kind": "not_a_bug", "reason": "绕过"},
            format="json",
        ).status_code
        == 409
    )
    accepted = workflow(session_client, base, defects[0], a, "accept", comment="验收通过")
    assert accepted.status_code == 200, accepted.content
    assert accepted.data["current"]["status"] == "accepted"
    defects[0].refresh_from_db()
    assert defects[0].status == "closed"
    b = session_client.get(base + f"defects/{defects[1].id}/verification/").data["current"]
    assert b["summary"]["pending"] == 2
    assert workflow(session_client, base, defects[1], b, "accept").status_code == 409


def test_manual_results_retest_reopen_and_actor_audit(session_client, verification):
    base, cases, defects, tester, manager = verification
    defect = defects[0]
    response = configure(session_client, base, defect)
    assert response.status_code == 201, response.content
    current = response.data["current"]
    url = base + f"defects/{defect.id}/verification/result/"
    payload = {
        "expected_version": current["version"],
        "request_id": str(uuid4()),
        "result": "passed",
        "actual_result": "结果符合",
        "evidence": "截图",
        "step_results": [{"result": "passed", "actual": "操作成功"}],
    }
    session_client.force_authenticate(tester)
    recorded = session_client.post(url, payload, format="json")
    assert recorded.status_code == 201, recorded.content
    assert session_client.post(url, payload, format="json").status_code == 200
    current = recorded.data["current"]
    current = workflow(session_client, base, defect, current, "submit").data["current"]
    session_client.force_authenticate(manager)
    assert workflow(session_client, base, defect, current, "return_test").status_code == 400
    returned = workflow(session_client, base, defect, current, "return_test", comment="补测")
    assert returned.status_code == 200, returned.content
    new = returned.data["current"]
    assert new["round_no"] == 2 and new["summary"]["pending"] == 1
    assert session_client.post(url, payload, format="json").status_code == 409
    assert workflow(session_client, base, defect, new, "submit").status_code == 400
    payload.update(expected_version=new["version"], request_id=str(uuid4()))
    new = session_client.post(url, payload, format="json").data["current"]
    new = workflow(session_client, base, defect, new, "submit").data["current"]
    new = workflow(session_client, base, defect, new, "accept").data["current"]
    assert workflow(session_client, base, defect, new, "reopen").status_code == 400
    reopened = workflow(session_client, base, defect, new, "reopen", comment="发现遗漏")
    assert reopened.status_code == 200, reopened.content
    defect.refresh_from_db()
    assert defect.status == "open"
    assert reopened.data["history"][0]["manual_results"][0]["created_by_id"] == str(tester.id)
    assert reopened.data["history"][0]["manual_results"][0]["created_by_name"] == (
        tester.display_name or tester.username
    )
    assert defect.events.filter(created_by=manager, note__contains="发现遗漏").exists()


def test_new_build_and_case_revision_invalidate_old_pass_and_plan_is_immutable(session_client, verification):
    base, cases, defects, tester, manager = verification
    defect = defects[0]
    configured = configure(session_client, base, defect, cases)
    assert configured.status_code == 201, configured.content
    current = configured.data["current"]
    for item in current["items"]:
        assert execute(session_client, base, item).status_code == 201
    assert (
        session_client.patch(
            base + f"plans/{current['plan_id']}/", {"expected_version": 1, "build": "fake"}, format="json"
        ).status_code
        == 409
    )
    current = workflow(session_client, base, defect, current, "submit").data["current"]
    assert execute(session_client, base, current["items"][0], "failed").status_code == 409
    changed = session_client.patch(
        base + f"cases/{cases[0]['id']}/", {"expected_version": 1, "title": "新版本"}, format="json"
    )
    assert changed.status_code == 200
    assert workflow(session_client, base, defect, current, "accept").status_code == 409
    assert workflow(session_client, base, defect, current, "return_repair", comment="重修").status_code == 200
    defect.refresh_from_db()
    assert defect.status == "open"
    listed = session_client.get(base + "verification-results/")
    assert listed.status_code == 200 and listed.data["results"][0]["defect_id"] == str(defect.id)
    assert listed.data["results"][0]["code"] == defect.code
    assert session_client.get(base + "verification-results/", {"search": defect.code}).data["count"] == 1
    assert session_client.get(base + "verification-results/", {"search": "不存在"}).data["count"] == 0


def test_preconfigure_actual_execution_latest_result_and_build_change(session_client, verification):
    base, cases, defects, tester, manager = verification
    defect = defects[0]
    defect.status, defect.fixed_build, defect.resolved_at = "open", "", None
    defect.save()
    response = configure(session_client, base, defect, cases)
    assert response.status_code == 201, response.content
    current = response.data["current"]
    assert not current["can_record"] and current["can_configure"]
    assert configure(session_client, base, defect, cases).data["current"]["id"] == current["id"]
    assert execute(session_client, base, current["items"][0]).status_code == 409
    resolved = session_client.patch(
        base + f"defects/{defect.id}/", {"status": "resolved", "fixed_build": "v2"}, format="json"
    )
    assert resolved.status_code == 200, resolved.content
    for item in current["items"]:
        assert execute(session_client, base, item).status_code == 201
    assert execute(session_client, base, current["items"][0], "failed").status_code == 201
    current = workflow(session_client, base, defect, current, "submit").data["current"]
    assert current["summary"]["failed"] == 1
    assert workflow(session_client, base, defect, current, "accept").status_code == 400
    defect.fixed_build = "v3"
    defect.save()
    assert workflow(session_client, base, defect, current, "accept").status_code == 409


def test_configure_changes_create_round_keep_evidence_and_stale_versions_fail(session_client, verification):
    base, cases, defects, tester, manager = verification
    defect = defects[0]
    first = configure(session_client, base, defect).data["current"]
    response = configure(session_client, base, defect, cases)
    assert response.status_code == 201, response.content
    assert response.data["current"]["round_no"] == 2
    assert response.data["history"][0]["steps"] == first["steps"]
    stale = session_client.post(
        base + f"defects/{defect.id}/verification/",
        {
            "expected_version": 1,
            "request_id": str(uuid4()),
            "mode": "manual",
            "fixed_build": "v2",
            "environment": "环境",
            "steps": [{"action": "操作", "expected": "结果"}],
        },
        format="json",
    )
    assert stale.status_code == 409
    assert workflow(session_client, base, defect, first, "submit").status_code == 409


def test_strict_business_duties_and_readonly_boundaries(session_client, verification):
    from plane.quality.models import BusinessRole, ProjectRolePolicy

    base, cases, defects, tester, manager = verification
    defect = defects[0]
    ProjectRolePolicy.objects.create(project=defect.project, enabled=True)
    BusinessRole.objects.create(project=defect.project, created_by=manager, user=manager, role="PROJECT_MANAGER")
    duty = BusinessRole.objects.create(project=defect.project, created_by=manager, user=tester, role="TECHNICIAN")
    session_client.force_authenticate(tester)
    response = configure(session_client, base, defect)
    assert response.status_code == 201, response.content
    current = response.data["current"]
    manual_url = base + f"defects/{defect.id}/verification/result/"
    result = {
        "expected_version": current["version"],
        "request_id": str(uuid4()),
        "result": "passed",
        "actual_result": "现场成功",
        "evidence": "截图",
        "step_results": [{"result": "passed", "actual": "成功"}],
    }
    assert session_client.post(manual_url, result, format="json").status_code == 403
    duty.role = "REGRESSION_TESTER"
    duty.save()
    response = session_client.post(manual_url, result, format="json")
    assert response.status_code == 201, response.content
    current = workflow(session_client, base, defect, response.data["current"], "submit").data["current"]
    assert workflow(session_client, base, defect, current, "accept").status_code == 403
    session_client.force_authenticate(manager)
    response = workflow(session_client, base, defect, current, "accept")
    assert response.status_code == 200, response.content
    ProjectMember.objects.filter(project=defect.project, member=manager).update(role=5)
    assert workflow(session_client, base, defect, response.data["current"], "reopen", comment="只读").status_code == 403


@pytest.mark.parametrize("readonly_scope", ["project", "workspace"])
def test_nonstrict_readonly_get_exposes_no_write_actions(session_client, verification, readonly_scope):
    base, cases, defects, tester, manager = verification
    defect = defects[0]
    configure(session_client, base, defect)
    configured = configure(session_client, base, defect, cases)
    assert configured.status_code == 201
    if readonly_scope == "project":
        ProjectMember.objects.filter(project=defect.project, member=tester).update(role=5)
    else:
        WorkspaceMember.objects.filter(workspace=defect.project.workspace, member=tester).update(role=5)
    session_client.force_authenticate(tester)
    response = session_client.get(base + f"defects/{defect.id}/verification/")
    assert response.status_code == 200
    rows = [response.data["current"], *response.data["history"]]
    assert len(rows) == 2
    for row in rows:
        assert all(not value for key, value in row.items() if key.startswith("can_")), row
    listed = session_client.get(base + "verification-results/")
    assert listed.status_code == 200
    assert not listed.data["results"][0]["current"]["can_configure"]


@pytest.mark.django_db(transaction=True)
def test_concurrent_manual_result_has_one_winner(session_client, verification):
    from concurrent.futures import ThreadPoolExecutor
    from django.db import close_old_connections
    from rest_framework.test import APIClient
    from plane.quality.models import DefectVerificationResult

    base, cases, defects, tester, manager = verification
    defect = defects[0]
    current = configure(session_client, base, defect).data["current"]

    def submit(_):
        close_old_connections()
        try:
            client = APIClient()
            client.force_authenticate(tester)
            response = client.post(
                base + f"defects/{defect.id}/verification/result/",
                {
                    "expected_version": current["version"],
                    "request_id": str(uuid4()),
                    "result": "passed",
                    "actual_result": "成功",
                    "evidence": "截图",
                    "step_results": [{"result": "passed", "actual": "成功"}],
                },
                format="json",
            )
            return response.status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(submit, range(2))) == [201, 409]
    assert DefectVerificationResult.objects.filter(verification__defect=defect).count() == 1
