"""One terminal lifecycle and transaction boundary for HTTP and WebSocket adapters."""

import base64
from datetime import timedelta
from typing import NamedTuple

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError

from .errors import Conflict
from .remote_access import online, permitted, station_for
from .remote_commands import command
from .remote_models import RemoteTerminal, RemoteWorkstation


class SessionResult(NamedTuple):
    data: dict
    status_code: int = 200


def robot_target(station):
    value = station.capabilities.get("robot", {})
    if not isinstance(value, dict) or value.get("connected") is not True:
        raise Conflict("请先在DAQ连接机器人。")
    import ipaddress

    try:
        address = ipaddress.ip_address(value.get("host", ""))
        if (
            not address.is_private
            or address.is_loopback
            or address.is_unspecified
            or address.is_multicast
        ):
            raise ValueError()
    except ValueError:
        raise Conflict("机器人连接信息尚未就绪。")
    if (
        not value.get("username")
        or not isinstance(value.get("target_revision"), str)
        or len(value["target_revision"]) != 64
    ):
        raise Conflict("机器人连接信息尚未就绪。")
    return {"username": str(value["username"]), "host": str(address)}, value[
        "target_revision"
    ]


def terminal_snapshot(session):
    return {
        "id": str(session.id),
        "status": session.status,
        "target": session.target,
        "identity": session.target_identity,
        "target_revision": session.target_revision,
        "created_at": session.created_at,
        "last_read_at": session.last_read_at,
    }


def terminal_target_valid(session, station):
    if session.target != "robot":
        return True
    try:
        target, revision = robot_target(station)
    except Conflict:
        return False
    return revision == session.target_revision and target == session.target_identity


def close_session(session):
    if session.status == "closed":
        return
    session.status = "closed"
    session.save(update_fields=["status"])
    session.remotecommand_set.exclude(status="done").update(
        status="expired", payload={}
    )
    command(
        session.workstation,
        {"kind": "terminal_close", "session_id": str(session.id)},
        session=session,
        lifetime=60,
    )


@transaction.atomic(savepoint=False)
def open_session(user, data):
    if set(data) - {
        "action",
        "device_id",
        "cols",
        "rows",
        "target",
        "expected_target_revision",
    }:
        raise ValidationError("终端目标只能选择已登记的采集电脑或已连接机器人。")
    station = station_for(user, data.get("device_id"))
    station = (
        RemoteWorkstation.objects.select_for_update(of=("self",))
        .select_related("agent__project__workspace")
        .get(pk=station.pk)
    )
    if not permitted(user, station):
        raise PermissionDenied()
    if not online(station):
        raise Conflict("采集电脑离线，请等待连接。")
    if station.remoteagentrun_set.filter(
        status__in=["queued", "running"], expires_at__gt=timezone.now()
    ).exists():
        raise Conflict("该电脑正在执行 Agent 任务，请结束后再打开人工终端。")
    from .remote_models import RemoteUploadedFile

    if RemoteUploadedFile.objects.filter(
        workstation=station, status="uploading", expires_at__gt=timezone.now()
    ).exists():
        raise Conflict("该电脑正在上传文件，请完成或取消后再打开人工终端。")
    if (
        RemoteTerminal.objects.filter(
            workstation=station, status="open", expires_at__gt=timezone.now()
        ).count()
        >= 2
    ):
        raise Conflict("该电脑终端会话已达上限。")
    target = serializers.ChoiceField(choices=["operator", "robot"]).run_validation(
        data.get("target", "operator")
    )
    target_identity = {
        "username": station.username,
        "host": station.capabilities.get("network", {}).get("ip_address", ""),
    }
    revision = ""
    if target == "robot":
        target_identity, revision = robot_target(station)
        if data.get("expected_target_revision") != revision:
            raise Conflict("机器人已切换，请刷新后重新连接。")
    now = timezone.now()
    session = RemoteTerminal.objects.create(
        workstation=station,
        owner=user,
        target=target,
        target_identity=target_identity,
        target_revision=revision,
        last_read_at=now,
        expires_at=now + timedelta(hours=1),
    )
    cols = serializers.IntegerField(min_value=20, max_value=500).run_validation(
        data.get("cols", 100)
    )
    rows = serializers.IntegerField(min_value=5, max_value=200).run_validation(
        data.get("rows", 30)
    )
    command(
        station,
        {
            "kind": "terminal_open",
            "session_id": str(session.id),
            "cols": cols,
            "rows": rows,
            "target": target,
            "target_revision": revision,
        },
        session=session,
    )
    return SessionResult(terminal_snapshot(session), 201)


