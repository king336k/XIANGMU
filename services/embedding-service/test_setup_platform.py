"""Default embedding deployment contracts; Docker/Compose/download are mocked, files are real."""
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock,patch
import docker
import pytest

ROOT=Path(__file__).parent

def load():
 spec=importlib.util.spec_from_file_location('setup_builtin',ROOT/'setup_platform.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

@pytest.fixture
def project(tmp_path):
 (tmp_path/'docker-compose.yml').write_text('services: {}\n');(tmp_path/'deploy/local').mkdir(parents=True);(tmp_path/'deploy/local/.env').write_text('PRIVATE_TEST=value\n');return tmp_path

@pytest.fixture
def model(tmp_path):
 root=tmp_path/'weights';root.mkdir();entries=[]
 for name in ['model.onnx','tokenizer.json']:
  raw=(name+' fixture').encode();(root/name).write_bytes(raw);entries.append({'name':name,'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'url':'https://huggingface.co/official/fixed/'+name})
 return root,{'model':'bge-small-zh-v1.5','files':entries}

def client(existing=False):
 c=MagicMock();c.networks.get.return_value.attrs={'Internal':True};c.containers.get.side_effect=None if existing else docker.errors.NotFound('missing');return c

def test_default_check_verifies_files_and_never_runs_compose(project,model,capsys):
 m=load();root,manifest=model;c=client()
 with patch.object(m,'load_manifest',return_value=manifest),patch.object(m.docker,'from_env',return_value=c),patch.object(m.subprocess,'run') as run:
  assert m.main(['--project-root',str(project),'--model-dir',str(root)])==0
 run.assert_not_called();c.networks.create.assert_not_called();assert json.loads(capsys.readouterr().out)['applied'] is False

def test_existing_corrupt_model_is_never_replaced(project,model):
 m=load();root,manifest=model;(root/'model.onnx').write_bytes(b'user data');
 with patch.object(m,'load_manifest',return_value=manifest),patch.object(m,'download_model') as download,patch.object(m.docker,'from_env') as factory:
  assert m.main(['--apply','--download-model','--project-root',str(project),'--model-dir',str(root)])==1
 assert (root/'model.onnx').read_bytes()==b'user data';download.assert_not_called();factory.assert_not_called()

def test_apply_enables_profile_and_builtin_env_without_database_writes(project,model,capsys):
 m=load();root,manifest=model;c=client();run=MagicMock(return_value=SimpleNamespace(returncode=0,stdout='',stderr=''))
 with patch.object(m,'load_manifest',return_value=manifest),patch.object(m.docker,'from_env',return_value=c),patch.object(m.subprocess,'run',run),patch.object(m,'wait_ready',return_value=True):
  assert m.main(['--apply','--project-root',str(project),'--model-dir',str(root),'--project-name','fixture','--api-services','api,worker'])==0
 args=run.call_args_list[-1].args[0];env=run.call_args_list[-1].kwargs['env'];assert '--profile' in args and 'embedding' in args and '--pull' in args and 'never' in args
 assert env['KNOWLEDGE_BUILTIN_EMBEDDING_BASE_URL']=='http://builtin-embedding:18885/v1'
 assert env['KNOWLEDGE_BUILTIN_EMBEDDING_MODEL']=='bge-small-zh-v1.5';assert env['EMBEDDING_API_KEY']==env['KNOWLEDGE_BUILTIN_EMBEDDING_API_KEY'];assert env['EMBEDDING_API_KEY'] not in capsys.readouterr().out
 assert not any('manage.py' in str(x.args) or 'configure_platform' in str(x.args) for x in run.call_args_list)

def test_existing_service_key_is_reused_without_recreate(project,model):
 m=load();root,manifest=model;c=client(True);existing=c.containers.get.return_value;existing.attrs={'Config':{'Env':['EMBEDDING_API_KEY=existing-fixture-key'],'Labels':{'com.docker.compose.project':'fixture','com.docker.compose.service':'builtin-embedding'}},'NetworkSettings':{'Networks':{'fixture_embedding':{'Aliases':['builtin-embedding']}}},'Mounts':[{'Source':str(root.resolve()),'Destination':'/model','RW':False}]};existing.image.id='expected-image';c.images.get.return_value.id='expected-image'
 with patch.object(m,'load_manifest',return_value=manifest),patch.object(m.docker,'from_env',return_value=c),patch.object(m.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='',stderr='')) as run,patch.object(m,'wait_ready',return_value=True):
  assert m.main(['--apply','--project-root',str(project),'--model-dir',str(root),'--project-name','fixture'])==0
 assert run.call_args_list[0].kwargs['env']['EMBEDDING_API_KEY']=='existing-fixture-key';assert '--no-recreate' in run.call_args_list[0].args[0];existing.restart.assert_not_called();existing.remove.assert_not_called()

def test_compose_failure_output_never_echoes_secrets(project,model,capsys):
 m=load();root,manifest=model
 with patch.object(m,'load_manifest',return_value=manifest),patch.object(m.docker,'from_env',return_value=client()),patch.object(m.subprocess,'run',return_value=SimpleNamespace(returncode=1,stdout='SECRET_TEST',stderr='SECRET_TEST')):
  assert m.main(['--apply','--project-root',str(project),'--model-dir',str(root)])==1
 assert 'SECRET_TEST' not in capsys.readouterr().out

class DownloadResponse:
 status_code=200
 headers={}
 def __init__(self,raw):self.raw=raw
 def iter_content(self,n):yield self.raw
 def close(self):pass

def test_atomic_model_download_verifies_sha_and_cleans_partial(tmp_path):
 m=load();raw=b'verified fixture';entry={'name':'model.onnx','size':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'url':'https://huggingface.co/official/fixed/model.onnx'}
 with patch.object(m.requests,'get',return_value=DownloadResponse(raw)):
  m.download_model(tmp_path,entry)
 assert (tmp_path/'model.onnx').read_bytes()==raw;assert not list(tmp_path.glob('*.part'))
 other=tmp_path/'other';other.mkdir();entry['sha256']='0'*64
 with patch.object(m.requests,'get',return_value=DownloadResponse(raw)):
  with pytest.raises(ValueError):m.download_model(other,entry)
 assert not list(other.iterdir())

def test_download_requires_explicit_apply(project,model):
 m=load();root,manifest=model
 with patch.object(m,'load_manifest',return_value=manifest),patch.object(m,'download_model') as down:
  assert m.main(['--download-model','--project-root',str(project),'--model-dir',str(root)])==1
 down.assert_not_called()

def test_offline_verified_cache_does_not_download(project,model):
 m=load();root,manifest=model
 with patch.object(m,'load_manifest',return_value=manifest),patch.object(m,'download_model') as down,patch.object(m.docker,'from_env',return_value=client()):
  assert m.main(['--project-root',str(project),'--model-dir',str(root)])==0
 down.assert_not_called()


def test_existing_noninternal_network_is_not_reused(project,model):
 m=load();root,manifest=model;c=client();c.networks.get.return_value.attrs={'Internal':False}
 with patch.object(m,'load_manifest',return_value=manifest),patch.object(m.docker,'from_env',return_value=c),patch.object(m.subprocess,'run') as run:
  assert m.main(['--apply','--project-root',str(project),'--model-dir',str(root)])==1
 run.assert_not_called()

def test_compose_preserves_external_allowlist_and_does_not_set_mode():
 text=(ROOT/'platform.override.yml').read_text()
 assert '${KNOWLEDGE_EMBEDDING_ALLOWED_HTTP_ORIGINS:-},http://builtin-embedding:18885' in text
 assert 'KNOWLEDGE_EMBEDDING_MODE' not in text and 'KNOWLEDGE_SEMANTIC_ENABLED' not in text

def test_same_name_from_another_project_is_not_taken_over(project,model):
 m=load();root,manifest=model;c=client(True);existing=c.containers.get.return_value;existing.attrs={'Config':{'Env':['EMBEDDING_API_KEY=existing-fixture-key'],'Labels':{'com.docker.compose.project':'other','com.docker.compose.service':'builtin-embedding'}},'NetworkSettings':{'Networks':{'fixture_embedding':{}}},'Mounts':[{'Source':str(root.resolve()),'Destination':'/model','RW':False}]};existing.image.id='image';c.images.get.return_value.id='image';c.networks.get.return_value.attrs={'Internal':True}
 with patch.object(m,'load_manifest',return_value=manifest),patch.object(m.docker,'from_env',return_value=c),patch.object(m.subprocess,'run') as run:
  assert m.main(['--apply','--project-root',str(project),'--model-dir',str(root),'--project-name','fixture'])==1
 run.assert_not_called()


def test_corrupt_second_file_prevents_downloading_missing_first(project,model):
 m=load();root,manifest=model;(root/'model.onnx').unlink();(root/'tokenizer.json').write_bytes(b'other user content')
 with patch.object(m,'load_manifest',return_value=manifest),patch.object(m,'download_model') as download:
  assert m.main(['--apply','--download-model','--project-root',str(project),'--model-dir',str(root)])==1
 download.assert_not_called()


def test_apply_records_nonsecret_resume_configuration(project,model,capsys):
 m=load();root,manifest=model;c=client()
 with patch.object(m,'load_manifest',return_value=manifest),patch.object(m.docker,'from_env',return_value=c),patch.object(m.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='',stderr='')),patch.object(m,'wait_ready',return_value=True):
  assert m.main(['--apply','--project-root',str(project),'--model-dir',str(root),'--project-name','fixture'])==0
 marker=project/'deploy/local/builtin-embedding.json'
 data=json.loads(marker.read_text())
 assert data['version']==1 and data['project_name']=='fixture' and data['model_dir']==str(root.resolve())
 assert data['compose_files']==[str(project/'docker-compose.yml')]
 assert marker.stat().st_mode&0o777==0o600
 assert 'KEY' not in marker.read_text() and 'PRIVATE_TEST' not in marker.read_text()


def test_resume_restores_options_without_download_or_build(project,model,capsys):
 m=load();root,manifest=model;c=client()
 record={'version':1,'project_root':str(project),'project_name':'fixture','compose_files':[str(project/'docker-compose.yml')],'env_file':str(project/'deploy/local/.env'),'network':'fixture_embedding','model_dir':str(root),'image':'fixture-image','api_services':'api,worker'}
 (project/'deploy/local/builtin-embedding.json').write_text(json.dumps(record))
 with patch.object(m,'load_manifest',return_value=manifest),patch.object(m.docker,'from_env',return_value=c),patch.object(m,'download_model') as down,patch.object(m.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='',stderr='')) as run,patch.object(m,'wait_ready',return_value=True):
  assert m.main(['--apply','--resume','--project-root',str(project)])==0
 assert 'fixture' in run.call_args_list[-1].args[0]
 assert run.call_args_list[-1].kwargs['env']['EMBEDDING_MODEL_DIR']==str(root)
 down.assert_not_called()


