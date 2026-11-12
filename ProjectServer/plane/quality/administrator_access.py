"""Project/workspace membership projections of revocable global administrator authority."""

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import PermissionDenied
from plane.db.models import User, Workspace, Project, WorkspaceMember, ProjectMember
from .models import AdministratorAccessGrant
from .permissions import is_administrator


def synchronize_administrator_access(user):
    """Run before request permissions so native lists and APIs share the same authority."""
    if not user.is_authenticated:
        return
    if not user.is_active:
        raise PermissionDenied("账号已停用。")
    if not is_administrator(user):
        if AdministratorAccessGrant.objects.filter(user=user).exists():
            release_administrator_access(user)
        return
    scopes = [
        ("workspace", WorkspaceMember, "workspace_id", Workspace.objects.values_list("id", flat=True)),
        (
            "project",
            ProjectMember,
            "project_id",
            Project.objects.filter(workspace__deleted_at__isnull=True).values_list("id", flat=True),
        ),
    ]
    for kind, model, field, targets in scopes:
        targets = set(targets)
        rows = {getattr(row, field): row for row in model.objects.filter(member=user)}
        missing = targets - {key for key, row in rows.items() if row.is_active and row.role == 20}
        if missing:
            _grant(user, kind, model, field, missing)


@transaction.atomic
def _grant(user, kind, model, field, targets):
    # Serialize grants with revocation; recheck authority after obtaining the lock.
    User.objects.select_for_update().get(pk=user.pk)
    if not is_administrator(user):
        return
    for target in sorted(targets, key=str):
        row = model.objects.filter(member=user, **{field: target}).first()
        if row is None:
            row = model.all_objects.filter(member=user, **{field: target}).order_by("-deleted_at").first()
        if row and row.deleted_at is None and row.is_active and row.role == 20:
            continue
        original = (
            None
            if row is None
            else {
                "role": row.role,
                "is_active": row.is_active,
                "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
            }
        )
        if row is None:
            defaults = {field: target, "member": user, "role": 20, "is_active": True}
            if kind == "project":
                defaults["workspace_id"] = Project.objects.get(pk=target).workspace_id
            row = model.objects.create(**defaults)
        grant, _ = AdministratorAccessGrant.objects.get_or_create(
            user=user,
            scope=kind,
            target_id=target,
            defaults={"membership_id": row.pk, "previous_access": original},
        )
        if grant.membership_id != row.pk:
            grant.membership_id = row.pk
            grant.save(update_fields=["membership_id"])
        model.all_objects.filter(pk=row.pk).update(role=20, is_active=True, deleted_at=None)


@transaction.atomic
def release_administrator_access(user):
    """Remove only projected authority; preserve the person's original scope access."""
    User.objects.select_for_update().get(pk=user.pk)
    if is_administrator(user):
        return
    for grant in AdministratorAccessGrant.objects.select_for_update().filter(user=user).order_by("scope", "target_id"):
        model = WorkspaceMember if grant.scope == "workspace" else ProjectMember
        prior = grant.previous_access
        values = (
            {"role": 5, "is_active": False}
            if prior is None
            else {
                "role": prior["role"],
                "is_active": prior["is_active"],
                "deleted_at": parse_datetime(prior["deleted_at"]) if prior["deleted_at"] else None,
            }
        )
        model.all_objects.filter(pk=grant.membership_id, member=user).update(**values, updated_at=timezone.now())
        grant.delete()
