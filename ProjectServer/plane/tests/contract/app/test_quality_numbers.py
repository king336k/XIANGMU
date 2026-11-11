import pytest
from plane.db.models import Project, ProjectMember
from plane.quality.models import Defect, TestCase, TestPlan, TestSuite

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def numbered_project(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="业务编号", identifier="QNUM")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    return project


def test_quality_numbers_are_separate_stable_and_never_reused(numbered_project):
    project = numbered_project
    first = Defect.objects.create(project=project, title="原缺陷")
    case = TestCase.objects.create(project=project, title="用例")
    assert first.code == "QNUM-D-1" and case.code == "QNUM-C-1"
    first.title = "改标题"
    first.save()
    assert first.code == "QNUM-D-1"
    first.delete()
    second = Defect.objects.create(project=project, title="新缺陷")
    assert second.code == "QNUM-D-2"
    suite = TestSuite.objects.create(project=project, name="用例集")
    plan = TestPlan.objects.create(project=project, name="测试计划", build="1", environment="本地")
    assert suite.code == "QNUM-S-1" and plan.code == "QNUM-P-1"


def test_number_search_combines_with_filters_and_stays_in_project(session_client, numbered_project, workspace):
    project = numbered_project
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/"
    first = session_client.post(base + "defects/", {"title": "连接失败"}, format="json")
    assert first.status_code == 201
    assert first.data["code"] == "QNUM-D-1" and first.data["number"] == 1
    session_client.post(base + "defects/", {"title": "另一个缺陷"}, format="json")
    other = Project.objects.create(workspace=workspace, name="其他项目", identifier="OTHERQ")
    Defect.objects.create(project=other, title="连接失败")
    assert session_client.get(base + "defects/", {"search": "qnum-d-1"}).data["count"] == 1
    assert session_client.get(base + "defects/", {"code": "QNUM-D-1", "status": "closed"}).data["count"] == 0
    assert session_client.get(base + "defects/", {"number": 2}).data["count"] == 1
    assert session_client.get(base + "defects/", {"search": "OTHERQ-D-1"}).data["count"] == 0
    assert session_client.get(base + "defects/", {"number": "invalid"}).status_code == 400
    assert session_client.get(base + "defects/", {"search": "连接"}).data["count"] == 1


def test_records_do_not_accept_client_supplied_number(session_client, numbered_project, workspace):
    base = f"/api/workspaces/{workspace.slug}/projects/{numbered_project.id}/quality/"
    response = session_client.post(
        base + "defects/", {"title": "普通新建", "code": "QNUM-D-99", "number": 99}, format="json"
    )
    assert response.status_code == 201 and response.data["code"] == "QNUM-D-1"


def test_number_allocation_rolls_back_with_record(numbered_project):
    from django.db import transaction

    try:
        with transaction.atomic():
            Defect.objects.create(project=numbered_project, title="未提交")
            raise ValueError
    except ValueError:
        pass
    assert Defect.objects.create(project=numbered_project, title="已提交").code == "QNUM-D-1"


def test_number_lookup_returns_authorized_record_and_specific_link(session_client, numbered_project, workspace):
    row = Defect.objects.create(project=numbered_project, title="可以查看")
    url = "/api/quality-auth/record-number/"
    response = session_client.get(url, {"workspace": workspace.slug, "code": row.code})
    assert response.status_code == 200, response.content
    assert response.data["results"][0]["url"].endswith(f"/defects/?defect={row.pk}")
    ProjectMember.objects.filter(project=numbered_project).update(is_active=False)
    assert session_client.get(url, {"workspace": workspace.slug, "code": row.code}).data["results"] == []


def test_backfill_assigns_old_records_once_in_creation_order(numbered_project):
    from importlib import import_module
    from django.apps import apps
    from django.db import connection
    from plane.quality.models import BusinessNumber

    rows = [Defect.objects.create(project=numbered_project, title=f"历史{index}") for index in range(3)]
    BusinessNumber.objects.filter(project=numbered_project).delete()
    import_module("plane.quality.migrations.0038_backfill_business_numbers").populate(apps, connection.schema_editor())
    assert list(
        BusinessNumber.objects.filter(project=numbered_project).order_by("number").values_list("object_id", flat=True)
    ) == [r.id for r in rows]
    assert Defect.objects.create(project=numbered_project, title="迁移后").code == "QNUM-D-4"


@pytest.mark.django_db(transaction=True)
def test_concurrent_daq_and_web_creations_get_distinct_numbers(numbered_project):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from django.db import close_old_connections

    barrier = Barrier(4)

    def create(index):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return Defect.objects.create(project_id=numbered_project.id, title=f"并发{index}").code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=4) as executor:
        codes = list(executor.map(create, range(4)))
    assert set(codes) == {f"QNUM-D-{i}" for i in range(1, 5)}
