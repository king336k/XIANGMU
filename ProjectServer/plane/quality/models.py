# SPDX-License-Identifier: AGPL-3.0-only
"""Native project quality records. Revisions and executions are append-only via the API."""

import uuid

from django.db import models


class QualityRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey("db.Project", on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey("db.User", on_delete=models.SET_NULL, null=True, related_name="+")

    def save(self, *args, **kwargs):
        from django.db import transaction, router, connections
        from plane.db.models import Project
        from .numbering import PREFIXES, allocate
        from plane.utils.uuid import convert_uuid_to_integer

        if self._state.adding and self._meta.label_lower in PREFIXES:
            using = kwargs.get("using") or router.db_for_write(type(self), instance=self)
            with transaction.atomic(using=using):
                with connections[using].cursor() as cursor:
                    cursor.execute(
                        "SELECT pg_advisory_xact_lock(%s)",
                        [convert_uuid_to_integer(f"{self.project_id}:{self._meta.label_lower}")],
                    )
                project = Project.objects.using(using).get(pk=self.project_id)
                result = super().save(*args, **kwargs)
                allocate(self, project, using)
                return result
        return super().save(*args, **kwargs)

    @property
    def code(self):
        from .numbering import metadata

        return metadata(self).get("code", "")

    class Meta:
        abstract = True
        ordering = ["-created_at", "-id"]


class BusinessNumber(models.Model):
    project = models.ForeignKey("db.Project", on_delete=models.PROTECT)
    workspace = models.ForeignKey("db.Workspace", on_delete=models.PROTECT)
    resource = models.CharField(max_length=64)
    object_id = models.UUIDField()
    number = models.PositiveBigIntegerField()
    code = models.CharField(max_length=96, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["resource", "object_id"], name="quality_number_object_unique"),
            models.UniqueConstraint(fields=["project", "resource", "number"], name="quality_number_sequence_unique"),
            models.UniqueConstraint(fields=["workspace", "code"], name="quality_number_code_unique"),
        ]


class TestCase(QualityRecord):
    trashed_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    title = models.CharField(max_length=255)
    module = models.CharField(max_length=120, blank=True)
    priority = models.CharField(max_length=16, default="medium")
    preconditions = models.TextField(blank=True)
    steps = models.JSONField(default=list)
    requirement = models.ForeignKey(
        "db.Issue", on_delete=models.PROTECT, null=True, blank=True, related_name="quality_cases"
    )
    version = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)


class CaseRevision(QualityRecord):
    case = models.ForeignKey(TestCase, on_delete=models.PROTECT, related_name="revisions")
    version = models.PositiveIntegerField()
    title = models.CharField(max_length=255)
    snapshot = models.JSONField()

    class Meta(QualityRecord.Meta):
        constraints = [models.UniqueConstraint(fields=["case", "version"], name="quality_case_version_unique")]


