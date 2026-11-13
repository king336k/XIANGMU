#!/usr/bin/env python3
"""Validated offline code installation. Default is read-only --check; never pulls/builds."""
import argparse
import importlib.util
import fcntl
import errno
import hashlib
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import struct
import socket
import subprocess
import tarfile
import time
from urllib.request import urlopen

PROJECT = 'engram_project'
TREES = ('ProjectServer/plane/', 'ProjectServer/templates/', 'ProjectServer/bin/', 'ProjectFront/build/client/', 'services/collaboration/dist/', 'deploy/release/initial-knowledge/')
FILES = {'ProjectServer/manage.py', 'README.md', 'LICENSE', 'LICENSE.txt', 'start.sh', 'stop.sh', 'scripts/init_local_config.py', 'deploy/local/.env.example', 'version_info.json', 'SHA256SUMS'}
FILES.update(['AGENTS.md', 'ProjectServer/tests/RUNNING_TESTS.md', 'deploy/network/frp-bridge/README.md',
              'docs/design/agent-diagnosis/本轮实施记录.md', 'docs/design/three-platform/公网与内网部署验证.md',
              'docs/design/three-platform/本轮测试与遗留项.md', 'docs/legal/COPYRIGHT.txt', 'docs/legal/THIRD_PARTY_NOTICES.md'])
FILES.update('deploy/release/'+s for s in ['runtime-manifest.json', 'compose.yml', 'install.py', 'launcher.py', 'frp_control.py', 'seed_knowledge.py', 'nginx.web.conf', 'Caddyfile', '部署说明.md'])
FILES.update('services/'+s for s in ['diagnostic-agent/runner.py', 'diagnostic-agent/requirements.txt', 'document-ocr/server.py', 'document-ocr/extractor.py', 'document-ocr/README.md', 'embedding-service/app.py', 'embedding-service/setup_platform.py', 'embedding-service/model-manifest.json', 'embedding-service/platform.override.yml', 'embedding-service/README.md', 'embedding-service/requirements.txt'])
REQUIRED = {'ProjectServer/manage.py', 'ProjectServer/plane/__init__.py', 'ProjectServer/bin/docker-entrypoint-api.sh', 'ProjectFront/build/client/index.html', 'services/collaboration/dist/start.mjs', 'deploy/release/runtime-manifest.json', 'deploy/release/compose.yml', 'deploy/release/install.py', 'deploy/release/launcher.py', 'deploy/release/frp_control.py', 'version_info.json', 'SHA256SUMS'}
REQUIRED.add('services/embedding-service/model-manifest.json')
APPS = ['proxy', 'api', 'worker', 'beat-worker', 'diagnostic-worker', 'live', 'web', 'space', 'admin']
BASE = ['plane-db', 'plane-redis', 'plane-mq', 'plane-minio', 'builtin-embedding', 'document-ocr']
EXCLUDED = {'.git', '.ssh', 'node_modules', '__pycache__', '.pytest_cache', 'logs', 'data', 'datasets', 'quality-attachments', 'uploads', 'secrets', 'secret', 'backups'}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def file_sha(path):
    with Path(path).open('rb') as source:
        h = hashlib.sha256()
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            h.update(chunk)
        return h.hexdigest()


def safe_root(value):
    path = Path(value).expanduser()
    if not path.is_absolute() or '..' in path.parts or any(p.is_symlink() for p in [path, *path.parents]):
        raise ValueError('absolute path without symlink ancestors required')
    return path


def safe_name(value):
    return isinstance(value, str) and bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', value)) and value not in {'.', '..'}


def allowed(name):
    p = PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or str(p) != name or '\\' in name or any(ord(c) < 32 for c in name):
        return False
    if any(x in EXCLUDED for x in p.parts) or (p.name.startswith('.env') and not p.name.endswith('.example')):
        return False
    if p.suffix.lower() in {'.key', '.pem', '.p12', '.pfx', '.sqlite', '.db', '.log', '.pyc', '.onnx', '.pt'}:
        return False
    return name in FILES or name.startswith(TREES)


