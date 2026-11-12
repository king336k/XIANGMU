"""The account and native administration APIs share one atomic grant/revoke rule."""

import json
from uuid import uuid4
from django.db import transaction
from rest_framework.exceptions import PermissionDenied, ValidationError
from plane.db.models import User
from plane.license.models import Instance, InstanceAdmin, InstanceConfiguration
from .models import BusinessRole, BusinessRoleEvent
from .permissions import is_administrator


@transaction.atomic
def set_administrator(actor, target, enabled):
    instance = Instance.objects.select_for_update().first()
    if not instance:
        raise ValidationError({"administrator": "请先完成平台初始化。"})
    if not is_administrator(actor):
        raise PermissionDenied("只有管理员可以授予或取消管理员身份。")
    if type(enabled) is not bool or not target.is_active or target.is_bot:
        raise ValidationError({"administrator": "请选择有效账号和管理员状态。"})
    # Serialize native access projection and revocation on the same target lock.
    User.objects.select_for_update().get(pk=target.pk)
    previous = is_administrator(target)
    if enabled:
        InstanceAdmin.all_objects.update_or_create(
            instance=instance, user=target, defaults={"role": 20, "created_by": actor, "deleted_at": None}
        )
    else:
        if previous and not any(
            is_administrator(person)
            for person in User.objects.filter(is_active=True, is_bot=False).exclude(pk=target.pk)
        ):
            raise ValidationError({"administrator": "必须保留至少一名有效管理员。"})
        InstanceAdmin.objects.filter(user=target).delete()
        for row in BusinessRole.objects.filter(user=target):
            if "PLATFORM_ADMIN" not in {row.role, *(row.additional_roles or [])}:
                continue
            duties = [role for role in [row.role, *(row.additional_roles or [])] if role != "PLATFORM_ADMIN"] or [
                "PROJECT_MANAGER"
            ]
            row.role, row.additional_roles = duties[0], duties[1:]
            row.save()
            BusinessRoleEvent.objects.create(
                project=row.project,
                user=target,
                created_by=actor,
                role="+".join(duties)[:32],
                previous_role="PLATFORM_ADMIN",
                action="revoke_admin",
            )
    InstanceConfiguration.objects.update_or_create(
        key="QUALITY_ADMIN_OVERRIDE:" + str(target.id),
        defaults={"category": "QUALITY_ADMIN_AUTHORITY", "value": "true" if enabled else "false"},
    )
    if enabled:
        from .administrator_access import synchronize_administrator_access

        synchronize_administrator_access(target)
    else:
        from .administrator_access import release_administrator_access

        release_administrator_access(target)
    InstanceConfiguration.objects.create(
        key="QUALITY_ADMIN_AUDIT:" + str(uuid4()),
        category="QUALITY_ADMIN_AUDIT",
        value=json.dumps(
            {"actor_id": str(actor.id), "user_id": str(target.id), "previous": previous, "administrator": enabled}
        ),
    )
    return is_administrator(target)
