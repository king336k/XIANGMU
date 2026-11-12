# SPDX-License-Identifier: AGPL-3.0-only
"""One administrator-only editor for explicit workspace and project membership grants."""

import hashlib
import json
from types import SimpleNamespace

from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from plane.app.views.base import BaseAPIView
from plane.db.models import User, Workspace, WorkspaceMember, Project, ProjectMember
from .models import BusinessRole, BusinessRoleEvent, PlatformAccount, PlatformIdentity, PlatformProject
from .permissions import is_administrator
from .roles import apply_project_roles, validate_project_role_retention
from .views import Conflict

DUTIES = ["PROJECT_MANAGER", "TECHNICIAN", "REGRESSION_TESTER"]


class ScopeQuery(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["workspace", "project"], default="workspace")
    workspace_id = serializers.UUIDField(required=False)
    assigned_only = serializers.BooleanField(default=False)
    assignment = serializers.ChoiceField(choices=["all", "assigned", "unassigned"], default="all")
    search = serializers.CharField(max_length=128, allow_blank=True, default="")
    page = serializers.IntegerField(min_value=1, default=1)
    per_page = serializers.IntegerField(min_value=1, max_value=50, default=20)


class ScopeChange(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["workspace", "project"])
    id = serializers.UUIDField()
    access_role = serializers.ChoiceField(choices=[0, 5, 15, 20])
    expected_revision = serializers.RegexField(r"^[a-f0-9]{64}$")
    roles = serializers.ListField(
        child=serializers.ChoiceField(choices=DUTIES), allow_empty=True, max_length=3, required=False
    )


class ScopeChanges(serializers.Serializer):
    changes = ScopeChange(many=True, allow_empty=False, max_length=100)

    def validate_changes(self, changes):
        keys = [(row["kind"], row["id"]) for row in changes]
        if len(keys) != len(set(keys)):
            raise ValidationError("同一范围不能重复提交。")
        return changes


def membership_snapshot(row):
    return (
        None
        if row is None
        else {"id": str(row.id), "role": row.role, "active": row.is_active, "updated_at": row.updated_at.isoformat()}
    )


def scope_row(kind, obj, target):
    model = WorkspaceMember if kind == "workspace" else ProjectMember
    filters = {"workspace": obj} if kind == "workspace" else {"project": obj}
    member = model.objects.filter(member=target, **filters).first()
    raw = {"membership": membership_snapshot(member)}
    if kind == "workspace":
        raw["has_workspace_access"] = bool(member and member.has_workspace_access)
    roles = list(member.business_roles or []) if kind == "workspace" and member else []
    if kind == "workspace":
        raw["business_roles"] = roles
        raw["project_memberships"] = list(
            ProjectMember.objects.filter(workspace=obj, member=target)
            .order_by("project_id")
            .values("id", "project_id", "role", "is_active", "updated_at")
        )
        raw["project_duties"] = list(
            BusinessRole.objects.filter(project__workspace=obj, user=target)
            .order_by("project_id")
            .values("id", "project_id", "role", "additional_roles", "updated_at")
        )
    if kind == "project":
        binding = BusinessRole.objects.filter(project=obj, user=target).first()
        roles = [
            duty for duty in ([binding.role, *(binding.additional_roles or [])] if binding else []) if duty in DUTIES
        ]
        raw["duties"] = (
            None
            if binding is None
            else {
                "id": str(binding.id),
                "role": binding.role,
                "additional_roles": binding.additional_roles,
                "updated_at": binding.updated_at.isoformat(),
            }
        )
        workspace_member = WorkspaceMember.objects.filter(workspace=obj.workspace, member=target).first()
        raw["workspace"] = membership_snapshot(workspace_member)
        inherited = (
            list(workspace_member.business_roles or [])
            if workspace_member
            and workspace_member.is_active
            and workspace_member.role >= 15
            and workspace_member.has_workspace_access
            else []
        )
        raw["inherited_roles"] = inherited
        inherited_access = bool(
            workspace_member
            and workspace_member.is_active
            and workspace_member.has_workspace_access
            and workspace_member.role >= 15
        )
    revision = hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
    result = {
        "kind": kind,
        "id": str(obj.id),
        "name": obj.name,
        "active": bool(member and member.is_active and (kind != "workspace" or member.has_workspace_access)),
        "access_role": member.role
        if member and member.is_active and (kind != "workspace" or member.has_workspace_access)
        else 0,
        "roles": roles,
        "revision": revision,
    }
    if kind == "workspace":
        result.update(
            slug=obj.slug, project_count=Project.objects.filter(workspace=obj, archived_at__isnull=True).count()
        )
    else:
        result.update(
            identifier=obj.identifier,
            workspace_id=str(obj.workspace_id),
            workspace_name=obj.workspace.name,
            inherited_roles=inherited,
            inherited_access=inherited_access,
        )
    return result


