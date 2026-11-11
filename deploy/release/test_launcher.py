import importlib.util
import json
from pathlib import Path
import pytest
spec=importlib.util.spec_from_file_location('release_launcher',Path(__file__).with_name('launcher.py'))
mod=importlib.util.module_from_spec(spec)
if Path(spec.origin).exists():spec.loader.exec_module(mod)

@pytest.fixture
def deploy(tmp_path):
    root=tmp_path/'deployment';release=root/'releases/v1';(release/'deploy/release').mkdir(parents=True);(root/'shared').mkdir();(release/'deploy/release/compose.yml').write_text('services: {}');(root/'current').symlink_to('releases/v1');(root/'shared/.env').write_text('HTTP_PORT=18890\nBUILTIN_EMBEDDING_KEY=present\nDOCUMENT_OCR_KEY=present\n');(root/'shared/.env').chmod(0o600);(root/'shared/deployment.json').write_text(json.dumps({'schema_version':1,'deploy_root':str(root),'project_name':'isolated-test','profiles':['helpers']}));return root

def test_start_uses_persisted_profiles_and_no_build_pull(deploy,monkeypatch):
    calls=[];monkeypatch.setattr(mod,'execute',lambda root,release,record,action,since:calls.append((record,action)))
    assert mod.main(['--deploy-root',str(deploy),'start'])==0
    assert calls[0][0]['profiles']==['helpers'] and calls[0][1]=='start'

@pytest.mark.parametrize('action',['status','stop','logs'])
def test_all_actions_use_same_record_and_no_env_output(deploy,monkeypatch,action,capsys):
    monkeypatch.setattr(mod,'execute',lambda *a:None)
    assert mod.main(['--deploy-root',str(deploy),action])==0
    assert 'BUILTIN_EMBEDDING_KEY' not in capsys.readouterr().out

def test_escape_pointer_or_world_readable_env_refused(deploy,monkeypatch):
    monkeypatch.setattr(mod,'execute',lambda *a:pytest.fail('must refuse'))
    (deploy/'shared/.env').chmod(0o644)
    assert mod.main(['--deploy-root',str(deploy),'start'])==1
    (deploy/'shared/.env').chmod(0o600);(deploy/'current').unlink();(deploy/'current').symlink_to(deploy.parent)
    assert mod.main(['--deploy-root',str(deploy),'start'])==1

def test_logs_command_only_exports_owned_container_streams(deploy,monkeypatch):
    calls=[];rows=[{'Id':'owned','Config':{'Labels':{'com.docker.compose.service':'api'}}}]
    monkeypatch.setattr(mod.runtime,'owned_containers',lambda *a:rows)
    monkeypatch.setattr(mod.runtime,'export_logs',lambda *a:calls.append(a))
    mod.execute(deploy,deploy/'releases/v1',{'project_name':'isolated-test','profiles':['helpers']},'logs','2h')
    assert calls[0][-1]=='2h' and calls[0][2]==rows
