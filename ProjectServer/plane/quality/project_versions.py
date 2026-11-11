# SPDX-License-Identifier: AGPL-3.0-only
"""Business version planning. Workflow projections never invent business completion."""

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db.models import Q
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from plane.db.models import Issue, IssueAssignee, ProjectMember, Cycle, Project
from .models import ProjectVersion, ProjectVersionEvent, Requirement, TestPlan, Defect, Release, PlanEvent
from .authorship import AuthoredRecordSerializer, authored_metadata
from .views import QualityView, Conflict
from .permissions import strict, capable, writable_member, require_assignee
from .project_report import report_access
from .assets import readiness
from .history import event_page

PHASES = ["planning", "development", "testing", "ready", "released"]
MODELS = {"issue": Issue, "requirement": Requirement, "plan": TestPlan, "defect": Defect}


def is_manager(project_id, user):
    if not user.is_active or not Project.objects.filter(pk=project_id, archived_at__isnull=True).exists():
        return False
    return writable_member(
        project_id,
        user.id,
        Project.objects.get(pk=project_id).workspace.slug,
    ) and (
        capable(project_id, user.id, "manage_test")
        if strict(project_id)
        else ProjectMember.objects.filter(project_id=project_id, member=user, is_active=True, role=20).exists()
    )


def manager(view):
    if not is_manager(view.project_id, view.request.user):
        raise PermissionDenied("版本规划和流程分派由项目经理负责。")


class NodeInput(serializers.Serializer):
    id = serializers.RegexField(r"^[a-zA-Z0-9_-]{1,40}$")
    name = serializers.CharField(max_length=160)
    kind = serializers.ChoiceField(choices=["issue", "requirement", "plan", "defect", "milestone"])
    object_id = serializers.UUIDField(required=False)
    owner_id = serializers.UUIDField(required=False, allow_null=True)
    depends_on = serializers.ListField(child=serializers.CharField(max_length=40), max_length=100, default=list)
    join = serializers.ChoiceField(choices=["all", "any"], default="all")
    required = serializers.BooleanField(default=True)
    target_date = serializers.DateField(required=False, allow_null=True)


