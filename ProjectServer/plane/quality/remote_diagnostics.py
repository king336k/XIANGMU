"""Authorized outbound workstation relay. PTYs and tools execute only on the workstation."""

import base64
import hashlib
import json
import re
import secrets
import time
import uuid
from datetime import timedelta
from urllib.parse import urlsplit

from django.db import transaction
from django.db.models import Q, Prefetch, OuterRef, Subquery, Case, When, Value, CharField, Count
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied, ValidationError
from rest_framework.response import Response

from plane.app.views.base import BaseAPIView
from plane.db.models import Project
from .models import FieldAgent, Defect, DefectEvent
from .permissions import is_administrator, writable_member, has_role
from .remote_models import (
    RemoteWorkstation,
    RemoteTerminal,
    RemoteTerminalEvent,
    RemoteCommand,
    RemoteAgentRun,
)
from .views import Conflict


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def permitted(user, station):
    project = station.agent.project
    return bool(
        user.is_authenticated
        and user.is_active
        and station.enabled
        and station.agent.enabled
        and writable_member(project.id, user.id, project.workspace.slug)
        and (
            is_administrator(user)
            or station.agent.owner_id == user.id
            and has_role(project.id, user.id, "TECHNICIAN")
        )
    )


def online(station):
    return bool(station.last_seen_at and (timezone.now() - station.last_seen_at).total_seconds() < 20)


def identity_key(station):
    robot=station.capabilities.get('robot',{})
    peer=[robot.get('username'),robot.get('host'),robot.get('target_revision')] if isinstance(robot,dict) and robot.get('connected') is True else None
    # DHCP/DAQ versions are metadata. A robot switch changes the execution target.
    return digest(json.dumps([str(station.pk), station.boot_id, station.hostname, station.username,peer], ensure_ascii=False))


def robot_target(station):
    value=station.capabilities.get('robot',{})
    if not isinstance(value,dict) or value.get('connected') is not True:
        raise Conflict('请先在DAQ连接机器人。')
    import ipaddress
    try:
        address=ipaddress.ip_address(value.get('host',''))
        if not address.is_private or address.is_loopback or address.is_unspecified or address.is_multicast:
            raise ValueError()
    except ValueError:
        raise Conflict('机器人连接信息尚未就绪。')
    if not value.get('username') or not isinstance(value.get('target_revision'),str) or len(value['target_revision'])!=64:
        raise Conflict('机器人连接信息尚未就绪。')
    return {'username':str(value['username']),'host':str(address)},value['target_revision']


def terminal_snapshot(session):
    return {'id':str(session.id),'status':session.status,'target':session.target,
        'identity':session.target_identity,'target_revision':session.target_revision,
        'created_at':session.created_at,'last_read_at':session.last_read_at}


def terminal_target_valid(session,station):
    if session.target!='robot':return True
    try:target,revision=robot_target(station)
    except Conflict:return False
    return revision==session.target_revision and target==session.target_identity


def daq_binding(defect):
    """A signed DAQ source owns its execution target; legacy bindings cannot replace it."""
    from .daq_incidents import signed_record
    from .models import SourceLink

    links=list(SourceLink.objects.filter(defect=defect,project_id=defect.project_id,
        source_system='ENGRAM_DAQ',record_type='daq_incident').select_related('defect'))
    if not links:return {'kind':'manual','state':'matched','device_id':None,'source_instance':''},None
    accepted=[]
    for link in links:
        record=signed_record(link)
        if (record and record.get('authorityMode')=='report_only' and link.device
                and record.get('payload',{}).get('device')==link.device):accepted.append(link)
    devices={(link.device,link.source_instance)for link in accepted}
    if len(devices)!=1:
        return {'kind':'daq','state':'conflict','device_id':None,'source_instance':''},None
    device,source=next(iter(devices))
    try:device=str(uuid.UUID(str(device)))
    except (ValueError,TypeError):return {'kind':'daq','state':'conflict','device_id':None,'source_instance':source},None
    station=RemoteWorkstation.objects.select_related('agent__project__workspace').filter(
        pk=device,agent__project_id=defect.project_id).first()
    from .daq_execution_binding import source_matches
    accepted_source=station is not None and (not station.agent.source_instance or source_matches(station,accepted[0]))
    state='missing' if station is None else 'matched' if accepted_source else 'conflict'
    binding={'kind':'daq','state':state,'device_id':device,'source_instance':source}
    if state=='matched' and station.agent.source_instance and station.agent.source_instance!=source:binding['execution_scope']='verify_only'
    return binding,station


def defect_agent_availability(defect):
    binding,station=daq_binding(defect)
    if binding['kind']!='daq':return None
    if binding['state']=='conflict':return {'state':'conflict','summary':'反馈接入来源与原执行端不一致，尚未开始现场处理。'}
    if station is None:return {'state':'missing','summary':'原采集电脑尚未完成远程接入，不能替换为其他电脑执行。'}
    if not online(station):return {'state':'offline','summary':'原采集电脑执行端心跳中断，等待自动恢复连接。'}
    return {'state':'ready','summary':'原采集电脑已连接，可开始现场处理。'}


