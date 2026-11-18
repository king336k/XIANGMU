#!/usr/bin/env python3
"""Read-only file browsing and bounded downloads through the enrolled operator."""
import base64
import hashlib
import hmac
import getpass
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tarfile
import time
import uuid
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

CHUNK = 96 * 1024
MAX_DOWNLOAD = 256 * 1024 * 1024
_PEER_SCOPE_SECRET = os.urandom(32)
DENIED = {'.codex', '.claude', '.docker', '.cc-switch', '.mozilla', '.chromium', '.google-chrome', '.thunderbird', '.ssh', '.config', '.cache', '.local', '.git', '.aws', '.gnupg', '.kube', 'id_rsa', 'id_ed25519', 'token', 'sim-token', 'robot177-key', 'known_hosts', 'credentials', 'credential', '.netrc', '.npmrc', '.pypirc', '.bash_history', '.zsh_history'}


def permitted_name(name):
    lower = name.lower()
    return (lower not in DENIED and not lower.startswith(('.env', '.field-', '.engram-upload-'))
            and not any(word in lower for word in ('secret', 'token', 'credential', 'password'))
            and not lower.endswith(('.key', '.pem', '.p12', '.pfx')))


def resolve(root, relative):
    root = Path(root).resolve(strict=True)
    if not isinstance(relative, str) or len(relative) > 2000 or '\x00' in relative:
        raise ValueError('invalid_path')
    path = Path(relative or '.')
    if path.is_absolute() or '..' in path.parts:
        raise ValueError('path_outside_home')
    current = root
    for part in path.parts:
        if not permitted_name(part):
            raise ValueError('protected_path')
        current = current / part
        if current.is_symlink():
            raise ValueError('symbolic_links_not_downloadable')
    if not current.resolve(strict=True).is_relative_to(root):
        raise ValueError('path_outside_home')
    return current


def directory_fd(root, relative=''):
    root = Path(root)
    if root.is_symlink():
        raise ValueError('unsafe_home_root')
    parts = Path(relative or '.').parts if isinstance(relative, str) else ()
    if not isinstance(relative, str) or len(relative) > 2000 or '\x00' in relative or Path(relative).is_absolute() or '..' in parts:
        raise ValueError('invalid_relative_directory')
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts:
            if not permitted_name(part): raise ValueError('protected_path')
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd); fd = child
        return fd
    except Exception:
        os.close(fd); raise


