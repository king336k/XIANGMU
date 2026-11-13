"""DAQ reporting destination is independent from project membership."""

import hashlib
import json
from uuid import uuid4
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient
from plane.db.models import Project, ProjectMember, WorkspaceMember
from plane.quality.models import BusinessRole, PlatformIdentity, PlatformProject, Defect
from plane.tests.contract.app.test_daq_incidents import signature

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def upload_part(path, fields, actor=16):
    import base64
    import hmac
    from django.test.client import BOUNDARY, MULTIPART_CONTENT, encode_multipart
    from plane.quality.identity import encode, multipart_digest, target_path

    body = encode_multipart(BOUNDARY, fields)
    headers = signature(path, "", actor=actor, method="POST")
    digest = multipart_digest(body, MULTIPART_CONTENT)
    canonical = "\n".join(
        [
            "ISSUE-IDENTITY-V2",
            encode("plane-quality"),
            encode("test-incidents"),
            headers["HTTP_X_ISSUE_PRINCIPAL_TIMESTAMP"],
            encode(headers["HTTP_X_ISSUE_PRINCIPAL_NONCE"]),
            "POST",
            encode(target_path(path)),
            digest,
            encode(headers["HTTP_X_ISSUE_PRINCIPAL"]),
        ]
    )
    headers["HTTP_X_ISSUE_CONTENT_SHA256"] = digest
    headers["HTTP_X_ISSUE_PRINCIPAL_SIGNATURE"] = (
        base64.urlsafe_b64encode(hmac.new(b"synthetic-incidents-only", canonical.encode(), hashlib.sha256).digest())
        .decode()
        .rstrip("=")
    )
    return APIClient().post(path, body, content_type=MULTIPART_CONTENT, **headers)


def registered_evidence(project, user, report_id):
    from plane.quality.models import PackageFile, ProblemPackage

    package = ProblemPackage.objects.create(
        project=project,
        defect_id=report_id,
        created_by=user,
        name="own evidence",
        source_system="ENGRAM_DAQ",
        external_id=str(uuid4()),
        status="files_verified",
    )
    return PackageFile.objects.create(
        project=project,
        package=package,
        created_by=user,
        name="own.log",
        size=24,
        sha256="a" * 64,
        storage_key=str(uuid4()) + ".bin",
    )


@pytest.fixture
def reporting(workspace, settings, mocker):
    from plane.license.models import InstanceConfiguration, Instance, InstanceAdmin
    from plane.db.models import User
    from django.utils import timezone

    instance = Instance.objects.create(
        instance_name="reporting", instance_id=str(uuid4()), current_version="test", last_checked_at=timezone.now()
    )
    InstanceAdmin.objects.create(instance=instance, user=workspace.owner)
    destination = Project.objects.create(workspace=workspace, name="已授权反馈项目", identifier="ANYDEST")
    settings.QUALITY_DAQ_REPORT_KEYS = {
        "test-incidents": {
            "secret": "synthetic-incidents-only",
            "audience": "plane-quality",
            "source_instance": "daq-device",
        }
    }
    grants = InstanceConfiguration.objects.create(
        key="QUALITY_DAQ_PROJECT_GRANTS", value=json.dumps({"projects": [str(destination.id)], "revision": 1})
    )
    mocker.patch(
        "plane.quality.platform.fetch", side_effect=AssertionError("standalone DAQ must not contact data platform")
    )
    mocker.patch("plane.quality.diagnostics.enqueue")
    response = call("/api/quality-auth/daq-project-options/")
    assert response.status_code == 200, response.content
    user = User.objects.get(is_bot=True)
    payload = {
        "eventId": str(uuid4()),
        "kind": "startup_failure",
        "occurredAt": timezone.now().isoformat(),
        "title": "采集启动失败",
        "description": "采集程序记录connect timeout",
        "device": "robot-test",
    }
    return destination, user, payload, {"grants": grants, "keys": settings.QUALITY_DAQ_REPORT_KEYS}


