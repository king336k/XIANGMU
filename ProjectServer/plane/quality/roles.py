# SPDX-License-Identifier: AGPL-3.0-only
from django.db import transaction
from django.db.models import Q
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from plane.db.models import ProjectMember, WorkspaceMember
from .models import BusinessRole, BusinessRoleEvent, ProjectRolePolicy
from .permissions import (
    ROLE_NAMES,
    ROLE_CAPABILITIES,
    capable,
    strict,
    writable_member,
    roles_for,
    has_role,
    is_administrator,
    role_for,
)
from .views import QualityView, Conflict


class RoleInput(serializers.Serializer):
    user_id = serializers.UUIDField()
    role = serializers.ChoiceField(choices=list(ROLE_NAMES), required=False)
    roles = serializers.ListField(
        child=serializers.ChoiceField(choices=list(ROLE_NAMES)), required=False, allow_empty=True, max_length=4
    )


class PolicyInput(serializers.Serializer):
    enabled = serializers.BooleanField()


@transaction.atomic
def initialize_project_roles(project, actor):
    """Preserve existing project admins as managers; other members need explicit duties."""
    if strict(project.id):
        return
    admins = (
        ProjectMember.objects.filter(
            project=project,
            role=20,
            is_active=True,
            member__is_active=True,
            member__is_bot=False,
            member__member_workspace__workspace=project.workspace,
            member__member_workspace__is_active=True,
            member__member_workspace__role__gte=15,
        )
        .select_related("member")
        .distinct()
    )
    if not admins.exists():
        raise ValidationError({"role_policy": "请先设置本项目的有效负责人。"})
    for member in admins:
        binding, created = BusinessRole.objects.get_or_create(
            project=project,
            user=member.member,
            defaults={"role": "PROJECT_MANAGER", "additional_roles": [], "created_by": actor},
        )
        if created:
            BusinessRoleEvent.objects.create(
                project=project,
                user=member.member,
                created_by=actor,
                role="PROJECT_MANAGER",
                previous_role="",
                action="initialize",
            )
    ProjectRolePolicy.objects.update_or_create(project=project, defaults={"enabled": True})


def management(view):
    project_admin = ProjectMember.objects.filter(
        project_id=view.project_id, member=view.request.user, is_active=True, role=20
    ).exists()
    if not project_admin and not (
        strict(view.project_id) and capable(view.project_id, view.request.user.id, "manage_roles")
    ):
        raise PermissionDenied("只有管理员或项目经理可以管理业务角色。")


class RoleList(QualityView):
    def get(self, request, **kwargs):
        management(self)
        project = self.project()
        members = ProjectMember.objects.filter(project=project, is_active=True, member__is_active=True).select_related(
            "member"
        )
        results = []
        for member in members:
            duties = roles_for(project.id, member.member_id)
            if not duties:
                continue
            results.append(
                {
                    "user_id": str(member.member_id),
                    "name": member.member.display_name,
                    "role": role_for(project.id, member.member_id),
                    "roles": sorted(duties),
                    "is_administrator": "PLATFORM_ADMIN" in duties,
                    "capabilities": sorted(set().union(*(ROLE_CAPABILITIES[role] for role in duties))),
                }
            )
        return Response(
            {
                "enabled": strict(project.id),
                "roles": {role: name for role, name in ROLE_NAMES.items() if role != "PLATFORM_ADMIN"},
                "results": results,
            }
        )

    @transaction.atomic
    def post(self, request, **kwargs):
        management(self)
        data = self.input(RoleInput)
        return apply_project_roles(self, data)


def validate_project_role_retention(project, user_id, wanted):
    """Retain a writable manager when changing duties or removing access."""
    for role in roles_for(project.pk, user_id) - set(wanted):
        if strict(project.pk) and role in {"PLATFORM_ADMIN", "PROJECT_MANAGER"}:
            if role == "PROJECT_MANAGER" and "PLATFORM_ADMIN" in wanted:
                continue
            equivalent = [role, "PLATFORM_ADMIN"] if role == "PROJECT_MANAGER" else [role]
            replacements = BusinessRole.objects.filter(
                Q(role__in=equivalent)
                | Q(additional_roles__contains=[role])
                | (
                    Q(additional_roles__contains=["PLATFORM_ADMIN"])
                    if role == "PROJECT_MANAGER"
                    else Q(pk__isnull=True)
                ),
                project=project,
            ).exclude(user_id=user_id)
            administrators = ProjectMember.objects.filter(project=project, is_active=True).exclude(member_id=user_id)
            workspace_managers = (
                WorkspaceMember.objects.filter(
                    workspace=project.workspace,
                    is_active=True,
                    role__gte=15,
                    business_roles__contains=["PROJECT_MANAGER"],
                ).exclude(member_id=user_id)
                if role == "PROJECT_MANAGER"
                else WorkspaceMember.objects.none()
            )
            if (
                not any(
                    writable_member(project.pk, row.member_id, project.workspace.slug) for row in workspace_managers
                )
                and not any(writable_member(project.pk, row.user_id, project.workspace.slug) for row in replacements)
                and not any(
                    is_administrator(member.member_id)
                    and writable_member(project.pk, member.member_id, project.workspace.slug)
                    for member in administrators
                )
            ):
                raise ValidationError({"roles": "项目必须保留有效的管理员或项目经理。"})


