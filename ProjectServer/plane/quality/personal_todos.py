"""A paginated personal action queue over current project and duty permissions."""

from django.db.models import Case, When, CharField, DateField, F, Q, Value, Exists, OuterRef, Subquery
from django.db.models.functions import Cast, Concat, Coalesce
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from plane.app.views.base import BaseAPIView
from plane.db.models import ProjectMember, WorkspaceMember, Issue, IssueAssignee
from .models import (
    BusinessNumber,
    ProjectRolePolicy,
    Defect,
    TestPlan,
    SolutionRevision,
    SolutionReview,
    DataRegression,
    Requirement,
    PlanItem,
    TestExecution,
)
from .permissions import ROLE_CAPABILITIES, roles_for
from .views import QualityPagination

KINDS = {
    "task": "研发任务",
    "requirement": "需求",
    "defect": "缺陷",
    "solution": "方案审核",
    "plan": "测试计划",
}


class TodoQuery(serializers.Serializer):
    workspace = serializers.SlugField(max_length=255)
    kind = serializers.ChoiceField(choices=list(KINDS), required=False)
    search = serializers.CharField(max_length=160, allow_blank=True, default="")
    project_id = serializers.UUIDField(required=False)
    per_page = serializers.IntegerField(min_value=1, max_value=100, required=False)


def permitted_projects(user, workspace):
    membership = WorkspaceMember.objects.filter(workspace__slug=workspace, member=user, is_active=True).first()
    if not user.is_active or membership is None:
        raise PermissionDenied("当前账号没有此工作空间的工作权限。")
    if membership.role < 15:
        return [], [], [], [], []
    memberships = dict(
        ProjectMember.objects.filter(
            project__workspace__slug=workspace,
            project__archived_at__isnull=True,
            member=user,
            is_active=True,
            role__gte=15,
        ).values_list("project_id", "role")
    )
    strict = set(
        ProjectRolePolicy.objects.filter(project_id__in=memberships, enabled=True).values_list("project_id", flat=True)
    )
    duties = {project_id: roles_for(project_id, user.id) for project_id in strict}

    def allowed(capability):
        return [
            pk
            for pk in memberships
            if pk not in strict
            or any(capability in ROLE_CAPABILITIES.get(role, set()) for role in duties.get(pk, set()))
        ]

    native = [
        pk
        for pk in memberships
        if pk not in strict or duties.get(pk, set()) & {"PLATFORM_ADMIN", "TECHNICIAN", "PROJECT_MANAGER"}
    ]
    managers = [
        pk
        for pk, role in memberships.items()
        if pk not in strict
        and role == 20
        or pk in strict
        and any("manage_test" in ROLE_CAPABILITIES.get(d, set()) for d in duties.get(pk, set()))
    ]
    return native, allowed("manage_defect"), allowed("execute"), allowed("review"), managers


FIELDS = [
    "todo_id",
    "todo_title",
    "todo_kind",
    "todo_status",
    "todo_code",
    "todo_project",
    "todo_project_name",
    "todo_project_key",
    "todo_created",
    "todo_due",
    "todo_target",
    "todo_responsibility",
    "todo_action",
]


def projection(
    query,
    kind,
    title,
    status,
    resource,
    *,
    target="id",
    responsibility="负责",
    action="继续处理",
    due=None,
    code_expression=None,
    code_object="pk",
):
    code = Subquery(
        BusinessNumber.objects.filter(
            resource=resource, object_id=OuterRef(code_object), project_id=OuterRef("project_id")
        ).values("code")[:1]
    )
    return (
        query.order_by()
        .annotate(
            todo_id=Cast("pk", CharField()),
            todo_title=F(title),
            todo_kind=kind if hasattr(kind, "resolve_expression") else Value(kind),
            todo_status=F(status) if isinstance(status, str) else status,
            todo_code=code_expression if code_expression is not None else Coalesce(code, Value("")),
            todo_project=Cast("project_id", CharField()),
            todo_project_name=F("project__name"),
            todo_project_key=F("project__identifier"),
            todo_created=F("created_at"),
            todo_due=F(due) if due else Value(None, output_field=DateField()),
            todo_target=Cast(target, CharField()),
            todo_responsibility=responsibility
            if hasattr(responsibility, "resolve_expression")
            else Value(responsibility),
            todo_action=action if hasattr(action, "resolve_expression") else Value(action),
        )
        .values(*FIELDS)
    )


