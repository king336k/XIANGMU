# SPDX-License-Identifier: AGPL-3.0-only
from django.db import transaction
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import SAFE_METHODS
from rest_framework.response import Response
from plane.license.models import InstanceConfiguration
from plane.license.utils.encryption import encrypt_data
from plane.quality.permissions import writable_member, is_administrator
from plane.quality.views import QualityView, QualityPermission
from . import assistant


class ModelPermission(QualityPermission):
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return super().has_permission(request, view)
        return (
            request.user.is_authenticated
            and writable_member(view.project_id, request.user.id, view.workspace_slug)
            and is_administrator(request.user)
        )


class ModelInput(serializers.Serializer):
    model = serializers.CharField(max_length=120, required=False)
    base_url = serializers.CharField(max_length=500, required=False)
    api_key = serializers.CharField(
        max_length=4000, allow_blank=True, required=False, write_only=True, trim_whitespace=False
    )
    clear_key = serializers.BooleanField(default=False)
    semantic_enabled = serializers.BooleanField(required=False)
    embedding_mode = serializers.ChoiceField(choices=["builtin", "external"], required=False)
    embedding_model = serializers.CharField(max_length=120, allow_blank=True, required=False)
    embedding_base_url = serializers.CharField(max_length=500, allow_blank=True, required=False)
    embedding_api_key = serializers.CharField(
        max_length=4000, allow_blank=True, required=False, write_only=True, trim_whitespace=False
    )
    clear_embedding_key = serializers.BooleanField(default=False)

    def validate(self, data):
        if data.get("embedding_mode") == "external":
            model = data.get("embedding_model", assistant.model_option("KNOWLEDGE_EMBEDDING_MODEL", ""))
            url = data.get("embedding_base_url", assistant.model_option("KNOWLEDGE_EMBEDDING_BASE_URL", ""))
            if not model or not url:
                raise ValidationError({"embedding_mode": "使用外部向量服务时请填写独立模型与接口地址。"})
        return data

    def validate_embedding_base_url(self, value):
        from .semantic_provider import valid_embedding_url

        if value and not valid_embedding_url(value):
            raise ValidationError("请使用服务器允许的向量模型接口地址。")
        return value.rstrip("/")

    def validate_base_url(self, value):
        if not assistant.valid_provider_url(value):
            raise ValidationError("请使用已列入服务器白名单的HTTPS地址或指定内网模型地址。")
        return value.rstrip("/")


class ModelConfiguration(QualityView):
    permission_classes = [ModelPermission]

    def get(self, request, **kwargs):
        from .semantic_provider import public_status

        config = assistant.provider_config()
        semantic = public_status()
        return Response(
            {
                "semantic_enabled": semantic["enabled"],
                "embedding_mode": semantic["source"],
                "embedding_model": semantic["model"],
                "embedding_base_url": assistant.model_option("KNOWLEDGE_EMBEDDING_BASE_URL", ""),
                "embedding_key_present": bool(assistant.model_option("KNOWLEDGE_EMBEDDING_API_KEY", "")),
                "semantic": semantic,
                "configured": config["configured"],
                "model": config["model"],
                "base_url": config["base_url"],
                "key_present": bool(config["api_key"]),
                "can_configure": is_administrator(request.user),
                "scope": "整个平台共用的模型连接，由管理员配置；项目权限仍独立校验。",
            }
        )

    @transaction.atomic
    def patch(self, request, **kwargs):
        data = self.input(ModelInput)
        if data.get("api_key") and data["clear_key"]:
            raise ValidationError({"api_key": "不能同时填写和清除密钥。"})
        if data.get("embedding_api_key") and data["clear_embedding_key"]:
            raise ValidationError({"embedding_api_key": "不能同时填写和清除向量服务密钥。"})
        updates = {}
        if "embedding_mode" in data:
            updates["KNOWLEDGE_EMBEDDING_MODE"] = (data["embedding_mode"], False)
        for name in ["model", "base_url"]:
            if name in data:
                updates["KNOWLEDGE_" + name.upper()] = (data[name], False)
        if "semantic_enabled" in data:
            updates["KNOWLEDGE_SEMANTIC_ENABLED"] = (str(data["semantic_enabled"]).lower(), False)
        if "embedding_model" in data:
            updates["KNOWLEDGE_EMBEDDING_MODEL"] = (data["embedding_model"], False)
        if "embedding_base_url" in data:
            updates["KNOWLEDGE_EMBEDDING_BASE_URL"] = (data["embedding_base_url"], False)
        if data.get("embedding_api_key") or data["clear_embedding_key"]:
            encrypted = encrypt_data(data["embedding_api_key"]) if data.get("embedding_api_key") else ""
            if data.get("embedding_api_key") and not encrypted:
                raise ValidationError({"embedding_api_key": "密钥加密不可用，未保存配置。"})
            updates["KNOWLEDGE_EMBEDDING_API_KEY"] = (encrypted, True)
        if data.get("api_key") or data["clear_key"]:
            encrypted = encrypt_data(data.get("api_key", "")) if not data["clear_key"] else ""
            if data.get("api_key") and not encrypted:
                raise ValidationError({"api_key": "密钥加密不可用，未保存配置。"})
            updates["KNOWLEDGE_API_KEY"] = (encrypted, True)
        for key, (value, encrypted) in updates.items():
            InstanceConfiguration.objects.update_or_create(
                key=key, defaults={"value": value, "category": "KNOWLEDGE", "is_encrypted": encrypted}
            )
        return self.get(request, **kwargs)
