"""Report messages are previewed, scoped, and explicitly sent; no real external requests in tests."""

from uuid import uuid4
import pytest
from plane.db.models import Project, ProjectMember
from plane.quality.models import SavedReport

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def delivery(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="报告投递", identifier="SEND")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    report = SavedReport.objects.create(
        project=project,
        created_by=create_user,
        name="待补测报告",
        request_id=uuid4(),
        snapshot={
            "project_name": project.name,
            "summary": {"total": 2, "passed": 1, "failed": 0, "pending": 1},
            "plans": [],
        },
    )
    return f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/", project, report


def test_delivery_preview_never_sends_and_missing_connection_is_explicit(session_client, delivery, mocker):
    base, project, report = delivery
    outgoing = mocker.patch("requests.post")
    target = session_client.post(
        base + "notification-targets/",
        {"name": "本地测试目标", "source_instance": "feishu-test", "chat_id": "oc_test_local_only"},
        format="json",
    )
    assert target.status_code == 201, target.content
    preview = session_client.post(
        base + f"reports/{report.id}/deliveries/",
        {"target_id": target.data["id"], "request_id": str(uuid4()), "expected_version": 1},
        format="json",
    )
    assert preview.status_code == 201 and preview.data["status"] == "preview", preview.content
    assert "待补测报告" in preview.data["text"] and "未执行 1" in preview.data["text"]
    outgoing.assert_not_called()
    denied = session_client.post(
        base + f"report-deliveries/{preview.data['id']}/send/", {"confirmed": True}, format="json"
    )
    assert denied.status_code == 503, denied.content
    outgoing.assert_not_called()


def test_send_requires_explicit_confirmation_and_retries_are_idempotent(session_client, delivery, mocker):
    base, project, report = delivery
    target = session_client.post(
        base + "notification-targets/",
        {"name": "本地测试目标", "source_instance": "feishu-test", "chat_id": "oc_test_local_only"},
        format="json",
    )
    assert target.status_code == 201, target.content
    draft = session_client.post(
        base + f"reports/{report.id}/deliveries/",
        {"target_id": target.data["id"], "request_id": str(uuid4()), "expected_version": 1},
        format="json",
    ).data
    send = mocker.patch("plane.quality.report_delivery.send_message", return_value="local-message-only")
    assert session_client.post(base + f"report-deliveries/{draft['id']}/send/", {}, format="json").status_code == 400
    sent = session_client.post(base + f"report-deliveries/{draft['id']}/send/", {"confirmed": True}, format="json")
    assert sent.status_code == 200 and sent.data["status"] == "sent", sent.content
    repeated = session_client.post(base + f"report-deliveries/{draft['id']}/send/", {"confirmed": True}, format="json")
    assert repeated.status_code == 200 and send.call_count == 1
    report.refresh_from_db()
    assert report.snapshot["summary"]["pending"] == 1


def test_target_and_send_are_manager_scoped_and_target_changes_invalidate_preview(
    session_client, delivery, create_user
):
    base, project, report = delivery
    target = session_client.post(
        base + "notification-targets/",
        {"name": "本地目标", "source_instance": "feishu-test", "chat_id": "oc_test_local_only"},
        format="json",
    )
    assert target.status_code == 201, target.content
    draft = session_client.post(
        base + f"reports/{report.id}/deliveries/",
        {"target_id": target.data["id"], "request_id": str(uuid4()), "expected_version": 1},
        format="json",
    ).data
    changed = session_client.patch(
        base + f"notification-targets/{target.data['id']}/", {"expected_version": 1, "enabled": False}, format="json"
    )
    assert changed.status_code == 200
    assert (
        session_client.post(
            base + f"report-deliveries/{draft['id']}/send/", {"confirmed": True}, format="json"
        ).status_code
        == 409
    )
    ProjectMember.objects.filter(project=project, member=create_user).update(role=15)
    assert (
        session_client.post(
            base + "notification-targets/",
            {"name": "越权", "source_instance": "feishu-test", "chat_id": "oc_test_local_only"},
            format="json",
        ).status_code
        == 403
    )