class TestPlan(QualityRecord):
    archived_at = models.DateTimeField(null=True, blank=True)
    name = models.CharField(max_length=255)
    build = models.CharField(max_length=120)
    environment = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    assignee = models.ForeignKey("db.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    managed = models.BooleanField(default=False)
    status = models.CharField(max_length=16, default="pending")
    round_no = models.PositiveIntegerField(default=1)
    workflow_version = models.PositiveIntegerField(default=1)
    reviewed_by = models.ForeignKey("db.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)


class PlanEvent(QualityRecord):
    plan = models.ForeignKey(TestPlan, on_delete=models.PROTECT, related_name="workflow_events")
    action = models.CharField(max_length=20)
    previous_status = models.CharField(max_length=16)
    status = models.CharField(max_length=16)
    round_no = models.PositiveIntegerField()
    note = models.TextField(blank=True)
    execution_ids = models.JSONField(default=list)


class PlanItem(QualityRecord):
    plan = models.ForeignKey(TestPlan, on_delete=models.PROTECT, related_name="items")
    case = models.ForeignKey(TestCase, on_delete=models.PROTECT)
    revision = models.ForeignKey(CaseRevision, on_delete=models.PROTECT)

    class Meta(QualityRecord.Meta):
        constraints = [models.UniqueConstraint(fields=["plan", "case"], name="quality_plan_case_unique")]


class TestExecution(QualityRecord):
    reason_category = models.CharField(max_length=24, blank=True)
    next_action = models.TextField(blank=True)
    resource_snapshot = models.JSONField(default=dict)
    item = models.ForeignKey(PlanItem, on_delete=models.PROTECT, related_name="executions")
    request_id = models.UUIDField()
    result = models.CharField(max_length=16)
    actual_result = models.TextField(blank=True)
    evidence = models.TextField(blank=True)
    step_results = models.JSONField(default=list)
    round_no = models.PositiveIntegerField(default=1)

    class Meta(QualityRecord.Meta):
        constraints = [models.UniqueConstraint(fields=["item", "request_id"], name="quality_execution_request_unique")]


class Defect(QualityRecord):
    responsible_department = models.CharField(max_length=128, blank=True)
    component = models.CharField(max_length=128, blank=True)
    resolution_kind = models.CharField(max_length=24, default="fixed")
    duplicate_of = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="duplicates")
    defer_until = models.DateField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    edit_version = models.PositiveIntegerField(default=1)
    pending_assignee = models.ForeignKey("db.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    transfer_reason = models.CharField(max_length=4000, blank=True)
    case = models.ForeignKey(TestCase, on_delete=models.PROTECT, null=True, blank=True, related_name="defects")
    source_execution = models.OneToOneField(
        TestExecution, on_delete=models.PROTECT, null=True, blank=True, related_name="defect"
    )
    title = models.CharField(max_length=255)
    severity = models.CharField(max_length=16, default="major")
    description = models.TextField(blank=True)
    affected_build = models.CharField(max_length=120, blank=True)
    fixed_build = models.CharField(max_length=120, blank=True)
    verification_scope = models.CharField(max_length=16, default="auto")
    status = models.CharField(max_length=16, default="open")
    resolution = models.TextField(blank=True)
    assignee = models.ForeignKey("db.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    repair_issue = models.ForeignKey(
        "db.Issue", on_delete=models.PROTECT, null=True, blank=True, related_name="quality_defects"
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    regression_execution = models.ForeignKey(
        TestExecution, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)


class DefectEvent(QualityRecord):
    defect = models.ForeignKey(Defect, on_delete=models.PROTECT, related_name="events")
    previous_status = models.CharField(max_length=16, blank=True)
    status = models.CharField(max_length=16)
    note = models.TextField(blank=True)


class DefectVerification(QualityRecord):
    """Frozen validation scope: one defect, build, repair timestamp and round."""

    defect = models.ForeignKey(Defect, on_delete=models.PROTECT, related_name="verification_rounds")
    round_no = models.PositiveIntegerField()
    version = models.PositiveIntegerField(default=1)
    request_id = models.UUIDField()
    request_hash = models.CharField(max_length=64)
    mode = models.CharField(max_length=16)
    status = models.CharField(max_length=24, default="testing")
    fixed_build = models.CharField(max_length=120)
    environment = models.CharField(max_length=255)
    steps = models.JSONField(default=list)
    resolved_at = models.DateTimeField(null=True, blank=True)
    plan = models.OneToOneField(
        TestPlan, on_delete=models.PROTECT, null=True, blank=True, related_name="defect_verification"
    )

    class Meta(QualityRecord.Meta):
        constraints = [
            models.UniqueConstraint(fields=["defect", "round_no"], name="quality_defect_verification_round_unique"),
            models.UniqueConstraint(fields=["defect", "request_id"], name="quality_defect_verification_request_unique"),
        ]


class DefectVerificationResult(QualityRecord):
    verification = models.ForeignKey(DefectVerification, on_delete=models.PROTECT, related_name="manual_results")
    request_id = models.UUIDField()
    request_hash = models.CharField(max_length=64)
    result = models.CharField(max_length=16)
    actual_result = models.TextField()
    evidence = models.TextField()
    step_results = models.JSONField(default=list)
    reason_category = models.CharField(max_length=24, blank=True)
    next_action = models.TextField(blank=True)

    class Meta(QualityRecord.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["verification", "request_id"], name="quality_verification_result_request_unique"
            )
        ]


class DefectVerificationEvent(QualityRecord):
    verification = models.ForeignKey(DefectVerification, on_delete=models.PROTECT, related_name="workflow_events")
    request_id = models.UUIDField()
    request_hash = models.CharField(max_length=64)
    action = models.CharField(max_length=24)
    note = models.TextField(blank=True)
    snapshot = models.JSONField(default=dict)

    class Meta(QualityRecord.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["verification", "request_id"], name="quality_verification_event_request_unique"
            )
        ]


class Solution(QualityRecord):
    contributor_ids = models.JSONField(default=list, null=True)
    defect = models.ForeignKey(Defect, on_delete=models.PROTECT, related_name="solutions")
    title = models.CharField(max_length=255)
    root_cause = models.TextField()
    steps = models.TextField()
    verification = models.TextField()
    risk = models.TextField(blank=True)
    rollback = models.TextField(blank=True)
    repository = models.CharField(max_length=500, blank=True)
    commit_sha = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=16, default="draft")
    edit_version = models.PositiveIntegerField(default=1)
    submitted_version = models.PositiveIntegerField(default=0)


