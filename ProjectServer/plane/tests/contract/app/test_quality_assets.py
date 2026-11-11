from uuid import uuid4
import pytest
from plane.db.models import Project, ProjectMember

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def assets(session_client, workspace, create_user):
    p = Project.objects.create(workspace=workspace, name="发布测试", identifier="RL")
    ProjectMember.objects.create(project=p, member=create_user, role=20)
    base = f"/api/workspaces/{workspace.slug}/projects/{p.id}/quality/"
    case = session_client.post(
        base + "cases/", {"title": "发布验证", "steps": [{"action": "操作", "expected": "成功"}]}, format="json"
    ).data
    return base, case


def test_suite_freezes_revisions_and_creates_plan(session_client, assets):
    base, case = assets
    created = session_client.post(base + "suites/", {"name": "冒烟套件", "case_ids": [case["id"]]}, format="json")
    assert created.status_code == 201, created.content
    suite = created.data
    session_client.patch(base + f"cases/{case['id']}/", {"expected_version": 1, "title": "后改标题"}, format="json")
    published = session_client.post(base + f"suites/{suite['id']}/publish/", {}, format="json")
    assert published.status_code == 200
    plan = session_client.post(
        base + "plans/",
        {"name": "套件生成计划", "build": "v1", "environment": "staging", "suite_id": suite["id"]},
        format="json",
    )
    assert plan.status_code == 201, plan.data
    assert plan.data["items"][0]["revision"]["version"] == 1
    assert plan.data["items"][0]["revision"]["title"] == "发布验证"


def test_release_admission_requires_completed_managed_plans(session_client, assets):
    base, case = assets
    plan = session_client.post(
        base + "plans/",
        {"name": "未验收计划", "build": "v1", "environment": "staging", "case_ids": [case["id"]], "managed": True},
        format="json",
    ).data
    r = session_client.post(
        base + "releases/", {"name": "第一个版本", "version": "v1", "plan_ids": [plan["id"]]}, format="json"
    )
    assert r.status_code == 201, r.content
    release = r.data
    denied = session_client.post(base + f"releases/{release['id']}/admit/", {"expected_version": 1}, format="json")
    assert denied.status_code == 400
    report = session_client.get(base + f"releases/{release['id']}/").data
    assert report["readiness"]["ready"] is False
    assert report["readiness"]["blockers"]


def test_foreign_suite_cases_and_release_plans_rejected(session_client, assets):
    base, case = assets
    assert (
        session_client.post(base + "suites/", {"name": "非法", "case_ids": [str(uuid4())]}, format="json").status_code
        == 400
    )
    assert (
        session_client.post(
            base + "releases/", {"name": "非法", "version": "v1", "plan_ids": [str(uuid4())]}, format="json"
        ).status_code
        == 400
    )


def test_release_acceptance_is_snapshot_and_does_not_trigger_external_publish(session_client, assets):
    from plane.quality.models import TestPlan

    base, case = assets
    plan = session_client.post(
        base + "plans/",
        {"name": "完成测试", "build": "v2", "environment": "staging", "case_ids": [case["id"]], "managed": True},
        format="json",
    ).data
    from plane.quality.models import TestExecution
    from uuid import uuid4

    TestExecution.objects.create(
        project_id=TestPlan.objects.get(pk=plan["id"]).project_id,
        item_id=plan["items"][0]["id"],
        request_id=uuid4(),
        result="passed",
    )
    TestPlan.objects.filter(pk=plan["id"]).update(status="completed")
    release = session_client.post(
        base + "releases/", {"name": "版本2", "version": "v2", "plan_ids": [plan["id"]]}, format="json"
    ).data
    approved = session_client.post(base + f"releases/{release['id']}/admit/", {"expected_version": 1}, format="json")
    assert approved.status_code == 200 and approved.data["status"] == "admitted"
    assert approved.data["admission_snapshot"]["plans"][0]["id"] == plan["id"]
    assert approved.data["admitted_at"]


