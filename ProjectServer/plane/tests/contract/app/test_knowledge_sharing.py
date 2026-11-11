"""Sharing grants expose one frozen publication, never project membership or draft access."""
import pytest
from plane.db.models import Project, ProjectMember, User, WorkspaceMember
from plane.knowledge.models import Article, PublishedRevision
from plane.knowledge.retrieval import published

pytestmark=[pytest.mark.contract,pytest.mark.django_db]
@pytest.fixture
def shared_projects(workspace,create_user):
    source=Project.objects.create(workspace=workspace,name="源知识项目",identifier="KBS152")
    target=Project.objects.create(workspace=workspace,name="目标知识项目",identifier="KBT152")
    for project in [source,target]:ProjectMember.objects.create(project=project,member=create_user,role=20)
    article=Article.objects.create(project=source,title="连接处理经验",content="核对监听端口后重新连接。",publication_active=True,status="published",published_version=1,edit_version=3)
    revision=PublishedRevision.objects.create(project=source,article=article,version=1,title=article.title,content=article.content)
    return source,target,article,revision

def base(workspace,source):return f"/api/workspaces/{workspace.slug}/projects/{source.id}/knowledge/"

def test_explicit_share_only_target_and_published_revision(session_client,shared_projects,workspace):
    source,target,article,revision=shared_projects
    assert not published(target).exists()
    result=session_client.post(base(workspace,source)+f"articles/{article.id}/shares/",{"target_project_id":str(target.id),"expected_version":3,"reason":"通用连接经验","device_scope":"采集工作站","version_scope":"v2"},format="json")
    assert result.status_code==201,result.content
    assert published(target).get().id==revision.id
    search=session_client.get(base(workspace,target)+"search/?q=连接")
    assert search.status_code==200 and search.data["count"]==1,search.content
    assert search.data["results"][0]["reference"]==f"KN-{article.id}-v1"
    # The grant does not expose the source project's editorial endpoint.
    viewer=User.objects.create(username="shared-viewer",email="shared-viewer@local.test")
    WorkspaceMember.objects.create(workspace=workspace,member=viewer,role=15)
    ProjectMember.objects.create(project=target,member=viewer,role=15)
    session_client.force_authenticate(user=viewer)
    assert session_client.get(base(workspace,target)+"search/?q=连接").data["count"]==1
    assert session_client.get(base(workspace,source)+f"articles/{article.id}/").status_code==403

def test_share_requires_source_and_target_manager_and_version(session_client,shared_projects,workspace,create_user):
    source,target,article,revision=shared_projects
    url=base(workspace,source)+f"articles/{article.id}/shares/"
    WorkspaceMember.objects.filter(workspace=workspace,member=create_user).update(role=15)
    ProjectMember.objects.filter(project=target,member=create_user).update(role=15)
    response=session_client.post(url,{"target_project_id":str(target.id),"expected_version":3,"reason":"共享"},format="json")
    assert response.status_code==403,response.content
    ProjectMember.objects.filter(project=target,member=create_user).update(role=20)
    article.publication_active=False;article.save()
    assert session_client.post(url,{"target_project_id":str(target.id),"expected_version":3,"reason":"共享"},format="json").status_code==409

def test_share_withdraw_source_offline_and_new_publication_remove_references(session_client,shared_projects,workspace):
    from plane.knowledge.serializers import visible_references
    source,target,article,revision=shared_projects
    url=base(workspace,source)+f"articles/{article.id}/shares/"
    response=session_client.post(url,{"target_project_id":str(target.id),"expected_version":3,"reason":"共享"},format="json")
    assert response.status_code==201,response.content
    assert f"KN-{article.id}-v1" in visible_references(target.id)
    withdrawn=session_client.post(base(workspace,source)+f"shares/{response.data['id']}/withdraw/",{"expected_version":response.data["version"],"reason":"适用范围调整"},format="json")
    assert withdrawn.status_code==200,withdrawn.content
    assert not published(target).exists()
    response=session_client.post(url,{"target_project_id":str(target.id),"expected_version":3,"expected_share_version":withdrawn.data["version"],"reason":"再次授权"},format="json")
    assert response.status_code in [200,201]
    article.publication_active=False;article.save()
    assert not published(target).exists()
    article.publication_active=True;article.published_version=2;article.save()
    PublishedRevision.objects.create(project=source,article=article,version=2,title="新版本",content="变化")
    assert not published(target).exists()
    assert f"KN-{article.id}-v1" not in visible_references(target.id)

