import pytest
from plane.db.models import Project, ProjectMember, Issue

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def req_project(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="需求管理", identifier="REQ")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    return f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/", project


def test_requirement_reuses_native_issue_versions_and_test_coverage(session_client, req_project):
    base, project = req_project
    created = session_client.post(
        base + "requirements/",
        {
            "title": "采集员上报异常",
            "description": "允许采集员从真实Session上报",
            "acceptance": "显示来源、日志和处理进度",
            "priority": "high",
        },
        format="json",
    )
    assert created.status_code == 201, created.content
    requirement = created.data
    assert Issue.objects.filter(pk=requirement["id"], project=project).exists()
    assert requirement["version"] == 1 and requirement["case_count"] == 0
    case = session_client.post(
        base + "cases/",
        {
            "title": "验证异常上报",
            "steps": [{"action": "提交", "expected": "创建成功"}],
            "requirement_id": requirement["id"],
        },
        format="json",
    )
    assert case.status_code == 201
    detail = session_client.get(base + f"requirements/{requirement['id']}/").data
    assert detail["case_count"] == 1 and detail["cases"][0]["id"] == case.data["id"]
    updated = session_client.patch(
        base + f"requirements/{requirement['id']}/",
        {"expected_version": 1, "acceptance": "新增附件预览验收要求"},
        format="json",
    )
    assert updated.status_code == 200 and updated.data["version"] == 2
    assert (
        len(updated.data["revisions"]) == 2
        and updated.data["revisions"][1]["snapshot"]["acceptance"] == "显示来源、日志和处理进度"
    )
    assert (
        session_client.patch(
            base + f"requirements/{requirement['id']}/", {"expected_version": 1, "title": "旧页面覆盖"}, format="json"
        ).status_code
        == 409
    )


def test_requirement_review_and_cross_project_isolation(session_client, req_project, workspace, create_user):
    base, project = req_project
    r = session_client.post(
        base + "requirements/", {"title": "权限需求", "acceptance": "明确权限拒绝"}, format="json"
    ).data
    workflow = base + f"requirements/{r['id']}/workflow/"
    assert session_client.post(workflow, {"action": "submit", "expected_version": 1}, format="json").status_code == 200
    approved = session_client.post(workflow, {"action": "approve", "expected_version": 2}, format="json")
    assert approved.status_code == 200 and approved.data["status"] == "approved"
    assert approved.data["case_count"] == 0  # Test cases are optional, including for small copy changes.
    other = Project.objects.create(workspace=workspace, name="其他项目", identifier="OTHERREQ")
    ProjectMember.objects.create(project=other, member=create_user, role=20)
    other_base = f"/api/workspaces/{workspace.slug}/projects/{other.id}/quality/"
    assert session_client.get(other_base + f"requirements/{r['id']}/").status_code == 404
    ProjectMember.objects.filter(project=project, member=create_user).update(role=5)
    assert session_client.get(base + "requirements/").status_code == 200
    assert session_client.post(base + "requirements/", {"title": "访客不可创建"}, format="json").status_code == 403


def test_requirement_return_reason_and_issue_name_updates_audit(session_client, req_project):
    base, project = req_project
    r = session_client.post(base + "requirements/", {"title": "待确认需求", "acceptance": "可验收"}, format="json").data
    url = base + f"requirements/{r['id']}/workflow/"
    assert session_client.post(url, {"action": "submit", "expected_version": 1}, format="json").status_code == 200
    assert session_client.post(url, {"action": "return", "expected_version": 2}, format="json").status_code == 400
    returned = session_client.post(
        url, {"action": "return", "expected_version": 2, "comment": "补充设备断线场景"}, format="json"
    )
    assert returned.status_code == 200
    assert returned.data["revisions"][0]["snapshot"]["comment"] == "补充设备断线场景"


def test_native_issue_edits_cannot_silently_overwrite_requirement_version(session_client, req_project):
    base, project = req_project
    r = session_client.post(base + "requirements/", {"title": "原需求", "acceptance": "通过"}, format="json").data
    Issue.objects.filter(pk=r["id"]).update(name="用户从原生工作项更改的标题")
    response = session_client.patch(
        base + f"requirements/{r['id']}/", {"expected_version": 1, "title": "旧需求页面覆盖"}, format="json"
    )
    assert response.status_code == 409
    assert Issue.objects.get(pk=r["id"]).name == "用户从原生工作项更改的标题"


