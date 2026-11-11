"""Case pickers stay paginated and bulk selection uses the exact authorized filter scope."""

import pytest
from django.utils import timezone
from plane.db.models import Project, ProjectMember
from plane.quality.models import TestCase

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def picker(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="批量用例选择", identifier="PICK")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    TestCase.objects.bulk_create(
        [
            TestCase(
                project=project,
                title=f"上传校验 {i:03d}",
                module="数据上传",
                priority="high",
                steps=[{"action": "保留在详情，选用时不传输", "expected": "不应在选项传输"}],
            )
            for i in range(125)
        ]
    )
    TestCase.objects.bulk_create(
        [TestCase(project=project, title=f"采集场景 {i:03d}", module="数据采集", priority="medium") for i in range(400)]
    )
    TestCase.objects.create(project=project, title="归档用例", module="不应出现", archived_at=timezone.now())
    return f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/", project


def test_picker_pages_lightweight_rows_with_module_counts_and_exact_filtered_selection(session_client, picker):
    base, project = picker
    response = session_client.get(base + "case-options/?module=数据上传&priority=high&page=3&per_page=50")
    assert response.status_code == 200, response.content
    assert response.data["count"] == 125 and len(response.data["results"]) == 25
    assert "steps" not in response.data["results"][0]
    assert {row["module"]: row["count"] for row in response.data["modules"]} == {"数据上传": 125, "数据采集": 400}
    selected = session_client.get(base + "case-options/?module=数据上传&priority=high&selection=true")
    assert selected.status_code == 200 and len(selected.data["results"]) == 125
    assert all(row["module"] == "数据上传" for row in selected.data["results"])


def test_bulk_selection_above_existing_500_limit_is_rejected_without_silent_truncation(session_client, picker):
    base, project = picker
    response = session_client.get(base + "case-options/?selection=true")
    assert response.status_code == 400 and "500" in str(response.data), response.content
    assert session_client.get(base + "case-options/?search=上传校验%20001").data["count"] == 1


def test_case_picker_never_leaks_foreign_project_or_archived_cases(session_client, picker, workspace, create_user):
    base, project = picker
    other = Project.objects.create(workspace=workspace, name="其他项目", identifier="FPICK")
    TestCase.objects.create(project=other, title="上传校验 外项目", module="外部")
    response = session_client.get(base + "case-options/?selection=true&module=数据上传")
    assert response.status_code == 200 and response.data["count"] == 125, response.content
    ProjectMember.objects.filter(project=project, member=create_user).update(is_active=False)
    assert session_client.get(base + "case-options/").status_code == 403