def apply_project_roles(view, data):
    """Apply validated duties after the caller has authorized the management operation."""
    if not writable_member(view.project_id, data["user_id"], view.workspace_slug):
        raise ValidationError({"user_id": "请选择当前项目和工作区的有效成员。"})
    project = view.project()
    type(project).objects.select_for_update().get(pk=project.pk)
    wanted = list(dict.fromkeys(data.get("roles") or ([data["role"]] if data.get("role") else [])))
    if "PLATFORM_ADMIN" in wanted:
        raise PermissionDenied("管理员身份请在账号管理中统一授权，项目岗位不能授予管理员。")
    previous = roles_for(project.pk, data["user_id"])
    if is_administrator(data["user_id"]):
        raise PermissionDenied("管理员已具备全部业务职责，请在账号管理中调整管理员身份。")
    if (
        strict(project.pk)
        and not has_role(project.pk, view.request.user.id, "PLATFORM_ADMIN")
        and ("PLATFORM_ADMIN" in wanted or "PLATFORM_ADMIN" in previous)
    ):
        raise PermissionDenied("项目经理不能授予或调整平台管理身份。")
    inherited = (
        WorkspaceMember.objects.filter(
            workspace=project.workspace, member_id=data["user_id"], is_active=True, role__gte=15
        )
        .values_list("business_roles", flat=True)
        .first()
        or []
    )
    validate_project_role_retention(project, data["user_id"], set(wanted) | set(inherited))
    if not wanted:
        BusinessRole.objects.filter(project=project, user_id=data["user_id"]).delete()
        if previous:
            BusinessRoleEvent.objects.create(
                project=project,
                user_id=data["user_id"],
                created_by=view.request.user,
                previous_role="+".join(sorted(previous))[:32],
                role="",
                action="set_roles",
            )
        return Response({"user_id": str(data["user_id"]), "role": None, "roles": []})
    primary = wanted[0]
    binding, _ = BusinessRole.objects.update_or_create(
        project=project,
        user_id=data["user_id"],
        defaults={"role": primary, "additional_roles": wanted[1:], "created_by": view.request.user},
    )
    if previous != set(wanted):
        BusinessRoleEvent.objects.create(
            project=project,
            user_id=binding.user_id,
            created_by=view.request.user,
            previous_role="+".join(sorted(previous))[:32],
            role="+".join(wanted)[:32],
            action="set_roles",
        )
    return Response({"user_id": str(binding.user_id), "role": binding.role, "roles": wanted})


class RolePolicy(QualityView):
    @transaction.atomic
    def post(self, request, **kwargs):
        management(self)
        data = self.input(PolicyInput)
        if not is_administrator(request.user):
            raise PermissionDenied("只有管理员可以调整权限策略。")
        project = self.project()
        type(project).objects.select_for_update().get(pk=project.pk)
        policy, _ = ProjectRolePolicy.objects.get_or_create(project=project)
        if policy.enabled and not data["enabled"]:
            raise Conflict("业务角色权限启用后不能退回宽泛成员权限，请通过成员角色管理调整职责。")
        if data["enabled"]:
            for role in ["PROJECT_MANAGER"]:
                equivalent = [role, "PLATFORM_ADMIN"] if role == "PROJECT_MANAGER" else [role]
                candidates = BusinessRole.objects.filter(
                    Q(role__in=equivalent)
                    | Q(additional_roles__contains=[role])
                    | (
                        Q(additional_roles__contains=["PLATFORM_ADMIN"])
                        if role == "PROJECT_MANAGER"
                        else Q(pk__isnull=True)
                    ),
                    project=project,
                )
                if not any(writable_member(project.pk, row.user_id, self.workspace_slug) for row in candidates):
                    raise ValidationError({"enabled": "请先设置有效的项目经理，再启用业务权限。"})
        if policy.enabled != data["enabled"]:
            policy.enabled = data["enabled"]
            policy.save()
            BusinessRoleEvent.objects.create(
                project=project, created_by=request.user, action="enable" if policy.enabled else "disable"
            )
        return Response({"enabled": policy.enabled})
