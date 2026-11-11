# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
from django.db.models import Q
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from plane.db.models import UserRecentVisit, Project, ProjectMember, Issue, Page
from plane.app.serializers import WorkspaceRecentVisitSerializer
from ..base import BaseViewSet
from plane.app.permissions import allow_permission, ROLE


class RecentPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = "per_page"
    max_page_size = 50


class UserRecentVisitViewSet(BaseViewSet):
    model = UserRecentVisit
    use_read_replica = True

    def get_serializer_class(self):
        return WorkspaceRecentVisitSerializer

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="WORKSPACE")
    def list(self, request, slug):
        memberships = ProjectMember.objects.filter(
            workspace__slug=slug, member=request.user, is_active=True, project__archived_at__isnull=True
        )
        projects = Project.objects.filter(workspace__slug=slug, pk__in=memberships.values("project_id"))
        limited = memberships.filter(role=5, project__guest_view_all_features=False).values("project_id")
        issues = Issue.issue_objects.filter(workspace__slug=slug, project_id__in=projects.values("id")).exclude(
            Q(project_id__in=limited) & ~Q(created_by=request.user)
        )
        pages = (
            Page.objects.filter(workspace__slug=slug, projects__in=projects)
            .filter(Q(owned_by=request.user) | Q(access=0))
            .distinct()
        )
        recents = (
            UserRecentVisit.objects.filter(workspace__slug=slug, user=request.user)
            .filter(
                Q(entity_name="issue", entity_identifier__in=issues.values("id"))
                | Q(entity_name="project", entity_identifier__in=projects.values("id"))
                | Q(entity_name="page", entity_identifier__in=pages.values("id"))
            )
            .order_by("-visited_at", "-id")
        )
        entity_name = request.query_params.get("entity_name")
        if entity_name:
            value = serializers.ChoiceField(choices=["issue", "page", "project"]).run_validation(entity_name)
            recents = recents.filter(entity_name=value)
        if "page" not in request.query_params and "per_page" not in request.query_params:
            return Response(WorkspaceRecentVisitSerializer(recents[:20], many=True).data)
        for key in ["page", "per_page"]:
            if key in request.query_params:
                serializers.IntegerField(min_value=1, max_value=50 if key == "per_page" else None).run_validation(
                    request.query_params[key]
                )
        paginator = RecentPagination()
        rows = paginator.paginate_queryset(recents, request)
        return paginator.get_paginated_response(WorkspaceRecentVisitSerializer(rows, many=True).data)
