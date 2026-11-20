"""Bounded command records shared by sessions, exchange and Agent tasks."""

from datetime import timedelta
from django.utils import timezone
from .remote_models import RemoteCommand


def command(station, payload, session=None, run=None, lifetime=35):
    expiry = timezone.now() + timedelta(seconds=lifetime)
    if run:
        expiry = min(expiry, run.expires_at)
    return RemoteCommand.objects.create(
        workstation=station,
        session=session,
        run=run,
        payload=payload,
        expires_at=expiry,
    )