class SolutionRevision(QualityRecord):
    solution = models.ForeignKey(Solution, on_delete=models.PROTECT, related_name="revisions")
    version = models.PositiveIntegerField()
    snapshot = models.JSONField()
    reviewer_ids = models.JSONField()
    required_count = models.PositiveIntegerField()

    class Meta(QualityRecord.Meta):
        constraints = [models.UniqueConstraint(fields=["solution", "version"], name="quality_solution_version_unique")]


class SolutionReview(QualityRecord):
    revision = models.ForeignKey(SolutionRevision, on_delete=models.PROTECT, related_name="reviews")
    decision = models.CharField(max_length=16)
    comment = models.TextField(blank=True)

    class Meta(QualityRecord.Meta):
        constraints = [
            models.UniqueConstraint(fields=["revision", "created_by"], name="quality_solution_reviewer_unique")
        ]


class TestSuite(QualityRecord):
    trashed_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    edit_version = models.PositiveIntegerField(default=1)
    source_suite = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="copies")
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    published = models.BooleanField(default=False)


class SuiteItem(QualityRecord):
    suite = models.ForeignKey(TestSuite, on_delete=models.PROTECT, related_name="items")
    case = models.ForeignKey(TestCase, on_delete=models.PROTECT)
    revision = models.ForeignKey(CaseRevision, on_delete=models.PROTECT)

    class Meta(QualityRecord.Meta):
        constraints = [models.UniqueConstraint(fields=["suite", "case"], name="quality_suite_case_unique")]


class Release(QualityRecord):
    name = models.CharField(max_length=255)
    version = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=16, default="draft")
    edit_version = models.PositiveIntegerField(default=1)
    admitted_by = models.ForeignKey("db.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    admitted_at = models.DateTimeField(null=True, blank=True)
    admission_snapshot = models.JSONField(default=dict)

    class Meta(QualityRecord.Meta):
        constraints = [models.UniqueConstraint(fields=["project", "version"], name="quality_release_version_unique")]


class ReleasePlan(QualityRecord):
    release = models.ForeignKey(Release, on_delete=models.PROTECT, related_name="plans")
    plan = models.ForeignKey(TestPlan, on_delete=models.PROTECT, related_name="releases")

    class Meta(QualityRecord.Meta):
        constraints = [models.UniqueConstraint(fields=["release", "plan"], name="quality_release_plan_unique")]


class SourceLink(QualityRecord):
    defect = models.ForeignKey(Defect, on_delete=models.PROTECT, related_name="sources")
    source_system = models.CharField(max_length=64)
    source_instance = models.CharField(max_length=120)
    record_type = models.CharField(max_length=64)
    record_id = models.CharField(max_length=255)
    task_id = models.CharField(max_length=255, blank=True)
    package_id = models.CharField(max_length=255, blank=True)
    device = models.CharField(max_length=255, blank=True)

    class Meta(QualityRecord.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["project", "source_system", "source_instance", "record_type", "record_id"],
                name="quality_source_record_unique",
            )
        ]


