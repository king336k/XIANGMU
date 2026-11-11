# SPDX-License-Identifier: AGPL-3.0-only
"""Read the official catalog contract without overwriting native work or granting access."""

from html import escape
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import serializers
from rest_framework.response import Response
from plane.db.models import Issue, State
from . import platform
from .models import PlatformCatalog, PlatformCatalogTask, PlatformProject, PlatformIdentity, QualityLifecycleEvent
from .permissions import has_role
from .roles import management
from .views import QualityView, Conflict

INACTIVE = {"DELETED", "DISABLED", "ARCHIVED", "CANCELLED", "INACTIVE"}


def positive_id(value):
    return isinstance(value, int) and not isinstance(value, bool) and 0 < value < 2**63


def valid_stamp(value):
    try:
        return isinstance(value, str) and len(value) <= 80 and parse_datetime(value) is not None
    except ValueError:
        return False


def pages(instance, path, after=""):
    items, cursors, ids, snapshot = [], set(), set(), None
    params = {"limit": 200, **({"updatedAfter": after} if after else {})}
    for _ in range(20):
        page = platform.fetch(instance, path, params)
        if (
            not isinstance(page, dict)
            or not isinstance(page.get("items"), list)
            or len(page["items"]) > 200
            or type(page.get("hasMore")) is not bool
            or not valid_stamp(page.get("snapshotAt"))
            or (snapshot is not None and snapshot != page["snapshotAt"])
        ):
            raise platform.PlatformUnavailable("来源目录响应不完整，未应用任何同步变更。")
        snapshot = page["snapshotAt"]
        for item in page["items"]:
            if (
                not isinstance(item, dict)
                or not positive_id(item.get("id"))
                or item["id"] in ids
                or not isinstance(item.get("name"), str)
                or not item["name"].strip()
                or len(item["name"]) > 255
                or not isinstance(item.get("status", ""), str)
                or len(item.get("status", "")) > 80
            ):
                raise platform.PlatformUnavailable("来源目录包含重复或无效条目，未应用同步。")
            ids.add(item["id"])
            items.append(item)
        if not page["hasMore"]:
            return items, snapshot
        cursor = page.get("nextCursor")
        if not isinstance(cursor, str) or not cursor or len(cursor) > 2000 or cursor in cursors:
            raise platform.PlatformUnavailable("来源目录分页游标无效，未应用同步。")
        cursors.add(cursor)
        params = {"limit": 200, "cursor": cursor}
    raise platform.PlatformUnavailable("来源目录超过单次4000条上限，未应用同步。")


class CatalogInput(serializers.Serializer):
    source_instance = serializers.RegexField(r"^[a-zA-Z0-9_-]{1,80}$")
    external_project_id = serializers.IntegerField(min_value=1, required=False)
    full = serializers.BooleanField(default=False)


class CatalogTaskSerializer(serializers.ModelSerializer):
    issue_state = serializers.SerializerMethodField()

    def get_issue_state(self, obj):
        if not obj.issue_id:
            return "unlinked"
        issue = obj.issue
        if issue.deleted_at:
            return "deleted"
        if issue.project_id != obj.project_id:
            return "moved"
        return "archived" if issue.archived_at else "active"

    class Meta:
        model = PlatformCatalogTask
        fields = ["id", "external_id", "name", "source_status", "active", "issue_id", "issue_state"]


def representation(row):
    return {
        "id": str(row.id),
        "source_instance": row.source_instance,
        "source_project": row.source_project,
        "members": row.members,
        "synced_at": row.synced_at,
        "task_watermark": row.task_watermark,
        "tasks": CatalogTaskSerializer(row.tasks.select_related("issue").order_by("external_id")[:50], many=True).data,
        "task_count": row.tasks.count(),
    }


