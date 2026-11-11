# SPDX-License-Identifier: AGPL-3.0-only
"""Server-only, bounded calls to data-platform identity and task authorities."""

import ipaddress
from urllib.parse import urlsplit
import requests
from django.conf import settings
from rest_framework.exceptions import AuthenticationFailed, APIException
from .permissions import strict


class PlatformUnavailable(APIException):
    status_code = 503
    default_detail = "数据平台身份或任务核验暂不可用，请稍后重试。"


def configuration(instance):
    import json
    import os

    from .connection_settings import read_connection

    stored = read_connection(instance)
    if stored is not None:
        return stored
    configs = getattr(settings, "QUALITY_PLATFORM_SOURCES", None)
    if configs is None:
        try:
            configs = json.loads(os.environ.get("QUALITY_PLATFORM_SOURCES_JSON", "{}"))
        except ValueError:
            raise PlatformUnavailable()
    value = configs.get(instance)
    if not isinstance(value, dict):
        raise PlatformUnavailable()
    return value


def fetch(instance, path, params=None):
    config = configuration(instance)
    url = config.get("base_url", "").rstrip("/")
    parsed = urlsplit(url)
    if (
        parsed.scheme not in ["http", "https"]
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ["", "/"]
        or parsed.hostname not in config.get("allowed_hosts", [])
    ):
        raise PlatformUnavailable()
    if parsed.scheme == "http" and not config.get("allow_http_local", False):
        raise PlatformUnavailable()
    if parsed.scheme == "http":
        try:
            if not ipaddress.ip_address(parsed.hostname).is_private:
                raise PlatformUnavailable()
        except ValueError:
            raise PlatformUnavailable()
    token = config.get("service_token")
    if config.get("directory_auth") == "trusted_v2":
        from .directory_bridge import directory_headers

        headers = directory_headers(config, path, params)
    else:
        if not token:
            raise PlatformUnavailable()
        headers = {"Authorization": "Bearer " + token}
    try:
        with requests.get(
            url + path,
            params=params,
            headers=headers,
            timeout=(3, 8),
            allow_redirects=False,
            stream=True,
        ) as response:
            if response.status_code == 404:
                raise AuthenticationFailed("平台用户、任务或数据记录不存在。")
            if response.status_code != 200:
                raise PlatformUnavailable()
            raw = bytearray()
            for chunk in response.iter_content(65536):
                raw.extend(chunk)
                if len(raw) > 1024 * 1024:
                    raise PlatformUnavailable()
            import json

            payload = json.loads(raw)
            if payload.get("code") != 1 or "data" not in payload:
                raise PlatformUnavailable()
            return payload["data"]
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        raise PlatformUnavailable()


def verify_identity(identity, external_project_id=None, *, require_collector=True):
    try:
        config = configuration(identity.source_instance)
    except PlatformUnavailable:
        config = {}
    if config.get("kind") == "legacy_hub":
        from .legacy_login import verify_legacy_identity

        return verify_legacy_identity(identity, external_project_id)
    from .models import PlatformProject
    from .permissions import has_role

    mappings = PlatformProject.objects.filter(
        project_id=identity.project_id, source_instance=identity.source_instance, active=True
    )
    if external_project_id is not None:
        mappings = mappings.filter(external_project_id=external_project_id)
    if not mappings.exists():
        raise AuthenticationFailed("当前项目尚未完成数据平台映射。")
    user = fetch(identity.source_instance, f"/internal/issue-users/{identity.external_user_id}")
    permissions = fetch(identity.source_instance, f"/internal/issue-permissions/users/{identity.external_user_id}")
    if not isinstance(user, dict) or user.get("id") != identity.external_user_id or user.get("active") is not True:
        raise AuthenticationFailed("数据平台账号已停用或身份不匹配。")
    projects = permissions.get("projects") if isinstance(permissions, dict) else None
    if not isinstance(projects, list):
        raise PlatformUnavailable()
    allowed = {row.get("id") for row in projects if isinstance(row, dict)}
    mapping = mappings.filter(external_project_id__in=allowed).first()
    if not mapping:
        raise AuthenticationFailed("数据平台项目权限已撤销。")
    # Platform Collector is distinct from Hub REPORTER: both must be granted.
    if (
        require_collector
        and strict(identity.project_id)
        and has_role(identity.project_id, identity.user_id, "REPORTER")
        and user.get("role") != "Collector"
    ):
        raise AuthenticationFailed("当前数据平台项目未授予数采员职责。")
    return mapping


def verify_binding(binding):
    from .models import PlatformProject

    mappings = PlatformProject.objects.filter(
        project_id=binding.project_id, source_instance=binding.source_instance, active=True
    )
    if binding.external_project_id:
        mappings = mappings.filter(external_project_id=binding.external_project_id)
    if not mappings.exists():
        raise AuthenticationFailed("当前项目尚未完成数据平台映射。")
    context = fetch(
        binding.source_instance,
        f"/internal/issue-integration/tasks/{binding.platform_task_id}/context",
        {"sourceSessionId": binding.source_record_id},
    )
    if (
        not isinstance(context, dict)
        or context.get("taskId") != binding.platform_task_id
        or not mappings.filter(external_project_id=context.get("projectId")).exists()
        or context.get("sourceSessionId") != binding.source_record_id
        or str(context.get("dataPackageId")) != binding.package_id
    ):
        raise AuthenticationFailed("平台任务、Session或数据包归属已变更，请重新核对。")
    return context
