# SPDX-License-Identifier: AGPL-3.0-only
"""Private defect discussions. Rich text and attachments never become DAQ public replies."""

import hashlib
import json
import os
from pathlib import Path
import uuid

from bs4 import BeautifulSoup
import nh3
from django.db import transaction
from django.db.models import Count, Q
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from .attachments import MAX_FILE, IMAGE_TYPES, directory, image_type, validate_archive
from .collaboration_admin import internal_access
from .models import CommentAttachment, Defect, DefectComment
from .views import Conflict, QualityPagination, QualityView

TAGS = {
    "p",
    "br",
    "strong",
    "b",
    "em",
    "i",
    "u",
    "s",
    "del",
    "h1",
    "h2",
    "h3",
    "h4",
    "ul",
    "ol",
    "li",
    "blockquote",
    "pre",
    "code",
    "a",
    "hr",
}
ATTRIBUTES = {"a": {"href", "title"}, "ol": {"start"}}
TYPES = {
    ".txt": "text/plain",
    ".log": "text/plain",
    ".md": "text/plain",
    ".json": "application/json",
    ".csv": "text/csv",
    ".yaml": "text/plain",
    ".yml": "text/plain",
    ".pdf": "application/pdf",
    ".zip": "application/zip",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def actor(user):
    return (user.display_name or user.username or "成员") if user else "已删除账号"


def attachment_data(row):
    return {"id": str(row.id), "name": row.name, "size": row.size, "content_type": row.content_type}


def comment_data(row):
    parent = row.reply_to
    if parent and (
        parent.defect_id != row.defect_id or parent.project_id != row.project_id or parent.visibility != "internal"
    ):
        parent = None
    return {
        "id": str(row.id),
        "content": row.content,
        "content_html": row.content_html,
        "visibility": "internal",
        "actor": actor(row.created_by),
        "created_by_id": str(row.created_by_id) if row.created_by_id else None,
        "created_at": row.created_at,
        "thread_id": str(row.thread_root_id or row.id),
        "reply_to": {"id": str(parent.id), "actor": actor(parent.created_by), "content": parent.content[:300]}
        if parent
        else None,
        "attachments": [attachment_data(file) for file in row.attachments.all()],
        "reply_count": getattr(row, "reply_count", 0),
    }


class CommentInput(serializers.Serializer):
    request_id = serializers.UUIDField()
    content_html = serializers.CharField(max_length=50000, allow_blank=True, trim_whitespace=False)
    reply_to = serializers.UUIDField(allow_null=True, required=False, default=None)
    attachment_ids = serializers.ListField(child=serializers.UUIDField(), max_length=10, required=False, default=list)

    def validate_attachment_ids(self, values):
        if len(values) != len(set(values)):
            raise ValidationError("附件不能重复。")
        return values


class DiscussionView(QualityView):
    def scoped_defect(self, pk, lock=False):
        defect = self.obj(Defect, pk)
        if not internal_access(self.project_id, self.request.user, self.workspace_slug):
            raise PermissionDenied("仅当前项目的平台成员可以查看和参与内部评论。")
        if lock:
            defect = Defect.objects.select_for_update().get(pk=defect.pk)
        return defect


def filtered_comments(comments, request):
    search = serializers.CharField(max_length=200, allow_blank=True).run_validation(
        request.query_params.get("search", "")
    )
    if search:
        comments = comments.filter(content__icontains=search)
    if request.query_params.get("author"):
        author = serializers.UUIDField().run_validation(request.query_params["author"])
        comments = comments.filter(created_by_id=author)
    return comments


class DefectDiscussion(DiscussionView):
    def get(self, request, pk, **kwargs):
        defect = self.scoped_defect(pk)
        comments = (
            defect.comments.filter(visibility="internal")
            .select_related("created_by", "reply_to__created_by")
            .prefetch_related("attachments")
        )
        participants = [
            {
                "id": str(row["created_by_id"]),
                "name": row["created_by__display_name"] or row["created_by__username"] or "成员",
            }
            for row in comments.order_by()
            .exclude(created_by_id=None)
            .values("created_by_id", "created_by__display_name", "created_by__username")
            .distinct()
        ]
        view = serializers.ChoiceField(choices=["flat", "threads"]).run_validation(
            request.query_params.get("view", "flat")
        )
        matching = filtered_comments(comments, request)
        if view == "threads":
            comments = (
                comments.filter(thread_root__isnull=True)
                .filter(
                    Q(pk__in=matching.order_by().values("pk"))
                    | Q(pk__in=matching.filter(thread_root__isnull=False).order_by().values("thread_root_id"))
                )
                .annotate(
                    reply_count=Count(
                        "thread_replies", filter=Q(thread_replies__defect=defect, thread_replies__visibility="internal")
                    )
                )
            )
        else:
            comments = matching
        paginator = QualityPagination()
        rows = paginator.paginate_queryset(comments.order_by("-created_at", "-id"), request)
        response = paginator.get_paginated_response([comment_data(row) for row in rows])
        response.data["participants"] = sorted(participants, key=lambda item: item["name"])
        if view == "threads":
            response.data["comment_count"] = matching.count()
        return response

    @transaction.atomic
    def post(self, request, pk, **kwargs):
        defect = self.scoped_defect(pk, lock=True)
        data = self.input(CommentInput)
        digest = hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()
        existing = (
            DefectComment.objects.filter(defect=defect, created_by=request.user, request_id=data["request_id"])
            .select_related("created_by", "reply_to__created_by")
            .prefetch_related("attachments")
            .first()
        )
        if existing:
            if existing.request_hash != digest:
                raise Conflict("该提交编号已用于另一条评论，请刷新后重试。")
            return Response(comment_data(existing))
        clean = nh3.clean(
            data["content_html"],
            tags=TAGS,
            attributes=ATTRIBUTES,
            url_schemes={"http", "https", "mailto"},
            link_rel="noopener noreferrer",
        )
        plain = BeautifulSoup(clean, "html.parser").get_text(" ", strip=True)
        if len(plain) > 10000:
            raise ValidationError({"content_html": "评论最多10000字。"})
        if not plain and not data["attachment_ids"]:
            raise ValidationError({"content_html": "请填写评论或添加附件。"})
        parent = None
        thread_root = None
        if data["reply_to"]:
            parent = DefectComment.objects.filter(pk=data["reply_to"], defect=defect, visibility="internal").first()
            if not parent:
                raise ValidationError({"reply_to": "只能回复本缺陷的内部评论。"})
            thread_root = parent
            if parent.thread_root_id:
                thread_root = DefectComment.objects.filter(
                    pk=parent.thread_root_id, defect=defect, visibility="internal", thread_root__isnull=True
                ).first()
                if not thread_root:
                    raise ValidationError({"reply_to": "评论线程已变化，请刷新后再回复。"})
        files = list(
            CommentAttachment.objects.select_for_update().filter(
                id__in=data["attachment_ids"], defect=defect, created_by=request.user, comment__isnull=True
            )
        )
        if len(files) != len(data["attachment_ids"]):
            raise ValidationError({"attachment_ids": "附件不存在、已被使用或不属于当前草稿。"})
        if sum(file.size for file in files) > 50 * 1024 * 1024:
            raise ValidationError({"attachment_ids": "单条评论的附件合计不能超过50MB。"})
        row = DefectComment.objects.create(
            project=defect.project,
            defect=defect,
            created_by=request.user,
            content=plain,
            content_html=clean,
            visibility="internal",
            request_id=data["request_id"],
            request_hash=digest,
            reply_to=parent,
            thread_root=thread_root,
        )
        CommentAttachment.objects.filter(id__in=[file.id for file in files]).update(comment=row)
        row = (
            DefectComment.objects.select_related("created_by", "reply_to__created_by")
            .prefetch_related("attachments")
            .get(pk=row.pk)
        )
        return Response(comment_data(row), status=201)


class DiscussionReplies(DiscussionView):
    def get(self, request, pk, comment_id, **kwargs):
        defect = self.scoped_defect(pk)
        selected = get_object_or_404(DefectComment, pk=comment_id, defect=defect, visibility="internal")
        root = (
            selected
            if selected.thread_root_id is None
            else get_object_or_404(
                DefectComment,
                pk=selected.thread_root_id,
                defect=defect,
                visibility="internal",
                thread_root__isnull=True,
            )
        )
        replies = (
            defect.comments.filter(visibility="internal", thread_root=root)
            .select_related("created_by", "reply_to__created_by")
            .prefetch_related("attachments")
        )
        total = replies.count()
        paginator = QualityPagination()
        rows = paginator.paginate_queryset(filtered_comments(replies, request).order_by("-created_at", "-id"), request)
        response = paginator.get_paginated_response([comment_data(row) for row in rows])
        response.data.update({"thread_id": str(root.id), "reply_count": total})
        return response


class DiscussionFiles(DiscussionView):
    def post(self, request, pk, **kwargs):
        defect = self.scoped_defect(pk)
        upload = serializers.FileField(allow_empty_file=False).run_validation(request.FILES.get("file"))
        extension = Path(upload.name).suffix.lower()
        if (
            extension not in set(IMAGE_TYPES) | set(TYPES)
            or upload.size > MAX_FILE
            or len(upload.name) > 255
            or any(part in upload.name for part in ["/", "\\", "\x00"])
            or upload.name.startswith(".")
        ):
            raise ValidationError({"file": "支持图片、文档及日志文件，单个文件不超过20MB。"})
        raw = upload.read(MAX_FILE + 1)
        if len(raw) > MAX_FILE:
            raise ValidationError({"file": "文件超过20MB。"})
        upload.seek(0)
        content_type = TYPES.get(extension)
        if extension in IMAGE_TYPES:
            content_type = image_type(raw[:16], upload.name)
            if not content_type:
                raise ValidationError({"file": "图片内容与类型不匹配。"})
        validate_archive(upload, upload.name)
        if extension in {".docx", ".xlsx"}:
            validate_archive(upload, upload.name + ".zip")
        key = "comment-" + uuid.uuid4().hex + ".bin"
        path = directory() / key
        try:
            with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            row = CommentAttachment.objects.create(
                project=defect.project,
                defect=defect,
                created_by=request.user,
                name=upload.name,
                size=len(raw),
                sha256=hashlib.sha256(raw).hexdigest(),
                storage_key=key,
                content_type=content_type,
            )
            return Response(attachment_data(row), status=201)
        except BaseException:
            path.unlink(missing_ok=True)
            raise


class DiscussionFile(DiscussionView):
    def get(self, request, pk, file_id, preview=False, **kwargs):
        defect = self.scoped_defect(pk)
        row = get_object_or_404(CommentAttachment, pk=file_id, defect=defect)
        if row.comment_id is None and row.created_by_id != request.user.id:
            raise PermissionDenied("草稿附件仅上传者可见。")
        if preview and not row.content_type.startswith("image/"):
            raise ValidationError({"file": "此文件请下载查看。"})
        root = directory()
        path = root / row.storage_key
        if path.parent != root or path.is_symlink():
            raise Conflict("附件存储位置无效。")
        try:
            handle = path.open("rb")
        except FileNotFoundError:
            raise Conflict("附件暂不可用，请稍后重试。")
        response = FileResponse(
            handle,
            as_attachment=not preview,
            filename=row.name,
            content_type=row.content_type if preview else "application/octet-stream",
        )
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = "default-src 'none'; sandbox"
        response["Cache-Control"] = "private, no-store"
        return response
