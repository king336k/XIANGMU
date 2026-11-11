# SPDX-License-Identifier: AGPL-3.0-only
"""Use the data platform as account authority; never import its passwords or grant roles by name."""

import hashlib
from uuid import uuid4
import requests
from django.db import transaction
from django.middleware.csrf import CsrfViewMiddleware
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from plane.app.views.base import BaseAPIView
from plane.authentication.utils.login import user_login
from plane.db.models import User, Profile, ProjectMember
from plane.license.models import InstanceConfiguration
from plane.license.utils.encryption import encrypt_data, decrypt_data
from .connection_settings import read_connection, ConnectionInput
from .legacy_login import LoginInput, LoginThrottle
from .models import PlatformAccount, PlatformIdentity, PlatformProject, BusinessRole
from .permissions import ROLE_NAMES, can_create_projects, is_administrator
from urllib.parse import quote
from . import platform
from .sso import same_origin


def authority_config(name):
    config = read_connection(name)
    if not config or config.get("kind") != "data_platform" or not config.get("login_enabled"):
        raise platform.PlatformUnavailable("数据平台账号登录尚未接通，请选择本地维护账号或联系管理员。")
    if not is_administrator(config.get("configured_by")):
        raise PermissionDenied("此账号来源尚未由管理员确认。")
    schema = ConnectionInput(
        data={
            "source_instance": name,
            "kind": "data_platform",
            "base_url": config.get("base_url", ""),
            "allow_private_http": config.get("allow_http_local", False),
        }
    )
    if not schema.is_valid():
        raise platform.PlatformUnavailable("数据平台源站地址无效。")
    return config


def authority_request(config, path, method="get", token=None, payload=None):
    try:
        with requests.request(
            method,
            config["base_url"].rstrip("/") + path,
            headers={"Authorization": "Bearer " + token} if token else {},
            json=payload,
            timeout=(3, 8),
            allow_redirects=False,
            stream=True,
        ) as response:
            if response.status_code in {401, 403}:
                raise AuthenticationFailed("数据平台账号、会话或项目权限已失效。")
            if response.status_code != 200:
                raise platform.PlatformUnavailable("数据平台暂不可用，请稍后重试。")
            raw = bytearray()
            for chunk in response.iter_content(8192):
                raw.extend(chunk)
                if len(raw) > 65536:
                    raise platform.PlatformUnavailable("数据平台响应超出允许大小。")
        import json

        value = json.loads(raw)
        if not isinstance(value, dict) or value.get("code") != 1 or "data" not in value:
            raise AuthenticationFailed("数据平台账号或密码无效，或账号已停用。")
        return value["data"]
    except (requests.RequestException, ValueError, TypeError):
        raise platform.PlatformUnavailable("数据平台身份核验暂不可用。")


def source_user(config, token, expected_id=None):
    data = authority_request(config, "/api/user/info", token=token)
    if (
        not isinstance(data, dict)
        or type(data.get("id")) is not int
        or data["id"] <= 0
        or data.get("status") != "Active"
        or not isinstance(data.get("username"), str)
        or not data["username"].strip()
        or len(data["username"]) > 128
        or (expected_id is not None and data["id"] != expected_id)
    ):
        raise AuthenticationFailed("数据平台账号已停用或身份不匹配。")
    return data


def authenticate_upstream(config, username, password):
    login = authority_request(config, "/api/user/login", "post", payload={"username": username, "password": password})
    token = login.get("accessToken") if isinstance(login, dict) else None
    user_id = login.get("userId") if isinstance(login, dict) else None
    if not isinstance(token, str) or not 16 <= len(token) <= 2048 or type(user_id) is not int:
        raise AuthenticationFailed("数据平台登录核验失败。")
    return source_user(config, token, user_id), token


def sync_account(account, info):
    account.source_username = info["username"]
    account.source_email = str(info.get("email") or "")[:255]
    account.source_role = str(info.get("role") or "")[:40]
    account.save(update_fields=["source_username", "source_email", "source_role"])
    if account.user.display_name != info["username"] or account.user.first_name != info["username"]:
        account.user.display_name = info["username"]
        account.user.first_name = info["username"]
        account.user.save(update_fields=["display_name", "first_name"])


