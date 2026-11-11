# SPDX-License-Identifier: AGPL-3.0-only
"""Business capabilities complement, never replace, Plane membership boundaries."""

from rest_framework.exceptions import PermissionDenied, ValidationError
from plane.db.models import ProjectMember, WorkspaceMember
from .models import BusinessRole, BusinessRoleEvent, ProjectRolePolicy

ROLE_NAMES = {
    "PLATFORM_ADMIN": "管理员",
    "PROJECT_MANAGER": "项目经理",
    "TECHNICIAN": "技术员",
    "REGRESSION_TESTER": "测试员",
    "REPORTER": "数采员",
}
ROLE_CAPABILITIES = {
    "PLATFORM_ADMIN": {"manage_roles"},
    "PROJECT_MANAGER": {
        "manage_roles",
        "manage_test",
        "manage_case",
        "manage_test_plan",
        "manage_defect",
        "review",
        "admit",
        "knowledge_write",
        "report",
        "comment",
        "chat",
        "package",
    },
    "TECHNICIAN": {
        "solution",
        "manage_defect",
        "claim_defect",
        "knowledge_write",
        "report",
        "comment",
        "chat",
        "package",
    },
    "REGRESSION_TESTER": {
        "manage_case",
        "manage_test_plan",
        "execute",
        "report",
        "comment",
        "chat",
        "package",
        "knowledge_write",
    },
    "REPORTER": {"report", "chat", "package"},
}
# Administrators include every business duty; assigned roles remain unchanged for source identity checks.
ROLE_CAPABILITIES["PLATFORM_ADMIN"] |= set().union(*ROLE_CAPABILITIES.values())
ALL_CAPABILITIES = set().union(*ROLE_CAPABILITIES.values()) | {"knowledge_edit", "knowledge_review"}


def is_administrator(user):
    """One effective administrator; project role 20 alone never grants instance power."""
    from plane.db.models import User
    from plane.license.models import InstanceAdmin, InstanceConfiguration
    from .models import PlatformAccount

    user_id = getattr(user, "pk", user)
    if not user_id or not User.objects.filter(pk=user_id, is_active=True, is_bot=False).exists():
        return False
    if PlatformAccount.objects.filter(user_id=user_id).exists():
        return False
    if InstanceAdmin.objects.filter(user_id=user_id, role=20).exists():
        return True
    if InstanceConfiguration.objects.filter(key="QUALITY_ADMIN_OVERRIDE:" + str(user_id), value="false").exists():
        return False
    for row in BusinessRole.objects.filter(user_id=user_id).select_related("project__workspace"):
        if "PLATFORM_ADMIN" not in {row.role, *(row.additional_roles or [])}:
            continue
        if not writable_member(row.project_id, user_id, row.project.workspace.slug):
            continue
        events = BusinessRoleEvent.objects.filter(project_id=row.project_id, user_id=user_id)
        explicit_admin = any(
            "PLATFORM_ADMIN" in event.role.split("+")
            for event in events.filter(action__in=["set_roles", "assign", "source_policy"])
        )
        if events.filter(action="initialize").exists() and not explicit_admin:
            continue
        return True
    return False


def can_create_projects(user):
    from .models import PlatformAccount, LocalManagedAccount

    if is_administrator(user):
        return True
    account = PlatformAccount.objects.filter(user=user).first()
    if account:
        return False
    return not LocalManagedAccount.objects.filter(user=user).exists()


def strict(project_id):
    return ProjectRolePolicy.objects.filter(project_id=project_id, enabled=True).exists()


def role_for(project_id, user_id):
    roles = roles_for(project_id, user_id)
    if "PLATFORM_ADMIN" in roles:
        return "PLATFORM_ADMIN"
    row = BusinessRole.objects.filter(project_id=project_id, user_id=user_id).first()
    return row.role if row and row.role in roles else next(iter(sorted(roles)), None)


def roles_for(project_id, user_id):
    membership = (
        ProjectMember.objects.filter(project_id=project_id, member_id=user_id)
        .values_list("project__workspace__slug", flat=True)
        .first()
    )
    if not membership or not writable_member(project_id, user_id, membership):
        return set()
    row = BusinessRole.objects.filter(project_id=project_id, user_id=user_id).first()
    roles = {row.role, *(row.additional_roles or [])} if row else set()
    workspace_member = WorkspaceMember.objects.filter(
        workspace__slug=membership, member_id=user_id, is_active=True, role__gte=15
    ).first()
    if workspace_member:
        roles.update(workspace_member.business_roles or [])
    legacy_admin = "PLATFORM_ADMIN" in roles
    roles.discard("PLATFORM_ADMIN")
    if is_administrator(user_id):
        roles.add("PLATFORM_ADMIN")
    elif legacy_admin:
        roles.add("PROJECT_MANAGER")
    return roles


