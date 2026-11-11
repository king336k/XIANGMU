# SPDX-License-Identifier: AGPL-3.0-only
"""Original account authentication adapter; credentials are never imported."""

import json
import requests
from django.middleware.csrf import CsrfViewMiddleware
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from plane.app.views.base import BaseAPIView
from plane.authentication.rate_limit import AuthenticationThrottle
from plane.authentication.utils.login import user_login
from plane.license.models import InstanceConfiguration
from . import platform
from .connection_settings import read_connection
from .directory_bridge import directory_ready
from .models import PlatformIdentity, PlatformProject
from .permissions import writable_member, roles_for, has_role, strict, is_administrator
from .sso import same_origin


def upstream_login(config, username, password):
    # Reuse the exact source-origin validation used by administrator settings.
    from .connection_settings import ConnectionInput

    check = ConnectionInput(
        data={
            "source_instance": "login",
            "kind": "legacy_hub",
            "base_url": config.get("base_url", ""),
            "allow_private_http": config.get("allow_http_local", False),
        }
    )
    if not check.is_valid():
        raise platform.PlatformUnavailable("原账号服务地址尚未正确配置。")
    try:
        with requests.post(
            config["base_url"].rstrip("/") + "/api/auth/login",
            json={"username": username, "password": password},
            timeout=(3, 8),
            allow_redirects=False,
            stream=True,
        ) as response:
            if response.status_code in [400, 401, 403, 422]:
                raise AuthenticationFailed("原账号或密码无效，或账号已停用。")
            if response.status_code != 200:
                raise platform.PlatformUnavailable("原账号服务暂不可用。")
            raw = bytearray()
            for chunk in response.iter_content(8192):
                raw.extend(chunk)
                if len(raw) > 65536:
                    raise platform.PlatformUnavailable("原账号服务响应超过允许大小。")
        payload = json.loads(raw)
        data = payload.get("data") if isinstance(payload, dict) else None
        user = data.get("user") if isinstance(data, dict) else None
        token = data.get("token") if isinstance(data, dict) else None
        if (
            payload.get("code") != 1
            or not isinstance(user, dict)
            or type(user.get("id")) is not int
            or user["id"] <= 0
            or user.get("active") is not True
            or not isinstance(token, str)
            or not token.startswith("phs_")
        ):
            raise AuthenticationFailed("原账号登录核验失败。")
        # Native sessions never store the upstream bearer. Close this short-lived upstream login.
        try:
            with requests.post(
                config["base_url"].rstrip("/") + "/api/auth/logout",
                headers={"Authorization": "Bearer " + token},
                timeout=(3, 5),
                allow_redirects=False,
                stream=True,
            ):
                pass
        except requests.RequestException:
            pass
        return {"id": user["id"], "active": True}
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        raise platform.PlatformUnavailable("原账号核验暂不可用，请稍后重试。")


def verify_legacy_identity(identity, external_project_id=None):
    config = platform.configuration(identity.source_instance)
    if not config.get("login_enabled"):
        raise AuthenticationFailed("原账号登录已停用，请使用底座账号登录。")
    mappings = PlatformProject.objects.filter(
        project_id=identity.project_id, source_instance=identity.source_instance, active=True
    )
    if external_project_id is not None:
        mappings = mappings.filter(external_project_id=external_project_id)
    if not mappings.exists():
        raise AuthenticationFailed("原平台项目映射已失效。")
    mapping = mappings.order_by("external_project_id").first()
    if not mapping:
        raise AuthenticationFailed("原平台项目映射已失效。")
    found = None
    for page in range(1, 41):
        data = platform.fetch(identity.source_instance, "/api/admin/users", {"page": page, "size": 100})
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("items"), list)
            or len(data["items"]) > 100
            or type(data.get("total")) is not int
            or not 0 <= data["total"] <= 4000
            or data.get("page") != page
            or data.get("size") != 100
        ):
            raise platform.PlatformUnavailable("原平台身份目录不完整，未放行登录。")
        for user in data["items"]:
            if not isinstance(user, dict) or type(user.get("id")) is not int:
                raise platform.PlatformUnavailable("原平台身份目录格式无效。")
            if user["id"] == identity.external_user_id:
                found = user
                break
        if found or page * 100 >= data["total"]:
            break
        if not data["items"]:
            raise platform.PlatformUnavailable("原平台身份目录分页不完整。")
    if not found or found.get("active") is not True:
        raise AuthenticationFailed("原平台账号不存在或已停用。")
    memberships = found.get("projectMemberships")
    if not isinstance(memberships, list):
        raise platform.PlatformUnavailable("原平台项目权限信息缺失。")
    if (
        strict(identity.project_id)
        and has_role(identity.project_id, identity.user_id, "PLATFORM_ADMIN")
        and found.get("platformAdmin") is True
        and found.get("primaryRole") == "PLATFORM_ADMIN"
    ):
        return mapping
    duties = roles_for(identity.project_id, identity.user_id) if strict(identity.project_id) else set()
    expected = {"PROJECT_ADMIN" if role == "PROJECT_MANAGER" else role for role in duties}
    for candidate in mappings:
        membership = next(
            (
                item
                for item in memberships
                if isinstance(item, dict)
                and type(item.get("projectId")) is int
                and item["projectId"] == candidate.external_project_id
                and item.get("active") is True
            ),
            None,
        )
        if not membership:
            continue
        if strict(identity.project_id) and (
            not expected or not isinstance(membership.get("roles"), list) or not expected.issubset(membership["roles"])
        ):
            continue
        return candidate
    raise AuthenticationFailed("原平台项目权限或业务职责已撤销。")