def test_saved_report_snapshot_rename_download_and_retry(session_client, workspace, create_user):
    from plane.db.models import Project, ProjectMember
    from uuid import uuid4

    p = Project.objects.create(workspace=workspace, name="报告", identifier="REPORT")
    ProjectMember.objects.create(project=p, member=create_user, role=20)
    base = f"/api/workspaces/{workspace.slug}/projects/{p.id}/quality/"
    case = session_client.post(
        base + "cases/", {"title": "原始用例", "steps": [{"action": "执行", "expected": "成功"}]}, format="json"
    ).data
    plan = session_client.post(
        base + "plans/",
        {"name": "报告计划", "build": "v1", "environment": "本地", "case_ids": [case["id"]]},
        format="json",
    ).data
    payload = {"name": "测试报告", "plan_id": plan["id"], "request_id": str(uuid4())}
    created = session_client.post(base + "reports/", payload, format="json")
    assert created.status_code == 201, created.content
    report = created.data
    assert report["snapshot"]["summary"]["pending"] == 1
    assert session_client.post(base + "reports/", payload, format="json").data["id"] == report["id"]
    session_client.post(
        base + f"items/{plan['items'][0]['id']}/executions/",
        {"result": "passed", "actual_result": "成功", "request_id": str(uuid4())},
        format="json",
    )
    detail = base + f"reports/{report['id']}/"
    assert session_client.get(detail).data["snapshot"]["summary"]["pending"] == 1
    renamed = session_client.patch(detail, {"name": "改名后的报告", "expected_version": 1}, format="json")
    assert renamed.status_code == 200 and renamed.data["edit_version"] == 2
    assert session_client.patch(detail, {"name": "旧页面覆盖", "expected_version": 1}, format="json").status_code == 409
    download = session_client.get(detail + "download/")
    assert download.status_code == 200 and "attachment" in download["Content-Disposition"]
    assert "改名后的报告" in download.content.decode()
    assert "原始用例" in download.content.decode()


def test_report_project_scope_guest_and_idempotency_conflict(session_client, workspace, create_user):
    from plane.db.models import Project, ProjectMember
    from plane.quality.models import TestPlan
    from uuid import uuid4

    p = Project.objects.create(workspace=workspace, name="报告权限", identifier="RPT")
    ProjectMember.objects.create(project=p, member=create_user, role=20)
    other = Project.objects.create(workspace=workspace, name="其他", identifier="OTH")
    foreign = TestPlan.objects.create(project=other, name="不可读取", build="v1", environment="本地")
    base = f"/api/workspaces/{workspace.slug}/projects/{p.id}/quality/"
    request = {"name": "项目报告", "request_id": str(uuid4())}
    assert (
        session_client.post(base + "reports/", {**request, "plan_id": str(foreign.id)}, format="json").status_code
        == 404
    )
    saved = session_client.post(base + "reports/", request, format="json")
    assert saved.status_code == 201
    assert session_client.post(base + "reports/", {**request, "name": "另一个报告"}, format="json").status_code == 409
    ProjectMember.objects.filter(project=p, member=create_user).update(role=5)
    assert session_client.get(base + f"reports/{saved.data['id']}/download/").status_code == 200
    assert (
        session_client.post(base + "reports/", {**request, "request_id": str(uuid4())}, format="json").status_code
        == 403
    )