class CatalogSync(QualityView):
    def get(self, request, **kwargs):
        management(self)
        return Response(
            {"results": [representation(row) for row in PlatformCatalog.objects.filter(project=self.project())]}
        )

    @transaction.atomic
    def post(self, request, **kwargs):
        management(self)
        data = self.input(CatalogInput)
        project = self.project()
        # Serialize the complete fetch/apply cycle; failed pages roll back without advancing a cursor.
        type(project).objects.select_for_update().get(pk=project.pk)
        mappings = PlatformProject.objects.select_for_update().filter(
            project=project, source_instance=data["source_instance"], active=True
        )
        if data.get("external_project_id"):
            mappings = mappings.filter(external_project_id=data["external_project_id"])
        if mappings.count() != 1:
            raise Conflict("请选择要同步的数据管理平台项目。")
        mapping = mappings.get()
        old = PlatformCatalog.objects.filter(
            project=project, source_instance=mapping.source_instance, external_project_id=mapping.external_project_id
        ).first()
        source_projects, _ = pages(mapping.source_instance, "/internal/issue-integration/catalog/projects")
        source = next((item for item in source_projects if item["id"] == mapping.external_project_id), None)
        inactive_project = source is None or source.get("status", "").upper() in INACTIVE
        after = old.task_watermark if old and not data["full"] else ""
        tasks, watermark, members = [], "", []
        if not inactive_project:
            root = f"/internal/issue-integration/catalog/projects/{mapping.external_project_id}"
            tasks, watermark = pages(mapping.source_instance, root + "/tasks", after)
            for task in tasks:
                if (
                    task.get("projectId") != mapping.external_project_id
                    or not isinstance(task.get("description") or "", str)
                    or len(task.get("description") or "") > 20000
                    or not isinstance(task.get("updatedAt") or "", str)
                    or len(task.get("updatedAt") or "") > 80
                ):
                    raise platform.PlatformUnavailable("来源任务归属或正文无效，未应用同步。")
            raw_members = platform.fetch(mapping.source_instance, root + "/members")
            if not isinstance(raw_members, list) or len(raw_members) > 2000:
                raise platform.PlatformUnavailable("来源成员完整快照无效，未应用同步。")
            seen = set()
            for member in raw_members:
                if (
                    not isinstance(member, dict)
                    or not positive_id(member.get("userId"))
                    or member["userId"] in seen
                    or type(member.get("active")) is not bool
                    or any(
                        not isinstance(member.get(key, ""), str) or len(member.get(key, "")) > 255
                        for key in ["displayName", "userRole", "projectRole"]
                    )
                ):
                    raise platform.PlatformUnavailable("来源成员条目无效，未应用同步。")
                seen.add(member["userId"])
                members.append(
                    {key: member.get(key, "") for key in ["userId", "displayName", "userRole", "projectRole", "active"]}
                )
        identities = PlatformIdentity.objects.filter(
            project=project, source_instance=mapping.source_instance, active=True
        )
        active_members = {member["userId"]: member for member in members if member["active"]}
        other_projects = list(
            PlatformProject.objects.filter(
                project=project, source_instance=mapping.source_instance, active=True
            ).exclude(pk=mapping.pk)
        )
        if other_projects:
            for other in other_projects:
                values = platform.fetch(
                    mapping.source_instance,
                    f"/internal/issue-integration/catalog/projects/{other.external_project_id}/members",
                )
                if not isinstance(values, list):
                    raise platform.PlatformUnavailable("其他来源项目成员快照无效，未更改授权。")
                for value in values:
                    if (
                        not isinstance(value, dict)
                        or not positive_id(value.get("userId"))
                        or type(value.get("active")) is not bool
                    ):
                        raise platform.PlatformUnavailable("来源成员快照无效。")
                    if value["active"]:
                        active_members[value["userId"]] = value
        revoked = []
        for identity in identities:
            member = active_members.get(identity.external_user_id)
            if not member or (has_role(project.id, identity.user_id, "REPORTER") and member["userRole"] != "Collector"):
                identity.active = False
                identity.save(update_fields=["active"])
                revoked.append(identity.id)
                QualityLifecycleEvent.objects.create(
                    project=project,
                    created_by=request.user,
                    resource="identity",
                    object_id=identity.id,
                    action="source_revoke",
                    reason="完整权威成员目录显示身份停用、移除或采集职责撤销。",
                    before_version=1,
                    after_version=2,
                )
        row, _ = PlatformCatalog.objects.get_or_create(
            project=project,
            source_instance=mapping.source_instance,
            external_project_id=mapping.external_project_id,
            defaults={"created_by": request.user},
        )
        row.source_project = (
            {key: source.get(key) for key in ["id", "name", "status", "updatedAt"]}
            if source
            else {"id": mapping.external_project_id, "name": "来源项目已移除", "status": "DELETED"}
        )
        row.members, row.synced_at = members, timezone.now()
        if inactive_project:
            mapping.active = False
            mapping.save(update_fields=["active"])
            row.tasks.update(active=False)
        else:
            if not after:
                row.tasks.exclude(external_id__in=[task["id"] for task in tasks]).update(active=False)
            for task in tasks:
                PlatformCatalogTask.objects.update_or_create(
                    catalog=row,
                    external_id=task["id"],
                    defaults={
                        "project": project,
                        "name": task["name"],
                        "description": task.get("description") or "",
                        "source_status": task.get("status", ""),
                        "source_updated_at": task.get("updatedAt") or "",
                        "active": task.get("status", "").upper() not in INACTIVE,
                    },
                )
            row.task_watermark = watermark
        row.save()
        return Response(
            {
                "status": "synchronized",
                "revoked_identities": len(revoked),
                "task_changes": len(tasks),
                "project_active": not inactive_project,
                "catalog": representation(row),
            }
        )


