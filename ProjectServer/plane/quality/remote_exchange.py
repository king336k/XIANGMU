"""Atomic device exchange shared by HTTP and WebSocket transports."""

import base64
import json
import re
from datetime import timedelta
from typing import NamedTuple
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from .remote_access import digest, identity_key, online, permitted
from .remote_models import RemoteWorkstation, RemoteTerminal, RemoteTerminalEvent, RemoteCommand
from .remote_sessions import close_session, terminal_target_valid
from .remote_run_state import fail_runs, invalidate_run, record_tool_completion


class ExchangeResult(NamedTuple):
    data: dict
    status_code: int = 200


def authenticate_station(raw):
    if not raw.startswith("rw_") or len(raw) > 120:
        raise AuthenticationFailed("现场连接凭据无效。")
    station = (
        RemoteWorkstation.objects.select_related("agent__project__workspace", "agent__owner")
        .filter(
            credential_hash=digest(raw),
            enabled=True,
            credential_expires_at__gt=timezone.now(),
            agent__enabled=True,
        )
        .first()
    )
    if not station or not permitted(station.agent.owner, station):
        raise AuthenticationFailed("现场连接凭据已失效。")
    return station.agent.owner, station


@transaction.atomic
def exchange_station(station_id, data, previous_identity=None, poll_only=False):
    station = (
        RemoteWorkstation.objects.select_for_update(of=("self",))
        .select_related("agent__owner", "agent__project__workspace")
        .get(pk=station_id)
    )
    now = timezone.now()
    if not permitted(station.agent.owner, station) or station.credential_expires_at <= now:
        raise AuthenticationFailed("现场连接凭据已失效。")
    # All decisions use this locked device snapshot and are discarded at
    # request completion; revocation is checked again on the next exchange.
    permission_decisions = {station.agent.owner_id: True}

    def allowed(user):
        if user.pk not in permission_decisions:
            permission_decisions[user.pk] = permitted(user, station)
        return permission_decisions[user.pk]

    if len(json.dumps(data)) > 1500000:
        raise ValidationError("现场消息超过限制。")
    identity = data.get("identity", {})
    if not isinstance(identity, dict):
        raise ValidationError("电脑身份无效。")
    capabilities = identity.get("capabilities", {})
    if not isinstance(capabilities, dict) or len(json.dumps(capabilities)) >= 16000:
        capabilities = None

    def executor_instance(value):
        terminal = value.get("terminal", {}) if isinstance(value, dict) else {}
        instance = terminal.get("executor_instance") if isinstance(terminal, dict) else None
        return instance if isinstance(instance, str) and re.fullmatch(r"[a-f0-9]{32}", instance) else None

    previous_executor = executor_instance(station.capabilities)
    current_executor = executor_instance(capabilities)
    if previous_identity is not None:

        def matches_current(candidate):
            return (
                candidate.get("boot_id", "") == station.boot_id
                and candidate.get("hostname", "") == station.hostname
                and candidate.get("username", "") == station.username
                and executor_instance(candidate.get("capabilities")) == previous_executor
            )

        if not matches_current(previous_identity) and not matches_current(identity):
            return ExchangeResult({"error": "旧执行端连接已被替换。"}, status_code=409)
    if poll_only:
        # A server command poll is not a new workstation observation.
        if not online(station):
            return ExchangeResult({"error": "执行端心跳已中断。"}, status_code=409)
        identity = {"boot_id": station.boot_id, "hostname": station.hostname, "username": station.username}
        capabilities = station.capabilities
        current_executor = previous_executor
    executor_changed = (
        capabilities is not None
        and previous_executor != current_executor
        and bool(previous_executor or current_executor)
    )
    boot = str(identity.get("boot_id", ""))[:120]
    interrupted = not poll_only and (
        station.boot_id
        and station.boot_id != boot
        or station.last_seen_at
        and (now - station.last_seen_at).total_seconds() > 30
        or bool(station.last_seen_at)
        and (
            station.hostname != str(identity.get("hostname", ""))[:200]
            or station.username != str(identity.get("username", ""))[:120]
            or executor_changed
        )
    )
    if interrupted:
        for session in station.remoteterminal_set.exclude(status="closed"):
            close_session(session)
        fail_runs(station, "现场连接身份已变化，旧任务已停止。")
        station.commands.filter(status__in=["pending", "delivered"], run__isnull=False).update(
            status="expired", payload={}
        )
    if not poll_only:
        station.username = str(identity.get("username", ""))[:120]
        station.hostname = str(identity.get("hostname", ""))[:200]
        station.boot_id = boot
        station.last_seen_at = now
        if capabilities is not None:
            from .remote_profiles import daq_profile

            station.capabilities = {
                **capabilities,
                "agent_context": daq_profile(station.capabilities.get("agent_context", {}), capabilities),
            }
        station.save()
    for run in station.remoteagentrun_set.filter(status__in=["queued", "running"]).select_related("owner"):
        if run.expires_at <= now or run.identity_key != identity_key(station) or not allowed(run.owner):
            invalidate_run(run, "任务现场身份或操作权限已变化。")
    outputs = data.get("outputs", [])
    results = data.get("results", [])
    if not isinstance(outputs, list) or len(outputs) > 100 or not isinstance(results, list) or len(results) > 100:
        raise ValidationError("现场消息数量超过限制。")
    for value in results:
        row = station.commands.filter(pk=value.get("id")).first()
        if not row:
            raise ValidationError("现场任务不属于本电脑。")
        if row.status == "done":
            continue
        if row.status == "expired":
            continue
        if row.expires_at <= now:
            row.status = "expired"
            row.payload = {}
            row.save(update_fields=["status", "payload"])
            continue
        safe = {
            k: v
            for k, v in value.items()
            if k
            in {
                "ok",
                "stdout",
                "stderr",
                "exit_code",
                "content",
                "sha256",
                "backup",
                "recovered",
                "error",
                "timed_out",
                "truncated",
                "file_result",
                "resolved_path",
                "changes",
                "target_username",
                "target_ip",
                "target_kind",
            }
        }
        if len(json.dumps(safe)) > 280000:
            raise ValidationError("命令结果超过限制。")
        if "file_result" in safe and not isinstance(safe["file_result"], dict):
            raise ValidationError("现场文件结果格式无效。")
        row.status = "done"
        row.result = safe
        if row.payload.get("kind") == "file_browser":
            from .remote_file_operations import record_upload_result

            record_upload_result(row)
        if row.payload.get("kind") == "file_browser" and row.payload.get("request", {}).get("action") == "upload_chunk":
            row.payload = {}
        # Interactive inputs are transport buffers, never retained as an audit transcript.
        if row.session_id:
            row.payload = {}
            row.result = {
                "ok": bool(value.get("ok")),
                "terminal_roundtrip_ms": round((timezone.now() - row.created_at).total_seconds() * 1000, 1),
            }
            if not value.get("ok"):
                session = row.session
                session.error = "现场终端执行失败，请重新连接。"
                session.save(update_fields=["error"])
                close_session(session)
        row.save(update_fields=["status", "result", "payload"])
        record_tool_completion(row)
    for value in outputs:
        session = RemoteTerminal.objects.filter(pk=value.get("session_id"), workstation=station).first()
        if not session or session.status == "closed":
            continue
        if value.get("kind") == "exit":
            close_session(session)
            continue
        data = str(value.get("data", ""))
        try:
            decoded = base64.b64decode(data, validate=True)
        except Exception:
            raise ValidationError("终端输出编码无效。")
        if len(decoded) > 65536:
            raise ValidationError("终端输出超过限制。")
        source = str(value.get("id", ""))[:80]
        if not source:
            raise ValidationError("终端输出缺少序号。")
        RemoteTerminalEvent.objects.get_or_create(session=session, source_id=source, defaults={"data": data})
        cutoff = list(session.events.order_by("-id").values_list("id", flat=True)[200:201])
        if cutoff:
            session.events.filter(id__lte=cutoff[0]).delete()
    for session in station.remoteterminal_set.filter(status="open").select_related("owner"):
        if (
            session.expires_at < now
            or (now - session.last_read_at).total_seconds() > 60
            or not allowed(session.owner)
            or not terminal_target_valid(session, station)
        ):
            close_session(session)
    station.commands.filter(status__in=["pending", "delivered"], expires_at__lte=now).update(
        status="expired", payload={}
    )
    station.commands.filter(run__status__in=["failed", "completed"], status__in=["pending", "delivered"]).update(
        status="expired", payload={}
    )
    station.commands.filter(run__expires_at__lte=now, status__in=["pending", "delivered"]).update(
        status="expired", payload={}
    )
    RemoteTerminalEvent.objects.filter(
        session__workstation=station,
        session__status="closed",
        session__last_read_at__lt=now - timedelta(minutes=2),
    ).delete()
    pending = list(
        station.commands.filter(status__in=["pending", "delivered"], expires_at__gt=now).order_by("created_at", "id")[
            :50
        ]
    )
    allowed_pending = []
    for row in pending:
        if row.payload.get("kind") == "file_browser":
            job = getattr(row, "file_request", None)
            if not job or not allowed(job.owner) or job.identity_key != identity_key(station):
                row.status = "expired"
                row.payload = {}
                row.save(update_fields=["status", "payload"])
                continue
        allowed_pending.append(row)
    task = next(
        (
            row
            for row in allowed_pending
            if row.payload.get("kind") in {"run", "read_file", "patch_file", "file_browser"}
        ),
        None,
    )
    pending = [
        row
        for row in allowed_pending
        if row.payload.get("kind") not in {"run", "read_file", "patch_file", "file_browser"} or row is task
    ]
    payload = [{"id": str(c.id), "expires_at": c.expires_at.timestamp(), **c.payload} for c in pending]
    for row in pending:
        row.status = "delivered"
    RemoteCommand.objects.bulk_update(pending, ["status"])
    # Only short-lived terminal buffers are kept, no historical terminal transcript.
    station.commands.filter(file_request__isnull=False, expires_at__lt=now).delete()
    station.commands.filter(
        session__isnull=False, status__in=["done", "expired"], created_at__lt=now - timedelta(minutes=5)
    ).delete()
    if station.capabilities.get("agent_context", {}).get("auto_diagnose") is True:
        # A report arriving while an operator is using the machine remains pending.
        # Resume one signed report on a later heartbeat after the busy guard clears.
        from .remote_feedback import resume_pending

        transaction.on_commit(lambda: resume_pending(station.pk))
    return ExchangeResult({"commands": payload})
