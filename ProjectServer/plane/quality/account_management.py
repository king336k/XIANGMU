# SPDX-License-Identifier: AGPL-3.0-only
"""Separate login identities from per-project duties; ordinary account creation grants no resources."""

from uuid import uuid4
from django.db import transaction
from django.db.models import Q
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from plane.app.views.base import BaseAPIView
from plane.db.models import User, Profile, WorkspaceMember, ProjectMember, Project, Workspace
from .models import (
    PlatformAccount,
    LocalManagedAccount,
    BusinessRole,
    BusinessRoleEvent,
)
from .permissions import ROLE_NAMES, writable_member, has_role, is_administrator


def account_admin(request):
    if is_administrator(request.user):
        return "local", None
    if any(
        has_role(project_id, request.user.id, "PROJECT_MANAGER")
        for project_id in ProjectMember.objects.filter(member=request.user, is_active=True).values_list(
            "project_id", flat=True
        )
    ):
        return "project", None
    raise PermissionDenied("账号管理由管理员负责。")


def managed_project(request, project):
    kind, _ = account_admin(request)
    if not writable_member(project.id, request.user.id, project.workspace.slug):
        raise PermissionDenied("您没有此项目的成员管理权限。")
    if kind == "local" or has_role(project.id, request.user.id, "PROJECT_MANAGER"):
        return
    raise PermissionDenied("您没有此项目的成员管理权限。")


class AccountGrant(serializers.Serializer):
    id = serializers.UUIDField()
    roles = serializers.ListField(
        child=serializers.ChoiceField(choices=["PROJECT_MANAGER", "TECHNICIAN", "REGRESSION_TESTER"]),
        allow_empty=True,
        default=list,
        max_length=3,
    )
    access_role = serializers.ChoiceField(choices=[5, 15, 20], default=15)


class LocalInput(serializers.Serializer):
    username = serializers.RegexField(r"^[a-zA-Z0-9_.-]{2,128}$")
    password = serializers.CharField(min_length=8, max_length=256, write_only=True, trim_whitespace=False)
    grant_mode = serializers.ChoiceField(choices=["none", "workspace", "project"], default="none")
    grants = AccountGrant(many=True, allow_empty=True, max_length=100, default=list)

    def validate(self, data):
        if (data["grant_mode"] == "none") != (not data["grants"]):
            raise ValidationError({"grants": "请选择授权范围，或选择暂不授权。"})
        ids = [row["id"] for row in data["grants"]]
        if len(ids) != len(set(ids)):
            raise ValidationError({"grants": "同一范围不能重复选择。"})
        return data


class AdministratorInput(serializers.Serializer):
    user_id = serializers.UUIDField()
    administrator = serializers.BooleanField()


def assigned_scopes(user, kind):
    memberships = WorkspaceMember.objects.filter(member=user, is_active=True).select_related("workspace")
    if kind == "workspace":
        return [
            {
                "kind": "workspace",
                "id": str(member.workspace_id),
                "name": member.workspace.name,
                "access_role": member.role,
                "roles": member.business_roles or [],
            }
            for member in memberships.filter(has_workspace_access=True).order_by("workspace__name", "workspace_id")
        ]
    inherited = {
        member.workspace_id: member.business_roles or []
        for member in memberships
        if member.has_workspace_access and member.role >= 15
    }
    duties = {
        binding.project_id: [binding.role, *(binding.additional_roles or [])]
        for binding in BusinessRole.objects.filter(user=user)
    }
    return [
        {
            "kind": "project",
            "id": str(member.project_id),
            "name": member.project.name,
            "workspace_name": member.project.workspace.name,
            "workspace_id": str(member.workspace_id),
            "access_role": member.role,
            "roles": duties.get(member.project_id, []),
            "inherited_roles": inherited.get(member.workspace_id, []),
            "inherited_access": member.workspace_id in inherited,
        }
        for member in ProjectMember.objects.filter(member=user, is_active=True, project__archived_at__isnull=True)
        .select_related("project__workspace")
        .order_by("project__workspace__name", "project__name", "project_id")
    ]


