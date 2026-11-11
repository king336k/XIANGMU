"""Creation provenance survives assignment and editing by another person."""

import pytest
from plane.db.models import Project, ProjectMember, WorkspaceMember, User

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def test_core_records_return_real_creator_on_create_list_and_detail(session_client, workspace, create_user):
    create_user.display_name = "创建同事"
    create_user.save()
    project = Project.objects.create(workspace=workspace, name="来源核对", identifier="AUTHOR")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/"
    records = []
    for endpoint, payload in [
        ("cases", {"title": "用例", "steps": [{"action": "检查", "expected": "成功"}]}),
        ("defects", {"title": "缺陷"}),
        ("requirements", {"title": "需求", "acceptance": "显示创建人"}),
        ("versions", {"name": "版本", "version": "v1"}),
    ]:
        result = session_client.post(base + endpoint + "/", payload, format="json")
        assert result.status_code == 201, result.content
        assert result.data["created_by_id"] == str(create_user.id)
        assert result.data["created_by_name"] == "创建同事"
        records.append((endpoint, result.data["id"]))
    case_id = records[0][1]
    plan = session_client.post(
        base + "plans/",
        {"name": "测试计划", "build": "v1", "environment": "隔离", "case_ids": [case_id]},
        format="json",
    )
    assert plan.status_code == 201, plan.content
    records.append(("plans", plan.data["id"]))
    editor = User.objects.create(email="editor@accounts.invalid", username="editor", display_name="处理同事")
    WorkspaceMember.objects.create(workspace=workspace, member=editor, role=15)
    ProjectMember.objects.create(workspace=workspace, project=project, member=editor, role=20)
    session_client.force_authenticate(user=editor)
    for endpoint, record_id in records:
        detail = session_client.get(base + f"{endpoint}/{record_id}/")
        assert detail.status_code == 200, detail.content
        assert detail.data["created_by_id"] == str(create_user.id)
        assert detail.data["created_by_name"] == "创建同事"
        listing = session_client.get(base + endpoint + "/")
        assert listing.status_code == 200, listing.content
        rows = listing.data if isinstance(listing.data, list) else listing.data["results"]
        row = next(item for item in rows if str(item["id"]) == str(record_id))
        assert row["created_by_id"] == str(create_user.id)
        assert row["created_by_name"] == "创建同事"


def test_startup_incident_retains_daq_authorship_without_a_session(workspace, create_user):
    from plane.quality.models import Defect, SourceLink
    from plane.quality.serializers import DefectSerializer

    defect = Defect.objects.create(
        project=Project.objects.create(workspace=workspace, name="启动事件", identifier="STARTAUTHOR"),
        created_by=create_user,
        title="启动失败",
    )
    SourceLink.objects.create(
        project=defect.project,
        defect=defect,
        source_system="ENGRAM_DAQ",
        source_instance="test",
        record_type="daq_incident",
        record_id="startup-event-1",
    )
    assert DefectSerializer(defect).data["source_kind"] == "daq"


@pytest.mark.parametrize("signature_key", ["incidentSignature", "incidentSessionSignature"])
def test_incident_event_displays_message_instead_of_signature_metadata(workspace, create_user, signature_key):
    import json
    from plane.quality.models import Defect, DefectEvent
    from plane.quality.serializers import EventSerializer

    project = Project.objects.create(workspace=workspace, name="启动事件展示", identifier="STARTNOTE")
    defect = Defect.objects.create(project=project, created_by=create_user, title="启动失败")
    event = DefectEvent.objects.create(
        project=project,
        defect=defect,
        status="open",
        note=json.dumps(
            {
                "message": "DAQ启动异常上报",
                signature_key: "test-fixture-signature",
            }
        ),
    )
    assert EventSerializer(event).data["note"] == "DAQ启动异常上报"