def sync_administrator(account, info, config, permissions=None):
    """Remember verified source authority, never a browser role or a same-name local user."""
    approved = False
    if info.get("role") == "Admin" and config.get("service_token") and is_administrator(config.get("configured_by")):
        if permissions is None:
            permissions = authority_request(
                config, f"/internal/issue-permissions/users/{account.external_user_id}", token=config["service_token"]
            )
        approved = isinstance(permissions, dict) and permissions.get("administrator") is True
    InstanceConfiguration.objects.update_or_create(
        key="QUALITY_VERIFIED_ADMIN:" + str(account.id),
        defaults={"value": "true" if approved else "false", "category": "QUALITY_ADMIN_AUTHORITY"},
    )
    return approved


@transaction.atomic
def link_account(name, info, config):
    InstanceConfiguration.objects.select_for_update().filter(key="QUALITY_SOURCE:" + name).first()
    account = (
        PlatformAccount.objects.select_for_update().filter(source_instance=name, external_user_id=info["id"]).first()
    )
    if account:
        if not account.active or not account.user.is_active:
            raise AuthenticationFailed("当前项目平台账号已停用。")
        sync_account(account, info)
        return account
    if not config.get("login_auto_provision"):
        raise AuthenticationFailed("管理员尚未启用数据平台新账号自动关联。")
    # A source-controlled ID is canonical; matching display names or email addresses grant nothing.
    digest = hashlib.sha256(name.encode()).hexdigest()[:20]
    user = User(
        email=f"dp-{digest}-{info['id']}@accounts.invalid",
        username="dpa_" + uuid4().hex,
        display_name=info["username"],
        first_name=info["username"],
        is_active=True,
        is_password_autoset=True,
    )
    user.set_unusable_password()
    user.save()
    profile, _ = Profile.objects.get_or_create(user=user)
    profile.is_onboarded = True
    profile.is_navigation_tour_completed = True
    profile.language = "zh-CN"
    profile.onboarding_step = {key: True for key in profile.onboarding_step}
    profile.save()
    return PlatformAccount.objects.create(
        source_instance=name,
        external_user_id=info["id"],
        user=user,
        source_username=info["username"],
        source_email=str(info.get("email") or "")[:255],
        source_role=str(info.get("role") or "")[:40],
    )


def verify_account_session(request):
    marker = request.session.get("quality_data_account")
    if not marker:
        return None
    account = (
        PlatformAccount.objects.select_related("user")
        .filter(pk=marker, user=request.user, active=True, user__is_active=True)
        .first()
    )
    if not account:
        raise AuthenticationFailed("数据平台账号关联已停用。")
    config = authority_config(account.source_instance)
    try:
        token = decrypt_data(request.session.get("quality_data_access", ""))
    except (ValueError, TypeError):
        raise AuthenticationFailed("数据平台会话无效，请重新登录。")
    if not token:
        raise AuthenticationFailed("数据平台会话已过期，请重新登录。")
    info = source_user(config, token, account.external_user_id)
    sync_account(account, info)
    # Revoke an old source-admin marker before any fallible permission lookup.
    if info.get("role") != "Admin":
        sync_administrator(account, info, config)
    links = PlatformIdentity.objects.filter(user=account.user, source_instance=account.source_instance, active=True)
    memberships = ProjectMember.objects.filter(member=account.user, is_active=True)
    source_mappings = PlatformProject.objects.filter(
        source_instance=account.source_instance, project_id__in=memberships.values("project_id")
    )
    permissions = None
    if links.exists() or source_mappings.exists() or info.get("role") == "Admin":
        if not config.get("service_token"):
            raise platform.PlatformUnavailable("数据平台项目权限核验尚未配置。")
        permissions = authority_request(
            config, f"/internal/issue-permissions/users/{account.external_user_id}", token=config["service_token"]
        )
        projects = permissions.get("projects") if isinstance(permissions, dict) else None
        if not isinstance(projects, list):
            raise platform.PlatformUnavailable("数据平台项目权限响应无效。")
        allowed = {row["id"] for row in projects if isinstance(row, dict) and type(row.get("id")) is int}
        mapped = {
            mapping.project_id
            for mapping in source_mappings
            if mapping.active and mapping.external_project_id in allowed
        }
        revoked = {mapping.project_id for mapping in source_mappings} - mapped
        for link in links:
            if link.project_id not in mapped:
                revoked.add(link.project_id)
        if revoked:
            ProjectMember.objects.filter(project_id__in=revoked, member=account.user).update(is_active=False)
            links.filter(project_id__in=revoked).update(active=False)
    sync_administrator(account, info, config, permissions)
    return account