class AccountDirectory(BaseAPIView):
    @transaction.atomic
    def patch(self, request):
        from django.shortcuts import get_object_or_404
        from .administrators import set_administrator

        data = AdministratorInput(data=request.data)
        data.is_valid(raise_exception=True)
        target = get_object_or_404(User, pk=data.validated_data["user_id"], is_active=True, is_bot=False)
        set_administrator(request.user, target, data.validated_data["administrator"])
        return Response({"user_id": str(target.id), "is_administrator": is_administrator(target)})

    def get(self, request):
        try:
            kind, account = account_admin(request)
        except PermissionDenied:
            return Response({"can_manage": False, "results": []})
        if request.query_params.get("scope_options"):
            if kind != "local":
                raise PermissionDenied("只有管理员可以选择全平台授权范围。")
            from .member_scopes import ScopeQuery

            query = ScopeQuery(data=request.query_params)
            query.is_valid(raise_exception=True)
            options = query.validated_data
            model = Workspace if options["kind"] == "workspace" else Project
            objects = model.objects.all()
            if model is Project:
                objects = objects.filter(archived_at__isnull=True).select_related("workspace")
            if options["search"]:
                objects = objects.filter(name__icontains=options["search"])
            count = objects.count()
            offset = (options["page"] - 1) * options["per_page"]
            return Response(
                {
                    "results": [
                        {
                            "kind": options["kind"],
                            "id": str(obj.id),
                            "name": obj.name,
                            "workspace_name": obj.workspace.name if model is Project else None,
                            "workspace_id": str(obj.workspace_id) if model is Project else None,
                            "access_role": 0,
                            "roles": [],
                            "revision": "",
                        }
                        for obj in objects.order_by("name", "id")[offset : offset + options["per_page"]]
                    ],
                    "count": count,
                }
            )
        page = serializers.IntegerField(min_value=1).run_validation(request.query_params.get("page", 1))
        per_page = serializers.IntegerField(min_value=1, max_value=100).run_validation(
            request.query_params.get("per_page", 100)
        )
        offset = (page - 1) * per_page
        queryset = User.objects.filter(is_active=True, is_bot=False).exclude(
            id__in=PlatformAccount.objects.values("user_id")
        )
        directory_project = None
        if request.query_params.get("project_id") or request.query_params.get("workspace_slug"):
            from django.shortcuts import get_object_or_404

            project_id = serializers.UUIDField().run_validation(request.query_params.get("project_id"))
            workspace_slug = serializers.SlugField().run_validation(request.query_params.get("workspace_slug"))
            directory_project = get_object_or_404(
                Project, pk=project_id, workspace__slug=workspace_slug, archived_at__isnull=True
            )
            managed_project(request, directory_project)
        if account and not directory_project:
            queryset = queryset.filter(
                Q(platform_account__source_instance=account.source_instance)
                | Q(local_managed_account__created_by=request.user)
            )
        elif kind == "project" and not directory_project:
            queryset = queryset.filter(local_managed_account__created_by=request.user)
        term = request.query_params.get("search", "").strip()[:128]
        if term:
            queryset = queryset.filter(Q(display_name__icontains=term) | Q(username__icontains=term))
        assignment_kind = request.query_params.get("assignment_kind")
        if assignment_kind and kind != "local":
            raise PermissionDenied("只有管理员可以管理跨范围成员。")
        if assignment_kind and assignment_kind not in {"workspace", "project"}:
            raise ValidationError({"assignment_kind": "请选择工作空间或项目成员。"})
        exclude_admins = assignment_kind or request.query_params.get("exclude_administrators") in {"1", "true"}
        if exclude_admins:
            from plane.license.models import InstanceAdmin

            candidates = set(InstanceAdmin.objects.filter(role=20).values_list("user_id", flat=True))
            candidates.update(
                BusinessRole.objects.filter(
                    Q(role="PLATFORM_ADMIN") | Q(additional_roles__contains=["PLATFORM_ADMIN"])
                ).values_list("user_id", flat=True)
            )
            queryset = queryset.exclude(id__in=[user_id for user_id in candidates if is_administrator(user_id)])
        if assignment_kind == "workspace":
            queryset = queryset.filter(
                id__in=WorkspaceMember.objects.filter(is_active=True, has_workspace_access=True).values("member_id")
            )
        elif assignment_kind == "project":
            queryset = queryset.filter(
                id__in=ProjectMember.objects.filter(is_active=True, project__archived_at__isnull=True).values(
                    "member_id"
                )
            )
        count = queryset.count()
        results = []
        for user in queryset.select_related("platform_account").order_by("display_name", "id")[
            offset : offset + per_page
        ]:
            results.append(
                {
                    "id": str(user.id),
                    "username": user.username,
                    "display_name": user.display_name,
                    "is_administrator": is_administrator(user),
                    "source": "项目管理平台",
                    "scopes": assigned_scopes(user, assignment_kind) if assignment_kind else [],
                    "in_project": bool(
                        directory_project
                        and ProjectMember.objects.filter(
                            project=directory_project, member=user, is_active=True
                        ).exists()
                    ),
                }
            )
        directories = []
        requested_source = request.query_params.get("source_instance")
        if requested_source:
            raise ValidationError({"source_instance": "只支持项目管理平台本地账号。"})
        external_results = []
        return Response(
            {
                "can_manage": True,
                "can_manage_administrators": is_administrator(request.user),
                "results": results,
                "count": count,
                "page": page,
                "per_page": per_page,
                "next": page + 1 if offset + per_page < count else None,
                "previous": page - 1 if page > 1 else None,
                "external_results": external_results,
                "external_partial": bool(requested_source),
                "external_limit": 100,
                "external_notice": (
                    "来源目录未提供全量分页信息，本次最多显示100条匹配账号；请通过搜索缩小范围。"
                    if requested_source
                    else ""
                ),
                "sources": [{"id": name, "name": name} for name, _ in directories],
            }
        )

    @transaction.atomic
    def post(self, request):
        if not is_administrator(request.user):
            raise PermissionDenied("只有管理员可以创建平台账号。")
        data = LocalInput(data=request.data)
        data.is_valid(raise_exception=True)
        data = data.validated_data
        if User.objects.filter(username__iexact=data["username"]).exists():
            raise ValidationError({"username": "用户名已存在，请选择已有账号。"})
        user = User(
            username=data["username"],
            email=f"local-{uuid4().hex}@accounts.invalid",
            display_name=data["username"],
            first_name=data["username"],
            is_password_autoset=False,
        )
        user.set_password(data["password"])
        user.save()
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.is_onboarded = True
        profile.is_navigation_tour_completed = True
        profile.language = "zh-CN"
        profile.onboarding_step = {key: True for key in profile.onboarding_step}
        profile.save()
        LocalManagedAccount.objects.create(user=user, created_by=request.user)
        from django.shortcuts import get_object_or_404
        from .member_scopes import MemberScopes

        editor = MemberScopes()
        for grant in sorted(data["grants"], key=lambda row: str(row["id"])):
            if data["grant_mode"] == "workspace":
                scope = get_object_or_404(Workspace.objects.select_for_update(), pk=grant["id"])
                editor.save_workspace(request, user, scope, grant["access_role"], grant["roles"])
            else:
                scope = get_object_or_404(Project.objects.select_for_update(), pk=grant["id"], archived_at__isnull=True)
                editor.save_project(request, user, scope, grant["access_role"], grant["roles"])
        return Response(
            {"id": str(user.id), "username": user.username, "project_assigned": bool(data["grants"])}, status=201
        )