@pytest.mark.parametrize('mutation',['broken','other_root','extra_secret','symlink'])
def test_invalid_resume_never_falls_back_to_base(project,mutation):
 m=load();marker=project/'deploy/local/builtin-embedding.json'
 data={'version':1,'project_root':str(project),'project_name':'fixture','compose_files':[str(project/'docker-compose.yml')],'env_file':str(project/'deploy/local/.env'),'network':'fixture_embedding','model_dir':str(project),'image':'fixture-image','api_services':'api'}
 if mutation=='other_root':data['project_root']='/different'
 if mutation=='extra_secret':data['EMBEDDING_API_KEY']='fixture-secret'
 marker.write_text('invalid JSON' if mutation=='broken' else json.dumps(data))
 if mutation=='symlink':
  original=project/'other.json';marker.rename(original);marker.symlink_to(original)
 with patch.object(m.docker,'from_env') as factory,patch.object(m.subprocess,'run') as run:
  assert m.main(['--apply','--resume','--project-root',str(project)])==1
 factory.assert_not_called();run.assert_not_called()


def test_resume_preserves_ocr_env_only_from_own_project(project,model):
 m=load();root,manifest=model;c=client()
 data={'version':1,'project_root':str(project),'project_name':'fixture','compose_files':[str(project/'docker-compose.yml')],'env_file':str(project/'deploy/local/.env'),'network':'fixture_embedding','model_dir':str(root),'image':'fixture-image','api_services':'api'}
 (project/'deploy/local/builtin-embedding.json').write_text(json.dumps(data))
 own=SimpleNamespace(attrs={'Config':{'Labels':{'com.docker.compose.project':'fixture','com.docker.compose.service':'api'},'Env':['DOCUMENT_OCR_BASE_URL=http://document-ocr:18886','DOCUMENT_OCR_API_KEY=fixture-ocr-preserved','DOCUMENT_OCR_ALLOWED_HTTP_ORIGINS=http://document-ocr:18886','KNOWLEDGE_EMBEDDING_ALLOWED_HTTP_ORIGINS=http://old-extra:18885','UNRELATED_SECRET=must-not-copy']}})
 c.containers.list.return_value=[own]
 with patch.object(m,'load_manifest',return_value=manifest),patch.object(m.docker,'from_env',return_value=c),patch.object(m.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='',stderr='')) as run,patch.object(m,'wait_ready',return_value=True):
  assert m.main(['--apply','--resume','--project-root',str(project)])==0
 env=run.call_args_list[-1].kwargs['env']
 assert env['DOCUMENT_OCR_API_KEY']=='fixture-ocr-preserved'
 assert env['DOCUMENT_OCR_BASE_URL']=='http://document-ocr:18886'
 assert env['KNOWLEDGE_EMBEDDING_ALLOWED_HTTP_ORIGINS']=='http://old-extra:18885'
 assert 'UNRELATED_SECRET' not in env


