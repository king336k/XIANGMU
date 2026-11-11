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
from plane.license.models import Instance
from .models import PlatformAccount
from .sso import same_origin
from .legacy_login import LoginThrottle
from .views import Conflict


class LoginInput(serializers.Serializer):
    username = serializers.CharField(max_length=128)
    password = serializers.CharField(max_length=256, trim_whitespace=False, write_only=True)
    next_path = serializers.CharField(max_length=2000, allow_blank=True, default="")


def account_candidates(identifier):
    # Only independently managed local identities can establish a browser session.
    local = User.objects.filter(
        Q(username__iexact=identifier) | Q(email__iexact=identifier), is_active=True, is_bot=False
    ).exclude(id__in=PlatformAccount.objects.values("user_id"))
    return [{"kind": "local", "user": user} for user in local[:3] if user.has_usable_password()]


def password_matches(candidates, password):
    return [row for row in candidates if row["user"].check_password(password)]


def clear_auth_markers(request):
    for key in ("quality_data_account", "quality_data_access", "quality_bridge_identity"):
        request.session.pop(key, None)


class UnifiedLogin(BaseAPIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]

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
            raise Conflict("存在同名账号，请联系管理员核对登录名。")
        selected = matches[0]
        with transaction.atomic():
            clear_auth_markers(request)
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
