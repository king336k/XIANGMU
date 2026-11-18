# SPDX-License-Identifier: AGPL-3.0-only
import json
from uuid import uuid4

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
    profile_action = serializers.ChoiceField(choices=["save", "create", "activate"], default="save")
    profile_id = serializers.CharField(max_length=36, required=False)
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
        action = data["profile_action"]
        if action == "activate" and (
            not data.get("profile_id") or set(self.initial_data) - {"profile_action", "profile_id"}
        ):
            raise ValidationError({"profile_id": "切换模型时请仅指定已保存的模型配置。"})
        if action == "create" and (
            not data.get("model") or not data.get("base_url") or not data.get("api_key") or data["clear_key"]
        ):
            raise ValidationError({"api_key": "添加模型时请填写模型名称、接口地址及独立密钥。"})
        if data.get("embedding_mode") == "external":
            model = data.get(
                "embedding_model",
                assistant.model_option("KNOWLEDGE_EMBEDDING_MODEL", "", self.context.get("workspace_id")),
            )
            url = data.get(
                "embedding_base_url",
                assistant.model_option("KNOWLEDGE_EMBEDDING_BASE_URL", "", self.context.get("workspace_id")),
            )
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

    def workspace(self):
        return self.project().workspace

    def profiles(self):
        raw = assistant.model_option("KNOWLEDGE_MODEL_PROFILES", "", self.workspace().id)
        if raw:
            return json.loads(raw)
        config = assistant.provider_config(self.workspace().id)
        profile_id = str(self.workspace().id)
        return {
            "active": profile_id,
            "items": [
                {
                    "id": profile_id,
                    "model": config["model"],
                    "base_url": config["base_url"],
                    "api_key": config["api_key"] or "",
                }
            ],
        }

    def get(self, request, **kwargs):
        from .semantic_provider import public_status

        workspace = self.workspace()
        config = assistant.provider_config(workspace.id)
        from .semantic_provider import configuration

        semantic = public_status(configuration(workspace.id))
        profiles = self.profiles()
        return Response(
            {
                "semantic_enabled": semantic["enabled"],
                "embedding_mode": semantic["source"],
                "embedding_model": semantic["model"],
                "embedding_base_url": assistant.model_option(
                    "KNOWLEDGE_EMBEDDING_BASE_URL", "", workspace.id
                ),
                "embedding_key_present": bool(
                    assistant.model_option("KNOWLEDGE_EMBEDDING_API_KEY", "", workspace.id)
                ),
                "semantic": semantic,
                "configured": config["configured"],
                "model": config["model"],
                "base_url": config["base_url"],
                "key_present": bool(config["api_key"]),
                "active_profile_id": profiles["active"],
                "profiles": [
                    {
                        "id": row["id"],
                        "model": row["model"],
                        "base_url": row["base_url"],
                        "key_present": bool(row["api_key"]),
                    }
                    for row in profiles["items"]
                ],
                "can_configure": is_administrator(request.user),
                "scope": "当前工作区下所有项目共用此模型配置。",
                "workspace_id": str(workspace.id),
                "workspace_name": workspace.name,
            }
        )

    @transaction.atomic
    def patch(self, request, **kwargs):
        from plane.db.models import Workspace

        workspace = self.workspace()
        # Serialize additions/switches even before a profile registry exists.
        Workspace.objects.select_for_update().get(pk=workspace.id)
        parser = ModelInput(data=request.data, context={"workspace_id": workspace.id})
        parser.is_valid(raise_exception=True)
        data = parser.validated_data
        if data.get("api_key") and data["clear_key"]:
            raise ValidationError({"api_key": "不能同时填写和清除密钥。"})
        if data.get("embedding_api_key") and data["clear_embedding_key"]:
            raise ValidationError({"embedding_api_key": "不能同时填写和清除向量服务密钥。"})
        profiles = self.profiles()
        action = data["profile_action"]
        if action == "create":
            if len(profiles["items"]) >= 20:
                raise ValidationError({"profile_action": "最多保存20份模型配置。"})
            selected = {
                "id": str(uuid4()),
                "model": data["model"],
                "base_url": data["base_url"],
                "api_key": data["api_key"],
            }
            profiles["items"].append(selected)
            profiles["active"] = selected["id"]
        else:
            selected_id = data.get("profile_id", profiles["active"])
            selected = next((row for row in profiles["items"] if row["id"] == selected_id), None)
            if selected is None:
                raise ValidationError({"profile_id": "模型配置不存在，请刷新后重试。"})
            if action == "activate":
                if not assistant.valid_provider_url(selected["base_url"]):
                    raise ValidationError({"base_url": "该模型地址当前不在服务器允许列表中。"})
                profiles["active"] = selected["id"]
            else:
                if selected_id != profiles["active"] and set(request.data) - {
                    "profile_action",
                    "profile_id",
                    "model",
                    "base_url",
                    "api_key",
                    "clear_key",
                }:
                    raise ValidationError(
                        {"profile_id": "编辑未使用的模型时，仅可修改名称、接口地址和密钥。"}
                    )
                selected.update({name: data[name] for name in ["model", "base_url"] if name in data})
                if data.get("api_key") or data["clear_key"]:
                    selected["api_key"] = "" if data["clear_key"] else data["api_key"]
        # Keep the canonical active keys for all existing question/diagnostic consumers.
        active = next(row for row in profiles["items"] if row["id"] == profiles["active"])
        data.update({name: active[name] for name in ["model", "base_url", "api_key"]})
        data["clear_key"] = not bool(active["api_key"])
        updates = {}
        encrypted_profiles = encrypt_data(json.dumps(profiles))
        if not encrypted_profiles:
            raise ValidationError({"api_key": "密钥加密不可用，未保存配置。"})
        updates["KNOWLEDGE_MODEL_PROFILES"] = (encrypted_profiles, True)
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
                key=f"WS:{self.workspace().id}:{key}",
                defaults={"value": value, "category": "KNOWLEDGE", "is_encrypted": encrypted},
            )
        return self.get(request, **kwargs)


class WorkspaceModelPermission(ModelPermission):
    def has_permission(self, request, view):
        from plane.db.models import WorkspaceMember

        return bool(
            request.user.is_authenticated
            and is_administrator(request.user)
            and WorkspaceMember.objects.filter(
                workspace__slug=view.workspace_slug,
                member=request.user,
                is_active=True,
                **({} if request.method in SAFE_METHODS else {"role__gte": 15}),
            ).exists()
        )


class WorkspaceModelConfiguration(ModelConfiguration):
    permission_classes = [WorkspaceModelPermission]

    def workspace(self):
        from django.shortcuts import get_object_or_404
        from plane.db.models import Workspace

        return get_object_or_404(Workspace, slug=self.workspace_slug)
