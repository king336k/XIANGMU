"""Agent queue state, invalidation and execution receipts, independent of HTTP."""

from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import DefectEvent
from .remote_models import RemoteAgentRun, RemoteWorkstation


@transaction.atomic
def invalidate_run(run, reason):
    """End authorization immediately; actual worker release is recorded separately."""
    RemoteWorkstation.objects.select_for_update(of=("self",)).get(pk=run.workstation_id)
    RemoteAgentRun.objects.select_for_update(of=("self",)).get(pk=run.pk)
    run.refresh_from_db()
    if run.status not in {"queued", "running"}:
        return
    run.status = "failed"
    run.error = reason
    run.tool_credential_hash = ""
    run.completed_at = timezone.now()
    run.result = {
        **run.result,
        "queued_at": run.created_at.timestamp(),
        "worker_started_at": run.started_at.timestamp() if run.started_at else None,
        "worker_completed_at": None,
        "invalidated_at": run.completed_at.timestamp(),
        "worker_queue": "field-repairs",
        "repaired": False,
        "verification_passed": False,
    }
    run.save(update_fields=["status", "error", "tool_credential_hash", "completed_at", "result"])
    from .agent_lifecycle import handoff

    handoff(run)
    run.remotecommand_set.filter(status__in=["pending", "delivered"]).update(status="expired", payload={})


def fail_runs(station, reason):
    for run in station.remoteagentrun_set.filter(status__in=["queued", "running"]):
        invalidate_run(run, reason)


def record_tool_completion(row):
    """Record workflow progress, without copying command arguments or raw output."""
    if not row.run_id:
        return
    context = row.workstation.capabilities.get("agent_context", {})
    payload = row.payload
    argv = payload.get("argv")
    if payload.get("kind") == "patch_file":
        action = "配置修复"
    elif payload.get("kind") == "read_file":
        action = "读取配置"
    elif argv and argv == context.get("verify_argv"):
        action = "现场复测"
    elif (
        context.get("repair_argv")
        and isinstance(argv, list)
        and argv[: len(context["repair_argv"])] == context["repair_argv"]
    ):
        action = "现场修复"
    else:
        action = "现场排查"
    success = row.result.get("ok") is True and row.result.get("exit_code", 0) == 0
    defect = row.run.defect
    DefectEvent.objects.create(
        project_id=defect.project_id,
        defect=defect,
        created_by_id=row.run.owner_id,
        previous_status=defect.status,
        status=defect.status,
        note=(
            f"Agent {action}：{'工具执行完成' if success else '工具执行失败'}；任务 {row.run_id}；命令 {row.id}。"
            "功能是否恢复以本轮复测结论为准。"
        ),
    )


def run_queue(run):
    """Database wait state, never an estimate of model completion time."""
    if run.status not in {"queued", "running"}:
        return None
    station = run.workstation
    now = timezone.now()
    if run.status == "running":
        cached = getattr(run, "_processing_commands", None)
        latest = (
            (cached[0] if cached else None)
            if cached is not None
            else run.remotecommand_set.order_by("-created_at", "-id").first()
        )
        stage = "inspect" if latest else "analysis"
        if latest:
            from .remote_event_display import safe_argv

            context = run.result.get("display_policy_snapshot") or station.capabilities.get("agent_context", {})
            argv = safe_argv(latest.payload.get("argv"))
            if argv and argv == safe_argv(context.get("verify_argv")):
                stage = "verify"
            elif latest.payload.get("kind") == "patch_file" or (
                context.get("repair_argv")
                and isinstance(argv, list)
                and argv[: len(context["repair_argv"])] == safe_argv(context["repair_argv"])
            ):
                stage = "repair"
        return {"position": None, "reason": "", "stage": stage}
    from .remote_models import RemoteUploadedFile

    earlier = Q(created_at__lt=run.created_at) | Q(created_at=run.created_at, id__lt=run.id)
    # Position is limited to this device; other workers can serve other devices.
    waiting = station.remoteagentrun_set.filter(status="queued", expires_at__gt=now).filter(earlier).count()
    reason = "worker_busy"
    if station.remoteterminal_set.filter(
        status="open", expires_at__gt=now, last_read_at__gt=now - timedelta(seconds=60)
    ).exists():
        reason = "terminal_open"
    elif RemoteUploadedFile.objects.filter(workstation=station, status="uploading", expires_at__gt=now).exists():
        reason = "transfer_active"
    elif waiting or station.remoteagentrun_set.filter(status="running", expires_at__gt=now).exists():
        reason = "device_busy"
    return {"position": waiting, "reason": reason, "stage": "queued"}
