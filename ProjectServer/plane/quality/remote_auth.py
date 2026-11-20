"""HTTP credential adapters for workstation and Agent callers."""

from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from django.utils import timezone
from .remote_access import digest, identity_key, permitted
from .remote_models import RemoteAgentRun
from .remote_exchange import authenticate_station


class ToolAuthentication(BaseAuthentication):
    def authenticate_header(self, request):
        return "Bearer"

    def authenticate(self, request):
        raw = request.headers.get("Authorization", "").removeprefix("Bearer ")
        run = (
            RemoteAgentRun.objects.select_related("owner", "workstation__agent__project__workspace")
            .filter(tool_credential_hash=digest(raw), status="running", expires_at__gt=timezone.now())
            .first()
            if raw.startswith("rr_")
            else None
        )
        if not run or not permitted(run.owner, run.workstation) or run.identity_key != identity_key(run.workstation):
            raise AuthenticationFailed("Agent工具会话无效。")
        return run.owner, run


class WorkstationAuthentication(BaseAuthentication):
    def authenticate_header(self, request):
        return "Bearer"

    def authenticate(self, request):
        raw = request.headers.get("Authorization", "").removeprefix("Bearer ")
        return authenticate_station(raw)
