"""Session-less DAQ faults use current authority, never invented collection evidence."""

import base64
import hashlib
import hmac
import json
import time
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.utils import timezone
from plane.db.models import Issue, Project, ProjectMember, User, WorkspaceMember
from plane.quality.models import (
    BusinessRole,
    DaqBinding,
    DaqReport,
    Defect,
    PlatformIdentity,
    PlatformProject,
    ProjectRolePolicy,
    SourceLink,
)

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def signature(path, body, actor=16, method="POST"):
    stamp, nonce = str(int(time.time())), str(uuid4())
    principal = json.dumps({"id": actor, "username": "test-collector"}, separators=(",", ":"))

    def enc(v):
        return base64.urlsafe_b64encode(v.encode()).decode().rstrip("=")

    digest = "-" if method == "GET" else hashlib.sha256(body.encode()).hexdigest()
    canonical = "\n".join(
        [
            "ISSUE-IDENTITY-V2",
            enc("plane-quality"),
            enc("test-incidents"),
            stamp,
            enc(nonce),
            method,
            enc(path),
            digest,
            enc(principal),
        ]
    )
    sig = (
        base64.urlsafe_b64encode(hmac.new(b"synthetic-incidents-only", canonical.encode(), hashlib.sha256).digest())
        .decode()
        .rstrip("=")
    )
    return {
        "HTTP_X_ISSUE_IDENTITY_VERSION": "2",
        "HTTP_X_ISSUE_KEY_ID": "test-incidents",
        "HTTP_X_ISSUE_AUDIENCE": "plane-quality",
        "HTTP_X_ISSUE_PRINCIPAL": principal,
        "HTTP_X_ISSUE_PRINCIPAL_TIMESTAMP": stamp,
        "HTTP_X_ISSUE_PRINCIPAL_NONCE": nonce,
        "HTTP_X_ISSUE_CONTENT_SHA256": digest,
        "HTTP_X_ISSUE_PRINCIPAL_SIGNATURE": sig,
    }


@pytest.fixture
def incident(api_client, workspace, create_user, settings):
    project = Project.objects.create(workspace=workspace, name="无Session故障", identifier="INC")
    ProjectMember.objects.create(project=project, member=create_user, role=15)
    ProjectRolePolicy.objects.create(project=project, enabled=True)
    BusinessRole.objects.create(project=project, user=create_user, role="REPORTER")
    PlatformIdentity.objects.create(project=project, source_instance="test-dp", external_user_id=16, user=create_user)
    PlatformProject.objects.create(project=project, source_instance="test-dp", external_project_id=9)
    settings.QUALITY_BRIDGE_KEYS = {
        "test-incidents": {
            "secret": "synthetic-incidents-only",
            "audience": "plane-quality",
            "source_instance": "test-dp",
        }
    }
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/daq/incidents/"
    payload = {
        "eventId": str(uuid4()),
        "kind": "startup_failure",
        "occurredAt": timezone.now().isoformat(),
        "platformProjectId": 9,
        "platformTaskId": 24,
        "title": "采集启动连接失败",
        "description": "启动时连接被拒绝；还没有Session",
        "device": "robot-test",
    }
    state = {
        "context": {"taskId": 24, "projectId": 9, "sourceSessionId": None, "dataPackageId": None},
        "role": "Collector",
        "projects": [{"id": 9}],
        "calls": [],
    }

    def fetch(source, path, params=None):
        state["calls"].append((source, path, params))
        if path.startswith("/internal/issue-users/"):
            return {"id": int(path.rsplit("/", 1)[1]), "active": True, "role": state["role"]}
        if path.startswith("/internal/issue-permissions/"):
            return {"projects": state["projects"]}
        return state["context"]

    def post(data=None, path=None, actor=16):
        from rest_framework.test import APIClient

        path = path or base
        body = json.dumps(data if data is not None else payload, separators=(",", ":"), ensure_ascii=False)
        return APIClient().post(path, body, content_type="application/json", **signature(path, body, actor))

    with patch("plane.quality.platform.fetch", side_effect=fetch):
        yield project, create_user, base, payload, state, post