def feedback_for(station, defect_id=None):
    from .daq_incidents import signed_record
    from .daq_execution_binding import source_matches
    from .models import SourceLink, DefectEvent

    links = SourceLink.objects.filter(
        project_id=station.agent.project_id, source_system="ENGRAM_DAQ",
        record_type="daq_incident", device=str(station.id),
    ).select_related("defect").prefetch_related(Prefetch(
        "defect__events", queryset=DefectEvent.objects.filter(status="open", previous_status=""),
        to_attr="_incident_signature_events",
    ))
    if defect_id:links=links.filter(defect_id=defect_id)
    verified=[]
    for link in links.order_by('-created_at'):
        record=signed_record(link)
        if (record and record.get('authorityMode')=='report_only'
                and record.get('payload',{}).get('device')==str(station.id)
                and (not station.agent.source_instance or source_matches(station,link))):
            verified.append(link.defect_id)
    rows=Defect.objects.filter(project_id=station.agent.project_id)
    if defect_id:rows=rows.filter(pk=defect_id)
    # Explicit legacy association is only for records without any DAQ provenance.
    return rows.filter(Q(pk__in=verified)|(
        Q(remote_bindings__workstation=station)&~Q(sources__source_system='ENGRAM_DAQ',sources__record_type='daq_incident'))).distinct()


@transaction.atomic
def invalidate_run(run, reason):
    """End authorization immediately; actual worker release is recorded separately."""
    RemoteWorkstation.objects.select_for_update(of=('self',)).get(pk=run.workstation_id)
    RemoteAgentRun.objects.select_for_update(of=('self',)).get(pk=run.pk)
    run.refresh_from_db()
    if run.status not in {'queued','running'}:return
    run.status='failed';run.error=reason;run.tool_credential_hash='';run.completed_at=timezone.now()
    run.result={**run.result,'queued_at':run.created_at.timestamp(),
        'worker_started_at':run.started_at.timestamp() if run.started_at else None,
        'worker_completed_at':None,'invalidated_at':run.completed_at.timestamp(),
        'worker_queue':'field-repairs','repaired':False,'verification_passed':False}
    run.save(update_fields=['status','error','tool_credential_hash','completed_at','result'])
    from .agent_lifecycle import handoff
    handoff(run)
    run.remotecommand_set.filter(status__in=['pending','delivered']).update(status='expired',payload={})


def fail_runs(station, reason):
    for run in station.remoteagentrun_set.filter(status__in=['queued','running']):
        invalidate_run(run, reason)


def station_for(user, pk):
    value = get_object_or_404(RemoteWorkstation.objects.select_related("agent__project__workspace"), pk=pk)
    if not permitted(user, value):
        raise PermissionDenied("没有这台采集电脑的远程操作权限。")
    return value


def browser_boundary(request):
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    if not request.content_type.startswith("application/json"):
        raise ValidationError("仅接受JSON请求。")
    origin = request.headers.get("Origin")
    if origin and (
        urlsplit(origin).netloc != request.get_host() or urlsplit(origin).scheme not in {"http", "https"}
    ):
        raise PermissionDenied("请求来源不匹配。")
    if request.headers.get("Sec-Fetch-Site") in {"cross-site", "same-site"}:
        raise PermissionDenied("请求来源不匹配。")


def command(station, payload, session=None, run=None, lifetime=35):
    expiry = timezone.now() + timedelta(seconds=lifetime)
    if run:
        expiry = min(expiry, run.expires_at)
    return RemoteCommand.objects.create(
        workstation=station, session=session, run=run, payload=payload, expires_at=expiry
    )


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
    elif context.get("repair_argv") and isinstance(argv, list) and argv[:len(context["repair_argv"])] == context["repair_argv"]:
        action = "现场修复"
    else:
        action = "现场排查"
    success = row.result.get("ok") is True and row.result.get("exit_code", 0) == 0
    defect = row.run.defect
    DefectEvent.objects.create(project_id=defect.project_id, defect=defect, created_by_id=row.run.owner_id,
        previous_status=defect.status, status=defect.status,
        note=f"Agent {action}：{'工具执行完成' if success else '工具执行失败'}；任务 {row.run_id}；命令 {row.id}。功能是否恢复以本轮复测结论为准。")


def close_session(session):
    if session.status == "closed":
        return
    session.status = "closed"
    session.save(update_fields=["status"])
    session.remotecommand_set.exclude(status="done").update(status="expired", payload={})
    command(
        session.workstation,
        {"kind": "terminal_close", "session_id": str(session.id)},
        session=session,
        lifetime=60,
    )


