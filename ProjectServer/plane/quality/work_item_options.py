"""Paginated authorized record choices; old records remain searchable without full context dumps."""

from rest_framework import serializers
from plane.db.models import Issue, ProjectMember
from .models import Requirement
from .views import QualityView, QualityPagination


class WorkItemOptions(QualityView):
    def get(self, request, **kwargs):
        project = self.project()
        query = Issue.issue_objects.filter(project=project, archived_at__isnull=True, is_draft=False)
        if (
            not project.guest_view_all_features
            and ProjectMember.objects.filter(project=project, member=request.user, is_active=True, role=5).exists()
        ):
            query = query.filter(created_by=request.user)
        search = serializers.CharField(max_length=160, allow_blank=True).run_validation(
            request.query_params.get("search", "")
        )
        if search:
            if search.upper().startswith(project.identifier + "-"):
                parts = search.split("-")
                number = parts[-1]
                if number.isascii() and number.isdigit() and len(number) <= 10:
                    if len(parts) > 2 and parts[-2].upper() == "R":
                        query = query.filter(
                            pk__in=Requirement.objects.filter(project=project, number=int(number)).values("issue_id")
                        )
                    else:
                        query = query.filter(sequence_id=int(number))
                else:
                    query = query.filter(name__icontains=search)
            else:
                query = query.filter(name__icontains=search)
        paginator = QualityPagination()
        rows = paginator.paginate_queryset(query.order_by("-created_at", "-id"), request, view=self)
        numbers = dict(
            Requirement.objects.filter(project=project, issue_id__in=[row.id for row in rows]).values_list(
                "issue_id", "number"
            )
        )
        return paginator.get_paginated_response(
            [
                {
                    "id": str(row.id),
                    "name": row.name,
                    "sequence_id": row.sequence_id,
                    "code": f"{project.identifier}-R-{numbers[row.id]}"
                    if row.id in numbers
                    else f"{project.identifier}-T-{row.sequence_id}",
                }
                for row in rows
            ]
        )
