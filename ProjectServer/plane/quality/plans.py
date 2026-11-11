# SPDX-License-Identifier: AGPL-3.0-only
"""Plan preparation and repeat runs never rewrite recorded executions."""

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.response import Response
from .models import PlanEvent, PlanItem, TestCase, TestExecution, TestPlan, PlanResource
from .serializers import PlanSerializer
from .views import QualityView, Conflict, plan_queryset, PlanDetail as ReadPlanDetail


class PlanEditInput(serializers.Serializer):
    name = serializers.CharField(max_length=255, required=False)
    build = serializers.CharField(max_length=120, required=False)
    environment = serializers.CharField(max_length=255, required=False)
    description = serializers.CharField(max_length=20000, allow_blank=True, required=False)
    expected_version = serializers.IntegerField(min_value=1)
    case_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=False, max_length=500, required=False)
    use_latest = serializers.BooleanField(default=False)
    expected_case_versions = serializers.DictField(child=serializers.IntegerField(min_value=1), required=False)


class PlanCopyInput(PlanEditInput):
    name = serializers.CharField(max_length=255)
    use_latest = serializers.BooleanField(default=False)


def chosen_revisions(plan, ids, latest, expected):
    old = {item.case_id: item.revision for item in plan.items.select_related("revision")}
    ids = set(ids) if ids is not None else set(old)
    cases = {case.id: case for case in TestCase.objects.select_for_update().filter(project=plan.project, pk__in=ids)}
    if len(cases) != len(ids):
        from rest_framework.exceptions import ValidationError

        raise ValidationError({"case_ids": "请选择当前项目中的有效用例。"})
    revisions = {}
    for pk in ids:
        case = cases[pk]
        if case.trashed_at or case.archived_at and (latest or pk not in old):
            raise Conflict("已归档用例不能用于新增或升级，请恢复用例或移出本次计划。")
        if str(pk) in expected and expected[str(pk)] != case.version:
            raise Conflict("用例库版本已更新，请刷新版本清单后再提交。")
        revisions[pk] = case.revisions.get(version=case.version) if latest or pk not in old else old[pk]
    return revisions


class PlanDetail(ReadPlanDetail):
    @transaction.atomic
    def patch(self, request, pk, **kwargs):
        data = self.input(PlanEditInput)
        plan = get_object_or_404(TestPlan.objects.select_for_update(), pk=pk, project_id=self.project_id)
        if plan.archived_at:
            raise Conflict("计划已归档，请先恢复后编辑。")
        if hasattr(plan, "data_regression"):
            raise Conflict("数据回归的修复版本与验证场景已固定，请从缺陷详情发起新的数据回归。")
        if data.pop("expected_version") != plan.workflow_version:
            raise Conflict()
        if plan.status not in {"pending", "ready"} or TestExecution.objects.filter(item__plan=plan).exists():
            raise Conflict("计划已经开始，不能改写测试内容；请复制为新计划重新安排。")
        ids = data.pop("case_ids", None)
        latest = data.pop("use_latest", False)
        expected = data.pop("expected_case_versions", {})
        if ids is not None or latest:
            revisions = chosen_revisions(plan, ids, latest, expected)
            plan.items.all().delete()
            for pk, revision in revisions.items():
                PlanItem.objects.create(
                    project=plan.project, created_by=request.user, plan=plan, case_id=pk, revision=revision
                )
        labels = {"name": "计划名称", "build": "被测版本", "environment": "测试环境", "description": "计划说明"}
        changes = [
            f"{labels[key]}：{getattr(plan, key)} → {value}"
            for key, value in data.items()
            if getattr(plan, key) != value
        ]
        for key, value in data.items():
            setattr(plan, key, value)
        plan.workflow_version += 1
        plan.save()
        PlanEvent.objects.create(
            project=plan.project,
            created_by=request.user,
            plan=plan,
            action="edit",
            previous_status=plan.status,
            status=plan.status,
            round_no=plan.round_no,
            note="调整测试安排：" + "；".join(changes),
        )
        return Response(PlanSerializer(plan_queryset().get(pk=plan.pk)).data)


class PlanCopy(QualityView):
    @transaction.atomic
    def post(self, request, pk, **kwargs):
        data = self.input(PlanCopyInput)
        source = get_object_or_404(TestPlan.objects.select_for_update(), pk=pk, project_id=self.project_id)
        if hasattr(source, "data_regression"):
            raise Conflict("请从缺陷详情发起新数据回归，保留来源核验要求。")
        if data.pop("expected_version") != source.workflow_version:
            raise Conflict()
        latest = data.pop("use_latest")
        ids = data.pop("case_ids", None)
        expected = data.pop("expected_case_versions", {})
        revisions = chosen_revisions(source, ids, latest, expected)
        target = TestPlan.objects.create(
            project=source.project,
            created_by=request.user,
            name=data["name"],
            build=data.get("build", source.build),
            environment=data.get("environment", source.environment),
            description=data.get("description", source.description),
            managed=source.managed,
        )
        for pk, revision in revisions.items():
            PlanItem.objects.create(
                project=source.project, created_by=request.user, plan=target, case_id=pk, revision=revision
            )
        PlanResource.objects.bulk_create(
            [
                PlanResource(project=source.project, created_by=request.user, plan=target, resource_id=link.resource_id)
                for link in source.resource_links.all()
            ]
        )
        PlanEvent.objects.create(
            project=source.project,
            created_by=request.user,
            plan=target,
            action="copy",
            status="pending",
            round_no=1,
            note=f"从计划 {source.id} 复制；" + ("使用当前用例版本" if latest else "保留原计划用例版本"),
        )
        return Response(PlanSerializer(plan_queryset().get(pk=target.pk)).data, status=201)