class MembershipInput(serializers.Serializer):
    user_id = serializers.UUIDField()
    role = serializers.ChoiceField(choices=[name for name in ROLE_NAMES if name != "PLATFORM_ADMIN"], required=False)

    def validate(self, data):
        if set(self.initial_data) - set(self.fields):
            raise ValidationError("只支持选择项目管理平台本地账号。")
        return data


class NativeWorkAccess(BaseAPIView):
    def get(self, request):
        from .models import ProjectRolePolicy
        from .permissions import roles_for, capable

        writable_workspaces = WorkspaceMember.objects.filter(member=request.user, is_active=True, role__gte=15).values(
            "workspace_id"
        )
        memberships = ProjectMember.objects.filter(
            member=request.user,
            is_active=True,
            role__gte=15,
            project__archived_at__isnull=True,
            project__workspace_id__in=writable_workspaces,
        )
        strict_ids = set(
            ProjectRolePolicy.objects.filter(project_id__in=memberships.values("project_id"), enabled=True).values_list(
                "project_id", flat=True
            )
        )
        results = {}
        for member in memberships:
            roles = roles_for(member.project_id, request.user.id) if member.project_id in strict_ids else set()
            arrange = member.project_id not in strict_ids or bool(roles & {"PLATFORM_ADMIN", "PROJECT_MANAGER"})
            edit = arrange or "TECHNICIAN" in roles
            results[str(member.project_id)] = {
                "can_arrange": arrange,
                "can_edit": edit,
                "own_only": edit and not arrange,
                "can_edit_documents": capable(member.project_id, request.user.id, "knowledge_edit"),
            }
        response = Response({"projects": results})
        response["Cache-Control"] = "no-store"
        return response