class DataPlatformLogin(BaseAPIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]

    def post(self, request, **kwargs):
        rejection = CsrfViewMiddleware(lambda value: None).process_view(request._request, lambda value: None, (), {})
        if rejection is not None:
            raise PermissionDenied("登录校验已失效，请刷新页面后重试。")
        same_origin(request)
        data = LoginInput(data=request.data)
        data.is_valid(raise_exception=True)
        data = data.validated_data
        config = authority_config(data["source_instance"])
        info, token = authenticate_upstream(config, data["username"], data["password"])
        return complete_data_login(request, data["source_instance"], info, token, config)


def complete_data_login(request, source_instance, info, token, config):
    account = link_account(source_instance, info, config)
    sync_administrator(account, info, config)
    from .account_projects import provision_projects

    provision_projects(account, info, config, authority_request)
    encrypted = encrypt_data(token)
    if not encrypted:
        raise platform.PlatformUnavailable("会话加密不可用，未建立登录。")
    user_login(request._request, account.user, is_app=True)
    request.session["quality_data_account"] = str(account.id)
    request.session["quality_data_access"] = encrypted
    request.session.set_expiry(15 * 60)
    # Unassigned users can sign in, but provisioning never adds workspace/project duties.
    next_path = "/settings/profile/security/"
    for identity in PlatformIdentity.objects.select_related("project__workspace").filter(
        user=account.user,
        source_instance=account.source_instance,
        external_user_id=account.external_user_id,
        active=True,
        project__archived_at__isnull=True,
    )[:100]:
        try:
            platform.verify_identity(identity, require_collector=False)
            from .permissions import roles_for

            duties = roles_for(identity.project_id, account.user_id)
            target = (
                "issues"
                if duties & {"PLATFORM_ADMIN", "PROJECT_MANAGER"}
                else "quality"
                if "REGRESSION_TESTER" in duties
                else "defects"
            )
            next_path = f"/{identity.project.workspace.slug}/p/{identity.project.identifier}/{target}/"
            break
        except AuthenticationFailed:
            continue
    if next_path == "/settings/profile/security/":
        from plane.db.models import Project
        from .permissions import roles_for, writable_member

        for project in Project.objects.filter(
            project_projectmember__member=account.user,
            project_projectmember__is_active=True,
            archived_at__isnull=True,
        ).exclude(id__in=PlatformProject.objects.filter(source_instance=account.source_instance).values("project_id"))[
            :100
        ]:
            if not writable_member(project.id, account.user_id, project.workspace.slug):
                continue
            duties = roles_for(project.id, account.user_id)
            target = (
                "issues"
                if duties & {"PLATFORM_ADMIN", "PROJECT_MANAGER"}
                else "quality"
                if "REGRESSION_TESTER" in duties
                else "defects"
            )
            next_path = f"/{project.workspace.slug}/p/{project.identifier}/{target}/"
            break
    response = Response({"next": next_path, "account_source": "data_platform"})
    response["Cache-Control"] = "no-store"
    return response


