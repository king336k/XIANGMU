# SPDX-License-Identifier: AGPL-3.0-only
from plane.quality.authorship import AuthoredRecordSerializer
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from plane.db.models import ProjectMember
from .permissions import strict, capable
from .models import Defect, Release, ReleasePlan, SuiteItem, TestCase, TestPlan, TestSuite
from .serializers import RevisionSerializer
from .views import Conflict, QualityView, plan_queryset
from .serializers import plan_summary


def manager(view, capability="manage_test"):
    if strict(view.project_id):
        if not capable(view.project_id, view.request.user.id, capability):
            raise PermissionDenied("只有项目经理可以执行此操作。")
        return
    if not ProjectMember.objects.filter(
        project_id=view.project_id, member=view.request.user, is_active=True, role=20
    ).exists():
        raise PermissionDenied("当前角色不能发布测试资产或确认版本准入。")


class SuiteInput(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    description = serializers.CharField(max_length=10000, allow_blank=True, default="")
    case_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=False, max_length=500)


class SuiteItemSerializer(serializers.ModelSerializer):
    revision = RevisionSerializer(read_only=True)

    class Meta:
        model = SuiteItem
        fields = ["id", "case_id", "revision"]


class SuiteSerializer(AuthoredRecordSerializer):
    items = SuiteItemSerializer(many=True, read_only=True)

    class Meta:
        model = TestSuite
        fields = [
            "id",
            "name",
            "description",
            "published",
            "archived_at",
            "trashed_at",
            "edit_version",
            "source_suite_id",
            "created_at",
            "items",
        ]


def suites():
    return TestSuite.objects.prefetch_related("items__revision")


class SuiteList(QualityView):
    def get(self, request, **kwargs):
        return self.listing(suites().filter(project=self.project()), SuiteSerializer)

    @transaction.atomic
    def post(self, request, **kwargs):
        data = self.input(SuiteInput)
        ids = set(data.pop("case_ids"))
        cases = list(
            TestCase.objects.select_for_update().filter(
                project_id=self.project_id, id__in=ids, archived_at__isnull=True, trashed_at__isnull=True
            )
        )
        if len(cases) != len(ids):
            raise ValidationError({"case_ids": "用例不存在或不属于当前项目。"})
        suite = TestSuite.objects.create(project=self.project(), created_by=request.user, **data)
        for case in cases:
            SuiteItem.objects.create(
                suite=suite,
                project=suite.project,
                case=case,
                revision=case.revisions.get(version=case.version),
                created_by=request.user,
            )
        return Response(SuiteSerializer(suites().get(pk=suite.pk)).data, status=201)


class SuiteEditInput(SuiteInput):
    expected_version = serializers.IntegerField(min_value=1)