def test_no_session_fault_creates_numbered_defect_waiting_for_materials_and_idempotent_receipt(incident):
    project, user, base, payload, state, post = incident
    first = post()
    assert first.status_code == 201, first.content
    assert first.data["issueCode"] == "INC-D-1"
    assert first.data["diagnosticStatus"] == "waiting_materials"
    assert first.data["sourceRecordType"] == "startup_failure"
    assert first.data["sourceSessionId"] is None and first.data["dataPackageId"] is None
    defect = Defect.objects.get()
    assert not defect.diagnostics.exists()
    assert DaqBinding.objects.count() == DaqReport.objects.count() == 0
    source = SourceLink.objects.get()
    assert source.record_type == "daq_incident" and source.source_system == "ENGRAM_DAQ"
    assert source.record_id == f"16:{payload['eventId']}" and source.package_id == ""
    from plane.quality.daq_incidents import trusted_incident

    assert trusted_incident(defect).pk == source.pk
    assert post().status_code == 200 and Defect.objects.count() == 1
    assert post({**payload, "title": "different intent"}).status_code == 409
    assert any(p.endswith("/tasks/24/context") and params is None for _, p, params in state["calls"])


def test_project_only_fault_requires_current_collector_and_exact_upstream_project(incident):
    project, user, base, payload, state, post = incident
    data = {k: v for k, v in payload.items() if k != "platformTaskId"}
    assert post(data).status_code == 201
    assert not any("/tasks/" in p for _, p, _ in state["calls"])
    state["role"] = "Manager"
    assert post({**data, "eventId": str(uuid4())}).status_code in [401, 403]
    state["role"] = "Collector"
    assert post({**data, "platformProjectId": 10}).status_code == 403
    state["projects"] = []
    assert post(data).status_code in [401, 403]
    assert Defect.objects.count() == 1


@pytest.mark.parametrize(
    "bad",
    [
        {"eventId": "not-uuid"},
        {"kind": "session"},
        {"sourceRecordId": "fake-session"},
        {"dataPackageId": "fake-package"},
        {"occurredAt": "2039-01-01T00:00:00Z"},
        {"occurredAt": "2026-01-01T00:00:00"},
        {"platformTaskId": True},
        {"platformProjectId": False},
        {"environment": {"password": "SYNTHETIC_SECRET"}},
    ],
)
def test_strict_input_rejects_fabricated_session_future_naive_and_sensitive_fields(incident, bad):
    project, user, base, payload, state, post = incident
    assert post({**payload, **bad}).status_code == 400
    assert not Defect.objects.exists()


def test_task_mismatch_role_denial_and_native_session_do_not_create_fault(incident, session_client):
    project, user, base, payload, state, post = incident
    state["context"]["projectId"] = 10
    assert post().status_code == 403
    state["context"]["projectId"] = 9
    state["context"]["taskId"] = 25
    assert post().status_code == 403
    state["context"]["taskId"] = 24
    BusinessRole.objects.filter(project=project).update(role="PROJECT_MANAGER")
    assert post().status_code == 403
    BusinessRole.objects.filter(project=project).update(role="REPORTER")
    assert session_client.post(base, payload, format="json").status_code == 403
    assert not Defect.objects.exists()


def test_cross_project_and_other_actor_cannot_read_or_attach_and_session_is_real_only(incident, api_client, workspace):
    project, user, base, payload, state, post = incident
    first = post()
    assert first.status_code == 201, first.content
    detail = base + first.data["issueId"] + "/"
    session_path = detail + "session/"
    state["context"] = {
        "taskId": 24,
        "projectId": 9,
        "sourceSessionId": "real-session",
        "dataPackageId": "actual-package",
    }
    attached = post({"sourceSessionId": "real-session"}, session_path)
    assert attached.status_code == 201, attached.content
    assert attached.data["sourceSessionId"] == "real-session" and attached.data["dataPackageId"] == "actual-package"
    assert post({"sourceSessionId": "real-session"}, session_path).status_code == 200
    assert DaqBinding.objects.count() == DaqReport.objects.count() == 0
    assert Defect.objects.get().status == "open"
    state["context"]["sourceSessionId"] = "other-session"
    assert post({"sourceSessionId": "real-session"}, session_path).status_code == 403
    assert SourceLink.objects.filter(record_type="verified_session").count() == 1
    other = User.objects.create(email="incident-other@example.test", username="incident-other")
    WorkspaceMember.objects.create(workspace=workspace, member=other, role=15)
    ProjectMember.objects.create(project=project, member=other, role=15)
    BusinessRole.objects.create(project=project, user=other, role="REPORTER")
    PlatformIdentity.objects.create(project=project, source_instance="test-dp", external_user_id=17, user=other)
    assert post({"sourceSessionId": "real-session"}, session_path, actor=17).status_code == 403


