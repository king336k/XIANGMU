# SPDX-License-Identifier: AGPL-3.0-only
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from .models import DiagnosticJob, Defect, PackageFile
from .views import QualityView, Conflict
from .data_regression import manager
from plane.knowledge import assistant
from copy import deepcopy
from django.db.models import Q
import hashlib
import json
from uuid import uuid5
from datetime import timedelta


def enqueue(job_id):
    from .tasks import run_diagnostic

    try:
        run_diagnostic.apply_async(args=[str(job_id)], queue="diagnostics", expires=900)
    except Exception:
        DiagnosticJob.objects.filter(pk=job_id, status="queued").update(
            status="failed", error_code="QUEUE_UNAVAILABLE", completed_at=timezone.now()
        )


def input_snapshot(defect):
    prior = defect.diagnostics.filter(mode="auto").order_by("-created_at").first()
    return {
        "context": (prior.result.get("input", {}).get("context", {}) if prior else {}),
        "title": defect.title,
        "description": defect.description,
        "files": list(PackageFile.objects.filter(package__defect=defect).order_by("id").values_list("id", flat=True)),
    }


def snapshot_json(defect):
    value = input_snapshot(defect)
    value["files"] = [str(pk) for pk in value["files"]]
    return value


def automatic_source_available(defect):
    from .models import DaqReport, PackageFile

    if DaqReport.objects.filter(defect=defect, binding__active=True).exists():
        return True
    from .daq_incidents import trusted_incident, verify_incident_authority

    link = trusted_incident(defect)
    if link is None:
        # Platform-created defects use their own authorized attachments. Do not
        # interpret an unsigned external source as a native defect.
        if defect.sources.exists() or defect.status == "closed":
            return False
        return any(
            row.name.lower().endswith((".log", ".txt", ".json", ".csv", ".md", ".yaml", ".yml", ".zip"))
            for row in PackageFile.objects.filter(package__defect=defect, package__status="files_verified")
        )
    try:
        verify_incident_authority(link)
    except Exception:
        return False
    return True


@transaction.atomic
def schedule_automatic(defect, actor, trigger, context=None):
    # The caller has already passed DAQ or attachment permissions; the worker checks again.
    from .models import DaqReport, ProblemPackage

    if not DaqReport.objects.filter(defect=defect).exists() and not automatic_source_available(defect):
        return None
    defect = Defect.objects.select_for_update().get(pk=defect.pk)
    if (
        trigger == "materials_verified"
        and ProblemPackage.objects.filter(defect=defect).exclude(status="files_verified").exists()
    ):
        return None
    snapshot = snapshot_json(defect)
    if isinstance(context, dict):
        snapshot["context"] = {
            key: value
            for key, value in context.items()
            if key
            in {
                "declaredSteps",
                "actualSteps",
                "schemaVersion",
                "pkgSizeBytes",
                "packageType",
                "dataPackageStatus",
                "rosMode",
            }
            and isinstance(value, (str, int, float, bool, type(None)))
        }
    digest = hashlib.sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    request_id = uuid5(defect.id, digest)
    prior = DiagnosticJob.objects.filter(defect=defect, request_id=request_id).first()
    if prior:
        return prior
    job = DiagnosticJob.objects.create(
        project=defect.project,
        defect=defect,
        created_by=actor,
        request_id=request_id,
        mode="auto",
        result={"trigger": trigger, "input": snapshot, "version": defect.diagnostics.count() + 1},
    )
    transaction.on_commit(lambda: enqueue(job.id))
    return job


def expire_stale(defect):
    stale = defect.diagnostics.filter(
        Q(status="running", started_at__lt=timezone.now() - timedelta(seconds=190))
        | Q(status="queued", created_at__lt=timezone.now() - timedelta(minutes=15))
    )
    for job in stale:
        result = {**job.result, "model_status": "timeout" if job.status == "running" else "not_requested"}
        error_code = "DIAGNOSTIC_TIMEOUT" if job.status == "running" else "QUEUE_WAIT_TIMEOUT"
        DiagnosticJob.objects.filter(pk=job.id, status__in=["queued", "running"]).update(
            status="failed", result=result, error_code=error_code, completed_at=timezone.now()
        )


class DiagnosticInput(serializers.Serializer):
    request_id = serializers.UUIDField()
    mode = serializers.ChoiceField(choices=["rules", "llm", "auto"], default="rules")


