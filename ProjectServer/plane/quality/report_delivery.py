# SPDX-License-Identifier: AGPL-3.0-only
"""Explicit, previewed report delivery to a configured Feishu chat only."""

import hashlib
import json
from datetime import timedelta
from urllib.parse import urlsplit
import requests
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from .models import SavedReport, NotificationTarget, ReportDelivery, BusinessRole
from plane.db.models import ProjectMember, WorkspaceMember
from .permissions import writable_member
from .views import QualityView, Conflict
from .data_regression import manager
from .connection_settings import read_connection
from .platform import PlatformUnavailable
from .reports import conclusion_representation
from plane.knowledge.retrieval import scan_content


def require_manager(view):
    if not manager(view.project_id, view.request.user):
        raise PermissionDenied("报告投递与通知目标由项目经理操作。")


class TargetInput(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    source_instance = serializers.RegexField(r"^[a-zA-Z0-9_-]{1,80}$")
    chat_id = serializers.RegexField(r"^oc_[a-zA-Z0-9_-]{1,140}$")
    enabled = serializers.BooleanField(default=True)
    expected_version = serializers.IntegerField(min_value=1, required=False)


class TargetSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationTarget
        fields = ["id", "name", "source_instance", "chat_id", "enabled", "edit_version"]


class NotificationTargets(QualityView):
    def get(self, request, **kwargs):
        require_manager(self)
        return self.listing(NotificationTarget.objects.filter(project=self.project()), TargetSerializer)

    @transaction.atomic
    def post(self, request, **kwargs):
        require_manager(self)
        data = self.input(TargetInput)
        data.pop("expected_version", None)
        row = NotificationTarget.objects.create(project=self.project(), created_by=request.user, **data)
        return Response(TargetSerializer(row).data, status=201)


class NotificationTargetDetail(QualityView):
    @transaction.atomic
    def patch(self, request, pk, **kwargs):
        require_manager(self)
        data = self.input(TargetInput, partial=True)
        row = get_object_or_404(NotificationTarget.objects.select_for_update(), pk=pk, project_id=self.project_id)
        if data.pop("expected_version", None) != row.edit_version:
            raise Conflict()
        for key, value in data.items():
            setattr(row, key, value)
        row.edit_version += 1
        row.save()
        return Response(TargetSerializer(row).data)


def fingerprint(report):
    conclusion = getattr(report, "conclusion", None)
    return hashlib.sha256(
        json.dumps(
            {
                "name": report.name,
                "snapshot": report.snapshot,
                "conclusion": conclusion_representation(conclusion) if conclusion else None,
            },
            sort_keys=True,
            default=str,
            ensure_ascii=False,
        ).encode()
    ).hexdigest()


def report_text(report):
    summary = report.snapshot.get("summary", {})
    conclusion = getattr(report, "conclusion", None)
    text = "\n".join(
        [
            "测试报告：" + report.name,
            "项目：" + report.snapshot.get("project_name", report.project.name),
            "报告编号：" + str(report.id),
            "保存时间：" + report.created_at.isoformat(),
            " · ".join(
                title + " " + str(summary.get(key, 0))
                for key, title in [
                    ("total", "总用例"),
                    ("passed", "通过"),
                    ("failed", "失败"),
                    ("blocked", "阻塞"),
                    ("inconclusive", "无法判定"),
                    ("skipped", "跳过"),
                    ("pending", "未执行"),
                ]
            ),
            "经理结论："
            + (
                {"passed": "通过", "failed": "不通过", "blocked": "阻塞", "inconclusive": "无法判定"}[conclusion.result]
                + "\n"
                + conclusion.summary
                if conclusion
                else "尚未签署"
            ),
            "风险与后续：" + (conclusion.risks if conclusion else "请在平台核对完整报告与待办。"),
            "报告不代表发布准入；详细用例、附件与日志仅在平台按权限查看。",
        ]
    )
    if len(text.encode()) > 18000 or scan_content(text):
        raise ValidationError({"report": "报告摘要过长或包含疑似敏感信息，请先核对报告名称和经理结论。"})
    return text


class DeliverySerializer(serializers.ModelSerializer):
    target_name = serializers.SerializerMethodField()
    chat_id = serializers.SerializerMethodField()

    def get_target_name(self, obj):
        return obj.target_snapshot.get("name", "历史目标未保存")

    def get_chat_id(self, obj):
        return obj.target_snapshot.get("chat_id", "")

    class Meta:
        model = ReportDelivery
        fields = [
            "id",
            "target_name",
            "chat_id",
            "target_id",
            "text",
            "status",
            "attempts",
            "last_error",
            "sent_at",
            "created_at",
        ]


class PreviewInput(serializers.Serializer):
    target_id = serializers.UUIDField()
    request_id = serializers.UUIDField()
    expected_version = serializers.IntegerField(min_value=1)


class ReportDeliveries(QualityView):
    def get(self, request, pk, **kwargs):
        require_manager(self)
        report = self.obj(SavedReport, pk)
        return self.listing(report.deliveries.select_related("target"), DeliverySerializer)

    @transaction.atomic
    def post(self, request, pk, **kwargs):
        require_manager(self)
        data = self.input(PreviewInput)
        report = get_object_or_404(SavedReport.objects.select_for_update(), pk=pk, project_id=self.project_id)
        target = get_object_or_404(NotificationTarget, pk=data["target_id"], project_id=self.project_id, enabled=True)
        if data["expected_version"] != report.edit_version:
            raise Conflict()
        digest = fingerprint(report)
        old = ReportDelivery.objects.filter(project_id=self.project_id, request_id=data["request_id"]).first()
        if old:
            if (
                old.report_id != report.id
                or old.target_id != target.id
                or old.report_fingerprint != digest
                or old.target_version != target.edit_version
            ):
                raise Conflict()
            return Response(DeliverySerializer(old).data)
        row = ReportDelivery.objects.create(
            project=report.project,
            created_by=request.user,
            report=report,
            target=target,
            request_id=data["request_id"],
            report_fingerprint=digest,
            target_version=target.edit_version,
            target_snapshot={"name": target.name, "chat_id": target.chat_id, "source_instance": target.source_instance},
            text=report_text(report),
        )
        return Response(DeliverySerializer(row).data, status=201)


def send_message(delivery, target):
    config = read_connection(target.source_instance)
    if (
        not config
        or config.get("kind") != "feishu"
        or urlsplit(config.get("base_url", "")).hostname != "open.feishu.cn"
        or not config.get("service_token")
    ):
        raise PlatformUnavailable("飞书消息连接未配置或未授权；当前仅保留投递预览。")
    try:
        with requests.post(
            "https://open.feishu.cn/open-apis/im/v1/messages",
            params={"receive_id_type": "chat_id"},
            headers={"Authorization": "Bearer " + config["service_token"]},
            json={
                "receive_id": target.chat_id,
                "msg_type": "text",
                "content": json.dumps({"text": delivery.text}, ensure_ascii=False),
                "uuid": str(delivery.request_id),
            },
            timeout=(3, 8),
            allow_redirects=False,
            stream=True,
        ) as response:
            if response.status_code != 200:
                raise PlatformUnavailable("飞书未确认接收，请核对连接与目标授权后用同一投递记录重试。")
            raw = bytearray()
            for chunk in response.iter_content(8192):
                raw.extend(chunk)
                if len(raw) > 32768:
                    raise PlatformUnavailable()
        payload = json.loads(raw)
        message_id = payload.get("data", {}).get("message_id")
        if payload.get("code") != 0 or not isinstance(message_id, str) or not 0 < len(message_id) <= 255:
            raise PlatformUnavailable("飞书未返回有效消息回执，请核对目标授权。")
        return message_id
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        raise PlatformUnavailable("飞书投递未确认，请在投递记录中检查后重试。")


class SendInput(serializers.Serializer):
    confirmed = serializers.BooleanField(required=True)


class ReportDeliverySend(QualityView):
    @transaction.atomic
    def post(self, request, pk, **kwargs):
        require_manager(self)
        data = self.input(SendInput)
        if data["confirmed"] is not True:
            raise ValidationError({"confirmed": "请核对消息内容与接收群后明确确认发送。"})
        row = get_object_or_404(
            ReportDelivery.objects.select_for_update(of=("self",)).select_related("report__project", "target"),
            pk=pk,
            project_id=self.project_id,
        )
        if row.status == "sent":
            return Response(DeliverySerializer(row).data)
        if row.created_at < timezone.now() - timedelta(minutes=10):
            raise Conflict("此投递预览已过期；若曾尝试发送，请先在飞书核对回执，再决定是否创建新投递。")
        report = SavedReport.objects.select_for_update().get(pk=row.report_id)
        target = NotificationTarget.objects.select_for_update().get(pk=row.target_id)
        list(ProjectMember.objects.select_for_update().filter(project_id=self.project_id, member=request.user))
        list(WorkspaceMember.objects.select_for_update().filter(workspace=row.project.workspace, member=request.user))
        list(BusinessRole.objects.select_for_update().filter(project_id=self.project_id, user=request.user))
        if not writable_member(self.project_id, request.user.id, self.workspace_slug):
            raise PermissionDenied("项目成员权限已撤销，未发送。")
        require_manager(self)
        if (
            not target.enabled
            or target.edit_version != row.target_version
            or fingerprint(report) != row.report_fingerprint
        ):
            raise Conflict("报告或接收目标已改变，请重新生成预览并核对。")
        row.attempts += 1
        try:
            row.external_message_id = send_message(row, target)
        except PlatformUnavailable:
            row.status, row.last_error = "unconfirmed", "DELIVERY_NOT_CONFIRMED"
            row.save()
            return Response(
                {
                    **DeliverySerializer(row).data,
                    "error": "飞书投递尚未确认，可能未配置或服务不可用；请核对后使用本记录重试。",
                },
                status=503,
            )
        row.status, row.sent_at, row.last_error = "sent", timezone.now(), ""
        row.save()
        return Response(DeliverySerializer(row).data)
