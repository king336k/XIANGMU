# SPDX-License-Identifier: AGPL-3.0-only
"""Separate login identities from per-project duties; ordinary account creation grants no resources."""

from uuid import uuid4
from django.db import transaction
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from plane.app.views.base import BaseAPIView
from plane.db.models import User, Profile, WorkspaceMember, ProjectMember, Project
from plane.license.models import InstanceConfiguration
from .models import (
    PlatformAccount,
    LocalManagedAccount,
    PlatformIdentity,
    PlatformProject,
    BusinessRole,
    BusinessRoleEvent,
)
from .permissions import ROLE_NAMES, writable_member, has_role, is_administrator
from . import platform
from .data_accounts import authority_config, authority_request


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
    kind, account = account_admin(request)
    if kind == "local":
        if writable_member(project.id, request.user.id, project.workspace.slug):
            return
        raise PermissionDenied("管理员须先获得当前项目的有效成员访问权限。")
    if account and PlatformProject.objects.filter(project=project, source_instance=kind, active=True).exists():
        return
    if (
        account
        and project.created_by_id == request.user.id
        and writable_member(project.id, request.user.id, project.workspace.slug)
        and ProjectMember.objects.filter(project=project, member=request.user, is_active=True, role=20).exists()
    ):
        return
    if writable_member(project.id, request.user.id, project.workspace.slug) and has_role(
        project.id, request.user.id, "PROJECT_MANAGER"
    ):
        return
    raise PermissionDenied("您没有此项目的成员管理权限。")


class LocalInput(serializers.Serializer):
    username = serializers.RegexField(r"^[a-zA-Z0-9_.-]{2,128}$")
    password = serializers.CharField(min_length=8, max_length=256, write_only=True, trim_whitespace=False)


class AdministratorInput(serializers.Serializer):
    user_id = serializers.UUIDField()
    administrator = serializers.BooleanField()


def source_directories():
    from .connection_settings import read_connection

    results = []
    for row in InstanceConfiguration.objects.filter(key__startswith="QUALITY_SOURCE:"):
        name = row.key.split(":", 1)[1]
        config = read_connection(name) or {}
        if config.get("kind") == "data_platform" and config.get("login_enabled") and config.get("login_auto_provision"):
            results.append((name, config))
    return results


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
        page = serializers.IntegerField(min_value=1).run_validation(request.query_params.get("page", 1))
        per_page = serializers.IntegerField(min_value=1, max_value=100).run_validation(
            request.query_params.get("per_page", 100)
        )
        offset = (page - 1) * per_page
        queryset = User.objects.filter(is_active=True, is_bot=False)
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
            from django.db.models import Q

            queryset = queryset.filter(
                Q(platform_account__source_instance=account.source_instance)
                | Q(local_managed_account__created_by=request.user)
            )
        elif kind == "project" and not directory_project:
            queryset = queryset.filter(local_managed_account__created_by=request.user)
        term = request.query_params.get("search", "").strip()[:128]
        if term:
            from django.db.models import Q

            queryset = queryset.filter(Q(display_name__icontains=term) | Q(username__icontains=term))
        count = queryset.count()
        results = []
        for user in queryset.select_related("platform_account").order_by("display_name", "id")[
            offset : offset + per_page
        ]:
            external = getattr(user, "platform_account", None)
            results.append(
                {
                    "id": str(user.id),
                    "username": external.source_username if external else user.username,
                    "display_name": user.display_name,
                    "is_administrator": is_administrator(user),
                    "source": "数据管理平台" if external else "项目管理平台",
                    "in_project": bool(
                        directory_project
                        and ProjectMember.objects.filter(
                            project=directory_project, member=user, is_active=True
                        ).exists()
                    ),
                }
            )
        directories = source_directories() if directory_project else []
        if account:
            directories = [(name, config) for name, config in directories if name == account.source_instance]
        requested_source = request.query_params.get("source_instance")
        external_results = []
        if requested_source:
            if not directory_project or requested_source not in {name for name, _ in directories}:
                raise PermissionDenied("没有此账号目录的访问权限。")
            people = platform.fetch(requested_source, "/internal/issue-users")
            if not isinstance(people, list):
                raise platform.PlatformUnavailable("数据平台账号目录格式无效。")
            linked = set(
                PlatformAccount.objects.filter(source_instance=requested_source).values_list(
                    "external_user_id", flat=True
                )
            )
            for person in people:
                if (
                    not isinstance(person, dict)
                    or type(person.get("id")) is not int
                    or person["id"] <= 0
                    or person.get("active") is not True
                    or not isinstance(person.get("username"), str)
                    or not person["username"].strip()
                    or len(person["username"]) > 128
                    or person.get("role") == "Pending"
                    or person["id"] in linked
                    or (term and term.casefold() not in person["username"].casefold())
                ):
                    continue
                external_results.append(
                    {
                        "source_instance": requested_source,
                        "external_user_id": person["id"],
                        "username": person["username"],
                        "source": "数据管理平台",
                        "in_project": False,
                    }
                )
                if len(external_results) >= 100:
                    break
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
        account_admin(request)
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
        return Response({"id": str(user.id), "username": user.username, "project_assigned": False}, status=201)


