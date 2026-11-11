# SPDX-License-Identifier: AGPL-3.0-only
"""Resolve credentials server-side, never merge or prioritize independent same-name accounts."""

from django.db import transaction
from django.db.models import Q
from django.middleware.csrf import CsrfViewMiddleware
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from plane.app.views.base import BaseAPIView
from plane.authentication.adapter.error import AuthenticationException
from plane.authentication.provider.credentials.email import EmailProvider
from plane.authentication.utils.login import user_login
from plane.authentication.utils.redirection_path import get_redirection_path
from plane.authentication.utils.user_auth_workflow import post_user_auth_workflow
from plane.db.models import User
from plane.license.models import Instance, InstanceConfiguration
from . import data_accounts, legacy_login, platform
from .connection_settings import read_connection
from .directory_bridge import directory_ready
from .models import PlatformAccount, PlatformIdentity
from .sso import same_origin
from .views import Conflict


class LoginInput(serializers.Serializer):
    username = serializers.CharField(max_length=128)
    password = serializers.CharField(max_length=256, trim_whitespace=False, write_only=True)
    next_path = serializers.CharField(max_length=2000, allow_blank=True, default="")


def configured_sources():
    sources = []
    for row in InstanceConfiguration.objects.filter(key__startswith="QUALITY_SOURCE:"):
        name = row.key.split(":", 1)[1]
        config = read_connection(name) or {}
        if not config.get("login_enabled"):
            continue
        if config.get("kind") == "data_platform":
            sources.append((name, data_accounts.authority_config(name)))
        elif config.get("kind") == "legacy_hub" and directory_ready(config):
            sources.append((name, config))
    if len(sources) > 4:
        raise platform.PlatformUnavailable("账号来源配置过多，请联系管理员核对。")
    return sources


def account_candidates(identifier):
    sources = configured_sources()
    legacy_names = [name for name, config in sources if config["kind"] == "legacy_hub"]
    local = (
        User.objects.filter(Q(username__iexact=identifier) | Q(email__iexact=identifier))
        .exclude(id__in=PlatformAccount.objects.values("user_id"))
        .exclude(id__in=PlatformIdentity.objects.filter(source_instance__in=legacy_names).values("user_id"))
    )
    candidates = [
        {"kind": "local", "user": user}
        for user in local[:3]
        if user.is_active and not user.is_bot and user.has_usable_password()
    ]
    for name, config in sources:
        if config["kind"] == "data_platform":
            rows = platform.fetch(name, "/internal/issue-users")
        else:
            from .legacy_directory import read_directory

            rows = read_directory(name)
        if not isinstance(rows, list):
            raise platform.PlatformUnavailable("账号目录响应无效。")
        matched = [
            row
            for row in rows
            if isinstance(row, dict)
            and isinstance(row.get("username"), str)
            and row["username"].casefold() == identifier.casefold()
            and row.get("active") is True
        ]
        if len(matched) > 1:
            raise Conflict("账号名称存在冲突，请联系管理员核对。")
        if matched:
            person = matched[0]
            external_id = person.get("id") if config["kind"] == "data_platform" else person.get("external_user_id")
            if type(external_id) is not int or external_id <= 0:
                raise platform.PlatformUnavailable("账号目录响应无效。")
            candidates.append(
                {
                    "kind": config["kind"],
                    "source": name,
                    "config": config,
                    "external_id": external_id,
                    "username": person["username"],
                }
            )
    return candidates


def revoke_unused_tokens(matches):
    for match in matches:
        if match["kind"] == "data_platform":
            try:
                data_accounts.authority_request(match["config"], "/api/user/logout", "post", token=match["token"])
            except (AuthenticationFailed, PermissionDenied, platform.PlatformUnavailable):
                pass


def password_matches(candidates, password):
    matches = []
    for candidate in candidates:
        if candidate["kind"] == "local":
            if candidate["user"].check_password(password):
                matches.append(candidate)
            continue
        try:
            if candidate["kind"] == "data_platform":
                info, token = data_accounts.authenticate_upstream(candidate["config"], candidate["username"], password)
                if info["id"] != candidate["external_id"]:
                    raise AuthenticationFailed("账号身份不匹配。")
                existing = (
                    PlatformAccount.objects.select_related("user")
                    .filter(source_instance=candidate["source"], external_user_id=info["id"])
                    .first()
                )
                if existing and (not existing.active or not existing.user.is_active):
                    continue
                matches.append({**candidate, "info": info, "token": token})
            else:
                upstream = legacy_login.upstream_login(candidate["config"], candidate["username"], password)
                if upstream["id"] != candidate["external_id"]:
                    raise AuthenticationFailed("账号身份不匹配。")
                identity = legacy_login.resolve_legacy_identity(candidate["source"], upstream)
                matches.append({**candidate, "identity": identity})
        except (AuthenticationFailed, PermissionDenied):
            continue
        except platform.PlatformUnavailable:
            revoke_unused_tokens(matches)
            raise
    return matches


def clear_auth_markers(request):
    for key in ("quality_data_account", "quality_data_access", "quality_bridge_identity"):
        request.session.pop(key, None)


class UnifiedLogin(BaseAPIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [legacy_login.LoginThrottle]

    def post(self, request, **kwargs):
        if (
            CsrfViewMiddleware(lambda value: None).process_view(request._request, lambda value: None, (), {})
            is not None
        ):
            raise PermissionDenied("登录校验已失效，请刷新后重试。")
        same_origin(request)
        data = LoginInput(data=request.data)
        data.is_valid(raise_exception=True)
        data = data.validated_data
        if not Instance.objects.filter(is_setup_done=True).exists():
            raise PermissionDenied("平台尚未完成初始化。")
        matches = password_matches(account_candidates(data["username"]), data["password"])
        if not matches:
            raise AuthenticationFailed("用户名或密码不正确，或账号已停用。")
        if len(matches) != 1:
            revoke_unused_tokens(matches)
            raise Conflict("存在同名且密码相同的独立账号，请联系管理员设置唯一登录名。")
        selected = matches[0]
        with transaction.atomic():
            clear_auth_markers(request)
            if selected["kind"] == "data_platform":
                return data_accounts.complete_data_login(
                    request, selected["source"], selected["info"], selected["token"], selected["config"]
                )
            if selected["kind"] == "legacy_hub":
                return legacy_login.complete_legacy_login(request, selected["identity"])
            request._request.META.setdefault("HTTP_USER_AGENT", "")
            try:
                user = EmailProvider(
                    request=request._request,
                    key=selected["user"].email,
                    code=data["password"],
                    is_signup=False,
                    callback=post_user_auth_workflow,
                ).authenticate()
            except AuthenticationException:
                raise AuthenticationFailed("用户名或密码不正确，或账号登录已停用。")
            user_login(request._request, user, is_app=True)
            path = data["next_path"]
            if (
                not path.startswith("/")
                or path.startswith("//")
                or "\\" in path
                or any(ord(char) < 32 for char in path)
            ):
                path = "/" + get_redirection_path(user).lstrip("/")
            if not user.member_workspace.filter(is_active=True).exists():
                path = "/settings/profile/security/"
            response = Response({"next": path, "account_source": "local"})
            response["Cache-Control"] = "no-store"
            return response