def card(value, user, can_connect=None):
    return {
        "id": str(value.id),
        "username": value.username or value.agent.name,
        "hostname": value.hostname,
        "ip_address": value.capabilities.get("network", {}).get("ip_address", ""),
        "name": value.agent.name,
        "online": online(value),
        "last_seen_at": value.last_seen_at,
        "project_id": str(value.agent.project_id),
        "workspace_slug": value.agent.project.workspace.slug,
        "can_connect": permitted(user, value) if can_connect is None else can_connect,
        "capabilities": value.capabilities,
    }


class RemoteDirectory(BaseAPIView):
    def get(self, request):
        stations = RemoteWorkstation.objects.select_related("agent__project__workspace").order_by(
            "username", "id"
        )
        if request.query_params.get("workspace"):
            stations = stations.filter(agent__project__workspace__slug=request.query_params["workspace"])
        if request.query_params.get("project"):
            stations = stations.filter(agent__project_id=request.query_params["project"])
        params = request.query_params
        paged = any(key in params for key in ("page", "per_page", "search", "status", "active"))
        page = serializers.IntegerField(min_value=1).run_validation(params.get("page", 1))
        size = serializers.ChoiceField(choices=(6, 12, 24)).run_validation(int(params.get("per_page", 6))) if str(params.get("per_page", 6)).isdigit() else None
        if size is None:
            raise ValidationError({"per_page": "请选择6、12或24台。"})
        state = serializers.ChoiceField(choices=("all", "online", "offline")).run_validation(params.get("status", "all"))
        active = [str(serializers.UUIDField().run_validation(value)) for value in params.get("active", "").split(",") if value]
        if len(active) > 2:
            raise ValidationError({"active": "最多保留两台当前操作电脑。"})
        # Permissions are memoized only within this request and checked before counts or pins.
        access = {}
        allowed = []
        for station in stations:
            key = (station.agent.project_id, station.agent.owner_id, station.enabled, station.agent.enabled)
            if key not in access:
                access[key] = permitted(request.user, station)
            if access[key]:
                allowed.append(station)
        if not paged:
            return Response({"results": [card(station, request.user, True) for station in allowed],
                "can_manage": is_administrator(request.user)})
        selected = [station for station in allowed if str(station.id) in active]
        search = str(params.get("search", "")).strip().casefold()[:200]
        visible = [station for station in allowed
            if (state == "all" or online(station) == (state == "online"))
            and (not search or search in " ".join([station.username, station.hostname, station.agent.name,
                str(station.capabilities.get("network", {}).get("ip_address", ""))]).casefold())]
        count = len(visible)
        page = min(page, max(1, (count + size - 1) // size))
        return Response({"results": [card(station, request.user, True) for station in visible[(page-1)*size:page*size]],
            "active_results": [card(station, request.user, True) for station in selected],
            "count": count, "page": page, "per_page": size, "can_manage": is_administrator(request.user)})

    @transaction.atomic
    def post(self, request):
        browser_boundary(request)
        action = request.data.get("action")
        if action == "register":
            if not is_administrator(request.user):
                raise PermissionDenied("仅管理员可登记远程采集电脑。")
            project = get_object_or_404(Project, pk=request.data.get("project_id"), archived_at__isnull=True)
            if not writable_member(project.id, request.user.id, project.workspace.slug):
                raise PermissionDenied()
            name = str(request.data.get("name", "采集电脑")).strip()[:120]
            agent = FieldAgent.objects.create(
                project=project, created_by=request.user, owner=request.user, name=name
            )
            raw = "rw_" + secrets.token_urlsafe(36)
            station = RemoteWorkstation.objects.create(
                agent=agent,
                credential_hash=digest(raw),
                credential_expires_at=timezone.now() + timedelta(days=30),
            )
            return Response({**card(station, request.user), "token": raw}, status=201)
        if action == "revoke":
            station = station_for(request.user, request.data.get("device_id"))
            station.enabled = False
            station.save(update_fields=["enabled"])
            for session in station.remoteterminal_set.exclude(status="closed"):
                close_session(session)
            station.commands.filter(status__in=["pending", "delivered"]).update(status="expired", payload={})
            fail_runs(station,"设备授权已撤销")
            return Response({"enabled": False})
        if action != "open":
            raise ValidationError("未知操作。")
        if set(request.data)-{'action','device_id','cols','rows','target','expected_target_revision'}:
            raise ValidationError('终端目标只能选择已登记的采集电脑或已连接机器人。')
        station = station_for(request.user, request.data.get("device_id"))
        station = RemoteWorkstation.objects.select_for_update(of=("self",)).select_related("agent__project__workspace").get(pk=station.pk)
        if not permitted(request.user, station):
            raise PermissionDenied()
        if not online(station):
            raise Conflict("采集电脑离线，请等待连接。")
        if station.remoteagentrun_set.filter(status__in=["queued","running"],expires_at__gt=timezone.now()).exists():
            raise Conflict("该电脑正在执行 Agent 任务，请结束后再打开人工终端。")
        from .remote_models import RemoteUploadedFile
        if RemoteUploadedFile.objects.filter(workstation=station,status="uploading",expires_at__gt=timezone.now()).exists():
            raise Conflict("该电脑正在上传文件，请完成或取消后再打开人工终端。")
        if (
            RemoteTerminal.objects.filter(
                workstation=station, status="open", expires_at__gt=timezone.now()
            ).count()
            >= 2
        ):
            raise Conflict("该电脑终端会话已达上限。")
        target=serializers.ChoiceField(choices=['operator','robot']).run_validation(request.data.get('target','operator'))
        target_identity={'username':station.username,'host':station.capabilities.get('network',{}).get('ip_address','')}
        revision=''
        if target=='robot':
            target_identity,revision=robot_target(station)
            if request.data.get('expected_target_revision')!=revision:
                raise Conflict('机器人已切换，请刷新后重新连接。')
        now = timezone.now()
        session = RemoteTerminal.objects.create(
            workstation=station, owner=request.user, target=target,target_identity=target_identity,target_revision=revision,last_read_at=now, expires_at=now + timedelta(hours=1)
        )
        cols = serializers.IntegerField(min_value=20, max_value=500).run_validation(
            request.data.get("cols", 100)
        )
        rows = serializers.IntegerField(min_value=5, max_value=200).run_validation(
            request.data.get("rows", 30)
        )
        command(
            station,
            {"kind": "terminal_open", "session_id": str(session.id), "cols": cols, "rows": rows,"target":target,"target_revision":revision},
            session=session,
        )
        return Response(terminal_snapshot(session), status=201)


class RemoteSession(BaseAPIView):
    def session(self, request, pk):
        session = get_object_or_404(
            RemoteTerminal.objects.select_related("workstation__agent__project__workspace"),
            pk=pk,
            owner=request.user,
        )
        RemoteWorkstation.objects.select_for_update(of=("self",)).get(pk=session.workstation_id)
        session.refresh_from_db()
        if session.workstation.remoteagentrun_set.filter(status="running",expires_at__gt=timezone.now()).exists():
            close_session(session)
        if session.status == "open" and session.last_read_at <= timezone.now()-timedelta(seconds=60):
            close_session(session)
        if not permitted(request.user, session.workstation):
            close_session(session)
            raise PermissionDenied()
        if session.expires_at <= timezone.now() or not terminal_target_valid(session,session.workstation):
            close_session(session)
        return session

    @transaction.atomic
    def get(self, request, pk):
        try:
            session = self.session(request, pk)
        except PermissionDenied:
            # Keep the invalidation committed when authorization changed.
            return Response({"error": "终端权限已失效。"}, status=403)
        if session.status != "closed" and not online(session.workstation):
            close_session(session)
        session.last_read_at = timezone.now()
        session.save(update_fields=["last_read_at"])
        after = serializers.IntegerField(min_value=0).run_validation(request.query_params.get("after", 0))
        events = list(session.events.filter(id__gt=after).order_by("id")[:100])
        return Response(
            {
                **terminal_snapshot(session),
                "error": session.error,
                "events": [{"seq": e.id, "source_id": e.source_id, "data": e.data} for e in events],
                "cursor": events[-1].id if events else after,
            }
        )

    @transaction.atomic
    def post(self, request, pk):
        browser_boundary(request)
        try:
            session = self.session(request, pk)
        except PermissionDenied:
            # Return inside atomic so the invalidation above is committed.
            return Response({"error": "终端权限已失效。"}, status=403)
        action = request.data.get("action")
        if action == "close":
            close_session(session)
            return Response({"status": "closed"})
        if session.status == "closed":
            return Response({"error": "终端已关闭。"}, status=409)
        if not online(session.workstation):
            raise Conflict("采集电脑离线。")
        if action == "input":
            data = serializers.CharField(
                max_length=44000, allow_blank=False, trim_whitespace=False
            ).run_validation(request.data.get("data"))
            try:
                if len(base64.b64decode(data, validate=True)) > 4096:
                    raise ValueError()
            except Exception:
                raise ValidationError("终端输入编码无效。")
            payload = {"kind": "terminal_input", "session_id": str(session.id), "data": data}
        elif action == "resize":
            payload = {
                "kind": "terminal_resize",
                "session_id": str(session.id),
                "cols": serializers.IntegerField(min_value=20, max_value=500).run_validation(
                    request.data.get("cols")
                ),
                "rows": serializers.IntegerField(min_value=5, max_value=200).run_validation(
                    request.data.get("rows")
                ),
            }
        else:
            raise ValidationError("未知终端操作。")
        if session.remotecommand_set.filter(status="pending").count() > 100:
            raise Conflict("终端输入积压，请稍后重试。")
        command(session.workstation, payload, session=session, lifetime=10)
        return Response({"accepted": True})


class WorkstationAuthentication(BaseAuthentication):
    def authenticate_header(self, request):
        return "Bearer"

    def authenticate(self, request):
        raw = request.headers.get("Authorization", "").removeprefix("Bearer ")
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


class RemoteExchange(BaseAPIView):
    authentication_classes = [WorkstationAuthentication]

    def perform_authentication(self, request):
        # WorkstationAuthentication checks the credential and current project permissions;
        # high-frequency transport must not synchronize unrelated admin memberships.
        request.user

    @transaction.atomic
    def post(self, request):
        station = RemoteWorkstation.objects.select_for_update(of=("self",)).select_related("agent__owner", "agent__project__workspace").get(pk=request.auth.pk)
        now = timezone.now()
        if not permitted(station.agent.owner, station) or station.credential_expires_at <= now:
            raise AuthenticationFailed("现场连接凭据已失效。")
        if len(json.dumps(request.data)) > 1500000:
            raise ValidationError("现场消息超过限制。")
        identity = request.data.get("identity", {})
        if not isinstance(identity, dict):
            raise ValidationError("电脑身份无效。")
        boot = str(identity.get("boot_id", ""))[:120]
        interrupted = (
            station.boot_id
            and station.boot_id != boot
            or station.last_seen_at
            and (now - station.last_seen_at).total_seconds() > 30
            or bool(station.last_seen_at) and (
                station.hostname != str(identity.get("hostname", ""))[:200]
                or station.username != str(identity.get("username", ""))[:120]
            )
        )
        if interrupted:
            for session in station.remoteterminal_set.exclude(status="closed"):
                close_session(session)
            fail_runs(station, "现场连接身份已变化，旧任务已停止。")
            station.commands.filter(status__in=["pending", "delivered"], run__isnull=False).update(status="expired", payload={})
        station.username = str(identity.get("username", ""))[:120]
        station.hostname = str(identity.get("hostname", ""))[:200]
        station.boot_id = boot
        station.last_seen_at = now
        capabilities = identity.get("capabilities", {})
        if isinstance(capabilities, dict) and len(json.dumps(capabilities)) < 16000:
            from .remote_profiles import daq_profile
            station.capabilities = {
                **capabilities,
                "agent_context": daq_profile(station.capabilities.get("agent_context", {}), capabilities),
            }
        station.save()
        for run in station.remoteagentrun_set.filter(status__in=["queued", "running"]).select_related("owner"):
            if run.expires_at <= now or run.identity_key != identity_key(station) or not permitted(run.owner, station):
                invalidate_run(run,"任务现场身份或操作权限已变化。")
        outputs = request.data.get("outputs", [])
        results = request.data.get("results", [])
        if (
            not isinstance(outputs, list)
            or len(outputs) > 100
            or not isinstance(results, list)
            or len(results) > 100
        ):
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
                row.status="expired"
                row.payload={}
                row.save(update_fields=["status","payload"])
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
                from .remote_files import record_upload_result
                record_upload_result(row)
            if row.payload.get("kind") == "file_browser" and row.payload.get("request", {}).get("action") == "upload_chunk":
                row.payload = {}
            # Interactive inputs are transport buffers, never retained as an audit transcript.
            if row.session_id:
                row.payload = {}
                row.result = {"ok": bool(value.get("ok")),
                    "terminal_roundtrip_ms": round((timezone.now()-row.created_at).total_seconds()*1000,1)}
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
            RemoteTerminalEvent.objects.get_or_create(
                session=session, source_id=source, defaults={"data": data}
            )
            cutoff = list(session.events.order_by("-id").values_list("id", flat=True)[200:201])
            if cutoff:
                session.events.filter(id__lte=cutoff[0]).delete()
        for session in station.remoteterminal_set.filter(status="open").select_related("owner"):
            if session.expires_at < now or (now - session.last_read_at).total_seconds() > 60 or not permitted(session.owner, station) or not terminal_target_valid(session,station):
                close_session(session)
        station.commands.filter(status__in=["pending", "delivered"], expires_at__lte=now).update(
            status="expired", payload={}
        )
        station.commands.filter(
            run__status__in=["failed", "completed"], status__in=["pending", "delivered"]
        ).update(status="expired", payload={})
        station.commands.filter(run__expires_at__lte=now, status__in=["pending", "delivered"]).update(
            status="expired", payload={}
        )
        RemoteTerminalEvent.objects.filter(
            session__workstation=station,
            session__status="closed",
            session__last_read_at__lt=now - timedelta(minutes=2),
        ).delete()
        pending = list(
            station.commands.filter(status__in=["pending", "delivered"], expires_at__gt=now).order_by(
                "created_at", "id"
            )[:50]
        )
        allowed_pending = []
        for row in pending:
            if row.payload.get("kind") == "file_browser":
                job = getattr(row, "file_request", None)
                if not job or not permitted(job.owner, station) or job.identity_key != identity_key(station):
                    row.status = "expired"
                    row.payload = {}
                    row.save(update_fields=["status", "payload"])
                    continue
            allowed_pending.append(row)
        task = next((row for row in allowed_pending if row.payload.get("kind") in {"run", "read_file", "patch_file", "file_browser"}), None)
        pending = [row for row in allowed_pending if row.payload.get("kind") not in {"run", "read_file", "patch_file", "file_browser"} or row is task]
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
        return Response({"commands": payload})


class RemoteFeedback(BaseAPIView):
    def get(self, request):
        station = station_for(request.user, request.query_params.get("device_id"))
        from .models import BusinessNumber
        rows = feedback_for(station)
        query = str(request.query_params.get("q", "")).strip()[:200]
        if query:
            numbered = BusinessNumber.objects.filter(resource="quality.defect", code__icontains=query).values("object_id")
            rows = rows.filter(Q(title__icontains=query) | Q(description__icontains=query) | Q(pk__in=numbered))
        latest = RemoteAgentRun.objects.filter(workstation=station, defect_id=OuterRef("pk")).order_by("-created_at", "-id")
        from .agent_lifecycle import with_mutation_evidence
        latest=with_mutation_evidence(latest)
        rows=rows.annotate(latest_mutation=Subquery(latest.values('processing_mutation')[:1]))
        rows = rows.annotate(latest_run_status=Subquery(latest.values("status")[:1]), latest_mode=Subquery(latest.values("mode")[:1]), latest_outcome=Subquery(latest.values("result__outcome")[:1]), latest_repaired=Subquery(latest.values("result__repaired")[:1]), latest_verified=Subquery(latest.values("result__verification_passed")[:1]), latest_run_id=Subquery(latest.values("id")[:1]), run_count=Count("remoteagentrun", filter=Q(remoteagentrun__workstation=station), distinct=True))
        rows = rows.annotate(latest_status=Case(
            When(latest_run_status__in=["queued", "running"], then=Value("running")),
            When(latest_run_status="completed", latest_repaired=True, latest_verified=True, then=Value("repaired")),
            When(latest_run_status="completed", latest_outcome__in=["verified","verified_without_repair"], latest_verified=True, latest_mutation=False, then=Value("verified")),
            When(latest_run_status__isnull=True, then=Value("pending")),
            default=Value("unresolved"), output_field=CharField()))
        state = serializers.ChoiceField(choices=["all", "needs_attention", "pending", "running", "repaired", "unresolved"]).run_validation(request.query_params.get("state", "all"))
        if state == "needs_attention": rows = rows.exclude(latest_status__in=["repaired","verified"])
        elif state == "repaired": rows = rows.filter(latest_status__in=["repaired","verified"])
        elif state != "all": rows = rows.filter(latest_status=state)
        page = serializers.IntegerField(min_value=1).run_validation(request.query_params.get("page", 1))
        size = serializers.IntegerField(min_value=1,max_value=50).run_validation(request.query_params.get("per_page", 20))
        count = rows.count()
        rows = list(rows.order_by("-created_at", "-id")[(page-1)*size:page*size])
        from .numbering import preload
        preload(rows)
        return Response({"count":count,"page":page,"per_page":size,"results": [{"id": str(d.id), "title": d.title, "code": d.code, "latest_status": d.latest_status, "latest_run_id":str(d.latest_run_id) if d.latest_run_id else None, "run_count":d.run_count, "created_at":d.created_at} for d in rows]})


def run_queue(run):
    """Database wait state, never an estimate of model completion time."""
    if run.status not in {"queued", "running"}:
        return None
    station = run.workstation
    now = timezone.now()
    if run.status == "running":
        cached=getattr(run,'_processing_commands',None)
        latest = (cached[0] if cached else None) if cached is not None else run.remotecommand_set.order_by("-created_at", "-id").first()
        stage = "inspect" if latest else "analysis"
        if latest:
            from .remote_event_display import safe_argv
            context = run.result.get('display_policy_snapshot') or station.capabilities.get("agent_context", {})
            argv = safe_argv(latest.payload.get("argv"))
            if argv and argv == safe_argv(context.get("verify_argv")):
                stage = "verify"
            elif latest.payload.get("kind") == "patch_file" or (
                context.get("repair_argv") and isinstance(argv, list)
                and argv[:len(context["repair_argv"])] == safe_argv(context["repair_argv"])
            ):
                stage = "repair"
        return {"position": None, "reason": "", "stage": stage}
    from .remote_models import RemoteUploadedFile
    earlier = Q(created_at__lt=run.created_at) | Q(created_at=run.created_at, id__lt=run.id)
    # Position is limited to this device; other workers can serve other devices.
    waiting = station.remoteagentrun_set.filter(status="queued", expires_at__gt=now).filter(earlier).count()
    reason = "worker_busy"
    if station.remoteterminal_set.filter(status="open", expires_at__gt=now, last_read_at__gt=now-timedelta(seconds=60)).exists():
        reason = "terminal_open"
    elif RemoteUploadedFile.objects.filter(workstation=station,status="uploading",expires_at__gt=now).exists():
        reason = "transfer_active"
    elif waiting or station.remoteagentrun_set.filter(status="running",expires_at__gt=now).exists():
        reason = "device_busy"
    return {"position": waiting, "reason": reason, "stage": "queued"}


class RemoteRuns(BaseAPIView):
    @transaction.atomic
    def post(self, request):
        browser_boundary(request)
        station = station_for(request.user, request.data.get("device_id"))
        station = RemoteWorkstation.objects.select_for_update(of=("self",)).select_related("agent__project__workspace").get(pk=station.pk)
        if not permitted(request.user, station):
            raise PermissionDenied()
        if not online(station):
            raise Conflict("采集电脑离线。")
        defect = get_object_or_404(
            feedback_for(station, request.data.get("defect_id")), pk=request.data.get("defect_id")
        )
        defect=Defect.objects.select_for_update().get(pk=defect.pk)
        problem = serializers.CharField(max_length=8000).run_validation(request.data.get("problem"))
        mode = serializers.ChoiceField(choices=["diagnose", "repair", "verify"], default="repair").run_validation(request.data.get("mode", "repair"))
        binding,_=daq_binding(defect)
        if binding.get('execution_scope')=='verify_only' and mode!='verify':
            raise Conflict('这条历史反馈仅批准在原采集电脑重新验证，请使用重新验证。')
        active = RemoteAgentRun.objects.filter(workstation=station, status__in=["queued", "running"], expires_at__gt=timezone.now())
        if active.filter(defect=defect).exists():
            raise Conflict("这条反馈已有处理任务，请查看当前进度。")
        if active.count() >= 20:
            raise Conflict("这台采集电脑待处理任务已达上限，请稍后提交。")
        for session in station.remoteterminal_set.filter(status="open", last_read_at__lte=timezone.now()-timedelta(seconds=60)):
            close_session(session)
        run = RemoteAgentRun.objects.create(
            workstation=station,
            defect=defect,
            owner=request.user,
            problem=problem,
            mode=mode,
            expires_at=timezone.now() + timedelta(minutes=30),
            identity_key=identity_key(station),
            result={'defect_state_version':defect.edit_version},
        )
        DefectEvent.objects.create(project_id=defect.project_id,defect=defect,created_by=request.user,previous_status=defect.status,status=defect.status,note=f"Agent {'重新诊断' if mode == 'diagnose' else '重新验证' if mode == 'verify' else '诊断与自动修复'}：已进入队列；任务 {run.id}。")
        from .remote_tasks import remote_repair

        transaction.on_commit(lambda: remote_repair.apply_async(args=[str(run.id)], queue="field-repairs"))
        return Response({"id": str(run.id), "status": run.status, "queue": run_queue(run)}, status=201)


class RemoteDefectTargets(BaseAPIView):
    def get(self, request):
        defect=get_object_or_404(Defect,pk=request.query_params.get('defect_id'))
        if not writable_member(defect.project_id,request.user.id,defect.project.workspace.slug):raise PermissionDenied()
        binding,fixed=daq_binding(defect)
        if binding['kind']=='daq':
            available=[fixed] if fixed is not None and permitted(request.user,fixed) else []
        else:
            stations=RemoteWorkstation.objects.filter(agent__project_id=defect.project_id).select_related('agent__project__workspace')
            available=[station for station in stations if permitted(request.user,station)and feedback_for(station,defect.id).exists()]
        active=RemoteAgentRun.objects.filter(defect=defect,owner=request.user,workstation__in=available,
            status__in=['queued','running'],expires_at__gt=timezone.now()).select_related('workstation__agent__project__workspace').order_by('-created_at').first()
        return Response({'binding':binding,'results':[card(station,request.user)for station in available],
            'active_run':{'id':str(active.id),'status':active.status,'queue':run_queue(active),'error':active.error}if active else None})


class RemoteRunDetail(BaseAPIView):
    def get(self, request, pk):
        run = get_object_or_404(
            RemoteAgentRun.objects.select_related("workstation__agent__project__workspace"),
            pk=pk,
            owner=request.user,
        )
        if not permitted(request.user, run.workstation):
            raise PermissionDenied()
        if run.status in {"queued", "running"} and run.expires_at <= timezone.now():
            invalidate_run(run,"远程任务已超时，现场恢复未确认。")
        return Response({"id": str(run.id), "status": run.status, "result": run.result, "error": run.error, "queue": run_queue(run)})


class ToolAuthentication(BaseAuthentication):
    def authenticate_header(self, request):
        return "Bearer"

    def authenticate(self, request):
        raw = request.headers.get("Authorization", "").removeprefix("Bearer ")
        run = (
            RemoteAgentRun.objects.select_related("owner", "workstation__agent__project__workspace")
            .filter(tool_credential_hash=digest(raw), status="running", expires_at__gt=timezone.now())
            .first()
            if raw.startswith("rr_")
            else None
        )
        if not run or not permitted(run.owner, run.workstation) or run.identity_key != identity_key(run.workstation):
            raise AuthenticationFailed("Agent工具会话无效。")
        return run.owner, run


class RemoteTool(BaseAPIView):
    authentication_classes = [ToolAuthentication]

    def post(self, request):
        run = request.auth
        if not online(run.workstation):
            raise Conflict("现场电脑离线。")
        if run.remotecommand_set.count() >= 20:
            raise Conflict("已达本轮工具次数上限。")
        op = request.data.get("operation")
        if op not in {"run", "read_file", "patch_file"}:
            raise ValidationError("不支持的现场工具。")
        payload = {"kind": op}
        if op == "run":
            payload["argv"] = serializers.ListField(
                child=serializers.CharField(max_length=2000), min_length=1, max_length=30
            ).run_validation(request.data.get("argv"))
            payload["cwd"] = str(request.data.get("cwd") or ".")[:500]
            payload["timeout"] = serializers.IntegerField(min_value=1, max_value=30).run_validation(
                request.data.get("timeout", 20)
            )
        else:
            payload["path"] = serializers.CharField(max_length=500).run_validation(request.data.get("path"))
            if op == "patch_file":
                payload["content"] = serializers.CharField(
                    max_length=100000, allow_blank=True, trim_whitespace=False
                ).run_validation(request.data.get("content"))
                payload["expected_sha256"] = serializers.RegexField(r"^[a-f0-9]{64}$").run_validation(
                    request.data.get("expected_sha256")
                )
        from .remote_tools_policy import check_tool
        with transaction.atomic():
            station = RemoteWorkstation.objects.select_for_update(of=("self",)).select_related("agent__project__workspace").get(pk=run.workstation_id)
            run.refresh_from_db()
            if run.status != "running" or run.expires_at <= timezone.now() or run.identity_key != identity_key(station) or not permitted(run.owner, station):
                raise PermissionDenied("远程任务身份或权限已失效。")
            tool_context = dict(station.capabilities.get("agent_context", {}))
            tool_context["repair_allowed"] = tool_context.get("repair_allowed") is True and run.mode == "repair"
            check_tool(tool_context, op, payload)
            fixed_argv = payload.get('argv', [])
            if op == 'run' and fixed_argv[:1] == ['daq-local-diagnostics-v1']:
                target=run.result.get('configuration_target')
                if isinstance(target,str) and re.fullmatch(r'[A-Za-z0-9_-]{1,80}',target):
                    payload['configuration_target']=target
                    if fixed_argv[1:2] == ['repair']:
                        observed=run.remotecommand_set.filter(status='done',payload__argv=['daq-local-diagnostics-v1','inspect'],
                            payload__configuration_target=target).order_by('-created_at','-id').first()
                        try:
                            configuration=json.loads(observed.result.get('stdout','{}')).get('configuration',{}) if observed else {}
                        except (ValueError,TypeError,AttributeError):configuration={}
                        revision=configuration.get('target_revision')
                        if (not isinstance(revision,str) or not re.fullmatch(r'[a-f0-9]{64}',revision)
                                or configuration.get('snapshot_sha256') != fixed_argv[-1]):
                            raise Conflict('请先读取本轮目标配置，再按当前快照执行修复。')
                        payload['expected_configuration_revision']=revision
                elif fixed_argv[1:2] == ['repair']:
                    _, payload['expected_target_revision'] = robot_target(station)
            if run.remotecommand_set.filter(status__in=["pending", "delivered"],expires_at__gt=timezone.now()).exists():
                raise Conflict("上一个现场操作尚未完成，请等待结果。")
            if run.remotecommand_set.count() >= 20:
                raise Conflict("已达本轮工具次数上限。")
            row = command(station, payload, run=run, lifetime=40)
        deadline = time.monotonic() + 38
        while time.monotonic() < deadline:
            row.refresh_from_db()
            if row.status == "done":
                return Response(row.result)
            if row.status == "expired":
                raise Conflict("现场任务已过期，未重复执行。")
            time.sleep(0.25)
        return Response(
            {
                "ok": False,
                "error": "现场执行结果未到达，状态未知；不要重复提交同一修复。",
                "command_id": str(row.id),
            },
            status=504,
        )
