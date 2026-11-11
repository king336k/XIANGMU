# SPDX-License-Identifier: AGPL-3.0-only
import ipaddress
import json
import re
from uuid import uuid4
from urllib.parse import urlsplit
from pathlib import PurePosixPath
from django.conf import settings
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from django.db import transaction
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import BasePermission
from plane.license.models import Instance, InstanceConfiguration
from plane.license.utils.encryption import encrypt_data, decrypt_data
from plane.knowledge.configuration import ModelPermission
from .views import QualityView, Conflict
from .permissions import capable, is_administrator, writable_member

PREFIX = "QUALITY_SOURCE:"
DEFAULT_LOGIN_ROLES = {
    "Admin": "PLATFORM_ADMIN",
    "Manager": "PROJECT_MANAGER",
    "TeamLeader": "REPORTER",
    "Annotator": "REPORTER",
    "Auditor": "REPORTER",
    "Collector": "REPORTER",
}


def directory_configuration_enabled():
    return getattr(settings, "QUALITY_OTA_DIRECTORY_CONFIGURATION_ENABLED", False) is True


def read_connection(instance):
    row = InstanceConfiguration.objects.filter(key=PREFIX + instance).first()
    if row is None:
        return None
    try:
        return json.loads(decrypt_data(row.value) if row.is_encrypted else row.value)
    except (ValueError, TypeError):
        return None


class ConnectionInput(serializers.Serializer):
    source_instance = serializers.RegexField(r"^[a-zA-Z0-9_-]{1,80}$")
    kind = serializers.ChoiceField(choices=["data_platform", "legacy_hub", "ota", "feishu"])
    base_url = serializers.CharField(max_length=500)
    portal_url = serializers.CharField(max_length=500, allow_blank=True, default="")
    roots = serializers.ListField(
        child=serializers.CharField(max_length=512, trim_whitespace=False), min_length=1, max_length=20, required=False
    )
    expected_revision = serializers.IntegerField(min_value=0, required=False)
    bridge_key_id = serializers.RegexField(r"^[a-zA-Z0-9_.-]{1,80}$", allow_blank=True, default="")
    bridge_audience = serializers.CharField(max_length=120, allow_blank=True, default="")
    bridge_secret = serializers.CharField(max_length=4000, allow_blank=True, required=False, write_only=True)
    timezone = serializers.CharField(max_length=80, default="Asia/Shanghai")
    allow_private_http = serializers.BooleanField(default=False)
    service_token = serializers.CharField(max_length=4000, allow_blank=True, required=False, write_only=True)
    clear_token = serializers.BooleanField(default=False)
    login_enabled = serializers.BooleanField(default=False)
    login_auto_provision = serializers.BooleanField(default=False)
    login_role_map = serializers.DictField(
        child=serializers.ChoiceField(
            choices=["", "PLATFORM_ADMIN", "PROJECT_MANAGER", "TECHNICIAN", "REGRESSION_TESTER", "REPORTER"]
        ),
        default=dict,
    )
    directory_auth = serializers.ChoiceField(choices=["bearer", "trusted_v2"], default="bearer")
    directory_key_id = serializers.RegexField(r"^[a-zA-Z0-9_.-]{1,80}$", allow_blank=True, default="")
    directory_user_id = serializers.IntegerField(min_value=1, allow_null=True, default=None)
    directory_username = serializers.RegexField(r"^[a-zA-Z0-9_.@-]{1,64}$", allow_blank=True, default="")

    def validate_roots(self, roots):
        if not directory_configuration_enabled():
            raise ValidationError("安装包目录配置暂未启用。")
        normalized = []
        for value in roots:
            if (
                not value.startswith("/")
                or value.startswith("//")
                or "\\" in value
                or any(ord(char) < 32 or ord(char) == 127 for char in value)
                or any(part in {".", ".."} for part in value.split("/"))
                or str(PurePosixPath(value)) == "/"
            ):
                raise ValidationError("安装包目录须为绝对目录，不能使用根目录、相对段或控制字符。")
            normalized.append(str(PurePosixPath(value)))
        if len(set(normalized)) != len(normalized):
            raise ValidationError("安装包目录不能重复。")
        return normalized

    def validate(self, data):
        if data["kind"] == "ota" and directory_configuration_enabled() and "roots" not in data:
            raise ValidationError({"roots": "请填写1至20个安装包目录，每行一个绝对目录。"})
        if data["kind"] != "ota" and "roots" in data:
            raise ValidationError({"roots": "安装包目录仅用于外部OTA目录配置。"})
        if any(
            key not in {"Admin", "Manager", "TeamLeader", "Annotator", "Auditor", "Collector", "Pending"}
            for key in data["login_role_map"]
        ):
            raise ValidationError({"login_role_map": "数据平台角色无效。"})
        if data["login_role_map"].get("Pending"):
            raise ValidationError({"login_role_map": "待分配用户不能自动分配项目业务权限。"})
        if any(
            value == "REPORTER" and key not in {"TeamLeader", "Annotator", "Auditor", "Collector"}
            for key, value in data["login_role_map"].items()
        ):
            raise ValidationError(
                {"login_role_map": "数采员策略适用于数据平台TeamLeader、Annotator、Auditor或Collector。"}
            )
        if any(value == "PLATFORM_ADMIN" and key != "Admin" for key, value in data["login_role_map"].items()):
            raise ValidationError({"login_role_map": "仅数据平台Admin可映射为管理员。"})
        if data["directory_auth"] == "trusted_v2" and (
            data["kind"] != "legacy_hub"
            or not data["directory_key_id"]
            or not data["directory_user_id"]
            or not data["directory_username"]
        ):
            raise ValidationError(
                {"directory_auth": "V2签名仅用于原45100只读目录，请填写服务器密钥编号和已映射的来源服务用户。"}
            )
        try:
            url = urlsplit(data["base_url"])
            if (
                url.scheme not in ["https", "http"]
                or not url.hostname
                or url.username
                or url.password
                or url.path not in ["", "/"]
                or url.query
                or url.fragment
                or url.hostname.lower() == "localhost"
            ):
                raise ValueError()
            try:
                address = ipaddress.ip_address(url.hostname)
            except ValueError:
                address = None
                if re.fullmatch(r"[0-9.:]+", url.hostname):
                    raise ValueError()
            if address and (
                address.is_loopback or address.is_link_local or address.is_unspecified or address.is_multicast
            ):
                raise ValueError()
            private = bool(address and address.is_private)
            if url.scheme == "http" and not (data["allow_private_http"] and private):
                raise ValueError()
            ZoneInfo(data["timezone"])
        except (ValueError, ZoneInfoNotFoundError):
            raise ValidationError(
                {
                    "base_url": (
                        "请使用不含凭据的HTTP(S)源站地址；HTTP仅限明确启用的私网IP。不允许回环、元数据地址或路径。"
                    )
                }
            )
        if data.get("portal_url"):
            portal = urlsplit(data["portal_url"])
            if (
                portal.scheme not in {"http", "https"}
                or not portal.hostname
                or portal.username
                or portal.password
                or portal.query
                or portal.fragment
            ):
                raise ValidationError({"portal_url": "请填写不含凭据的用户平台地址。"})
        data["base_url"] = data["base_url"].rstrip("/")
        return data


