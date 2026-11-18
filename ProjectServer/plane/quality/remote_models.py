"""Transient remote-workstation sessions and bounded field operations."""

import uuid

from django.db import models


class RemoteWorkstation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agent = models.OneToOneField("quality.FieldAgent", on_delete=models.PROTECT, related_name="remote")
    credential_hash = models.CharField(max_length=64)
    credential_expires_at = models.DateTimeField()
    username = models.CharField(max_length=120, blank=True)
    hostname = models.CharField(max_length=200, blank=True)
    boot_id = models.CharField(max_length=120, blank=True)
    last_seen_at = models.DateTimeField(null=True)
    enabled = models.BooleanField(default=True)
    capabilities = models.JSONField(default=dict)


class RemoteTerminal(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workstation = models.ForeignKey(RemoteWorkstation, on_delete=models.CASCADE)
    owner = models.ForeignKey("db.User", on_delete=models.PROTECT)
    status = models.CharField(max_length=16, default="open")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    last_read_at = models.DateTimeField()
    error = models.CharField(max_length=200, blank=True)


class RemoteTerminalEvent(models.Model):
    session = models.ForeignKey(RemoteTerminal, on_delete=models.CASCADE, related_name="events")
    source_id = models.CharField(max_length=80)
    data = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["session", "source_id"], name="remote_event_source_unique")
        ]


class RemoteAgentRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workstation = models.ForeignKey(RemoteWorkstation, on_delete=models.PROTECT)
    defect = models.ForeignKey("quality.Defect", on_delete=models.PROTECT)
    owner = models.ForeignKey("db.User", on_delete=models.PROTECT)
    problem = models.TextField()
    mode = models.CharField(max_length=16, default="repair")
    status = models.CharField(max_length=20, default="queued")
    result = models.JSONField(default=dict)
    error = models.CharField(max_length=200, blank=True)
    tool_credential_hash = models.CharField(max_length=64, blank=True)
    identity_key = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    comment = models.OneToOneField("quality.DefectComment", null=True, on_delete=models.PROTECT)


class RemoteFeedbackBinding(models.Model):
    """Explicit administrator association for a legacy report without a device source."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workstation = models.ForeignKey(RemoteWorkstation, on_delete=models.CASCADE, related_name="feedback_bindings")
    defect = models.ForeignKey("quality.Defect", on_delete=models.PROTECT, related_name="remote_bindings")
    created_by = models.ForeignKey("db.User", null=True, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["workstation", "defect"], name="remote_feedback_binding_unique")]


class RemoteCommand(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workstation = models.ForeignKey(RemoteWorkstation, on_delete=models.CASCADE, related_name="commands")
    session = models.ForeignKey(RemoteTerminal, null=True, on_delete=models.CASCADE)
    run = models.ForeignKey(RemoteAgentRun, null=True, on_delete=models.CASCADE)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=16, default="pending")
    result = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()


class RemoteFileRequest(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    command = models.OneToOneField(RemoteCommand, on_delete=models.CASCADE, related_name="file_request")
    owner = models.ForeignKey("db.User", on_delete=models.PROTECT)
    identity_key = models.CharField(max_length=64)


class RemoteUploadedFile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workstation = models.ForeignKey(RemoteWorkstation, on_delete=models.CASCADE)
    owner = models.ForeignKey("db.User", on_delete=models.PROTECT)
    defect = models.ForeignKey("quality.Defect", null=True, on_delete=models.PROTECT)
    target = models.CharField(max_length=16)
    path = models.CharField(max_length=2000)
    filename = models.CharField(max_length=255)
    sha256 = models.CharField(max_length=64)
    size = models.PositiveBigIntegerField()
    ticket_hash = models.CharField(max_length=64, blank=True)
    identity_key = models.CharField(max_length=64)
    status = models.CharField(max_length=16, default="uploading")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