def verify_source_grant(target, project=None):
    if PlatformAccount.objects.filter(user=target).exists():
        raise PermissionDenied("请在项目管理平台建立独立账号后分配权限。")


def audit_access(project, target, actor, before, after):
    BusinessRoleEvent.objects.create(
        project=project,
        user=target,
        created_by=actor,
        action="scope_access",
        previous_role=str(before),
        role=str(after),
    )


class MemberScopes(BaseAPIView):
    def target(self, request, user_id, lock=False):
        if not is_administrator(request.user):
            raise PermissionDenied("只有管理员可以管理跨工作空间和项目的人员权限。")
        query = User.objects.filter(is_active=True, is_bot=False)
        if lock:
            query = query.select_for_update()
        return get_object_or_404(query, pk=user_id)

    def get(self, request, user_id):
        target = self.target(request, user_id)
        query = ScopeQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        data = query.validated_data
        kind = data["kind"]
        if kind == "workspace":
            objects = Workspace.objects.all()
            if data["search"]:
                objects = objects.filter(Q(name__icontains=data["search"]) | Q(slug__icontains=data["search"]))
        else:
            objects = Project.objects.filter(archived_at__isnull=True).select_related("workspace")
            if "workspace_id" in data:
                workspace = get_object_or_404(Workspace, pk=data["workspace_id"])
                objects = objects.filter(workspace=workspace)
            if data["search"]:
                objects = objects.filter(Q(name__icontains=data["search"]) | Q(identifier__icontains=data["search"]))
        if data["assigned_only"] or data["assignment"] != "all":
            if kind == "workspace":
                assigned = WorkspaceMember.objects.filter(
                    member=target, is_active=True, has_workspace_access=True
                ).values("workspace_id")
            else:
                assigned = ProjectMember.objects.filter(member=target, is_active=True).values("project_id")
            objects = (
                objects.exclude(id__in=assigned)
                if data["assignment"] == "unassigned"
                else objects.filter(id__in=assigned)
            )
        count = objects.count()
        offset = (data["page"] - 1) * data["per_page"]
        response = Response(
            {
                "results": [
                    scope_row(kind, obj, target)
                    for obj in objects.order_by("name", "id")[offset : offset + data["per_page"]]
                ],
                "count": count,
                "page": data["page"],
                "per_page": data["per_page"],
                "next": data["page"] + 1 if offset + data["per_page"] < count else None,
                "previous": data["page"] - 1 if data["page"] > 1 else None,
                "is_administrator": is_administrator(target),
            }
        )
        response["Cache-Control"] = "no-store"
        return response

    @transaction.atomic
    def post(self, request, user_id):
        target = self.target(request, user_id, lock=True)
        if is_administrator(target):
            raise ValidationError("管理员自动管理全部工作空间和项目；如需限制访问，请先取消管理员身份。")
        parser = ScopeChanges(data=request.data)
        parser.is_valid(raise_exception=True)
        changes = parser.validated_data["changes"]
        workspace_ids = {row["id"] for row in changes if row["kind"] == "workspace"}
        project_ids = {row["id"] for row in changes if row["kind"] == "project"}
        workspace_ids.update(Project.objects.filter(id__in=project_ids).values_list("workspace_id", flat=True))
        list(Workspace.objects.select_for_update().filter(id__in=workspace_ids).order_by("id"))
        list(
            Project.objects.select_for_update()
            .filter(Q(id__in=project_ids) | Q(workspace_id__in=workspace_ids))
            .order_by("id")
        )
        prepared = []
        # Validate the entire visible snapshot before any writes. Lock scopes in stable order.
        for data in sorted(changes, key=lambda row: (row["kind"], str(row["id"]))):
            model = Workspace if data["kind"] == "workspace" else Project
            filters = {} if model is Workspace else {"archived_at__isnull": True}
            obj = get_object_or_404(model.objects.select_for_update(), pk=data["id"], **filters)
            if scope_row(data["kind"], obj, target)["revision"] != data["expected_revision"]:
                raise Conflict("人员权限已变化，请刷新后重新选择。")
            prepared.append((data, obj))
        for data, obj in sorted(prepared, key=lambda item: 0 if item[0]["kind"] == "workspace" else 1):
            role = int(data["access_role"])
            if data["kind"] == "workspace":
                self.save_workspace(request, target, obj, role, data.get("roles"))
            else:
                self.save_project(request, target, obj, role, data.get("roles"))
        return Response({"saved": len(changes), "user_id": str(target.id)})

    def save_workspace(self, request, target, workspace, role, roles=None):
        member = WorkspaceMember.objects.filter(workspace=workspace, member=target).first()
        if target.id == request.user.id and (role == 0 or role == 5):
            raise ValidationError({"workspace": "请使用退出工作空间操作调整自己的访问。"})
        if role:
            verify_source_grant(target)
        if role in {0, 5}:
            projects = Project.objects.filter(
                workspace=workspace,
                project_projectmember__member=target,
                project_projectmember__is_active=True,
                archived_at__isnull=True,
            ).distinct()
            for project in projects:
                validate_project_role_retention(project, target.id, [])
            for project in projects:
                before = ProjectMember.objects.get(project=project, member=target).role
                ProjectMember.objects.filter(project=project, member=target).update(
                    is_active=role != 0, **({"role": 5} if role == 5 else {})
                )
                audit_access(project, target, request.user, before, role)
        roles = list(roles if roles is not None else (member.business_roles if member else []))
        if role >= 15:
            from .models import BusinessRole

            for project in Project.objects.filter(workspace=workspace, archived_at__isnull=True):
                binding = BusinessRole.objects.filter(project=project, user=target).first()
                explicit = {binding.role, *(binding.additional_roles or [])} if binding else set()
                validate_project_role_retention(project, target.id, explicit | set(roles))
        if member:
            member.role = role or member.role
            member.is_active = role != 0
            member.has_workspace_access = role != 0
            member.save()
        elif role:
            member = WorkspaceMember.objects.create(
                workspace=workspace, member=target, role=role, has_workspace_access=True, created_by=request.user
            )
        if member and roles is not None:
            member.business_roles = roles if role >= 15 else []
            member.save(update_fields=["business_roles"])
            if role >= 15:
                for project in Project.objects.filter(workspace=workspace, archived_at__isnull=True):
                    project_member, created = ProjectMember.objects.get_or_create(
                        project=project, member=target, defaults={"role": 15, "is_active": True}
                    )
                    if not created and (not project_member.is_active or project_member.role < 15):
                        project_member.is_active = True
                        project_member.role = max(project_member.role, 15)
                        project_member.save()
        if member and role in {0, 5}:
            member.business_roles = []
            member.save(update_fields=["business_roles"])

    def save_project(self, request, target, project, role, roles):
        if roles and role < 15:
            raise ValidationError({"roles": "只读或未授权范围不能分配业务岗位。"})
        member = ProjectMember.objects.filter(project=project, member=target).first()
        workspace = WorkspaceMember.objects.filter(workspace=project.workspace, member=target, is_active=True).first()
        if target.id == request.user.id and role == 0:
            raise ValidationError({"project": "请使用退出项目操作调整自己的访问。"})
        if role:
            if not workspace:
                existing = WorkspaceMember.objects.filter(workspace=project.workspace, member=target).first()
                if existing:
                    raise ValidationError({"workspace": "工作空间成员已停用，请先处理停用状态。"})
                workspace = WorkspaceMember.objects.create(
                    workspace=project.workspace,
                    member=target,
                    role=15,
                    has_workspace_access=False,
                    created_by=request.user,
                )
            if role >= 15 and workspace.role < 15:
                raise ValidationError({"workspace": "工作空间只读成员不能授予可写项目访问。"})
            verify_source_grant(target, project)
        if role in {0, 5}:
            if workspace and workspace.has_workspace_access and workspace.role >= 15:
                raise ValidationError({"workspace": "项目访问继承自工作空间，请在工作空间成员中调整。"})
            validate_project_role_retention(project, target.id, [])
        before = member.role if member and member.is_active else 0
        if member:
            member.role = role or member.role
            member.is_active = role != 0
            member.save()
        elif role:
            member = ProjectMember.objects.create(project=project, member=target, role=role, created_by=request.user)
        if role >= 15 and not is_administrator(target):
            adapter = SimpleNamespace(
                project_id=project.id, workspace_slug=project.workspace.slug, request=request, project=lambda: project
            )
            if roles is not None:
                apply_project_roles(adapter, {"user_id": target.id, "roles": roles})
        audit_access(project, target, request.user, before, role)
        account = PlatformAccount.objects.filter(user=target, active=True).first()
        if account and role:
            if PlatformProject.objects.filter(
                project=project, source_instance=account.source_instance, active=True
            ).exists():
                PlatformIdentity.objects.update_or_create(
                    project=project,
                    source_instance=account.source_instance,
                    external_user_id=account.external_user_id,
                    defaults={"user": target, "active": True, "created_by": request.user},
                )