def test_forged_generic_source_link_is_not_trusted(incident):
    project, user, base, payload, state, post = incident
    defect = Defect.objects.create(project=project, created_by=user, title="forged")
    SourceLink.objects.create(
        project=project,
        created_by=user,
        defect=defect,
        source_system="ENGRAM_DAQ",
        source_instance="test-dp",
        record_type="daq_incident",
        record_id="16:" + str(uuid4()),
        task_id="24",
    )
    from plane.quality.daq_incidents import trusted_incident

    assert trusted_incident(defect) is None


def test_project_only_incident_can_later_link_real_task_session_without_rewriting_original(incident):
    project, user, base, payload, state, post = incident
    data = {k: v for k, v in payload.items() if k != "platformTaskId"}
    first = post(data)
    assert first.status_code == 201
    path = base + first.data["issueId"] + "/session/"
    assert post({"sourceSessionId": "actual-session"}, path).status_code == 409
    state["context"] = {
        "taskId": 24,
        "projectId": 9,
        "sourceSessionId": "actual-session",
        "dataPackageId": "actual-package",
    }
    attached = post({"sourceSessionId": "actual-session", "platformTaskId": 24}, path)
    assert attached.status_code == 201, attached.content
    from plane.quality.daq_incidents import signed_record, trusted_incident

    link = trusted_incident(Defect.objects.get())
    assert "platformTaskId" not in signed_record(link)["payload"] and link.task_id == ""
    assert SourceLink.objects.get(record_type="verified_session").task_id == "24"
    state["context"]["projectId"] = 10
    assert post({"sourceSessionId": "foreign-session", "platformTaskId": 24}, path).status_code == 403


def test_incident_detail_returns_actual_diagnostics_and_rechecks_actor_and_permissions(incident, api_client):
    project, user, base, payload, state, post = incident
    result = post()
    path = base + result.data["issueId"] + "/"
    response = api_client.get(path, **signature(path, "", method="GET"))
    assert response.status_code == 200, response.content
    assert response.data["diagnostics"] == response.data["packages"] == response.data["regressions"] == []
    assert response.data["defect"]["id"] == result.data["issueId"]
    state["projects"] = []
    assert api_client.get(path, **signature(path, "", method="GET")).status_code in [401, 403]


def test_incident_regression_uses_real_session_baseline_and_keeps_new_ready_evidence_gate(incident, session_client):
    from plane.quality.models import DataRegression, Solution, SolutionRevision
    from plane.quality.data_regression import verified_context
    from rest_framework.exceptions import ValidationError

    project, user, base, payload, state, post = incident
    first = post()
    assert first.status_code == 201
    defect = Defect.objects.get()
    issue = Issue.objects.create(project=project, workspace=project.workspace, name="技术修复任务")
    defect.repair_issue = issue
    defect.fixed_build = "repair-v2"
    defect.status = "resolved"
    defect.resolved_at = timezone.now()
    defect.save()
    BusinessRole.objects.filter(project=project, user=user).update(additional_roles=["PROJECT_MANAGER"])
    solution = Solution.objects.create(
        project=project,
        created_by=user,
        defect=defect,
        title="修复",
        root_cause="启动失败",
        steps="修复",
        verification="真实新Session和ready数据包",
        status="approved",
        submitted_version=1,
    )
    SolutionRevision.objects.create(
        project=project,
        created_by=user,
        solution=solution,
        version=1,
        snapshot={"verification": solution.verification},
        reviewer_ids=[str(user.id)],
        required_count=1,
    )
    path = base.split("daq/incidents/")[0] + f"defects/{defect.id}/data-regressions/"
    body = {"solution_id": str(solution.id), "environment": "真实来源回归"}
    assert session_client.post(path, body, format="json").status_code == 409
    assert not DaqBinding.objects.exists()
    state["context"] = {
        "taskId": 24,
        "projectId": 9,
        "sourceSessionId": "baseline-real-session",
        "dataPackageId": "baseline-real-package",
    }
    assert (
        post({"sourceSessionId": "baseline-real-session"}, base + first.data["issueId"] + "/session/").status_code
        == 201
    )
    accepted = session_client.post(path, body, format="json")
    assert accepted.status_code == 201, accepted.content
    regression = DataRegression.objects.get()
    assert regression.binding.source_record_id == "baseline-real-session"
    assert regression.binding.package_id == "baseline-real-package" and regression.binding.issue == issue
    assert not DaqReport.objects.exists()
    with pytest.raises(ValidationError):
        verified_context(regression, "baseline-real-session")
    state["context"] = {
        "taskId": 24,
        "projectId": 9,
        "sourceSessionId": "new-real-session",
        "dataPackageId": "new-real-package",
        "collectedAt": timezone.now().isoformat(),
        "dataReady": False,
        "dataPackageStatus": "Transferring",
    }
    with pytest.raises(ValidationError):
        verified_context(regression, "new-real-session")
    state["context"].update(dataReady=True, dataPackageStatus="PendingAnnotation")
    assert verified_context(regression, "new-real-session")[0]["dataPackageId"] == "new-real-package"