class AccountProjectMembers(BaseAPIView):
    @transaction.atomic
    def post(self, request, workspace_slug, project_id):
        from django.shortcuts import get_object_or_404

        project = get_object_or_404(Project, pk=project_id, workspace__slug=workspace_slug, archived_at__isnull=True)
        managed_project(request, project)
        data = MembershipInput(data=request.data)
        data.is_valid(raise_exception=True)
        data = data.validated_data
        if data.get("role") == "PLATFORM_ADMIN":
            raise PermissionDenied("管理员请在账号管理中统一授权，加入项目只分配业务岗位。")
        user = get_object_or_404(User, pk=data["user_id"], is_active=True, is_bot=False)
        # Existing duties must go through RoleList, including its last-manager protection.
        if BusinessRole.objects.filter(project=project, user=user).exists():
            from .views import Conflict

            raise Conflict("该账号已加入项目，请在成员与权限中调整岗位。")
        if is_administrator(user):
            raise PermissionDenied("管理员自动管理全部项目，无需加入成员。")
        if PlatformAccount.objects.filter(user=user).exists():
            raise PermissionDenied("请先在项目管理平台建立独立账号。")
        ws, _ = WorkspaceMember.objects.get_or_create(
            workspace=project.workspace, member=user, defaults={"role": 15, "has_workspace_access": False}
        )
        if not ws.is_active:
            raise PermissionDenied("工作空间成员已停用，请先处理停用状态。")
        member, _ = ProjectMember.objects.get_or_create(
            project=project, member=user, defaults={"workspace": project.workspace, "role": 15}
        )
        member.is_active = True
        member.save(update_fields=["is_active"])
        if data.get("role"):
            BusinessRole.objects.create(project=project, user=user, role=data["role"], created_by=request.user)
            BusinessRoleEvent.objects.create(
                project=project,
                user=user,
                previous_role="",
                role=data["role"],
                action="assign",
                created_by=request.user,
            )
        return Response(
            {
                "user_id": str(user.id),
                "project_id": str(project.id),
                "role": data.get("role"),
                "roles": [data["role"]] if data.get("role") else [],
            }
        )
