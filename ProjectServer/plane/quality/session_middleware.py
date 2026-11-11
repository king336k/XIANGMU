# SPDX-License-Identifier: AGPL-3.0-only
from django.contrib.auth import logout
from django.http import JsonResponse
from django.core.exceptions import ValidationError as DjangoValidationError
from .models import PlatformIdentity, PlatformAccount
from .permissions import writable_member, is_administrator
from . import platform
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied


class BridgeSessionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == "/auth/sign-out/":
            return self.get_response(request)
        if (
            request.user.is_authenticated
            and request.path in {"/auth/change-password/", "/auth/set-password/"}
            and request.method == "POST"
            and PlatformAccount.objects.filter(user=request.user).exists()
        ):
            return JsonResponse({"error": "此账号由数据管理平台维护，请在数据管理平台修改密码。"}, status=403)
        public_auth = {
            "/api/quality-auth/login/",
            "/auth/sign-in/",
            "/auth/get-csrf-token/",
            "/api/quality-auth/data-login/",
            "/api/quality-auth/data-sources/",
            "/api/quality-auth/legacy-login/",
            "/api/quality-auth/legacy-sources/",
        }
        if request.session.get("quality_data_account") and request.path not in public_auth:
            try:
                from .data_accounts import verify_account_session

                verify_account_session(request)
            except platform.PlatformUnavailable:
                return JsonResponse({"error": "数据平台身份核验暂不可用。"}, status=503)
            except (AuthenticationFailed, PermissionDenied, DjangoValidationError, ValueError):
                logout(request)
                return JsonResponse({"error": "数据平台账号或会话已失效，请重新登录。"}, status=401)
        marker = request.session.get("quality_bridge_identity")
        if marker and request.path not in public_auth:
            try:
                identity = (
                    PlatformIdentity.objects.select_related("project__workspace")
                    .filter(pk=marker, user=request.user, active=True, user__is_active=True)
                    .first()
                    if request.user.is_authenticated
                    else None
                )
                if (
                    not identity
                    or not identity.created_by_id
                    or not is_administrator(identity.created_by_id)
                    or not writable_member(identity.project_id, identity.user_id, identity.project.workspace.slug)
                ):
                    raise AuthenticationFailed("外部身份或项目权限已撤销，请重新登录。")
                platform.verify_identity(identity)
            except platform.PlatformUnavailable:
                return JsonResponse({"error": "身份核验服务暂不可用，请稍后重试。"}, status=503)
            except (AuthenticationFailed, ValueError, DjangoValidationError):
                logout(request)
                return JsonResponse({"error": "外部身份已失效，请重新登录。"}, status=401)
        return self.get_response(request)
