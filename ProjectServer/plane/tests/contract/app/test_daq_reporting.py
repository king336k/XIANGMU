"""DAQ reporting destination is independent from project membership."""

import hashlib
import json
from uuid import uuid4
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient
from plane.db.models import Project, ProjectMember, WorkspaceMember
from plane.quality.models import BusinessRole, PlatformAccount, PlatformIdentity, PlatformProject, Defect, SourceLink
from plane.tests.contract.app.test_daq_incidents import incident as incident, signature

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
def reporting(incident, mocker):
    project, user, base, payload, state, post = incident
    PlatformAccount.objects.create(
        user=user,
        source_instance="test-dp",
        external_user_id=16,
        source_username="test-collector",
        source_role="Collector",
    )
    destination = Project.objects.create(workspace=project.workspace, name="任意目标项目", identifier="ANYDEST")
    from plane.quality import platform

    original_fetch = platform.fetch

    def source_with_username(source, path, params=None):
        result = original_fetch(source, path, params)
        if path.startswith("/internal/issue-users/"):
            return {**result, "username": "test-collector"}
        if path.startswith("/internal/issue-permissions/"):
            return {**result, "projects": [{"role": "Member", **row} for row in result["projects"]]}
        return result

    mocker.patch("plane.quality.platform.fetch", side_effect=source_with_username)
    return destination, user, payload, state


def call(path, data=None, method="GET", actor=16, headers=None):
    body = json.dumps(data or {}, separators=(",", ":"), ensure_ascii=False)
    supplied = headers or signature(path, "" if method == "GET" else body, actor=actor, method=method)
    client = APIClient()
    return (
        client.get(path, **supplied)
        if method == "GET"
        else client.post(path, body, content_type="application/json", **supplied)
    )


def test_collector_can_choose_all_nonarchived_projects_without_membership(reporting):
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


def test_unsigned_replay_and_demoted_source_cannot_use_project_directory(reporting):
    destination, user, payload, state = reporting
    path = "/api/quality-auth/daq-project-options/"
    assert APIClient().get(path).status_code in {401, 403}
    headers = signature(path, "", method="GET")
    assert call(path, headers=headers).status_code == 200
    assert call(path, headers=headers).status_code in {401, 403}
    state["role"] = "Auditor"
    assert call(path).status_code in {401, 403}


def test_report_without_session_creates_mapping_and_no_project_membership_idempotently(reporting):
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
    assert (
        PlatformProject.objects.filter(project=destination, source_instance="test-dp", external_project_id=9).count()
        == 1
    )
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


@pytest.mark.parametrize("boundary", ["wrong_task", "revoked_project", "archived_target", "invalid_category"])
def test_report_rejects_source_authority_or_target_without_partial_mapping(reporting, boundary):
    destination, user, payload, state = reporting
    data = {**payload, "hubProjectId": str(destination.id)}
    if boundary == "wrong_task":
        state["context"]["projectId"] = 999
    elif boundary == "revoked_project":
        state["projects"] = []
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
    state["projects"] = []
    assert call(base + issue + "/files/" + fileid + "/").status_code in {401, 403}


def test_report_scope_does_not_read_another_collectors_report_or_materials(reporting):
    destination, user, payload, state = reporting
    base = "/api/quality-auth/daq-reports/"
    first = call(base, {**payload, "hubProjectId": str(destination.id)}, "POST")
    assert first.status_code == 201
    from plane.db.models import User

    other = User.objects.create(username="other-reporter", email="other-reporter@test.invalid")
    PlatformAccount.objects.create(
        user=other,
        source_instance="test-dp",
        external_user_id=17,
        source_username="other-reporter",
        source_role="Collector",
    )
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


