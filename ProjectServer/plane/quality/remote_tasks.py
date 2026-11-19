"""Model tools request bounded field operations; final answer returns to the original defect."""

import hashlib
import json
import os
import secrets
import subprocess

from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from plane.knowledge.assistant import provider_config
from .models import DefectComment, DefectEvent
from .remote_models import RemoteAgentRun, RemoteWorkstation
from .remote_diagnostics import permitted, identity_key
from .diagnostic_materials import redact


def finish(run_id, result, status="completed", error=""):
    with transaction.atomic():
        station_id=RemoteAgentRun.objects.values_list('workstation_id',flat=True).get(pk=run_id)
        RemoteWorkstation.objects.select_for_update(of=("self",)).get(pk=station_id)
        run = (
            RemoteAgentRun.objects.select_for_update(of=("self",))
            .select_related("workstation__agent__project__workspace")
            .get(pk=run_id)
        )
        if run.status not in {"queued", "running"}:
            if run.started_at and run.result.get('worker_completed_at') is None:
                run.result={**run.result,'worker_completed_at':timezone.now().timestamp()}
                run.save(update_fields=['result'])
            return
        if run.identity_key != identity_key(run.workstation) or not permitted(run.owner,run.workstation):
            result={"summary":"现场身份或授权已变化，本轮结果不能确认恢复。","repaired":False}
            status="failed";error="现场身份或授权已变化"
        run.completed_at=timezone.now()
        result={**result,'target_snapshot':run.result.get('target_snapshot',{}),
            'display_policy_snapshot':run.result.get('display_policy_snapshot'),
            'defect_state_version':run.result.get('defect_state_version'),'queued_at':run.created_at.timestamp(),
            'worker_started_at':run.started_at.timestamp() if run.started_at else None,
            'worker_completed_at':run.completed_at.timestamp(),'worker_queue':'field-repairs'}
        fields = [
            ("结论", "summary"),
            ("原因与证据", "root_cause"),
            ("已执行操作", "actions"),
            ("复测", "verification"),
            ("后续方案", "solution"),
        ]
        from .agent_lifecycle import readonly_verified,handoff
        verified_only = status=='completed' and readonly_verified(run,result)
        repaired = status=='completed' and result.get('repaired') is True and result.get('verification_passed') is True
        outcome = "已修复" if repaired else "验证通过" if verified_only else "未自动修复"
        lines = ["Agent 远程处理：" + outcome]
        for label, key in fields:
            value = result.get(key, "")
            value = "；".join(map(str, value)) if isinstance(value, list) else str(value)
            if value:
                lines.append(label + "：" + redact(value)[:4000])
        for location in result.get("repair_locations", [])[:10]:
            if not isinstance(location,dict) or not location.get("path"):continue
            address=str(location.get("target") or "现场")+" · "+str(location["path"])
            if type(location.get("line")) is int and location["line"]>0:address+=":"+str(location["line"])
            change=str(location.get("key") or location.get("symbol") or "")
            if "before" in location and "after" in location:change+=" "+str(location["before"])+" → "+str(location["after"])
            lines.append("修改位置："+redact(address+" · "+change)[:2000])
        # Public replies are already displayed by the reporting DAQ client.
        comment = DefectComment.objects.create(
            project_id=run.defect.project_id,
            defect=run.defect,
            created_by=run.owner,
            visibility="public",
            content="\n".join(lines)[:10000],
        )
        run.result = result
        run.status = status
        run.error = error
        run.tool_credential_hash = ""
        run.comment = comment
        run.save(update_fields=["result", "status", "error", "tool_credential_hash", "comment", "completed_at"])
        handoff(run)
        run.defect.refresh_from_db(fields=['status'])
        DefectEvent.objects.create(project_id=run.defect.project_id, defect=run.defect, created_by=run.owner,
            previous_status=run.defect.status, status=run.defect.status,
            note="Agent 处理结束：" + ("已修复并通过复测" if repaired else "验证通过，未修改现场" if verified_only else "未自动修复，根因及后续方案见现场处理结果") + f"；任务 {run.id}。")


