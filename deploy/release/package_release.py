#!/usr/bin/env python3
"""Produce independent code, fixed-runtime image and optional FRP packages; never deploy."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone

FRP_VERSION = '0.72.0'
FRP_BINARY_SHA256 = {
    'frpc': '522352244a4872beaa0ad6fa136c8cc8d2e993e72bcf49f9c8a1d9683770d80e',
    'frps': '4ad311e0630cf12945041143b926f515458836e896ff93c253d43c98cf304b89',
}
FRP_LICENSE_SHA256 = 'c6596eb7be8581c18be736c846fb9173b69eccf6ef94c5135893ec56bd92ba08'
DEFAULT_FRP = '/home/engram/Documents/tmp/artifacts/project-hub-network-155-2026-11-10/EngramFrpBridge-linux-amd64-0.72.0/bin'
DEFAULT_MODEL = str(Path.home() / 'Documents/tmp/artifacts/embedding-model-cache/bge-small-zh-v1.5')
TREES = ['ProjectServer/plane', 'ProjectServer/templates', 'ProjectServer/bin', 'ProjectFront/build/client', 'services/collaboration/dist', 'deploy/release/initial-knowledge']
FILES = ['ProjectServer/manage.py', 'README.md', 'LICENSE', 'LICENSE.txt', 'start.sh', 'stop.sh',
         'AGENTS.md', 'ProjectServer/tests/RUNNING_TESTS.md', 'deploy/network/frp-bridge/README.md',
         'docs/design/agent-diagnosis/本轮实施记录.md', 'docs/design/three-platform/公网与内网部署验证.md',
         'docs/deployment/5090项目平台部署说明.md',
         'docs/design/three-platform/本轮测试与遗留项.md', 'docs/legal/COPYRIGHT.txt', 'docs/legal/THIRD_PARTY_NOTICES.md',
         'scripts/init_local_config.py', 'deploy/local/.env.example',
         'services/diagnostic-agent/runner.py', 'services/diagnostic-agent/requirements.txt',
         'services/diagnostic-agent/remote_runner.py',
         'services/diagnostic-integrations/holmes_runner.py', 'services/diagnostic-integrations/holmes_service.py',
         'services/document-ocr/server.py', 'services/document-ocr/extractor.py', 'services/document-ocr/README.md',
         'services/embedding-service/app.py', 'services/embedding-service/setup_platform.py',
         'services/embedding-service/model-manifest.json', 'services/embedding-service/platform.override.yml',
         'services/embedding-service/README.md', 'services/embedding-service/requirements.txt',
         'deploy/release/runtime-manifest.json', 'deploy/release/compose.yml', 'deploy/release/install.py',
         'deploy/release/seed_knowledge.py', 'deploy/release/launcher.py', 'deploy/release/frp_control.py', 'deploy/release/Caddyfile', 'deploy/release/nginx.web.conf', 'deploy/release/部署说明.md']
REQUIRED = ['ProjectServer/manage.py', 'ProjectServer/plane/__init__.py', 'ProjectServer/bin/docker-entrypoint-api.sh',
            'ProjectFront/build/client/index.html', 'services/collaboration/dist/start.mjs',
            'deploy/release/runtime-manifest.json', 'deploy/release/compose.yml', 'deploy/release/install.py', 'deploy/release/launcher.py', 'deploy/release/frp_control.py', 'deploy/release/Caddyfile']
EXCLUDED = {'.git', '.ssh', 'node_modules', '__pycache__', '.pytest_cache', '.mypy_cache', '.cache', 'logs',
            'data', 'datasets', 'quality-attachments', 'uploads', 'secrets', 'secret', 'backups', 'collected-static'}


class PackageError(ValueError):
    pass


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(2 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def run_command(args, **kwargs):
    return subprocess.run(args, capture_output=True, text=True, check=False, **kwargs)


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def safe_version(value):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', value) or value in {'.', '..'}:
        raise PackageError('version must be a safe single path component')
    return value


def reject_links(path):
    if any(p.is_symlink() for p in [path, *path.parents]):
        raise PackageError('symlink in selected path')


def regular(path):
    path = Path(path)
    reject_links(path)
    if not path.is_file():
        raise PackageError('required regular file missing or symlink: ' + path.name)
    return path


def excluded(relative):
    if relative == Path('ProjectServer/plane/tests') or Path('ProjectServer/plane/tests') in relative.parents:
        return True
    if any(x in EXCLUDED for x in relative.parts):
        return True
    name = relative.name.lower()
    if (name == '.env' or name.startswith('.env.')) and not name.endswith('.example'):
        return True
    return name.endswith(('.pyc', '.pyo', '.log', '.pem', '.key', '.p12', '.pfx', '.sqlite', '.sqlite3', '.db', '.onnx', '.pt', '.part'))


def collect_tree(root, relative):
    path = root / relative
    reject_links(path)
    if not path.exists() and not path.is_symlink():
        return []
    if path.is_symlink():
        raise PackageError('symlinks are not accepted: ' + relative)
    if path.is_file():
        return [] if excluded(Path(relative)) else [Path(relative)]
    result = []
    for child in sorted(path.iterdir()):
        rel = child.relative_to(root)
        if excluded(rel):
            continue
        if child.is_symlink():
            raise PackageError('symlinks are not accepted: ' + str(rel))
        if child.is_dir():
            result.extend(collect_tree(root, str(rel)))
        elif child.is_file():
            result.append(rel)
        else:
            raise PackageError('special files are not accepted: ' + str(rel))
    return result


def load_manifest(path):
    regular(path)
    value = json.loads(path.read_text())
    if value.get('schema_version') != 1 or value.get('project_key') != 'engram_project':
        raise PackageError('unsupported runtime manifest')
    safe_version(value.get('runtime_set_version', ''))
    if value.get('platform') not in {'linux/amd64', 'linux/arm64'} or not value.get('images'):
        raise PackageError('runtime platform/images missing')
    services = set(); refs = {}
    for image in value['images']:
        if (not isinstance(image, dict) or not re.fullmatch(r'[A-Za-z0-9_-]+', image.get('service', ''))
                or image['service'] in services or image.get('platform') != value['platform']
                or not re.fullmatch(r'sha256:[a-f0-9]{64}', image.get('id', ''))
                or not re.fullmatch(r'[a-f0-9]{64}', image.get('dependency_sha256', ''))
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/@-]{0,499}', image.get('ref', ''))):
            raise PackageError('invalid runtime image entry')
        if image['ref'] in refs and refs[image['ref']] != image['id']:
            raise PackageError('conflicting runtime image identities')
        services.add(image['service']); refs[image['ref']] = image['id']
    return value


def verify_dependencies(root, manifest):
    for image in manifest['images']:
        if 'dependency_files' not in image:
            continue
        files = image['dependency_files']
        if not isinstance(files, list) or len(set(files)) != len(files):
            raise PackageError('invalid dependency file list')
        digest = hashlib.sha256()
        for name in sorted(files):
            rel = Path(name)
            if rel.is_absolute() or '..' in rel.parts or str(rel) != name:
                raise PackageError('unsafe dependency path')
            digest.update(name.encode() + b'\0')
            digest.update(regular(root / rel).read_bytes() + b'\0')
        if digest.hexdigest() != image['dependency_sha256']:
            raise PackageError('runtime dependencies changed; prepare matching runtime images')


def git_metadata(root):
    # A missing/unborn HEAD is valid. Never relabel an arbitrary working tree as a commit.
    def git(*args):
        try:
            p = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, check=False, timeout=30)
            return p.stdout.strip() if p.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            return None
    head = git('rev-parse', '--verify', 'HEAD')
    if not head:
        return {'available': False, 'head': None, 'branch': None, 'dirty': None}
    status = git('status', '--porcelain', '--untracked-files=all')
    return {'available': True, 'head': head, 'branch': git('branch', '--show-current'), 'dirty': bool(status) if status is not None else None}


def stage_code(stage, root, manifest_path):
    paths = set()
    for rel in TREES + FILES:
        paths.update(collect_tree(root, rel))
    # The override manifest is copied to the canonical package location.
    for rel in REQUIRED:
        if rel != 'deploy/release/runtime-manifest.json' and Path(rel) not in paths:
            raise PackageError('required build/entrypoint missing: ' + rel)
    for rel in sorted(paths):
        target = stage / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(regular(root / rel), target)
        target.chmod(0o755 if (root / rel).stat().st_mode & 0o111 else 0o644)
    canonical = stage / 'deploy/release/runtime-manifest.json'
    canonical.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(manifest_path, canonical)
    tree = {str(p.relative_to(stage)): sha(p) for p in sorted(stage.rglob('*')) if p.is_file()}
    digest = hashlib.sha256(json.dumps(tree, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return digest, tree


def verify_images(manifest):
    for ref, identity in {x['ref']: x['id'] for x in manifest['images']}.items():
        p = run_command(['docker', 'image', 'inspect', ref], timeout=30)
        if p.returncode:
            raise PackageError('required image unavailable: ' + ref)
        values = json.loads(p.stdout)
        if len(values) != 1 or values[0].get('Id') != identity or values[0].get('Os') + '/' + values[0].get('Architecture') != manifest['platform']:
            raise PackageError('image identity/platform mismatch: ' + ref)


def verified_models(root, directory):
    value = json.loads(regular(root / 'services/embedding-service/model-manifest.json').read_text())
    if value.get('model') != 'bge-small-zh-v1.5' or len(value.get('files', [])) != 2 or {e.get('name') for e in value.get('files', [])} != {'model.onnx', 'tokenizer.json'}:
        raise PackageError('invalid model manifest')
    files = []
    for entry in value['files']:
        path = regular(directory / entry['name'])
        if path.stat().st_size != entry['size'] or sha(path) != entry['sha256']:
            raise PackageError('model size/SHA mismatch: ' + entry['name'])
        files.append(path)
    return files


LOADER = '''#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
deploy_root=""
if [[ ${1:-} == --deploy-root && $# == 2 ]]; then
  deploy_root=$2
elif [[ $# != 0 ]]; then
  printf '%s\n' 'Usage: ./load_images.sh [--deploy-root /absolute/deploy-root]' >&2
  exit 2
fi
sha256sum -c SHA256SUMS
docker load -i images.tar
python3 - <<'PYVERIFY'
import json, subprocess
m=json.load(open('image-manifest.json'))
for x in m['images']:
 r=json.loads(subprocess.check_output(['docker','image','inspect',x['ref']]))[0]
 assert r['Id']==x['id'] and r['Os']+'/'+r['Architecture']==x['platform'], 'loaded runtime identity/platform mismatch'
print('Runtime images verified; no image tags removed')
PYVERIFY
if [[ -n "$deploy_root" ]]; then
python3 - "$deploy_root" <<'PYMODELS'
import hashlib,json,os,pathlib,shutil,sys
root=pathlib.Path(sys.argv[1])
if not root.is_absolute() or any(p.is_symlink() for p in [root,*root.parents]):
 raise SystemExit('deploy root must be absolute and without symlinks')
source=pathlib.Path('models/bge-small-zh-v1.5')
m=json.loads((source/'model-manifest.json').read_text())
if m.get('model')!='bge-small-zh-v1.5' or len(m.get('files',[]))!=2 or {e.get('name') for e in m['files']}!={'model.onnx','tokenizer.json'}:
 raise SystemExit('invalid model manifest')
for e in m['files']:
 if type(e.get('size')) is not int or e['size']<1 or len(e.get('sha256',''))!=64 or any(c not in '0123456789abcdef' for c in e['sha256']):raise SystemExit('invalid model identity')
target=root/'shared/models/bge-small-zh-v1.5'
if any(p.is_symlink() for p in [target,*target.parents]):raise SystemExit('model destination contains symlink')
for e in m['files']:
 p=target/e['name']
 if p.exists() and (not p.is_file() or p.stat().st_size!=e['size'] or hashlib.sha256(p.read_bytes()).hexdigest()!=e['sha256']):
  raise SystemExit('existing model differs; preserved')
target.mkdir(parents=True,exist_ok=True)
for e in m['files']:
 p=target/e['name']
 if p.exists():continue
 tmp=target/(e['name']+'.'+os.urandom(8).hex()+'.part')
 try:
  with tmp.open('xb') as f, (source/e['name']).open('rb') as r:shutil.copyfileobj(r,f)
  if tmp.stat().st_size!=e['size'] or hashlib.sha256(tmp.read_bytes()).hexdigest()!=e['sha256']:raise ValueError('model integrity mismatch')
  os.link(tmp,p)
 finally:tmp.unlink(missing_ok=True)
manifest=target/'model-manifest.json'
raw=(source/'model-manifest.json').read_bytes()
if manifest.exists():
 if not manifest.is_file() or manifest.read_bytes()!=raw:raise SystemExit('existing model manifest differs; preserved')
else:
 with manifest.open('xb') as f:f.write(raw)
print('Verified models available in shared/models; no existing file overwritten')
PYMODELS
fi
'''


def stage_images(stage, root, manifest, model):
    verify_images(manifest)
    models = verified_models(root, model)
    refs = list(dict.fromkeys(x['ref'] for x in manifest['images']))
    p = run_command(['docker', 'save', '-o', str(stage / 'images.tar'), *refs], timeout=1800)
    if p.returncode or not (stage / 'images.tar').is_file():
        raise PackageError('image export failed; Docker diagnostics suppressed')
    verify_images(manifest)
    dump(stage / 'image-manifest.json', manifest)
    destination = stage / 'models/bge-small-zh-v1.5'; destination.mkdir(parents=True)
    for path in models:
        shutil.copyfile(path, destination / path.name)
        if sha(destination / path.name) != sha(path):
            raise PackageError('model changed while packaging')
    shutil.copyfile(root / 'services/embedding-service/model-manifest.json', destination / 'model-manifest.json')
    (stage / 'load_images.sh').write_text(LOADER)
    (stage / 'load_images.sh').chmod(0o755)


def stage_frp(stage, root, bins, platform):
    if platform != 'linux/amd64':
        raise PackageError('only the verified linux/amd64 FRP binaries are supported')
    for name, digest in FRP_BINARY_SHA256.items():
        if sha(regular(bins / name)) != digest:
            raise PackageError('official FRP binary SHA mismatch: ' + name)
    license_path = regular(bins.parent / 'FRP-LICENSE')
    if sha(license_path) != FRP_LICENSE_SHA256:
        raise PackageError('official FRP license SHA mismatch')
    directory = root / 'deploy/network/frp-bridge'
    if not directory.is_dir() or directory.is_symlink():
        raise PackageError('FRP source directory missing')
    for rel in collect_tree(root, 'deploy/network/frp-bridge'):
        if not (rel.suffix in {'.py', '.md', '.example'}):
            continue
        target = stage / rel.relative_to('deploy/network/frp-bridge')
        target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(root / rel, target)
    (stage / 'bin').mkdir()
    for name in FRP_BINARY_SHA256:
        shutil.copyfile(bins / name, stage / 'bin' / name); (stage / 'bin' / name).chmod(0o755)
    shutil.copyfile(license_path, stage / 'FRP-LICENSE')


def checksums(stage):
    paths = [p for p in sorted(stage.rglob('*')) if p.is_file() and p.name != 'SHA256SUMS']
    (stage / 'SHA256SUMS').write_text(''.join(sha(p) + '  ' + p.relative_to(stage).as_posix() + '\n' for p in paths))


def archive(stage, target):
    # Publish by no-replacement hard link. A concurrent packager cannot overwrite a valid archive.
    temporary = target.with_name('.' + target.name + '.' + os.urandom(6).hex() + '.part')
    try:
        with tarfile.open(temporary, 'w:gz', dereference=False) as tar:
            for path in sorted(stage.rglob('*')):
                if path.is_file():
                    tar.add(path, arcname=stage.name + '/' + path.relative_to(stage).as_posix(), recursive=False)
        os.link(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact', choices=['code', 'images', 'frp', 'all'], default='all')
    parser.add_argument('--output', required=True)
    parser.add_argument('--project-root', default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument('--version')
    parser.add_argument('--build', action='store_true', help='Explicit pnpm frozen install and platform build for code/all; never builds Docker images')
    parser.add_argument('--runtime-manifest')
    parser.add_argument('--model-dir', default=DEFAULT_MODEL)
    parser.add_argument('--frp-bin-dir', default=DEFAULT_FRP)
    parser.add_argument('--verify-only', action='store_true', help='Check image/model/source prerequisites without publishing archives')
    args = parser.parse_args(argv)
    try:
        root = Path(args.project_root).absolute()
        reject_links(root)
        if not root.is_dir():
            raise PackageError('project root must be a real directory')
        manifest_path = Path(args.runtime_manifest).absolute() if args.runtime_manifest else root / 'deploy/release/runtime-manifest.json'
        manifest = load_manifest(manifest_path)
        if args.build:
            if args.artifact not in {'code', 'all'} or args.verify_only:
                raise PackageError('--build requires code/all without verify-only')
            for cmd in [['pnpm', 'install', '--frozen-lockfile'], ['pnpm', 'build:platform']]:
                if run_command(cmd, cwd=root, timeout=1800).returncode:
                    raise PackageError('explicit platform build failed; diagnostics suppressed')
        verify_dependencies(root, manifest)
        output = Path(args.output).absolute()
        if any(output.is_relative_to(root / name) for name in TREES):
            raise PackageError('output cannot be nested inside packaged source trees')
        if output.is_symlink():
            raise PackageError('output cannot be a symlink')
        reject_links(output)
        output.mkdir(parents=True, exist_ok=True)
        if any(p.is_symlink() for p in [output, *output.parents]):
            raise PackageError('output path contains symlinks')
        kinds = ['code', 'images', 'frp'] if args.artifact == 'all' else [args.artifact]
        published = []
        batch_version = safe_version(args.version) if args.version else None
        with tempfile.TemporaryDirectory(prefix='.package-stage-', dir=output) as work:
            work = Path(work); staged = []
            for kind in kinds:
                stage = work / ('stage-' + kind); stage.mkdir()
                tree = None
                if kind == 'code':
                    tree, _ = stage_code(stage, root, manifest_path)
                elif kind == 'images':
                    if args.verify_only:
                        verify_images(manifest); verified_models(root, Path(args.model_dir).absolute())
                    else:
                        stage_images(stage, root, manifest, Path(args.model_dir).absolute())
                else:
                    stage_frp(stage, root, Path(args.frp_bin_dir).absolute(), manifest['platform'])
                if batch_version is None:
                    batch_version = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S') + '-' + (tree or manifest['runtime_set_version'])[:12]
                version = batch_version
                name = 'EngramProject_' + kind + '_' + version
                stage = stage.rename(work / name)
                info = {'schema_version': 1, 'project_key': 'engram_project', 'package_type': kind, 'version': version, 'release_id': version,
                        'created_at_utc': datetime.now(timezone.utc).isoformat(), 'platform': manifest['platform'],
                        'runtime_set_version': manifest['runtime_set_version'], 'required_images': manifest['images'],
                        'runtime_manifest_sha256': sha(manifest_path), 'source_tree_sha256': tree,
                        'git': git_metadata(root), 'autostart': False}
                if kind == 'frp':
                    info['frp_version'] = FRP_VERSION
                dump(stage / 'version_info.json', info); checksums(stage)
                destination = output / 'optional/frp' if kind == 'frp' else output
                target = destination / (name + '.tar.gz')
                reject_links(destination)
                if target.exists() or target.is_symlink() or target.with_suffix(target.suffix + '.sha256').exists():
                    raise PackageError('output already exists; refusing overwrite: ' + target.name)
                staged.append((stage, target))
            if not args.verify_only:
                for stage, target in staged:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    archive(stage, target)
                    sidecar = target.with_suffix(target.suffix + '.sha256')
                    with sidecar.open('x') as handle:
                        handle.write(sha(target) + '  ' + target.name + '\n')
                    published.append(str(target))
        print(json.dumps({'verified': True, 'artifact': args.artifact, 'archives': published, 'auto_started_services': 0}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        # Do not echo command outputs, source contents or arbitrary exception strings.
        print(json.dumps({'verified': False, 'error': 'Packaging refused: check required builds, manifests, identities, safe paths and output collisions; original outputs preserved.'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