class SuiteCopyInput(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    use_latest = serializers.BooleanField(default=False)
    expected_version = serializers.IntegerField(min_value=1, required=False)


class SuiteDetail(QualityView):
    def get(self, request, pk, **kwargs):
        return Response(SuiteSerializer(get_object_or_404(suites(), pk=pk, project_id=self.project_id)).data)

    @transaction.atomic
    def patch(self, request, pk, **kwargs):
        data = self.input(SuiteEditInput, partial=True)
        suite = get_object_or_404(TestSuite.objects.select_for_update(), pk=pk, project_id=self.project_id)
        if data.pop("expected_version", None) != suite.edit_version:
            raise Conflict()
        if suite.archived_at or suite.trashed_at:
            raise Conflict("套件已归档，请先恢复后操作。")
        if suite.published:
            raise Conflict("已发布套件固定用例版本，请复制为新草稿后调整。")
        ids = data.pop("case_ids", None)
        if ids is not None:
            ids = set(ids)
            cases = list(
                TestCase.objects.select_for_update().filter(
                    project_id=self.project_id, id__in=ids, archived_at__isnull=True, trashed_at__isnull=True
                )
            )
            if len(cases) != len(ids):
                raise ValidationError({"case_ids": "请选择当前项目中的有效用例。"})
            # Keep unchanged case revisions; adding/removing membership must not silently upgrade existing steps.
            revisions = {item.case_id: item.revision for item in suite.items.select_related("revision")}
            suite.items.all().delete()
            for case in cases:
                SuiteItem.objects.create(
                    suite=suite,
                    project=suite.project,
                    created_by=request.user,
                    case=case,
                    revision=revisions.get(case.id) or case.revisions.get(version=case.version),
                )
        for key, value in data.items():
            setattr(suite, key, value)
        suite.edit_version += 1
        suite.save()
        return Response(SuiteSerializer(suites().get(pk=suite.pk)).data)


class SuiteCopy(QualityView):
    @transaction.atomic
    def post(self, request, pk, **kwargs):
        data = self.input(SuiteCopyInput)
        source = get_object_or_404(TestSuite.objects.select_for_update(), pk=pk, project_id=self.project_id)
        if "expected_version" in data and data["expected_version"] != source.edit_version:
            raise Conflict()
        if source.trashed_at:
            raise Conflict("用例集已在回收站，请先恢复。")
        items = list(source.items.select_related("revision", "case"))
        cases = {
            case.id: case
            for case in TestCase.objects.select_for_update().filter(pk__in=[item.case_id for item in items])
        }
        target = TestSuite.objects.create(
            project=source.project,
            created_by=request.user,
            name=data["name"],
            description=source.description,
            source_suite=source,
        )
        for item in items:
            revision = (
                cases[item.case_id].revisions.get(version=cases[item.case_id].version)
                if data["use_latest"]
                else item.revision
            )
            SuiteItem.objects.create(
                suite=target, project=target.project, created_by=request.user, case=item.case, revision=revision
            )
        return Response(SuiteSerializer(suites().get(pk=target.pk)).data, status=201)


class SuitePublish(QualityView):
    @transaction.atomic
    def post(self, request, pk, **kwargs):
        manager(self, "manage_case")
        suite = get_object_or_404(TestSuite.objects.select_for_update(), pk=pk, project_id=self.project_id)
        if suite.archived_at or suite.trashed_at:
            raise Conflict("套件已归档，请先恢复后操作。")
        if request.data.get("expected_version") is not None and request.data["expected_version"] != suite.edit_version:
            raise Conflict()
        if not suite.published:
            suite.published = True
            suite.edit_version += 1
            suite.save(update_fields=["published", "archived_at", "edit_version"])
        return Response(SuiteSerializer(suites().get(pk=suite.pk)).data)


class ReleaseInput(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    version = serializers.CharField(max_length=120)
    description = serializers.CharField(max_length=10000, allow_blank=True, default="")
    plan_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=False, max_length=100)


def readiness(release):
    links = list(release.plans.select_related("plan"))
    blockers = []
    plans = []
    for link in links:
        plan = link.plan
        plans.append({"id": str(plan.id), "name": plan.name, "build": plan.build, "status": plan.status})
        if not plan.managed or plan.status != "completed":
            blockers.append(f"测试计划「{plan.name}」尚未完成经理验收。")
        summary = plan_summary(plan_queryset().get(pk=plan.pk))
        if not summary["total"] or summary["passed"] != summary["total"]:
            blockers.append(f"测试计划「{plan.name}」本轮用例尚未全部通过。")
        if plan.build != release.version:
            blockers.append(f"测试计划「{plan.name}」的被测版本与发布版本不一致。")
    if not plans:
        blockers.append("没有关联测试计划。")
    defects = (
        Defect.objects.filter(project=release.project)
        .exclude(status="closed")
        .filter(
            Q(affected_build=release.version) | Q(source_execution__item__plan_id__in=[link.plan_id for link in links])
        )
        .distinct()
        .count()
    )
    if defects:
        blockers.append(f"仍有 {defects} 个关联缺陷未关闭。")
    return {"ready": not blockers, "blockers": blockers, "plans": plans, "open_defects": defects}


class ReleaseSerializer(AuthoredRecordSerializer):
    readiness = serializers.SerializerMethodField()

    def get_readiness(self, obj):
        return readiness(obj)

    class Meta:
        model = Release
        fields = [
            "id",
            "name",
            "version",
            "description",
            "status",
            "edit_version",
            "created_at",
            "admitted_at",
            "admission_snapshot",
            "readiness",
        ]


class ReleaseList(QualityView):
    def get(self, request, **kwargs):
        return self.listing(
            Release.objects.filter(project=self.project()).prefetch_related("plans__plan"), ReleaseSerializer
        )

    @transaction.atomic
    def post(self, request, **kwargs):
        data = self.input(ReleaseInput)
        ids = set(data.pop("plan_ids"))
        plans = list(TestPlan.objects.filter(project_id=self.project_id, id__in=ids, archived_at__isnull=True))
        if len(plans) != len(ids):
            raise ValidationError({"plan_ids": "计划不存在或不属于当前项目。"})
        if Release.objects.filter(project_id=self.project_id, version=data["version"]).exists():
            raise Conflict("此项目已存在相同发布版本。")
        release = Release.objects.create(project=self.project(), created_by=request.user, **data)
        ReleasePlan.objects.bulk_create(
            [
                ReleasePlan(release=release, plan=plan, project=release.project, created_by=request.user)
                for plan in plans
            ]
        )
        return Response(ReleaseSerializer(release).data, status=201)


class ReleaseEditInput(ReleaseInput):
    expected_version = serializers.IntegerField(min_value=1)


class ReleaseDetail(QualityView):
    def get(self, request, pk, **kwargs):
        return Response(ReleaseSerializer(self.obj(Release, pk)).data)

    @transaction.atomic
    def patch(self, request, pk, **kwargs):
        manager(self)
        data = self.input(ReleaseEditInput, partial=True)
        row = get_object_or_404(Release.objects.select_for_update(), pk=pk, project_id=self.project_id)
        if data.pop("expected_version", None) != row.edit_version:
            raise Conflict()
        if row.status != "draft":
            raise Conflict("已确认发布检查的版本保留快照，请复制为新的发布计划。")
        if (
            "version" in data
            and Release.objects.filter(project=row.project, version=data["version"]).exclude(pk=row.pk).exists()
        ):
            raise Conflict("该发布版本已存在。")
        ids = data.pop("plan_ids", None)
        if ids is not None:
            ids = set(ids)
            plans = list(
                TestPlan.objects.select_for_update().filter(project=row.project, pk__in=ids, archived_at__isnull=True)
            )
            if len(plans) != len(ids):
                raise ValidationError({"plan_ids": "请选择本项目有效的测试计划。"})
            row.plans.all().delete()
            for plan in plans:
                ReleasePlan.objects.create(project=row.project, created_by=request.user, release=row, plan=plan)
        previous = row.edit_version
        changes = [f"{key}：{getattr(row, key)} → {value}" for key, value in data.items() if getattr(row, key) != value]
        for key, value in data.items():
            setattr(row, key, value)
        row.edit_version += 1
        row.save()
        from .models import QualityLifecycleEvent

        QualityLifecycleEvent.objects.create(
            project=row.project,
            created_by=request.user,
            resource="releases",
            object_id=row.id,
            action="edit",
            reason="调整发布计划：" + "；".join(changes),
            before_version=previous,
            after_version=row.edit_version,
        )
        return Response(ReleaseSerializer(row).data)


class ReleaseCopyInput(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    name = serializers.CharField(max_length=255)
    version = serializers.CharField(max_length=120)


class ReleaseCopy(QualityView):
    @transaction.atomic
    def post(self, request, pk, **kwargs):
        manager(self)
        data = self.input(ReleaseCopyInput)
        source = get_object_or_404(Release.objects.select_for_update(), pk=pk, project_id=self.project_id)
        if source.edit_version != data["expected_version"]:
            raise Conflict()
        if Release.objects.filter(project=source.project, version=data["version"]).exists():
            raise Conflict("目标版本已经存在。")
        target = Release.objects.create(
            project=source.project,
            created_by=request.user,
            name=data["name"],
            version=data["version"],
            description=source.description,
        )
        for link in source.plans.select_related("plan").all():
            if not link.plan.archived_at:
                ReleasePlan.objects.create(
                    project=target.project, created_by=request.user, release=target, plan=link.plan
                )
        return Response(ReleaseSerializer(target).data, status=201)


class AdmissionInput(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)


class ReleaseAdmit(QualityView):
    @transaction.atomic
    def post(self, request, pk, **kwargs):
        manager(self)
        data = self.input(AdmissionInput)
        release = get_object_or_404(Release.objects.select_for_update(), pk=pk, project_id=self.project_id)
        if release.status == "admitted":
            return Response(ReleaseSerializer(release).data)
        if release.edit_version != data["expected_version"]:
            raise Conflict()
        list(TestPlan.objects.select_for_update().filter(releases__release=release).order_by("id"))
        status = readiness(release)
        if not status["ready"]:
            raise ValidationError({"blockers": status["blockers"]})
        release.status = "admitted"
        release.edit_version += 1
        release.admitted_by = request.user
        release.admitted_at = timezone.now()
        release.admission_snapshot = status
        release.save()
        return Response(ReleaseSerializer(release).data)
