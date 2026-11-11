# SPDX-License-Identifier: AGPL-3.0-only
"""Apply an instance-approved, project-scoped account policy; local revocations stay revoked."""

from django.db import transaction
from plane.db.models import WorkspaceMember, ProjectMember
from .models import PlatformProject, PlatformIdentity, BusinessRole, BusinessRoleEvent
from . import platform
from .permissions import strict

DEFAULT_SOURCE_ROLES = {
    "Admin": "PLATFORM_ADMIN",
    "Manager": "PROJECT_MANAGER",
    "TeamLeader": "REPORTER",
    "Annotator": "REPORTER",
    "Auditor": "REPORTER",
    "Collector": "REPORTER",
}


@transaction.atomic
def provision_projects(account, info, config, fetch):
    if info.get("role") not in DEFAULT_SOURCE_ROLES:
        return
    # First login has one fixed mapping; later local duties are never overwritten.
    duty = DEFAULT_SOURCE_ROLES[info["role"]]
    if duty not in {"PLATFORM_ADMIN", "PROJECT_MANAGER", "TECHNICIAN", "REGRESSION_TESTER", "REPORTER"}:
        return
    if duty == "REPORTER" and info.get("role") not in {"TeamLeader", "Annotator", "Auditor", "Collector"}:
        return
    if duty == "PLATFORM_ADMIN" and info.get("role") != "Admin":
        return
    mappings = PlatformProject.objects.select_related("project__workspace").filter(
        source_instance=account.source_instance,
        active=True,
        project__archived_at__isnull=True,
        project__projectrolepolicy__enabled=True,
    )
    if not mappings.exists():
        return
    if not config.get("service_token"):
        raise platform.PlatformUnavailable("自动分配项目尚未配置权威权限核验。")
    data = fetch(config, f"/internal/issue-permissions/users/{account.external_user_id}", token=config["service_token"])
    rows = data.get("projects") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise platform.PlatformUnavailable("数据平台项目授权响应无效。")
    if duty == "PLATFORM_ADMIN" and data.get("administrator") is not True:
        return
    authorized = {row["id"] for row in rows if isinstance(row, dict) and type(row.get("id")) is int}
    for mapping in mappings.filter(external_project_id__in=authorized):
        project = mapping.project
        if not strict(project.id):
            continue
        workspace_member, _ = WorkspaceMember.objects.get_or_create(
            workspace=project.workspace,
            member=account.user,
            defaults={"role": 15, "is_active": True, "created_by_id": config["configured_by"]},
        )
        member, _ = ProjectMember.objects.get_or_create(
            project=project,
            member=account.user,
            defaults={
                "workspace": project.workspace,
                "role": 20 if duty == "PLATFORM_ADMIN" else 15,
                "is_active": True,
                "created_by_id": config["configured_by"],
            },
        )
        if not workspace_member.is_active or not member.is_active:
            continue
        identity, _ = PlatformIdentity.objects.get_or_create(
            project=project,
            source_instance=account.source_instance,
            external_user_id=account.external_user_id,
            defaults={"user": account.user, "created_by_id": config["configured_by"]},
        )
        if not identity.active or identity.user_id != account.user_id:
            continue
        role, created = BusinessRole.objects.get_or_create(
            project=project, user=account.user, defaults={"role": duty, "created_by_id": config["configured_by"]}
        )
        if created:
            BusinessRoleEvent.objects.create(
                project=project,
                user=account.user,
                role=duty,
                previous_role="",
                action="source_policy",
                created_by_id=config["configured_by"],
            )


@transaction.atomic
def provision_daq_collector(source_instance, project_id, external_user_id):
    """A signed DAQ request may link an authorized collector without a web login."""
    from rest_framework.exceptions import AuthenticationFailed
    from .data_accounts import read_connection, authority_config, authority_request, link_account

    stored = read_connection(source_instance)
    if not stored or stored.get("kind") != "data_platform":
        return None
    config = authority_config(source_instance)
    if not config.get("login_auto_provision") or config.get("login_role_map", {}).get("Collector") != "REPORTER":
        return None
    if PlatformIdentity.objects.filter(
        project_id=project_id, source_instance=source_instance, external_user_id=external_user_id
    ).exists():
        raise AuthenticationFailed("当前项目的来源身份已停用，不能自动恢复。")
    mappings = PlatformProject.objects.filter(
        project_id=project_id, source_instance=source_instance, active=True, project__archived_at__isnull=True
    )
    if not mappings.exists() or not strict(project_id):
        return None
    person = authority_request(config, f"/internal/issue-users/{external_user_id}", token=config.get("service_token"))
    permissions = authority_request(
        config, f"/internal/issue-permissions/users/{external_user_id}", token=config.get("service_token")
    )
    if (
        not isinstance(person, dict)
        or person.get("id") != external_user_id
        or person.get("active") is not True
        or person.get("role") != "Collector"
        or not isinstance(person.get("username"), str)
        or not person["username"].strip()
        or len(person["username"]) > 128
        or not isinstance(permissions, dict)
        or not any(
            isinstance(row, dict) and mappings.filter(external_project_id=row.get("id")).exists()
            for row in permissions.get("projects", [])
        )
    ):
        raise AuthenticationFailed("来源数采员或项目权限核验未通过。")
    account = link_account(source_instance, {**person, "status": "Active"}, config)
    provision_projects(account, {**person, "status": "Active"}, config, authority_request)
    return (
        PlatformIdentity.objects.filter(
            project_id=project_id,
            source_instance=source_instance,
            external_user_id=external_user_id,
            user=account.user,
            active=True,
        )
        .select_related("user")
        .first()
    )