def test_case_import_preflight_errors_and_confirm_once(session_client, workspace, create_user):
    from plane.db.models import Project, ProjectMember
    from plane.quality.models import TestCase

    p = Project.objects.create(workspace=workspace, name="导入", identifier="IMP")
    ProjectMember.objects.create(project=p, member=create_user, role=20)
    base = f"/api/workspaces/{workspace.slug}/projects/{p.id}/quality/"
    rows = [{"title": "导入场景", "steps": [{"action": "打开页面", "expected": "显示内容"}]}]
    invalid = session_client.post(
        base + "case-imports/", {"name": "不合法", "cases": rows + [{"title": "缺少步骤"}]}, format="json"
    )
    assert invalid.status_code == 200 and not invalid.data["valid"]
    assert invalid.data["errors"][0]["row"] == 2
    assert "必填" in str(invalid.data["errors"][0]["fields"]["steps"])
    assert TestCase.objects.filter(project=p).count() == 0
    assert (
        session_client.post(base + f"case-imports/{invalid.data['id']}/confirm/", {}, format="json").status_code == 400
    )
    preview = session_client.post(base + "case-imports/", {"name": "用例导入", "cases": rows}, format="json")
    assert preview.status_code == 200 and preview.data["valid"]
    assert TestCase.objects.filter(project=p).count() == 0
    imported = session_client.post(base + f"case-imports/{preview.data['id']}/confirm/", {}, format="json")
    assert imported.status_code == 200 and imported.data["status"] == "confirmed"
    assert imported.data["case_ids"]
    retry = session_client.post(base + f"case-imports/{preview.data['id']}/confirm/", {}, format="json")
    assert retry.data["case_ids"] == imported.data["case_ids"]
    case = TestCase.objects.get(project=p)
    assert case.title == "导入场景" and case.version == 1 and case.revisions.count() == 1


def test_case_import_rejects_foreign_requirements_and_confirm_is_project_scoped(session_client, workspace, create_user):
    from plane.db.models import Project, ProjectMember, Issue

    p = Project.objects.create(workspace=workspace, name="导入范围", identifier="ISCOPE")
    other = Project.objects.create(workspace=workspace, name="其他项目", identifier="IOTHER")
    ProjectMember.objects.create(project=p, member=create_user, role=20)
    ProjectMember.objects.create(project=other, member=create_user, role=20)
    foreign = Issue.objects.create(project=other, workspace=workspace, name="其他需求")
    base = f"/api/workspaces/{workspace.slug}/projects/{p.id}/quality/"
    row = {"title": "测试", "steps": [{"action": "执行", "expected": "成功"}], "requirement_id": str(foreign.id)}
    preview = session_client.post(base + "case-imports/", {"name": "来源范围", "cases": [row]}, format="json")
    assert preview.status_code == 200 and not preview.data["valid"]
    assert preview.data["errors"][0]["row"] == 1
    foreign_base = f"/api/workspaces/{workspace.slug}/projects/{other.id}/quality/"
    assert (
        session_client.post(foreign_base + f"case-imports/{preview.data['id']}/confirm/", {}, format="json").status_code
        == 404
    )


def test_admitted_release_cannot_overwrite_first_admission(session_client, assets):
    from plane.quality.models import Release

    base, case = assets
    from plane.quality.models import TestCase

    project = TestCase.objects.get(pk=case["id"]).project
    release = Release.objects.create(
        project=project,
        name="已准入",
        version="stable",
        status="admitted",
        edit_version=2,
        admission_snapshot={"ready": True, "original": "immutable"},
    )
    response = session_client.post(base + f"releases/{release.id}/admit/", {"expected_version": 2}, format="json")
    assert response.status_code == 200
    release.refresh_from_db()
    assert release.edit_version == 2 and release.admission_snapshot == {"ready": True, "original": "immutable"}