class DefectComment(QualityRecord):
    defect = models.ForeignKey(Defect, on_delete=models.PROTECT, related_name="comments")
    content = models.TextField()
    visibility = models.CharField(max_length=16, default="public")
    content_html = models.TextField(blank=True)
    request_id = models.UUIDField(null=True, blank=True)
    request_hash = models.CharField(max_length=64, blank=True)
    reply_to = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="replies")

    class Meta(QualityRecord.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["defect", "created_by", "request_id"], name="quality_comment_request_unique"
            )
        ]


class CommentAttachment(QualityRecord):
    """Private discussion files never enter DAQ evidence or diagnostic packages."""

    defect = models.ForeignKey(Defect, on_delete=models.PROTECT, related_name="comment_files")
    comment = models.ForeignKey(
        DefectComment, on_delete=models.PROTECT, null=True, blank=True, related_name="attachments"
    )
    name = models.CharField(max_length=255)
    size = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64)
    storage_key = models.CharField(max_length=64)
    content_type = models.CharField(max_length=100)


class CollaborationSettings(QualityRecord):
    # Opt-in labels route work, never grant membership or replace its single owner.
    project = models.OneToOneField("db.Project", on_delete=models.PROTECT)
    enabled = models.BooleanField(default=False)
    departments = models.JSONField(default=list)
    components = models.JSONField(default=list)
    version = models.PositiveIntegerField(default=1)


class DefectReminder(QualityRecord):
    defect = models.ForeignKey(Defect, on_delete=models.PROTECT, related_name="reminders")
    receiver = models.ForeignKey("db.User", on_delete=models.PROTECT)
    sent_at = models.DateTimeField()

    class Meta(QualityRecord.Meta):
        constraints = [
            models.UniqueConstraint(fields=["defect", "receiver"], name="quality_defect_reminder_recipient_unique")
        ]


class ProblemPackage(QualityRecord):
    defect = models.ForeignKey(Defect, on_delete=models.PROTECT, related_name="packages")
    name = models.CharField(max_length=255)
    source_system = models.CharField(max_length=64)
    external_id = models.CharField(max_length=255)
    files = models.JSONField(default=list)
    manifest_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=24, default="manifest_registered")

    class Meta(QualityRecord.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["project", "source_system", "external_id"], name="quality_package_external_unique"
            )
        ]


class SavedReport(QualityRecord):
    name = models.CharField(max_length=255)
    plan = models.ForeignKey(TestPlan, on_delete=models.PROTECT, null=True, blank=True, related_name="reports")
    request_id = models.UUIDField()
    request_hash = models.CharField(max_length=64)
    edit_version = models.PositiveIntegerField(default=1)
    snapshot = models.JSONField(default=dict)

    class Meta(QualityRecord.Meta):
        constraints = [models.UniqueConstraint(fields=["project", "request_id"], name="quality_report_request_unique")]


class CaseImport(QualityRecord):
    name = models.CharField(max_length=255)
    status = models.CharField(max_length=16, default="preview")
    rows = models.JSONField(default=list)
    errors = models.JSONField(default=list)
    case_ids = models.JSONField(default=list)
    confirmed_at = models.DateTimeField(null=True, blank=True)


class ProjectRolePolicy(models.Model):
    project = models.OneToOneField("db.Project", on_delete=models.PROTECT, primary_key=True)
    enabled = models.BooleanField(default=False)


