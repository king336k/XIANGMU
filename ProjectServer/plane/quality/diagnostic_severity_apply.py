"""Persist a verified grade without overriding a person or a newer diagnostic."""

from django.db import transaction

from .diagnostic_severity import propose
from .models import Defect, DefectEvent


@transaction.atomic
def apply_severity(job, result, materials=None):
    assessed = propose(job, result, materials)
    defect = Defect.objects.select_for_update().get(pk=job.defect_id)
    latest = defect.diagnostics.order_by("-created_at", "-id").first()
    if (
        not latest
        or latest.pk != job.pk
        or defect.status == "closed"
        or defect.archived_at
        or defect.severity_origin == "manual"
        or defect.severity_job_id == job.id
        or not assessed["severity"]
    ):
        return assessed
    old = defect.severity
    defect.severity = assessed["severity"]
    defect.severity_origin = "diagnostic"
    defect.severity_reason = assessed["basis"][:2000]
    defect.severity_job = job
    defect.edit_version += 1
    defect.save(
        update_fields=["severity", "severity_origin", "severity_reason", "severity_job", "edit_version", "updated_at"]
    )
    from .agent_lifecycle import advance_after_metadata
    advance_after_metadata(defect,defect.edit_version-1)
    names = {"": "待评估", "critical": "致命", "major": "严重", "minor": "一般", "trivial": "轻微"}
    DefectEvent.objects.create(
        defect=defect,
        project=defect.project,
        created_by=job.created_by,
        previous_status=defect.status,
        status=defect.status,
        note=f"诊断调整严重程度：{names.get(old, old)} → {names[defect.severity]}。{defect.severity_reason}",
    )
    from .notifications import defect_notice

    defect_notice(defect, job.created_by, "诊断已更新严重程度")
    return assessed
