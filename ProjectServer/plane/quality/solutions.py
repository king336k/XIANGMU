# SPDX-License-Identifier: AGPL-3.0-only
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from .authorship import AuthoredRecordSerializer
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from plane.db.models import ProjectMember
from .permissions import strict, require_assignee, has_role, is_administrator
from .models import Defect, Solution, SolutionRevision, SolutionReview
from .views import Conflict, QualityView

FIELDS = ["title", "root_cause", "steps", "verification", "risk", "rollback", "repository", "commit_sha"]


class SolutionInput(serializers.Serializer):
    defect_id = serializers.UUIDField()
    title = serializers.CharField(max_length=255)
    root_cause = serializers.CharField(max_length=20000)
    steps = serializers.CharField(max_length=20000)
    verification = serializers.CharField(max_length=20000)
    risk = serializers.CharField(max_length=10000, allow_blank=True, default="")
    rollback = serializers.CharField(max_length=10000, allow_blank=True, default="")
    repository = serializers.CharField(max_length=500, allow_blank=True, default="")
    commit_sha = serializers.CharField(max_length=120, allow_blank=True, default="")
    expected_version = serializers.IntegerField(min_value=1, required=False)


class VoteSerializer(serializers.ModelSerializer):
    actor = serializers.CharField(source="created_by.display_name", default="成员")

    class Meta:
        model = SolutionReview
        fields = ["id", "created_by_id", "actor", "decision", "comment", "created_at"]


class SnapshotSerializer(serializers.ModelSerializer):
    reviews = VoteSerializer(many=True, read_only=True)

    class Meta:
        model = SolutionRevision
        fields = [
            "id", "version", "snapshot", "reviewer_ids", "required_count", "reviews", "created_at", "created_by_id"
        ]


class SolutionSerializer(AuthoredRecordSerializer):
    revisions = SnapshotSerializer(many=True, read_only=True)
    defect_title = serializers.CharField(source="defect.title", read_only=True)
    created_by_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = Solution
        fields = [
            "id",
            "defect_id",
            "defect_title",
            "status",
            "edit_version",
            "submitted_version",
            "created_at",
            "created_by_id",
            "contributor_ids",
            "revisions",
            *FIELDS,
        ]


def solutions():
    return Solution.objects.select_related("defect").prefetch_related("revisions__reviews__created_by")


class SolutionList(QualityView):
    def get(self, request, **kwargs):
        qs = solutions().filter(project=self.project())
        if request.query_params.get("defect_id"):
            validator = serializers.UUIDField()
            defect_id = validator.run_validation(request.query_params["defect_id"])
            qs = qs.filter(defect_id=defect_id)
        return self.listing(qs, SolutionSerializer)

    @transaction.atomic
    def post(self, request, **kwargs):
        data = self.input(SolutionInput)
        data.pop("expected_version", None)
        defect = self.obj(Defect, data.pop("defect_id"))
        if (
            strict(self.project_id) and defect.assignee_id != request.user.id
            and not has_role(self.project_id, request.user.id, "PLATFORM_ADMIN")
        ):
            raise PermissionDenied("只有当前技术负责人可以维护方案。")
        value = Solution.objects.create(defect=defect, project=defect.project, created_by=request.user, **data)
        return Response(SolutionSerializer(value).data, status=201)


class SolutionDetail(QualityView):
    def get(self, request, pk, **kwargs):
        return Response(SolutionSerializer(get_object_or_404(solutions(), pk=pk, project_id=self.project_id)).data)

    def author(self, solution):
        if strict(self.project_id):
            if (
                solution.defect.assignee_id != self.request.user.id
                and not has_role(self.project_id, self.request.user.id, "PLATFORM_ADMIN")
            ):
                raise PermissionDenied("只有当前技术负责人可以维护方案。")
            return
        if solution.created_by_id != self.request.user.id and (
            strict(self.project_id)
            or not ProjectMember.objects.filter(
                project_id=self.project_id, member=self.request.user, is_active=True, role=20
            ).exists()
        ):
            raise PermissionDenied("只有方案作者或获授权的管理员可以编辑与提交。")

    @transaction.atomic
    def patch(self, request, pk, **kwargs):
        data = self.input(SolutionInput, partial=True)
        solution = get_object_or_404(Solution.objects.select_for_update(), pk=pk, project_id=self.project_id)
        self.author(solution)
        if data.pop("expected_version", None) != solution.edit_version:
            raise Conflict()
        if solution.status == "review":
            raise Conflict("审核中的方案已冻结，请等待审核结果。")
        if data.get("defect_id", solution.defect_id) != solution.defect_id:
            raise ValidationError({"defect_id": "方案不能迁移到其他缺陷。"})
        for key, value in data.items():
            setattr(solution, key, value)
        solution.contributor_ids = sorted({*map(str, solution.contributor_ids or []), str(request.user.id)})
        solution.status = "draft"
        solution.edit_version += 1
        solution.save()
        from .notifications import defect_notice

        defect_notice(solution.defect, request.user, "技术方案状态已更新", [solution.created_by_id])
        return Response(SolutionSerializer(solutions().get(pk=solution.pk)).data)


