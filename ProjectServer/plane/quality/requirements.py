# SPDX-License-Identifier: AGPL-3.0-only
"""Requirements keep Plane Issue as canonical work and test-link identity."""

from plane.quality.authorship import AuthoredRecordSerializer
from html import escape
from django.db import transaction
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from plane.db.models import Issue, ProjectMember
from .models import Requirement, RequirementRevision, TestCase
from .serializers import CaseSerializer
from .permissions import strict, capable
from .views import QualityView, Conflict


class RequirementInput(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    description = serializers.CharField(max_length=20000, allow_blank=True, default="")
    acceptance = serializers.CharField(max_length=20000, allow_blank=True, default="")
    target_build = serializers.CharField(max_length=120, allow_blank=True, default="")
    priority = serializers.ChoiceField(choices=["urgent", "high", "medium", "low", "none"], default="medium")
    expected_version = serializers.IntegerField(min_value=1, required=False)


class RequirementSerializer(AuthoredRecordSerializer):
    trashed_at = serializers.DateTimeField(source="issue.deleted_at", read_only=True)
    code = serializers.SerializerMethodField()

    def get_code(self, obj):
        return f"{obj.project.identifier}-R-{obj.number}"

    id = serializers.UUIDField(source="issue_id")
    title = serializers.CharField(source="issue.name")
    description = serializers.CharField(source="issue.description_stripped", allow_null=True)
    priority = serializers.CharField(source="issue.priority")
    sequence_id = serializers.IntegerField(source="issue.sequence_id")
    development_state = serializers.CharField(source="issue.state.name", default="")
    development_group = serializers.CharField(source="issue.state.group", default="")
    case_count = serializers.SerializerMethodField()

    def get_case_count(self, obj):
        return TestCase.objects.filter(project_id=obj.project_id, requirement_id=obj.issue_id).count()

    class Meta:
        model = Requirement
        fields = [
            "id",
            "number",
            "code",
            "title",
            "description",
            "acceptance",
            "target_build",
            "priority",
            "sequence_id",
            "development_state",
            "development_group",
            "status",
            "version",
            "case_count",
            "created_at",
            "trashed_at",
        ]


def content(row):
    return {
        "title": row.issue.name,
        "description": row.issue.description_stripped or "",
        "description_html": row.issue.description_html or "",
        "acceptance": row.acceptance,
        "target_build": row.target_build,
        "priority": row.issue.priority,
        "status": row.status,
    }


def check_revision(row):
    latest = row.revisions.filter(version=row.version).first()
    current = content(row)
    if latest is None or any(latest.snapshot.get(key) != value for key, value in current.items()):
        raise Conflict("需求内容已在其他入口变更，请刷新并核对后再操作。")


def visible_requirements(view):
    project = view.project()
    deleted = view.request.query_params.get("deleted") == "true"
    qs = Requirement.objects.filter(project=project, issue__deleted_at__isnull=not deleted).select_related("issue")
    if (
        not project.guest_view_all_features
        and ProjectMember.objects.filter(project=project, member=view.request.user, is_active=True, role=5).exists()
    ):
        qs = qs.filter(issue__created_by=view.request.user)
    return qs


def guard_native_requirement_edit(issue, attrs, request=None):
    # Keep native execution fields available; reviewed requirement content has one versioned writer.
    protected = {"name", "description_html", "description_stripped", "description_binary", "description", "priority"}
    if issue is None or not protected.intersection(attrs):
        return
    if Requirement.objects.filter(issue_id=issue.pk).exists():
        if request and not capable(issue.project_id, request.user.id, "knowledge_write"):
            raise PermissionDenied("当前业务角色不允许修改需求。")
        raise Conflict("请在项目的“需求管理”中编辑需求内容，系统将保留版本并重新审核；开发状态仍可在工作项中更新。")


def snapshot(row, actor, action="edit", comment=""):
    RequirementRevision.objects.create(
        project=row.project,
        created_by=actor,
        requirement=row,
        version=row.version,
        snapshot={**content(row), "action": action, "comment": comment},
    )


def detail(row):
    return {
        **RequirementSerializer(row).data,
        "revisions": [
            {
                "id": str(rev.id),
                "version": rev.version,
                "snapshot": rev.snapshot,
                "created_at": rev.created_at,
                "actor": rev.created_by.display_name or rev.created_by.email if rev.created_by else "",
            }
            for rev in row.revisions.select_related("created_by").all()
        ],
        "tasks": [
            {
                "id": str(task.id),
                "title": task.name,
                "sequence_id": task.sequence_id,
                "state": task.state.name if task.state else "未安排",
                "state_group": task.state.group if task.state else "backlog",
            }
            for task in Issue.objects.filter(parent_id=row.issue_id, project_id=row.project_id).select_related("state")
        ],
        "cases": CaseSerializer(
            TestCase.objects.filter(project=row.project, requirement_id=row.issue_id), many=True
        ).data,
    }


class RequirementList(QualityView):
    def get(self, request, **kwargs):
        qs = visible_requirements(self)
        return self.listing(qs, RequirementSerializer)

    @transaction.atomic
    def post(self, request, **kwargs):
        data = self.input(RequirementInput)
        data.pop("expected_version", None)
        title = data.pop("title")
        description = data.pop("description")
        priority = data.pop("priority")
        project = self.project()
        issue = Issue.objects.create(
            project=project,
            workspace=project.workspace,
            name=title,
            description_stripped=description,
            description_html="<p>" + escape(description).replace("\n", "<br>\n") + "</p>",
            priority=priority,
            created_by=request.user,
        )
        row = Requirement.objects.create(project=project, created_by=request.user, issue=issue, **data)
        snapshot(row, request.user, "create")
        return Response(detail(row), status=201)


class RequirementDetail(QualityView):
    def get(self, request, pk, **kwargs):
        row = get_object_or_404(Requirement.objects.select_related("issue"), project_id=self.project_id, issue_id=pk)
        if not visible_requirements(self).filter(pk=row.pk).exists():
            raise PermissionDenied("您没有此需求的查看权限。")
        return Response(detail(row))

    @transaction.atomic
    def patch(self, request, pk, **kwargs):
        data = self.input(RequirementInput, partial=True)
        row = get_object_or_404(
            Requirement.objects.select_for_update().select_related("issue"), project_id=self.project_id, issue_id=pk
        )
        check_revision(row)
        if data.pop("expected_version", None) != row.version:
            raise Conflict()
        if row.issue.deleted_at:
            raise Conflict("需求已在回收站，请先恢复。")
        if row.status in {"review", "completed", "cancelled", "archived"}:
            raise Conflict("当前需求已进入审核或结束阶段，请先退回或重开后修改。")
        issue = Issue.objects.select_for_update().get(pk=row.issue_id)
        description_changed = "description" in data and data["description"] != (issue.description_stripped or "")
        for key, target in [("title", "name"), ("description", "description_stripped"), ("priority", "priority")]:
            if key in data:
                setattr(issue, target, data.pop(key))
        if description_changed:
            issue.description_html = "<p>" + escape(issue.description_stripped or "").replace("\n", "<br>\n") + "</p>"
        issue.save()
        row.issue = issue
        for key, value in data.items():
            setattr(row, key, value)
        row.status = "draft"
        row.version += 1
        row.save()
        snapshot(row, request.user)
        return Response(detail(row))


class WorkflowInput(serializers.Serializer):
    action = serializers.ChoiceField(
        choices=["submit", "approve", "return", "accept", "cancel", "reopen", "archive", "restore", "trash", "untrash"]
    )
    expected_version = serializers.IntegerField(min_value=1)
    comment = serializers.CharField(max_length=4000, allow_blank=True, default="")


class RequirementWorkflow(QualityView):
    @transaction.atomic
    def post(self, request, pk, **kwargs):
        data = self.input(WorkflowInput)
        row = get_object_or_404(
            Requirement.objects.select_for_update().select_related("issue"), project_id=self.project_id, issue_id=pk
        )
        check_revision(row)
        if data["expected_version"] != row.version:
            raise Conflict()
        action = data["action"]
        if row.issue.deleted_at and action != "untrash":
            raise Conflict("需求已在回收站，请先恢复。")
        manager = (
            capable(self.project_id, request.user.id, "manage_test")
            if strict(self.project_id)
            else ProjectMember.objects.filter(
                project_id=self.project_id, member=request.user, is_active=True, role=20
            ).exists()
        )
        if action != "submit" and not manager:
            raise PermissionDenied("需求审核由项目经理负责。")
        if action in {"trash", "untrash"}:
            if not data["comment"].strip():
                raise ValidationError({"comment": "请填写操作原因。"})
            issue = Issue.all_objects.select_for_update().get(pk=row.issue_id)
            if action == "trash":
                if row.status not in {"draft", "cancelled"}:
                    raise Conflict("仅待完善或已取消的需求可删除，请先完成取消处理。")
                if Issue.objects.filter(project=row.project, parent_id=row.issue_id).exists():
                    raise Conflict("需求仍关联开发任务，请先处理任务关系后再删除。")
                issue.deleted_at = timezone.now()
            else:
                if not issue.deleted_at:
                    raise Conflict("需求不在回收站。")
                issue.deleted_at = None
            issue.save(update_fields=["deleted_at", "updated_at"])
            row.issue = issue
        elif action == "submit":
            if row.status != "draft" or not row.acceptance.strip():
                raise ValidationError({"acceptance": "请填写验收标准，再提交需求审核。"})
            row.status = "review"
        elif action == "approve":
            if row.status != "review":
                raise Conflict("只有待审核需求可以批准。")
            row.status = "approved"
        elif action == "return":
            if row.status != "review" or not data["comment"].strip():
                raise ValidationError({"comment": "退回需求须填写原因。"})
            row.status = "draft"
        else:
            if not data["comment"].strip():
                raise ValidationError({"comment": "请记录本次验收或状态调整的原因与依据。"})
            if action == "accept":
                if row.status != "approved" or getattr(row.issue.state, "group", None) != "completed":
                    raise ValidationError(
                        {"error": "请先确认需求并完成关联开发工作项，再记录验收结果；无需强制建立测试用例。"}
                    )
                if (
                    Issue.objects.filter(parent_id=row.issue_id)
                    .exclude(state__group__in=["completed", "cancelled"])
                    .exists()
                ):
                    raise ValidationError({"error": "需求仍有未完成的子工作项，请处理后再验收。"})
                row.status = "completed"
            elif action == "cancel":
                if row.status not in {"draft", "review", "approved"}:
                    raise Conflict("当前需求不能直接取消。")
                row.status = "cancelled"
            elif action == "reopen":
                if row.status not in {"completed", "cancelled"}:
                    raise Conflict("仅已完成或取消的需求可重开。")
                row.status = "draft"
            elif action == "archive":
                if row.status not in {"completed", "cancelled"}:
                    raise Conflict("仅已结束的需求可归档。")
                row.status = "archived"
            elif action == "restore":
                if row.status != "archived":
                    raise Conflict("当前需求未归档。")
                previous = row.revisions.filter(version=row.version - 1).first()
                row.status = (
                    previous.snapshot["status"]
                    if previous and previous.snapshot.get("status") in {"completed", "cancelled"}
                    else "draft"
                )
        row.version += 1
        row.save()
        snapshot(row, request.user, action, data["comment"])
        from .notifications import notify, managers

        targets = managers(row.project) if action == "submit" else [row.created_by_id]
        notify(
            row.project,
            request.user,
            targets,
            row.issue_id,
            {
                "submit": "需求等待审核",
                "approve": "需求已确认",
                "return": "需求已退回",
                "accept": "需求验收完成",
                "cancel": "需求已取消",
                "reopen": "需求已重开",
                "archive": "需求已归档",
                "restore": "需求已恢复",
                "trash": "需求已移入回收站",
                "untrash": "需求已从回收站恢复",
            }[action]
            + "："
            + row.issue.name,
            f"requirements?requirement={row.issue_id}",
        )
        return Response(detail(row))


class TaskInput(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    description = serializers.CharField(max_length=20000, allow_blank=True, default="")
    assignee_id = serializers.UUIDField(required=False, allow_null=True)


class RequirementTasks(QualityView):
    @transaction.atomic
    def post(self, request, pk, **kwargs):
        from plane.db.models import IssueAssignee

        data = self.input(TaskInput)
        row = get_object_or_404(
            Requirement.objects.select_for_update().select_related("issue"), issue_id=pk, project_id=self.project_id
        )
        if row.status in {"review", "completed", "cancelled", "archived"}:
            raise Conflict("请先重开需求，再拆分开发任务。")
        self.validate_assignee(data.get("assignee_id"))
        task = Issue.objects.create(
            project=row.project,
            workspace=row.project.workspace,
            parent=row.issue,
            created_by=request.user,
            name=data["title"],
            description_html="<p>" + escape(data["description"]).replace("\n", "<br>\n") + "</p>",
        )
        if data.get("assignee_id"):
            IssueAssignee.objects.create(
                project=row.project, workspace=row.project.workspace, issue=task, assignee_id=data["assignee_id"]
            )
        return Response({"id": str(task.id), "title": task.name, "parent_id": str(row.issue_id)}, status=201)