def revoke_grants(state):
    state["grants"].value = json.dumps({"projects": [], "revision": 2})
    state["grants"].save()


def call(path, data=None, method="GET", actor=16, headers=None):
    body = json.dumps(data or {}, separators=(",", ":"), ensure_ascii=False)
    supplied = headers or signature(path, "" if method == "GET" else body, actor=actor, method=method)
    client = APIClient()
    return (
        client.get(path, **supplied)
        if method == "GET"
        else client.post(path, body, content_type="application/json", **supplied)
    )


def test_collector_can_choose_only_granted_nonarchived_projects_without_membership(reporting):
    destination, user, payload, state = reporting
    archived = Project.objects.create(
        workspace=destination.workspace, name="已归档", identifier="ARCREPORT", archived_at=timezone.now()
    )
    path = "/api/quality-auth/daq-project-options/"
    response = call(path)
    assert response.status_code == 200, response.content
    ids = {row["hubProjectId"] for row in response.data["results"]}
    assert str(destination.id) in ids and str(archived.id) not in ids
    row = next(row for row in response.data["results"] if row["hubProjectId"] == str(destination.id))
    assert set(row) == {"hubProjectId", "projectName", "identifier", "workspace"}
    assert not ProjectMember.objects.filter(project=destination, member=user).exists()
    assert not PlatformIdentity.objects.filter(project=destination, user=user).exists()


def test_unsigned_replay_and_disabled_device_key_cannot_use_project_directory(reporting):
    destination, user, payload, state = reporting
    path = "/api/quality-auth/daq-project-options/"
    assert APIClient().get(path).status_code in {401, 403}
    headers = signature(path, "", method="GET")
    assert call(path, headers=headers).status_code == 200
    assert call(path, headers=headers).status_code in {401, 403}
    state["keys"]["test-incidents"]["enabled"] = False
    assert call(path).status_code in {401, 403}


def test_report_without_session_creates_no_mapping_or_project_membership_idempotently(reporting):
    destination, user, payload, state = reporting
    path = "/api/quality-auth/daq-reports/"
    data = {
        **payload,
        "hubProjectId": str(destination.id),
        "category": "ValidationFailed",
        "sourceReference": "local-only-name",
    }
    before = [
        WorkspaceMember.objects.count(),
        ProjectMember.objects.count(),
        BusinessRole.objects.count(),
        PlatformIdentity.objects.count(),
    ]
    first = call(path, data, "POST")
    assert first.status_code == 201, first.content
    retry = call(path, data, "POST")
    assert retry.status_code == 200 and retry.data["issueId"] == first.data["issueId"]
    assert first.data["category"] == "ValidationFailed" and first.data["sourceReference"] == "local-only-name"
    assert first.data["sourceSessionId"] is None and first.data["verifiedSessions"] == []
    assert first.data["hubProjectId"] == str(destination.id)
    assert not PlatformProject.objects.filter(project=destination).exists()
    assert [
        WorkspaceMember.objects.count(),
        ProjectMember.objects.count(),
        BusinessRole.objects.count(),
        PlatformIdentity.objects.count(),
    ] == before
    own = call(path)
    assert own.status_code == 200 and own.data["count"] == 1
    assert call(path + first.data["issueId"] + "/").status_code == 200
    old_quality = f"/api/workspaces/{destination.workspace.slug}/projects/{destination.id}/quality/defects/"
    assert call(old_quality).status_code in {401, 403}


@pytest.mark.parametrize("boundary", ["revoked_project", "archived_target", "invalid_category"])
def test_report_rejects_source_authority_or_target_without_partial_mapping(reporting, boundary):
    destination, user, payload, state = reporting
    data = {**payload, "hubProjectId": str(destination.id)}
    if boundary == "revoked_project":
        revoke_grants(state)
    elif boundary == "archived_target":
        destination.archived_at = timezone.now()
        destination.save()
    else:
        data["category"] = "invented"
    response = call("/api/quality-auth/daq-reports/", data, "POST")
    assert response.status_code in {400, 401, 403, 404}, response.content
    assert not PlatformProject.objects.filter(project=destination).exists()
    assert not Defect.objects.filter(project=destination).exists()