def test_first_report_creates_only_source_account_not_membership(reporting, mocker):
    destination, user, payload, state = reporting
    PlatformAccount.objects.filter(user=user).delete()
    mocker.patch("plane.quality.data_accounts.authority_config", return_value={"login_auto_provision": True})
    counts = (
        WorkspaceMember.objects.count(),
        ProjectMember.objects.count(),
        BusinessRole.objects.count(),
        PlatformIdentity.objects.count(),
    )
    response = call("/api/quality-auth/daq-reports/", {**payload, "hubProjectId": str(destination.id)}, "POST")
    assert response.status_code == 201, response.content
    account = PlatformAccount.objects.get(source_instance="test-dp", external_user_id=16)
    assert account.user_id != user.id and not account.user.has_usable_password()
    assert counts == (
        WorkspaceMember.objects.count(),
        ProjectMember.objects.count(),
        BusinessRole.objects.count(),
        PlatformIdentity.objects.count(),
    )
    assert Defect.objects.get(pk=response.data["issueId"]).created_by_id == account.user_id


def test_source_account_disabled_and_invalid_project_target_do_not_bypass_reporting(reporting):
    destination, user, payload, state = reporting
    account = PlatformAccount.objects.get(user=user)
    account.active = False
    account.save()
    assert call("/api/quality-auth/daq-project-options/").status_code in {401, 403}
    account.active = True
    account.save()
    invalid = call("/api/quality-auth/daq-reports/", {**payload, "hubProjectId": "wrong"}, "POST")
    assert invalid.status_code == 400
    assert not Defect.objects.filter(project=destination).exists()


def test_project_directory_search_paginates_without_details(reporting):
    destination, user, payload, state = reporting
    for index in range(4):
        Project.objects.create(workspace=destination.workspace, name=f"Page project {index}", identifier=f"RP{index}")
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
    state["projects"] = []
    run_diagnostic(revoked.id)
    revoked.refresh_from_db()
    assert revoked.status == "failed" and revoked.error_code == "ACCESS_REVOKED"


def test_existing_disabled_mapping_stays_disabled_and_report_receipt_shows_it(reporting):
    destination, user, payload, state = reporting
    mapping = PlatformProject.objects.create(
        project=destination, source_instance="test-dp", external_project_id=9, active=False
    )
    response = call("/api/quality-auth/daq-reports/", {**payload, "hubProjectId": str(destination.id)}, "POST")
    assert response.status_code == 201, response.content
    mapping.refresh_from_db()
    assert not mapping.active
    assert response.data["source_association_active"] is False
    assert PlatformProject.objects.filter(project=destination).count() == 1


def test_report_history_native_links_resolve_the_destination_workspace(reporting):
    destination, user, payload, state = reporting
    response = call("/api/quality-auth/daq-reports/", {**payload, "hubProjectId": str(destination.id)}, "POST")
    assert response.status_code == 201, response.content
    history = call("/api/quality-auth/daq-reports/")
    assert history.status_code == 200, history.content
    assert history.data["results"][0]["nativeUrl"].startswith(
        f"/{destination.workspace.slug}/p/{destination.identifier}/defects/"
    )
    assert response.data["source_association_active"] is True


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
    account = PlatformAccount.objects.get(user=user)
    account.active = False
    account.save()
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


def test_source_collector_with_real_data_platform_project_member_role_can_report(reporting):
    destination, user, payload, state = reporting
    state["projects"] = [{"id": 9, "role": "Member"}]
    response = call("/api/quality-auth/daq-reports/", {**payload, "hubProjectId": str(destination.id)}, "POST")
    assert response.status_code == 201, response.content
    assert Defect.objects.filter(project=destination).exists()


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
        state["projects"] = []
        return {"summary": "must not be published"}

    mocker.patch("plane.quality.tasks.analyze_diagnostic", side_effect=revoke_during_analysis)
    run_diagnostic(job.id)
    job.refresh_from_db()
    assert job.status == "failed" and job.error_code == "ACCESS_REVOKED" and job.result == {}
    knowledge.assert_not_called()