def has_role(project_id, user_id, role):
    roles = roles_for(project_id, user_id)
    return role in roles or "PLATFORM_ADMIN" in roles and role in ROLE_NAMES


def knowledge_reviewer(project_id, user_id):
    """Knowledge review is shared by admins, within active writable memberships."""

    member = (
        ProjectMember.objects.filter(
            project_id=project_id,
            project__archived_at__isnull=True,
            member_id=user_id,
            member__is_active=True,
            is_active=True,
            role__gte=15,
        )
        .values("role", "project__workspace_id")
        .first()
    )
    if not member:
        return False
    workspace_role = (
        WorkspaceMember.objects.filter(
            workspace_id=member["project__workspace_id"], member_id=user_id, is_active=True, role__gte=15
        )
        .values_list("role", flat=True)
        .first()
    )
    if workspace_role is None:
        return False
    if strict(project_id):
        return bool(roles_for(project_id, user_id) & {"PLATFORM_ADMIN", "PROJECT_MANAGER"})
    return (
        member["role"] == 20
        or workspace_role == 20
        or bool(roles_for(project_id, user_id) & {"PLATFORM_ADMIN", "PROJECT_MANAGER"})
        or is_administrator(user_id)
    )


def capable(project_id, user_id, capability):
    if capability == "knowledge_review":
        return knowledge_reviewer(project_id, user_id)
    if capability == "knowledge_edit":
        return knowledge_reviewer(project_id, user_id) or capable(project_id, user_id, "knowledge_write")
    if not strict(project_id):
        return True
    return any(capability in ROLE_CAPABILITIES.get(role, set()) for role in roles_for(project_id, user_id))


def capabilities_for(project_id, user_id, roles=None):
    """Compute a context snapshot once; never cache authorization across requests."""
    roles = roles_for(project_id, user_id) if roles is None else roles
    allowed = (
        set().union(*(ROLE_CAPABILITIES.get(role, set()) for role in roles)) if strict(project_id) else ALL_CAPABILITIES
    )
    reviewer = knowledge_reviewer(project_id, user_id)
    return {
        cap: (
            reviewer
            if cap == "knowledge_review"
            else reviewer or "knowledge_write" in allowed
            if cap == "knowledge_edit"
            else cap in allowed
        )
        for cap in ALL_CAPABILITIES
    }


def require_capability(view, capability):
    if not capable(view.project_id, view.request.user.id, capability):
        raise PermissionDenied("当前业务角色不允许此操作。")


def writable_member(project_id, user_id, workspace_slug):
    return (
        ProjectMember.objects.filter(
            project_id=project_id,
            member_id=user_id,
            is_active=True,
            role__gte=15,
            member__is_active=True,
            project__archived_at__isnull=True,
            project__workspace__slug=workspace_slug,
        ).exists()
        and WorkspaceMember.objects.filter(
            workspace__slug=workspace_slug, member_id=user_id, is_active=True, role__gte=15
        ).exists()
    )


def require_assignee(view, user_id, role):
    if strict(view.project_id) and not has_role(view.project_id, user_id, role):
        raise ValidationError({"assignee_id": f"请选择当前项目的{ROLE_NAMES[role]}。"})


