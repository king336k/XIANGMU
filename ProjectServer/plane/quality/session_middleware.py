"""Revoke retired external browser sessions without contacting another platform."""

from django.contrib.auth import logout
from django.http import JsonResponse
from .models import PlatformAccount


class BridgeSessionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        external_session = any(
            request.session.get(key)
            for key in ("quality_data_account", "quality_data_access", "quality_bridge_identity")
        )
        external_user = request.user.is_authenticated and PlatformAccount.objects.filter(user=request.user).exists()
        if external_session or external_user or (request.user.is_authenticated and request.user.is_bot):
            logout(request)
            if request.path.startswith("/api/") and request.path != "/api/quality-auth/login/":
                return JsonResponse({"error": "请使用项目管理平台独立账号重新登录。"}, status=401)
        return self.get_response(request)