def test_automatic_source_association_preserves_verified_project_and_task_names(reporting):
    destination, user, payload, state = reporting
    state["context"].update(projectName="生产采集项目", taskName="机械臂抓取任务")
    response = call("/api/quality-auth/daq-reports/", {**payload, "hubProjectId": str(destination.id)}, "POST")
    assert response.status_code == 201, response.content
    assert response.data["platformProjectName"] == "生产采集项目"
    assert response.data["platformTaskName"] == "机械臂抓取任务"
    mapping = PlatformProject.objects.get(project=destination, source_instance="test-dp", external_project_id=9)
    assert mapping.name == "生产采集项目"
    detail = call("/api/quality-auth/daq-reports/" + response.data["issueId"] + "/")
    assert detail.status_code == 200 and detail.data["source"]["platformTaskName"] == "机械臂抓取任务"


def test_reporter_can_link_verified_baseline_session_without_gaining_project_access(reporting):
    destination, user, payload, state = reporting
    base = "/api/quality-auth/daq-reports/"
    created = call(base, {**payload, "hubProjectId": str(destination.id)}, "POST")
    report_id = created.data["issueId"]
    path = base + report_id + "/session/"
    state["context"].update(sourceSessionId="actual-baseline", dataPackageId="actual-baseline-package")
    first = call(path, {"sourceSessionId": "actual-baseline", "platformTaskId": 24}, "POST")
    assert first.status_code == 201, first.content
    assert first.data["sourceSessionId"] == "actual-baseline"
    assert first.data["dataPackageId"] == "actual-baseline-package"
    again = call(path, {"sourceSessionId": "actual-baseline", "platformTaskId": 24}, "POST")
    assert again.status_code == 200 and again.data["verifiedSessions"] == first.data["verifiedSessions"]
    assert SourceLink.objects.filter(defect_id=report_id, record_type="verified_session").count() == 1
    assert not ProjectMember.objects.filter(project=destination, member=user).exists()
    wrong = call(path, {"sourceSessionId": "actual-baseline", "platformTaskId": 25}, "POST")
    assert wrong.status_code == 409, wrong.content


@pytest.mark.parametrize("boundary", ["foreign_actor", "wrong_project", "wrong_session", "missing_package"])
def test_report_baseline_session_rejects_unverified_authority_and_cross_actor(reporting, boundary):
    destination, user, payload, state = reporting
    base = "/api/quality-auth/daq-reports/"
    created = call(base, {**payload, "hubProjectId": str(destination.id)}, "POST")
    report_id = created.data["issueId"]
    state["context"].update(sourceSessionId="actual-session", dataPackageId="actual-package")
    actor = 16
    if boundary == "foreign_actor":
        from plane.db.models import User

        other = User.objects.create(username="session-other", email="session-other@test.invalid")
        PlatformAccount.objects.create(
            user=other, source_instance="test-dp", external_user_id=17, source_username="other", source_role="Collector"
        )
        actor = 17
    elif boundary == "wrong_project":
        state["context"]["projectId"] = 999
    elif boundary == "wrong_session":
        state["context"]["sourceSessionId"] = "other-session"
    else:
        state["context"]["dataPackageId"] = None
    response = call(
        base + report_id + "/session/", {"sourceSessionId": "actual-session", "platformTaskId": 24}, "POST", actor=actor
    )
    assert response.status_code in {403, 404}, response.content
    assert not SourceLink.objects.filter(defect_id=report_id, record_type="verified_session").exists()


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
    assert set(response.data) == {"defect", "source", "timeline"}
    assert all(set(item) == {"id", "actor", "action", "created_at", "status"} for item in response.data["timeline"])
    assert set(response.data["defect"]) == {"id", "code", "title", "status", "created_at", "updated_at"}
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
    assert [row["action"] for row in timeline] == ["提交反馈", "开始处理", "提交回归", "验收关闭", "重新打开"]
    assert [row["actor"] for row in timeline[1:]] == ["本次技术员", "本次技术员", "本次经理", "本次经理"]
    assert [row["id"] for row in timeline[1:]] == [str(event.id) for event in events]
    assert all(row["created_at"] for row in timeline)
    assert str(opaque.id) not in {row["id"] for row in timeline}
    assert b"private-event-body-sentinel" not in response.content
    assert b"internal-technical-plan-sentinel" not in response.content


