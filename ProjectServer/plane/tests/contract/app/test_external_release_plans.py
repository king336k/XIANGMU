"""External plans are immutable import snapshots, not local deployment confirmations."""
from uuid import uuid4
import pytest
from plane.db.models import Project,ProjectMember
from plane.quality.models import PlatformProject,PlatformIdentity,Release

pytestmark=[pytest.mark.contract,pytest.mark.django_db]
@pytest.fixture
def external_plan_case(workspace,create_user):
    project=Project.objects.create(workspace=workspace,name="外部计划",identifier="EXT152")
    ProjectMember.objects.create(project=project,member=create_user,role=20)
    PlatformProject.objects.create(project=project,source_instance="old-hub",external_project_id=9)
    PlatformIdentity.objects.create(project=project,source_instance="old-hub",external_user_id=4,user=create_user)
    return f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/",project

def test_preview_confirm_idempotent_and_not_local_admission(session_client,external_plan_case,mocker):
    base,project=external_plan_case
    mocker.patch("plane.quality.platform.configuration",return_value={"kind":"legacy_hub","directory_auth":"bearer"})
    mocker.patch("plane.quality.platform.verify_identity")
    fetch=mocker.patch("plane.quality.platform.fetch",return_value={"total":1,"items":[{"id":2,"project_id":9,"plan_key":"v2","name":"外部发布计划","description":"准备验证","status":"SYNCED","source_url":"https://docs.example.test/plan/2","synced_at":"2026-11-09T10:00:00+08:00"}]})
    data={"source_instance":"old-hub","external_project_id":9,"request_id":str(uuid4())}
    result=session_client.post(base+"external-release-plans/preview/",data,format="json")
    assert result.status_code==201,result.content
    assert result.data["status"]=="preview" and len(result.data["rows"])==1
    assert not Release.objects.filter(project=project).exists()
    done=session_client.post(base+f"external-release-plans/{result.data['id']}/confirm/",{"expected_version":1},format="json")
    assert done.status_code==200 and done.data["status"]=="confirmed",done.content
    assert session_client.post(base+"external-release-plans/preview/",data,format="json").data["id"]==result.data["id"]
    assert fetch.call_count==1
    assert not Release.objects.filter(project=project,status="admitted").exists()

def test_invalid_or_foreign_source_does_not_create_snapshot(session_client,external_plan_case,mocker):
    base,_=external_plan_case
    mocker.patch("plane.quality.platform.configuration",return_value={"kind":"legacy_hub","directory_auth":"bearer"})
    mocker.patch("plane.quality.platform.verify_identity")
    mocker.patch("plane.quality.platform.fetch",return_value={"total":2,"items":[{"id":2,"project_id":999,"plan_key":"v2","name":"错项目"}]})
    response=session_client.post(base+"external-release-plans/preview/",{"source_instance":"old-hub","external_project_id":9,"request_id":str(uuid4())},format="json")
    assert response.status_code==503,response.content
    response=session_client.post(base+"external-release-plans/preview/",{"source_instance":"old-hub","external_project_id":10,"request_id":str(uuid4())},format="json")
    assert response.status_code==404,response.content