def test_requirement_multiline_and_metadata_edit_preserve_native_rich_text(session_client, req_project):
    base, project = req_project
    description = "第一行\n第二行"
    response = session_client.post(
        base + "requirements/", {"title": "多行需求", "description": description}, format="json"
    )
    assert response.status_code == 201
    assert response.data["description"] == description
    requirement_id = response.data["id"]
    native_html = "<p>第一行</p><ul><li><a href='https://example.com'>查看文档</a></li></ul>"
    # A native rich description existing at the current requirement revision must survive metadata edits.
    from plane.quality.models import RequirementRevision

    issue = Issue.objects.get(pk=requirement_id)
    issue.description_html = native_html
    issue.save()
    revision = RequirementRevision.objects.get(requirement__issue_id=requirement_id, version=1)
    revision.snapshot.update(description_html=native_html, description=issue.description_stripped)
    revision.save()
    updated = session_client.patch(
        base + f"requirements/{requirement_id}/",
        {"expected_version": 1, "acceptance": "新增验收标准", "description": issue.description_stripped},
        format="json",
    )
    assert updated.status_code == 200, updated.content
    issue.refresh_from_db()
    assert issue.description_html == native_html


def test_guest_requirement_visibility_matches_native_issue(session_client, req_project, create_user):
    from plane.db.models import User

    base, project = req_project
    r = session_client.post(base + "requirements/", {"title": "内部需求"}, format="json").data
    other = User.objects.create(email="private-requirement@local.test", username="private-requirement")
    Issue.objects.filter(pk=r["id"]).update(created_by=other)
    ProjectMember.objects.filter(project=project, member=create_user).update(role=5)
    project.guest_view_all_features = False
    project.save()
    assert session_client.get(base + f"requirements/{r['id']}/").status_code == 403
    listed = session_client.get(base + "requirements/")
    assert listed.status_code == 200 and listed.data["count"] == 0
    Issue.objects.filter(pk=r["id"]).update(created_by=create_user)
    assert session_client.get(base + f"requirements/{r['id']}/").status_code == 200


@pytest.mark.parametrize("status", ["draft", "review", "approved"])
def test_native_issue_content_changes_require_requirement_workflow(session_client, req_project, status):
    from plane.quality.models import Requirement

    base, project = req_project
    r = session_client.post(base + "requirements/", {"title": "受审需求", "acceptance": "可验收"}, format="json").data
    Requirement.objects.filter(issue_id=r["id"]).update(status=status)
    response = session_client.patch(
        base.replace("quality/", "") + f"issues/{r['id']}/", {"name": "绕过需求审核"}, format="json"
    )
    assert response.status_code == 409, response.content
    assert Issue.objects.get(pk=r["id"]).name == "受审需求"


def test_requirement_review_cannot_approve_content_changed_outside_revision(session_client, req_project):
    base, project = req_project
    r = session_client.post(
        base + "requirements/", {"title": "确认过的内容", "acceptance": "可验收"}, format="json"
    ).data
    workflow = base + f"requirements/{r['id']}/workflow/"
    assert session_client.post(workflow, {"action": "submit", "expected_version": 1}, format="json").status_code == 200
    Issue.objects.filter(pk=r["id"]).update(description_html="<p>未审核内容</p>")
    assert session_client.post(workflow, {"action": "approve", "expected_version": 2}, format="json").status_code == 409


@pytest.mark.parametrize("role", ["REPORTER"])
def test_requirement_native_edit_respects_business_role(session_client, req_project, create_user, role):
    from plane.quality.models import BusinessRole, ProjectRolePolicy

    base, project = req_project
    r = session_client.post(base + "requirements/", {"title": "权限保护需求"}, format="json").data
    ProjectRolePolicy.objects.create(project=project, enabled=True)
    BusinessRole.objects.create(project=project, user=create_user, role=role, created_by=create_user)
    assert (
        session_client.patch(
            base + f"requirements/{r['id']}/", {"expected_version": 1, "title": "绕过权限"}, format="json"
        ).status_code
        == 403
    )
    response = session_client.patch(
        base.replace("quality/", "") + f"issues/{r['id']}/", {"name": "绕过权限"}, format="json"
    )
    assert response.status_code == 403, response.content


def test_member_can_submit_but_only_manager_can_review(session_client, req_project, create_user):
    base, project = req_project
    r = session_client.post(base + "requirements/", {"title": "职责划分", "acceptance": "可验收"}, format="json").data
    ProjectMember.objects.filter(project=project, member=create_user).update(role=15)
    workflow = base + f"requirements/{r['id']}/workflow/"
    assert session_client.post(workflow, {"action": "submit", "expected_version": 1}, format="json").status_code == 200
    assert (
        session_client.patch(
            base + f"requirements/{r['id']}/", {"expected_version": 2, "title": "审核中改内容"}, format="json"
        ).status_code
        == 409
    )
    assert session_client.post(workflow, {"action": "approve", "expected_version": 2}, format="json").status_code == 403
    assert (
        session_client.post(
            workflow, {"action": "return", "expected_version": 2, "comment": "越权退回"}, format="json"
        ).status_code
        == 403
    )


