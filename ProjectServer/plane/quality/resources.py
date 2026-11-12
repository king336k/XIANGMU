# SPDX-License-Identifier: AGPL-3.0-only
"""Field observations use existing identities and never create trusted test results."""

import hashlib
import hmac
import json
import math
import re
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from .authorship import AuthoredRecordSerializer
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from .models import FieldAgent, TelemetrySnapshot
from .views import QualityView, Conflict
from .daq import DaqView
from .permissions import writable_member, capable
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from .identity import PlatformBridgeAuthentication
from plane.authentication.session import BaseSessionAuthentication
from .data_regression import manager
from plane.knowledge.retrieval import scan_content


AGENT_ONLINE_SECONDS = 90


class SnapshotSerializer(serializers.ModelSerializer):
    trusted_as_test_result = serializers.SerializerMethodField()

    def get_trusted_as_test_result(self, obj):
        return False

    class Meta:
        model = TelemetrySnapshot
        fields = [
            "id",
            "agent_id",
            "snapshot",
            "review_status",
            "review_note",
            "reviewed_at",
            "created_at",
            "trusted_as_test_result",
        ]


class AgentSerializer(AuthoredRecordSerializer):
    latest_snapshot = serializers.SerializerMethodField()
    owner_name = serializers.CharField(source="owner.display_name", default="成员")
    credential_present = serializers.SerializerMethodField()

    def get_credential_present(self, obj):
        return bool(obj.credential_hash and obj.credential_expires_at and obj.credential_expires_at > timezone.now())

    online = serializers.SerializerMethodField()

    def get_online(self, obj):
        return bool(
            obj.enabled
            and obj.last_seen_at
            and (timezone.now() - obj.last_seen_at).total_seconds() < AGENT_ONLINE_SECONDS
        )

    def get_latest_snapshot(self, obj):
        row = obj.snapshots.first()
        return SnapshotSerializer(row).data if row else None

    class Meta:
        model = FieldAgent
        fields = [
            "id",
            "name",
            "owner_id",
            "owner_name",
            "source_instance",
            "enabled",
            "online",
            "edit_version",
            "last_seen_at",
            "credential_present",
            "credential_expires_at",
            "latest_snapshot",
        ]