class CatalogTasks(QualityView):
    def get(self, request, pk, **kwargs):
        management(self)
        row = self.obj(PlatformCatalog, pk)
        tasks = row.tasks.select_related("issue").order_by("external_id")
        term = serializers.CharField(max_length=255, allow_blank=True).run_validation(
            request.query_params.get("search", "")
        )
        if term.strip():
            tasks = tasks.filter(name__icontains=term.strip())
        return self.listing(tasks, CatalogTaskSerializer)


class CatalogTaskImport(QualityView):
    @transaction.atomic
    def post(self, request, pk, **kwargs):
        management(self)
        project = self.project()
        type(project).objects.select_for_update().get(pk=project.pk)
        task = get_object_or_404(
            PlatformCatalogTask.objects.select_for_update(of=("self",)).select_related("catalog", "project"),
            pk=pk,
            project_id=self.project_id,
        )
        if (
            not task.active
            or not PlatformProject.objects.filter(
                project_id=self.project_id, source_instance=task.catalog.source_instance, active=True
            )
            .filter(
                **(
                    {"external_project_id": task.catalog.external_project_id}
                    if task.catalog.external_project_id
                    else {}
                )
            )
            .exists()
            or (
                not task.catalog.external_project_id
                and PlatformProject.objects.filter(
                    project_id=self.project_id, source_instance=task.catalog.source_instance, active=True
                ).count()
                != 1
            )
        ):
            raise Conflict("来源项目或任务已失效，请先核对目录。")
        if task.issue_id:
            if not Issue.objects.filter(
                pk=task.issue_id, project_id=self.project_id, archived_at__isnull=True
            ).exists():
                raise Conflict("原工作项已移除、归档或移动，来源历史仍保留；请在工作项管理中核对或恢复。")
            return Response({"issue_id": str(task.issue_id)})
        state = State.objects.filter(project=project, group__in=["backlog", "unstarted"]).order_by("sequence").first()
        if state is None:
            state = State.objects.create(
                project=project, workspace=project.workspace, name="待规划", group="backlog", color="#60646C"
            )
        issue = Issue.objects.create(
            project=task.project,
            workspace=task.project.workspace,
            name=task.name,
            description_html="<p>" + escape(task.description).replace("\n", "<br>\n") + "</p>",
            created_by=request.user,
            state=state,
        )
        task.issue = issue
        task.save(update_fields=["issue"])
        QualityLifecycleEvent.objects.create(
            project=task.project,
            created_by=request.user,
            resource="catalog_task",
            object_id=task.id,
            action="import",
            reason=f"明确导入外部任务 {task.external_id}，以后独立维护底座状态。",
            before_version=1,
            after_version=2,
        )
        return Response({"issue_id": str(issue.id)}, status=201)
