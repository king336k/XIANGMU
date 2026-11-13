"""Workspace module responsibility is metadata, never a membership or role grant."""

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from plane.db.models import User, Workspace, ProjectMember, WorkspaceMember
from .models import ModuleCatalog, ModuleOwner, PlatformAccount
from .permissions import is_administrator, roles_for

DEFAULT_MODULES = {"daq": "DAQ", "teleop": "遥操"}


def module_options():
    catalog = {**DEFAULT_MODULES, **dict(ModuleCatalog.objects.values_list("key", "name"))}
    return [{"key": key, "name": name} for key, name in sorted(catalog.items())]


def module_record(key):
    if key in DEFAULT_MODULES:
        return ModuleCatalog.objects.get_or_create(key=key, defaults={"name": DEFAULT_MODULES[key]})[0]
    return get_object_or_404(ModuleCatalog, key=key)


def eligible_technician(project, user_id):
    return (
        User.objects.filter(pk=user_id, is_active=True, is_bot=False).exists()
        and not PlatformAccount.objects.filter(user_id=user_id).exists()
        and "TECHNICIAN" in roles_for(project.id, user_id)
    )


def eligible_pairs(workspace_ids, user_ids):
    """Batch directory eligibility; preserve the same active writable boundaries as roles_for."""
    workspace_members = {
        (row["workspace_id"], row["member_id"]): set(row["business_roles"] or [])
        for row in WorkspaceMember.objects.filter(
            workspace_id__in=workspace_ids,
            member_id__in=user_ids,
            member__is_active=True,
            member__is_bot=False,
            is_active=True,
            role__gte=15,
        ).values("workspace_id", "member_id", "business_roles")
    }
    from .models import BusinessRole

    duties = {
        (row.project_id, row.user_id): {row.role, *(row.additional_roles or [])}
        for row in BusinessRole.objects.filter(project__workspace_id__in=workspace_ids, user_id__in=user_ids)
    }
    external = set(PlatformAccount.objects.filter(user_id__in=user_ids).values_list("user_id", flat=True))
    result = set()
    for row in ProjectMember.objects.filter(
        project__workspace_id__in=workspace_ids,
        member_id__in=user_ids,
        project__archived_at__isnull=True,
        is_active=True,
        role__gte=15,
    ).values("project_id", "project__workspace_id", "member_id"):
        pair = (row["project__workspace_id"], row["member_id"])
        if (
            pair in workspace_members
            and row["member_id"] not in external
            and "TECHNICIAN" in (workspace_members[pair] | duties.get((row["project_id"], row["member_id"]), set()))
        ):
            result.add(pair)
    return result


def workspace_eligible(workspace_id, user_id):
    return (workspace_id, user_id) in eligible_pairs({workspace_id}, {user_id})


class StrictInput(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, dict) or set(data) - set(self.fields):
            raise ValidationError("含不支持的参数。")
        return super().to_internal_value(data)


class OwnerBinding(StrictInput):
    workspace_id = serializers.UUIDField()
    module_key = serializers.RegexField(r"^[a-z][a-z0-9_-]{0,63}$")


class OwnerInput(StrictInput):
    action = serializers.ChoiceField(choices=["module_owners"])
    user_id = serializers.UUIDField()
    bindings = OwnerBinding(many=True, max_length=100, allow_empty=True)


class ModuleInput(StrictInput):
    action = serializers.ChoiceField(choices=["create_module"])
    key = serializers.RegexField(r"^[a-z][a-z0-9_-]{0,63}$")
    name = serializers.CharField(max_length=120)


def binding_directory(users=None):
    rows = ModuleOwner.objects.select_related("module", "workspace", "user")
    if users is not None:
        rows = rows.filter(user_id__in=users)
    rows = list(rows.order_by("workspace_id", "module_id"))
    valid = eligible_pairs({row.workspace_id for row in rows}, {row.user_id for row in rows}) if rows else set()
    return rows, valid


def serialize_bindings(rows, valid):
    return [
        {
            "workspace_id": str(row.workspace_id),
            "workspace_name": row.workspace.name,
            "module_key": row.module_id,
            "module_name": row.module.name,
            "eligible": (row.workspace_id, row.user_id) in valid,
        }
        for row in rows
    ]


def user_bindings(user, workspace_ids=None):
    rows, valid = binding_directory([user.pk])
    if workspace_ids is not None:
        rows = [row for row in rows if row.workspace_id in workspace_ids]
    return serialize_bindings(rows, valid)


def owner_options(directory=None):
    rows, valid = directory if directory is not None else binding_directory()
    grouped = {}
    for row in rows:
        grouped.setdefault(row.workspace_id, {})[row.module_id] = {
            "user_id": str(row.user_id),
            "display_name": row.user.display_name,
            "eligible": (row.workspace_id, row.user_id) in valid,
        }
    catalog = module_options()
    return [
        {
            "workspace_id": str(workspace.id),
            "workspace_name": workspace.name,
            "modules": [
                {
                    **module,
                    **grouped.get(workspace.id, {}).get(
                        module["key"], {"user_id": None, "display_name": "", "eligible": False}
                    ),
                }
                for module in catalog
            ],
        }
        for workspace in Workspace.objects.order_by("name", "id")
    ]


@transaction.atomic
def replace_bindings(actor, user, bindings):
    if not is_administrator(actor):
        raise PermissionDenied("只有管理员可以配置模块负责人。")
    get_object_or_404(User.objects.select_for_update(), pk=user.pk, is_active=True, is_bot=False)
    if PlatformAccount.objects.filter(user=user).exists():
        raise ValidationError({"user_id": "请选择项目管理平台本地技术员。"})
    keys = [(str(row["workspace_id"]), row["module_key"]) for row in bindings]
    if len(keys) != len(set(keys)):
        raise ValidationError({"bindings": "同一工作区模块不能重复选择。"})
    workspace_ids = {row["workspace_id"] for row in bindings}
    workspace_ids.update(ModuleOwner.objects.filter(user=user).values_list("workspace_id", flat=True))
    # Serialize replacement across accounts, including the initial absent binding.
    list(Workspace.objects.select_for_update().filter(pk__in=workspace_ids).order_by("id"))
    prepared = []
    for row in bindings:
        workspace = get_object_or_404(Workspace, pk=row["workspace_id"])
        if not workspace_eligible(workspace.pk, user.pk):
            raise ValidationError(
                {"bindings": f"{workspace.name}中至少需要一个有效项目的技术员岗位，模块配置不会授予权限。"}
            )
        prepared.append((workspace, module_record(row["module_key"])))
    ModuleOwner.objects.filter(user=user).delete()
    for workspace, module in prepared:
        ModuleOwner.objects.update_or_create(
            workspace=workspace, module=module, defaults={"user": user, "created_by": actor}
        )
    return user_bindings(user)