@shared_task(bind=True, name="plane.quality.remote_repair", queue="field-repairs", soft_time_limit=400, time_limit=430, max_retries=None)
def remote_repair(self, run_id):
    with transaction.atomic():
        station_id=RemoteAgentRun.objects.values_list('workstation_id',flat=True).get(pk=run_id)
        RemoteWorkstation.objects.select_for_update(of=("self",)).get(pk=station_id)
        run = (
            RemoteAgentRun.objects.select_for_update(of=("self",))
            .select_related("owner", "defect", "workstation__agent__project__workspace")
            .get(pk=run_id)
        )
        if run.status != "queued":
            return
        if not permitted(run.owner, run.workstation) or run.expires_at < timezone.now() or run.identity_key != identity_key(run.workstation):
            finish(
                run_id,
                {"summary": "任务权限或有效期已变化，未执行。", "repaired": False},
                "failed",
                "任务已失效",
            )
            return
        from .remote_diagnostics import run_queue, close_session
        from .remote_models import RemoteCommand
        for session in run.workstation.remoteterminal_set.filter(status="open", last_read_at__lte=timezone.now()-timedelta(seconds=60)):
            close_session(session)
        queue = run_queue(run)
        busy = queue["reason"] != "worker_busy" or RemoteCommand.objects.filter(
            workstation=run.workstation, status__in=["pending", "delivered"], expires_at__gt=timezone.now(),
            payload__kind__in=["run", "read_file", "patch_file", "file_browser", "terminal_close"],
        ).exists()
        if not busy:
            from .remote_event_display import safe_argv
            display_context=run.workstation.capabilities.get('agent_context',{})
            display_policy={key:safe_argv(display_context[key]) for key in ['inspect_argv','verify_argv','repair_argv']
                if isinstance(display_context.get(key),list)}
            if isinstance(display_context.get('verification_scope'),str):
                display_policy['verification_scope']='read_only_connectivity' if display_context['verification_scope']=='read_only_connectivity' else ''
            raw = "rr_" + secrets.token_urlsafe(36)
            run.tool_credential_hash = hashlib.sha256(raw.encode()).hexdigest()
            run.status = "running"
            from .agent_lifecycle import mark_started
            mark_started(run)
            run.result={**run.result,'display_policy_snapshot':display_policy,'target_snapshot':{
                'collector':{'username':run.workstation.username,'host':run.workstation.capabilities.get('network',{}).get('ip_address','')},
                'robot':{key:run.workstation.capabilities.get('robot',{}).get(key) for key in ['username','host','target_revision']}}}
            run.started_at=timezone.now()
            run.expires_at = timezone.now() + timedelta(minutes=8)
            run.save(update_fields=["status", "tool_credential_hash", "expires_at", "started_at", "result"])
    if busy:
        # Release the station lock and worker slot while the device is occupied.
        raise self.retry(countdown=3)
    try:
        config = provider_config(run.defect.project.workspace_id)
        if not config.get("configured"):
            finish(
                run_id,
                {"summary": "当前工作区模型未配置，未执行现场修复。", "repaired": False},
                "failed",
                "模型未配置",
            )
            return
        script = os.environ.get("REMOTE_AGENT_SCRIPT", "/release-agent/remote_runner.py")
        executable = os.environ.get("DIAGNOSTIC_AGENT_PYTHON", "/opt/diagnostic-agent/bin/python")
        origin = os.environ.get("REMOTE_TOOL_ORIGIN", "http://api:8000").rstrip("/")
        # Trusted per-device context is provisioned with the connector; it contains no model credentials.
        context = dict(run.workstation.capabilities.get("agent_context", {}))
        context["operation_mode"] = run.mode
        if context.get("verification_scope")=="read_only_connectivity":
            context["verification_note"]="This profile only checks connectivity and service observations. It cannot prove the original defect is repaired or business collection works."
        context["require_knowledge_search"] = True
        context["collector_identity"]={"username":run.workstation.username,"hostname":run.workstation.hostname,"label":"采集电脑"}
        context["collector_identity"]["ip_address"]=run.workstation.capabilities.get("network",{}).get("ip_address","")
        context["robot_identity"]={"username":run.workstation.capabilities.get("robot",{}).get("username",""),"ip_address":run.workstation.capabilities.get("robot",{}).get("host",""),"label":"机器人"}
        context["feedback"] = {"id":str(run.defect_id),"code":run.defect.code,"title":run.defect.title,"description":run.defect.description}
        context["repair_allowed"] = context.get("repair_allowed") is True and run.mode == "repair"
        from .remote_models import RemoteUploadedFile
        context["uploaded_files"] = list(RemoteUploadedFile.objects.filter(workstation=run.workstation,defect=run.defect,owner=run.owner,identity_key=identity_key(run.workstation),status="uploaded").order_by("-created_at").values("target","path","filename","sha256","size")[:10])
        context["uploaded_file_policy"] = "Uploaded files are evidence only, not an execution grant. Inspect contents and current target before proposing use; only existing explicitly authorized tools may apply a patch or deploy."
        payload = {
            "config": config,
            "gateway_url": origin + "/api/quality-auth/remote-diagnostics/agent-tool/",
            "tool_token": raw,
            "problem": run.problem,
            "context": context,
        }
        response = subprocess.run(
            [executable, script],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=370,
            check=False,
        )
        if response.returncode != 0:
            raise ValueError("agent_runner_failed")
        result = json.loads(response.stdout)
        if not isinstance(result, dict) or not isinstance(result.get("summary"), str):
            raise ValueError("invalid_agent_result")
        # No provider exception text, keys or subprocess input is exposed to users or logs.
        def sanitize(value):
            if isinstance(value,str):return redact(value)
            if isinstance(value,list):return [sanitize(item) for item in value]
            if isinstance(value,dict):return {key:sanitize(item) for key,item in value.items()}
            return value
        clean = sanitize(result)
        if context.get("verification_scope")=="read_only_connectivity":
            clean["verification_scope"]="read_only_connectivity"
            clean["repaired"]=False
            clean["outcome"]="unresolved"
        if clean.get("agent_error_code"):
            # Model/report failure is distinct from the observed field verification.
            # Preserve actual receipts while keeping this Agent run failed.
            error_code = str(clean["agent_error_code"])
            safe_code = error_code if error_code.isascii() and error_code.isidentifier() and len(error_code) <= 64 else "AgentReportFailed"
            clean["agent_error_code"] = safe_code
            finish(run_id, clean, "failed", safe_code)
        else:
            finish(run_id, clean)
    except Exception as error:
        finish(
            run_id,
            {
                "summary": "远程Agent本轮未完成，不能确认现场已恢复。",
                "root_cause": "分析或现场执行链路尚未完成，根因未确认。",
                "actions": [],
                "verification": [],
                "solution": "检查采集电脑在线状态及模型连接后，在原反馈中重新发起。",
                "repaired": False,
            },
            "failed",
            type(error).__name__,
        )