def test_start_routes_installed_builtin_through_resume(project,tmp_path):
 import os,shutil,subprocess
 shutil.copy(ROOT.parents[1]/'start.sh',project/'start.sh')
 (project/'services/embedding-service').mkdir(parents=True)
 (project/'services/embedding-service/setup_platform.py').write_text('# placeholder\n')
 (project/'deploy/local/builtin-embedding.json').write_text('{}')
 fake=tmp_path/'fake-bin';fake.mkdir();record=tmp_path/'args'
 for executable in ['python3','docker']:
  tool=fake/executable;tool.write_text('#!/bin/sh\nprintf "%s\\n" "'+executable+'" "$@" > "$TEST_RECORD"\n');tool.chmod(0o755)
 result=subprocess.run(['bash',str(project/'start.sh')],env={**os.environ,'PATH':str(fake)+':'+os.environ['PATH'],'TEST_RECORD':str(record)},capture_output=True)
 assert result.returncode==0
 lines=record.read_text().splitlines()
 assert lines[0]=='python3' and '--resume' in lines and '--apply' in lines and '--start-platform' in lines


def test_saved_start_includes_all_compose_services(project,model):
 m=load();root,manifest=model;c=client()
 data={'version':1,'project_root':str(project),'project_name':'fixture','compose_files':[str(project/'docker-compose.yml')],'env_file':str(project/'deploy/local/.env'),'network':'fixture_embedding','model_dir':str(root),'image':'fixture-image','api_services':'api,worker'}
 (project/'deploy/local/builtin-embedding.json').write_text(json.dumps(data))
 with patch.object(m,'load_manifest',return_value=manifest),patch.object(m.docker,'from_env',return_value=c),patch.object(m.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='',stderr='')) as run,patch.object(m,'wait_ready',return_value=True):
  assert m.main(['--apply','--resume','--start-platform','--project-root',str(project)])==0
 assert run.call_args_list[-1].args[0][-5:]==['up','-d','--no-build','--pull','never']
