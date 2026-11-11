"""Offline archive boundaries: real filesystem/tar, mock image export only."""
import hashlib,importlib.util,json,tarfile
from pathlib import Path
from unittest.mock import patch
import pytest
ROOT=Path(__file__).parent

def load():
 spec=importlib.util.spec_from_file_location('package_builtin',ROOT/'package_offline.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
@pytest.fixture
def model(tmp_path):
 root=tmp_path/'verified-model';root.mkdir();entries=[]
 for name in ['model.onnx','tokenizer.json']:
  raw=('fixture-'+name).encode();(root/name).write_bytes(raw);entries.append({'name':name,'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
 return root,{'model':'bge-small-zh-v1.5','files':entries}

def test_default_check_creates_no_archive_and_does_not_access_docker(model,tmp_path,capsys):
 m=load();root,manifest=model
 with patch.object(m,'model_manifest',return_value=manifest),patch.object(m,'export_image') as export:
  assert m.main(['--model-dir',str(root)])==0
 export.assert_not_called();assert json.loads(capsys.readouterr().out)['packaged'] is False

def test_archive_contains_only_allowlisted_source_and_verified_models(model,tmp_path):
 m=load();root,manifest=model;(root/'.env').write_text('SECRET_NOT_ALLOWED');(root/'private.txt').write_text('PRIVATE_NOT_ALLOWED');out=tmp_path/'offline.tar.gz'
 with patch.object(m,'model_manifest',return_value=manifest):assert m.main(['--model-dir',str(root),'--output',str(out)])==0
 with tarfile.open(out,'r:gz') as archive:
  names=archive.getnames();assert not any('.env' in n or 'private' in n for n in names)
  assert 'embedding-dependencies/models/model.onnx' in names
  checks=json.load(archive.extractfile('embedding-dependencies/bundle-manifest.json'))
  for name,meta in checks['files'].items():assert hashlib.sha256(archive.extractfile('embedding-dependencies/'+name).read()).hexdigest()==meta['sha256']

def test_existing_output_and_bad_model_are_never_overwritten(model,tmp_path):
 m=load();root,manifest=model;out=tmp_path/'existing.tar.gz';out.write_bytes(b'user archive')
 with patch.object(m,'model_manifest',return_value=manifest):assert m.main(['--model-dir',str(root),'--output',str(out)])==1
 assert out.read_bytes()==b'user archive';out2=tmp_path/'new.tar.gz';(root/'model.onnx').write_bytes(b'wrong')
 with patch.object(m,'model_manifest',return_value=manifest):assert m.main(['--model-dir',str(root),'--output',str(out2)])==1
 assert not out2.exists()

def test_symlink_models_are_rejected(model,tmp_path):
 m=load();root,manifest=model;(root/'model.onnx').unlink();(tmp_path/'other').write_bytes(b'fixture-model.onnx');(root/'model.onnx').symlink_to(tmp_path/'other')
 with patch.object(m,'model_manifest',return_value=manifest):assert m.main(['--model-dir',str(root)])==1

def test_image_export_only_with_explicit_package_output(model,tmp_path):
 m=load();root,manifest=model
 with patch.object(m,'model_manifest',return_value=manifest),patch.object(m,'export_image') as export:
  assert m.main(['--model-dir',str(root),'--include-image'])==0
 export.assert_not_called()


def test_export_uses_exact_temporary_tag_not_first_image_tag(tmp_path):
 m=load();from unittest.mock import MagicMock
 c=MagicMock();image=c.images.get.return_value;image.id='sha256:fixture';image.attrs={'Size':12};image.save.return_value=[b'image tar fixture']
 with patch('docker.from_env',return_value=c):receipt=m.export_image('engramproject/embedding:bge-small-zh-v1.5',tmp_path/'image.tar')
 assert image.save.call_args.kwargs['named']==receipt['archive_tag']
 assert receipt['archive_tag'].startswith('engramproject/embedding:offline-export-')


def test_arbitrary_other_image_export_is_rejected_without_docker(tmp_path):
 m=load()
 with patch('docker.from_env') as factory:
  with pytest.raises(ValueError):m.export_image('private-business/api:latest',tmp_path/'image.tar')
 factory.assert_not_called()


def test_image_with_baked_credential_environment_is_not_exported(tmp_path):
 m=load();from unittest.mock import MagicMock
 c=MagicMock();image=c.images.get.return_value;image.attrs={'Config':{'Env':['EMBEDDING_API_KEY=not-allowed-baked-key']}}
 with patch('docker.from_env',return_value=c):
  with pytest.raises(ValueError):m.export_image('engramproject/embedding:unsafe-fixture',tmp_path/'image.tar')
 image.save.assert_not_called();assert not (tmp_path/'image.tar').exists()


def test_dependencies_default_excludes_deployment_source(model,tmp_path):
 m=load();root,manifest=model;out=tmp_path/'deps.tar.gz'
 with patch.object(m,'model_manifest',return_value=manifest):assert m.main(['--model-dir',str(root),'--output',str(out)])==0
 with tarfile.open(out,'r:gz') as archive:
  names=archive.getnames();assert 'embedding-dependencies/models/model.onnx' in names;assert not any('/service/' in n for n in names)

def test_code_package_is_small_independent_and_does_not_read_weights(tmp_path):
 m=load();out=tmp_path/'code.tar.gz'
 with patch.object(m,'export_image') as export:
  assert m.main(['--package-kind','code','--output',str(out)])==0
 export.assert_not_called()
 with tarfile.open(out,'r:gz') as archive:
  names=archive.getnames();assert 'embedding-code/service/setup_platform.py' in names;assert not any('/models/' in n or 'image.tar' in n for n in names)

def test_code_package_cannot_embed_image(tmp_path):
 m=load();out=tmp_path/'bad.tar.gz'
 assert m.main(['--package-kind','code','--include-image','--output',str(out)])==1
 assert not out.exists()