def permission_for(view, request):
    name = type(view).__name__
    action = request.data.get("action") if hasattr(request.data, "get") else None
    if name in {"RoleList", "RolePolicy"}:
        return "manage_roles"
    if name == "PlanWorkflow":
        return (
            "manage_test"
            if action in {"approve", "return"}
            else "manage_test_plan"
            if action in {"assign", "cancel"}
            else "execute"
        )
    if name == "BulkActions":
        return {"cases": "manage_case", "suites": "manage_case", "plans": "manage_test_plan"}.get(
            request.data.get("resource"), "manage_test"
        )
    if name == "DataRegressionList":
        return "manage_test_plan" if capable(view.project_id, request.user.id, "manage_test_plan") else "manage_defect"
    if name == "DefectCollaboration":
        return (
            "claim_defect"
            if action == "claim"
            else "comment"
            if request.data.get("visibility") == "internal"
            else "report"
        )
    if name in {"DocumentOcr", "DocumentOcrReview"}:
        return "knowledge_edit"
    if name in {"DocumentImports", "DocumentConfirm", "FeishuDocumentImport"}:
        resource = request.data.get("resource")
        if name == "DocumentConfirm":
            from .models import DocumentImport

            resource = (
                DocumentImport.objects.filter(pk=view.kwargs.get("pk"), project_id=view.project_id)
                .values_list("resource", flat=True)
                .first()
            )
        return "knowledge_edit" if resource == "knowledge" else "manage_test"
    if name == "ArticleWorkflow":
        return "knowledge_review" if action in {"publish", "reject", "offline"} else "knowledge_edit"
    return {
        "ExternalReleasePreview": "manage_test",
        "ExternalReleaseConfirm": "manage_test",
        "ProjectVersions": "manage_test",
        "ProjectVersionDetail": "manage_test",
        "ProjectVersionWorkflow": "manage_test",
        "ProjectVersionSync": "manage_test",
        "DefectTeam": "manage_defect",
        "ProjectCollaborationSettings": "manage_test",
        "DefectRouting": "manage_defect",
        "DefectReminders": "comment",
        "DataRegressionList": "manage_defect",
        "DataEvidenceList": "execute",
        "DaqBindings": "manage_test",
        "DaqIdentities": "manage_roles",
        "DaqProjectMapping": "manage_roles",
        "DaqReports": "report",
        "DaqIncidents": "report",
        "DaqIncidentSession": "report",
        "DaqQuery": "chat",
        "RequirementList": "knowledge_write",
        "RequirementDetail": "knowledge_write",
        "RequirementWorkflow": "knowledge_write",
        "RequirementTasks": "knowledge_write",
        "CaseList": "manage_case",
        "CaseDetail": "manage_case",
        "PlanList": "manage_test_plan",
        "PlanDetail": "manage_test_plan",
        "PlanCopy": "manage_test_plan",
        "ExecutionList": "execute",
        "ExecutionDefect": "report",
        "DefectList": "report",
        "DefectDetail": "manage_defect",
        "DefectReportEdit": "report",
        "SourceDefect": "report",
        "DefectAttachments": "package",
        "PackageFiles": "package",
        "PackagePreflight": "package",
        "PackageList": "package",
        "SuiteList": "manage_case",
        "SuiteDetail": "manage_case",
        "SuiteCopy": "manage_case",
        "SuitePublish": "manage_case",
        "ReleaseList": "manage_test",
        "ReleaseDetail": "manage_test",
        "ReleaseCopy": "manage_test",
        "ReleaseAdmit": "admit",
        "SolutionList": "solution",
        "SolutionDetail": "solution",
        "SolutionSubmit": "solution",
        "SolutionDecision": "review",
        "ReportList": "manage_test_plan",
        "ReportDetail": "manage_test_plan",
        "ReportConclude": "review",
        "NotificationTargets": "manage_test",
        "NotificationTargetDetail": "manage_test",
        "ReportDeliveries": "manage_test",
        "ReportDeliverySend": "manage_test",
        "DefectDisposition": "manage_defect",
        "BulkActions": "manage_test",
        "IntegrationOverview": "manage_roles",
        "IntegrationCheck": "manage_roles",
        "CatalogSync": "manage_roles",
        "CatalogTaskImport": "manage_test",
        "FieldAgentCredential": "manage_test",
        "FieldAgents": "manage_test",
        "TestResources": "manage_test_plan",
        "TestResourceDetail": "manage_test_plan",
        "PlanResources": "manage_test_plan",
        "FieldAgentDetail": "manage_test",
        "FieldHeartbeat": "report",
        "TelemetryReview": "review",
        "DiagnosticList": "manage_defect",
        "DiagnosticDetail": "manage_defect",
        "DocumentImports": "manage_test",
        "DocumentConfirm": "manage_test",
        "FeishuDocumentImport": "manage_test",
        "TaskPackages": "manage_test",
        "TaskPackageConfirm": "manage_test",
        "ImportList": "manage_case",
        "ImportConfirm": "manage_case",
        "ArticleShares": "knowledge_review",
        "ShareWithdraw": "knowledge_review",
        "GovernanceIgnore": "knowledge_review",
        "GovernanceUndo": "knowledge_review",
        "GovernanceMerge": "knowledge_review",
        "GovernanceOffline": "knowledge_review",
        "ArticleAnalysis": "knowledge_edit",
        "ArticleAnalysisApply": "knowledge_edit",
        "ArticleList": "knowledge_edit",
        "ArticleDetail": "knowledge_edit",
        "ChatEndpoint": "chat",
        "ChatFeedback": "chat",
    }.get(name, "unavailable")