def connection_input(request):
    """Omitted advanced fields keep their stored values; blank secrets keep existing credentials."""
    payload = request.data.copy()
    name = payload.get("source_instance")
    if not name:
        prefix = str(payload.get("kind", "source")).replace("_", "-")
        name = f"{prefix}-{uuid4().hex[:12]}"
    name = ConnectionInput().fields["source_instance"].run_validation(name)
    old = read_connection(name) or {}
    fields = ConnectionInput().fields
    merged = {
        key: value for key, value in old.items() if key in fields and key not in {"service_token", "bridge_secret"}
    }
    merged.update(payload)
    merged["source_instance"] = name
    if old and payload.get("kind", old.get("kind")) != old.get("kind"):
        raise ValidationError({"kind": "已有连接不能更换服务类型，请新增连接。"})
    merged.setdefault("portal_url", payload.get("base_url", ""))
    merged.setdefault("login_role_map", DEFAULT_LOGIN_ROLES)
    if merged.get("kind") == "data_platform":
        merged.setdefault("bridge_key_id", name[:72] + "-bridge")
        merged.setdefault("bridge_audience", "plane-quality")
    if "allow_private_http" not in payload:
        try:
            address = urlsplit(str(merged.get("base_url", "")))
            private = ipaddress.ip_address(address.hostname or "").is_private
        except ValueError:
            private = False
        # Entering an explicit private HTTP URL supplies the same intent as the former checkbox.
        merged["allow_private_http"] = private and str(merged.get("base_url", "")).startswith("http://")
    serializer = ConnectionInput(data=merged)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data, old