class DataPlatformSources(BaseAPIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, **kwargs):
        rows = []
        for key in InstanceConfiguration.objects.filter(key__startswith="QUALITY_SOURCE:").values_list(
            "key", flat=True
        ):
            name = key.split(":", 1)[1]
            try:
                authority_config(name)
            except (PermissionDenied, platform.PlatformUnavailable):
                continue
            rows.append({"source_instance": name, "kind": "data_platform", "label": "数据管理平台账号"})
        response = Response({"sources": rows})
        response["Cache-Control"] = "no-store"
        return response


class AccountSecurity(BaseAPIView):
    def get(self, request, **kwargs):
        account = PlatformAccount.objects.filter(user=request.user).first()
        identity = PlatformIdentity.objects.filter(user=request.user, active=True).first()
        if account:
            config = read_connection(account.source_instance) or {}
            data = {
                "source": "data_platform",
                "source_label": "数据管理平台账号",
                "username": account.source_username,
                "can_change_local_password": False,
                "portal_url": config.get("portal_url") or config.get("base_url", ""),
                "email": account.source_email,
                "platform_role": account.source_role,
                "status": "Active",
                "project_assigned": ProjectMember.objects.filter(member=request.user, is_active=True).exists(),
            }
        elif request.session.get("quality_bridge_identity") and identity:
            data = {
                "source": "external",
                "source_label": "外部平台账号",
                "username": request.user.display_name,
                "can_change_local_password": False,
                "portal_url": "",
                "project_assigned": True,
            }
        else:
            data = {
                "source": "local",
                "source_label": "项目管理平台账号",
                "username": request.user.username,
                "can_change_local_password": True,
                "portal_url": "",
                "project_assigned": ProjectMember.objects.filter(member=request.user, is_active=True).exists(),
            }
        data["display_name"] = data["username"]
        data["can_edit_identity"] = data["source"] == "local"
        data["can_create_api_tokens"] = data["source"] == "local"
        data["can_create_workspace"] = can_create_projects(request.user)
        if "email" not in data:
            email = request.user.email or ""
            data["email"] = "" if email.endswith("@accounts.invalid") else email
        data["project_duties"] = [
            {
                "project": row.project.name,
                "project_id": str(row.project_id),
                "identifier": row.project.identifier,
                "workspace": row.project.workspace.slug,
                "url": f"/{row.project.workspace.slug}/p/{quote(row.project.identifier, safe='')}/"
                + (
                    "issues/"
                    if {row.role, *(row.additional_roles or [])} & {"PLATFORM_ADMIN", "PROJECT_MANAGER", "TECHNICIAN"}
                    else "quality/"
                    if {row.role, *(row.additional_roles or [])} & {"REGRESSION_TESTER"}
                    else "defects/"
                ),
                "roles": [
                    ROLE_NAMES[role] for role in sorted({row.role, *(row.additional_roles or [])}) if role in ROLE_NAMES
                ],
            }
            for row in BusinessRole.objects.select_related("project__workspace").filter(
                user=request.user,
                project__archived_at__isnull=True,
                project__workspace__workspace_member__member=request.user,
                project__workspace__workspace_member__is_active=True,
                project_id__in=ProjectMember.objects.filter(member=request.user, is_active=True).values("project_id"),
            )
        ]
        response = Response(data)
        response["Cache-Control"] = "no-store"
        return response


def managed_registration():
    for key in InstanceConfiguration.objects.filter(key__startswith="QUALITY_SOURCE:").values_list("key", flat=True):
        config = read_connection(key.split(":", 1)[1]) or {}
        if config.get("kind") == "data_platform" and config.get("login_enabled"):
            return True
    return False


def configured_bridge_key(key_id):
    matches = []
    for row in InstanceConfiguration.objects.filter(key__startswith="QUALITY_SOURCE:"):
        name = row.key.split(":", 1)[1]
        config = read_connection(name) or {}
        if config.get("kind") != "data_platform" or config.get("bridge_key_id") != key_id:
            continue
        if not config.get("bridge_secret") or not config.get("bridge_audience"):
            continue
        if not is_administrator(config.get("configured_by")):
            continue
        matches.append(
            {"secret": config["bridge_secret"], "audience": config["bridge_audience"], "source_instance": name}
        )
    return matches[0] if len(matches) == 1 else None