class BusinessRole(QualityRecord):
    user = models.ForeignKey("db.User", on_delete=models.PROTECT, related_name="quality_business_roles")
    role = models.CharField(max_length=32)
    additional_roles = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(QualityRecord.Meta):
        constraints = [models.UniqueConstraint(fields=["project", "user"], name="quality_business_member_unique")]


class BusinessRoleEvent(QualityRecord):
    user = models.ForeignKey("db.User", on_delete=models.PROTECT, null=True, related_name="+")
    previous_role = models.CharField(max_length=32, blank=True)
    role = models.CharField(max_length=32, blank=True)
    action = models.CharField(max_length=24)


class DaqBinding(QualityRecord):
    external_project_id = models.PositiveBigIntegerField(null=True, blank=True)
    source_instance = models.CharField(max_length=120)
    platform_task_id = models.PositiveBigIntegerField()
    source_record_id = models.CharField(max_length=255)
    issue = models.ForeignKey("db.Issue", on_delete=models.PROTECT)
    device = models.CharField(max_length=255, blank=True)
    package_id = models.CharField(max_length=255, blank=True)
    active = models.BooleanField(default=True)

    class Meta(QualityRecord.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["project", "platform_task_id", "source_record_id"], name="quality_daq_source_binding_unique"
            )
        ]


class DaqReport(QualityRecord):
    binding = models.ForeignKey(DaqBinding, on_delete=models.PROTECT, related_name="reports")
    defect = models.OneToOneField(Defect, on_delete=models.PROTECT, related_name="daq_report")
    request_id = models.UUIDField()
    request_hash = models.CharField(max_length=64)
    category = models.CharField(max_length=32)

    class Meta(QualityRecord.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["project", "created_by", "request_id"], name="quality_daq_report_request_unique"
            )
        ]


class PlatformIdentity(QualityRecord):
    source_instance = models.CharField(max_length=120)
    external_user_id = models.PositiveBigIntegerField()
    user = models.ForeignKey("db.User", on_delete=models.PROTECT)
    active = models.BooleanField(default=True)

    class Meta(QualityRecord.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["project", "source_instance", "external_user_id"], name="quality_platform_identity_unique"
            )
        ]


class PackageFile(QualityRecord):
    package = models.ForeignKey(ProblemPackage, on_delete=models.PROTECT, related_name="uploaded_files")
    name = models.CharField(max_length=500)
    size = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64)
    storage_key = models.CharField(max_length=500)

    class Meta(QualityRecord.Meta):
        constraints = [models.UniqueConstraint(fields=["package", "name"], name="quality_package_file_unique")]


class PlatformProject(QualityRecord):
    source_instance = models.CharField(max_length=120)
    external_project_id = models.PositiveBigIntegerField()
    name = models.CharField(max_length=255, blank=True)
    active = models.BooleanField(default=True)

    class Meta(QualityRecord.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["project", "source_instance", "external_project_id"], name="quality_platform_project_unique"
            )
        ]


class Requirement(QualityRecord):
    issue = models.OneToOneField("db.Issue", on_delete=models.PROTECT, related_name="requirement_detail")
    number = models.PositiveIntegerField(editable=False)
    acceptance = models.TextField(blank=True)
    target_build = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=16, default="draft")
    version = models.PositiveIntegerField(default=1)

    class Meta(QualityRecord.Meta):
        constraints = [models.UniqueConstraint(fields=["project", "number"], name="quality_requirement_number_unique")]

    def save(self, *args, **kwargs):
        from django.db import transaction
        from django.db.models import Max
        from plane.db.models import Project

        if self._state.adding and self.number is None:
            with transaction.atomic():
                Project.objects.select_for_update().get(pk=self.project_id)
                self.number = (
                    type(self).objects.filter(project_id=self.project_id).aggregate(last=Max("number"))["last"] or 0
                ) + 1
                return super().save(*args, **kwargs)
        return super().save(*args, **kwargs)


class RequirementRevision(QualityRecord):
    requirement = models.ForeignKey(Requirement, on_delete=models.PROTECT, related_name="revisions")
    version = models.PositiveIntegerField()
    snapshot = models.JSONField(default=dict)

    class Meta(QualityRecord.Meta):
        constraints = [
            models.UniqueConstraint(fields=["requirement", "version"], name="quality_requirement_revision_unique")
        ]