def load_manifest(raw):
    value = json.loads(raw)
    if value.get('schema_version') != 1 or value.get('project_key') != PROJECT or value.get('platform') not in {'linux/amd64', 'linux/arm64'} or not safe_name(value.get('runtime_set_version')):
        raise ValueError('unknown runtime manifest')
    images = value.get('images', [])
    if not images or len(images) > 64:
        raise ValueError('runtime images missing')
    services, refs = set(), {}
    for image in images:
        if (not re.fullmatch(r'[A-Za-z0-9_-]+', image.get('service', '')) or image['service'] in services or image.get('platform') != value['platform'] or not re.fullmatch(r'sha256:[a-f0-9]{64}', image.get('id', '')) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/@-]{0,499}', image.get('ref', '')) or image.get('dependency_sha256') is not None and not re.fullmatch(r'[a-f0-9]{64}', image['dependency_sha256'])):
            raise ValueError('invalid image identity')
        if image['ref'] in refs and refs[image['ref']] != image['id']:
            raise ValueError('conflicting image identities')
        refs[image['ref']] = image['id']; services.add(image['service'])
    return value


def validate_package(path):
    path = safe_root(str(path))
    if not path.is_file():
        raise ValueError('regular code archive required')
    hashes, metadata, members, total, top = {}, {}, [], 0, None
    with tarfile.open(path, 'r:gz') as tar:
        for item in tar:
            parts = item.name.split('/', 1)
            if not item.isreg() or len(parts) != 2 or not safe_name(parts[0]) or item.mode & 0o7000:
                raise ValueError('archive links/special files/unsafe paths refused')
            top = top or parts[0]
            name = parts[1]; total += item.size
            if top != parts[0] or not allowed(name) or name in hashes or item.size > 256*1024**2 or total > 4*1024**3 or len(hashes) >= 100000:
                raise ValueError('unsafe, duplicate, secret or excessive archive member')
            h = hashlib.sha256(); content = bytearray(); tail = b''
            with tar.extractfile(item) as source:
                for chunk in iter(lambda: source.read(1024*1024), b''):
                    h.update(chunk)
                    if name in {'version_info.json', 'SHA256SUMS', 'deploy/release/runtime-manifest.json', 'services/embedding-service/model-manifest.json'}:
                        content.extend(chunk)
                        if len(content) > 8*1024**2: raise ValueError('metadata too large')
                    scanned = tail+chunk
                    if re.search(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----\s*\n[A-Za-z0-9+/=]{32,}\s*\n|\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{24,}', scanned):
                        raise ValueError('private credential material refused')
                    tail = scanned[-256:]
            hashes[name] = h.hexdigest(); members.append(name)
            if content: metadata[name] = bytes(content)
    if not REQUIRED.issubset(hashes): raise ValueError('required release files missing')
    sums = {}
    for line in metadata['SHA256SUMS'].decode().splitlines():
        match = re.fullmatch(r'([a-f0-9]{64})  (.+)', line)
        if not match or match[2] in sums or not allowed(match[2]): raise ValueError('invalid checksum manifest')
        sums[match[2]] = match[1]
    if sums != {k:v for k,v in hashes.items() if k != 'SHA256SUMS'}: raise ValueError('checksum set mismatch')
    info = json.loads(metadata['version_info.json']); manifest = load_manifest(metadata['deploy/release/runtime-manifest.json'])
    release = info.get('release_id', info.get('version'))
    if info.get('schema_version') != 1 or info.get('project_key') != PROJECT or info.get('package_type') != 'code' or not safe_name(release) or release != info.get('version') or top != 'EngramProject_code_'+release or info.get('autostart') is not False:
        raise ValueError('unknown package metadata')
    if any(info.get(k) != manifest[k] for k in ['platform', 'runtime_set_version']) or info.get('required_images') != manifest['images'] or info.get('runtime_manifest_sha256') != hashes['deploy/release/runtime-manifest.json']:
        raise ValueError('package runtime manifest mismatch')
    tree = {k:v for k,v in hashes.items() if k not in {'version_info.json', 'SHA256SUMS'}}
    if info.get('source_tree_sha256') != digest(json.dumps(tree, sort_keys=True, separators=(',', ':')).encode()): raise ValueError('source tree identity mismatch')
    return {'info':info, 'manifest':manifest, 'release_id':release, 'hashes':hashes, 'archive_sha256':file_sha(path), 'model_manifest':json.loads(metadata['services/embedding-service/model-manifest.json']) if 'services/embedding-service/model-manifest.json' in metadata else None}


def command(argv, *, output=None, input_data=None, timeout=180):
    result = subprocess.run(argv, input=input_data, stdout=output or subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False)
    if result.returncode: raise ValueError('Docker operation failed; private diagnostics suppressed')
    return result.stdout if output is None else b''


def verify_images(manifest):
    platform = json.loads(command(['docker', 'info', '--format', '{{json .}}']))
    arch = {'x86_64':'amd64', 'aarch64':'arm64'}.get(platform.get('Architecture'), platform.get('Architecture'))
    if platform.get('OSType')+'/'+str(arch) != manifest['platform']: raise ValueError('target Docker architecture mismatch')
    for image in {x['ref']:x for x in manifest['images']}.values():
        rows = json.loads(command(['docker', 'image', 'inspect', image['ref']]))
        if len(rows) != 1 or rows[0]['Id'] != image['id'] or rows[0]['Os']+'/'+rows[0]['Architecture'] != manifest['platform']: raise ValueError('runtime image identity mismatch; load matching images package')


def verify_models(root, expected=None):
    model = root/'shared/models/bge-small-zh-v1.5'; meta = model/'model-manifest.json'
    safe_root(str(meta))
    if meta.is_symlink() or not meta.is_file(): raise ValueError('verified offline model directory missing; load images package first')
    data = json.loads(meta.read_text())
    if expected is not None and data != expected: raise ValueError('model manifest differs from code release')
    if data.get('model') != 'bge-small-zh-v1.5' or {x['name'] for x in data['files']} != {'model.onnx', 'tokenizer.json'}: raise ValueError('unknown model manifest')
    for row in data['files']:
        path = model/row['name']
        if path.is_symlink() or not path.is_file() or path.stat().st_size != row['size'] or file_sha(path) != row['sha256']: raise ValueError('offline model integrity mismatch')


def atomic_json(path, value):
    if path.is_symlink(): raise ValueError('unsafe record path')
    temporary = path.with_name('.'+path.name+'.'+secrets.token_hex(6))
    with os.fdopen(os.open(temporary, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600), 'w') as out:
        json.dump(value, out, ensure_ascii=False); out.flush(); os.fsync(out.fileno())
    os.replace(temporary, path)


def deployment_options(root, project=None, profiles=None):
    path = root/'shared/deployment.json'
    if path.exists():
        safe_root(str(path)); value = json.loads(path.read_text())
        if value.get('schema_version') != 1 or value.get('deploy_root') != str(root) or project and project != value.get('project_name') or profiles is not None and profiles != value.get('profiles'): raise ValueError('deployment ownership/options mismatch')
    else: value = {'schema_version':1, 'deploy_root':str(root), 'project_name':project or 'engramproject', 'profiles':profiles if profiles is not None else ['helpers']}
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,62}', value['project_name']) or value['profiles'] != ['helpers']: raise ValueError('required helpers profile or project identity invalid')
    return value


