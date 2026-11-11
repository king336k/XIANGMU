# SPDX-License-Identifier: AGPL-3.0-only
"""Browser-bound trusted identity exchange; never import legacy passwords or trust name matches."""

import secrets
import time
from urllib.parse import urlsplit
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, AuthenticationFailed
from plane.app.views.base import BaseAPIView
from plane.authentication.utils.login import user_login
from .identity import PlatformBridgeAuthentication
from .models import PlatformIdentity
from .views import QualityPermission
from .permissions import is_administrator


def same_origin(request):
    origin = request.headers.get("Origin")
    if origin:
        source = urlsplit(origin)
        if source.scheme != request.scheme or source.netloc != request.get_host() or source.path not in {"", "/"}:
            raise PermissionDenied("请从新版平台本身发起登录交换。")


class Challenge(BaseAPIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, **kwargs):
        same_origin(request)
        nonce = secrets.token_urlsafe(32)
        request.session["quality_sso_challenge"] = {
            "nonce": nonce,
            "issued_at": int(time.time()),
            "project_id": str(self.project_id),
        }
        response = Response(
            {
                "challenge": nonce,
                "expires_in": 60,
                "next": "由可信来源服务对同一浏览器的交换请求签名；不得在浏览器放置签名密钥。",
            }
        )
        response["Cache-Control"] = "no-store"
        return response


class ExchangeInput(serializers.Serializer):
    challenge = serializers.CharField(max_length=120)


class Exchange(BaseAPIView):
    authentication_classes = [PlatformBridgeAuthentication]
    permission_classes = [QualityPermission]

    def post(self, request, **kwargs):
        same_origin(request)
        schema = ExchangeInput(data=request.data)
        schema.is_valid(raise_exception=True)
        pending = request.session.pop("quality_sso_challenge", None)
        if (
            not isinstance(pending, dict)
            or pending.get("project_id") != str(self.project_id)
            or time.time() - pending.get("issued_at", 0) > 60
            or not secrets.compare_digest(pending.get("nonce", ""), schema.validated_data["challenge"])
        ):
            raise AuthenticationFailed("登录交换已过期或不属于当前浏览器，请重新发起。")
        identity = (
            PlatformIdentity.objects.select_related("user")
            .filter(
                project_id=self.project_id,
                user=request.user,
                source_instance=request.auth["source_instance"],
                external_user_id=request.auth["external_user_id"],
                active=True,
            )
            .first()
        )
        if not identity or not identity.created_by_id or not is_administrator(identity.created_by_id):
            raise PermissionDenied("全平台账号登录须由管理员确认身份映射；项目映射本身不授予全局登录权。")
        user_login(request._request, request.user, is_app=True)
        request.session["quality_bridge_identity"] = str(identity.id)
        request.session.set_expiry(15 * 60)
        response = Response(
            {
                "user_id": str(request.user.id),
                "workspace": self.workspace_slug,
                "project_id": str(self.project_id),
                "next": f"/{self.workspace_slug}/projects/{self.project_id}/issues/",
            }
        )
        response["Cache-Control"] = "no-store"
        return response