class DataRegression(QualityRecord):
    request_snapshot = models.JSONField(default=dict)
    plan = models.OneToOneField(TestPlan, on_delete=models.PROTECT, related_name="data_regression")
    defect = models.ForeignKey(Defect, on_delete=models.PROTECT, related_name="data_regressions")
    solution_revision = models.ForeignKey(SolutionRevision, on_delete=models.PROTECT)
    binding = models.ForeignKey(DaqBinding, on_delete=models.PROTECT)
    fixed_build = models.CharField(max_length=120)
    resolved_at = models.DateTimeField()
    round_started_at = models.DateTimeField()


class DataEvidence(QualityRecord):
    regression = models.ForeignKey(DataRegression, on_delete=models.PROTECT, related_name="evidence")
    round_no = models.PositiveIntegerField()
    source_session_id = models.CharField(max_length=255)
    package_id = models.CharField(max_length=255)
    collected_at = models.DateTimeField()
    snapshot = models.JSONField()

    class Meta(QualityRecord.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["regression", "source_session_id"], name="quality_regression_session_unique"
            ),
            models.UniqueConstraint(fields=["regression", "package_id"], name="quality_regression_package_unique"),
        ]


class DefectCollaborator(QualityRecord):
    defect = models.ForeignKey(Defect, on_delete=models.PROTECT, related_name="collaborators")
    user = models.ForeignKey("db.User", on_delete=models.PROTECT)

    class Meta(QualityRecord.Meta):
        constraints = [models.UniqueConstraint(fields=["defect", "user"], name="quality_defect_collaborator_unique")]


class TaskPackageImport(QualityRecord):
    package_uuid = models.UUIDField()
    sha256 = models.CharField(max_length=64)
    payload = models.JSONField()
    rows = models.JSONField(default=list)
    status = models.CharField(max_length=16, default="validated")
    plan = models.ForeignKey(TestPlan, on_delete=models.PROTECT, null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta(QualityRecord.Meta):
        constraints = [
            models.UniqueConstraint(fields=["project", "package_uuid"], name="quality_task_package_uuid_unique"),
            models.UniqueConstraint(fields=["project", "sha256"], name="quality_task_package_sha_unique"),
        ]


class DiagnosticJob(QualityRecord):
    defect = models.ForeignKey(Defect, on_delete=models.PROTECT, related_name="diagnostics")
    request_id = models.UUIDField()
    mode = models.CharField(max_length=16)
    status = models.CharField(max_length=16, default="queued")
    result = models.JSONField(default=dict)
    error_code = models.CharField(max_length=64, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    feedback = models.CharField(max_length=20, blank=True)
    feedback_note = models.CharField(max_length=2000, blank=True)

    class Meta(QualityRecord.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["project", "created_by", "request_id"], name="quality_diagnostic_request_unique"
            )
        ]


class FieldAgent(QualityRecord):
    credential_hash = models.CharField(max_length=64, blank=True)
    credential_expires_at = models.DateTimeField(null=True, blank=True)
    name = models.CharField(max_length=200)
    owner = models.ForeignKey("db.User", on_delete=models.PROTECT)
    source_instance = models.CharField(max_length=120, blank=True)
    enabled = models.BooleanField(default=True)
    edit_version = models.PositiveIntegerField(default=1)
    last_seen_at = models.DateTimeField(null=True, blank=True)


class TelemetrySnapshot(QualityRecord):
    agent = models.ForeignKey(FieldAgent, on_delete=models.PROTECT, related_name="snapshots")
    request_id = models.UUIDField()
    sha256 = models.CharField(max_length=64)
    snapshot = models.JSONField(default=dict)
    review_status = models.CharField(max_length=16, default="pending")
    reviewed_by = models.ForeignKey("db.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=4000, blank=True)

    class Meta(QualityRecord.Meta):
        constraints = [models.UniqueConstraint(fields=["agent", "request_id"], name="quality_telemetry_request_unique")]


class SavedQualityView(QualityRecord):
    resource = models.CharField(max_length=32)
    name = models.CharField(max_length=120)
    filters = models.JSONField(default=dict)
    active = models.BooleanField(default=True)

    class Meta(QualityRecord.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["project", "created_by", "resource", "name"], name="quality_saved_view_name_unique"
            )
        ]


class QualityLifecycleEvent(QualityRecord):
    resource = models.CharField(max_length=32)
    object_id = models.UUIDField()
    action = models.CharField(max_length=24)
    reason = models.CharField(max_length=4000)
    before_version = models.PositiveIntegerField()
    after_version = models.PositiveIntegerField()


class DocumentImport(QualityRecord):
    resource = models.CharField(max_length=24)
    name = models.CharField(max_length=255)
    source_url = models.URLField(max_length=1000, blank=True)
    rows = models.JSONField(default=list)
    errors = models.JSONField(default=list)
    status = models.CharField(max_length=16, default="preview")
    object_ids = models.JSONField(default=list)
    sha256 = models.CharField(max_length=64)
    extraction = models.JSONField(default=dict)

    class Meta(QualityRecord.Meta):
        constraints = [
            models.UniqueConstraint(fields=["project", "resource", "sha256"], name="quality_document_import_unique")
        ]


class DocumentFile(QualityRecord):
    document_import = models.ForeignKey(DocumentImport, on_delete=models.CASCADE, related_name="files")
    name = models.CharField(max_length=255)
    kind = models.CharField(max_length=16)
    size = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    storage_key = models.CharField(max_length=64)


class PlatformCatalog(QualityRecord):
    source_instance = models.CharField(max_length=120)
    external_project_id = models.PositiveBigIntegerField(default=0)
    source_project = models.JSONField(default=dict)
    members = models.JSONField(default=list)
    task_watermark = models.CharField(max_length=80, blank=True)
    synced_at = models.DateTimeField(null=True, blank=True)

    class Meta(QualityRecord.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["project", "source_instance", "external_project_id"], name="quality_catalog_unique"
            )
        ]


