"""Initial knowledge is explicit, idempotent, never overwrites user state or publishes history."""
from copy import deepcopy
import pytest
from plane.knowledge.initial_seed import validate_bundle, import_seed
from plane.db.models import Project,ProjectMember
from plane.license.models import Instance,InstanceAdmin
from plane.knowledge.models import Article,PublishedRevision
from django.utils import timezone

pytestmark=[pytest.mark.contract,pytest.mark.django_db]

@pytest.fixture
def seeded_bundle():
 from plane.knowledge.initial_seed import record_revision
 record={'source_key':'legacy-db:1','title':'历史隔离样本','content':'历史资料，请复核后使用。','tags':['历史样本','待复核'],'provenance':{'database':'legacy-db','source_id':'1','classification':'test_fixture'},'source_versions':[{'version':1,'title':'历史1','content':'历史内容未在新平台发布'}]};record['source_revision']=record_revision(record)
 return {'schema':'engramproject-initial-knowledge-v1','seed_version':'test-v1','records':[record],'missing_attachments':[{'size':184,'sha256':'3cb78ecea3331adedd61507176cc634a26e6e9316002352fbf02725643732c17','status':'source_missing'}]}
@pytest.fixture
def seed_target(workspace,create_user):
 instance=Instance.objects.create(instance_name='seed-test',instance_id='seed-test',current_version='test',last_checked_at=timezone.now(),is_setup_done=True)
 InstanceAdmin.objects.create(instance=instance,user=create_user,role=20)
 project=Project.objects.create(workspace=workspace,name='仅管理员初始知识复核',identifier='SEED165',network=0);ProjectMember.objects.create(project=project,member=create_user,role=20);return project,create_user

def test_validate_rejects_unknown_and_secret_fields(seeded_bundle):
 assert validate_bundle(seeded_bundle)['records']==1
 bad=deepcopy(seeded_bundle);bad['records'][0]['password']='not-allowed'
 with pytest.raises(ValueError):validate_bundle(bad)

def test_seed_retry_preserves_history_and_never_publishes(seeded_bundle,seed_target):
 project,actor=seed_target;first=import_seed(seeded_bundle,project,actor);again=import_seed(seeded_bundle,project,actor)
 assert first['created']==1 and first['versions_created']==1 and again['status']=='already_initialized' and again['created']==0
 article=Article.objects.get();assert article.status=='draft' and not article.publication_active
 assert PublishedRevision.objects.count()==1

def test_edited_published_and_withdrawn_records_are_skipped_not_replaced(seeded_bundle,seed_target):
 project,actor=seed_target;import_seed(seeded_bundle,project,actor);article=Article.objects.get();article.content='管理员人工修改';article.status='offline';article.edit_version+=1;article.save()
 report=import_seed(seeded_bundle,project,actor);article.refresh_from_db();assert report['status']=='already_initialized' and report['created']==0 and article.content=='管理员人工修改' and article.status=='offline'

def test_new_source_revision_never_changes_initialized_database(seeded_bundle,seed_target):
 from plane.knowledge.initial_seed import record_revision
 project,actor=seed_target;import_seed(seeded_bundle,project,actor);changed=deepcopy(seeded_bundle);changed['seed_version']='test-v2';changed['records'][0]['content']='新来源修订等待复核';changed['records'][0]['source_revision']=record_revision(changed['records'][0]);report=import_seed(changed,project,actor)
 assert report['created']==0 and report['status']=='already_initialized' and Article.objects.count()==1 and not Article.objects.filter(publication_active=True).exists()

def test_unauthorized_actor_or_public_target_rejected(seeded_bundle,seed_target):
 project,actor=seed_target;InstanceAdmin.objects.filter(user=actor).delete()
 with pytest.raises(ValueError):import_seed(seeded_bundle,project,actor)
 assert Article.objects.count()==0


def test_packaged_real_seed_has_eleven_drafts_eight_histories_and_passes_scan():
    import json
    from pathlib import Path
    from plane.knowledge.retrieval import scan_content,scan_article
    source=Path('/seed/knowledge-bundle.json')
    if not source.exists():source=Path(__file__).resolve().parents[5]/'deploy/release/initial-knowledge/knowledge-bundle.json'
    bundle=json.loads(source.read_text());report=validate_bundle(bundle)
    assert report['records']==11 and report['history_versions']==8 and report['missing_attachments']==1
    assert not scan_content(json.dumps(bundle,ensure_ascii=False))
    for row in bundle['records']:
        assert '不是现场设备手册' in row['content']
        assert not scan_article(row['title'],row['content'],row['tags'])
        for version in row['source_versions']:
            assert not scan_article(version['title'],version['content'],[])
    assert bundle['missing_attachments'][0]['size']==184


def test_missing_target_no_import_permission_and_no_implicit_shared_project(seeded_bundle,seed_target,workspace):
    project,actor=seed_target
    project.network=2;project.save()
    with pytest.raises(ValueError):import_seed(seeded_bundle,project,actor)
    assert Article.objects.count()==0


def test_sensitive_text_is_rejected_during_pure_check(seeded_bundle):
    from plane.knowledge.initial_seed import record_revision
    bad=deepcopy(seeded_bundle);bad['records'][0]['content']='password=synthetic-private';bad['records'][0]['source_revision']=record_revision(bad['records'][0])
    with pytest.raises(ValueError):validate_bundle(bad)


def test_changed_history_is_skipped_preserving_user_revision(seeded_bundle,seed_target):
    project,actor=seed_target;import_seed(seeded_bundle,project,actor);PublishedRevision.objects.update(content='人工修订历史')
    report=import_seed(seeded_bundle,project,actor)
    assert report['status']=='already_initialized' and report['created']==0 and PublishedRevision.objects.get().content=='人工修订历史'


def test_new_bundle_version_without_source_change_is_not_a_new_draft(seeded_bundle,seed_target):
    from plane.knowledge.initial_seed import record_revision
    project,actor=seed_target;import_seed(seeded_bundle,project,actor);changed=deepcopy(seeded_bundle);changed['seed_version']='test-v2';changed['records'][0]['provenance']['export_sha256']='0'*64;changed['records'][0]['source_revision']=record_revision(changed['records'][0])
    report=import_seed(changed,project,actor)
    assert report['status']=='already_initialized' and report['created']==0 and Article.objects.count()==1


def test_v2_after_first_init_preserves_manual_offline_and_markers(seeded_bundle,seed_target):
    from plane.knowledge.initial_seed import record_revision,INITIALIZED_KEY
    from plane.license.models import InstanceConfiguration
    project,actor=seed_target;import_seed(seeded_bundle,project,actor);article=Article.objects.get();article.content='人工修改不能回退';article.status='offline';article.edit_version=8;article.save()
    changed=deepcopy(seeded_bundle);changed['seed_version']='new-v2';changed['records'][0]['content']='新种子不应进入';changed['records'][0]['source_revision']=record_revision(changed['records'][0])
    result=import_seed(changed,project,actor);article.refresh_from_db()
    assert result['status']=='already_initialized' and result['created']==0 and Article.objects.count()==1
    assert article.content=='人工修改不能回退' and article.status=='offline' and article.edit_version==8
    assert InstanceConfiguration.objects.filter(key=INITIALIZED_KEY).count()==1


def test_already_initialized_does_not_read_new_seed_material(seeded_bundle,seed_target):
    project,actor=seed_target;import_seed(seeded_bundle,project,actor)
    result=import_seed(None,project,actor)
    assert result['status']=='already_initialized' and result['imported']==0 and Article.objects.count()==1