class DiagnosticSerializer(serializers.ModelSerializer):
    def to_representation(self, instance):
        data = deepcopy(super().to_representation(instance))
        if instance.result.get("method") in {"llm", "hybrid"} and instance.status == "completed":
            from plane.knowledge.serializers import visible_references

            allowed = visible_references(instance.project_id)
            if any(
                row.get("reference", "").startswith("KN-") and row.get("reference") not in allowed
                for row in instance.result.get("citations", [])
            ):
                data.update(
                    result={
                        **instance.result,
                        "method": "rules",
                        "model_status": "reference_unavailable",
                        "answer": "",
                        "citations": [],
                        "model_confidence": None,
                        "evidence_assessment": None,
                        "confidence_basis": "",
                        "confidence_references": [],
                        "suggested_actions": [],
                        "verification_steps": [],
                    }
                )
        data["result"].pop("input", None)
        return data

    class Meta:
        model = DiagnosticJob
        fields = [
            "id",
            "defect_id",
            "mode",
            "status",
            "result",
            "error_code",
            "started_at",
            "completed_at",
            "created_at",
            "feedback",
            "feedback_note",
        ]


def writable(view, defect):
    if not manager(view.project_id, view.request.user) and defect.assignee_id != view.request.user.id:
        raise PermissionDenied("由当前技术负责人或项目经理发起诊断。")


class DiagnosticList(QualityView):
    def get(self, request, pk, **kwargs):
        defect = self.obj(Defect, pk)
        expire_stale(defect)
        jobs = defect.diagnostics.order_by("-created_at", "-id")
        latest = jobs.first()
        current = latest
        if (
            latest
            and latest.mode != "rules"
            and latest.result.get("input")
            and latest.result.get("model_status") != "completed"
        ):
            current = (
                jobs.filter(
                    status="completed", result__model_status="completed", result__input=latest.result["input"]
                ).first()
                or latest
            )
        response = self.listing(jobs, DiagnosticSerializer)
        serialized = DiagnosticSerializer(current).data if current else None
        if current and current != latest and serialized["result"].get("model_status") != "completed":
            serialized = DiagnosticSerializer(latest).data
        response.data["current_report"] = serialized
        response.data["latest_attempt"] = DiagnosticSerializer(latest).data if latest else None
        return response

    @transaction.atomic
    def post(self, request, pk, **kwargs):
        data = self.input(DiagnosticInput)
        defect = get_object_or_404(Defect.objects.select_for_update(), pk=pk, project_id=self.project_id)
        writable(self, defect)
        expire_stale(defect)
        existing = DiagnosticJob.objects.filter(
            project_id=self.project_id, created_by=request.user, request_id=data["request_id"]
        ).first()
        if existing:
            if existing.defect_id != defect.id or existing.mode != data["mode"]:
                raise Conflict()
            return Response(DiagnosticSerializer(existing).data)
        if DiagnosticJob.objects.filter(defect=defect, status__in=["queued", "running"]).exists():
            raise Conflict("当前缺陷已有诊断在运行，请等待完成或取消后重试。")
        status = "unconfigured" if data["mode"] == "llm" and not assistant.provider_config()["configured"] else "queued"
        job = DiagnosticJob.objects.create(
            project=defect.project,
            created_by=request.user,
            defect=defect,
            status=status,
            result={}
            if status == "unconfigured"
            else {"trigger": "manual", "input": snapshot_json(defect), "version": defect.diagnostics.count() + 1},
            **data,
        )
        if status == "queued":
            transaction.on_commit(lambda: enqueue(job.id))
        return Response(DiagnosticSerializer(job).data, status=201)


class DiagnosticAction(serializers.Serializer):
    action = serializers.ChoiceField(choices=["cancel", "feedback"])
    feedback = serializers.ChoiceField(choices=["helpful", "unhelpful"], required=False)
    note = serializers.CharField(max_length=2000, allow_blank=True, default="")


class DiagnosticDetail(QualityView):
    def get(self, request, pk, **kwargs):
        return Response(DiagnosticSerializer(self.obj(DiagnosticJob, pk)).data)

    @transaction.atomic
    def post(self, request, pk, **kwargs):
        data = self.input(DiagnosticAction)
        job = get_object_or_404(
            DiagnosticJob.objects.select_for_update().select_related("defect"), pk=pk, project_id=self.project_id
        )
        writable(self, job.defect)
        if data["action"] == "cancel":
            if job.status in ["completed", "failed", "unconfigured"]:
                raise Conflict("任务已经结束，请发起新的诊断。")
            job.status = "cancelled"
            job.completed_at = timezone.now()
        else:
            if job.status != "completed" or not data.get("feedback"):
                raise Conflict("仅已完成的报告可以反馈。")
            job.feedback = data["feedback"]
            job.feedback_note = data["note"]
        job.save()
        return Response(DiagnosticSerializer(job).data)
