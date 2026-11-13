"""Bounded retries share the diagnostics queue and preserve current rule results."""

from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from .diagnostic_limits import queue_wait_seconds

RETRYABLE = {"MODEL_TIMEOUT", "AGENT_FAILED", "AGENT_PROVIDER_UNAVAILABLE", "AGENT_INVALID_OUTPUT"}
MAX_RETRIES = 3


def schedule_retry(job):
    error = job.result.get("model_error_code", "")
    previous = job.result.get("retry", {})
    count = previous.get("count", 0) if isinstance(previous, dict) else 0
    if type(count) is not int or count < 0:
        count = 0
    if job.status not in {"completed", "failed"} or error not in RETRYABLE or count >= MAX_RETRIES:
        return False
    delay = 30 * 3**count
    job.result = {
        **job.result,
        "retry": {
            "count": count + 1,
            "limit": MAX_RETRIES,
            "next_at": (timezone.now() + timedelta(seconds=delay)).isoformat(),
            "last_error": error,
        },
    }
    job.status = "queued"
    job.completed_at = None
    job.started_at = None
    job.save(update_fields=["status", "completed_at", "started_at", "result"])

    def dispatch():
        from .tasks import run_diagnostic
        from .models import DiagnosticJob

        try:
            run_diagnostic.apply_async(
                args=[str(job.id)], queue="diagnostics", countdown=delay, expires=queue_wait_seconds()
            )
        except Exception:
            DiagnosticJob.objects.filter(pk=job.pk, status="queued").update(
                status="failed", error_code="QUEUE_UNAVAILABLE", completed_at=timezone.now()
            )

    transaction.on_commit(dispatch)
    return True
