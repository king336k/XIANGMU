# SPDX-License-Identifier: AGPL-3.0-only
import hashlib
from datetime import timedelta

from django.core.cache import cache
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import Throttled, ValidationError
from rest_framework.response import Response

from plane.quality.views import Conflict, QualityView
from plane.authentication.session import BaseSessionAuthentication
from plane.quality.identity import PlatformBridgeAuthentication
from . import assistant
from .models import ChatMessage, Conversation
from .retrieval import search, scan_content
from .serializers import ChatInput, ConversationSerializer, MessageSerializer, visible_references, references_available


class ChatEndpoint(QualityView):
    authentication_classes = [PlatformBridgeAuthentication, BaseSessionAuthentication]

    def post(self, request, **kwargs):
        data = self.input(ChatInput)
        project = self.project()
        # Scope idempotency to identity and project; simultaneous duplicate requests fail closed.
        digest = hashlib.sha256(f"{project.id}:{request.user.id}:{data['request_id']}".encode()).hexdigest()
        lock_key = f"knowledge-chat-lock:{digest}"
        if not cache.add(lock_key, True, timeout=90):
            raise Conflict("同一问题正在处理中，请稍后查看会话。")
        try:
            existing = ChatMessage.objects.filter(
                project=project, created_by=request.user, request_id=data["request_id"]
            ).first()
            if existing:
                if existing.query != data["query"] or (
                    data.get("conversation_id") and existing.conversation_id != data["conversation_id"]
                ):
                    raise Conflict("同一提交编号不能用于不同的问题。")
                if existing.status in {"completed", "no_knowledge"}:
                    return Response(MessageSerializer(existing).data)
                if existing.status == "running" and existing.created_at > timezone.now() - timedelta(seconds=90):
                    raise Conflict("问题仍在处理中。")
                return Response(
                    {
                        **MessageSerializer(existing).data,
                        "code": existing.error_code or "AI_REQUEST_INTERRUPTED",
                        "error": "上次调用未成功，请重新提交问题。",
                    },
                    status=502,
                )
            if scan_content(data["query"]):
                raise ValidationError({"query": "问题中包含疑似敏感信息，请脱敏后重试。"})
            config = assistant.provider_config()
            if not config.get("configured"):
                return Response(
                    {"code": "AI_NOT_CONFIGURED", "error": "模型服务尚未配置。可先使用已发布知识检索。"}, status=503
                )
            rate_key = f"knowledge-chat-rate:{project.id}:{request.user.id}"
            if cache.add(rate_key, 1, timeout=60):
                count = 1
            else:
                try:
                    count = cache.incr(rate_key)
                except ValueError:
                    cache.set(rate_key, 1, timeout=60)
                    count = 1
            if count > 10:
                raise Throttled(wait=60)
            with transaction.atomic():
                if data.get("conversation_id"):
                    conversation = get_object_or_404(
                        Conversation, pk=data["conversation_id"], project=project, created_by=request.user
                    )
                else:
                    conversation = Conversation.objects.create(
                        project=project, created_by=request.user, title=data["query"][:160]
                    )
                message = ChatMessage.objects.create(
                    project=project,
                    created_by=request.user,
                    conversation=conversation,
                    request_id=data["request_id"],
                    query=data["query"],
                )
            allowed = visible_references(project.id)
            previous = list(conversation.messages.filter(status="completed").order_by("-created_at", "-id")[:4])
            history = [
                {"question": entry.query, "answer": entry.answer[:3000]}
                for entry in reversed(previous)
                if references_available(entry, allowed)
            ]
            history_references = {
                citation["reference"]
                for entry in previous
                if references_available(entry, allowed)
                for citation in entry.citations
            }
            retrieval_query = data["query"] + " " + " ".join(entry["question"] for entry in history)
            revisions = list(search(project, retrieval_query)[:5])
            if not revisions:
                message.status = "no_knowledge"
                message.answer = "未检索到可引用的已发布知识，请补充现象、错误码或版本，也可先整理并发布知识。"
                message.save()
                return Response(MessageSerializer(message).data, status=201)
            references = assistant.reference_payload(revisions,retrieval_query)
            try:
                response = assistant.complete_answer(config, data["query"], references, history)
                answer = assistant.validate_answer(response, references)
                # A publication may have been taken offline while the model was responding.
                current = set(search(project, retrieval_query).values_list("id", flat=True))
                if any(r.id not in current for r in revisions):
                    raise serializers.ValidationError("引用版本已下线，请重新提问。")
                if not history_references.issubset(visible_references(project.id)):
                    raise serializers.ValidationError("会话引用已下线，请重新提问。")
                for key, value in answer.items():
                    setattr(message, key, value)
                message.status = "completed"
                message.model = str(config.get("model", ""))[:120]
                message.save()
                return Response(MessageSerializer(message).data, status=201)
            except (serializers.ValidationError, ValueError, TypeError, KeyError):
                message.status = "failed"
                message.error_code = "AI_INVALID_RESPONSE"
                message.save()
                return Response(
                    {"code": message.error_code, "error": "模型返回的结构或引用未通过校验，请重试或使用知识检索。"},
                    status=502,
                )
            except Exception:
                message.status = "failed"
                message.error_code = "AI_PROVIDER_UNAVAILABLE"
                message.save()
                return Response(
                    {"code": message.error_code, "error": "模型服务暂不可用，请稍后重试。知识检索仍可使用。"},
                    status=502,
                )
        finally:
            cache.delete(lock_key)


class ConversationList(QualityView):
    def get(self, request, **kwargs):
        return self.listing(
            Conversation.objects.filter(project=self.project(), created_by=request.user), ConversationSerializer
        )


class ConversationDetail(QualityView):
    def get(self, request, pk, **kwargs):
        conversation = get_object_or_404(Conversation, pk=pk, project=self.project(), created_by=request.user)
        return self.listing(conversation.messages.order_by("created_at", "id"), MessageSerializer)


class FeedbackInput(serializers.Serializer):
    feedback = serializers.ChoiceField(choices=["helpful", "unhelpful"])
    note = serializers.CharField(max_length=2000, allow_blank=True, default="")


class ChatFeedback(QualityView):
    def post(self, request, pk, **kwargs):
        data = self.input(FeedbackInput)
        message = get_object_or_404(ChatMessage, pk=pk, project=self.project(), created_by=request.user)
        message.feedback = data["feedback"]
        message.feedback_note = data["note"]
        message.save(update_fields=["feedback", "feedback_note"])
        return Response(MessageSerializer(message).data)


class AssistantStatus(QualityView):
    authentication_classes = [PlatformBridgeAuthentication, BaseSessionAuthentication]

    def get(self, request, **kwargs):
        from .semantic_provider import public_status

        config = assistant.provider_config()
        return Response(
            {
                "semantic": public_status(),
                "configured": config["configured"],
                "model": config.get("model", "") if config["configured"] else "",
                "message": "只引用当前项目可见的已发布知识；不会执行命令或修改业务数据。",
            }
        )
