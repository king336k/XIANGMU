"""Project choices from an administrator-approved data-platform connection."""

from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from plane.license.models import InstanceConfiguration
from .connection_settings import PREFIX, read_connection
from .catalog import pages, INACTIVE
from .models import PlatformAccount
from .roles import management
from .views import QualityView
from . import platform
from .permissions import is_administrator


def connections():
    return {
        row.key[len(PREFIX) :]: read_connection(row.key[len(PREFIX) :])
        for row in InstanceConfiguration.objects.filter(key__startswith=PREFIX)
    }


class ProjectSourceOptions(QualityView):
    def get(self, request, **kwargs):
        management(self)
        available = {
            name: config
            for name, config in connections().items()
            if config
            and config.get("kind") == "data_platform"
            and config.get("service_token")
            and is_administrator(config.get("configured_by"))
        }
        sources = [{"id": name, "label": "数据管理平台 · " + name} for name in sorted(available)]
        source = request.query_params.get("source_instance", "")
        if not source:
            return Response({"sources": sources, "projects": []})
        if source not in available:
            raise ValidationError({"source_instance": "请选择已配置的数据管理平台。"})
        is_admin = is_administrator(request.user)
        account = PlatformAccount.objects.filter(user=request.user, source_instance=source, active=True).first()
        if not is_admin and not account:
            raise PermissionDenied("需由管理员关联，或使用已获得数据平台项目授权的账号。")
        rows, _ = pages(source, "/internal/issue-integration/catalog/projects")
        allowed = None
        if not is_admin:
            permissions = platform.fetch(source, f"/internal/issue-permissions/users/{account.external_user_id}")
            items = permissions.get("projects") if isinstance(permissions, dict) else None
            if not isinstance(items, list):
                raise platform.PlatformUnavailable()
            allowed = {item.get("id") for item in items if isinstance(item, dict)}
        projects = [
            {"id": row["id"], "name": row["name"], "status": row.get("status", "")}
            for row in rows
            if row.get("status", "").upper() not in INACTIVE and (allowed is None or row["id"] in allowed)
        ]
        return Response({"sources": sources, "projects": projects})