def regular_fd(parent, name, flags=os.O_RDONLY):
    fd = os.open(name, flags | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        os.close(fd)
        raise ValueError('regular_file_without_hardlinks_required')
    return fd


def same_inode(info, expected):
    return [info.st_dev, info.st_ino] == expected


def private_spool(spool):
    spool = Path(spool)
    if spool.is_symlink(): raise ValueError('unsafe_download_cache')
    spool.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = spool.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError('unsafe_download_cache')
    return spool


def save_meta(stream, meta):
    stream.seek(0); stream.truncate(); json.dump(meta, stream)
    stream.flush(); os.fsync(stream.fileno())


def cleanup(root, spool_fd):
    for name in os.listdir(spool_fd):
        if not re.fullmatch(r'[a-f0-9]{32}(?:\.upload)?', name): continue
        try:
            info = os.stat(name, dir_fd=spool_fd, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or time.time() - info.st_mtime <= 1800: continue
            if name.endswith('.upload'):
                fd = regular_fd(spool_fd, name)
                with os.fdopen(fd) as stream: meta = json.load(stream)
                if not meta.get('completed'):
                    parent = directory_fd(root, meta['path'])
                    try:
                        part = '.engram-upload-' + name[:-7] + '.part'
                        if same_inode(os.fstat(parent), meta['directory_inode']):
                            part_info = os.stat(part, dir_fd=parent, follow_symlinks=False)
                            if same_inode(part_info, meta['part_inode']): os.unlink(part, dir_fd=parent)
                    finally: os.close(parent)
            os.unlink(name, dir_fd=spool_fd)
        except (OSError, ValueError, KeyError, TypeError):
            # Never follow a changed path or delete an object without ownership evidence.
            try: os.unlink(name, dir_fd=spool_fd)
            except OSError: pass


def upload_request(root, spool_fd, request):
    action = request['action']
    if action == 'upload_start':
        name, size, digest = request.get('filename'), request.get('size'), request.get('sha256')
        if (not isinstance(name, str) or not name or name in {'.', '..'} or '/' in name or '\\' in name
                or any(ord(c) < 32 for c in name) or not permitted_name(name) or len(name.encode()) > 255
                or type(size) is not int or not 0 <= size <= MAX_DOWNLOAD
                or not isinstance(digest, str) or not re.fullmatch(r'[a-f0-9]{64}', digest)):
            raise ValueError('invalid_upload_name_size_or_sha256')
        directory = directory_fd(root, request.get('path', ''))
        ticket = uuid.uuid4().hex; part = '.engram-upload-' + ticket + '.part'
        try:
            try: os.stat(name, dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError: pass
            else: raise ValueError('target_already_exists_choose_another_name')
            leases = [item for item in os.listdir(spool_fd) if item.endswith('.upload')]
            reserved = 0
            for item in leases:
                fd = regular_fd(spool_fd, item)
                with os.fdopen(fd) as stream:
                    lease = json.load(stream)
                    if not lease.get('completed'): reserved += lease['size']
            if len(leases) >= 32 or reserved + size > 2 * MAX_DOWNLOAD:
                raise ValueError('upload_cache_full_retry_after_expiry')
            fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            part_info = os.fstat(fd); os.close(fd)
            meta = {'path': request.get('path', ''), 'filename': name, 'size': size, 'sha256': digest,
                    'received': 0, 'directory_inode': [os.fstat(directory).st_dev, os.fstat(directory).st_ino],
                    'part_inode': [part_info.st_dev, part_info.st_ino]}
            try:
                fd = os.open(ticket + '.upload', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=spool_fd)
                with os.fdopen(fd, 'w') as stream: save_meta(stream, meta)
            except Exception:
                os.unlink(part, dir_fd=directory); raise
            os.fsync(directory)
            return {'ticket': ticket, 'offset': 0}
        finally: os.close(directory)
    ticket = request.get('ticket', '')
    if not isinstance(ticket, str) or not re.fullmatch(r'[a-f0-9]{32}', ticket): raise ValueError('invalid_upload_ticket')
    fd = regular_fd(spool_fd, ticket + '.upload', os.O_RDWR)
    with os.fdopen(fd, 'r+') as stream:
        meta = json.load(stream)
        if meta.get('completed'):
            if action == 'upload_finish': return meta['completed']
            if action == 'upload_abort':
                os.unlink(ticket + '.upload', dir_fd=spool_fd); return {'aborted': True}
            raise ValueError('upload_already_completed')
        directory = directory_fd(root, meta['path'])
        try:
            if not same_inode(os.fstat(directory), meta['directory_inode']): raise ValueError('upload_directory_changed')
            part = '.engram-upload-' + ticket + '.part'
            if action == 'upload_finish':
                # A crash after the atomic no-overwrite link but before metadata
                # acknowledgement must recover the same inode, never publish twice.
                try: published=os.stat(meta['filename'],dir_fd=directory,follow_symlinks=False)
                except FileNotFoundError: published=None
                if published and same_inode(published,meta['part_inode']) and stat.S_ISREG(published.st_mode):
                    check=os.open(meta['filename'],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory)
                    with os.fdopen(check,'rb') as content:
                        if not same_inode(os.fstat(content.fileno()),meta['part_inode']):raise ValueError('upload_target_changed')
                        digest=hashlib.sha256()
                        for data in iter(lambda:content.read(CHUNK),b''):digest.update(data)
                    if published.st_size!=meta['size'] or digest.hexdigest()!=meta['sha256']:raise ValueError('upload_target_changed')
                    try:
                        original=os.stat(part,dir_fd=directory,follow_symlinks=False)
                        if not same_inode(original,meta['part_inode']):raise ValueError('upload_part_changed')
                        os.unlink(part,dir_fd=directory)
                    except FileNotFoundError:pass
                    result={'uploaded':True,'path':str(Path(root)/meta['path']/meta['filename']),
                            'filename':meta['filename'],'size':meta['size'],'sha256':meta['sha256']}
                    meta['completed']=result;save_meta(stream,meta);os.fsync(directory)
                    return result
            fd = regular_fd(directory, part, os.O_RDWR)
            with os.fdopen(fd, 'r+b') as output:
                if not same_inode(os.fstat(output.fileno()), meta['part_inode']): raise ValueError('upload_part_changed')
                if action == 'upload_abort':
                    os.unlink(part, dir_fd=directory); os.unlink(ticket + '.upload', dir_fd=spool_fd)
                    os.fsync(directory); return {'aborted': True}
                if action == 'upload_chunk':
                    offset = request.get('offset'); data = base64.b64decode(request.get('data', ''), validate=True)
                    if type(offset) is not int or offset < 0 or not 0 < len(data) <= CHUNK or offset + len(data) > meta['size']:
                        raise ValueError('invalid_upload_chunk')
                    if offset > meta['received']: raise ValueError('upload_chunk_out_of_order')
                    output.seek(offset)
                    if offset < meta['received']:
                        if offset + len(data) > meta['received'] or output.read(len(data)) != data:
                            raise ValueError('upload_retry_content_conflict')
                    else:
                        output.write(data); output.flush(); os.fsync(output.fileno()); meta['received'] += len(data)
                    save_meta(stream, meta)
                    return {'next_offset': meta['received']}
                if action != 'upload_finish': raise ValueError('unsupported_upload_action')
                if meta['received'] != meta['size'] or os.fstat(output.fileno()).st_size != meta['size']:
                    raise ValueError('upload_incomplete')
                output.seek(0); digest = hashlib.sha256()
                for data in iter(lambda: output.read(CHUNK), b''): digest.update(data)
                if digest.hexdigest() != meta['sha256']: raise ValueError('upload_sha256_mismatch')
                if not same_inode(os.stat(part, dir_fd=directory, follow_symlinks=False), meta['part_inode']):
                    raise ValueError('upload_part_changed')
                try: os.link(part, meta['filename'], src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
                except FileExistsError: raise ValueError('target_already_exists_choose_another_name')
                if not same_inode(os.stat(meta['filename'], dir_fd=directory, follow_symlinks=False), meta['part_inode']):
                    os.unlink(meta['filename'], dir_fd=directory); raise ValueError('upload_part_changed')
                os.unlink(part, dir_fd=directory); os.fsync(directory)
                result = {'uploaded': True, 'path': str(Path(root) / meta['path'] / meta['filename']),
                          'filename': meta['filename'], 'size': meta['size'], 'sha256': meta['sha256']}
                meta['completed'] = result; save_meta(stream, meta)
                return result
        finally: os.close(directory)


def local_request(root, spool, request):
    if not isinstance(request, dict) or not isinstance(request.get('action'), str): raise ValueError('invalid_file_request')
    spool = private_spool(spool)
    spool_fd = directory_fd(spool)
    lock = os.open('.transfer.lock', os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=spool_fd)
    try:
        if not stat.S_ISREG(os.fstat(lock).st_mode) or os.fstat(lock).st_nlink != 1:raise ValueError('unsafe_transfer_lock')
        fcntl.flock(lock, fcntl.LOCK_EX)
        cleanup(root, spool_fd)
        return file_request(root, spool_fd, request)
    finally: os.close(lock); os.close(spool_fd)


def file_request(root, spool_fd, request):
    action = request['action']
    if action.startswith('upload_'): return upload_request(root, spool_fd, request)
    if action not in {'list', 'prepare', 'chunk'}: raise ValueError('unsupported_file_operation')
    if action == 'chunk':
        ticket, offset = request.get('ticket', ''), request.get('offset')
        if not isinstance(ticket, str) or not re.fullmatch(r'[a-f0-9]{32}', ticket) or type(offset) is not int or offset < 0:
            raise ValueError('invalid_download_chunk')
        fd = regular_fd(spool_fd, ticket)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if time.time() - info.st_mtime > 1800 or offset > info.st_size: raise ValueError('download_expired_or_invalid')
            stream.seek(offset); data = stream.read(CHUNK)
        return {'data': base64.b64encode(data).decode(), 'offset': offset, 'next_offset': offset + len(data)}
    relative = request.get('path', '')
    path = resolve(root, relative)
    if action == 'list':
        directory = directory_fd(root, relative)
        try:
            entries = []
            for name in os.listdir(directory):
                if not permitted_name(name): continue
                try: info = os.stat(name, dir_fd=directory, follow_symlinks=False)
                except OSError: continue
                if stat.S_ISDIR(info.st_mode) or (stat.S_ISREG(info.st_mode) and info.st_nlink == 1):
                    entries.append({'name': name, 'kind': 'directory' if stat.S_ISDIR(info.st_mode) else 'file',
                                    'size': info.st_size, 'modified': info.st_mtime})
                if len(entries) > 5000: raise ValueError('directory_has_more_than_5000_entries')
        finally: os.close(directory)
        offset = request.get('offset', 0)
        if type(offset) is not int or offset < 0: raise ValueError('invalid_listing_offset')
        entries.sort(key=lambda item: (item['kind'] != 'directory', item['name'].lower()))
        return {'username': getpass.getuser(), 'root': str(Path(root)), 'path': str(Path(relative or '.')),
                'entries': entries[offset:offset + 100], 'offset': offset, 'total': len(entries)}
    used = sum(os.stat(name, dir_fd=spool_fd, follow_symlinks=False).st_size for name in os.listdir(spool_fd))
    if used > 2 * MAX_DOWNLOAD: raise ValueError('download_cache_full_retry_after_expiry')
    ticket = uuid.uuid4().hex
    fd = os.open(ticket, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=spool_fd)
    total = count = skipped = 0
    try:
        with os.fdopen(fd, 'wb') as output:
            # Every operation below is relative to an anchored descriptor, not a
            # previously checked path that a concurrent rename can redirect.
            parent_relative = str(Path(relative).parent) if relative else '.'
            parent = directory_fd(root, parent_relative)
            try:
                name = Path(relative).name if relative and relative != '.' else '.'
                info = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    directory = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                    archive_root = path.name
                    def add_directory(archive, current, prefix, depth=0):
                        nonlocal total, count, skipped
                        if depth > 64:raise ValueError('download_directory_depth_exceeded')
                        names = os.listdir(current)
                        if not names and prefix != archive_root:
                            header = tarfile.TarInfo(prefix); header.type = tarfile.DIRTYPE; header.mode = 0o700
                            archive.addfile(header)
                        for child in sorted(names):
                            if not permitted_name(child): skipped += 1; continue
                            entry = os.stat(child, dir_fd=current, follow_symlinks=False)
                            child_name = prefix + '/' + child
                            if stat.S_ISDIR(entry.st_mode):
                                nested = os.open(child, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
                                try: add_directory(archive, nested, child_name, depth+1)
                                finally: os.close(nested)
                            elif stat.S_ISREG(entry.st_mode) and entry.st_nlink == 1:
                                source = regular_fd(current, child)
                                with os.fdopen(source, 'rb') as stream:
                                    actual = os.fstat(stream.fileno()); total += actual.st_size; count += 1
                                    if total > MAX_DOWNLOAD or count > 20000: raise ValueError('download_limit_256_MiB_or_20000_files')
                                    header = tarfile.TarInfo(child_name); header.size = actual.st_size
                                    header.mode = stat.S_IMODE(actual.st_mode); header.mtime = actual.st_mtime
                                    archive.addfile(header, stream)
                            else: skipped += 1
                    try:
                        with tarfile.open(fileobj=output, mode='w:gz') as archive: add_directory(archive, directory, archive_root)
                    finally: os.close(directory)
                    filename = path.name + '.tar.gz'
                elif stat.S_ISREG(info.st_mode):
                    source = regular_fd(parent, name)
                    with os.fdopen(source, 'rb') as stream:
                        for data in iter(lambda: stream.read(CHUNK), b''):
                            total += len(data)
                            if total > MAX_DOWNLOAD: raise ValueError('download_limit_256_MiB')
                            output.write(data)
                    filename = path.name
                else: raise ValueError('regular_file_or_directory_required')
            finally: os.close(parent)
            output.flush(); os.fsync(output.fileno())
        source = regular_fd(spool_fd, ticket)
        with os.fdopen(source, 'rb') as stream:
            size = os.fstat(stream.fileno()).st_size
            if size > MAX_DOWNLOAD: raise ValueError('download_archive_exceeds_256_MiB')
            digest = hashlib.sha256()
            for data in iter(lambda: stream.read(CHUNK), b''): digest.update(data)
        return {'ticket': ticket, 'filename': filename, 'size': size, 'sha256': digest.hexdigest(), 'skipped': skipped}
    except Exception:
        os.unlink(ticket, dir_fd=spool_fd); raise


def dispatch(policy_root, request, local_api=None):
    target = request.get('target')
    if target == 'operator':
        return local_request(Path.home(), Path.home()/'.cache/engram/remote-downloads', request)
    if target != 'robot': raise ValueError('invalid_file_target')
    local=local_api
    if local is not None:
        # The launcher alone resolves the active robot and owns its SSH credentials.
        if local.get('url')!='http://127.0.0.1:11452/api/launcher/remote-robot-files':raise ValueError('invalid_local_launcher_endpoint')
        fd=os.open(local['token_file'],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd) as stream:
            info=os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o777!=0o600 or info.st_nlink!=1 or info.st_size>256:raise ValueError('invalid_local_launcher_credential')
            token=stream.read(256).strip()
        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self,*_args):return None
        outgoing=Request(local['url'],data=json.dumps(request).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+token},method='POST')
        try:
            with build_opener(ProxyHandler({}),NoRedirect()).open(outgoing,timeout=105) as response:
                raw=response.read(250001)
            if len(raw)>250000:raise ValueError('local_launcher_response_too_large')
            result=json.loads(raw)
            if not isinstance(result,dict) or result.get('error'):raise ValueError('invalid_local_launcher_result')
            return result
        except OSError:raise ValueError('DAQ当前机器人未连接或文件连接失败，请在启动页确认机器人连接')
    # Existing enrolled SSH peer, not an arbitrary browser-provided host or command.
    from robot_peer import peer_config
    import shlex
    peer = peer_config(policy_root)
    def scope_for(ticket):
        identity=[peer['host'],peer['username'],peer['remote_root'],ticket]
        return hmac.new(_PEER_SCOPE_SECRET,json.dumps(identity,separators=(',',':')).encode(),hashlib.sha256).hexdigest()
    request=dict(request)
    if request['action'] in {'chunk','upload_chunk','upload_finish','upload_abort'}:
        matched=re.fullmatch(r'r1\.([a-f0-9]{64})\.([a-f0-9]{32})',request.get('ticket',''))
        if not matched or not hmac.compare_digest(matched[1],scope_for(matched[2])):raise ValueError('robot_identity_changed_restart_transfer')
        request['ticket']=matched[2]
    argv = ['/usr/bin/ssh','-T','-i',peer['ssh_key'],'-o','BatchMode=yes','-o','IdentitiesOnly=yes',
            '-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile='+peer['known_hosts'],'-o','ConnectTimeout=5',
            peer['username']+'@'+peer['host'],shlex.join(['/usr/bin/python3',peer['remote_root']+'/file_browser.py','--local'])]
    process = subprocess.run(argv, input=json.dumps(request).encode(), capture_output=True, timeout=90,
                             env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'})
    if process.returncode or len(process.stdout) > 250000: raise ValueError('robot_file_connection_failed')
    result = json.loads(process.stdout)
    if not isinstance(result,dict): raise ValueError('invalid_robot_file_result')
    if result.get('error'): raise ValueError(result['error'])
    if result.get('username')!=peer['username']:raise ValueError('remote_account_mismatch')
    if 'ticket' in result:
        if not isinstance(result['ticket'],str) or not re.fullmatch(r'[a-f0-9]{32}',result['ticket']):raise ValueError('invalid_robot_transfer_ticket')
        result['ticket']='r1.'+scope_for(result['ticket'])+'.'+result['ticket']
    return result


if __name__ == '__main__':
    try:
        raw=sys.stdin.buffer.read(256*1024+1)
        if len(raw)>256*1024:raise ValueError('file_request_too_large')
        request=json.loads(raw)
        result=local_request(Path.home(),Path.home()/'.cache/engram/remote-downloads',request)
        result['username']=getpass.getuser()
    except Exception as error:
        result={'error':str(error)[:160]}
    print(json.dumps(result,ensure_ascii=False))