@pytest.mark.django_db(transaction=True)
def test_concurrent_retries_and_other_actor_events_do_not_duplicate_or_collide(incident, workspace):
    from concurrent.futures import ThreadPoolExecutor
    from django.db import close_old_connections

    project, user, base, payload, state, post = incident

    def send(index):
        close_old_connections()
        try:
            response = post()
            return response.status_code, response.data.get("issueId")
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=4) as pool:
        replies = list(pool.map(send, range(4)))
    assert sorted(status for status, _ in replies) == [200, 200, 200, 201], replies
    assert len({key for _, key in replies}) == 1 and Defect.objects.count() == 1
    other = User.objects.create(email="actor17@example.test", username="actor17")
    WorkspaceMember.objects.create(workspace=workspace, member=other, role=15)
    ProjectMember.objects.create(project=project, member=other, role=15)
    BusinessRole.objects.create(project=project, user=other, role="REPORTER")
    PlatformIdentity.objects.create(project=project, source_instance="test-dp", external_user_id=17, user=other)
    assert post(actor=17).status_code == 201
    assert Defect.objects.count() == 2


def test_incident_context_checks_current_collector_project_and_optional_task(incident, api_client):
    project, user, base, payload, state, post = incident
    path = base + "?platformProjectId=9&platformTaskId=24"
    result = api_client.get(path, **signature(path, "", method="GET"))
    assert result.status_code == 200, result.content
    assert result.data["can_report"] is True
    assert result.data["platformProjectId"] == 9 and result.data["platformTaskId"] == 24
    assert not Defect.objects.exists()
    state["context"]["projectId"] = 10
    assert api_client.get(path, **signature(path, "", method="GET")).status_code == 403
    state["context"]["projectId"] = 9
    state["role"] = "Manager"
    assert api_client.get(path, **signature(path, "", method="GET")).status_code in [401, 403]
    state["role"] = "Collector"
    state["context"]["taskId"] = 24.0
    assert api_client.get(path, **signature(path, "", method="GET")).status_code == 403
    for value in ["invalid", "0", "9" * 100]:
        invalid = base + "?platformProjectId=9&platformTaskId=" + value
        assert api_client.get(invalid, **signature(invalid, "", method="GET")).status_code == 400


def test_receipt_and_detail_preserve_linked_session_after_refresh(incident, api_client):
    project, user, base, payload, state, post = incident
    first = post({key: value for key, value in payload.items() if key != "platformTaskId"})
    path = base + first.data["issueId"] + "/"
    state["context"] = {
        "taskId": 24,
        "projectId": 9,
        "sourceSessionId": "real-session",
        "dataPackageId": "real-package",
    }
    assert post({"sourceSessionId": "real-session", "platformTaskId": 24}, path + "session/").status_code == 201
    detail = api_client.get(path, **signature(path, "", method="GET"))
    assert detail.status_code == 200, detail.content
    assert detail.data["sourceSessionId"] == "real-session" and detail.data["dataPackageId"] == "real-package"
    assert detail.data["platformTaskId"] is None and detail.data["linkedPlatformTaskId"] == 24
    assert detail.data["verifiedSessions"][0]["sourceSessionId"] == "real-session"
    retry = post({key: value for key, value in payload.items() if key != "platformTaskId"})
    assert retry.status_code == 200 and retry.data["sourceSessionId"] == "real-session"