def test_expired_preview_and_report_conclusion_changes_require_fresh_review(session_client, delivery, mocker):
    from datetime import timedelta
    from django.utils import timezone
    from plane.quality.models import ReportDelivery

    base, project, report = delivery
    target = session_client.post(
        base + "notification-targets/",
        {"name": "本地目标", "source_instance": "feishu-test", "chat_id": "oc_test_local_only"},
        format="json",
    ).data
    draft = session_client.post(
        base + f"reports/{report.id}/deliveries/",
        {"target_id": target["id"], "request_id": str(uuid4()), "expected_version": 1},
        format="json",
    ).data
    outgoing = mocker.patch("requests.post")
    ReportDelivery.objects.filter(pk=draft["id"]).update(created_at=timezone.now() - timedelta(minutes=11))
    assert (
        session_client.post(
            base + f"report-deliveries/{draft['id']}/send/", {"confirmed": True}, format="json"
        ).status_code
        == 409
    )
    outgoing.assert_not_called()


def test_official_feishu_message_uses_fixed_endpoint_and_stable_request_id(session_client, delivery, mocker):
    import json

    base, project, report = delivery
    target = session_client.post(
        base + "notification-targets/",
        {"name": "本地目标", "source_instance": "feishu-test", "chat_id": "oc_test_local_only"},
        format="json",
    ).data
    request_id = str(uuid4())
    draft = session_client.post(
        base + f"reports/{report.id}/deliveries/",
        {"target_id": target["id"], "request_id": request_id, "expected_version": 1},
        format="json",
    ).data
    mocker.patch(
        "plane.quality.report_delivery.read_connection",
        return_value={"kind": "feishu", "base_url": "https://open.feishu.cn", "service_token": "synthetic-test-only"},
    )
    response = mocker.MagicMock()
    response.__enter__.return_value = response
    response.status_code = 200
    response.iter_content.return_value = iter(
        [json.dumps({"code": 0, "data": {"message_id": "om_local_only"}}).encode()]
    )
    post = mocker.patch("requests.post", return_value=response)
    sent = session_client.post(base + f"report-deliveries/{draft['id']}/send/", {"confirmed": True}, format="json")
    assert sent.status_code == 200 and sent.data["status"] == "sent", sent.content
    assert post.call_args.args[0] == "https://open.feishu.cn/open-apis/im/v1/messages"
    assert post.call_args.kwargs["json"]["uuid"] == request_id
    assert post.call_args.kwargs["json"]["receive_id"] == target["chat_id"]
    assert not post.call_args.kwargs["allow_redirects"]
    assert "synthetic-test-only" not in str(sent.data)


def test_sent_recipient_history_never_changes_after_target_is_edited(session_client, delivery, mocker):
    base, project, report = delivery
    target = session_client.post(
        base + "notification-targets/",
        {"name": "原接收群", "source_instance": "feishu-test", "chat_id": "oc_original_only"},
        format="json",
    ).data
    draft = session_client.post(
        base + f"reports/{report.id}/deliveries/",
        {"target_id": target["id"], "request_id": str(uuid4()), "expected_version": 1},
        format="json",
    ).data
    mocker.patch("plane.quality.report_delivery.send_message", return_value="local-message-only")
    assert (
        session_client.post(
            base + f"report-deliveries/{draft['id']}/send/", {"confirmed": True}, format="json"
        ).status_code
        == 200
    )
    session_client.patch(
        base + f"notification-targets/{target['id']}/",
        {"expected_version": 1, "name": "新接收群", "chat_id": "oc_changed_only"},
        format="json",
    )
    history = session_client.get(base + f"reports/{report.id}/deliveries/").data["results"][0]
    repeated = session_client.post(
        base + f"report-deliveries/{draft['id']}/send/", {"confirmed": True}, format="json"
    ).data
    assert history["target_name"] == "原接收群" and history["chat_id"] == "oc_original_only"
    assert repeated["target_name"] == history["target_name"] and repeated["chat_id"] == history["chat_id"]
