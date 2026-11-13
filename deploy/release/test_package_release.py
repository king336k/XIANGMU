"""Packaging contracts use real files/tars and mocked Docker export only."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tarfile
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parent


def load():
    spec = importlib.util.spec_from_file_location('release_package', ROOT / 'package_release.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def source(tmp_path):
    root = tmp_path / 'source'
    files = [
        'ProjectServer/manage.py', 'ProjectServer/plane/__init__.py', 'ProjectServer/bin/docker-entrypoint-api.sh',
        'ProjectFront/build/client/index.html', 'services/collaboration/dist/start.mjs',
        'services/diagnostic-agent/runner.py', 'deploy/release/compose.yml', 'deploy/release/install.py',
        'deploy/release/launcher.py', 'deploy/release/frp_control.py', 'deploy/release/Caddyfile', 'deploy/release/nginx.web.conf', 'deploy/release/部署说明.md',
        'README.md', 'LICENSE.txt', 'start.sh', 'stop.sh', 'deploy/local/.env.example',
        'deploy/network/frp-bridge/bridge.py', 'deploy/network/frp-bridge/templates/frpc.toml.example',
    ]
    for name in files:
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('fixture ' + name)
    manifest = {'schema_version': 1, 'project_key': 'engram_project', 'runtime_set_version': '165',
                'platform': 'linux/amd64', 'images': [
                    {'service': 'api', 'ref': 'example/api-runtime:165', 'id': 'sha256:' + 'a' * 64,
                     'platform': 'linux/amd64', 'dependency_sha256': 'b' * 64},
                    {'service': 'worker', 'ref': 'example/api-runtime:165', 'id': 'sha256:' + 'a' * 64,
                     'platform': 'linux/amd64', 'dependency_sha256': 'b' * 64}]}
    (root / 'deploy/release/runtime-manifest.json').write_text(json.dumps(manifest))
    return root, manifest


def archive(out, kind):
    return next(out.rglob('*_' + kind + '_*.tar.gz'))


def members(path):
    with tarfile.open(path) as tar:
        return {x.name: tar.extractfile(x).read() for x in tar if x.isfile()}


def test_code_no_head_hashes_secrets_and_no_docker(source, tmp_path, monkeypatch):
    m = load(); root, manifest = source; out = tmp_path / 'out'
    for name in ['ProjectServer/plane/.env', 'ProjectServer/plane/private.pem', 'ProjectServer/plane/logs/error.log',
                 'ProjectServer/plane/__pycache__/x.pyc', 'ProjectServer/plane/data/users.sqlite',
                 'ProjectFront/build/client/.env.local']:
        p = root / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text('private test canary')
    monkeypatch.setattr(m, 'run_command', lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('No Docker/build for code')))
    assert m.main(['--artifact', 'code', '--project-root', str(root), '--output', str(out), '--version', 'test165']) == 0
    content = members(archive(out, 'code')); prefix = 'EngramProject_code_test165/'
    info = json.loads(content[prefix + 'version_info.json'])
    assert info['git']['head'] is None and info['git']['available'] is False
    assert len(info['source_tree_sha256']) == 64
    assert info['runtime_manifest_sha256'] == hashlib.sha256((root / 'deploy/release/runtime-manifest.json').read_bytes()).hexdigest()
    assert all(b'private test canary' not in raw for raw in content.values())
    checks = content[prefix + 'SHA256SUMS'].decode().splitlines()
    for line in checks:
        digest, name = line.split('  ', 1)
        assert hashlib.sha256(content[prefix + name]).hexdigest() == digest
    assert prefix + 'ProjectFront/build/client/index.html' in content


def test_missing_build_and_unsafe_version_fail_without_artifacts(source, tmp_path):
    m = load(); root, _ = source; out = tmp_path / 'out'
    (root / 'ProjectFront/build/client/index.html').unlink()
    assert m.main(['--artifact', 'code', '--project-root', str(root), '--output', str(out)]) == 1
    assert not list(out.rglob('*.tar.gz'))
    assert m.main(['--artifact', 'code', '--project-root', str(root), '--output', str(out), '--version', '../bad']) == 1


def test_symlink_refused_and_existing_archive_never_overwritten(source, tmp_path):
    m = load(); root, _ = source; out = tmp_path / 'out'
    p = root / 'ProjectServer/plane/escape.py'; p.symlink_to('/etc/passwd')
    args = ['--artifact', 'code', '--project-root', str(root), '--output', str(out), '--version', 'fixed']
    assert m.main(args) == 1
    p.unlink(); assert m.main(args) == 0
    before = archive(out, 'code').read_bytes()
    assert m.main(args) == 1 and archive(out, 'code').read_bytes() == before


def test_images_once_dedup_and_include_verified_models(source, tmp_path, monkeypatch):
    m = load(); root, manifest = source; model = tmp_path / 'model'; model.mkdir()
    entries = []
    for name in ['model.onnx', 'tokenizer.json']:
        raw = ('test ' + name).encode(); (model / name).write_bytes(raw)
        entries.append({'name': name, 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
    model_manifest = root / 'services/embedding-service/model-manifest.json'; model_manifest.parent.mkdir(parents=True, exist_ok=True)
    model_manifest.write_text(json.dumps({'model': 'bge-small-zh-v1.5', 'files': entries}))
    calls = []
    def command(args, **kwargs):
        calls.append(args)
        if args[:3] == ['docker', 'image', 'inspect']:
            return SimpleNamespace(returncode=0, stdout=json.dumps([{'Id': 'sha256:' + 'a' * 64, 'Os': 'linux', 'Architecture': 'amd64', 'RepoTags': ['example/api-runtime:165']}]), stderr='')
        assert args[:2] == ['docker', 'save']
        Path(args[args.index('-o') + 1]).write_bytes(b'explicit fake docker archive')
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(m, 'run_command', command)
    out = tmp_path / 'out'
    assert m.main(['--artifact', 'images', '--project-root', str(root), '--output', str(out), '--model-dir', str(model)]) == 0
    saves = [x for x in calls if x[:2] == ['docker', 'save']]
    assert len(saves) == 1 and saves[0].count('example/api-runtime:165') == 1
    content = members(archive(out, 'images'))
    assert sum(x.endswith('/images.tar') for x in content) == 1
    assert any('/models/bge-small-zh-v1.5/model.onnx' in x for x in content)
    loader = next(raw for name, raw in content.items() if name.endswith('/load_images.sh'))
    assert b'image rm' not in loader and b'docker load' in loader


def test_wrong_image_id_or_model_hash_rejected(source, tmp_path, monkeypatch):
    m = load(); root, _ = source
    monkeypatch.setattr(m, 'run_command', lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout='[{"Id":"sha256:bad","Os":"linux","Architecture":"amd64"}]', stderr=''))
    assert m.main(['--artifact', 'images', '--project-root', str(root), '--output', str(tmp_path / 'out'), '--model-dir', str(tmp_path)]) == 1
    assert not list((tmp_path / 'out').rglob('*.tar.gz'))


def test_all_three_archives_frp_official_hash_and_no_autostart(source, tmp_path, monkeypatch):
    m = load(); root, _ = source; bins = tmp_path / 'frp' / 'bin'; bins.mkdir(parents=True)
    pinned = {}
    for name in ['frpc', 'frps']:
        raw = b'explicit fake binary ' + name.encode(); (bins / name).write_bytes(raw); pinned[name] = hashlib.sha256(raw).hexdigest()
    (bins.parent / 'FRP-LICENSE').write_text('license fixture')
    monkeypatch.setattr(m, 'FRP_BINARY_SHA256', pinned)
    monkeypatch.setattr(m, 'FRP_LICENSE_SHA256', hashlib.sha256(b'license fixture').hexdigest())
    # Exercise three orchestrated outputs, real tars; image implementation covered independently.
    def fake_images(stage, root, manifest, model):
        (stage / 'images.tar').write_bytes(b'fake images')
        (stage / 'image-manifest.json').write_text(json.dumps(manifest))
    monkeypatch.setattr(m, 'stage_images', fake_images)
    out = tmp_path / 'out'
    assert m.main(['--artifact', 'all', '--project-root', str(root), '--output', str(out), '--version', 'all165', '--frp-bin-dir', str(bins)]) == 0
    assert len(list(out.rglob('*.tar.gz'))) == 3
    frp = next((out / 'optional/frp').glob('*.tar.gz')); content = members(frp)
    info = json.loads(next(raw for name, raw in content.items() if name.endswith('/version_info.json')))
    assert info['autostart'] is False
    assert any(name.endswith('/bin/frpc') for name in content)
    assert not any(name.endswith('images.tar') for name in members(archive(out, 'code')))
    assert m.main(['--artifact', 'frp', '--project-root', str(root), '--output', str(tmp_path / 'bad'), '--frp-bin-dir', str(tmp_path)]) == 1


def test_parent_symlink_and_optional_output_symlink_refused(source, tmp_path, monkeypatch):
    m = load(); root, _ = source
    moved = root / 'ProjectServer'; outside = tmp_path / 'outside'; moved.rename(outside); moved.symlink_to(outside)
    assert m.main(['--artifact', 'code', '--project-root', str(root), '--output', str(tmp_path / 'out')]) == 1


def test_runtime_override_release_id_and_auto_version_are_consistent(source, tmp_path):
    m = load(); root, manifest = source; override = tmp_path / 'runtime.json'
    manifest['runtime_set_version'] = 'override165'; override.write_text(json.dumps(manifest))
    (root / 'deploy/release/runtime-manifest.json').unlink()
    out = tmp_path / 'out'
    assert m.main(['--artifact', 'code', '--project-root', str(root), '--runtime-manifest', str(override), '--output', str(out)]) == 0
    content = members(archive(out, 'code')); name = next(k for k in content if k.endswith('/version_info.json'))
    info = json.loads(content[name]); assert info['release_id'] == info['version']
    assert info['runtime_set_version'] == 'override165'
    assert json.loads(next(raw for k, raw in content.items() if k.endswith('/runtime-manifest.json'))) == manifest


def test_corrupt_model_is_rejected_even_with_valid_images(source, tmp_path, monkeypatch):
    m = load(); root, _ = source; model = tmp_path / 'weights'; model.mkdir()
    (model / 'model.onnx').write_bytes(b'corrupt'); (model / 'tokenizer.json').write_bytes(b'corrupt')
    path = root / 'services/embedding-service/model-manifest.json'; path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'model': 'bge-small-zh-v1.5', 'files': [{'name': n, 'size': 7, 'sha256': '0' * 64} for n in ['model.onnx', 'tokenizer.json']]}))
    monkeypatch.setattr(m, 'run_command', lambda *a, **kw: SimpleNamespace(returncode=0, stdout=json.dumps([{'Id': 'sha256:' + 'a' * 64, 'Os': 'linux', 'Architecture': 'amd64'}]), stderr=''))
    out = tmp_path / 'out'
    assert m.main(['--artifact', 'images', '--verify-only', '--project-root', str(root), '--output', str(out), '--model-dir', str(model)]) == 1
    assert not list(out.rglob('*.tar.gz'))


def test_explicit_build_runs_only_pnpm_and_is_rejected_for_images(source, tmp_path, monkeypatch):
    m = load(); root, _ = source; calls = []
    monkeypatch.setattr(m, 'run_command', lambda args, **kw: (calls.append((args, kw)) or SimpleNamespace(returncode=0, stdout='', stderr='')))
    assert m.main(['--artifact', 'code', '--build', '--project-root', str(root), '--output', str(tmp_path / 'out')]) == 0
    assert [x[0] for x in calls] == [['pnpm', 'install', '--frozen-lockfile'], ['pnpm', 'build:platform']]
    assert all(x[1]['cwd'] == root for x in calls)
    assert m.main(['--artifact', 'images', '--build', '--project-root', str(root), '--output', str(tmp_path / 'bad')]) == 1


def test_changed_runtime_dependency_refuses_code_package(source, tmp_path):
    m = load(); root, manifest = source
    dep = root / 'services/diagnostic-agent/requirements.txt'; dep.write_text('before')
    digest = hashlib.sha256(b'services/diagnostic-agent/requirements.txt\0before\0').hexdigest()
    for item in manifest['images']:
        item['dependency_files'] = ['services/diagnostic-agent/requirements.txt']; item['dependency_sha256'] = digest
    (root / 'deploy/release/runtime-manifest.json').write_text(json.dumps(manifest))
    dep.write_text('changed dependency')
    assert m.main(['--artifact', 'code', '--project-root', str(root), '--output', str(tmp_path / 'bad')]) == 1
    dep.write_text('before')
    assert m.main(['--artifact', 'code', '--project-root', str(root), '--output', str(tmp_path / 'good')]) == 0


def test_image_loader_copies_models_without_overwrite_or_docker_cleanup(source, tmp_path):
    import os
    import subprocess
    m = load(); root, manifest = source; stage = tmp_path / 'image-package'; stage.mkdir()
    (stage / 'images.tar').write_bytes(b'fake docker archive'); (stage / 'image-manifest.json').write_text(json.dumps(manifest))
    models = stage / 'models/bge-small-zh-v1.5'; models.mkdir(parents=True); entries = []
    for name in ['model.onnx', 'tokenizer.json']:
        raw = ('fixture ' + name).encode(); (models / name).write_bytes(raw); entries.append({'name': name, 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
    (models / 'model-manifest.json').write_text(json.dumps({'model': 'bge-small-zh-v1.5', 'files': entries}))
    script = stage / 'load_images.sh'; script.write_text(m.LOADER); m.checksums(stage)
    tools = tmp_path / 'tools'; tools.mkdir(); docker = tools / 'docker'
    docker.write_text('#!/usr/bin/env python3\nimport sys,json\nif sys.argv[1]=="load":sys.exit(0)\nassert sys.argv[1:3]==["image","inspect"]\nprint(json.dumps([{ "Id":"sha256:' + 'a' * 64 + '","Os":"linux","Architecture":"amd64"}]))\n')
    docker.chmod(0o755); env = {**os.environ, 'PATH': str(tools) + ':' + os.environ['PATH']}; deploy = tmp_path / 'installed'
    command = ['bash', str(script), '--deploy-root', str(deploy)]
    assert subprocess.run(command, env=env, capture_output=True).returncode == 0
    target = deploy / 'shared/models/bge-small-zh-v1.5/model.onnx'
    assert target.read_bytes() == (models / 'model.onnx').read_bytes()
    assert subprocess.run(command, env=env, capture_output=True).returncode == 0
    target.write_bytes(b'existing user file')
    assert subprocess.run(command, env=env, capture_output=True).returncode != 0
    assert target.read_bytes() == b'existing user file'


def test_frp_archive_does_not_include_operator_active_toml(source, tmp_path, monkeypatch):
    m = load(); root, _ = source; bins = tmp_path / 'frp/bin'; bins.mkdir(parents=True); pins = {}
    for name in ['frpc', 'frps']:
        raw = name.encode(); (bins / name).write_bytes(raw); pins[name] = hashlib.sha256(raw).hexdigest()
    (bins.parent / 'FRP-LICENSE').write_text('license'); monkeypatch.setattr(m, 'FRP_BINARY_SHA256', pins); monkeypatch.setattr(m, 'FRP_LICENSE_SHA256', hashlib.sha256(b'license').hexdigest())
    (root / 'deploy/network/frp-bridge/frps.toml').write_text('private-canary-current-config')
    out = tmp_path / 'out'
    assert m.main(['--artifact', 'frp', '--project-root', str(root), '--output', str(out), '--frp-bin-dir', str(bins)]) == 0
    assert all(b'private-canary-current-config' not in value for value in members(archive(out, 'frp')).values())


def test_initial_knowledge_baseline_ships_with_code_but_not_private_env(source, tmp_path):
    m = load(); root, _ = source
    seed = root / 'deploy/release/initial-knowledge'; seed.mkdir()
    (seed / 'manifest.json').write_text('{"version":"seed1","missing_attachment":true}')
    (seed / 'knowledge.json').write_text('{"articles":[{"title":"sanitized public baseline"}]}')
    (seed / '.env').write_text('PRIVATE_SEED_CANARY')
    (root / 'deploy/release/seed_knowledge.py').write_text('# guarded seed import')
    out = tmp_path / 'out'
    assert m.main(['--artifact', 'code', '--project-root', str(root), '--output', str(out)]) == 0
    content = members(archive(out, 'code'))
    assert any(name.endswith('/deploy/release/initial-knowledge/manifest.json') for name in content)
    assert any(name.endswith('/deploy/release/initial-knowledge/knowledge.json') for name in content)
    assert any(name.endswith('/deploy/release/seed_knowledge.py') for name in content)
    assert all(b'PRIVATE_SEED_CANARY' not in value for value in content.values())


def test_output_inside_selected_source_tree_is_refused(source):
    m = load(); root, _ = source
    assert m.main(['--artifact', 'code', '--project-root', str(root), '--output', str(root / 'ProjectServer/plane/output')]) == 1
    assert not list((root / 'ProjectServer/plane/output').rglob('*.tar.gz'))


def test_production_code_excludes_test_fixtures_but_keeps_runtime_modules(source, tmp_path):
    m = load(); root, _ = source
    fixture = root / 'ProjectServer/plane/tests/contract/private_fixture.py'
    fixture.parent.mkdir(parents=True)
    fixture.write_text('PRODUCTION_PACKAGE_TEST_CANARY')
    fixture.with_name('escape.py').symlink_to('/etc/passwd')
    runtime_paths = ['ProjectServer/plane/quality/test_resources.py',
                     'ProjectServer/plane/quality/migrations/0001_initial.py']
    for name in runtime_paths:
        path = root / name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('# required runtime module')
    out = tmp_path / 'out'
    assert m.main(['--artifact', 'code', '--project-root', str(root), '--output', str(out)]) == 0
    content = members(archive(out, 'code'))
    assert not any('/ProjectServer/plane/tests/' in name for name in content)
    assert all(b'PRODUCTION_PACKAGE_TEST_CANARY' not in raw for raw in content.values())
    for name in runtime_paths:
        assert any(member.endswith('/' + name) for member in content)


def test_readme_link_documents_are_exactly_whitelisted_for_package_and_install(source, tmp_path):
    m=load();root,_=source
    docs=['AGENTS.md','ProjectServer/tests/RUNNING_TESTS.md','deploy/network/frp-bridge/README.md',
          'docs/design/agent-diagnosis/本轮实施记录.md','docs/design/three-platform/公网与内网部署验证.md',
          'docs/design/three-platform/本轮测试与遗留项.md','docs/legal/COPYRIGHT.txt','docs/legal/THIRD_PARTY_NOTICES.md']
    for name in docs+['docs/private/unlisted.md','ProjectServer/tests/private_fixture.py']:
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('document '+name)
    out=tmp_path/'out'
    assert m.main(['--artifact','code','--project-root',str(root),'--output',str(out)])==0
    content=members(archive(out,'code'))
    install_spec=importlib.util.spec_from_file_location('release_doc_install',ROOT/'install.py')
    installer=importlib.util.module_from_spec(install_spec);install_spec.loader.exec_module(installer)
    for name in docs:
        assert any(member.endswith('/'+name) for member in content),name
        assert installer.allowed(name),name
    for name in ['docs/private/unlisted.md','ProjectServer/tests/private_fixture.py']:
        assert not any(member.endswith('/'+name) for member in content)
        assert not installer.allowed(name)