class PlatformCatalogTask(QualityRecord):
    catalog = models.ForeignKey(PlatformCatalog, on_delete=models.PROTECT, related_name="tasks")
    external_id = models.PositiveBigIntegerField()
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    source_status = models.CharField(max_length=80, blank=True)
    source_updated_at = models.CharField(max_length=80, blank=True)
    active = models.BooleanField(default=True)
    issue = models.ForeignKey("db.Issue", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta(QualityRecord.Meta):
        constraints = [models.UniqueConstraint(fields=["catalog", "external_id"], name="quality_catalog_task_unique")]


class ReportConclusion(QualityRecord):
    report = models.OneToOneField(SavedReport, on_delete=models.PROTECT, related_name="conclusion")
    report_version = models.PositiveIntegerField()
    result = models.CharField(max_length=24)
    summary = models.TextField()
    risks = models.TextField(blank=True)


class TestResource(QualityRecord):
    name = models.CharField(max_length=255)
    kind = models.CharField(max_length=32)
    status = models.CharField(max_length=24, default="available")
    build = models.CharField(max_length=120, blank=True)
    description = models.TextField(blank=True)
    edit_version = models.PositiveIntegerField(default=1)
    agent = models.ForeignKey(
        FieldAgent, on_delete=models.PROTECT, null=True, blank=True, related_name="test_resources"
    )
    source_instance = models.CharField(max_length=120, blank=True)
    external_id = models.CharField(max_length=255, blank=True)


class PlanResource(QualityRecord):
    plan = models.ForeignKey(TestPlan, on_delete=models.PROTECT, related_name="resource_links")
    resource = models.ForeignKey(TestResource, on_delete=models.PROTECT)

    class Meta(QualityRecord.Meta):
        constraints = [models.UniqueConstraint(fields=["plan", "resource"], name="quality_plan_resource_unique")]


class NotificationTarget(QualityRecord):
    name = models.CharField(max_length=120)
    source_instance = models.CharField(max_length=80)
    chat_id = models.CharField(max_length=150)
    enabled = models.BooleanField(default=True)
    edit_version = models.PositiveIntegerField(default=1)


class ReportDelivery(QualityRecord):
    report = models.ForeignKey(SavedReport, on_delete=models.PROTECT, related_name="deliveries")
    target = models.ForeignKey(NotificationTarget, on_delete=models.PROTECT)
    request_id = models.UUIDField()
    report_fingerprint = models.CharField(max_length=64)
    target_version = models.PositiveIntegerField()
    target_snapshot = models.JSONField(default=dict)
    text = models.TextField()
    status = models.CharField(max_length=24, default="preview")
    attempts = models.PositiveIntegerField(default=0)
    external_message_id = models.CharField(max_length=255, blank=True)
    last_error = models.CharField(max_length=80, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta(QualityRecord.Meta):
        constraints = [
            models.UniqueConstraint(fields=["project", "request_id"], name="quality_report_delivery_request_unique")
        ]


class ProjectVersion(QualityRecord):
    name = models.CharField(max_length=255)
    version = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, default="planning")
    start_date = models.DateField(null=True, blank=True)
    target_date = models.DateField(null=True, blank=True)
    owner = models.ForeignKey("db.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    cycle = models.ForeignKey("db.Cycle", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    quality_release = models.ForeignKey(
        Release, on_delete=models.PROTECT, null=True, blank=True, related_name="business_versions"
    )
    edit_version = models.PositiveIntegerField(default=1)
    flow_nodes = models.JSONField(default=list)
    flow_state = models.JSONField(default=dict)
    automation_enabled = models.BooleanField(default=False)
    automation_by = models.ForeignKey("db.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    automation_note = models.CharField(max_length=1000, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    published_snapshot = models.JSONField(default=dict)

    class Meta(QualityRecord.Meta):
        constraints = [models.UniqueConstraint(fields=["project", "version"], name="quality_project_version_unique")]


class ProjectVersionEvent(QualityRecord):
    version = models.ForeignKey(ProjectVersion, on_delete=models.PROTECT, related_name="events")
    action = models.CharField(max_length=32)
    note = models.TextField(blank=True)
    before_status = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=20)
    snapshot = models.JSONField(default=dict)


class PlatformAccount(models.Model):
    """Stable source account; project duties remain separate explicit grants."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_instance = models.CharField(max_length=80)
    external_user_id = models.PositiveBigIntegerField()
    user = models.OneToOneField("db.User", on_delete=models.PROTECT, related_name="platform_account")
    active = models.BooleanField(default=True)
    source_username = models.CharField(max_length=128)
    source_email = models.CharField(max_length=255, blank=True)
    source_role = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source_instance", "external_user_id"], name="quality_source_account_unique"
            )
        ]


class LocalManagedAccount(models.Model):
    user = models.OneToOneField(
        "db.User", primary_key=True, on_delete=models.PROTECT, related_name="local_managed_account"
    )
    created_by = models.ForeignKey("db.User", on_delete=models.PROTECT, related_name="created_local_accounts")
    created_at = models.DateTimeField(auto_now_add=True)


# Offline migration audit tables; no API or permission changes.
from .legacy_migration_models import LegacyMigrationRun, LegacyMigrationRecord  # noqa: F401,E402

from .external_release_models import ExternalReleaseSnapshot  # noqa: E402,F401


class AdministratorAccessGrant(models.Model):
    """Keep prior native access so global authority can be removed without privilege residue."""

    user = models.ForeignKey("db.User", on_delete=models.CASCADE)
    scope = models.CharField(max_length=10, choices=[("workspace", "workspace"), ("project", "project")])
    target_id = models.UUIDField()
    membership_id = models.UUIDField()
    previous_access = models.JSONField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "scope", "target_id"], name="quality_admin_access_scope_unique")
        ]