class VersionInput(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    version = serializers.CharField(max_length=120)
    description = serializers.CharField(max_length=20000, allow_blank=True, default="")
    start_date = serializers.DateField(required=False, allow_null=True)
    target_date = serializers.DateField(required=False, allow_null=True)
    owner_id = serializers.UUIDField(required=False, allow_null=True)
    cycle_id = serializers.UUIDField(required=False, allow_null=True)
    quality_release_id = serializers.UUIDField(required=False, allow_null=True)
    flow_nodes = NodeInput(many=True, required=False, max_length=100)
    expected_version = serializers.IntegerField(required=False, min_value=1)


def validate_flow(view, nodes):
    ids = [node["id"] for node in nodes]
    if len(set(ids)) != len(ids):
        raise ValidationError({"flow_nodes": "节点编号不能重复。"})
    references = set()
    for node in nodes:
        if any(dep not in ids or dep == node["id"] for dep in node["depends_on"]):
            raise ValidationError({"flow_nodes": "前置节点不存在或指向自身。"})
        owner = node.get("owner_id")
        if owner:
            view.validate_assignee(owner)
            if node["kind"] in {"plan", "defect"}:
                require_assignee(view, owner, "REGRESSION_TESTER" if node["kind"] == "plan" else "TECHNICIAN")
        if node["kind"] != "milestone":
            if not node.get("object_id"):
                raise ValidationError({"flow_nodes": "请关联已有记录。"})
            field = "issue_id" if node["kind"] == "requirement" else "id"
            model = MODELS[node["kind"]]
            qs = model.issue_objects.all() if node["kind"] == "issue" else model.objects.all()
            if not qs.filter(project_id=view.project_id, **{field: node["object_id"]}).exists():
                raise ValidationError({"flow_nodes": "关联记录不存在、已归档或不属于当前项目。"})
            ref = (node["kind"], str(node["object_id"]))
            if ref in references:
                raise ValidationError({"flow_nodes": "同一业务记录不能重复成为流程节点。"})
            references.add(ref)
            node["object_id"] = str(node["object_id"])
        if owner:
            node["owner_id"] = str(owner)
        if node.get("target_date"):
            node["target_date"] = node["target_date"].isoformat()
    done = set()
    while len(done) < len(nodes):
        ready = {
            node["id"] for node in nodes if node["id"] not in done and all(dep in done for dep in node["depends_on"])
        }
        if not ready:
            raise ValidationError({"flow_nodes": "存在循环依赖，请调整连线。"})
        done |= ready
    return nodes


def validate_data(view, data, row=None):
    start = data.get("start_date", row.start_date if row else None)
    end = data.get("target_date", row.target_date if row else None)
    if start and end and start > end:
        raise ValidationError({"target_date": "目标日期不能早于开始日期。"})
    if data.get("owner_id"):
        view.validate_assignee(data["owner_id"])
    if data.get("cycle_id") and not Cycle.objects.filter(project_id=view.project_id, id=data["cycle_id"]).exists():
        raise ValidationError({"cycle_id": "请选择本项目迭代周期。"})
    if data.get("quality_release_id"):
        release = get_object_or_404(Release, project_id=view.project_id, id=data["quality_release_id"])
        if release.version != data.get("version", row.version if row else ""):
            raise ValidationError({"quality_release_id": "发布检查版本必须与业务版本一致。"})
    if "flow_nodes" in data:
        data["flow_nodes"] = validate_flow(view, data["flow_nodes"])
    if (
        ProjectVersion.objects.filter(
            project_id=view.project_id, version=data.get("version", row.version if row else "")
        )
        .exclude(pk=row.pk if row else None)
        .exists()
    ):
        raise Conflict("当前项目已存在相同版本。")
    return data


def event(row, actor, action, note="", before=""):
    ProjectVersionEvent.objects.create(
        project=row.project,
        created_by=actor,
        version=row,
        action=action,
        note=note,
        before_status=before,
        status=row.status,
        snapshot={
            "edit_version": row.edit_version,
            "automation_enabled": row.automation_enabled,
            "flow_state": row.flow_state,
            "flow_nodes": row.flow_nodes,
        },
    )


def actual_node(row, node):
    if node["kind"] == "milestone":
        return None
    model = MODELS[node["kind"]]
    field = "issue_id" if node["kind"] == "requirement" else "id"
    qs = model.issue_objects.all() if node["kind"] == "issue" else model.objects.all()
    if node["kind"] in {"plan", "defect"}:
        qs = qs.filter(archived_at__isnull=True)
    return qs.filter(project=row.project, **{field: node.get("object_id")}).first()


def flow_projection(row):
    if row.status == "released" and row.published_snapshot.get("flow_state") is not None:
        return row.published_snapshot["flow_state"]
    states = {}
    remaining = list(row.flow_nodes)
    for _ in range(len(remaining) + 1):
        ready = [node for node in remaining if all(dep in states for dep in node["depends_on"])]
        if not ready:
            break
        for node in ready:
            parents = [states[dep]["status"] == "completed" for dep in node["depends_on"]]
            dependencies = not parents or (all(parents) if node.get("join", "all") == "all" else any(parents))
            obj = actual_node(row, node)
            if node["kind"] == "milestone":
                complete = row.flow_state.get(node["id"], {}).get("manual_completed", False)
                business = "里程碑已确认" if complete else "待确认里程碑"
            elif obj is None:
                complete = False
                business = "关联记录已不可用"
            elif node["kind"] == "issue":
                complete = bool(obj.state_id and obj.state.group == "completed")
                business = obj.state.name if obj.state_id else "未安排状态"
            elif node["kind"] == "requirement":
                complete = obj.status == "completed"
                business = obj.status
            elif node["kind"] == "plan":
                from .views import plan_queryset
                from .serializers import plan_summary

                summary = plan_summary(plan_queryset().get(pk=obj.pk))
                complete = (
                    summary["total"] > 0
                    and summary["passed"] == summary["total"]
                    and (not obj.managed or obj.status == "completed")
                )
                business = obj.status
            else:
                complete = obj.status == "closed"
                business = obj.status
            previous = row.flow_state.get(node["id"], {})
            status = (
                "completed"
                if complete
                else "blocked"
                if node["kind"] != "milestone" and obj is None
                else "ready"
                if dependencies
                else "waiting"
            )
            # Dependency reopening invalidates downstream completion in the workflow, not the underlying record.
            if complete and not dependencies:
                status = "waiting"
            states[node["id"]] = {
                "status": status,
                "business_status": business,
                "manual_completed": bool(previous.get("manual_completed")),
                "dispatched": bool(previous.get("dispatched")),
                "notice": previous.get("notice", ""),
            }
            remaining.remove(node)
    return states


def linked(row):
    issues = Issue.issue_objects.filter(project=row.project)
    requirements = Requirement.objects.filter(
        project=row.project, target_build=row.version, issue_id__in=issues.values("id")
    ).select_related("issue")
    tasks = issues.filter(
        Q(parent_id__in=requirements.values("issue_id"))
        | Q(pk__in=[node.get("object_id") for node in row.flow_nodes if node["kind"] == "issue"])
    )
    plans = TestPlan.objects.filter(project=row.project, build=row.version, archived_at__isnull=True)
    defects = Defect.objects.filter(project=row.project, archived_at__isnull=True).filter(
        Q(affected_build=row.version) | Q(fixed_build=row.version)
    )
    return requirements, tasks, plans, defects


def blockers(row):
    if row.status == "released":
        return []
    requirements, tasks, plans, defects = linked(row)
    result = []
    pending = requirements.exclude(status__in=["completed", "cancelled"]).count()
    if pending:
        result.append(f"仍有 {pending} 条需求尚未验收。")
    pending = tasks.exclude(state__group="completed").count()
    if pending:
        result.append(f"仍有 {pending} 条开发任务未完成。")
    pending = defects.exclude(status="closed").count()
    if pending:
        result.append(f"仍有 {pending} 个关联缺陷未关闭。")
    if plans.exists() or row.quality_release_id:
        if not row.quality_release_id:
            result.append("已有版本测试计划，请关联同版本发布检查并完成准入。")
        elif row.quality_release.status != "admitted" or not readiness(row.quality_release)["ready"]:
            result.append("关联发布检查尚未通过，或质量条件已变化。")
    states = flow_projection(row)
    if any(
        node.get("required", True) and states.get(node["id"], {}).get("status") != "completed"
        for node in row.flow_nodes
    ):
        result.append("必需流程节点或里程碑尚未完成。")
    return result


def detail(row, request=None):
    selected, pagination = event_page(row.events.select_related("created_by").order_by("-created_at", "-id"), request)
    requirements, tasks, plans, defects = linked(row)
    from .numbering import metadata

    return {
        **authored_metadata(row),
        **metadata(row),
        "id": str(row.id),
        "name": row.name,
        "version": row.version,
        "description": row.description,
        "status": row.status,
        "start_date": row.start_date,
        "target_date": row.target_date,
        "owner_id": str(row.owner_id) if row.owner_id else None,
        "owner_name": row.owner.display_name if row.owner_id else "未指定负责人",
        "cycle_id": str(row.cycle_id) if row.cycle_id else None,
        "cycle_name": row.cycle.name if row.cycle_id else "",
        "quality_release_id": str(row.quality_release_id) if row.quality_release_id else None,
        "edit_version": row.edit_version,
        "automation_enabled": row.automation_enabled,
        "automation_note": row.automation_note,
        "flow_nodes": row.flow_nodes,
        "flow_state": flow_projection(row),
        "published_at": row.published_at,
        "published_snapshot": row.published_snapshot,
        "blockers": blockers(row),
        "requirements": [
            {
                "id": str(item.issue_id),
                "name": item.issue.name,
                "status": item.status,
                "version": item.version,
                "code": f"{row.project.identifier}-R-{item.number}",
            }
            for item in requirements
        ],
        "tasks": [
            {
                "id": str(item.id),
                "name": item.name,
                "status": item.state.name if item.state_id else "未安排",
                "code": f"{row.project.identifier}-T-{item.sequence_id}",
                "done": item.state_id is not None and item.state.group == "completed",
                "start_date": item.start_date,
                "target_date": item.target_date,
            }
            for item in tasks.select_related("state")
        ],
        "plans": [{"id": str(item.id), "name": item.name, "status": item.status, **metadata(item)} for item in plans],
        "defects": [
            {"id": str(item.id), "name": item.title, "status": item.status, **metadata(item)} for item in defects
        ],
        "events": [
            {
                "id": str(item.id),
                "action": item.action,
                "note": item.note,
                "status": item.status,
                "created_at": item.created_at,
                "actor": item.created_by.display_name if item.created_by else "系统",
            }
            for item in selected
        ],
        "event_pagination": pagination,
    }


class ProjectVersions(QualityView):
    def get(self, request, **kwargs):
        report_access(self)
        qs = (
            ProjectVersion.objects.filter(project=self.project())
            .select_related("owner", "cycle", "quality_release")
            .order_by("-created_at", "id")
        )
        return self.listing(qs, VersionSummary)

    @transaction.atomic
    def post(self, request, **kwargs):
        manager(self)

        Project.objects.select_for_update().get(pk=self.project_id)
        data = validate_data(self, self.input(VersionInput))
        data.pop("expected_version", None)
        row = ProjectVersion.objects.create(project=self.project(), created_by=request.user, **data)
        event(row, request.user, "create", "创建版本规划")
        return Response(detail(row), status=201)


class VersionSummary(AuthoredRecordSerializer):
    owner_name = serializers.CharField(source="owner.display_name", default="未指定负责人")
    cycle_name = serializers.CharField(source="cycle.name", default="")

    class Meta:
        model = ProjectVersion
        fields = [
            "id",
            "name",
            "version",
            "description",
            "status",
            "start_date",
            "target_date",
            "owner_id",
            "owner_name",
            "cycle_id",
            "cycle_name",
            "edit_version",
            "automation_enabled",
        ]


class ProjectVersionDetail(QualityView):
    def get(self, request, pk, **kwargs):
        report_access(self)
        return Response(detail(self.obj(ProjectVersion, pk), request))

    @transaction.atomic
    def patch(self, request, pk, **kwargs):
        Project.objects.select_for_update().get(pk=self.project_id)
        manager(self)
        row = get_object_or_404(ProjectVersion.objects.select_for_update(), project_id=self.project_id, pk=pk)
        data = self.input(VersionInput, partial=True)
        if data.pop("expected_version", None) != row.edit_version:
            raise Conflict()
        if row.status in {"released", "cancelled"}:
            raise Conflict("已结束版本保留历史，请新建后续版本。")
        if row.automation_enabled:
            raise Conflict("请先切换到跟踪模式，再编辑流程或计划。")
        validate_data(self, data, row)
        if "version" in data and data["version"] != row.version:
            raise Conflict("版本号已建立，请新建版本；可调整版本名称和日期。")
        if "flow_nodes" in data:
            row.flow_state = {}
        for key, value in data.items():
            setattr(row, key, value)
        row.edit_version += 1
        row.save()
        event(row, request.user, "edit", "更新版本计划或分工")
        return Response(detail(row))


class ActionInput(serializers.Serializer):
    action = serializers.ChoiceField(
        choices=["advance", "back", "cancel", "enable_automation", "disable_automation", "complete_node", "reopen_node"]
    )
    expected_version = serializers.IntegerField(min_value=1)
    note = serializers.CharField(max_length=4000, allow_blank=False)
    node_id = serializers.CharField(max_length=40, required=False)


def dispatch_ready(row):
    """Assign ready records once, without changing completion, test evidence, or approvals."""
    if not row.automation_enabled:
        return
    actor = row.automation_by
    if not actor or not is_manager(row.project_id, actor):
        row.automation_enabled = False
        row.automation_note = "启用人已无项目经理权限，自动流转已暂停。"
        event(row, actor, "automation_paused", row.automation_note)
        return
    states = flow_projection(row)
    changed = False
    for node in row.flow_nodes:
        state = states[node["id"]]
        if state["status"] != "ready" or state["dispatched"] or node["kind"] == "milestone":
            continue
        owner = node.get("owner_id")
        if not owner:
            continue
        obj = actual_node(row, node)
        if not obj:
            continue
        if (
            not writable_member(row.project_id, owner, row.project.workspace.slug)
            or not ProjectMember.objects.filter(
                project=row.project, member_id=owner, member__is_active=True, is_active=True
            ).exists()
        ):
            state["notice"] = "节点负责人已无有效项目权限，请经理调整。"
            continue
        from .permissions import roles_for

        assigned_roles = roles_for(row.project_id, owner)
        expected = "REGRESSION_TESTER" if node["kind"] == "plan" else "TECHNICIAN"
        if strict(row.project_id) and not assigned_roles.intersection(
            {expected, "PLATFORM_ADMIN", "PROJECT_MANAGER"}
            if node["kind"] in {"issue", "requirement"} else {expected, "PLATFORM_ADMIN"}
        ):
            state["notice"] = "负责人业务角色与当前节点不匹配。"
            continue
        from .notifications import notify

        if node["kind"] in {"issue", "requirement"}:
            issue = obj.issue if node["kind"] == "requirement" else obj
            issue = Issue.objects.select_for_update().get(pk=issue.pk)
            assigned = list(issue.assignees.values_list("id", flat=True))
            if assigned and str(owner) not in {str(pk) for pk in assigned}:
                state["notice"] = "记录已有其他负责人，请经理交接后再流转。"
                continue
            IssueAssignee.objects.get_or_create(
                project=issue.project, workspace=issue.workspace, issue=issue, assignee_id=owner
            )
            path = f"issues/{issue.id}/"
        elif node["kind"] == "plan":
            obj = TestPlan.objects.select_for_update().get(pk=obj.pk)
            if not obj.managed or obj.status not in {"pending", "ready", "returned"}:
                state["notice"] = "计划未启用分派验收，或当前阶段不允许重新分派。"
                continue
            if obj.assignee_id and str(obj.assignee_id) != owner:
                state["notice"] = "计划已有其他负责人，请经理调整分派。"
                continue
            previous = obj.status
            obj.assignee_id = owner
            obj.status = "ready"
            obj.workflow_version += 1
            obj.save()
            PlanEvent.objects.create(
                project=row.project,
                created_by=actor,
                plan=obj,
                action="assign",
                previous_status=previous,
                status="ready",
                round_no=obj.round_no,
                note=f"版本流程分派：{row.version} / {node['name']}",
            )
            path = f"quality?tab=plans&plan={obj.pk}"
        else:
            obj = Defect.objects.select_for_update().get(pk=obj.pk)
            if obj.pending_assignee_id or obj.assignee_id and str(obj.assignee_id) != owner:
                state["notice"] = "缺陷已有负责人或待确认交接，请先处理交接。"
                continue
            obj.assignee_id = owner
            obj.edit_version += 1
            obj.save()
            from .models import DefectEvent

            DefectEvent.objects.create(
                project=row.project,
                created_by=actor,
                defect=obj,
                previous_status=obj.status,
                status=obj.status,
                note=f"版本流程分派：{row.version} / {node['name']}",
            )
            path = f"defects?defect={obj.pk}"
        state["dispatched"] = True
        state["notice"] = "已分派，等待负责人处理。"
        changed = True
        notify(row.project, actor, [owner], obj.pk, f"版本 {row.version}：{node['name']} 已就绪", path)
        event(row, actor, "dispatch", f"节点 {node['name']} 就绪，已分派指定负责人。")
    row.flow_state = states
    if changed:
        row.automation_note = "依赖满足后自动分派；审批与完成仍由业务人员确认。"


class ProjectVersionWorkflow(QualityView):
    @transaction.atomic
    def post(self, request, pk, **kwargs):
        Project.objects.select_for_update().get(pk=self.project_id)
        manager(self)
        row = get_object_or_404(ProjectVersion.objects.select_for_update(), project_id=self.project_id, pk=pk)
        data = self.input(ActionInput)
        if data["expected_version"] != row.edit_version:
            raise Conflict()
        action = data["action"]
        before = row.status
        if row.status in {"released", "cancelled"}:
            raise Conflict("已结束版本保留历史，请新建后续版本。")
        if action == "enable_automation":
            if not row.flow_nodes:
                raise ValidationError({"flow_nodes": "请先配置流程节点和依赖关系。"})
            row.automation_enabled = True
            row.automation_by = request.user
            row.automation_note = "已启用自动分派；需求验收、测试结果和发布仍需人工确认。"
            from django_celery_beat.models import IntervalSchedule, PeriodicTask

            schedule, _ = IntervalSchedule.objects.get_or_create(every=30, period=IntervalSchedule.SECONDS)
            PeriodicTask.objects.update_or_create(
                name="native-project-version-flow",
                defaults={"task": "plane.quality.tasks.sync_project_versions", "interval": schedule, "enabled": True},
            )
            dispatch_ready(row)
        elif action == "disable_automation":
            row.automation_enabled = False
            row.automation_note = "跟踪模式：仅展示进展，由负责人手动推进。"
        elif action in {"complete_node", "reopen_node"}:
            node = next((node for node in row.flow_nodes if node["id"] == data.get("node_id")), None)
            if not node or node["kind"] != "milestone":
                raise ValidationError({"node_id": "只可手动确认里程碑；业务记录须在原页面完成。"})
            states = flow_projection(row)
            if action == "complete_node" and states[node["id"]]["status"] != "ready":
                raise Conflict("前置条件尚未满足，不能确认此里程碑。")
            states[node["id"]]["manual_completed"] = action == "complete_node"
            row.flow_state = states
            if row.automation_enabled:
                dispatch_ready(row)
        elif action == "cancel":
            row.status = "cancelled"
            row.automation_enabled = False
        elif action == "back":
            index = PHASES.index(row.status)
            if index == 0:
                raise Conflict("当前已在规划阶段。")
            row.status = PHASES[index - 1]
        else:
            index = PHASES.index(row.status)
            if index == len(PHASES) - 2:
                Project.objects.select_for_update().get(pk=row.project_id)
                problems = blockers(row)
                if problems:
                    raise Conflict("无法发布：" + "；".join(problems))
                requirements, tasks, plans, defects = linked(row)
                row.published_at = timezone.now()
                row.published_snapshot = {
                    "requirements": [
                        {
                            "id": str(item.issue_id),
                            "version": item.version,
                            "status": item.status,
                            "title": item.issue.name,
                        }
                        for item in requirements
                    ],
                    "tasks": [
                        {
                            "id": str(item.id),
                            "status": item.state.name if item.state_id else "未安排",
                            "title": item.name,
                        }
                        for item in tasks.select_related("state")
                    ],
                    "plans": [
                        {
                            "id": str(item.id),
                            "status": item.status,
                            "workflow_version": item.workflow_version,
                            "title": item.name,
                        }
                        for item in plans
                    ],
                    "defects": [
                        {
                            "id": str(item.id),
                            "status": item.status,
                            "edit_version": item.edit_version,
                            "title": item.title,
                        }
                        for item in defects
                    ],
                    "quality_release_id": str(row.quality_release_id) if row.quality_release_id else None,
                    "version": row.version,
                    "note": data["note"],
                    "actor": str(request.user.id),
                    "flow_state": flow_projection(row),
                }
                row.automation_enabled = False
            row.status = PHASES[index + 1]
        row.edit_version += 1
        row.save()
        event(row, request.user, action, data["note"], before)
        return Response(detail(row))


class ProjectVersionSync(QualityView):
    @transaction.atomic
    def post(self, request, pk, **kwargs):
        Project.objects.select_for_update().get(pk=self.project_id)
        manager(self)
        row = get_object_or_404(ProjectVersion.objects.select_for_update(), project_id=self.project_id, pk=pk)
        if row.status in {"released", "cancelled"}:
            return Response(detail(row))
        if row.automation_enabled:
            dispatch_ready(row)
        else:
            row.flow_state = flow_projection(row)
        row.save(update_fields=["flow_state", "automation_enabled", "automation_note"])
        return Response(detail(row))


class ProjectVersionOptions(QualityView):
    def get(self, request, **kwargs):
        report_access(self)
        kind = serializers.ChoiceField(choices=list(MODELS) + ["cycle", "release"]).run_validation(
            request.query_params.get("kind", "issue")
        )
        search = serializers.CharField(max_length=160, allow_blank=True).run_validation(
            request.query_params.get("search", "")
        )
        page = serializers.IntegerField(min_value=1).run_validation(request.query_params.get("page", 1))
        per_page = serializers.IntegerField(min_value=1, max_value=100).run_validation(
            request.query_params.get("per_page", 25)
        )
        offset = (page - 1) * per_page
        project = self.project()
        if kind == "cycle":
            qs = Cycle.objects.filter(project=project, name__icontains=search).order_by("-created_at", "id")
            rows = [{"id": str(row.id), "name": row.name} for row in qs[offset : offset + per_page]]
        elif kind == "release":
            qs = (
                Release.objects.filter(project=project)
                .filter(Q(name__icontains=search) | Q(version__icontains=search))
                .order_by("-created_at", "id")
            )
            rows = [
                {"id": str(row.id), "name": f"{row.version} · {row.name}", "version": row.version}
                for row in qs[offset : offset + per_page]
            ]
        else:
            qs = (
                MODELS[kind].issue_objects.filter(project=project)
                if kind == "issue"
                else MODELS[kind].objects.filter(project=project)
            )
            if kind in {"defect", "plan"}:
                qs = qs.filter(archived_at__isnull=True)
            field = "issue__name" if kind == "requirement" else "name" if kind in {"issue", "plan"} else "title"
            if kind in {"plan", "defect", "requirement"}:
                from .filters import filter_records

                qs = filter_records(qs, {"search": search}, request.user)
            else:
                qs = qs.filter(**{field + "__icontains": search})
            qs = qs.order_by("-created_at", "id")
            rows = [
                {
                    "id": str(row.issue_id if kind == "requirement" else row.id),
                    "name": row.issue.name
                    if kind == "requirement"
                    else row.name
                    if kind in {"issue", "plan"}
                    else row.title,
                    "code": f"{project.identifier}-R-{row.number}"
                    if kind == "requirement"
                    else row.code
                    if kind in {"plan", "defect"}
                    else f"{project.identifier}-T-{row.sequence_id}",
                }
                for row in qs[offset : offset + per_page]
            ]
        count = qs.count()
        return Response(
            {
                "results": rows,
                "count": count,
                "page": page,
                "per_page": per_page,
                "next": page + 1 if offset + per_page < count else None,
                "previous": page - 1 if page > 1 else None,
            }
        )