class SubmitInput(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    reviewer_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=False, max_length=30)
    required_count = serializers.IntegerField(min_value=1, max_value=30)


class SolutionSubmit(SolutionDetail):
    @transaction.atomic
    def post(self, request, pk, **kwargs):
        data = self.input(SubmitInput)
        solution = get_object_or_404(Solution.objects.select_for_update(), pk=pk, project_id=self.project_id)
        self.author(solution)
        if data["expected_version"] != solution.edit_version or solution.status != "draft":
            raise Conflict("当前方案不能重复送审，请刷新后确认状态。")
        ids = {str(value) for value in data["reviewer_ids"]}
        contributors = {str(solution.created_by_id), str(request.user.id), *map(str, solution.contributor_ids or [])}
        if (contributors & ids and not is_administrator(request.user)) or data["required_count"] > len(ids):
            raise ValidationError({
                "reviewer_ids": "审核人不能包含方案作者、本版修改人或提交人，且通过人数不能超过审核人数。"
            })
        members = ProjectMember.objects.filter(
            project_id=self.project_id, member_id__in=ids, is_active=True, role__gte=15, member__is_bot=False
        )
        if members.count() != len(ids):
            raise ValidationError({"reviewer_ids": "审核人必须是当前项目的有效成员。"})
        for member in members:
            self.validate_assignee(member.member_id)
            require_assignee(self, member.member_id, "PROJECT_MANAGER")
        solution.submitted_version += 1
        SolutionRevision.objects.create(
            solution=solution,
            project=solution.project,
            created_by=request.user,
            version=solution.submitted_version,
            snapshot={**{key: getattr(solution, key) for key in FIELDS}, "contributor_ids": sorted(contributors)},
            reviewer_ids=sorted(ids),
            required_count=data["required_count"],
        )
        from .notifications import defect_notice

        defect_notice(solution.defect, request.user, "技术方案等待审核", ids)
        solution.status = "review"
        solution.edit_version += 1
        solution.save()
        from .notifications import defect_notice

        defect_notice(solution.defect, request.user, "技术方案状态已更新", [solution.created_by_id])
        return Response(SolutionSerializer(solutions().get(pk=solution.pk)).data)


class ReviewInput(serializers.Serializer):
    revision_id = serializers.UUIDField()
    decision = serializers.ChoiceField(choices=["approve", "reject"])
    comment = serializers.CharField(max_length=4000, allow_blank=True, default="")


class SolutionDecision(QualityView):
    @transaction.atomic
    def post(self, request, pk, **kwargs):
        data = self.input(ReviewInput)
        solution = get_object_or_404(Solution.objects.select_for_update(), pk=pk, project_id=self.project_id)
        revision = get_object_or_404(SolutionRevision, pk=data["revision_id"], solution=solution)
        contributors = {
            str(solution.created_by_id), str(revision.created_by_id),
            *map(str, revision.snapshot.get("contributor_ids", [])),
        }
        if str(request.user.id) not in revision.reviewer_ids or (str(request.user.id) in contributors and not is_administrator(request.user)):
            raise PermissionDenied("您不是该冻结版本的审核人。")
        existing = SolutionReview.objects.filter(revision=revision, created_by=request.user).first()
        if existing:
            if existing.decision != data["decision"] or existing.comment != data["comment"]:
                raise Conflict("本版本已提交决定，不能改写审核历史。")
            return Response(SolutionSerializer(solutions().get(pk=solution.pk)).data)
        if solution.status != "review" or revision.version != solution.submitted_version:
            raise Conflict("该版本已经完成审核或不再是当前送审版本。")
        if data["decision"] == "reject" and not data["comment"].strip():
            raise ValidationError({"comment": "退回方案必须说明原因。"})
        SolutionReview.objects.create(
            revision=revision,
            project=solution.project,
            created_by=request.user,
            decision=data["decision"],
            comment=data["comment"],
        )
        if data["decision"] == "reject":
            solution.status = "rejected"
        elif revision.reviews.filter(decision="approve").count() >= revision.required_count:
            solution.status = "approved"
        solution.edit_version += 1
        solution.save()
        from .notifications import defect_notice

        defect_notice(solution.defect, request.user, "技术方案状态已更新", [solution.created_by_id])
        return Response(SolutionSerializer(solutions().get(pk=solution.pk)).data)