def open_install_lock(shared):
    path = safe_root(str(shared/'.install.lock'))
    return os.fdopen(os.open(path, os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW, 0o600), 'a')


def wrapper_bytes(action):
    return ('#!/bin/sh\n# EngramProject managed deployment wrapper v1\nset -eu\nroot=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)\nexec python3 "$root/current/deploy/release/launcher.py" --deploy-root "$root" '+action+' \"$@\"\n').encode()


def preflight_wrappers(root, record):
    for action in ['start', 'stop']:
        path = root/(action+'.sh'); safe_root(str(path))
        if path.exists() and (not path.is_file() or path.read_bytes() != wrapper_bytes(action) and file_sha(path) != record.get('managed_wrappers', {}).get(path.name)):
            raise ValueError('existing user start/stop script preserved; choose a new deployment directory')


def install_wrappers(root, record):
    preflight_wrappers(root, record)
    for action in ['start', 'stop']:
        path = root/(action+'.sh'); raw = wrapper_bytes(action)
        if not path.exists() or path.read_bytes() != raw:
            temporary = root/('.'+path.name+'.'+secrets.token_hex(6))
            with os.fdopen(os.open(temporary, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o755), 'wb') as out: out.write(raw); out.flush(); os.fsync(out.fileno())
            if path.exists(): os.replace(temporary, path)
            else: os.link(temporary, path); temporary.unlink()
        path.chmod(0o755)
        record.setdefault('managed_wrappers', {})[path.name] = digest(raw)