def test_report_timeline_includes_only_its_testers_structured_regression_results(reporting):
    destination, user, payload, state = reporting
    from plane.db.models import Issue, User
    from plane.quality.models import (
        CaseRevision,
        DaqBinding,
        DataRegression,
        DefectEvent,
        PlanItem,
        Solution,
        SolutionRevision,
        TestCase,
        TestExecution,
        TestPlan,
    )

    tester = User.objects.create(
        username="timeline-tester", email="timeline-tester@test.invalid", display_name="本次测试员"
    )
    created = call("/api/quality-auth/daq-reports/", {**payload, "hubProjectId": str(destination.id)}, "POST")
    report_id = created.data["issueId"]
    defect = Defect.objects.get(pk=report_id)
    DefectEvent.objects.create(
        project=destination, defect=defect, created_by=user, previous_status="in_progress", status="resolved"
    )
    issue = Issue.objects.create(project=destination, workspace=destination.workspace, name="private-repair-task")
    binding = DaqBinding.objects.create(
        project=destination, issue=issue, source_instance="test-dp", platform_task_id=24, source_record_id="old-session"
    )
    solution = Solution.objects.create(
        project=destination,
        defect=defect,
        title="private-solution",
        root_cause="private-root-cause",
        steps="private-steps",
        verification="private-verification",
    )
    revision = SolutionRevision.objects.create(
        project=destination, solution=solution, version=1, snapshot={}, reviewer_ids=[], required_count=1
    )
    plan = TestPlan.objects.create(
        project=destination, name="private-plan", build="v2", environment="private-environment", managed=True
    )
    DataRegression.objects.create(
        project=destination,
        plan=plan,
        defect=defect,
        solution_revision=revision,
        binding=binding,
        fixed_build="v2",
        resolved_at=timezone.now(),
        round_started_at=timezone.now(),
    )
    case = TestCase.objects.create(project=destination, title="private-case-title", steps=[])
    case_revision = CaseRevision.objects.create(
        project=destination, case=case, version=1, title=case.title, snapshot={}
    )
    item = PlanItem.objects.create(project=destination, plan=plan, case=case, revision=case_revision)
    visible = []
    for result in ["failed", "blocked", "inconclusive", "passed", "skipped"]:
        execution = TestExecution.objects.create(
            project=destination,
            item=item,
            created_by=tester,
            request_id=uuid4(),
            result=result,
            actual_result="private-actual-result-sentinel",
            evidence="private-evidence-sentinel",
            step_results=[{"actual": "private-step-sentinel"}],
        )
        if result != "skipped":
            visible.append(execution)
    unrelated_plan = TestPlan.objects.create(project=destination, name="unrelated-plan", build="v2", environment="env")
    unrelated_item = PlanItem.objects.create(
        project=destination, plan=unrelated_plan, case=case, revision=case_revision
    )
    unrelated = TestExecution.objects.create(
        project=destination,
        item=unrelated_item,
        created_by=tester,
        request_id=uuid4(),
        result="passed",
        actual_result="unrelated-execution-sentinel",
    )
    DefectEvent.objects.create(
        project=destination, defect=defect, created_by=user, previous_status="resolved", status="closed"
    )
    response = call(f"/api/quality-auth/daq-reports/{report_id}/")
    assert response.status_code == 200, response.content
    timeline = response.data["timeline"]
    execution_rows = [row for row in timeline if row["actor"] == "本次测试员"]
    assert [row["action"] for row in execution_rows] == ["回归失败", "回归未完成", "回归未完成", "回归通过"]
    assert {row["id"] for row in execution_rows} == {"execution:" + str(execution.id) for execution in visible}
    assert all(set(row) == {"id", "actor", "action", "created_at", "status"} for row in execution_rows)
    assert all(row["status"] == "resolved" for row in execution_rows)
    assert timeline[-1]["action"] == "验收关闭" and timeline[-1]["status"] == "closed"
    assert "execution:" + str(unrelated.id) not in {row["id"] for row in timeline}
    assert b"private-" not in response.content and b"unrelated-" not in response.content


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