def todo_query(user, options):
    native, defects, execute, reviews, managers = permitted_projects(user, options["workspace"])
    project = options.get("project_id")
    if project:
        native, defects, execute, reviews, managers = [
            [pk for pk in group if pk == project] for group in [native, defects, execute, reviews, managers]
        ]
    assigned = IssueAssignee.objects.filter(issue_id=OuterRef("pk"), assignee=user, deleted_at__isnull=True)
    req = Requirement.objects.filter(issue_id=OuterRef("pk"))
    issues = (
        Issue.objects.filter(project_id__in=native, archived_at__isnull=True, is_draft=False)
        .exclude(state__group__in=["completed", "cancelled"])
        .annotate(
            is_assigned=Exists(assigned),
            is_requirement=Exists(req),
            requirement_status=Subquery(req.values("status")[:1]),
        )
        .filter(is_assigned=True)
        .filter(Q(is_requirement=False) | Q(requirement_status__in=["draft", "review", "approved"]))
    )
    # The same public code is used by project lists; UUIDs remain internal identifiers.
    issue_code = Case(
        When(
            is_requirement=True,
            then=Concat(F("project__identifier"), Value("-R-"), Cast(Subquery(req.values("number")[:1]), CharField())),
        ),
        default=Concat(F("project__identifier"), Value("-T-"), Cast("sequence_id", CharField())),
    )
    issue_rows = projection(
        issues,
        Case(When(is_requirement=True, then=Value("requirement")), default=Value("task")),
        "name",
        Case(When(is_requirement=True, then=F("requirement_status")), default=F("state__group")),
        "db.issue",
        action="更新工作项",
        due="target_date",
        code_expression=issue_code,
        target=Case(When(is_requirement=True, then=Cast("pk", CharField())), default=Cast("sequence_id", CharField())),
    )
    active_regression = DataRegression.objects.filter(defect_id=OuterRef("pk")).exclude(
        plan__status__in=["completed", "cancelled", "failed"]
    )
    defect_query = (
        Defect.objects.filter(
            project_id__in=defects, archived_at__isnull=True, status__in=["open", "in_progress", "resolved"]
        )
        .filter(Q(assignee=user) | Q(pending_assignee=user))
        .annotate(active_regression=Exists(active_regression))
        .filter(~Q(status="resolved", active_regression=True) | Q(pending_assignee=user))
    )
    defect_rows = projection(
        defect_query,
        "defect",
        "title",
        "status",
        "quality.defect",
        responsibility=Case(When(pending_assignee=user, then=Value("待接收")), default=Value("负责")),
        action=Case(
            When(pending_assignee=user, then=Value("确认交接")),
            When(status="resolved", then=Value("安排回归")),
            default=Value("处理缺陷"),
        ),
    )
    voted = SolutionReview.objects.filter(revision_id=OuterRef("pk"), created_by=user)
    current_reviews = (
        SolutionRevision.objects.filter(
            project_id__in=reviews,
            solution__status="review",
            solution__submitted_version=F("version"),
            solution__defect__archived_at__isnull=True,
            reviewer_ids__contains=[str(user.id)],
        )
        .exclude(solution__created_by=user)
        .annotate(has_voted=Exists(voted))
        .filter(has_voted=False)
    )
    review_rows = projection(
        current_reviews,
        "solution",
        "solution__title",
        "solution__status",
        "quality.solution",
        target="solution__defect_id",
        responsibility="审核",
        action="审核方案",
        code_object="solution_id",
    )
    recorded = TestExecution.objects.filter(item_id=OuterRef("pk"))
    pending_items = (
        PlanItem.objects.filter(plan_id=OuterRef("pk")).annotate(has_result=Exists(recorded)).filter(has_result=False)
    )
    plan_query = (
        TestPlan.objects.filter(archived_at__isnull=True)
        .annotate(has_pending_items=Exists(pending_items))
        .filter(
            Q(
                managed=True,
                project_id__in=execute,
                assignee=user,
                status__in=["pending", "ready", "running", "paused", "returned"],
            )
            | Q(managed=False, project_id__in=execute, assignee=user, has_pending_items=True)
            | Q(managed=True, project_id__in=managers, status="review")
        )
    )
    plan_query = plan_query.annotate(is_regression=Exists(DataRegression.objects.filter(plan_id=OuterRef("pk"))))
    plan_rows = projection(
        plan_query,
        Value("plan"),
        "name",
        "status",
        "quality.testplan",
        responsibility=Case(When(status="review", then=Value("验收")), default=Value("执行")),
        action=Case(
            When(managed=False, then=Value("记录结果")),
            When(status="review", then=Value("确认结果")),
            When(status__in=["pending", "ready", "returned"], then=Value("开始测试")),
            When(status="paused", then=Value("恢复测试")),
            default=Value("记录结果"),
        ),
    )
    queries = [issue_rows, defect_rows, review_rows, plan_rows]
    filtered = []
    for query in queries:
        if options.get("kind"):
            query = query.filter(todo_kind=options["kind"])
        if options["search"]:
            query = query.filter(Q(todo_title__icontains=options["search"]) | Q(todo_code__icontains=options["search"]))
        filtered.append(query.values(*FIELDS))
    return filtered[0].union(*filtered[1:], all=True).order_by("-todo_created", "todo_kind", "todo_id")


class PersonalTodos(BaseAPIView):
    def get(self, request):
        options = TodoQuery(data=request.query_params)
        options.is_valid(raise_exception=True)
        paginator = QualityPagination()
        rows = paginator.paginate_queryset(todo_query(request.user, options.validated_data), request, view=self)
        results = []
        for row in rows:
            kind = row["todo_kind"]
            target = row["todo_target"]
            path = (
                f"defects/?defect={target}"
                if kind in {"defect", "solution"}
                else f"quality/?tab=plans&plan={target}"
                if kind in {"plan", "regression"}
                else f"requirements/?requirement={target}"
                if kind == "requirement"
                else f"issues/{target}/"
            )
            results.append(
                {
                    "id": row["todo_id"],
                    "title": row["todo_title"],
                    "kind": kind,
                    "kind_name": KINDS[kind],
                    "status": row["todo_status"] or "pending",
                    "code": row["todo_code"],
                    "project_id": row["todo_project"],
                    "project_name": row["todo_project_name"],
                    "responsibility": row["todo_responsibility"],
                    "next_action": row["todo_action"],
                    "due_date": row["todo_due"],
                    "created_at": row["todo_created"],
                    "url": f"/{options.validated_data['workspace']}/browse/{row['todo_project_key']}-{target}/"
                    if kind == "task"
                    else f"/{options.validated_data['workspace']}/p/{row['todo_project_key']}/{path}",
                }
            )
        response = paginator.get_paginated_response(results)
        response["Cache-Control"] = "no-store"
        return response