def deployment_endpoint(shared, preferred, bind, host='localhost'):
    """Select a new installation's free port; upgrades retain their saved endpoint."""
    saved = shared/'.env'
    if saved.exists():
        values = read_env(saved)
        port = int(values['HTTP_PORT'])
        return {'port':port, 'bind':values.get('BIND_ADDRESS', '127.0.0.1'),
                'host':values.get('APP_DOMAIN', 'localhost'),
                'url':values.get('WEB_URL', f'http://localhost:{port}')}
    if not 1 <= preferred <= 65535 or bind not in {'127.0.0.1', '0.0.0.0'}:
        raise ValueError('invalid bind/port')
    if not isinstance(host, str) or len(host) > 253 or not re.fullmatch(
        r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?', host
    ) or any(not label or len(label) > 63 or label.startswith('-') or label.endswith('-') for label in host.split('.')):
        raise ValueError('host must be an IPv4 address or DNS name without scheme/port')
    for port in range(preferred, min(preferred + 100, 65536)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind((bind, port))
            except OSError as error:
                if error.errno in {errno.EADDRINUSE, errno.EACCES}:
                    continue
                raise
        return {'port':port, 'bind':bind, 'host':host, 'url':f'http://{host}:{port}'}
    raise ValueError('no free TCP port in the requested 100-port range')


def initialize_env(shared, port, bind, subnets, host='localhost'):
    safe_root(str(shared))
    path = shared/'.env'
    if path.exists():
        safe_root(str(path))
        if path.stat().st_mode & 0o077: raise ValueError('shared environment must be mode0600')
        return read_env(path)
    values = {'HTTP_PORT':str(port), 'BIND_ADDRESS':bind, 'WEB_URL':f'http://{host}:{port}', 'APP_DOMAIN':host, 'CORS_ALLOWED_ORIGINS':f'http://{host}:{port}', 'POSTGRES_USER':'engram', 'POSTGRES_DB':'engramproject', 'RABBITMQ_USER':'engram', 'RABBITMQ_VHOST':'engramproject', 'AWS_ACCESS_KEY_ID':'engram-local', 'AWS_S3_BUCKET_NAME':'uploads', 'FILE_SIZE_LIMIT':'52428800', 'USE_MINIO':'1', 'DEBUG':'0', 'PLATFORM_SUBNET':subnets[0], 'HELPERS_SUBNET':subnets[1]}
    for name in ['POSTGRES_PASSWORD', 'RABBITMQ_PASSWORD', 'AWS_SECRET_ACCESS_KEY', 'SECRET_KEY', 'LIVE_SERVER_SECRET_KEY', 'BUILTIN_EMBEDDING_KEY', 'DOCUMENT_OCR_KEY']: values[name] = secrets.token_urlsafe(48)
    with os.fdopen(os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600), 'w') as out:
        out.write(''.join(k+'='+v+'\n' for k,v in values.items())); out.flush(); os.fsync(out.fileno())
    return values


def read_env(path):
    safe_root(str(path)); result = {}
    for line in path.read_text().splitlines():
        if line.strip() and not line.startswith('#'):
            key,sep,value = line.partition('=')
            if not sep or not re.fullmatch(r'[A-Z][A-Z0-9_]*', key) or key in result: raise ValueError('invalid shared environment')
            result[key] = value
    return result


def compose(root, release, record):
    return ['docker', 'compose', '--project-directory', str(release), '--project-name', record['project_name'], '--env-file', str(root/'shared/.env'), '-f', str(release/'deploy/release/compose.yml'), *sum((['--profile', p] for p in record['profiles']), [])]