def test_incident_regression_requires_explicit_ready_state_and_rejects_forged_session_link(incident, session_client):
    from rest_framework.exceptions import ValidationError
    from plane.quality.models import DataRegression, Solution, SolutionRevision
    from plane.quality.data_regression import verified_context

    project, user, base, payload, state, post = incident
    assert post().status_code == 201
    defect = Defect.objects.get()
    repair = Issue.objects.create(project=project, workspace=project.workspace, name="真实技术修复")
    defect.repair_issue, defect.status, defect.fixed_build, defect.resolved_at = (
        repair,
        "resolved",
        "v2",
        timezone.now(),
    )
    defect.save()
    BusinessRole.objects.filter(project=project, user=user).update(additional_roles=["PROJECT_MANAGER"])
    solution = Solution.objects.create(
        project=project, created_by=user, defect=defect, title="修复", status="approved", submitted_version=1
    )
    SolutionRevision.objects.create(
        project=project,
        created_by=user,
        solution=solution,
        version=1,
        snapshot={"verification": "新数据"},
        reviewer_ids=[str(user.id)],
        required_count=1,
    )
    regression_path = base.split("daq/incidents/")[0] + f"defects/{defect.id}/data-regressions/"
    request = {"solution_id": str(solution.id), "environment": "真实新数据回归"}
    fake = SourceLink.objects.create(
        project=project,
        created_by=user,
        defect=defect,
        source_system="ENGRAM_DAQ",
        source_instance="test-dp",
        record_type="verified_session",
        record_id="forged",
        task_id="24",
        package_id="fake",
    )
    assert session_client.post(regression_path, request, format="json").status_code == 409
    assert not DaqBinding.objects.exists()
    fake.delete()
    state["context"] = {"taskId": 24, "projectId": 9, "sourceSessionId": "baseline", "dataPackageId": "baseline-pkg"}
    assert post({"sourceSessionId": "baseline"}, base + str(defect.id) + "/session/").status_code == 201
    assert session_client.post(regression_path, request, format="json").status_code == 201
    row = DataRegression.objects.get()
    state["context"] = {
        "taskId": 24,
        "projectId": 9,
        "sourceSessionId": "new",
        "dataPackageId": "new-pkg",
        "collectedAt": timezone.now().isoformat(),
    }
    with pytest.raises(ValidationError):
        verified_context(row, "new")
    state["context"].update(dataReady=True, dataPackageStatus="PendingAnnotation")
    assert verified_context(row, "new")[0]["dataPackageId"] == "new-pkg"


