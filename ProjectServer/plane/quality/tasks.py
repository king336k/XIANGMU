# SPDX-License-Identifier: AGPL-3.0-only
"""Bounded diagnostics with evidence-gated, single-owner assignment after completion."""

import time
from celery import shared_task
from openai import APITimeoutError
from django.db import transaction
from django.utils import timezone
from .models import DiagnosticJob, Defect
from .diagnostic_materials import inspect, redact, diagnostic_search_query
from .diagnostic_model import analyze_diagnostic
from .diagnostic_rules import evaluate
from .log_evidence import summarize
from plane.knowledge.retrieval import search
from plane.knowledge import assistant
from .diagnostic_limits import timeout_seconds, task_limits

DIAGNOSTIC_SOFT_LIMIT, DIAGNOSTIC_HARD_LIMIT = task_limits()


@shared_task(
    name="plane.quality.run_diagnostic", soft_time_limit=DIAGNOSTIC_SOFT_LIMIT, time_limit=DIAGNOSTIC_HARD_LIMIT
)
def run_diagnostic(job_id):
    with transaction.atomic():
        job = DiagnosticJob.objects.select_for_update().select_related("defect", "project").filter(pk=job_id).first()
        if not job or job.status != "queued":
            return
        from .permissions import writable_member, capable, is_administrator
        from .data_regression import manager

        from .daq_reporting import report_only_diagnostic_access

        report_only = report_only_diagnostic_access(job)
        automatic = job.mode == "auto" and job.result.get("trigger") in {"daq_report", "materials_verified"}
        allowed = (
            capable(job.project_id, job.created_by_id, "report")
            if automatic
            else capable(job.project_id, job.created_by_id, "manage_defect")
            and (manager(job.project_id, job.created_by) or job.defect.assignee_id == job.created_by_id)
        )
        from .diagnostics import automatic_source_available

        administrator = not automatic and is_administrator(job.created_by_id)
        if report_only or administrator:
            allowed = True
        if automatic and not automatic_source_available(job.defect):
            allowed = False
        if (
            not job.created_by_id
            or not job.created_by.is_active
            or (
                not report_only
                and not administrator
                and not writable_member(job.project_id, job.created_by_id, job.project.workspace.slug)
            )
            or not allowed
        ):
            job.status = "failed"
            job.error_code = "ACCESS_REVOKED"
            job.completed_at = timezone.now()
            job.save()
            return
        job.status = "running"
        job.started_at = timezone.now()
        job.result = {**job.result, "progress": {"stage": "reading_materials", "at": job.started_at.isoformat()}}
        job.save()
    started = time.monotonic()
    if report_only:
        from .models import PackageFile

        snapshot = dict(job.result.get("input") or {})
        files = PackageFile.objects.filter(
            package__defect=job.defect,
            created_by_id=job.created_by_id,
            package__created_by_id=job.created_by_id,
        )
        permitted_files = list(map(str, files.values_list("id", flat=True)))
        if "files" in snapshot:
            wanted = set(map(str, snapshot["files"])) if isinstance(snapshot["files"], list) else set()
            permitted_files = [pk for pk in permitted_files if pk in wanted]
        snapshot["files"] = permitted_files
        job.result = {**job.result, "input": snapshot}
    meta = {key: job.result[key] for key in ["trigger", "input", "version", "retry"] if key in job.result}
    status, code = "completed", ""
    result = dict(meta)
    try:
        materials = {}
        text, sources, findings = inspect(job, materials) if job.mode in {"llm", "auto"} else inspect(job)
        facts = meta.get("input", {}).get("context", {})
        findings = [*findings, *evaluate(facts)]
        result.update(
            method="rules",
            notice="规则检查（未调用模型）",
            sources=sources,
            findings=findings,
            model_status="not_requested",
            timeout_seconds=timeout_seconds(),
            progress={"stage": "rule_check", "at": timezone.now().isoformat()},
            materials_status="read" if sources else "awaiting_materials",
            read_bytes=sum(row["read_bytes"] for row in sources),
            input_scope={
                "model_text_chars": min(len(text), 12000),
                "model_text_truncated": len(text) > 12000,
                "max_file_bytes": 256 * 1024,
                "max_total_bytes": 1024 * 1024,
            },
        )
        # Save the useful baseline before a slow or failed provider request.
        DiagnosticJob.objects.filter(pk=job.pk, status="running").update(result=result)
        from .models import ProblemPackage

        incomplete_upload = ProblemPackage.objects.filter(defect=job.defect).exclude(status="files_verified").exists()
        if incomplete_upload or (automatic and (not meta.get("input", {}).get("files") or not sources)):
            result["model_status"] = "awaiting_materials"
        elif any(row.get("scan_incomplete") for row in sources):
            result["model_status"] = "material_scan_incomplete"
        elif job.mode in {"llm", "auto"}:
            config = assistant.provider_config(job.project.workspace_id)
            if not config["configured"]:
                result["model_status"] = "unconfigured"
            elif time.monotonic() - started > 20:
                result["model_status"] = "timeout"
                result["model_error_code"] = "MODEL_TIMEOUT"
            else:
                model_text = summarize(redact(text), 12000)
                # A collector may submit to a project without acquiring its knowledge access.
                revisions = [] if report_only else list(search(job.project, diagnostic_search_query(text, sources))[:5])
                references = assistant.reference_payload(revisions, diagnostic_search_query(text, sources))
                try:
                    result["progress"] = {"stage": "model_analysis", "at": timezone.now().isoformat()}
                    DiagnosticJob.objects.filter(pk=job.pk, status="running").update(result=result)
                    from .diagnostic_context import diagnostic_context

                    context_references = diagnostic_context(job, report_only=report_only)
                    answer = analyze_diagnostic(
                        config, model_text, sources, [*references, *context_references], materials
                    )
                    result["context_references"] = context_references
                    result.update(answer, method="hybrid", notice="规则与模型分析", model_status="completed")
                except (TimeoutError, APITimeoutError):
                    result["model_status"] = "timeout"
                    result["model_error_code"] = "MODEL_TIMEOUT"
                except Exception as error:
                    result["model_status"] = "failed"
                    safe_codes = {
                        "INVALID_DIAGNOSTIC_OUTPUT",
                        "INVALID_DIAGNOSTIC_CITATION",
                        "SENSITIVE_DIAGNOSTIC_OUTPUT",
                        "AGENT_FAILED",
                        "AGENT_USAGE_LIMIT",
                        "AGENT_PROVIDER_AUTH",
                        "AGENT_PROVIDER_UNAVAILABLE",
                        "AGENT_INVALID_OUTPUT",
                    }
                    result["model_error_code"] = str(error) if str(error) in safe_codes else "MODEL_FAILED"
    except Exception:
        status, code = "failed", "DIAGNOSTIC_FAILED"
    result["duration_ms"] = round((time.monotonic() - started) * 1000)
    with transaction.atomic():
        # Match scheduling's defect -> job lock order before any assignment write.
        Defect.objects.select_for_update().get(pk=job.defect_id)
        current = DiagnosticJob.objects.select_for_update().get(pk=job_id)
        if current.status != "running":
            return
        # Re-check permissions before publishing late model output.
        from .permissions import writable_member

        current_report_only = report_only_diagnostic_access(current)
        current_administrator = not automatic and is_administrator(current.created_by_id)
        current_allowed = (
            capable(current.project_id, current.created_by_id, "report")
            if automatic
            else capable(current.project_id, current.created_by_id, "manage_defect")
            and (manager(current.project_id, current.created_by) or current.defect.assignee_id == current.created_by_id)
        )
        if (
            not current.created_by.is_active
            or not (current_report_only or current_administrator or current_allowed)
            or (
                not current_report_only
                and not current_administrator
                and not writable_member(current.project_id, current.created_by_id, current.project.workspace.slug)
            )
            or (automatic and not automatic_source_available(current.defect))
        ):
            current.status, current.result, current.error_code = "failed", {}, "ACCESS_REVOKED"
        else:
            current.status, current.result, current.error_code = status, result, code
        current.completed_at = timezone.now()
        current.save()
        if current.result.get("model_status") in {"timeout", "failed"}:
            from .diagnostic_retry import schedule_retry

            if schedule_retry(current):
                return
            if current.result.get("retry", {}).get("count", 0) >= 3:
                current.result = {**current.result, "fallback": "rules_after_retries"}
                current.save(update_fields=["result"])
        if current.status == "completed":
            from .module_routing import route_completed

            route_completed(current, materials)
            assigned = Defect.objects.select_related("module", "assignee").get(pk=current.defect_id)
            current.result = {
                **current.result,
                "assignment": {
                    "module": {"key": assigned.module_id, "name": assigned.module.name} if assigned.module_id else None,
                    "assignee": (assigned.assignee.display_name or assigned.assignee.username)
                    if assigned.assignee_id
                    else "",
                    "origin": assigned.assignment_origin,
                    "reason": assigned.assignment_reason,
                },
            }
            current.save(update_fields=["result"])
            if current.result.get("fallback") == "rules_after_retries":
                from .notifications import defect_notice, managers
                from plane.license.models import InstanceAdmin
                from .models import DefectEvent

                receivers = [
                    *managers(assigned.project),
                    *InstanceAdmin.objects.filter(role=20).values_list("user_id", flat=True),
                ]
                defect_notice(assigned, current.created_by, "诊断重试已结束，按规则处理", receivers)
                DefectEvent.objects.create(
                    project=assigned.project,
                    defect=assigned,
                    created_by=current.created_by,
                    previous_status=assigned.status,
                    status=assigned.status,
                    note="模型自动重试3次未完成，保留规则结果并按现有证据分派；可手动重新诊断。",
                )


@shared_task(name="plane.quality.tasks.sync_project_versions")
def sync_project_versions():
    """Only explicitly enabled versions run. Revoked managers pause before any assignment."""
    from .models import ProjectVersion
    from .project_versions import dispatch_ready

    for pk, project_id in (
        ProjectVersion.objects.filter(automation_enabled=True)
        .exclude(status__in=["released", "cancelled"])
        .values_list("pk", "project_id")
        .iterator(chunk_size=100)
    ):
        with transaction.atomic():
            from plane.db.models import Project

            Project.objects.select_for_update().get(pk=project_id)
            row = ProjectVersion.objects.select_for_update().filter(pk=pk, automation_enabled=True).first()
            if row:
                dispatch_ready(row)
                row.save(update_fields=["flow_state", "automation_enabled", "automation_note"])
