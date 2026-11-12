"""Verification depends on the reviewed impact, independently of report origin."""

from uuid import uuid4
import pytest
from plane.db.models import Project, ProjectMember, Issue
from plane.quality.models import Defect, DaqBinding, DaqReport

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def scope_case(session_client, workspace, create_user):
    p = Project.objects.create(workspace=workspace, name="验证方式", identifier="VERIFY")
    ProjectMember.objects.create(project=p, member=create_user, role=20)
    base = f"/api/workspaces/{workspace.slug}/projects/{p.id}/quality/"
    row = session_client.post(base + "defects/", {"title": "DAQ按钮提示错误"}, format="json").data
    issue = Issue.objects.create(project=p, workspace=workspace, name="来源任务", created_by=create_user)
    binding = DaqBinding.objects.create(
        project=p,
        created_by=create_user,
        source_instance="test",
        platform_task_id=4,
        source_record_id="baseline",
        issue=issue,
    )
    DaqReport.objects.create(
        project=p,
        created_by=create_user,
        binding=binding,
        defect_id=row["id"],
        request_id=uuid4(),
        request_hash="scope",
        category="Other",
    )
    return base, p, row


def test_manager_can_route_daq_page_fix_to_functional_verification(session_client, scope_case):
    base, p, row = scope_case
    url = base + f"defects/{row['id']}/"
    changed = session_client.patch(
        url,
        {
            "verification_scope": "functional",
            "verification_scope_reason": "仅修改按钮提示，不影响录制、QC或上传数据",
            "expected_version": 1,
        },
        format="json",
    )
    assert changed.status_code == 200, changed.content
    assert changed.data["requires_data_regression"] is False
    assert changed.data["manual_verification_allowed"] is True
    assert any("仅修改按钮提示" in event["note"] for event in changed.data["events"])
    resolved = session_client.patch(
        url, {"status": "resolved", "fixed_build": "ui-v2", "resolution": "修正按钮提示"}, format="json"
    )
    assert resolved.status_code == 200
    closed = session_client.patch(
        url,
        {
            "status": "closed",
            "verification_method": "manual",
            "verification_note": "测试员已在ui-v2点击按钮，确认提示准确；经理复核",
        },
        format="json",
    )
    assert closed.status_code == 200 and closed.data["status"] == "closed", closed.content


def test_scope_change_needs_reason_manager_and_separate_close(session_client, scope_case, create_user):
    base, p, row = scope_case
    url = base + f"defects/{row['id']}/"
    assert session_client.patch(url, {"verification_scope": "functional"}, format="json").status_code == 400
    ProjectMember.objects.filter(project=p, member=create_user).update(role=15)
    Defect.objects.filter(pk=row["id"]).update(assignee=create_user)
    denied = session_client.patch(
        url,
        {"verification_scope": "functional", "verification_scope_reason": "技术员不能自行降低验证方式"},
        format="json",
    )
    assert denied.status_code == 403
    ProjectMember.objects.filter(project=p, member=create_user).update(role=20)
    combined = session_client.patch(
        url,
        {"verification_scope": "functional", "verification_scope_reason": "须先保存分类", "status": "closed"},
        format="json",
    )
    assert combined.status_code == 400


def test_external_data_verification_is_not_supported_in_standalone_platform(session_client, scope_case):
    base, project, row = scope_case
    response = session_client.patch(
        base + f"defects/{row['id']}/",
        {"verification_scope": "data", "verification_scope_reason": "外部平台已取消"},
        format="json",
    )
    assert response.status_code == 400, response.content
    assert not response.data.get("requires_data_regression")


def test_retired_data_regression_route_never_reactivates_upstream_lookup(session_client, scope_case, mocker):
    base, project, row = scope_case
    outbound = mocker.patch("plane.quality.platform.fetch", side_effect=AssertionError("No external regression"))
    response = session_client.post(base + "data-regressions/", {"defect_id": row["id"]}, format="json")
    assert response.status_code == 404, response.content
    outbound.assert_not_called()


def test_functional_close_creates_reviewable_knowledge_with_verified_context(session_client, scope_case, create_user):
    from plane.knowledge.models import Article
    from plane.quality.models import Solution, SolutionRevision

    base, project, _ = scope_case
    row = session_client.post(
        base + "defects/", {"title": "按钮提示错误", "description": "保存成功后显示失败提示"}, format="json"
    ).data
    defect = Defect.objects.get(pk=row["id"])
    solution = Solution.objects.create(
        project=project,
        created_by=create_user,
        defect=defect,
        title="修正保存提示",
        root_cause="不可引用的未审核改动",
        steps="不可引用的未审核步骤",
        verification="重新点击保存",
        status="approved",
        submitted_version=1,
    )
    SolutionRevision.objects.create(
        project=project,
        created_by=create_user,
        solution=solution,
        version=1,
        snapshot={
            "title": "修正保存提示",
            "root_cause": "成功分支引用了失败文案",
            "steps": "修正成功提示映射",
            "verification": "保存后核对提示和实际保存结果",
        },
        reviewer_ids=[str(create_user.id)],
        required_count=1,
    )
    url = base + f"defects/{defect.id}/"
    assert (
        session_client.patch(
            url, {"status": "resolved", "fixed_build": "ui-v3", "resolution": "已修正提示映射"}, format="json"
        ).status_code
        == 200
    )
    closed = session_client.patch(
        url,
        {
            "status": "closed",
            "verification_method": "manual",
            "verification_note": "连续保存三次，提示成功且数据持久化，经理复核通过",
        },
        format="json",
    )
    assert closed.status_code == 200, closed.content
    draft = Article.objects.get(source_defect=defect)
    assert draft.status == "draft" and draft.publication_active is False
    assert draft.source_regression_id is None
    assert "成功分支引用了失败文案" in draft.content
    assert "修正成功提示映射" in draft.content
    assert "连续保存三次" in draft.content and "ui-v3" in draft.content
    assert "不可引用的未审核" not in draft.content
    assert "新数据回归通过" not in draft.content
    assert session_client.patch(url, {"status": "closed"}, format="json").status_code == 400
    assert Article.objects.filter(source_defect=defect).count() == 1
    reopened = session_client.patch(url, {"status": "open", "resolution": "另一种操作仍有问题"}, format="json")
    assert reopened.status_code == 200
    draft.refresh_from_db()
    assert draft.status == "offline" and draft.publication_active is False


def test_functional_close_without_reviewed_solution_does_not_invent_root_cause(session_client, scope_case):
    from plane.knowledge.models import Article

    base, _, _ = scope_case
    row = session_client.post(base + "defects/", {"title": "更新按钮文字"}, format="json").data
    url = base + f"defects/{row['id']}/"
    assert (
        session_client.patch(
            url, {"status": "resolved", "fixed_build": "ui-v4", "resolution": "按钮改为保存"}, format="json"
        ).status_code
        == 200
    )
    assert (
        session_client.patch(
            url,
            {"status": "closed", "verification_method": "manual", "verification_note": "按钮文字显示保存，操作正常"},
            format="json",
        ).status_code
        == 200
    )
    draft = Article.objects.get(source_defect_id=row["id"])
    assert draft.status == "draft" and "按钮改为保存" in draft.content
    assert "根因：" not in draft.content and "新数据" not in draft.content