def compose_run(root, release, record, args, **kwargs):
    env = {**os.environ, **read_env(root/'shared/.env'), 'RELEASE_DIR':str(release), 'SHARED_DIR':str(root/'shared')}
    # Explicit interpolation variables are not shell source and remain private.
    with_env = kwargs.pop('env', None)
    if with_env: env.update(with_env)
    result = subprocess.run(compose(root, release, record)+args, env=env, stdout=kwargs.get('output', subprocess.PIPE), stderr=subprocess.PIPE, input=kwargs.get('input_data'), timeout=kwargs.get('timeout', 300), check=False)
    if result.returncode: raise ValueError('Compose operation failed; private diagnostics suppressed')
    return result.stdout if kwargs.get('output') is None else b''


def validate_compose(config, root, release, manifest, record):
    images = {x['ref'] for x in manifest['images']}
    for service in config.get('services', {}).values():
        if service.get('image') not in images or service.get('privileged') or service.get('build') or service.get('network_mode') == 'host' or service.get('volumes_from') or service.get('devices'):
            raise ValueError('Compose requires unapproved runtime or host privileges')
        for mount in service.get('volumes', []):
            if mount.get('type') == 'bind':
                source = safe_root(mount['source'])
                if not mount.get('read_only') or not any(source.is_relative_to(p) for p in [release, root/'shared/models']): raise ValueError('Compose host mount outside release/model boundary')
    for category in ['volumes', 'networks']:
        for name, value in config.get(category, {}).items():
            value = value or {}
            if value.get('external') or value.get('name', record['project_name']+'_'+name) != record['project_name']+'_'+name: raise ValueError('external deployment resource cannot be adopted')


def choose_subnets():
    ids = command(['docker', 'network', 'ls', '-q']).decode().split(); used = []
    if ids:
        for network in json.loads(command(['docker', 'network', 'inspect', *ids])):
            used.extend(ipaddress.ip_network(x['Subnet']) for x in (network.get('IPAM', {}).get('Config') or []) if x.get('Subnet'))
    for line in Path('/proc/net/route').read_text().splitlines()[1:]:
        fields = line.split()
        if len(fields) >= 8 and fields[1] != '00000000':
            address = socket.inet_ntoa(struct.pack('<I', int(fields[1], 16)))
            mask = socket.inet_ntoa(struct.pack('<I', int(fields[7], 16)))
            used.append(ipaddress.ip_network(address+'/'+mask, strict=False))
    candidates = [ipaddress.ip_network(f'10.246.{i}.0/28') for i in range(1, 255)]
    result = tuple(str(x) for x in candidates if not any(x.overlaps(y) for y in used if x.version == y.version))[:2]
    if len(result) != 2: raise ValueError('two unused private subnets required')
    return result


def pristine_target(root):
    if not root.exists(): return True
    for child in root.iterdir():
        if child.name == 'releases' and child.is_dir() and not child.is_symlink() and not any(child.iterdir()): continue
        if child.name == 'shared' and child.is_dir() and not child.is_symlink() and all(p.name in {'models', '.install.lock'} and not p.is_symlink() for p in child.iterdir()): continue
        return False
    return True


def owned_containers(record, release=None):
    ids = command(['docker', 'ps', '-aq', '--filter', 'label=com.docker.compose.project='+record['project_name']]).decode().split()
    if not ids: return []
    rows = json.loads(command(['docker', 'inspect', *ids]))
    for row in rows:
        labels = row['Config'].get('Labels') or {}
        working = Path(labels.get('com.docker.compose.project.working_dir', ''))
        if release is None or not working.is_absolute() or working.parent != release.parent or labels.get('com.docker.compose.project', record['project_name']) != record['project_name']: raise ValueError('Compose project already belongs to another deployment')
    return rows


def extract_release(archive, root, checked):
    safe_root(str(root/'releases'))
    release = root/'releases'/checked['release_id']
    if release.exists() or release.is_symlink(): raise ValueError('release already exists; refusing overwrite')
    stage = release.with_name('.'+release.name+'.'+secrets.token_hex(6)); stage.mkdir()
    try:
        with tarfile.open(archive, 'r:gz') as tar:
            for item in tar:
                name = item.name.split('/',1)[1]
                if name not in checked['hashes'] or not item.isreg(): raise ValueError('archive changed during install')
                target = stage/name; target.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(item) as source, target.open('xb') as out: shutil.copyfileobj(source, out)
                target.chmod(0o755 if item.mode & 0o111 else 0o644)
                if file_sha(target) != checked['hashes'][name]: raise ValueError('archive changed during install')
        if file_sha(archive) != checked['archive_sha256']: raise ValueError('archive changed during install')
        stage.rename(release)
    finally:
        if stage.exists(): shutil.rmtree(stage)
    return release


