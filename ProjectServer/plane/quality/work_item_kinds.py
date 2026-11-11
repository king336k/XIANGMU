# SPDX-License-Identifier: AGPL-3.0-only
from rest_framework.response import Response
from plane.db.models import Issue, ProjectMember
from .models import Requirement
from .views import QualityView


class WorkItemKinds(QualityView):
    def get(self, request, **kwargs):
        project = self.project()
        visible = Issue.objects.filter(project=project, is_draft=False)
        if (
            not project.guest_view_all_features
            and ProjectMember.objects.filter(project=project, member=request.user, is_active=True, role=5).exists()
        ):
            visible = visible.filter(created_by=request.user)
        issues = visible.filter(archived_at__isnull=True)
        sequences = list(
            Requirement.objects.filter(project=project, issue_id__in=visible.values("id"))
            .order_by("issue__sequence_id")
            .values_list("issue__sequence_id", flat=True)
        )
        total = issues.count()
        requirement_count = Requirement.objects.filter(project=project, issue_id__in=issues.values("id")).count()
        return Response(
            {
                "total": total,
                "requirements": requirement_count,
                "tasks": total - requirement_count,
                "requirement_sequences": sequences,
                "requirement_numbers": {
                    str(seq): number
                    for seq, number in Requirement.objects.filter(
                        project=project, issue_id__in=visible.values("id")
                    ).values_list("issue__sequence_id", "number")
                },
            }
        )
