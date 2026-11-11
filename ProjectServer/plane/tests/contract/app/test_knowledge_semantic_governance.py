"""Editorial semantic suggestions are version-bound and human decided."""
from uuid import uuid4
import pytest
from plane.db.models import Project, ProjectMember
from plane.knowledge.models import Article, PublishedRevision
from plane.knowledge.semantic_models import SemanticRevisionIndex

pytestmark=[pytest.mark.contract,pytest.mark.django_db]
@pytest.fixture
def governance_pair(workspace,create_user):
    project=Project.objects.create(workspace=workspace,name="知识治理",identifier="GOV152")
    ProjectMember.objects.create(project=project,member=create_user,role=20)
    rows=[]
    for title,content in [("采集连接中断","检查目标服务监听和端口"),("无法连上机器人","核对服务监听端口后重新连接")]:
        article=Article.objects.create(project=project,title=title,content=content,status="published",publication_active=True,published_version=1,edit_version=1)
        revision=PublishedRevision.objects.create(project=project,article=article,version=1,title=title,content=content)
        rows.append((article,revision))
    return f"/api/workspaces/{workspace.slug}/projects/{project.id}/knowledge/",project,rows

def test_semantic_governance_uses_index_current_versions_and_independent_threshold(session_client,governance_pair,mocker):
    from plane.knowledge.semantic import content_hash
    base,project,pairs=governance_pair
    mocker.patch("plane.knowledge.semantic_provider.configuration",return_value={"configured":True,"fingerprint":"fp"})
    for article,revision in pairs:SemanticRevisionIndex.objects.create(project=project,revision=revision,fingerprint="fp",content_hash=content_hash(revision),vectors=[[1.0,0.0]])
    response=session_client.get(base+"governance/?semantic_threshold=0.9")
    assert response.status_code==200,response.content
    candidates=response.data["semantic_candidates"]
    assert len(candidates)==1 and candidates[0]["similarity"]==1.0
    assert "相似度" in candidates[0]["basis"]
    assert candidates[0]["source"]["id"]==str(pairs[0][0].id) or candidates[0]["target"]["id"]==str(pairs[0][0].id)
    pairs[0][0].publication_active=False;pairs[0][0].save()
    assert session_client.get(base+"governance/").data["semantic_candidates"]==[]

def test_ignored_pair_only_hides_frozen_versions(session_client,governance_pair,mocker):
    from plane.knowledge.semantic import content_hash
    base,project,pairs=governance_pair
    mocker.patch("plane.knowledge.semantic_provider.configuration",return_value={"configured":True,"fingerprint":"fp"})
    for article,revision in pairs:SemanticRevisionIndex.objects.create(project=project,revision=revision,fingerprint="fp",content_hash=content_hash(revision),vectors=[[1.0,0.0]])
    a,b=[r[0] for r in pairs]
    result=session_client.post(base+"governance/ignore/",{"source_id":str(a.id),"target_id":str(b.id),"source_version":a.edit_version,"target_version":b.edit_version,"reason":"不同设备场景，各自保留"},format="json")
    assert result.status_code==201,result.content
    assert session_client.get(base+"governance/").data["semantic_candidates"]==[]
    a.edit_version+=1;a.save()
    assert session_client.get(base+"governance/").data["semantic_candidates"]

def test_merge_can_undo_without_republishing_and_rejects_overwriting_later_edit(session_client,governance_pair):
    base,project,pairs=governance_pair
    a,b=[r[0] for r in pairs];original=b.content
    data={"source_id":str(a.id),"target_id":str(b.id),"source_version":1,"target_version":1,"reason":"整理同类排查经验"}
    result=session_client.post(base+"governance/merge/",data,format="json")
    assert result.status_code==200,result.content
    merged=session_client.get(base+"governance/").data["merge_history"][0]
    undo=session_client.post(base+f"governance/merges/{merged['id']}/undo/",{"reason":"保留原文独立维护"},format="json")
    assert undo.status_code==200,undo.content
    a.refresh_from_db();b.refresh_from_db()
    assert a.merged_into_id is None and b.content==original
    assert not a.publication_active and not b.publication_active
    assert a.status==b.status=="draft"