def test_approved_requirement_edit_restarts_review_and_keeps_old_snapshot(session_client, req_project):
    base, project = req_project
    row = session_client.post(
        base + "requirements/", {"title": "已确认的需求", "acceptance": "第一版验收"}, format="json"
    ).data
    workflow = base + f"requirements/{row['id']}/workflow/"
    assert session_client.post(workflow, {"action": "submit", "expected_version": 1}, format="json").status_code == 200
    assert session_client.post(workflow, {"action": "approve", "expected_version": 2}, format="json").status_code == 200
    response = session_client.patch(
        base + f"requirements/{row['id']}/", {"expected_version": 3, "acceptance": "第二版验收"}, format="json"
    )
    assert response.status_code == 200
    assert response.data["version"] == 4 and response.data["status"] == "draft"
    assert response.data["revisions"][1]["snapshot"]["status"] == "approved"
    assert response.data["revisions"][1]["snapshot"]["acceptance"] == "第一版验收"


def test_requirement_development_state_remains_native_and_external_serializer_is_guarded(session_client, req_project):
    from plane.api.serializers.issue import IssueSerializer
    from plane.quality.views import Conflict
    from plane.db.models import State

    base, project = req_project
    row = session_client.post(base + "requirements/", {"title": "开发中需求"}, format="json").data
    state = State.objects.create(project=project, workspace=project.workspace, name="开发中", group="started")
    response = session_client.patch(
        base.replace("quality/", "") + f"issues/{row['id']}/", {"state_id": str(state.id)}, format="json"
    )
    assert response.status_code in {200, 204}, response.content
    assert Issue.objects.get(pk=row["id"]).state_id == state.id
    serializer = IssueSerializer(
        Issue.objects.get(pk=row["id"]), data={"name": "外部API绕过"}, partial=True, context={"project_id": project.id}
    )
    with pytest.raises(Conflict):
        serializer.is_valid(raise_exception=True)


def test_requirement_acceptance_cancel_archive_restore_do_not_require_testcases(session_client, req_project):
    from plane.db.models import State

    base, project = req_project
    r = session_client.post(
        base + "requirements/", {"title": "简单文案调整", "acceptance": "提示正确可见"}, format="json"
    ).data
    url = base + f"requirements/{r['id']}/workflow/"
    r = session_client.post(url, {"action": "submit", "expected_version": 1}, format="json").data
    r = session_client.post(url, {"action": "approve", "expected_version": r["version"]}, format="json").data
    assert (
        session_client.post(
            url,
            {"action": "accept", "expected_version": r["version"], "comment": "还未开发完成不能验收"},
            format="json",
        ).status_code
        == 400
    )
    completed = State.objects.create(project=project, workspace=project.workspace, name="完成", group="completed")
    issue = Issue.objects.get(pk=r["id"])
    issue.state = completed
    issue.save()
    accepted = session_client.post(
        url, {"action": "accept", "expected_version": r["version"], "comment": "页面提示及位置已核对"}, format="json"
    )
    assert (
        accepted.status_code == 200 and accepted.data["status"] == "completed" and accepted.data["case_count"] == 0
    ), accepted.content
    archived = session_client.post(
        url, {"action": "archive", "expected_version": accepted.data["version"], "comment": "本轮已交付"}, format="json"
    )
    assert archived.status_code == 200 and archived.data["status"] == "archived"
    assert (
        session_client.patch(
            base + f"requirements/{r['id']}/",
            {"expected_version": archived.data["version"], "title": "归档后不可改写"},
            format="json",
        ).status_code
        == 409
    )
    restored = session_client.post(
        url, {"action": "restore", "expected_version": archived.data["version"], "comment": "恢复查看"}, format="json"
    )
    assert restored.status_code == 200 and restored.data["status"] == "completed"


