"""Search and summaries cover project results before pagination, never only the visible page."""

from datetime import timedelta
import pytest
from django.utils import timezone
from plane.db.models import Project, ProjectMember
from plane.quality.models import TestCase, TestPlan, Defect, TestSuite, Release, SourceLink
from plane.knowledge.models import Article

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def filtered_project(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="筛选验收", identifier="FILTER")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    return f"/api/workspaces/{workspace.slug}/projects/{project.id}/", project


@pytest.mark.parametrize(
    "resource,model,fields,title_field",
    [
        ("quality/cases", TestCase, {"steps": []}, "title"),
        ("quality/plans", TestPlan, {"build": "v1", "environment": "local"}, "name"),
        ("quality/defects", Defect, {}, "title"),
        ("quality/suites", TestSuite, {}, "name"),
        ("quality/releases", Release, {"version": "v1"}, "name"),
        ("knowledge/articles", Article, {"content": "正文"}, "title"),
    ],
)
def test_search_happens_before_pagination(
    session_client, filtered_project, create_user, resource, model, fields, title_field
):
    base, project = filtered_project
    target = model.objects.create(project=project, created_by=create_user, **{title_field: "较早的匹配需求"}, **fields)
    newer_fields = {**fields, **({"version": "v2"} if model is Release else {})}
    model.objects.create(project=project, created_by=create_user, **{title_field: "较新的其他内容"}, **newer_fields)
    response = session_client.get(base + resource + "/?search=匹配&per_page=1")
    assert response.status_code == 200, response.content
    assert response.data["count"] == 1
    assert response.data["results"][0]["id"] == str(target.id)


def test_defect_combined_filters_and_statistics_have_same_full_scope(
    session_client, filtered_project, create_user, workspace
):
    base, project = filtered_project
    rows = [
        Defect.objects.create(
            project=project,
            created_by=create_user,
            title=f"采集故障{i}",
            severity="major",
            affected_build="v2",
            assignee=create_user,
        )
        for i in range(3)
    ]
    Defect.objects.create(
        project=project,
        created_by=create_user,
        title="不同版本故障",
        severity="minor",
        affected_build="v1",
        status="closed",
    )
    other = Project.objects.create(workspace=workspace, name="隔离项目", identifier="ISOF")
    Defect.objects.create(project=other, title="不可泄漏", severity="major", affected_build="v2")
    for row in rows:
        SourceLink.objects.create(
            project=project,
            created_by=create_user,
            defect=row,
            source_system="DAQ",
            source_instance="test",
            record_type="session",
            record_id=str(row.id),
            device="robot-1",
        )
    query = "?view=assigned_to_me&status=open&severity=major&build=v2&source_system=DAQ&device=robot-1&per_page=1"
    response = session_client.get(base + "quality/defects/" + query)
    assert response.status_code == 200, response.content
    assert response.data["count"] == 3 and len(response.data["results"]) == 1
    stats = session_client.get(base + "quality/defect-statistics/" + query)
    assert stats.status_code == 200, stats.content
    assert stats.data["total"] == 3 and stats.data["unclosed"] == 3
    assert stats.data["by_status"] == [{"value": "open", "count": 3}]
    assert stats.data["by_severity"] == [{"value": "major", "count": 3}]
    assert sum(row["count"] for row in stats.data["opened_by_day"]) == 3
    no_results = session_client.get(base + "quality/defects/" + query.replace("robot-1", "robot-2"))
    assert no_results.status_code == 200 and no_results.data["count"] == 0


@pytest.mark.parametrize(
    "query",
    [
        "status=invalid",
        "assignee_id=invalid",
        "created_after=invalid",
        "created_after=2026-11-06&created_before=2026-01-01",
        "view=invalid",
    ],
)
def test_invalid_filter_is_reported_instead_of_silently_ignored(session_client, filtered_project, query):
    base, _ = filtered_project
    response = session_client.get(base + "quality/defects/?" + query)
    assert response.status_code == 400, response.content


def test_requirement_and_case_domain_filters(session_client, filtered_project, create_user):
    base, project = filtered_project
    r = session_client.post(
        base + "quality/requirements/",
        {"title": "页面提示", "acceptance": "可见", "priority": "low", "target_build": "v2"},
        format="json",
    ).data
    assert session_client.get(base + "quality/requirements/?status=approved").data["count"] == 0
    assert session_client.get(base + "quality/requirements/?status=draft&priority=low&build=v2").data["count"] == 1
    TestCase.objects.create(
        project=project,
        created_by=create_user,
        title="权限用例",
        module="权限",
        priority="high",
        requirement_id=r["id"],
    )
    TestCase.objects.create(project=project, created_by=create_user, title="登录用例", module="账号", priority="low")
    response = session_client.get(base + f"quality/cases/?module=权限&priority=high&requirement_id={r['id']}")
    assert response.data["count"] == 1, response.content
    assert session_client.get(base + "quality/cases/?module=权限&priority=low").data["count"] == 0


def test_plan_owner_status_date_and_pagination_compose(session_client, filtered_project, create_user):
    base, project = filtered_project
    old = TestPlan.objects.create(
        project=project,
        created_by=create_user,
        name="旧计划",
        build="v1",
        environment="local",
        assignee=create_user,
        status="ready",
    )
    TestPlan.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=7))
    TestPlan.objects.create(
        project=project,
        created_by=create_user,
        name="新计划",
        build="v2",
        environment="staging",
        assignee=create_user,
        status="running",
    )
    date = timezone.localdate().isoformat()
    result = session_client.get(
        base
        + "quality/plans/?status=running&assignee_id=me&build=v2&environment=staging"
        + f"&created_after={date}&created_before={date}"
    )
    assert result.status_code == 200 and result.data["count"] == 1, result.content
    assert result.data["results"][0]["name"] == "新计划"


def test_daq_filter_includes_native_report_binding_not_only_generic_source(
    session_client, filtered_project, create_user
):
    from uuid import uuid4
    from plane.db.models import Issue
    from plane.quality.models import DaqBinding, DaqReport

    base, project = filtered_project
    issue = Issue.objects.create(
        project=project, workspace=project.workspace, name="真实来源任务", created_by=create_user
    )
    binding = DaqBinding.objects.create(
        project=project,
        created_by=create_user,
        source_instance="daq-test",
        platform_task_id=24,
        source_record_id="session-1",
        issue=issue,
        device="robot-live",
    )
    defect = Defect.objects.create(project=project, created_by=create_user, title="DAQ原生上报")
    DaqReport.objects.create(
        project=project,
        created_by=create_user,
        binding=binding,
        defect=defect,
        request_id=uuid4(),
        request_hash="hash",
        category="Other",
    )
    response = session_client.get(base + "quality/defects/?source_system=DAQ&device=robot-live&task_id=24")
    assert response.status_code == 200 and response.data["count"] == 1, response.content
    assert response.data["results"][0]["id"] == str(defect.id)