def stage_seed(root, release):
    source = release/'deploy/release/initial-knowledge'
    if not source.exists(): return {'status':'not_in_package', 'imported':0}
    command(['python3', str(release/'deploy/release/seed_knowledge.py'), '--check', '--seed-dir', str(source)])
    manifest = json.loads((source/'manifest.json').read_text()); version = manifest.get('seed_version')
    if not safe_name(version) or manifest.get('schema') != 'engramproject-initial-knowledge-manifest-v1': raise ValueError('unknown initial knowledge manifest')
    if set(manifest.get('files', {})) != {'knowledge-bundle.json'}: raise ValueError('initial knowledge file set invalid')
    for name, row in manifest['files'].items():
        path = source/name
        if path.stat().st_size != row['size'] or file_sha(path) != row['sha256']: raise ValueError('initial knowledge integrity mismatch')
    target = root/'shared/initial-knowledge'/version; safe_root(str(target))
    if target.exists():
        if {p.name:file_sha(p) for p in target.iterdir()} != {p.name:file_sha(p) for p in source.iterdir()}: raise ValueError('existing seed differs; preserved')
    else:
        target.parent.mkdir(parents=True, exist_ok=True); temporary = target.with_name('.'+version+'.'+secrets.token_hex(6))
        shutil.copytree(source, temporary); temporary.rename(target)
    return {'status':'staged_pending_admin', 'imported':0, 'seed_version':version, 'manifest_sha256':file_sha(target/'manifest.json')}


def initial_knowledge_step(root, release, old):
    if old is not None or (root/'shared/initial-knowledge').exists():
        return {'status':'skipped_existing_deployment', 'imported':0}
    return stage_seed(root, release)


def prepare_mountpoints(release):
    for name in ['quality-attachments', 'mediafiles', 'plane/logs', 'plane/static-assets/collected-static']:
        path = safe_root(str(release/'ProjectServer'/name))
        path.mkdir(parents=True, exist_ok=True)


def export_logs(root, record, rows, since='24h'):
    stamp = time.strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(3)
    for row in rows:
        service = row['Config']['Labels'].get('com.docker.compose.service', 'unknown')
        if not safe_name(service): raise ValueError('invalid log service')
        directory = root/'shared/logs'/service; safe_root(str(directory)); directory.mkdir(parents=True, exist_ok=True)
        path = directory/(stamp+'.log')
        with os.fdopen(os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600), 'wb') as out:
            result = subprocess.run(['docker', 'logs', '--timestamps', '--since', since, row['Id']], stdout=out, stderr=out, check=False, timeout=90)
            if result.returncode: raise ValueError('log export failed; old services preserved')
    return stamp


def backup_database(root, old, record, values):
    path = root/'shared/backups'/('pre-upgrade-'+time.strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(4)+'.dump'); path.parent.mkdir(parents=True, exist_ok=True)
    stage = 'database_backup_dump_failed'
    try:
        with os.fdopen(os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600), 'wb') as out:
            compose_run(root, old, record, ['exec', '-T', 'plane-db', 'pg_dump', '--host=/var/run/postgresql', '-U', values.get('POSTGRES_USER','engram'), '-d', values.get('POSTGRES_DB','engramproject'), '--format=c'], output=out)
        if path.stat().st_size < 64: raise ValueError('empty backup')
        stage = 'database_backup_verify_failed'
        with path.open('rb') as source:
            compose_run(root, old, record, ['exec', '-T', 'plane-db', 'pg_restore', '--list'], input_data=source.read())
    except (ValueError, OSError, subprocess.SubprocessError):
        atomic_json(path.with_suffix('.failed.json'), {'file':path.name, 'stage':stage, 'bytes':path.stat().st_size if path.exists() else 0, 'validated':False})
        raise ValueError(stage+'; backup evidence preserved, migration refused') from None
    atomic_json(path.with_suffix('.json'), {'file':path.name, 'sha256':file_sha(path), 'validated_by':'pg_restore --list'})
    return str(path)


