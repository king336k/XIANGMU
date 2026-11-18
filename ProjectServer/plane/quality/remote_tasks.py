"""Model tools request bounded field operations; final answer returns to the original defect."""

import hashlib
import json
import os
import secrets
import subprocess

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
        RemoteWorkstation.objects.select_for_update().get(pk=station_id)
        run = (
            RemoteAgentRun.objects.select_for_update()
            .select_related("workstation__agent__project__workspace")
            .get(pk=run_id)
        )
        if run.status not in {"queued", "running"}:
            return
        if run.identity_key != identity_key(run.workstation) or not permitted(run.owner,run.workstation):
            result={"summary":"现场身份或授权已变化，本轮结果不能确认恢复。","repaired":False}
            status="failed";error="现场身份或授权已变化"
        fields = [
            ("结论", "summary"),
            ("原因与证据", "root_cause"),
            ("已执行操作", "actions"),
            ("复测", "verification"),
            ("后续方案", "solution"),
        ]
        verified_only = run.mode == "verify" and result.get("outcome") == "verified" and result.get("verification_passed") is True
        outcome = "已修复" if result.get("repaired") is True else "验证通过" if verified_only else "未自动修复"
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
        run.save(update_fields=["result", "status", "error", "tool_credential_hash", "comment"])
        DefectEvent.objects.create(project_id=run.defect.project_id, defect=run.defect, created_by=run.owner,
            previous_status=run.defect.status, status=run.defect.status,
            note="Agent 处理结束：" + ("已修复并通过复测" if result.get("repaired") is True else "验证通过，未修改现场" if verified_only else "未自动修复，根因及后续方案见现场处理结果") + f"；任务 {run.id}。")


@shared_task(name="plane.quality.remote_repair", soft_time_limit=400, time_limit=430)
def remote_repair(run_id):
    with transaction.atomic():
        station_id=RemoteAgentRun.objects.values_list('workstation_id',flat=True).get(pk=run_id)
        RemoteWorkstation.objects.select_for_update().get(pk=station_id)
        run = (
            RemoteAgentRun.objects.select_for_update()
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
        raw = "rr_" + secrets.token_urlsafe(36)
        run.tool_credential_hash = hashlib.sha256(raw.encode()).hexdigest()
        run.status = "running"
        run.save(update_fields=["status", "tool_credential_hash"])
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
    try:
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
