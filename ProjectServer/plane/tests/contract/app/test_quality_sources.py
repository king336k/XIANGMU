import pytest
from plane.db.models import Project, ProjectMember

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def source_project(workspace, create_user):
    p = Project.objects.create(workspace=workspace, name="来源工单", identifier="SRC")
    ProjectMember.objects.create(project=p, member=create_user, role=20)
    return f"/api/workspaces/{workspace.slug}/projects/{p.id}/quality/", p


def test_source_dedup_and_task_relation(session_client, source_project):
    base, project = source_project
    payload = {
        "source_system": "daq",
        "source_instance": "local",
        "record_type": "session",
        "record_id": "session-abc",
        "title": "采集数据异常",
        "description": "有日志证据",
        "device": "robot-1",
        "task_id": "task-123",
        "package_id": "package-456",
    }
    first = session_client.post(base + "source-defects/", payload, format="json")
    assert first.status_code == 201, first.content
    retry = session_client.post(base + "source-defects/", payload, format="json")
    assert retry.status_code == 200 and retry.data["defect"]["id"] == first.data["defect"]["id"]
    assert first.data["source"]["record_id"] == "session-abc"
    assert first.data["source"]["task_id"] == "task-123"


def test_issue_claim_comments_and_audit(session_client, source_project):
    base, project = source_project
    defect = session_client.post(base + "defects/", {"title": "协作工单"}, format="json").data
    url = base + f"defects/{defect['id']}/collaboration/"
    claimed = session_client.post(url, {"action": "claim"}, format="json")
    assert claimed.status_code == 200
    assert claimed.data["status"] == "in_progress"
    comment = session_client.post(url, {"action": "comment", "content": "已核对来源，继续分析"}, format="json")
    assert comment.status_code == 201
    listed = session_client.get(url)
    assert listed.status_code == 200 and listed.data["count"] == 1
    assert listed.data["results"][0]["content"] == "已核对来源，继续分析"


def test_problem_package_import_preflight_and_idempotency(session_client, source_project):
    base, project = source_project
    defect = session_client.post(base + "defects/", {"title": "问题包关联"}, format="json").data
    manifest = {
        "name": "测试问题包",
        "defect_id": defect["id"],
        "files": [{"path": "logs/capture.log", "size": 18, "sha256": "a" * 64}],
        "source_system": "daq",
        "external_id": "test-pkg-1",
    }
    preview = session_client.post(base + "packages/preflight/", manifest, format="json")
    assert preview.status_code == 200 and preview.data["valid"]
    created = session_client.post(base + "packages/", manifest, format="json")
    assert created.status_code == 201, created.data
    retry = session_client.post(base + "packages/", manifest, format="json")
    assert retry.status_code == 200 and retry.data["id"] == created.data["id"]
    bad = {**manifest, "files": [{"path": "../../etc/passwd", "size": 1, "sha256": "a" * 64}]}
    assert session_client.post(base + "packages/preflight/", bad, format="json").status_code == 400
    bad = {**manifest, "files": [{"path": "logs/secret", "size": -1, "sha256": "invalid"}]}
    assert session_client.post(base + "packages/preflight/", bad, format="json").status_code == 400


def test_retries_do_not_duplicate_claim_audit(session_client, source_project):
    from plane.quality.models import DefectEvent

    base, _ = source_project
    defect = session_client.post(base + "defects/", {"title": "重复认领"}, format="json").data
    url = base + f"defects/{defect['id']}/collaboration/"
    assert session_client.post(url, {"action": "claim"}, format="json").status_code == 200
    count = DefectEvent.objects.filter(defect_id=defect["id"]).count()
    assert session_client.post(url, {"action": "claim"}, format="json").status_code == 200
    assert DefectEvent.objects.filter(defect_id=defect["id"]).count() == count


def test_source_identity_conflict_preserves_original(session_client, source_project):
    base, _ = source_project
    data = {
        "source_system": "daq",
        "source_instance": "local",
        "record_type": "session",
        "record_id": "stable",
        "title": "来源问题",
        "device": "robot-a",
    }
    original = session_client.post(base + "source-defects/", data, format="json")
    assert original.status_code == 201
    conflict = session_client.post(base + "source-defects/", {**data, "device": "robot-b"}, format="json")
    assert conflict.status_code == 409
    sources = session_client.get(base + f"defects/{original.data['defect']['id']}/sources/")
    assert sources.data[0]["device"] == "robot-a"


def test_package_conflict_scope_guest_and_path_validation(session_client, source_project, workspace, create_user):
    from plane.quality.models import Defect, ProblemPackage

    base, project = source_project
    defect = session_client.post(base + "defects/", {"title": "范围隔离"}, format="json").data
    other = Project.objects.create(workspace=workspace, name="其他项目", identifier="OTHER")
    foreign = Defect.objects.create(project=other, title="其他缺陷")
    manifest = {
        "name": "包",
        "defect_id": defect["id"],
        "source_system": "daq",
        "external_id": "stable",
        "files": [{"path": "logs/a.txt", "size": 0, "sha256": "0" * 64}],
    }
    assert session_client.post(base + "packages/", manifest, format="json").status_code == 201
    assert session_client.post(base + "packages/", {**manifest, "name": "内容变更"}, format="json").status_code == 409
    assert (
        session_client.post(base + "packages/", {**manifest, "defect_id": str(foreign.id)}, format="json").status_code
        == 404
    )
    assert session_client.get(base + f"defects/{foreign.id}/sources/").status_code == 404
    assert session_client.get(base + "packages/?defect_id=invalid").status_code == 400
    assert ProblemPackage.objects.filter(project=project).count() == 1
    for path in ["/etc/passwd", "C:\\logs\\a", "logs/../a", "logs//a", "logs/./a", "a\x00b"]:
        bad = {**manifest, "files": [{"path": path, "size": 0, "sha256": "0" * 64}]}
        assert session_client.post(base + "packages/preflight/", bad, format="json").status_code == 400
    ProjectMember.objects.filter(project=project, member=create_user).update(role=5)
    assert session_client.get(base + "packages/").status_code == 200
    assert session_client.post(base + "packages/", manifest, format="json").status_code == 403
    assert (
        session_client.post(
            base + f"defects/{defect['id']}/collaboration/", {"action": "claim"}, format="json"
        ).status_code
        == 403
    )