class AgentInput(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    owner_id = serializers.UUIDField()
    source_instance = serializers.CharField(max_length=120, allow_blank=True, default="")
    enabled = serializers.BooleanField(required=False)
    expected_version = serializers.IntegerField(min_value=1, required=False)


class FieldAgents(QualityView):
    def get(self, request, **kwargs):
        return self.listing(FieldAgent.objects.filter(project=self.project()).select_related("owner"), AgentSerializer)

    @transaction.atomic
    def post(self, request, **kwargs):
        if not manager(self.project_id, request.user):
            raise PermissionDenied("现场采集资源由项目经理管理。")
        data = self.input(AgentInput)
        data.pop("expected_version", None)
        self.validate_assignee(data["owner_id"])
        row = FieldAgent.objects.create(project=self.project(), created_by=request.user, **data)
        return Response(AgentSerializer(row).data, status=201)


class FieldAgentDetail(QualityView):
    def get(self, request, pk, **kwargs):
        return Response(AgentSerializer(self.obj(FieldAgent, pk)).data)

    @transaction.atomic
    def patch(self, request, pk, **kwargs):
        if not manager(self.project_id, request.user):
            raise PermissionDenied("现场采集资源由项目经理管理。")
        data = self.input(AgentInput, partial=True)
        row = get_object_or_404(FieldAgent.objects.select_for_update(), pk=pk, project_id=self.project_id)
        if data.pop("expected_version", None) != row.edit_version:
            raise Conflict()
        if "owner_id" in data:
            self.validate_assignee(data["owner_id"])
        if data.get("enabled") is False or data.get("owner_id", row.owner_id) != row.owner_id:
            row.credential_hash = ""
            row.credential_expires_at = None
        for key, value in data.items():
            setattr(row, key, value)
        row.edit_version += 1
        row.save()
        return Response(AgentSerializer(row).data)


def validate_snapshot(value, depth=0):
    if depth > 8:
        raise ValidationError("快照嵌套层数过多。")
    if isinstance(value, dict):
        if len(value) > 200:
            raise ValidationError("快照字段过多。")
        for key, nested in value.items():
            normalized = re.sub(r"[^a-z]", "", key.lower())
            if any(word in str(key) for word in ["密码", "密钥", "令牌", "凭据"]):
                raise ValidationError("快照不可包含凭据字段。")
            if any(
                word in normalized
                for word in ["password", "secret", "token", "apikey", "credential", "authorization", "cookie"]
            ):
                raise ValidationError("快照不可包含凭据或认证字段。")
            validate_snapshot(nested, depth + 1)
    elif isinstance(value, list):
        if len(value) > 500:
            raise ValidationError("快照数组过长。")
        for nested in value:
            validate_snapshot(nested, depth + 1)
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValidationError("快照数字必须为有限值。")
    elif isinstance(value, str) and scan_content(value):
        raise ValidationError("快照包含疑似敏感信息，请先脱敏。")


class HeartbeatInput(serializers.Serializer):
    request_id = serializers.UUIDField()
    snapshot = serializers.JSONField()

    def validate_snapshot(self, value):
        if not isinstance(value, dict) or len(json.dumps(value, ensure_ascii=False).encode()) > 128 * 1024:
            raise ValidationError("现场快照必须为128KB以内的JSON对象。")
        validate_snapshot(value)
        return value


class FieldAgentAuthentication(BaseAuthentication):
    def authenticate(self, request):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer fa_"):
            return None
        raw = header[7:]
        if len(raw) > 120:
            raise AuthenticationFailed("现场代理凭据无效。")
        pk = request.parser_context["kwargs"].get("pk")
        project_id = request.parser_context["kwargs"].get("project_id")
        agent = (
            FieldAgent.objects.select_related("owner", "project__workspace")
            .filter(pk=pk, project_id=project_id, enabled=True, owner__is_active=True)
            .first()
        )
        if (
            not agent
            or not agent.credential_hash
            or not agent.credential_expires_at
            or agent.credential_expires_at <= timezone.now()
            or not hmac.compare_digest(agent.credential_hash, hashlib.sha256(raw.encode()).hexdigest())
            or not writable_member(agent.project_id, agent.owner_id, agent.project.workspace.slug)
            or not capable(agent.project_id, agent.owner_id, "report")
        ):
            raise AuthenticationFailed("现场代理凭据已失效或数采员权限已撤销。")
        if agent.source_instance:
            from .models import PlatformIdentity
            from .platform import verify_identity

            identity = PlatformIdentity.objects.filter(
                project_id=agent.project_id, user_id=agent.owner_id, source_instance=agent.source_instance, active=True
            ).first()
            if not identity:
                raise AuthenticationFailed("现场代理的外部身份映射无效。")
            verify_identity(identity)
        return agent.owner, {"agent_id": str(agent.id)}


class CredentialInput(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)


class FieldAgentCredential(QualityView):
    @transaction.atomic
    def post(self, request, pk, **kwargs):
        import secrets
        from datetime import timedelta

        if not manager(self.project_id, request.user):
            raise PermissionDenied("仅项目经理可设置现场资源接入凭据。")
        data = self.input(CredentialInput)
        row = get_object_or_404(FieldAgent.objects.select_for_update(), pk=pk, project_id=self.project_id)
        if row.edit_version != data["expected_version"]:
            raise Conflict()
        if not row.enabled:
            raise Conflict("请先启用资源。")
        token = "fa_" + secrets.token_urlsafe(32)
        row.credential_hash = hashlib.sha256(token.encode()).hexdigest()
        row.credential_expires_at = timezone.now() + timedelta(days=30)
        row.edit_version += 1
        row.save()
        response = Response(
            {
                "token": token,
                "expires_at": row.credential_expires_at,
                "scope": "仅此资源的脱敏心跳和快照上报，不能读取项目或修改业务。",
            },
            status=201,
        )
        response["Cache-Control"] = "no-store"
        return response


class FieldHeartbeat(DaqView):
    authentication_classes = [FieldAgentAuthentication, PlatformBridgeAuthentication, BaseSessionAuthentication]

    @transaction.atomic
    def post(self, request, pk, **kwargs):
        data = self.input(HeartbeatInput)
        agent = get_object_or_404(FieldAgent.objects.select_for_update(), pk=pk, project_id=self.project_id)
        self.validate_assignee(request.user.id)
        if not agent.enabled or agent.owner_id != request.user.id:
            raise PermissionDenied("仅有效资源登记的数采员可上报。")
        if (
            isinstance(request.auth, dict)
            and request.auth.get("source_instance")
            and request.auth["source_instance"] != agent.source_instance
        ):
            raise PermissionDenied("采集资源与可信来源实例不匹配。")
        digest = hashlib.sha256(
            json.dumps(data["snapshot"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        existing = agent.snapshots.filter(request_id=data["request_id"]).first()
        if existing:
            if existing.sha256 != digest:
                raise Conflict("同次上报编号对应不同快照。")
            return Response(SnapshotSerializer(existing).data)
        row = TelemetrySnapshot.objects.create(
            project=agent.project, created_by=request.user, agent=agent, sha256=digest, **data
        )
        agent.last_seen_at = timezone.now()
        agent.save(update_fields=["last_seen_at"])
        return Response(SnapshotSerializer(row).data, status=201)


class ReviewInput(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["accept", "reject"])
    note = serializers.CharField(max_length=4000)


class TelemetryReview(QualityView):
    @transaction.atomic
    def post(self, request, pk, **kwargs):
        if not manager(self.project_id, request.user):
            raise PermissionDenied("现场候选证据由项目经理复核。")
        data = self.input(ReviewInput)
        row = get_object_or_404(TelemetrySnapshot.objects.select_for_update(), pk=pk, project_id=self.project_id)
        target = {"accept": "accepted", "reject": "rejected"}[data["decision"]]
        if row.review_status != "pending":
            if row.review_status != target or row.review_note != data["note"]:
                raise Conflict("复核记录不可覆盖。")
            return Response(SnapshotSerializer(row).data)
        row.review_status = target
        row.review_note = data["note"]
        row.reviewed_by = request.user
        row.reviewed_at = timezone.now()
        row.save()
        return Response(SnapshotSerializer(row).data)


class FieldAgentClient(QualityView):
    def get(self, request, **kwargs):
        import io
        import zipfile
        from pathlib import Path
        from django.http import HttpResponse

        output = io.BytesIO()
        readme = (
            "# 现场观察客户端\n\n"
            "Python 3 标准库实现，不安装后台服务，不执行控制命令。\n"
            "先在平台登记资源与负责数采员，再设置运行身份环境变量。\n"
            "运行身份只使用此资源专用的 FIELD_AGENT_TOKEN 环境变量；"
            "它只允许向单一资源上报，30天有效，服务端仅保存摘要，停用或更换负责人会撤销。"
            "不应将平台桥接签名密钥下发到现场机器。\n"
            "本机联调可使用 PLANE_RUNTIME_COOKIE，现场运行使用资源专用限权凭据。\n"
            "示例：python3 field_agent_client.py --server https://your-platform.example --workspace workspace-slug "
            "--project PROJECT_UUID --agent AGENT_UUID --device DEVICE_LABEL --once\n"
            "可选 --daq-url http://127.0.0.1:8000/api/records/list 读取明确的本机DAQ端点；"
            "DAQ_RUNTIME_TOKEN 只从环境读取。无DAQ端点时只报机器资源观察，DAQ状态为not_checked。\n"
            "私网HTTP仅在明确指定--allow-private-http时使用。快照不自动成为测试通过依据。\n"
        )
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("field_agent_client.py", Path(__file__).with_name("field_agent_client.py").read_bytes())
            archive.writestr("README.md", readme)
        response = HttpResponse(output.getvalue(), content_type="application/zip")
        response["Content-Disposition"] = 'attachment; filename="native-field-observer.zip"'
        return response


class FieldAgentInstallPackage(QualityView):
    def get(self, request, pk, **kwargs):
        import io
        import zipfile
        from pathlib import Path
        from django.http import HttpResponse

        if not manager(self.project_id, request.user):
            raise PermissionDenied("现场部署包由项目经理为指定资源生成。")
        row = self.obj(FieldAgent, pk)
        if not row.enabled:
            raise Conflict("资源已停用，不能准备新的部署包。")
        config = {
            "server": request.build_absolute_uri("/").rstrip("/"),
            "workspace": self.workspace_slug,
            "project": str(self.project_id),
            "agent": str(row.id),
            "device": row.name,
        }
        bootstrap = (
            "import json, sys\nfrom pathlib import Path\nimport field_agent_client\n\n"
            "config=json.loads(Path(__file__).with_name('connection.json').read_text(encoding='utf-8'))\n"
            "args=[]\nfor name in ['server','workspace','project','agent','device']:\n"
            "    args.extend(['--'+name,str(config[name])])\n"
            "sys.argv=[sys.argv[0],*args,*sys.argv[1:]]\nfield_agent_client.main()\n"
        )
        readme = (
            "# 指定现场资源部署包\n\n仅包含Python标准库观察客户端、启动脚本和非敏感连接编号。"
            "不包含密码、会话、资源凭据或桥接签名密钥；不会自动安装后台服务或控制设备。\n\n"
            "1. 将整个目录放到负责数采员的工作站，确认Python 3可用。\n"
            "2. 检查connection.json的server地址。若当前地址是localhost，只适用于同机；"
            "跨设备接入须由部署管理员提供可达的HTTPS地址，本包不会更改服务器网络或开放端口。\n"
            "3. 由项目经理在平台的资源接入设置中准备此资源专用凭据，数采员通过环境变量FIELD_AGENT_TOKEN传入。"
            "禁止将主签名密钥或凭据写入本包。\n"
            "4. 执行 python3 run_observer.py --once 进行一次真实心跳。明确使用受信内网HTTP时须额外传入"
            " --allow-private-http。持续观察时去掉--once；Ctrl+C退出。\n"
            "可选 --daq-url 仅支持明确的本机DAQ状态端点；没有配置时DAQ状态为not_checked。\n\n"
            "下载部署包不代表已安装、已在线或测试通过；以平台收到的近期心跳与人工复核为准。"
        )
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("field_agent_client.py", Path(__file__).with_name("field_agent_client.py").read_bytes())
            archive.writestr("run_observer.py", bootstrap)
            archive.writestr("connection.json", json.dumps(config, ensure_ascii=False, indent=2))
            archive.writestr("README.md", readme)
        response = HttpResponse(output.getvalue(), content_type="application/zip")
        response["Content-Disposition"] = f'attachment; filename="field-observer-{row.id}.zip"'
        response["Cache-Control"] = "private, no-store"
        return response