def test_suite_draft_edit_publish_copy_keeps_original_frozen_revisions(session_client, assets):
    base, case = assets
    suite = session_client.post(
        base + "suites/", {"name": "常用冒烟组合", "case_ids": [case["id"]]}, format="json"
    ).data
    url = base + f"suites/{suite['id']}/"
    edited = session_client.patch(
        url, {"name": "已完善的冒烟组合", "case_ids": [case["id"]], "expected_version": 1}, format="json"
    )
    assert edited.status_code == 200 and edited.data["edit_version"] == 2, edited.content
    assert session_client.patch(url, {"name": "旧页面覆盖", "expected_version": 1}, format="json").status_code == 409
    assert (
        session_client.post(base + f"suites/{suite['id']}/publish/", {"expected_version": 2}, format="json").status_code
        == 200
    )
    assert (
        session_client.patch(url, {"name": "改写已发布内容", "expected_version": 3}, format="json").status_code == 409
    )
    assert (
        session_client.patch(
            base + f"cases/{case['id']}/", {"title": "新版验证步骤", "expected_version": 1}, format="json"
        ).status_code
        == 200
    )
    copied = session_client.post(
        base + f"suites/{suite['id']}/copy/", {"name": "下一版冒烟组合", "use_latest": True}, format="json"
    )
    assert copied.status_code == 201, copied.content
    assert copied.data["published"] is False and copied.data["items"][0]["revision"]["version"] == 2
    original = session_client.get(url)
    assert original.status_code == 200 and original.data["items"][0]["revision"]["version"] == 1


def test_suite_creation_and_edit_reject_guest_and_foreign_case(session_client, assets):
    base, case = assets
    suite = session_client.post(base + "suites/", {"name": "权限组合", "case_ids": [case["id"]]}, format="json").data
    url = base + f"suites/{suite['id']}/"
    assert (
        session_client.patch(url, {"expected_version": 1, "case_ids": [str(uuid4())]}, format="json").status_code == 400
    )
    from plane.quality.models import TestSuite

    project_id = TestSuite.objects.get(pk=suite["id"]).project_id
    ProjectMember.objects.filter(project_id=project_id).update(role=5)
    assert session_client.patch(url, {"expected_version": 1, "name": "访客改写"}, format="json").status_code == 403
    assert (
        session_client.post(base + f"suites/{suite['id']}/copy/", {"name": "访客复制"}, format="json").status_code
        == 403
    )


def test_edit_suite_draft_preserves_existing_case_revision_until_explicit_latest_copy(session_client, assets):
    base, case = assets
    suite = session_client.post(base + "suites/", {"name": "原组合", "case_ids": [case["id"]]}, format="json").data
    assert (
        session_client.patch(
            base + f"cases/{case['id']}/", {"expected_version": 1, "title": "改过的用例"}, format="json"
        ).status_code
        == 200
    )
    response = session_client.patch(
        base + f"suites/{suite['id']}/",
        {"expected_version": 1, "name": "只改组合标题", "case_ids": [case["id"]]},
        format="json",
    )
    assert response.status_code == 200
    assert response.data["items"][0]["revision"]["version"] == 1


def test_release_draft_can_edit_and_confirmed_release_requires_new_copy(session_client, assets):
    base, case = assets
    p = session_client.post(
        base + "plans/",
        {"name": "发版安排", "build": "v-draft", "environment": "local", "case_ids": [case["id"]], "managed": True},
        format="json",
    ).data
    r = session_client.post(
        base + "releases/", {"name": "初始发布", "version": "v-draft", "plan_ids": [p["id"]]}, format="json"
    ).data
    updated = session_client.patch(
        base + f"releases/{r['id']}/",
        {"expected_version": r["edit_version"], "name": "修改发布说明", "description": "本轮更改范围"},
        format="json",
    )
    assert updated.status_code == 200 and updated.data["edit_version"] == 2, updated.content
    from plane.quality.models import Release

    Release.objects.filter(pk=r["id"]).update(status="admitted")
    assert (
        session_client.patch(
            base + f"releases/{r['id']}/", {"expected_version": 2, "name": "不可覆盖已确认快照"}, format="json"
        ).status_code
        == 409
    )
    copied = session_client.post(
        base + f"releases/{r['id']}/copy/",
        {"name": "下一轮发布", "version": "v-next", "expected_version": 2},
        format="json",
    )
    assert copied.status_code == 201, copied.content
    assert copied.data["status"] == "draft" and not copied.data["admission_snapshot"]