def _locked_session(user, pk):
    """Load and invalidate under the outer read/change transaction."""
    # Lock the device before reading the current session snapshot. The joined
    # owner condition preserves the same 404 boundary without an early query.
    station = get_object_or_404(
        RemoteWorkstation.objects.select_for_update(of=("self",))
        .select_related("agent__project__workspace"),
        remoteterminal__pk=pk,
        remoteterminal__owner=user,
    )
    session = get_object_or_404(RemoteTerminal.objects, pk=pk, owner=user, workstation=station)
    session.workstation = station
    if session.workstation.remoteagentrun_set.filter(
        status="running", expires_at__gt=timezone.now()
    ).exists():
        close_session(session)
    if session.status == "open" and session.last_read_at <= timezone.now() - timedelta(
        seconds=60
    ):
        close_session(session)
    if not permitted(user, session.workstation):
        close_session(session)
        raise PermissionDenied()
    if session.expires_at <= timezone.now() or not terminal_target_valid(
        session, session.workstation
    ):
        close_session(session)
    return session


@transaction.atomic
def read_session(user, pk, after=0):
    try:
        session = _locked_session(user, pk)
    except PermissionDenied:
        # Keep the invalidation committed when authorization changed.
        return SessionResult({"error": "终端权限已失效。"}, status_code=403)
    if session.status != "closed" and not online(session.workstation):
        close_session(session)
    session.last_read_at = timezone.now()
    session.save(update_fields=["last_read_at"])
    after = serializers.IntegerField(min_value=0).run_validation(after)
    events = list(session.events.filter(id__gt=after).order_by("id")[:100])
    return SessionResult(
        {
            **terminal_snapshot(session),
            "error": session.error,
            "events": [
                {"seq": e.id, "source_id": e.source_id, "data": e.data} for e in events
            ],
            "cursor": events[-1].id if events else after,
        }
    )


@transaction.atomic
def change_session(user, pk, payload):
    try:
        session = _locked_session(user, pk)
    except PermissionDenied:
        # Return inside atomic so the invalidation above is committed.
        return SessionResult({"error": "终端权限已失效。"}, status_code=403)
    action = payload.get("action")
    if action == "close":
        close_session(session)
        return SessionResult({"status": "closed"})
    if session.status == "closed":
        return SessionResult({"error": "终端已关闭。"}, status_code=409)
    if not online(session.workstation):
        raise Conflict("采集电脑离线。")
    if action == "input":
        data = serializers.CharField(
            max_length=44000, allow_blank=False, trim_whitespace=False
        ).run_validation(payload.get("data"))
        try:
            if len(base64.b64decode(data, validate=True)) > 4096:
                raise ValueError()
        except Exception:
            raise ValidationError("终端输入编码无效。")
        payload = {
            "kind": "terminal_input",
            "session_id": str(session.id),
            "data": data,
        }
    elif action == "resize":
        payload = {
            "kind": "terminal_resize",
            "session_id": str(session.id),
            "cols": serializers.IntegerField(
                min_value=20, max_value=500
            ).run_validation(payload.get("cols")),
            "rows": serializers.IntegerField(min_value=5, max_value=200).run_validation(
                payload.get("rows")
            ),
        }
    else:
        raise ValidationError("未知终端操作。")
    if session.remotecommand_set.filter(status="pending").count() > 100:
        raise Conflict("终端输入积压，请稍后重试。")
    command(session.workstation, payload, session=session, lifetime=10)
    return SessionResult({"accepted": True})
