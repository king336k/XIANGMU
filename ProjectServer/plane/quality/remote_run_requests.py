"""User-owned Agent task creation and inspection with a device transaction boundary."""

from datetime import timedelta

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from .errors import Conflict
from .models import Defect, DefectEvent
from .remote_access import identity_key, online, permitted, station_for
from .remote_bindings import daq_binding, feedback_for
from .remote_models import RemoteAgentRun, RemoteWorkstation
from .remote_run_state import invalidate_run, run_queue
from .remote_sessions import close_session


@transaction.atomic
def create_run(user, data):
    station = station_for(user, data.get("device_id"))
    station = (
        RemoteWorkstation.objects.select_for_update(of=("self",))
        .select_related("agent__project__workspace")
        .get(pk=station.pk)
    )
    if not permitted(user, station):
        raise PermissionDenied()
    if not online(station):
        raise Conflict("采集电脑离线。")
    defect = get_object_or_404(feedback_for(station, data.get("defect_id")), pk=data.get("defect_id"))
    defect = Defect.objects.select_for_update().get(pk=defect.pk)
    problem = serializers.CharField(max_length=8000).run_validation(data.get("problem"))
    mode = serializers.ChoiceField(choices=["diagnose", "repair", "verify"], default="repair").run_validation(
        data.get("mode", "repair")
    )
    binding, _ = daq_binding(defect)
    if binding.get("execution_scope") == "verify_only" and mode != "verify":
        raise Conflict("这条历史反馈仅批准在原采集电脑重新验证，请使用重新验证。")
    active = RemoteAgentRun.objects.filter(
        workstation=station, status__in=["queued", "running"], expires_at__gt=timezone.now()
    )
    if active.filter(defect=defect).exists():
        raise Conflict("这条反馈已有处理任务，请查看当前进度。")
    if active.count() >= 20:
        raise Conflict("这台采集电脑待处理任务已达上限，请稍后提交。")
    for session in station.remoteterminal_set.filter(
        status="open", last_read_at__lte=timezone.now() - timedelta(seconds=60)
    ):
        close_session(session)
    run = RemoteAgentRun.objects.create(
        workstation=station,
        defect=defect,
        owner=user,
        problem=problem,
        mode=mode,
        expires_at=timezone.now() + timedelta(minutes=30),
        identity_key=identity_key(station),
        result={"defect_state_version": defect.edit_version},
    )
    DefectEvent.objects.create(
        project_id=defect.project_id,
        defect=defect,
        created_by=user,
        previous_status=defect.status,
        status=defect.status,
        note=(
            f"Agent {'重新诊断' if mode == 'diagnose' else '重新验证' if mode == 'verify' else '诊断与自动修复'}"
            f"：已进入队列；任务 {run.id}。"
        ),
    )
    from .remote_tasks import remote_repair

    transaction.on_commit(lambda: remote_repair.apply_async(args=[str(run.id)], queue="field-repairs"))
    return {"id": str(run.id), "status": run.status, "queue": run_queue(run)}


def read_run(user, pk):
    run = get_object_or_404(
        RemoteAgentRun.objects.select_related("workstation__agent__project__workspace"),
        pk=pk,
        owner=user,
    )
    if not permitted(user, run.workstation):
        raise PermissionDenied()
    if run.status in {"queued", "running"} and run.expires_at <= timezone.now():
        invalidate_run(run, "远程任务已超时，现场恢复未确认。")
    return {"id": str(run.id), "status": run.status, "result": run.result, "error": run.error, "queue": run_queue(run)}