def test_target_list_is_paginated_authorized_and_no_cross_workspace(session_client,shared_projects,workspace,create_user):
    source,target,*_=shared_projects
    result=session_client.get(base(workspace,source)+"share-targets/?per_page=1")
    assert result.status_code==200 and result.data["count"]==1,result.content
    assert result.data["results"][0]["id"]==str(target.id)
    ProjectMember.objects.filter(project=target,member=create_user).update(is_active=False)
    assert session_client.get(base(workspace,source)+"share-targets/").data["count"]==0


def test_shared_knowledge_revocation_hides_model_assessment_as_well_as_answer(session_client,shared_projects,workspace):
    from plane.quality.models import Defect,DiagnosticJob
    from plane.quality.diagnostics import DiagnosticSerializer
    from plane.knowledge.models import ChatMessage,Conversation
    from plane.knowledge.serializers import MessageSerializer
    from uuid import uuid4
    source,target,article,revision=shared_projects
    url=base(workspace,source)+f"articles/{article.id}/shares/"
    grant=session_client.post(url,{"target_project_id":str(target.id),"expected_version":3,"reason":"共享"},format="json")
    assert grant.status_code==201,grant.content
    reference={"reference":f"KN-{article.id}-v1","title":article.title,"content":article.content}
    defect=Defect.objects.create(project=target,title="故障")
    job=DiagnosticJob.objects.create(project=target,defect=defect,request_id=uuid4(),status="completed",result={"method":"hybrid","answer":"历史知识说明","citations":[reference],"model_confidence":0.95,"evidence_assessment":"supported","confidence_basis":"历史共享正文","confidence_references":[reference]})
    conversation=Conversation.objects.create(project=target,title="询问")
    message=ChatMessage.objects.create(project=target,conversation=conversation,request_id=uuid4(),query="连接故障",status="completed",answer="历史共享正文",citations=[reference])
    session_client.post(base(workspace,source)+f"shares/{grant.data['id']}/withdraw/",{"expected_version":grant.data["version"],"reason":"撤销授权"},format="json")
    data=DiagnosticSerializer(job).data["result"]
    assert data.get("confidence_basis","")=="" and data.get("confidence_references",[])==[]
    assert data.get("model_confidence") is None
    assert MessageSerializer(message).data["status"]=="reference_unavailable"


def test_sharing_strict_duties_enforced_after_native_membership(session_client,shared_projects,workspace,create_user):
    from plane.quality.models import BusinessRole,ProjectRolePolicy
    source,target,article,revision=shared_projects
    for project in [source,target]:
        ProjectRolePolicy.objects.create(project=project,enabled=True)
        BusinessRole.objects.create(project=project,user=create_user,role="PROJECT_MANAGER")
    url=base(workspace,source)+f"articles/{article.id}/shares/"
    data={"target_project_id":str(target.id),"expected_version":3,"reason":"共享"}
    first=session_client.post(url,data,format="json")
    assert first.status_code==201,first.content
    retry=session_client.post(url,data,format="json")
    assert retry.status_code==200 and retry.data["id"]==first.data["id"] and retry.data["version"]==first.data["version"]
    BusinessRole.objects.filter(project=source,user=create_user).update(role="REPORTER")
    ProjectMember.objects.filter(project=source,member=create_user).update(role=15)
    WorkspaceMember.objects.filter(workspace=workspace,member=create_user).update(role=15)
    denied=session_client.post(base(workspace,source)+f"shares/{first.data['id']}/withdraw/",{"expected_version":1,"reason":"无权限"},format="json")
    assert denied.status_code==403,denied.content


def test_old_grant_retry_cannot_reactivate_a_withdrawn_share(session_client,shared_projects,workspace):
    source,target,article,_=shared_projects
    url=base(workspace,source)+f"articles/{article.id}/shares/"
    data={"target_project_id":str(target.id),"expected_version":3,"reason":"共享"}
    grant=session_client.post(url,data,format="json")
    assert grant.status_code==201,grant.content
    withdrawn=session_client.post(base(workspace,source)+f"shares/{grant.data['id']}/withdraw/",{"expected_version":grant.data["version"],"reason":"撤回"},format="json")
    assert withdrawn.status_code==200
    retry=session_client.post(url,data,format="json")
    assert retry.status_code==409,retry.content
    assert not published(target).exists()
    explicit=session_client.post(url,{**data,"expected_share_version":withdrawn.data["version"]},format="json")
    assert explicit.status_code==200,explicit.content