def test_requirement_cancellation_requires_manager_and_reason(session_client, req_project, create_user):
    base, project = req_project
    r = session_client.post(base + "requirements/", {"title": "不再需要的需求"}, format="json").data
    url = base + f"requirements/{r['id']}/workflow/"
    assert session_client.post(url, {"action": "cancel", "expected_version": 1}, format="json").status_code == 400
    cancelled = session_client.post(
        url, {"action": "cancel", "expected_version": 1, "comment": "需求调整，暂不实施"}, format="json"
    )
    assert cancelled.status_code == 200 and cancelled.data["status"] == "cancelled", cancelled.content
    reopened = session_client.post(
        url,
        {"action": "reopen", "expected_version": cancelled.data["version"], "comment": "重新纳入规划"},
        format="json",
    )
    assert reopened.status_code == 200 and reopened.data["status"] == "draft"


def test_requirement_decomposes_into_native_children_and_child_completion_is_required(session_client, req_project):
    from plane.db.models import State

    base, project = req_project
    requirement = session_client.post(
        base + "requirements/", {"title": "用户注册优化", "acceptance": "流程正确且提示清晰"}, format="json"
    ).data
    created = session_client.post(
        base + f"requirements/{requirement['id']}/tasks/",
        {"title": "增加字段提示", "description": "补充中文说明"},
        format="json",
    )
    assert created.status_code == 201, created.content
    task = Issue.objects.get(pk=created.data["id"])
    assert str(task.parent_id) == requirement["id"]
    detail = session_client.get(base + f"requirements/{requirement['id']}/")
    assert detail.data["tasks"][0]["id"] == str(task.id)
    completed = State.objects.create(project=project, workspace=project.workspace, name="完成", group="completed")
    parent = Issue.objects.get(pk=requirement["id"])
    parent.state = completed
    parent.save()
    url = base + f"requirements/{requirement['id']}/workflow/"
    row = session_client.post(url, {"action": "submit", "expected_version": 1}, format="json").data
    row = session_client.post(url, {"action": "approve", "expected_version": row["version"]}, format="json").data
    assert (
        session_client.post(
            url,
            {"action": "accept", "expected_version": row["version"], "comment": "子任务未完成不能验收"},
            format="json",
        ).status_code
        == 400
    )
    task.state = completed
    task.save()
    done = session_client.post(
        url,
        {"action": "accept", "expected_version": row["version"], "comment": "主任务及子任务均已完成，验收符合"},
        format="json",
    )
    assert done.status_code == 200

def test_requirement_recycle_preserves_history_and_restores(session_client, req_project):
    from plane.quality.models import RequirementRevision
    from plane.db.models import Issue

    base, project = req_project
    row = session_client.post(
        base + "requirements/", {"title": "需求删除恢复", "acceptance": "可恢复"}, format="json"
    ).data
    url = base + f"requirements/{row['id']}/workflow/"
    result = session_client.post(
        url, {"action": "trash", "expected_version": 1, "comment": "本轮删除回归"}, format="json"
    )
    assert result.status_code == 200, result.content
    assert result.data["trashed_at"]
    assert session_client.get(base + "requirements/").data["count"] == 0
    deleted = session_client.get(base + "requirements/?deleted=true")
    assert deleted.data["count"] == 1
    assert not Issue.objects.filter(pk=row["id"]).exists()
    assert Issue.all_objects.filter(pk=row["id"]).exists()
    assert RequirementRevision.objects.filter(requirement__issue_id=row["id"]).count() == 2
    stale = session_client.post(url, {"action": "untrash", "expected_version": 1, "comment": "恢复"}, format="json")
    assert stale.status_code == 409
    restored = session_client.post(url, {"action": "untrash", "expected_version": 2, "comment": "恢复"}, format="json")
    assert restored.status_code == 200, restored.content
    assert not restored.data["trashed_at"]
    assert session_client.get(base + "requirements/").data["count"] == 1


def test_requirement_recycle_blocks_review_and_active_children(session_client, req_project):
    base, project = req_project
    row = session_client.post(
        base + "requirements/", {"title": "保留需求", "acceptance": "需要审核"}, format="json"
    ).data
    url = base + f"requirements/{row['id']}/workflow/"
    assert session_client.post(url, {"action": "submit", "expected_version": 1}, format="json").status_code == 200
    assert (
        session_client.post(
            url, {"action": "trash", "expected_version": 2, "comment": "尝试删除"}, format="json"
        ).status_code
        == 409
    )
    assert (
        session_client.post(
            url, {"action": "return", "expected_version": 2, "comment": "退回"}, format="json"
        ).status_code
        == 200
    )
    Issue.objects.create(project=project, workspace=project.workspace, name="关联任务", parent_id=row["id"])
    assert (
        session_client.post(
            url, {"action": "trash", "expected_version": 3, "comment": "仍有任务"}, format="json"
        ).status_code
        == 409
    )
    assert session_client.get(base + "requirements/").data["count"] == 1