def test_own_report_materials_upload_and_download_without_project_read_access(reporting, settings, tmp_path, mocker):
    destination, user, payload, state = reporting
    settings.QUALITY_ATTACHMENT_ROOT = str(tmp_path)
    mocker.patch("plane.quality.diagnostics.enqueue")
    base = "/api/quality-auth/daq-reports/"
    created = call(base, {**payload, "hubProjectId": str(destination.id)}, "POST")
    assert created.status_code == 201, created.content
    issue = created.data["issueId"]
    raw = b"2026-11-10 ERROR permission denied\n"
    package = call(
        base + issue + "/packages/",
        {
            "name": "诊断材料",
            "defect_id": issue,
            "source_system": "ENGRAM_DAQ",
            "external_id": "report-materials",
            "files": [{"path": "fault.log", "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}],
        },
        "POST",
    )
    assert package.status_code == 201, package.content
    from plane.quality.identity import multipart_digest
    from django.test.client import encode_multipart
    from django.test.client import BOUNDARY, MULTIPART_CONTENT

    upload = SimpleUploadedFile("fault.log", raw, content_type="text/plain")
    body = encode_multipart(BOUNDARY, {"file": upload})
    path = base + issue + "/packages/" + str(package.data["id"]) + "/files/"
    headers = signature(path, "", method="POST")
    # Use the bridge's canonical manifest signing for multipart requests.
    import base64
    import hmac
    from plane.quality.identity import encode, target_path

    principal = headers["HTTP_X_ISSUE_PRINCIPAL"]
    stamp = headers["HTTP_X_ISSUE_PRINCIPAL_TIMESTAMP"]
    nonce = headers["HTTP_X_ISSUE_PRINCIPAL_NONCE"]
    digest = multipart_digest(body, MULTIPART_CONTENT)
    canonical = "\n".join(
        [
            "ISSUE-IDENTITY-V2",
            encode("plane-quality"),
            encode("test-incidents"),
            stamp,
            encode(nonce),
            "POST",
            encode(target_path(path)),
            digest,
            encode(principal),
        ]
    )
    headers["HTTP_X_ISSUE_CONTENT_SHA256"] = digest
    headers["HTTP_X_ISSUE_PRINCIPAL_SIGNATURE"] = (
        base64.urlsafe_b64encode(hmac.new(b"synthetic-incidents-only", canonical.encode(), hashlib.sha256).digest())
        .decode()
        .rstrip("=")
    )
    response = APIClient().post(path, body, content_type=MULTIPART_CONTENT, **headers)
    assert response.status_code == 201, response.content
    fileid = str(response.data["id"])
    fetched = call(base + issue + "/files/" + fileid + "/")
    assert fetched.status_code == 200
    assert b"".join(fetched.streaming_content) == raw
    revoke_grants(state)
    assert call(base + issue + "/files/" + fileid + "/").status_code in {401, 403}


def test_report_scope_does_not_read_another_collectors_report_or_materials(reporting):
    destination, user, payload, state = reporting
    base = "/api/quality-auth/daq-reports/"
    first = call(base, {**payload, "hubProjectId": str(destination.id)}, "POST")
    assert first.status_code == 201

    assert call(base + first.data["issueId"] + "/", actor=17).status_code in {403, 404}
    assert call(
        base + first.data["issueId"] + "/packages/",
        {
            "defect_id": first.data["issueId"],
            "name": "foreign",
            "source_system": "ENGRAM_DAQ",
            "external_id": "foreign",
            "files": [],
        },
        "POST",
        actor=17,
    ).status_code in {403, 404}
    own = call(base, actor=17)
    assert own.status_code == 200 and own.data["count"] == 0


def test_project_directory_search_paginates_without_details(reporting):
    destination, user, payload, state = reporting
    for index in range(4):
        project = Project.objects.create(
            workspace=destination.workspace, name=f"Page project {index}", identifier=f"RP{index}"
        )
        values = json.loads(state["grants"].value)
        values["projects"].append(str(project.id))
        state["grants"].value = json.dumps(values)
        state["grants"].save()
    path = "/api/quality-auth/daq-project-options/?search=Page&per_page=2&page=2"
    response = call(path)
    assert response.status_code == 200, response.content
    assert response.data["count"] == 4 and len(response.data["results"]) == 2
    assert all(
        set(row) == {"hubProjectId", "projectName", "identifier", "workspace"} for row in response.data["results"]
    )


def test_automatic_report_only_diagnostic_never_fetches_project_knowledge(reporting, mocker):
    destination, user, payload, state = reporting
    base = "/api/quality-auth/daq-reports/"
    response = call(base, {**payload, "hubProjectId": str(destination.id)}, "POST")
    assert response.status_code == 201
    from plane.quality.models import DiagnosticJob
    from plane.quality.tasks import run_diagnostic

    file = registered_evidence(destination, user, response.data["issueId"])

    job = DiagnosticJob.objects.create(
        project=destination,
        defect_id=response.data["issueId"],
        created_by=user,
        request_id=uuid4(),
        mode="auto",
        result={"trigger": "materials_verified", "input": {"files": [str(file.id)]}},
    )
    mocker.patch("plane.quality.tasks.inspect", return_value=("ERROR connection refused", [{"read_bytes": 24}], []))
    mocker.patch("plane.quality.tasks.assistant.provider_config", return_value={"configured": True})
    knowledge = mocker.patch("plane.quality.tasks.search", return_value=[])
    mocker.patch("plane.quality.tasks.assistant.reference_payload", return_value=[])
    analyze = mocker.patch("plane.quality.tasks.analyze_diagnostic", return_value={"summary": "connection refused"})
    run_diagnostic(job.id)
    job.refresh_from_db()
    assert job.status == "completed", job.error_code
    knowledge.assert_not_called()
    assert analyze.call_count == 1
    revoked = DiagnosticJob.objects.create(
        project=destination,
        defect_id=response.data["issueId"],
        created_by=user,
        request_id=uuid4(),
        mode="auto",
        result={"trigger": "materials_verified", "input": {"files": ["present"]}},
    )
    revoke_grants(state)
    run_diagnostic(revoked.id)
    revoked.refresh_from_db()
    assert revoked.status == "failed" and revoked.error_code == "ACCESS_REVOKED"


def test_report_history_native_links_resolve_the_destination_workspace(reporting):
    destination, user, payload, state = reporting
    response = call("/api/quality-auth/daq-reports/", {**payload, "hubProjectId": str(destination.id)}, "POST")
    assert response.status_code == 201, response.content
    history = call("/api/quality-auth/daq-reports/")
    assert history.status_code == 200, history.content
    assert history.data["results"][0]["nativeUrl"].startswith(
        f"/{destination.workspace.slug}/p/{destination.identifier}/defects/"
    )
    assert "source_association_active" not in response.data


def test_report_only_diagnostic_rechecks_disabled_local_account(reporting, mocker):
    destination, user, payload, state = reporting
    response = call("/api/quality-auth/daq-reports/", {**payload, "hubProjectId": str(destination.id)}, "POST")
    assert response.status_code == 201, response.content
    from plane.quality.models import DiagnosticJob
    from plane.quality.tasks import run_diagnostic

    job = DiagnosticJob.objects.create(
        project=destination,
        defect_id=response.data["issueId"],
        created_by=user,
        request_id=uuid4(),
        mode="auto",
        result={"trigger": "materials_verified", "input": {"files": ["present"]}},
    )
    user.is_active = False
    user.save()
    inspect = mocker.patch("plane.quality.tasks.inspect")
    run_diagnostic(job.id)
    job.refresh_from_db()
    assert job.status == "failed" and job.error_code == "ACCESS_REVOKED"
    inspect.assert_not_called()


def test_report_chunk_upload_retries_and_bounded_download_preserve_complete_sha(reporting, settings, tmp_path, mocker):
    destination, user, payload, state = reporting
    settings.QUALITY_ATTACHMENT_ROOT = str(tmp_path)
    mocker.patch("plane.quality.diagnostics.enqueue")
    base = "/api/quality-auth/daq-reports/"
    created = call(base, {**payload, "hubProjectId": str(destination.id)}, "POST")
    issue = created.data["issueId"]
    raw = b"diagnostic context\n" * 500000
    digest = hashlib.sha256(raw).hexdigest()
    package = call(
        base + issue + "/packages/",
        {
            "name": "完整日志",
            "defect_id": issue,
            "source_system": "ENGRAM_DAQ",
            "external_id": "chunk-report",
            "files": [{"path": "large.log", "size": len(raw), "sha256": digest}],
        },
        "POST",
    )
    assert package.status_code == 201, package.content
    path = base + issue + "/packages/" + str(package.data["id"]) + "/files/"
    count = (len(raw) + 4 * 1024 * 1024 - 1) // (4 * 1024 * 1024)
    for index in [0, 0, *range(1, count)]:
        part = raw[index * 4 * 1024 * 1024 : (index + 1) * 4 * 1024 * 1024]
        result = upload_part(
            path,
            {
                "file": SimpleUploadedFile("chunk.bin", part),
                "manifest_path": "large.log",
                "chunk_index": str(index),
                "chunk_count": str(count),
            },
        )
        assert result.status_code == (201 if index == count - 1 else 202), result.content
    file_id = str(result.data["id"])
    preview_path = base + issue + "/files/" + file_id + "/preview/"
    metadata = call(preview_path + "?metadata=1")
    assert metadata.status_code == 200 and metadata.data["sha256"] == digest
    actual = bytearray()
    for offset in range(0, len(raw), 4 * 1024 * 1024):
        response = call(preview_path + f"?offset={offset}&length={min(4 * 1024 * 1024, len(raw) - offset)}")
        assert response.status_code == 206, response.content
        assert response["Content-Type"].startswith("text/plain")
        actual.extend(b"".join(response.streaming_content))
    assert bytes(actual) == raw and hashlib.sha256(actual).hexdigest() == digest
    from plane.quality.models import DiagnosticJob, PackageFile

    assert PackageFile.objects.filter(package_id=package.data["id"]).count() == 1
    assert DiagnosticJob.objects.filter(defect_id=issue).count() == 1
    foreign = call(base, {**payload, "hubProjectId": str(destination.id), "eventId": str(uuid4())}, "POST")
    wrong_file = call(base + foreign.data["issueId"] + "/files/" + file_id + "/download/")
    assert wrong_file.status_code == 404


def test_archived_or_deleted_workspace_is_not_reportable_after_publication(reporting):
    destination, user, payload, state = reporting
    from plane.db.models import Workspace

    Workspace.all_objects.filter(pk=destination.workspace_id).update(deleted_at=timezone.now())
    options = call("/api/quality-auth/daq-project-options/")
    assert options.status_code == 200
    assert str(destination.id) not in {row["hubProjectId"] for row in options.data["results"]}
    response = call("/api/quality-auth/daq-reports/", {**payload, "hubProjectId": str(destination.id)}, "POST")
    assert response.status_code == 404, response.content
    assert not Defect.objects.filter(project=destination).exists()


def test_report_only_diagnostic_discards_late_model_result_after_source_revocation(reporting, mocker):
    destination, user, payload, state = reporting
    response = call("/api/quality-auth/daq-reports/", {**payload, "hubProjectId": str(destination.id)}, "POST")
    from plane.quality.models import DiagnosticJob
    from plane.quality.tasks import run_diagnostic

    file = registered_evidence(destination, user, response.data["issueId"])

    job = DiagnosticJob.objects.create(
        project=destination,
        defect_id=response.data["issueId"],
        created_by=user,
        request_id=uuid4(),
        mode="auto",
        result={"trigger": "materials_verified", "input": {"files": [str(file.id)]}},
    )
    mocker.patch("plane.quality.tasks.inspect", return_value=("ERROR failed", [{"read_bytes": 12}], []))
    mocker.patch("plane.quality.tasks.assistant.provider_config", return_value={"configured": True})
    knowledge = mocker.patch("plane.quality.tasks.search")

    def revoke_during_analysis(*args):
        revoke_grants(state)
        return {"summary": "must not be published"}

    mocker.patch("plane.quality.tasks.analyze_diagnostic", side_effect=revoke_during_analysis)
    run_diagnostic(job.id)
    job.refresh_from_db()
    assert job.status == "failed" and job.error_code == "ACCESS_REVOKED" and job.result == {}
    knowledge.assert_not_called()


@pytest.mark.parametrize("package_owner", ["reporter", "technician"])
def test_report_only_progress_returns_status_without_internal_materials_or_diagnoses(
    reporting, settings, tmp_path, package_owner
):
    destination, user, payload, state = reporting
    settings.QUALITY_ATTACHMENT_ROOT = str(tmp_path)
    created = call("/api/quality-auth/daq-reports/", {**payload, "hubProjectId": str(destination.id)}, "POST")
    assert created.status_code == 201
    report_id = created.data["issueId"]
    from plane.db.models import User
    from plane.quality.models import DefectEvent, DiagnosticJob, PackageFile, ProblemPackage

    technician = User.objects.create(username="report-private-tech", email="report-private-tech@test.invalid")
    defect = Defect.objects.get(pk=report_id)
    defect.status = "resolved"
    defect.save(update_fields=["status", "updated_at"])
    DefectEvent.objects.create(
        project=destination, defect=defect, created_by=technician, status="in_progress", note="internal-event-sentinel"
    )
    DiagnosticJob.objects.create(
        project=destination,
        defect=defect,
        created_by=technician,
        request_id=uuid4(),
        mode="llm",
        status="completed",
        result={
            "method": "hybrid",
            "summary": "internal-knowledge-sentinel",
            "citations": [{"reference": "KN-PRIVATE"}],
        },
    )
    package = ProblemPackage.objects.create(
        project=destination,
        defect=defect,
        created_by=user if package_owner == "reporter" else technician,
        name="internal-file-sentinel",
        source_system="manual",
        external_id="tech-private",
    )
    raw = b"technical private material"
    file = PackageFile.objects.create(
        project=destination,
        package=package,
        created_by=technician,
        name="private.log",
        size=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        storage_key="private-tech-file.bin",
    )
    (tmp_path / file.storage_key).write_bytes(raw)
    response = call(f"/api/quality-auth/daq-reports/{report_id}/")
    assert response.status_code == 200, response.content
    assert set(response.data) == {"defect", "source", "timeline", "comments"}
    assert all(set(item) == {"id", "actor", "action", "created_at", "status"} for item in response.data["timeline"])
    assert set(response.data["defect"]) == {
        "id", "code", "title", "status", "created_at", "updated_at", "module", "assignee_name", "assignment_origin"
    }
    assert response.data["defect"]["status"] == "resolved"
    assert b"internal-" not in response.content and b"KN-PRIVATE" not in response.content
    fetched = call(f"/api/quality-auth/daq-reports/{report_id}/files/{file.id}/download/")
    assert fetched.status_code in {403, 404}, fetched.content


def test_report_timeline_uses_real_actors_and_state_changes_without_internal_notes(reporting):
    destination, user, payload, state = reporting
    from plane.db.models import User
    from plane.quality.models import DefectEvent

    technician = User.objects.create(
        username="timeline-tech", email="timeline-tech@test.invalid", display_name="本次技术员"
    )
    manager = User.objects.create(
        username="timeline-manager", email="timeline-manager@test.invalid", display_name="本次经理"
    )
    created = call("/api/quality-auth/daq-reports/", {**payload, "hubProjectId": str(destination.id)}, "POST")
    report_id = created.data["issueId"]
    defect = Defect.objects.get(pk=report_id)
    defect.assignee = manager
    defect.save(update_fields=["assignee", "updated_at"])
    events = []
    for actor, before, after in [
        (technician, "open", "in_progress"),
        (technician, "in_progress", "resolved"),
        (manager, "resolved", "closed"),
        (manager, "closed", "open"),
    ]:
        events.append(
            DefectEvent.objects.create(
                project=destination,
                defect=defect,
                created_by=actor,
                previous_status=before,
                status=after,
                note="private-event-body-sentinel",
            )
        )
    opaque = DefectEvent.objects.create(
        project=destination,
        defect=defect,
        created_by=technician,
        previous_status="in_progress",
        status="in_progress",
        note="internal-technical-plan-sentinel",
    )
    response = call(f"/api/quality-auth/daq-reports/{report_id}/")
    assert response.status_code == 200, response.content
    timeline = response.data["timeline"]
    assert [row["action"] for row in timeline] == [
        "提交反馈", "初步分派负责人", "开始处理", "提交回归", "验收关闭", "重新打开"
    ]
    assert [row["actor"] for row in timeline[2:]] == ["本次技术员", "本次技术员", "本次经理", "本次经理"]
    assert [row["id"] for row in timeline[2:]] == [str(event.id) for event in events]
    assert all(row["created_at"] for row in timeline)
    assert str(opaque.id) not in {row["id"] for row in timeline}
    assert b"private-event-body-sentinel" not in response.content
    assert b"internal-technical-plan-sentinel" not in response.content


def test_report_diagnostic_reads_only_materials_uploaded_by_its_reporter(reporting, settings, tmp_path, mocker):
    destination, user, payload, state = reporting
    settings.QUALITY_ATTACHMENT_ROOT = str(tmp_path)
    created = call("/api/quality-auth/daq-reports/", {**payload, "hubProjectId": str(destination.id)}, "POST")
    from plane.db.models import User
    from plane.quality.models import DiagnosticJob, PackageFile, ProblemPackage
    from plane.quality.tasks import run_diagnostic

    technician = User.objects.create(username="private-evidence-tech", email="private-evidence-tech@test.invalid")
    files = []
    for actor in [user, technician]:
        package = ProblemPackage.objects.create(
            project=destination,
            defect_id=created.data["issueId"],
            created_by=actor,
            name="evidence",
            source_system="manual",
            external_id=str(actor.id),
            status="files_verified",
        )
        raw = b"2026-11-10 ERROR own evidence" if actor == user else b"internal-tech-material-sentinel"
        file = PackageFile.objects.create(
            project=destination,
            package=package,
            created_by=actor,
            name="evidence.log",
            size=len(raw),
            sha256=hashlib.sha256(raw).hexdigest(),
            storage_key=f"{actor.id}.bin",
        )
        (tmp_path / file.storage_key).write_bytes(raw)
        files.append(file)
    job = DiagnosticJob.objects.create(
        project=destination,
        defect_id=created.data["issueId"],
        created_by=user,
        request_id=uuid4(),
        mode="auto",
        result={"trigger": "materials_verified", "input": {"files": [str(file.id) for file in files]}},
    )
    mocker.patch("plane.quality.tasks.assistant.provider_config", return_value={"configured": False})
    run_diagnostic(job.id)
    job.refresh_from_db()
    assert job.status == "completed", job.error_code
    assert {row["file_id"] for row in job.result["sources"]} == {str(files[0].id)}
    assert "internal-tech-material-sentinel" not in json.dumps(job.result)


def test_report_only_detail_returns_public_replies_without_internal_notes_or_cross_actor_access(reporting):
    from plane.quality.models import DefectComment

    destination, user, payload, state = reporting
    created = call("/api/quality-auth/daq-reports/", {**payload, "hubProjectId": str(destination.id)}, "POST")
    defect = Defect.objects.get(pk=created.data["issueId"])
    public = DefectComment.objects.create(
        project=destination, defect=defect, created_by=user, visibility="public", content="已修复，请复查"
    )
    DefectComment.objects.create(
        project=destination, defect=defect, created_by=user, visibility="internal", content="internal-reply-secret"
    )
    detail = call(f"/api/quality-auth/daq-reports/{defect.id}/")
    assert detail.status_code == 200
    assert detail.data["comments"] == [
        {"id": str(public.id), "content": public.content, "actor": user.display_name, "created_at": public.created_at}
    ]
    assert b"internal-reply-secret" not in detail.content
    assert call(f"/api/quality-auth/daq-reports/{defect.id}/", actor=99).status_code in {403, 404}
    defect.status = "closed"
    defect.save()
    assert len(call(f"/api/quality-auth/daq-reports/{defect.id}/").data["comments"]) == 1

def test_no_legal_owner_rejects_report_without_creating_defect_then_same_event_recovers(reporting):
    from plane.tests.contract.app.test_daq_reporting import call
    from plane.license.models import Instance, InstanceAdmin

    project, user, payload, _ = reporting
    InstanceAdmin.objects.all().delete()
    before = Defect.objects.count()
    request = {**payload, "hubProjectId": str(project.id)}
    response = call("/api/quality-auth/daq-reports/", request, "POST")
    assert response.status_code == 503 and "负责人未配置" in str(response.data), response.content
    assert Defect.objects.count() == before
    instance = Instance.objects.create(
        instance_name="recovery", instance_id=str(uuid4()), current_version="test", last_checked_at=timezone.now()
    )
    InstanceAdmin.objects.create(instance=instance, user=project.workspace.owner)
    response = call("/api/quality-auth/daq-reports/", request, "POST")
    assert response.status_code == 201, response.content
    defect = Defect.objects.get(pk=response.data["issueId"])
    assert defect.assignee_id == project.workspace.owner_id and defect.assignment_origin == "triage"
    assert not ProjectMember.objects.filter(project=project, member=user).exists()


def test_review_context_separates_collectors_sharing_one_service_actor(reporting):
    from plane.quality.models import DiagnosticJob
    from plane.quality.diagnostic_context import diagnostic_context

    destination, user, payload, state = reporting
    base = "/api/quality-auth/daq-reports/"
    first = call(base, {**payload, "hubProjectId": str(destination.id), "eventId": str(uuid4())}, "POST", actor=16)
    second = call(base, {**payload, "hubProjectId": str(destination.id), "eventId": str(uuid4())}, "POST", actor=17)
    third = call(base, {**payload, "hubProjectId": str(destination.id), "eventId": str(uuid4())}, "POST", actor=16)
    assert first.status_code == second.status_code == third.status_code == 201
    d1 = Defect.objects.get(pk=first.data["issueId"])
    d2 = Defect.objects.get(pk=second.data["issueId"])
    d3 = Defect.objects.get(pk=third.data["issueId"])
    assert d1.created_by_id == d2.created_by_id == d3.created_by_id
    file = registered_evidence(destination, d1.created_by, d1.id)
    source = {
        "file_id": str(file.id),
        "sha256": file.sha256,
        "scan_incomplete": False,
        "preview_truncated": False,
        "excerpt": "ERROR storage_quota_exceeded limit=12 used=13",
    }
    reviewed = DiagnosticJob.objects.create(
        project=destination,
        defect=d1,
        created_by=d1.created_by,
        status="completed",
        mode="auto",
        request_id=uuid4(),
        feedback="unhelpful",
        feedback_note="仅账号16的私有评价",
        result={"sources": [source], "feedback_review": {"actor_id": "reviewer"}},
    )
    for target, expected in [(d2, False), (d3, True)]:
        current = DiagnosticJob.objects.create(
            project=destination, defect=target, created_by=target.created_by, mode="auto", request_id=uuid4()
        )
        current_file = registered_evidence(destination, target.created_by, target.id)
        current_source = {**source, "file_id": str(current_file.id), "sha256": current_file.sha256}
        refs = diagnostic_context(current, report_only=True, sources=[current_source])
        assert any(ref["reference"] == f"REVIEW-{reviewed.id}" for ref in refs) is expected