class LoginThrottle(AuthenticationThrottle):
    scope = "quality_legacy_login"


class LoginInput(serializers.Serializer):
    source_instance = serializers.RegexField(r"^[a-zA-Z0-9_-]{1,80}$")
    username = serializers.CharField(max_length=64)
    password = serializers.CharField(max_length=256, trim_whitespace=False, write_only=True)
    project_id = serializers.UUIDField(required=False)


def approved(identity):
    return (
        identity.created_by_id
        and is_administrator(identity.created_by_id)
        and writable_member(identity.project_id, identity.user_id, identity.project.workspace.slug)
    )


class LegacySources(BaseAPIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, **kwargs):
        rows = []
        for key in InstanceConfiguration.objects.filter(key__startswith="QUALITY_SOURCE:").values_list(
            "key", flat=True
        ):
            name = key.split(":", 1)[1]
            config = read_connection(name)
            if (
                config
                and config.get("kind") == "legacy_hub"
                and config.get("login_enabled")
                and directory_ready(config)
            ):
                rows.append({"source_instance": name})
        response = Response({"sources": rows})
        response["Cache-Control"] = "no-store"
        return response


class LegacyLogin(BaseAPIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]

    def post(self, request, **kwargs):
        # The host's HTML CSRF failure view returns HTTP 200; this API must fail with 403.
        rejection = CsrfViewMiddleware(lambda value: None).process_view(request._request, lambda value: None, (), {})
        if rejection is not None:
            raise PermissionDenied("登录校验已失效，请刷新页面后重试。")
        same_origin(request)
        data = LoginInput(data=request.data)
        data.is_valid(raise_exception=True)
        data = data.validated_data
        config = read_connection(data["source_instance"])
        if (
            not config
            or config.get("kind") != "legacy_hub"
            or not config.get("login_enabled")
            or not directory_ready(config)
        ):
            raise platform.PlatformUnavailable("原账号登录尚未配置，请使用本地账号或联系管理员。")
        upstream = upstream_login(config, data["username"], data["password"])
        identity = resolve_legacy_identity(data["source_instance"], upstream, data.get("project_id"))
        return complete_legacy_login(request, identity)


def resolve_legacy_identity(source_instance, upstream, project_id=None):
    identities = PlatformIdentity.objects.select_related("user", "project__workspace").filter(
        source_instance=source_instance,
        external_user_id=upstream["id"],
        active=True,
        user__is_active=True,
        project__archived_at__isnull=True,
    )
    if project_id:
        identities = identities.filter(project_id=project_id)
    if identities.count() > 100:
        raise PermissionDenied("账号映射项目过多，请填写指定项目编号后登录。")
    candidates = [identity for identity in identities[:100] if approved(identity)]
    if not candidates or len({identity.user_id for identity in candidates}) != 1:
        raise AuthenticationFailed("原账号尚未由管理员完成唯一身份和项目权限映射。")
    identity = candidates[0]
    verify_legacy_identity(identity)
    return identity


def complete_legacy_login(request, identity):
    user_login(request._request, identity.user, is_app=True)
    request.session["quality_bridge_identity"] = str(identity.id)
    request.session.set_expiry(15 * 60)
    response = Response({"next": f"/{identity.project.workspace.slug}/projects/{identity.project_id}/issues/"})
    response["Cache-Control"] = "no-store"
    return response
