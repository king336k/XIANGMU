"""Latest DAQ payload maps only through server-managed native source bindings."""

from uuid import uuid4
import pytest
from plane.db.models import Project, ProjectMember, Issue, User

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def daq(session_client, workspace, create_user):
    p = Project.objects.create(workspace=workspace, name="DAQ联调", identifier="DAQ")
    ProjectMember.objects.create(project=p, member=create_user, role=20)
    issue = Issue.objects.create(project=p, workspace=workspace, name="来源平台任务")
    base = f"/api/workspaces/{workspace.slug}/projects/{p.id}/quality/"
    payload = {
        "source_instance": "daq-local-integration",
        "platform_task_id": 24,
        "source_record_id": "daq-session-1106",
        "issue_id": str(issue.id),
        "device": "robot-test",
        "package_id": "pkg-test",
    }
    r = session_client.post(base + "daq/bindings/", payload, format="json")
    assert r.status_code == 201, r.content
    return base, p, create_user


def report(client, base, key, **extra):
    return client.post(
        base + "daq/reports/",
        {
            "sourceRecordId": "daq-session-1106",
            "platformTaskId": 24,
            "category": "DataAnomaly",
            "title": "采集异常",
            "description": "真实诊断摘要",
            "sourceSnapshot": '{"projectId":999}',
            **extra,
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=key,
    )


def test_daq_report_retry_and_intentional_multiple_reports(session_client, daq):
    base, p, user = daq
    key = str(uuid4())
    first = report(session_client, base, key)
    assert first.status_code == 201, first.content
    retry = report(session_client, base, key)
    assert retry.status_code == 200 and retry.data["issueId"] == first.data["issueId"]
    assert first.data["issueCode"] == "DAQ-D-1" and retry.data["issueCode"] == first.data["issueCode"]
    assert report(session_client, base, key, title="改变正文").status_code == 409
    second = report(session_client, base, str(uuid4()))
    assert second.status_code == 201 and second.data["issueId"] != first.data["issueId"]
    history = session_client.post(
        base + "daq/source-links/query/",
        {"records": [{"sourceRecordId": "daq-session-1106", "platformTaskId": 24}]},
        format="json",
    )
    assert history.status_code == 200 and len(history.data) == 2
    assert history.data[0]["sourceIssueCount"] == 2
    assert second.data["status"] == "open" and second.data["issueCode"] == "DAQ-D-2"
    assert second.data["nativeUrl"] == f"/{p.workspace.slug}/p/DAQ/defects/?defect={second.data['issueId']}"


def test_daq_native_detail_keeps_uuid_author_and_current_regressions(session_client, daq, workspace):
    base, project, user = daq
    first = report(session_client, base, str(uuid4()))
    response = session_client.get(base + f"daq/issues/{first.data['issueId']}/")
    assert response.status_code == 200, response.content
    assert response.data["defect"]["id"] == first.data["issueId"]
    assert response.data["defect"]["created_by_id"] == str(user.id)
    assert response.data["packages"] == [] and response.data["regressions"] == []
    other = Project.objects.create(workspace=workspace, name="隔离项目", identifier="DQOTHER")
    ProjectMember.objects.create(project=other, member=user, role=20)
    other_base = base.replace(str(project.id), str(other.id))
    assert session_client.get(other_base + f"daq/issues/{first.data['issueId']}/").status_code == 404
    assert session_client.get(base + "daq/context/").status_code == 200


def test_binding_scope_missing_key_and_untrusted_identity_rejected(session_client, daq, workspace):
    base, p, user = daq
    assert report(session_client, base, "").status_code == 400
    assert report(session_client, base, str(uuid4()), sourceRecordId="unknown").status_code == 404
    other = Project.objects.create(workspace=workspace, name="其他项目", identifier="DOTHER")
    foreign = Issue.objects.create(project=other, workspace=workspace, name="其他任务")
    bad = session_client.post(
        base + "daq/bindings/",
        {"source_instance": "daq", "platform_task_id": 12, "source_record_id": "x", "issue_id": str(foreign.id)},
        format="json",
    )
    assert bad.status_code == 400
    guest = User.objects.create(email="untrusted@daq.local", username="untrusted")
    session_client.force_authenticate(user=guest)
    assert report(session_client, base, str(uuid4())).status_code == 403


@pytest.mark.parametrize("nonce_style", ["uuid", "base64url"])
def test_platform_v2_identity_signature_replay_and_native_project_mapping(api_client, session_client, daq, settings, nonce_style):
    import base64
    import hashlib
    import hmac
    import json
    import time

    base, p, user = daq
    mapping = session_client.post(
        base + "daq/identities/",
        {"source_instance": "data-platform-test", "external_user_id": 16, "user_id": str(user.id)},
        format="json",
    )
    assert mapping.status_code == 201, mapping.content
    settings.QUALITY_BRIDGE_KEYS = {
        "test-key": {
            "secret": "test-secret-not-a-live-key",
            "audience": "plane-quality",
            "source_instance": "data-platform-test",
        }
    }
    url = base + "daq/source-links/query/"
    body = json.dumps(
        {"records": [{"sourceRecordId": "daq-session-1106", "platformTaskId": 24}]}, separators=(",", ":")
    )
    principal = json.dumps(
        {"id": 16, "username": "collector-example", "displayName": "采集员"}, separators=(",", ":"), ensure_ascii=False
    )

    def enc(value):
        return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")

    timestamp = str(int(time.time()))
    nonce = str(uuid4()) if nonce_style == "uuid" else "Java_nonce-base64_" + uuid4().hex[:12]
    digest = hashlib.sha256(body.encode()).hexdigest()
    canonical = "\n".join(
        [
            "ISSUE-IDENTITY-V2",
            enc("plane-quality"),
            enc("test-key"),
            timestamp,
            enc(nonce),
            "POST",
            enc(url),
            digest,
            enc(principal),
        ]
    )
    signature = (
        base64.urlsafe_b64encode(hmac.new(b"test-secret-not-a-live-key", canonical.encode(), hashlib.sha256).digest())
        .decode()
        .rstrip("=")
    )
    headers = {
        "HTTP_X_ISSUE_IDENTITY_VERSION": "2",
        "HTTP_X_ISSUE_KEY_ID": "test-key",
        "HTTP_X_ISSUE_AUDIENCE": "plane-quality",
        "HTTP_X_ISSUE_PRINCIPAL": principal,
        "HTTP_X_ISSUE_PRINCIPAL_TIMESTAMP": timestamp,
        "HTTP_X_ISSUE_PRINCIPAL_NONCE": nonce,
        "HTTP_X_ISSUE_CONTENT_SHA256": digest,
        "HTTP_X_ISSUE_PRINCIPAL_SIGNATURE": signature,
    }
    api_client.force_authenticate(user=None)
    from unittest.mock import patch

    with patch("plane.quality.platform.verify_identity"):
        accepted = api_client.post(url, body, content_type="application/json", **headers)
    assert accepted.status_code == 200, accepted.content
    assert api_client.post(url, body, content_type="application/json", **headers).status_code in [401, 403]
    nonce2 = str(uuid4())
    headers["HTTP_X_ISSUE_PRINCIPAL_NONCE"] = nonce2
    assert api_client.post(url, body, content_type="application/json", **headers).status_code in [401, 403]


def test_platform_multipart_digest_matches_java_manifest_and_rejects_tampering():
    import hashlib
    from plane.quality.identity import multipart_digest, encode

    body = (
        b'--sample\r\nContent-Disposition: form-data; name="request"\r\n'
        b"Content-Type: application/json\r\n\r\n{}\r\n--sample\r\n"
        b'Content-Disposition: form-data; name="files"; filename="recording.log"\r\n'
        b"Content-Type: text/plain\r\n\r\nhello\r\n--sample--\r\n"
    )
    lines = ["ISSUE-MULTIPART-MANIFEST-V1"]
    for index, name, filename, kind, raw in [
        (0, "request", "", "application/json", b"{}"),
        (1, "files", "recording.log", "text/plain", b"hello"),
    ]:
        lines += [
            str(index),
            encode(name),
            encode(filename),
            encode(kind),
            str(len(raw)),
            hashlib.sha256(raw).hexdigest(),
        ]
    expected = hashlib.sha256("\n".join(lines).encode()).hexdigest()
    assert multipart_digest(body, "multipart/form-data; boundary=sample") == expected
    assert multipart_digest(body.replace(b"hello", b"other"), "multipart/form-data; boundary=sample") != expected


def test_platform_revocation_and_task_rebinding_fail_closed(session_client, daq):
    from unittest.mock import patch
    from plane.quality.models import PlatformIdentity, PlatformProject, DaqBinding
    from plane.quality.platform import verify_identity, verify_binding
    from rest_framework.exceptions import AuthenticationFailed

    base, project, user = daq
    PlatformProject.objects.create(project=project, source_instance="daq-local-integration", external_project_id=3)
    identity = PlatformIdentity.objects.create(
        project=project, source_instance="daq-local-integration", external_user_id=16, user=user
    )
    with patch(
        "plane.quality.platform.fetch",
        side_effect=[{"id": 16, "active": True, "role": "Collector"}, {"projects": [{"id": 3, "role": "Collector"}]}],
    ):
        assert verify_identity(identity).external_project_id == 3
    with patch(
        "plane.quality.platform.fetch",
        side_effect=[{"id": 16, "active": False}, {"projects": [{"id": 3, "role": "Collector"}]}],
    ):
        with pytest.raises(AuthenticationFailed):
            verify_identity(identity)
    with patch(
        "plane.quality.platform.fetch", side_effect=[{"id": 16, "active": True, "role": "Collector"}, {"projects": []}]
    ):
        with pytest.raises(AuthenticationFailed):
            verify_identity(identity)
    binding = DaqBinding.objects.get(project=project)
    with patch(
        "plane.quality.platform.fetch", return_value={"taskId": 24, "projectId": 99, "dataPackageId": "pkg-test"}
    ):
        with pytest.raises(AuthenticationFailed):
            verify_binding(binding)


def test_bridge_query_is_filtered_to_authenticated_source(session_client, daq):
    from plane.quality.models import DaqBinding, DaqReport, Defect

    base, project, user = daq
    binding = DaqBinding.objects.get(project=project)
    defect = Defect.objects.create(project=project, title="其他来源私有描述")
    DaqReport.objects.create(
        project=project,
        created_by=user,
        binding=binding,
        defect=defect,
        request_id=uuid4(),
        request_hash="a" * 64,
        category="Other",
    )
    session_client.force_authenticate(user=user, token={"source_instance": "other-platform"})
    response = session_client.post(
        base + "daq/source-links/query/",
        {"records": [{"sourceRecordId": binding.source_record_id, "platformTaskId": binding.platform_task_id}]},
        format="json",
    )
    assert response.status_code == 200 and response.data == []


def test_signed_multipart_rejects_transfer_encoding_parser_ambiguity():
    from plane.quality.identity import multipart_digest
    from rest_framework.exceptions import AuthenticationFailed

    body = (
        b'--sample\r\nContent-Disposition: form-data; name="title"\r\n'
        b"Content-Transfer-Encoding: quoted-printable\r\n\r\n=61=62=63\r\n--sample--\r\n"
    )
    with pytest.raises(AuthenticationFailed):
        multipart_digest(body, "multipart/form-data; boundary=sample")


def test_signed_multipart_rejects_duplicate_and_extended_disposition_params():
    from plane.quality.identity import multipart_digest
    from rest_framework.exceptions import AuthenticationFailed

    for disposition in [
        'form-data; name="title"; name="description"',
        "form-data; name=\"title\"; name*=utf-8''description",
    ]:
        body = ("--sample\r\nContent-Disposition: " + disposition + "\r\n\r\nabc\r\n--sample--\r\n").encode()
        with pytest.raises(AuthenticationFailed):
            multipart_digest(body, "multipart/form-data; boundary=sample")


def test_platform_task_context_must_identify_exact_source_session(session_client, daq):
    from unittest.mock import patch
    from plane.quality.models import PlatformProject, DaqBinding
    from plane.quality.platform import verify_binding
    from rest_framework.exceptions import AuthenticationFailed

    base, project, user = daq
    PlatformProject.objects.create(project=project, source_instance="daq-local-integration", external_project_id=3)
    binding = DaqBinding.objects.get(project=project)
    for source in [None, "wrong-session"]:
        with patch(
            "plane.quality.platform.fetch",
            return_value={"taskId": 24, "projectId": 3, "dataPackageId": "pkg-test", "sourceSessionId": source},
        ):
            with pytest.raises(AuthenticationFailed):
                verify_binding(binding)


@pytest.mark.parametrize(
    "method,suffix,expected", [("GET", "search/", 200), ("GET", "status/", 200), ("POST", "chat/", 503)]
)
def test_native_daq_knowledge_uses_verified_identity_and_keeps_model_unconfigured(
    api_client, daq, settings, mocker, method, suffix, expected
):
    import base64
    import hashlib
    import hmac
    import json
    import time
    from plane.quality.models import PlatformIdentity

    base, project, user = daq
    PlatformIdentity.objects.create(project=project, user=user, source_instance="native-knowledge", external_user_id=42)
    settings.QUALITY_BRIDGE_KEYS = {
        "knowledge-test": {"secret": "fixture-only", "audience": "quality", "source_instance": "native-knowledge"}
    }
    mocker.patch("plane.quality.platform.verify_identity")
    mocker.patch("plane.knowledge.assistant.provider_config", return_value={"configured": False})
    path = base.replace("/quality/", "/knowledge/") + suffix
    body = json.dumps({"query": "故障排查", "request_id": str(uuid4())}).encode() if method == "POST" else b""

    def enc(value):
        return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")

    timestamp, nonce = str(int(time.time())), uuid4().hex
    digest = hashlib.sha256(body).hexdigest() if method == "POST" else "-"
    principal = json.dumps({"id": 42, "username": "collector"}, separators=(",", ":"))
    canonical = "\n".join(
        [
            "ISSUE-IDENTITY-V2",
            enc("quality"),
            enc("knowledge-test"),
            timestamp,
            enc(nonce),
            method,
            enc(path),
            digest,
            enc(principal),
        ]
    )
    signature = (
        base64.urlsafe_b64encode(hmac.new(b"fixture-only", canonical.encode(), hashlib.sha256).digest())
        .decode()
        .rstrip("=")
    )
    api_client.force_authenticate(user=None)
    response = api_client.generic(
        method,
        path,
        body,
        content_type="application/json",
        **{
            "HTTP_X_ISSUE_IDENTITY_VERSION": "2",
            "HTTP_X_ISSUE_KEY_ID": "knowledge-test",
            "HTTP_X_ISSUE_AUDIENCE": "quality",
            "HTTP_X_ISSUE_PRINCIPAL": principal,
            "HTTP_X_ISSUE_PRINCIPAL_TIMESTAMP": timestamp,
            "HTTP_X_ISSUE_PRINCIPAL_NONCE": nonce,
            "HTTP_X_ISSUE_CONTENT_SHA256": digest,
            "HTTP_X_ISSUE_PRINCIPAL_SIGNATURE": signature,
        },
    )
    assert response.status_code == expected, response.content
    if suffix == "status/":
        assert response.data["configured"] is False
    if suffix == "chat/":
        assert response.data["code"] == "AI_NOT_CONFIGURED"


def test_signed_new_session_uses_authoritative_package_and_existing_task_mapping(api_client, daq, mocker):
    from plane.quality.models import DaqBinding, PlatformProject

    base, project, user = daq
    PlatformProject.objects.create(project=project, source_instance="daq-local-integration", external_project_id=3)
    from plane.quality.models import PlatformIdentity
    PlatformIdentity.objects.create(project=project, source_instance="daq-local-integration", external_user_id=42, user=user)
    mocker.patch("plane.quality.platform.verify_identity")
    api_client.force_authenticate(user=None)
    mocker.patch(
        "plane.quality.identity.PlatformBridgeAuthentication.authenticate",
        return_value=(user, {"source_instance": "daq-local-integration", "external_user_id": 42}),
    )
    context = {
        "projectId": 3,
        "taskId": 24,
        "sourceSessionId": "new-authoritative-session",
        "dataPackageId": "new-authoritative-package",
        "deviceName": "机器人甲",
    }
    mocker.patch("plane.quality.platform.fetch", return_value=context)
    response = report(api_client, base, str(uuid4()), sourceRecordId="new-authoritative-session")
    assert response.status_code == 201, response.content
    binding = DaqBinding.objects.get(project=project, source_record_id="new-authoritative-session")
    assert binding.package_id == "new-authoritative-package"
    assert binding.issue_id == DaqBinding.objects.get(project=project, source_record_id="daq-session-1106").issue_id
    context["projectId"] = 999
    assert report(api_client, base, str(uuid4()), sourceRecordId="different-project-session").status_code == 403
    assert not DaqBinding.objects.filter(project=project, source_record_id="different-project-session").exists()


def test_signed_daq_discovers_only_its_approved_native_project(api_client, daq, settings, mocker):
    import base64
    import hashlib
    import hmac
    import json
    import time
    from plane.quality.models import PlatformIdentity, PlatformProject

    base, project, user = daq
    PlatformProject.objects.create(project=project, source_instance="discovery", external_project_id=3)
    PlatformIdentity.objects.create(project=project, user=user, source_instance="discovery", external_user_id=42)
    settings.QUALITY_BRIDGE_KEYS = {
        "discover": {"secret": "fixture-only", "audience": "quality", "source_instance": "discovery"}
    }
    mocker.patch("plane.quality.platform.verify_identity")
    api_client.force_authenticate(user=None)

    def request(external):
        def enc(text):
            return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")

        target = f"/api/quality-auth/daq-project/?platform_project_id={external}"
        stamp, nonce = str(int(time.time())), uuid4().hex
        principal = json.dumps({"id": 42, "username": "collector"}, separators=(",", ":"))
        canonical = "\n".join(
            [
                "ISSUE-IDENTITY-V2",
                enc("quality"),
                enc("discover"),
                stamp,
                enc(nonce),
                "GET",
                enc(target),
                "-",
                enc(principal),
            ]
        )
        signature = (
            base64.urlsafe_b64encode(hmac.new(b"fixture-only", canonical.encode(), hashlib.sha256).digest())
            .decode()
            .rstrip("=")
        )
        return api_client.get(
            target,
            **{
                "HTTP_X_ISSUE_IDENTITY_VERSION": "2",
                "HTTP_X_ISSUE_KEY_ID": "discover",
                "HTTP_X_ISSUE_AUDIENCE": "quality",
                "HTTP_X_ISSUE_PRINCIPAL": principal,
                "HTTP_X_ISSUE_PRINCIPAL_TIMESTAMP": stamp,
                "HTTP_X_ISSUE_PRINCIPAL_NONCE": nonce,
                "HTTP_X_ISSUE_CONTENT_SHA256": "-",
                "HTTP_X_ISSUE_PRINCIPAL_SIGNATURE": signature,
            },
        )

    accepted = request(3)
    assert accepted.status_code == 200, accepted.content
    assert accepted.data["project_id"] == str(project.id)
    assert accepted.data["workspace"] == project.workspace.slug
    assert request(999).status_code == 403
    assert api_client.get("/api/quality-auth/daq-project/?platform_project_id=3").status_code in {401, 403}


def test_daq_history_paginates_after_exact_record_filter(session_client, daq):
    base, project, user = daq
    for _ in range(3):
        assert report(session_client, base, str(uuid4())).status_code == 201
    body = {"records": [{"platformTaskId": 24, "sourceRecordId": "daq-session-1106"}]}
    first = session_client.post(base + "daq/source-links/query/?page=1&per_page=2", body, format="json")
    assert first.status_code == 200
    assert first.data["count"] == 3 and len(first.data["results"]) == 2
    second = session_client.post(base + "daq/source-links/query/?page=2&per_page=2", body, format="json")
    assert second.data["count"] == 3 and len(second.data["results"]) == 1
    assert not {x["issueId"] for x in first.data["results"]} & {x["issueId"] for x in second.data["results"]}
    body["records"][0]["platformTaskId"] = 999
    empty = session_client.post(base + "daq/source-links/query/?page=1&per_page=2", body, format="json")
    assert empty.data["count"] == 0


@pytest.mark.parametrize("authorized", [True, False])
def test_first_daq_report_links_collector_without_any_web_login(
    api_client, session_client, daq, workspace, create_user, settings, mocker, authorized
):
    import base64
    import hashlib
    import hmac
    import json
    import time
    from django.utils import timezone
    from plane.license.models import Instance, InstanceAdmin
    from plane.quality.models import PlatformAccount, PlatformProject, PlatformIdentity, ProjectRolePolicy
    from plane.quality.identity import encode

    base, project, owner = daq
    source = "daq-local-integration"
    instance = Instance.objects.create(
        instance_name="DAQ首次接入验收",
        instance_id=str(uuid4()),
        current_version="test",
        last_checked_at=timezone.now(),
    )
    InstanceAdmin.objects.create(instance=instance, user=create_user)
    PlatformProject.objects.create(project=project, source_instance=source, external_project_id=3)
    ProjectRolePolicy.objects.create(project=project, enabled=True)
    config = {
        "kind": "data_platform",
        "base_url": "https://authority.example",
        "login_enabled": True,
        "login_auto_provision": True,
        "configured_by": str(create_user.id),
        "service_token": "test-only-service",
        "login_role_map": {"Collector": "REPORTER"},
    }
    mocker.patch("plane.quality.data_accounts.read_connection", return_value=config)

    def authority(_config, path, *args, **kwargs):
        if path == "/internal/issue-users/72":
            return {"id": 72, "username": "first-daq-collector", "role": "Collector", "active": True}
        if path == "/internal/issue-permissions/users/72":
            return {"projects": [{"id": 3}] if authorized else []}
        if path.endswith("/tasks/24/context"):
            return {"projectId": 3, "taskId": 24, "sourceSessionId": "daq-session-1106", "dataPackageId": "pkg-test"}
        raise AssertionError(path)

    mocker.patch("plane.quality.data_accounts.authority_request", side_effect=authority)
    mocker.patch("plane.quality.platform.fetch", side_effect=authority)
    settings.QUALITY_BRIDGE_KEYS = {
        "first-daq": {"secret": "test-only-key", "audience": "plane-quality", "source_instance": source}
    }
    url = base + "daq/reports/"
    body = json.dumps(
        {
            "sourceRecordId": "daq-session-1106",
            "platformTaskId": 24,
            "category": "DataAnomaly",
            "title": "未登录数采员首次上报",
            "description": "仅本机自动测试",
        },
        separators=(",", ":"),
    )
    principal = json.dumps({"id": 72, "username": "do-not-trust-this-name"}, separators=(",", ":"))
    stamp = str(int(time.time()))
    nonce = str(uuid4())
    digest = hashlib.sha256(body.encode()).hexdigest()
    canonical = "\n".join(
        [
            "ISSUE-IDENTITY-V2",
            encode("plane-quality"),
            encode("first-daq"),
            stamp,
            encode(nonce),
            "POST",
            encode(url),
            digest,
            encode(principal),
        ]
    )
    signature = (
        base64.urlsafe_b64encode(hmac.new(b"test-only-key", canonical.encode(), hashlib.sha256).digest())
        .decode()
        .rstrip("=")
    )
    api_client.force_authenticate(user=None)
    assert not PlatformAccount.objects.filter(source_instance=source, external_user_id=72).exists()
    r = api_client.post(
        url,
        body,
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
        HTTP_X_ISSUE_IDENTITY_VERSION="2",
        HTTP_X_ISSUE_KEY_ID="first-daq",
        HTTP_X_ISSUE_AUDIENCE="plane-quality",
        HTTP_X_ISSUE_PRINCIPAL=principal,
        HTTP_X_ISSUE_PRINCIPAL_TIMESTAMP=stamp,
        HTTP_X_ISSUE_PRINCIPAL_NONCE=nonce,
        HTTP_X_ISSUE_CONTENT_SHA256=digest,
        HTTP_X_ISSUE_PRINCIPAL_SIGNATURE=signature,
    )
    if not authorized:
        assert r.status_code in {401, 403}, r.content
        assert not PlatformAccount.objects.filter(source_instance=source, external_user_id=72).exists()
        return
    assert r.status_code == 201, r.content
    account = PlatformAccount.objects.get(source_instance=source, external_user_id=72)
    assert account.user.last_login is None
    assert account.user.display_name == "first-daq-collector"
    assert PlatformIdentity.objects.filter(project=project, user=account.user, active=True).exists()
    from plane.quality.models import Defect

    assert Defect.objects.get(pk=r.data["issueId"]).created_by_id == account.user_id