class MembershipInput(serializers.Serializer):
    user_id = serializers.UUIDField(required=False)
    source_instance = serializers.RegexField(r"^[a-zA-Z0-9_-]{1,80}$", required=False)
    external_user_id = serializers.IntegerField(min_value=1, required=False)
    role = serializers.ChoiceField(choices=list(ROLE_NAMES))

    def validate(self, data):
        if bool(data.get("user_id")) == bool(data.get("source_instance") or data.get("external_user_id")):
            raise ValidationError("请选择一个本平台账号或来源数据平台账号。")
        if not data.get("user_id") and not (data.get("source_instance") and data.get("external_user_id")):
            raise ValidationError("来源实例与账号编号必须同时填写。")
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
        if data["role"] == "PLATFORM_ADMIN":
            raise PermissionDenied("管理员请在账号管理中统一授权，加入项目只分配业务岗位。")
        if data.get("source_instance"):
            from .data_accounts import link_account

            source = data["source_instance"]
            kind, source_admin = account_admin(request)
            if source_admin and source_admin.source_instance != source:
                raise PermissionDenied("不能从其他来源目录添加人员。")
            config = authority_config(source)
            person = authority_request(
                config, f"/internal/issue-users/{data['external_user_id']}", token=config.get("service_token")
            )
            if (
                not isinstance(person, dict)
                or person.get("id") != data["external_user_id"]
                or person.get("active") is not True
                or person.get("role") == "Pending"
                or not isinstance(person.get("username"), str)
                or not person["username"].strip()
                or len(person["username"]) > 128
            ):
                raise PermissionDenied("来源账号未激活或仍待分配。")
            account = link_account(source, {**person, "status": "Active"}, config)
            user = account.user
        else:
            user = get_object_or_404(User, pk=data["user_id"], is_active=True, is_bot=False)
        # Existing duties must go through RoleList, including its last-manager protection.
        if BusinessRole.objects.filter(project=project, user=user).exists():
            from .views import Conflict

            raise Conflict("该账号已加入项目，请在成员与权限中调整岗位。")
        external = PlatformAccount.objects.filter(user=user).first()
        if external and not external.active:
            raise PermissionDenied("此来源账号关联已停用，不能加入项目。")
        if external:
            config = authority_config(external.source_instance)
            authority = authority_request(
                config, f"/internal/issue-users/{external.external_user_id}", token=config.get("service_token")
            )
            mappings = PlatformProject.objects.filter(project=project, source_instance=external.source_instance)
            if not isinstance(authority, dict) or authority.get("active") is not True:
                raise PermissionDenied("该数据平台账号不存在或已停用。")
            if mappings.exists():
                permissions = authority_request(
                    config,
                    f"/internal/issue-permissions/users/{external.external_user_id}",
                    token=config.get("service_token"),
                )
                if not isinstance(permissions, dict) or not any(
                    isinstance(row, dict) and mappings.filter(active=True, external_project_id=row.get("id")).exists()
                    for row in permissions.get("projects", [])
                ):
                    raise PermissionDenied("该账号尚未获得关联数据平台项目授权。")
            if data["role"] == "REPORTER" and authority.get("role") not in {
                "TeamLeader",
                "Annotator",
                "Auditor",
                "Collector",
            }:
                raise PermissionDenied("此来源身份不允许默认分配数采岗位。")
        ws, _ = WorkspaceMember.objects.get_or_create(workspace=project.workspace, member=user, defaults={"role": 15})
        if not ws.is_active:
            raise PermissionDenied("工作空间成员已停用，请先处理停用状态。")
        member, _ = ProjectMember.objects.get_or_create(
            project=project, member=user, defaults={"workspace": project.workspace, "role": 15}
        )
        member.is_active = True
        member.save(update_fields=["is_active"])
        binding, created = BusinessRole.objects.get_or_create(
            project=project, user=user, defaults={"role": data["role"], "created_by": request.user}
        )
        old = "" if created else binding.role
        binding.role = data["role"]
        binding.save()
        BusinessRoleEvent.objects.create(
            project=project, user=user, previous_role=old, role=binding.role, action="assign", created_by=request.user
        )
        if external and mappings.filter(active=True).exists():
            PlatformIdentity.objects.update_or_create(
                project=project,
                source_instance=external.source_instance,
                external_user_id=external.external_user_id,
                defaults={"user": user, "active": True, "created_by_id": config["configured_by"]},
            )
        return Response({"user_id": str(user.id), "project_id": str(project.id), "role": binding.role})
