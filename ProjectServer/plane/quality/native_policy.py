# SPDX-License-Identifier: AGPL-3.0-only
from rest_framework.response import Response
from plane.db.models import Issue, IssueAssignee
from .views import QualityView
from .models import Requirement
from .permissions import strict, writable_member, has_role


class NativeIssuePolicy(QualityView):
    def get(self, request, pk, **kwargs):
        issue = self.obj(Issue, pk)
        enabled = strict(self.project_id)
        writable = writable_member(self.project_id, request.user.id, self.workspace_slug)
        arrange = writable and (not enabled or has_role(self.project_id, request.user.id, "PROJECT_MANAGER"))
        edit = arrange or (
            writable
            and has_role(self.project_id, request.user.id, "TECHNICIAN")
            and IssueAssignee.objects.filter(issue=issue, assignee=request.user).exists()
        )
        requirement = Requirement.objects.filter(issue=issue).exists()
        return Response(
            {
                "can_edit": bool(edit),
                "can_edit_content": bool(edit and not requirement),
                "can_arrange": bool(arrange),
                "requirement": requirement,
                "notice": (
                    "需求标题、说明和优先级请在需求管理中修改，以保留版本和评审记录。"
                    if requirement
                    else "当前仅可阅读；研发任务由项目经理安排，技术员更新分派给自己的任务。"
                    if not edit
                    else ""
                ),
            }
        )
