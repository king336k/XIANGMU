# SPDX-License-Identifier: AGPL-3.0-only
"""Keep strict business duties at native project-work mutation entry points."""

from rest_framework.permissions import SAFE_METHODS
from rest_framework.exceptions import PermissionDenied
from plane.db.models import IssueAssignee, DraftIssue, WorkspaceMember, ProjectMember
from .permissions import strict, has_role, can_create_projects, writable_member, is_administrator

WORK_MUTATIONS = {
    "CycleViewSet",
    "ModuleViewSet",
    "ModuleLinkViewSet",
    "CycleArchiveUnarchiveEndpoint",
    "ModuleArchiveUnarchiveEndpoint",
    "CycleListCreateAPIEndpoint",
    "CycleDetailAPIEndpoint",
    "CycleArchiveUnarchiveAPIEndpoint",
    "ModuleListCreateAPIEndpoint",
    "ModuleDetailAPIEndpoint",
    "ModuleArchiveUnarchiveAPIEndpoint",
    "CycleIssueListCreateAPIEndpoint",
    "CycleIssueDetailAPIEndpoint",
    "TransferCycleIssueAPIEndpoint",
    "ModuleIssueListCreateAPIEndpoint",
    "ModuleIssueDetailAPIEndpoint",
    "WorkspaceDraftIssueViewSet",
    "TransferCycleIssueEndpoint",
    "IssueViewSet",
    "IssueArchiveViewSet",
    "BulkDeleteIssuesEndpoint",
    "BulkArchiveIssuesEndpoint",
    "IssueBulkUpdateDateEndpoint",
    "DeletedIssuesListViewSet",
    "SubIssuesEndpoint",
    "IssueListCreateAPIEndpoint",
    "IssueDetailAPIEndpoint",
    "CycleIssueViewSet",
    "ModuleIssueViewSet",
    "IssueRelationViewSet",
    "IssueRelationListCreateAPIEndpoint",
    "IssueRelationDetailAPIEndpoint",
}

PROJECT_SETTINGS_MUTATIONS = {
    "StateViewSet",
    "IntakeStateEndpoint",
    "LabelViewSet",
    "BulkCreateIssueLabelsEndpoint",
    "BulkEstimatePointEndpoint",
    "EstimatePointEndpoint",
    "StateListCreateAPIEndpoint",
    "StateDetailAPIEndpoint",
    "LabelListCreateAPIEndpoint",
    "LabelDetailAPIEndpoint",
}


def can_manage_native_access(user, workspace_slug, project_id=None):
    """Use the effective administrator within existing writable memberships."""
    if not (
        user.is_authenticated
        and user.is_active
        and WorkspaceMember.objects.filter(
            workspace__slug=workspace_slug, member=user, is_active=True, role__gte=15
        ).exists()
    ):
        return False
    if project_id and not writable_member(project_id, user.id, workspace_slug):
        return False
    return is_administrator(user)


def can_manage_native_work(view, request, kwargs):
    project_id = kwargs.get("project_id")
    return bool(
        request.user.is_authenticated
        and request.user.is_active
        and project_id
        and type(view).__name__ in WORK_MUTATIONS
        and strict(project_id)
        and writable_member(project_id, request.user.id, kwargs.get("slug", ""))
        and has_role(project_id, request.user.id, "PROJECT_MANAGER")
    )


def guard_native_mutation(view, request, kwargs):
    if (
        type(view).__module__.startswith(("plane.app.views.", "plane.api.views."))
        and kwargs.get("slug")
        and (kwargs.get("project_id") or kwargs.get("project_identifier"))
        and request.user.is_authenticated
        and not WorkspaceMember.objects.filter(
            workspace__slug=kwargs["slug"], member=request.user, member__is_active=True, is_active=True
        ).exists()
    ):
        raise PermissionDenied("当前账号没有此工作空间的访问权限。")
    if (
        request.method not in SAFE_METHODS
        and request.user.is_authenticated
        and type(view).__module__.startswith(("plane.app.views.", "plane.api.views."))
        and type(view).__name__ in PROJECT_SETTINGS_MUTATIONS
    ):
        slug, project_id = kwargs.get("slug"), kwargs.get("project_id")
        if not writable_member(project_id, request.user.id, slug) or not (
            can_manage_native_access(request.user, slug, project_id)
            or ProjectMember.objects.filter(
                project_id=project_id, member=request.user, is_active=True, role=20
            ).exists()
            or WorkspaceMember.objects.filter(
                workspace__slug=slug, member=request.user, is_active=True, role=20
            ).exists()
        ):
            raise PermissionDenied("项目配置由管理员维护。")
    if (
        request.user.is_authenticated
        and (
            getattr(view, "action", None) == "create"
            and type(view).__module__.startswith("plane.app.views.")
            and type(view).__name__ in {"WorkSpaceViewSet", "ProjectViewSet"}
            or request.method == "POST"
            and type(view).__module__.startswith("plane.api.views.")
            and type(view).__name__ == "ProjectListCreateAPIEndpoint"
        )
        and not can_create_projects(request.user)
    ):
        raise PermissionDenied("项目和工作空间由管理员创建，请联系管理员安排项目与岗位。")
    if (
        request.method in SAFE_METHODS
        or not request.user.is_authenticated
        or not type(view).__module__.startswith(("plane.app.views.", "plane.api.views."))
        or type(view).__name__ not in WORK_MUTATIONS
    ):
        return
    project_id = kwargs.get("project_id")
    if type(view).__name__ == "WorkspaceDraftIssueViewSet":
        if getattr(view, "action", None) != "create_draft_to_issue":
            return
        project_id = (
            DraftIssue.objects.filter(
                pk=kwargs.get("draft_id"), created_by=request.user, workspace__slug=kwargs.get("slug")
            )
            .values_list("project_id", flat=True)
            .first()
        )
    if not project_id or not strict(project_id):
        return
    if not writable_member(project_id, request.user.id, kwargs.get("slug", "")):
        raise PermissionDenied("当前账号没有此项目的可写访问权限。")
    if has_role(project_id, request.user.id, "PROJECT_MANAGER"):
        return
    if not has_role(project_id, request.user.id, "TECHNICIAN"):
        raise PermissionDenied("当前业务职责不允许调整研发工作项，请在本职业务模块操作。")
    if request.method not in {"PATCH", "PUT"} or type(view).__name__ not in {"IssueViewSet", "IssueDetailAPIEndpoint"}:
        raise PermissionDenied("由项目经理安排工作，技术员只可更新分派给自己的研发任务。")
    issue_id = kwargs.get("issue_id") or kwargs.get("pk")
    if (
        not issue_id
        or request.method == "DELETE"
        or not IssueAssignee.objects.filter(issue_id=issue_id, project_id=project_id, assignee=request.user).exists()
    ):
        raise PermissionDenied("由项目经理安排工作，技术员只可更新分派给自己的研发任务。")
    for key in ["assignee_ids", "assignees"]:
        if key in request.data and set(map(str, request.data[key] or [])) != {str(request.user.id)}:
            raise PermissionDenied("工作项转派由项目经理处理。")
    if "parent_id" in request.data or "parent" in request.data:
        raise PermissionDenied("研发任务层级由项目经理安排。")