def set_link(root, name, release):
    path = root/name
    if path.exists() and not path.is_symlink(): raise ValueError('release pointer must be a symlink')
    temporary = root/('.'+name+'.'+secrets.token_hex(6)); temporary.symlink_to(release.relative_to(root)); os.replace(temporary, path)


def current_release(root):
    path = root/'current'
    if not path.is_symlink():
        if path.exists(): raise ValueError('current pointer is invalid')
        return None
    release = path.resolve(strict=True)
    if release.parent != root/'releases' or not release.is_dir() or release.is_symlink(): raise ValueError('current release escapes deployment')
    return release


def wait_health(root, release, record, values, seconds=120):
    end = time.monotonic()+seconds
    while time.monotonic() < end:
        try:
            compose_run(root, release, record, ['exec', '-T', 'api', 'python', '-c', "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/',timeout=3)"])
            address = values.get('BIND_ADDRESS','127.0.0.1'); address = '127.0.0.1' if address == '0.0.0.0' else address
            with urlopen('http://'+address+':'+values.get('HTTP_PORT','18890')+'/', timeout=3) as response:
                if response.status == 200: return
        except (ValueError, OSError): pass
        time.sleep(2)
    raise ValueError('new release health failed; current pointer unchanged; no schema rollback attempted')



def frp_reconcile(root, local_port, action=None, backend=None, source_config=None, python_executable=None):
    spec = importlib.util.spec_from_file_location('engram_managed_frp', Path(__file__).with_name('frp_control.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.reconcile(root, local_port, action=action, backend=backend,
                            source_config=source_config, python_executable=python_executable)

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package'); parser.add_argument('--deploy-root', required=True)
    group = parser.add_mutually_exclusive_group(); group.add_argument('--check', action='store_true'); group.add_argument('--apply', action='store_true')
    parser.add_argument('--project-name'); parser.add_argument('--profile', action='append'); parser.add_argument('--port', type=int, default=18890, help='Preferred port; new installs try the next 99 ports when occupied'); parser.add_argument('--bind', default='127.0.0.1'); parser.add_argument('--host', default='localhost', help='Public IPv4 address or DNS name, without scheme or port')
    frp = parser.add_mutually_exclusive_group()
    frp.add_argument('--openfrp', action='store_true', help='Enable this deployment public TCP 18886 proxy only')
    frp.add_argument('--closefrp', action='store_true', help='Stop only the owned project FRP proxy')
    parser.add_argument('--frp-backend', choices=['docker', 'systemd-user'])
    parser.add_argument('--frp-source-config', help='Existing FRP TOML path; never copied into shared state')
    parser.add_argument('--frp-python', help='Python 3.11+ executable for systemd-user fallback')
    args = parser.parse_args(argv)
    receipt = None
    try:
        root = safe_root(args.deploy_root)
        frp_action = 'open' if args.openfrp else 'close' if args.closefrp else None
        if not args.package:
            if not frp_action or not args.apply: raise ValueError('FRP-only changes require --apply and an explicit switch')
            record = deployment_options(root, args.project_name, args.profile)
            if current_release(root) is None: raise ValueError('owned current release required')
            with open_install_lock(root/'shared') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
                values = read_env(root/'shared/.env')
                state = frp_reconcile(root, int(values['HTTP_PORT']), frp_action, args.frp_backend, args.frp_source_config, args.frp_python)
            print(json.dumps({'applied':True, 'frp_enabled':state['enabled'], 'frp_backend':state.get('backend','docker')}))
            return 0
        checked = validate_package(Path(args.package).absolute()); record = deployment_options(root, args.project_name, args.profile)
        if not (root/'shared/deployment.json').exists() and not pristine_target(root): raise ValueError('target contains unrelated files; no deployment ownership record')
        preflight_wrappers(root, record)
        if not 1 <= args.port <= 65535 or args.bind not in {'127.0.0.1','0.0.0.0'}: raise ValueError('invalid bind/port')
        endpoint = deployment_endpoint(root/'shared', args.port, args.bind, args.host)
        verify_images(checked['manifest']); verify_models(root, checked['model_manifest'])
        if not (root/'shared/deployment.json').exists():
            names = command(['docker', 'volume', 'ls', '--format', '{{.Name}}']).decode().split()
            if any(n.startswith(record['project_name']+'_') for n in names): raise ValueError('existing project data volumes cannot be adopted')
        old = current_release(root); rows = owned_containers(record, old)
        if not args.apply:
            print(json.dumps({'checked':True, 'applied':False, 'release_id':checked['release_id'], 'source_tree_sha256':checked['info']['source_tree_sha256'], 'existing_release':old.name if old else None, 'access_url':endpoint['url'], 'port':endpoint['port'], 'requested_port':args.port, 'port_changed':endpoint['port'] != args.port})); return 0
        subnets = choose_subnets() if not (root/'shared/.env').exists() else None
        root.mkdir(parents=True, exist_ok=True); shared = root/'shared'; shared.mkdir(exist_ok=True); safe_root(str(shared)); (root/'releases').mkdir(exist_ok=True)
        with open_install_lock(shared) as lock:
            fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
            if current_release(root) != old: raise ValueError('deployment changed during preflight')
            atomic_json(shared/'deployment.json', record)
            endpoint = deployment_endpoint(shared, args.port, args.bind, args.host)
            values = initialize_env(shared, endpoint['port'], endpoint['bind'], subnets, endpoint['host']); release = extract_release(Path(args.package), root, checked)
            prepare_mountpoints(release)
            config = json.loads(compose_run(root, release, record, ['config', '--format', 'json']))
            validate_compose(config, root, release, checked['manifest'], record)
            receipt = {'release_id':release.name, 'status':'prepared', 'schema_rollback_attempted':False, 'access_url':endpoint['url'], 'port':endpoint['port']}
            atomic_json(shared/'last-install.json', receipt)
            if old:
                if not rows or not any(r['Config']['Labels'].get('com.docker.compose.service') == 'plane-db' for r in rows): raise ValueError('existing database backup target unavailable; migration refused')
                export_logs(root, record, rows)
                compose_run(root, old, record, ['stop', *APPS])
                receipt['backup'] = backup_database(root, old, record, values)
            compose_run(root, release, record, ['up', '-d', '--no-build', '--pull', 'never', *BASE])
            compose_run(root, release, record, ['run', '--rm', '--no-deps', '--pull', 'never', 'migrator'], timeout=600)
            receipt['status'] = 'migrated'; atomic_json(shared/'last-install.json', receipt)
            receipt['initial_knowledge'] = initial_knowledge_step(root, release, old); atomic_json(shared/'last-install.json', receipt)
            compose_run(root, release, record, ['up', '-d', '--no-build', '--pull', 'never', *APPS])
            wait_health(root, release, record, values)
            install_wrappers(root, record); atomic_json(shared/'deployment.json', record)
            if old: set_link(root, 'previous', old)
            set_link(root, 'current', release); receipt['status'] = 'healthy'; atomic_json(shared/'last-install.json', receipt)
            state = frp_reconcile(root, endpoint['port'], frp_action, args.frp_backend, args.frp_source_config, args.frp_python)
            receipt['frp_enabled'] = state['enabled']; atomic_json(shared/'last-install.json', receipt)
        print(json.dumps({'checked':True, 'applied':True, 'release_id':release.name, 'health_verified':True, 'access_url':endpoint['url'], 'port':endpoint['port'], 'requested_port':args.port, 'port_changed':endpoint['port'] != args.port})); return 0
    except (ValueError, OSError, KeyError, TypeError, tarfile.TarError, subprocess.SubprocessError) as error:
        if receipt is not None:
            receipt['last_successful_phase'] = receipt['status']; receipt['status'] = 'failed'
            if str(error).startswith(('database_backup_dump_failed', 'database_backup_verify_failed')): receipt['failure_stage'] = str(error).split(';')[0]
            atomic_json(shared/'last-install.json', receipt)
        print(json.dumps({'applied':False, 'error':'Installation refused or failed; private diagnostics suppressed. Check image/package/model identities and shared/last-install.json; no schema rollback performed.'})); return 1


if __name__ == '__main__':
    raise SystemExit(main())