class ConnectionSettings(QualityView):
    permission_classes = [ModelPermission]

    def get(self, request, **kwargs):
        if not is_administrator(request.user):
            return Response(
                {
                    "can_configure": False,
                    "results": [],
                    "notice": "全平台来源连接由管理员配置，项目映射不包含凭据。",
                }
            )
        rows = []
        for row in InstanceConfiguration.objects.filter(key__startswith=PREFIX):
            config = read_connection(row.key[len(PREFIX) :])
            if config is None:
                continue
            rows.append(
                {
                    "source_instance": row.key[len(PREFIX) :],
                    "kind": config.get("kind"),
                    "base_url": config.get("base_url"),
                    "portal_url": config.get("portal_url", ""),
                    **(
                        {"roots": config.get("roots", []), "revision": config.get("revision", 0)}
                        if config.get("kind") == "ota" and directory_configuration_enabled()
                        else {}
                    ),
                    "bridge_key_id": config.get("bridge_key_id", ""),
                    "bridge_audience": config.get("bridge_audience", ""),
                    "bridge_secret_present": bool(config.get("bridge_secret")),
                    "timezone": config.get("timezone"),
                    "allow_private_http": bool(config.get("allow_http_local")),
                    "token_present": bool(config.get("service_token")),
                    "login_enabled": bool(config.get("login_enabled")),
                    "login_auto_provision": bool(config.get("login_auto_provision")),
                    "login_role_map": config.get("login_role_map", {}),
                    "directory_auth": config.get("directory_auth", "bearer"),
                    "directory_key_id": config.get("directory_key_id", ""),
                    "directory_user_id": config.get("directory_user_id"),
                    "directory_username": config.get("directory_username", ""),
                }
            )
        return Response(
            {"can_configure": True, "ota_directories_enabled": directory_configuration_enabled(), "results": rows}
        )

    @transaction.atomic
    def post(self, request, **kwargs):
        data, old = connection_input(request)
        name = data.pop("source_instance")
        token = data.pop("service_token", None)
        clear = data.pop("clear_token")
        expected = data.pop("expected_revision", 0)
        if data["kind"] == "ota" and directory_configuration_enabled():
            # Serialize first creation too: a missing configuration row cannot itself be locked.
            Instance.objects.select_for_update().order_by("id").first()
        if data["kind"] == "ota" and directory_configuration_enabled():
            if old.get("revision", 0) != expected:
                raise Conflict("目录配置已被修改，请刷新后核对再保存。")
            data["revision"] = expected + 1
        data["bridge_secret"] = data.get("bridge_secret") or old.get("bridge_secret", "")
        if token and clear:
            raise ValidationError({"service_token": "不能同时清除和填写凭据。"})
        data["configured_by"] = str(request.user.id)
        data["service_token"] = "" if clear else token or old.get("service_token", "")
        data["allowed_hosts"] = [urlsplit(data["base_url"]).hostname]
        data["allow_http_local"] = data.pop("allow_private_http")
        encrypted = encrypt_data(json.dumps(data, ensure_ascii=False))
        if not encrypted:
            raise ValidationError({"error": "加密配置不可用，未保存。"})
        InstanceConfiguration.objects.update_or_create(
            key=PREFIX + name, defaults={"value": encrypted, "is_encrypted": True, "category": "QUALITY_INTEGRATIONS"}
        )
        return Response(
            {
                "source_instance": name,
                "kind": data["kind"],
                "base_url": data["base_url"],
                "token_present": bool(data["service_token"]),
                **(
                    {"roots": data["roots"], "revision": data["revision"]}
                    if data["kind"] == "ota" and directory_configuration_enabled()
                    else {}
                ),
            },
            status=201,
        )


class GlobalConnectionPermission(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user.is_authenticated and is_administrator(request.user))


class GlobalConnectionSettings(ConnectionSettings):
    """Instance connection configuration has no project-selection prerequisite."""

    permission_classes = [GlobalConnectionPermission]


class FeishuConnectionQuery(serializers.Serializer):
    page = serializers.IntegerField(min_value=1, default=1)
    per_page = serializers.IntegerField(min_value=1, max_value=50, default=20)
    search = serializers.CharField(max_length=80, allow_blank=True, default="")


class FeishuConnectionOptions(QualityView):
    """Read-only connection identifiers for authorized document importers."""

    def get(self, request, **kwargs):
        if not writable_member(self.project_id, request.user.id, self.workspace_slug) or not (
            capable(self.project_id, request.user.id, "knowledge_edit")
            or capable(self.project_id, request.user.id, "manage_test")
        ):
            raise PermissionDenied("当前业务角色不允许导入文档。")
        query = FeishuConnectionQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        page, page_size = query.validated_data["page"], query.validated_data["per_page"]
        search = query.validated_data["search"].casefold()
        rows = []
        keys = (
            InstanceConfiguration.objects.filter(key__startswith=PREFIX).order_by("key").values_list("key", flat=True)
        )
        for key in keys:
            name = key[len(PREFIX) :]
            if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", name) or search not in name.casefold():
                continue
            config = read_connection(name)
            if not isinstance(config, dict) or config.get("kind") != "feishu":
                continue
            token = config.get("service_token")
            if not isinstance(token, str) or not token.strip():
                continue
            base_url = config.get("base_url", "")
            if not isinstance(base_url, str) or any(
                char.isspace() or ord(char) < 32 or ord(char) == 127 for char in base_url
            ):
                continue
            try:
                origin = urlsplit(base_url)
                if (
                    origin.scheme != "https"
                    or origin.netloc != "open.feishu.cn"
                    or origin.path not in {"", "/"}
                    or origin.query
                    or origin.fragment
                ):
                    continue
            except (TypeError, ValueError, AttributeError):
                continue
            rows.append({"source_instance": name, "label": name})
        start = (page - 1) * page_size
        return Response(
            {
                "results": rows[start : start + page_size],
                "count": len(rows),
                "page": page,
                "page_size": page_size,
                "can_configure": is_administrator(request.user),
                "notice": "飞书连接由管理员统一配置；请选择已授权的连接并填写文档链接。",
            }
        )
