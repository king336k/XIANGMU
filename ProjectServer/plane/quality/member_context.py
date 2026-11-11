# SPDX-License-Identifier: AGPL-3.0-only
from collections import defaultdict
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from plane.app.views.base import BaseAPIView
from plane.db.models import ProjectMember, WorkspaceMember
from .models import BusinessRole, PlatformIdentity, PlatformAccount
from .permissions import ROLE_NAMES


class WorkspaceMemberContext(BaseAPIView):
    def get(self, request, slug):
        if not WorkspaceMember.objects.filter(
            workspace__slug=slug, member=request.user, role=20, is_active=True
        ).exists():
            raise PermissionDenied("只有管理员或工作空间负责人可以核对成员账号。")
        visible_projects = ProjectMember.objects.filter(
            project__workspace__slug=slug,
            project__archived_at__isnull=True,
            member=request.user,
            is_active=True,
        ).values_list("project_id", flat=True)
        members = WorkspaceMember.objects.filter(workspace__slug=slug, is_active=True).select_related("member")
        source_names = dict(
            PlatformAccount.objects.filter(user_id__in=members.values("member_id")).values_list(
                "user_id", "source_username"
            )
        )
        active_project_members = set(
            ProjectMember.objects.filter(
                project_id__in=visible_projects, is_active=True, member__is_active=True
            ).values_list("project_id", "member_id")
        )
        responsibilities = defaultdict(list)
        for row in BusinessRole.objects.filter(project_id__in=visible_projects, user__is_active=True).select_related(
            "project"
        ):
            if (row.project_id, row.user_id) not in active_project_members:
                continue
            for role in sorted({row.role, *(row.additional_roles or [])}):
                responsibilities[str(row.user_id)].append(
                    {"project": row.project.name, "role": ROLE_NAMES.get(role, role)}
                )
        mapped = set(
            row.user_id
            for row in PlatformIdentity.objects.filter(project_id__in=visible_projects, active=True)
            if (row.project_id, row.user_id) in active_project_members
        )
        response = Response(
            {
                "members": {
                    str(row.member_id): {
                        "username": source_names.get(row.member_id) or row.member.username,
                        "business_roles": responsibilities[str(row.member_id)],
                        "identity_mapped": row.member_id in mapped,
                    }
                    for row in members
                }
            }
        )
        response["Cache-Control"] = "no-store"
        return response