def test_startup_incident_full_regression_failure_then_new_ready_data_manager_close_and_knowledge(
    incident, session_client
):
    from plane.knowledge.models import Article
    from plane.quality.models import Solution, SolutionRevision

    project, user, base, payload, state, post = incident
    created = post({key: value for key, value in payload.items() if key != "platformTaskId"})
    assert created.status_code == 201
    defect = Defect.objects.get()
    assert not DaqBinding.objects.exists() and not DaqReport.objects.exists()
    state["context"] = {
        "taskId": 24,
        "projectId": 9,
        "sourceSessionId": "actual-baseline",
        "dataPackageId": "actual-baseline-pkg",
    }
    assert (
        post(
            {"sourceSessionId": "actual-baseline", "platformTaskId": 24}, base + str(defect.id) + "/session/"
        ).status_code
        == 201
    )
    repair = Issue.objects.create(project=project, workspace=project.workspace, name="连接服务修复")
    defect.repair_issue, defect.fixed_build, defect.status, defect.resolved_at = (
        repair,
        "v2",
        "resolved",
        timezone.now(),
    )
    defect.save()
    BusinessRole.objects.filter(project=project, user=user).update(additional_roles=["PROJECT_MANAGER"])
    tester = User.objects.create(username="incident-tester", email="incident-tester@example.test")
    WorkspaceMember.objects.create(workspace=project.workspace, member=tester, role=15)
    ProjectMember.objects.create(project=project, member=tester, role=15)
    BusinessRole.objects.create(project=project, user=tester, role="REGRESSION_TESTER")
    solution = Solution.objects.create(
        project=project,
        created_by=user,
        defect=defect,
        title="恢复服务",
        root_cause="端口未监听",
        steps="启动监听服务",
        verification="新Session和ready数据包",
        status="approved",
        submitted_version=1,
    )
    SolutionRevision.objects.create(
        project=project,
        created_by=user,
        solution=solution,
        version=1,
        snapshot={
            "title": solution.title,
            "root_cause": solution.root_cause,
            "steps": solution.steps,
            "verification": solution.verification,
        },
        reviewer_ids=[str(user.id)],
        required_count=1,
    )
    quality = base.split("daq/incidents/")[0]

    def action(plan, verb, expected=200, **extra):
        response = session_client.post(
            quality + f"plans/{plan['id']}/workflow/",
            {"action": verb, "expected_version": plan["workflow_version"], **extra},
            format="json",
        )
        assert response.status_code == expected, response.content
        return response.data

    def start():
        session_client.force_authenticate(user=user)
        response = session_client.post(
            quality + f"defects/{defect.id}/data-regressions/",
            {"solution_id": str(solution.id), "environment": "本机隔离回归"},
            format="json",
        )
        assert response.status_code == 201, response.content
        plan = action(response.data["plan"], "assign", assignee_id=str(tester.id))
        session_client.force_authenticate(user=tester)
        return action(plan, "claim")

    first = start()
    execute = quality + f"items/{first['items'][0]['id']}/executions/"
    assert (
        session_client.post(
            execute,
            {"request_id": str(uuid4()), "result": "failed", "actual_result": "连接仍被拒绝", "evidence": "失败日志"},
            format="json",
        ).status_code
        == 201
    )
    assert action(first, "submit")["status"] == "failed"
    defect.refresh_from_db()
    assert defect.status == "open" and defect.resolved_at is None
    defect.status, defect.fixed_build, defect.resolved_at = "resolved", "v3", timezone.now()
    defect.save()
    second = start()
    execute = quality + f"items/{second['items'][0]['id']}/executions/"
    result = {
        "request_id": str(uuid4()),
        "result": "passed",
        "actual_result": "新数据检查通过",
        "evidence": "连接日志与数据完整性通过",
    }
    assert session_client.post(execute, result, format="json").status_code == 400
    state["context"] = {
        "taskId": 24,
        "projectId": 9,
        "sourceSessionId": "new-session",
        "dataPackageId": "new-ready-pkg",
        "collectedAt": timezone.now().isoformat(),
        "dataReady": False,
        "dataPackageStatus": "Transferring",
    }
    evidence = quality + f"plans/{second['id']}/data-evidence/"
    assert session_client.post(evidence, {"source_session_id": "new-session"}, format="json").status_code == 400
    state["context"].update(dataReady=True, dataPackageStatus="PendingAnnotation")
    assert session_client.post(evidence, {"source_session_id": "new-session"}, format="json").status_code == 201
    assert session_client.post(execute, result, format="json").status_code == 201
    submitted = action(second, "submit")
    action(submitted, "approve", expected=403)
    session_client.force_authenticate(user=user)
    state["context"].update(dataReady=False, dataPackageStatus="ConvertFailed")
    action(submitted, "approve", expected=400)
    defect.refresh_from_db()
    assert defect.status == "resolved"
    state["context"].update(dataReady=True, dataPackageStatus="PendingAnnotation")
    assert action(submitted, "approve")["status"] == "completed"
    defect.refresh_from_db()
    assert defect.status == "closed" and not DaqReport.objects.exists()
    article = Article.objects.get(source_defect=defect)
    assert article.status == "draft" and article.source_regression.defect == defect
    assert "端口未监听" in article.content and "启动监听服务" in article.content
    article.status, article.publication_active = "published", True
    article.save()
    reopened = session_client.patch(
        quality + f"defects/{defect.id}/",
        {"status": "open", "expected_version": defect.edit_version, "resolution": "同类问题复现"},
        format="json",
    )
    assert reopened.status_code == 200, reopened.content
    article.refresh_from_db()
    assert article.status == "offline" and article.publication_active is False


def test_signed_incident_cannot_close_through_ordinary_case_execution(incident, session_client):
    from plane.quality.models import TestCase, CaseRevision, TestPlan, PlanItem, TestExecution

    project, user, base, payload, state, post = incident
    assert post().status_code == 201
    BusinessRole.objects.filter(project=project, user=user).update(additional_roles=["PROJECT_MANAGER"])
    case = TestCase.objects.create(project=project, created_by=user, title="普通测试用例")
    revision = CaseRevision.objects.create(project=project, created_by=user, case=case, version=1, snapshot={})
    plan = TestPlan.objects.create(project=project, created_by=user, name="普通回归", build="v2")
    item = PlanItem.objects.create(project=project, created_by=user, plan=plan, case=case, revision=revision)
    defect = Defect.objects.get()
    defect.case, defect.status, defect.fixed_build, defect.resolved_at = case, "resolved", "v2", timezone.now()
    defect.save()
    execution = TestExecution.objects.create(
        project=project, created_by=user, item=item, request_id=uuid4(), result="passed", actual_result="普通用例通过"
    )
    path = base.split("daq/incidents/")[0] + f"defects/{defect.id}/"
    result = session_client.patch(
        path,
        {"status": "closed", "expected_version": defect.edit_version, "regression_execution_id": str(execution.id)},
        format="json",
    )
    assert result.status_code == 400, result.content
    defect.refresh_from_db()
    assert defect.status == "resolved"

