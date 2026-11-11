# SPDX-License-Identifier: AGPL-3.0-only
from plane.quality.authorship import AuthoredRecordSerializer
from rest_framework import serializers
from .models import Article, ArticleEvent, ChatMessage, Conversation, PublishedRevision
from .retrieval import published


def visible_references(project_id):
    return {
        f"KN-{article_id}-v{version}"
        for article_id, version in published(project_id).values_list("article_id", "version")
    }


def references_available(message, allowed):
    return bool(message.citations) and all(citation.get("reference") in allowed for citation in message.citations)


class ArticleInput(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    content = serializers.CharField(max_length=100000)
    tags = serializers.ListField(child=serializers.CharField(max_length=64), max_length=20, default=list)
    source_issue_id = serializers.UUIDField(required=False, allow_null=True)
    expected_version = serializers.IntegerField(min_value=1, required=False)


class PublicationSerializer(AuthoredRecordSerializer):
    device_scope = serializers.CharField(source="share_device_scope", default="", read_only=True)
    version_scope = serializers.CharField(source="share_version_scope", default="", read_only=True)
    source_project_name = serializers.CharField(source="project.name", read_only=True)
    article_id = serializers.UUIDField(read_only=True)
    reference = serializers.SerializerMethodField()

    def get_reference(self, obj):
        return f"KN-{obj.article_id}-v{obj.version}"

    class Meta:
        model = PublishedRevision
        fields = [
            "id",
            "article_id",
            "version",
            "reference",
            "title",
            "content",
            "tags",
            "created_at",
            "source_project_name",
            "device_scope",
            "version_scope",
        ]


class ArticleEventSerializer(serializers.ModelSerializer):
    actor = serializers.CharField(source="created_by.display_name", default="成员")

    class Meta:
        model = ArticleEvent
        fields = ["id", "action", "version", "note", "created_at", "actor"]


class ArticleSerializer(AuthoredRecordSerializer):
    source_defect_id = serializers.UUIDField(read_only=True, allow_null=True)
    source_regression_id = serializers.UUIDField(read_only=True, allow_null=True)
    source_issue_id = serializers.UUIDField(read_only=True, allow_null=True)
    source_files = serializers.SerializerMethodField()
    versions = PublicationSerializer(many=True, read_only=True)
    events = ArticleEventSerializer(many=True, read_only=True)

    def get_source_files(self, obj):
        from plane.quality.models import DocumentFile
        from plane.quality.document_imports import file_representation

        # A local source never follows publication sharing to another project.
        rows = DocumentFile.objects.filter(
            project_id=obj.project_id,
            document_import__project_id=obj.project_id,
            document_import__resource="knowledge",
            document_import__status="confirmed",
            document_import__object_ids__contains=[str(obj.id)],
        )
        return [file_representation(row) for row in rows]

    class Meta:
        model = Article
        fields = [
            "id",
            "title",
            "content",
            "tags",
            "status",
            "merged_into_id",
            "edit_version",
            "published_version",
            "publication_active",
            "scanned_version",
            "scan_findings",
            "source_issue_id",
            "source_defect_id",
            "source_regression_id",
            "source_files",
            "versions",
            "events",
            "created_at",
            "updated_at",
        ]


class ChatInput(serializers.Serializer):
    query = serializers.CharField(max_length=2000)
    request_id = serializers.UUIDField()
    conversation_id = serializers.UUIDField(required=False)


class AnswerInput(serializers.Serializer):
    answer = serializers.CharField(max_length=12000)
    suggested_actions = serializers.ListField(child=serializers.CharField(max_length=2000), max_length=12)
    verification_steps = serializers.ListField(child=serializers.CharField(max_length=2000), max_length=12)
    citations = serializers.ListField(child=serializers.CharField(max_length=100), max_length=8, allow_empty=False)


class MessageSerializer(serializers.ModelSerializer):
    conversation_id = serializers.UUIDField(read_only=True)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.status == "completed":
            visibility = self.context.setdefault("visible_references", {})
            if instance.project_id not in visibility:
                visibility[instance.project_id] = visible_references(instance.project_id)
            if not references_available(instance, visibility[instance.project_id]):
                data.update(
                    status="reference_unavailable",
                    error_code="KNOWLEDGE_REFERENCE_UNAVAILABLE",
                    answer="引用的知识已下线或更新，此历史回答已隐藏，请重新提问。",
                    citations=[],
                    suggested_actions=[],
                    verification_steps=[],
                )
        return data

    class Meta:
        model = ChatMessage
        fields = [
            "id",
            "conversation_id",
            "query",
            "status",
            "answer",
            "suggested_actions",
            "verification_steps",
            "citations",
            "feedback",
            "feedback_note",
            "error_code",
            "model",
            "created_at",
        ]


class ConversationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Conversation
        fields = ["id", "title", "created_at"]
