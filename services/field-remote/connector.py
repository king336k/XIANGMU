#!/usr/bin/env python3
"""Outbound-only Linux operator connector. Python standard library only."""

import argparse
import base64
import binascii
from concurrent.futures import ThreadPoolExecutor
import errno
import fcntl
import getpass
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import re
import select
import signal
import socket
import stat
import struct
import subprocess
import termios
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

MAX_FILE = 128 * 1024
MAX_OUTPUT = 64 * 1024
MAX_PENDING = 512 * 1024
TOKEN_ENV = 'FIELD_REMOTE_TOKEN'
# Transient process generation, separate from the persistent machine identity.
EXECUTOR_INSTANCE = uuid.uuid4().hex


def safe_environment(preserve_sim=False):
    # Tools and the human PTY must never inherit the enrollment secret.
    return {key: value for key, value in os.environ.items()
            if (preserve_sim and key == 'FIELD_SIM_TOKEN') or
            not any(word in key.upper() for word in ('TOKEN', 'SECRET', 'PASSWORD', 'API_KEY'))}


class Policy:
    def __init__(self, config):
        self.file_browser_enabled = config.get('file_browser_enabled') is True
        self.daq_local_api = config.get('daq_local_api')
        self.root = Path(config['approved_root']).resolve(strict=True)
        if not self.root.is_dir() or str(self.root) == '/':
            raise ValueError('approved_root must be an existing dedicated directory')
        self.allowed = config.get('allowed_commands', [])
        if not isinstance(self.allowed, list) or any(
            not isinstance(prefix, list) or not prefix or
            any(not isinstance(arg, str) or not arg for arg in prefix)
            for prefix in self.allowed
        ):
            raise ValueError('allowed_commands must contain argv prefixes')
        self.editable_files = config.get('editable_files', [])
        if not isinstance(self.editable_files, list) or any(not isinstance(path, str) for path in self.editable_files):
            raise ValueError('editable_files must be an explicit list of relative configuration files')
        for path in self.editable_files:
            self.parts(path)
            if Path(path).suffix.lower() in ('.py', '.pyc', '.sh', '.bash', '.js', '.mjs', '.so', '.exe'):
                raise ValueError('editable_files cannot include executable code')

    def parts(self, relative):
        if not isinstance(relative, str) or not relative or '\x00' in relative:
            raise ValueError('relative path required')
        parts = relative.split('/')
        if relative.startswith('/') or any(part in ('', '.', '..') for part in parts):
            raise ValueError('path must remain below approved_root')
        for part in parts:
            lower = part.lower()
            if (lower.startswith(('.env', '.field-')) or lower in ('.ssh', '.aws', '.git', 'id_rsa', 'id_ed25519')
                    or any(word in lower for word in ('secret', 'credential', 'password', 'token'))
                    or lower.endswith(('.pem', '.key', '.p12', '.pfx'))):
                raise ValueError('secret paths are not available to file tools')
        return parts

    def parent_fd(self, relative):
        parts = self.parts(relative)
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in parts[:-1]:
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = next_fd
            return fd, parts[-1]
        except OSError as exc:
            os.close(fd)
            raise ValueError('symlink or inaccessible parent path') from exc

    def read(self, relative):
        parent, name = self.parent_fd(relative)
        try:
            try:
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            except OSError as exc:
                raise ValueError('file is inaccessible or a symlink') from exc
            with os.fdopen(fd, 'rb') as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_FILE:
                    raise ValueError('only bounded regular files without hardlinks are permitted')
                data = stream.read(MAX_FILE + 1)
            if len(data) > MAX_FILE:
                raise ValueError('file too large')
            return data
        finally:
            os.close(parent)

    def patch(self, relative, expected_sha256, content):
        if relative not in self.editable_files:
            raise ValueError('patch target is not in the local editable_files allowlist')
        if not isinstance(content, str) or len(content.encode()) > MAX_FILE:
            raise ValueError('patch content must be bounded UTF-8 text')
        old = self.read(relative)
        if hashlib.sha256(old).hexdigest() != expected_sha256:
            raise ValueError('SHA256 conflict; read the current file before patching')
        parent, name = self.parent_fd(relative)
        suffix = uuid.uuid4().hex
        backup, temporary = f'{name}.backup-{suffix}', f'.field-patch-{suffix}'
        try:
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
            # Read again through the anchored directory before replacing.
            if self.read(relative) != old:
                raise ValueError('file changed during patch')
            for filename, data in ((backup, old), (temporary, content.encode())):
                fd = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=parent)
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
            os.chmod(temporary, stat.S_IMODE(info.st_mode) & 0o777, dir_fd=parent)
            os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
            os.fsync(parent)
        finally:
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass
            os.close(parent)
        backup_path = '/'.join(relative.split('/')[:-1] + [backup])
        return {'sha256': hashlib.sha256(content.encode()).hexdigest(), 'backup': backup_path}

    def cwd(self, relative):
        if relative in ('', '.'):
            return self.root
        self.parts(relative)
        path = self.root / relative
        if path.resolve(strict=True) != path or not path.is_dir():
            raise ValueError('cwd must be a directory without symlinks')
        return path

    def argv(self, argv):
        if (not isinstance(argv, list) or not argv or len(argv) > 64
                or any(not isinstance(arg, str) or '\x00' in arg or len(arg) > MAX_FILE for arg in argv)):
            raise ValueError('bounded argv list required')
        if argv[0]=='daq-local-diagnostics-v1':
            repair = len(argv)==3 and argv[1]=='repair' and re.fullmatch(r'[a-f0-9]{64}',argv[2])
            if (argv not in (['daq-local-diagnostics-v1','inspect'],['daq-local-diagnostics-v1','verify'])
                    and not repair) or self.daq_local_api is None:
                raise ValueError('only exact local diagnostic operations with a snapshot are permitted')
            return argv
        if not any(argv[:len(prefix)] == prefix for prefix in self.allowed):
            raise ValueError('command prefix is not approved locally')
        if '--remote' in argv or any(arg.startswith('--remote=') for arg in argv):
            raise ValueError('remote helper mode is unavailable to autonomous tools')
        for index, arg in enumerate(argv):
            if arg == '--root':
                if index + 1 >= len(argv) or argv[index + 1] != str(self.root):
                    raise ValueError('tool --root must equal the approved_root')
            elif arg.startswith('--root=') and arg != '--root=' + str(self.root):
                raise ValueError('tool --root must equal the approved_root')
        executable = Path(argv[0])
        if not executable.is_absolute() or not executable.is_file():
            raise ValueError('approved executable must be absolute')
        if executable.name in ('sh', 'bash', 'dash', 'zsh', 'fish', 'sudo', 'su', 'env', 'ssh'):
            raise ValueError('shells and privilege/remote launchers are not tool commands')
        if any('..' in arg.split('=', 1)[-1].split('/') for arg in argv[1:]):
            raise ValueError('parent traversal in tool arguments is forbidden')
        for arg in argv[1:]:
            value = arg.split('=', 1)[-1]
            if value.startswith('/') and not Path(value).resolve().is_relative_to(self.root):
                raise ValueError('absolute tool path arguments must remain under approved_root')
        if executable.name.startswith(('python', 'node', 'perl', 'ruby')):
            if len(argv) < 2 or argv[1].startswith('-'):
                raise ValueError('interpreters require a locally approved script')
            script = Path(argv[1])
            if not script.is_absolute():
                script = self.root / script
            if not script.resolve().is_relative_to(self.root):
                raise ValueError('script must be under approved_root')
            if not any(len(prefix) >= 2 and prefix[:2] == argv[:2] for prefix in self.allowed):
                raise ValueError('script itself must be approved')
            if script.name == 'robot_peer.py':
                if len(argv) < 5 or argv[2] not in ('inspect', 'repair', 'verify'):
                    raise ValueError('fixed robot_peer operation required')
                expected = argv[:3] + ['--root', str(self.root)]
                if argv[2] == 'repair':
                    if (len(argv) != 7 or argv[5] != '--expected-sha256'
                            or not re.fullmatch('[a-f0-9]{64}', argv[6])):
                        raise ValueError('repair only accepts a SHA256 after the fixed root')
                    expected += ['--expected-sha256', argv[6]]
                if argv != expected:
                    raise ValueError('robot_peer argv must match the fixed operation/root contract')
            elif script.name == 'collector_sim.py':
                if (len(argv) < 3 or argv[2] not in ('inspect', 'verify')
                        or argv[3:] not in ([], ['--root', str(self.root)])):
                    raise ValueError('collector argv must match its fixed operation/root contract')
        return argv


def kill_group(process):
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def run_command(policy, argv, cwd, timeout, max_output=MAX_OUTPUT, stopping=None, expected_target_revision=None,
                configuration_target=None, expected_configuration_revision=None, configuration_approval=None):
    argv = policy.argv(argv)
    if configuration_approval is not None and argv[:2] != ['daq-local-diagnostics-v1', 'repair']:
        raise ValueError('configuration_approval_requires_fixed_repair')
    if argv[0]=='daq-local-diagnostics-v1':
        from file_browser import local_launcher_request
        payload={'action':argv[1]}
        if configuration_target is not None:
            if not isinstance(configuration_target,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',configuration_target):
                raise ValueError('invalid_configuration_target')
            payload['configuration_target']=configuration_target
        if argv[1]=='repair' and configuration_target is not None:
            if not isinstance(expected_configuration_revision,str) or not re.fullmatch(r'[a-f0-9]{64}',expected_configuration_revision):
                raise ValueError('configuration_target_revision_required')
            payload.update(expected_sha256=argv[2],expected_configuration_revision=expected_configuration_revision)
        elif argv[1]=='repair':
            from file_browser import robot_status
            current=robot_status(policy.daq_local_api)
            if (not isinstance(expected_target_revision,str) or not re.fullmatch(r'[a-f0-9]{64}',expected_target_revision)
                    or current.get('connected') is not True or current.get('target_revision')!=expected_target_revision):
                raise ValueError('robot target changed; configuration repair was not executed')
            payload.update(expected_sha256=argv[2],expected_target_revision=expected_target_revision)
        if configuration_approval is not None:
            if argv[1] != 'repair' or not isinstance(configuration_approval, dict):
                raise ValueError('configuration_approval_requires_fixed_repair')
            payload['configuration_approval'] = configuration_approval
        response=local_launcher_request(policy.daq_local_api,payload,diagnostics=True)
        if argv[1]=='repair':
            state=response.get('configuration',{}).get('repair',{}).get('state')
            ok=state in {'applied','not_needed'}
        else:
            ok=response.get('ok') is not False if argv[1]=='inspect' else response.get('verified') is True
        output=json.dumps(response,ensure_ascii=False)
        if len(output.encode())>max_output:raise ValueError('local diagnostics response too large')
        result={'ok':ok,'stdout':output,'stderr':'','exit_code':0 if ok else 1,'timed_out':False,'truncated':False}
        if isinstance(response.get('changes'),list):result['changes']=response['changes']
        return result
    timeout = float(timeout)
    if not math.isfinite(timeout) or not 0 < timeout <= 60:
        raise ValueError('timeout must be between 0 and 60 seconds')
    process = subprocess.Popen(argv, cwd=policy.cwd(cwd), stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=True, env=safe_environment(preserve_sim=True))
    streams = {process.stdout: bytearray(), process.stderr: bytearray()}
    for stream in streams:
        os.set_blocking(stream.fileno(), False)
    deadline, timed_out, truncated = time.monotonic() + timeout, False, False
    try:
        active = list(streams)
        while active:
            if time.monotonic() >= deadline or (stopping and stopping.is_set()):
                timed_out = True
                break
            ready, _, _ = select.select(active, [], [], min(0.05, max(0, deadline - time.monotonic())))
            for stream in ready:
                chunk = os.read(stream.fileno(), 8192)
                if not chunk:
                    active.remove(stream)
                    continue
                available = max_output - len(streams[stream])
                streams[stream].extend(chunk[:available])
                truncated |= len(chunk) > available
        if process.poll() is None or timed_out:
            # A child holding pipes must not survive a tool call.
            kill_group(process)
        else:
            process.wait()
    finally:
        kill_group(process)
        process.stdout.close()
        process.stderr.close()
    return {'stdout': streams[process.stdout].decode('utf-8', errors='replace'),
            'stderr': streams[process.stderr].decode('utf-8', errors='replace'),
            'exit_code': process.returncode, 'timed_out': timed_out, 'truncated': truncated,
            'ok': process.returncode == 0 and not timed_out}


class Terminal:
    def __init__(self, root, cols, rows, host_ip=None):
        if type(cols) is not int or type(rows) is not int or not 1 <= cols <= 500 or not 1 <= rows <= 200:
            raise ValueError('invalid terminal dimensions')
        self.master, slave = os.openpty()
        self.resize(cols, rows)
        # A fresh Python interpreter sets up its controlling terminal; no unsafe
        # preexec_fn is run in this client's worker-thread process.
        helper = ('import os,fcntl,termios; os.setsid(); '
                  'fcntl.ioctl(0,termios.TIOCSCTTY,0); '
                  'os.execv("/bin/bash",["/bin/bash","--noprofile","--norc","-i"])')
        terminal_env = safe_environment()
        prompt_host = r'\h'
        if host_ip:
            import ipaddress
            prompt_host = str(ipaddress.ip_address(host_ip))
        terminal_env.update({
            'TERM': 'xterm-256color',
            'COLORTERM': 'truecolor',
            'PS1': r'\[\033[1;32m\]\u@' + prompt_host + r'\[\033[0m\]:\[\033[1;34m\]\w\[\033[0m\]\$ ',
        })
        self.process = subprocess.Popen(['/usr/bin/python3', '-c', helper], stdin=slave,
                                        stdout=slave, stderr=slave, cwd=root, env=terminal_env)
        os.close(slave)
        self.pid = self.process.pid
        os.set_blocking(self.master, False)
        self.created = self.active = time.monotonic()

    def resize(self, cols, rows):
        if type(cols) is not int or type(rows) is not int or not 1 <= cols <= 500 or not 1 <= rows <= 200:
            raise ValueError('invalid terminal dimensions')
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))

    def close(self):
        # The child can still be between Popen and setsid on an immediate close.
        try:
            os.killpg(self.pid, signal.SIGKILL)
        except ProcessLookupError:
            self.process.kill()
        self.process.wait()
        os.close(self.master)


class RobotTerminal:
    def __init__(self,local,sid,revision,cols,rows):
        if not isinstance(revision,str) or not re.fullmatch(r'[a-f0-9]{64}',revision):
            raise ValueError('robot_target_revision_required')
        self.local=local;self.sid=sid;self.revision=revision;self.cursor=0
        self.created=self.active=time.monotonic()
        self.snapshot=self.call('open',cols=cols,rows=rows)

    def call(self,action,**values):
        from file_browser import local_launcher_request
        return local_launcher_request(self.local,{'action':action,'session_id':self.sid,
            'expected_target_revision':self.revision,**values},terminal=True)

    def resize(self,cols,rows):self.call('resize',cols=cols,rows=rows)

    def send(self,data):self.call('input',data=base64.b64encode(data).decode())

    def read(self):
        result=self.call('read',after=self.cursor)
        events=result.get('events')
        if not isinstance(events,list) or len(events)>100:raise ValueError('invalid_robot_terminal_events')
        cursor=result.get('cursor')
        if type(cursor) is not int or cursor<self.cursor:raise ValueError('invalid_robot_terminal_cursor')
        for event in events:
            if not isinstance(event,dict) or not isinstance(event.get('id'),str) or event.get('kind') not in ('data','exit'):
                raise ValueError('invalid_robot_terminal_event')
            if event['kind']=='data' and len(base64.b64decode(event.get('data',''),validate=True))>65536:
                raise ValueError('robot_terminal_output_too_large')
            if event['kind']=='exit' and type(event.get('code')) is not int:raise ValueError('invalid_robot_exit')
        self.cursor=cursor
        return events

    def close(self):
        try:self.call('close')
        except (ValueError,OSError):pass


class Engine:
    def __init__(self, policy, host_ip=None):
        self.policy, self.terminals = policy, {}
        self.host_ip = host_ip
        self.results, self.outputs, self.seen, self.tasks = [], [], {}, {}
        self.cache, self.closed_sessions = {}, set()
        self.stopping = threading.Event()
        lock_path = policy.root / '.field-remote.lock'
        self.lock_fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(self.lock_fd)
            raise ValueError('another connector owns this approved_root')
        self.journal_path = policy.root / '.field-remote-state.json'
        try:
            info = self.journal_path.lstat()
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.getuid():
                raise ValueError('unsafe dedup journal permissions')
            journal = json.loads(self.journal_path.read_text())
            for key, entry in journal.items():
                if entry['expires_at'] >= time.time():
                    self.seen[key] = entry['expires_at']
                    self.cache[key] = {'id': key, 'ok': entry['ok'], 'recovered': True,
                                       'stdout': '', 'stderr': '', 'exit_code': entry['exit_code']}
        except FileNotFoundError:
            pass
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.last_exchange = time.monotonic()

    def journal(self, command_id, expires_at, result=None):
        """Persist only execution tombstones, never arguments or tool/PTY output."""
        entries = {}
        if self.journal_path.exists():
            entries = json.loads(self.journal_path.read_text())
        entries = {key: entry for key, entry in entries.items() if entry['expires_at'] >= time.time()}
        entries[command_id] = {'expires_at': expires_at, 'ok': bool(result and result.get('ok')),
                               'exit_code': result.get('exit_code', 1) if result else 1}
        temporary = self.journal_path.with_name('.field-state-' + uuid.uuid4().hex)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(entries, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.journal_path)
        directory = os.open(self.policy.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def output(self, event):
        self.outputs.append({'id': str(uuid.uuid4()), **event})

    def acknowledge(self, output_count, result_count):
        for result in self.results[:result_count]:
            cached = self.cache.get(result['id'])
            if cached:
                self.cache[result['id']] = {'id': result['id'], 'ok': cached['ok'],
                                           'exit_code': cached.get('exit_code', 0),
                                           'recovered': True, 'stdout': '', 'stderr': ''}
        del self.outputs[:output_count]
        del self.results[:result_count]

    def accept(self, command):
        if len(self.results) >= 256 or sum(len(json.dumps(item)) for item in self.results) > MAX_PENDING:
            return  # The central queue will retry after the current batch is acknowledged.
        command_id = command.get('id')
        if not isinstance(command_id, str) or not 1 <= len(command_id) <= 128:
            return
        now = time.time()
        self.seen = {key: expiry for key, expiry in self.seen.items() if expiry >= now}
        self.cache = {key: result for key, result in self.cache.items() if key in self.seen}
        if command_id in self.seen:
            if command_id in self.cache:
                self.results.append(self.cache[command_id])
            return
        expiry = command.get('expires_at', 0)
        valid_expiry = isinstance(expiry, (int, float)) and math.isfinite(expiry)
        self.seen[command_id] = max(now + 120, expiry) if valid_expiry else now + 120
        result = {'id': command_id, 'ok': True, 'stdout': '', 'stderr': '', 'exit_code': 0}
        try:
            if not valid_expiry or expiry <= now:
                raise ValueError('command expired')
            if expiry > now + 3600 or len(self.seen) > 10000:
                raise ValueError('command expiry or dedup capacity exceeded')
            kind = command.get('kind')
            if kind.startswith('terminal_'):
                sid = command.get('session_id')
                if not isinstance(sid, str) or not 1 <= len(sid) <= 128:
                    raise ValueError('invalid session_id')
                if kind == 'terminal_open':
                    if (sid in self.closed_sessions or sid in self.terminals or len(self.terminals) >= 2
                            or len(self.closed_sessions) >= 4096):
                        raise ValueError('terminal already open or session limit reached')
                    target=command.get('target','operator')
                    if target=='robot':
                        terminal=RobotTerminal(self.policy.daq_local_api,sid,command.get('target_revision') or command.get('expected_target_revision'),command['cols'],command['rows'])
                        self.terminals[sid]=terminal
                        result.update(identity=terminal.snapshot.get('identity'),target_revision=terminal.revision)
                    elif target=='operator':
                        self.terminals[sid] = Terminal(self.policy.root, command['cols'], command['rows'], self.host_ip)
                    else:raise ValueError('invalid_terminal_target')
                else:
                    terminal = self.terminals[sid]
                    terminal.active = time.monotonic()
                    if kind == 'terminal_input':
                        data = base64.b64decode(command['data'], validate=True)
                        if len(data) > 4096:
                            raise ValueError('terminal input exceeds 4096 bytes')
                        if isinstance(terminal,RobotTerminal):terminal.send(data)
                        else:
                            written = os.write(terminal.master, data)
                            if written != len(data):
                                raise ValueError('terminal input backpressure; input partially written')
                    elif kind == 'terminal_resize':
                        terminal.resize(command['cols'], command['rows'])
                    elif kind == 'terminal_close':
                        terminal.close()
                        del self.terminals[sid]
                        self.closed_sessions.add(sid)
                        self.output({'session_id': sid, 'kind': 'exit', 'code': -signal.SIGKILL})
                    else:
                        raise ValueError('unknown terminal command')
            elif kind == 'file_browser':
                if not self.policy.file_browser_enabled:
                    raise ValueError('file_browser_not_enabled')
                if self.tasks:
                    raise ValueError('one file or tool operation may run at a time')
                from file_browser import dispatch
                self.tasks[command_id] = self.executor.submit(
                    lambda: {'ok': True, 'exit_code': 0, 'file_result': dispatch(self.policy.root, command['request'], self.policy.daq_local_api)})
                return
            elif kind == 'run':
                if self.tasks:
                    raise ValueError('one tool command may run at a time')
                self.policy.argv(command['argv'])
                self.journal(command_id, self.seen[command_id])
                self.tasks[command_id] = self.executor.submit(
                    run_command, self.policy, command['argv'], command.get('cwd', '.'),
                    command.get('timeout', 15), stopping=self.stopping,
                    expected_target_revision=command.get('expected_target_revision'),
                    configuration_target=command.get('configuration_target'),
                    expected_configuration_revision=command.get('expected_configuration_revision'),
                    configuration_approval=command.get('configuration_approval'))
                return
            elif kind == 'read_file':
                data = self.policy.read(command['path'])
                result.update(content=data.decode('utf-8'), sha256=hashlib.sha256(data).hexdigest(),
                              resolved_path=str(self.policy.root / command['path']),
                              target_username=getpass.getuser(),target_ip=self.host_ip,target_kind='collector')
            elif kind == 'patch_file':
                self.journal(command_id, self.seen[command_id])
                patched=self.policy.patch(command['path'], command['expected_sha256'], command['content'])
                backup_data=self.policy.read(patched['backup'])
                actual=self.policy.read(command['path'])
                if hashlib.sha256(actual).hexdigest()!=patched['sha256']:
                    raise ValueError('file changed after patch; read actual state before reporting')
                resolved_path=str(self.policy.root / command['path'])
                backup_path=str(self.policy.root / patched['backup'])
                metadata={'target_username':getpass.getuser(),'target_ip':self.host_ip,'target_kind':'collector'}
                changes=[]
                try:
                    def unique_keys(pairs):
                        value={}
                        for key,item in pairs:
                            if key in value:raise ValueError('ambiguous JSON duplicate key')
                            value[key]=item
                        return value
                    before=json.loads(backup_data,object_pairs_hook=unique_keys)
                    after=json.loads(actual,object_pairs_hook=unique_keys)
                    if isinstance(before,dict) and isinstance(after,dict):
                        # Lazy import avoids module initialization cycles:
                        # robot_peer already reuses this connector's Policy.
                        from robot_peer import config_locations
                        before_locations=config_locations(backup_data,resolved_path,socket.gethostname())
                        after_locations=config_locations(actual,resolved_path,socket.gethostname())
                        for key in sorted(set(before)|set(after)):
                            if (key in before and key in after and
                                    json.dumps(before[key],sort_keys=True)==json.dumps(after[key],sort_keys=True)):
                                continue
                            changes.append({**metadata,'path':resolved_path,'key':key,'before':before.get(key),
                                'after':after.get(key),'before_exists':key in before,'after_exists':key in after,
                                'before_line':before_locations[key]['line'] if key in before_locations else None,
                                'after_line':after_locations[key]['line'] if key in after_locations else None,
                                'backup':backup_path,'before_sha256':hashlib.sha256(backup_data).hexdigest(),
                                'after_sha256':patched['sha256']})
                except (ValueError,UnicodeDecodeError):pass
                result.update(**metadata,sha256=patched['sha256'],resolved_path=resolved_path,
                              backup=backup_path,changes=changes)
            else:
                raise ValueError('unknown command kind')
        except (ValueError, OSError, KeyError, TypeError, AttributeError, binascii.Error) as exc:
            result.update(ok=False, stderr=str(exc)[:512], exit_code=1)
        self.cache[command_id] = result
        if command.get('kind') == 'patch_file':
            self.journal(command_id, self.seen[command_id], result)
        self.results.append(result)

    def pump(self):
        for command_id, future in list(self.tasks.items()):
            if future.done():
                try:
                    result = future.result()
                except (ValueError, OSError) as exc:
                    result = {'ok': False, 'stderr': str(exc)[:512], 'stdout': '', 'exit_code': 1}
                cached = {'id': command_id, **result}
                self.cache[command_id] = cached
                self.journal(command_id, self.seen[command_id], cached)
                self.results.append(cached)
                del self.tasks[command_id]
        pending = sum(len(event.get('data', '')) for event in self.outputs)
        for sid, terminal in list(self.terminals.items()):
            if (time.monotonic() - terminal.active > 300 or time.monotonic() - terminal.created > 3600
                    or time.monotonic() - self.last_exchange > 30):
                terminal.close()
                del self.terminals[sid]
                self.closed_sessions.add(sid)
                self.output({'session_id': sid, 'kind': 'exit', 'code': -signal.SIGKILL})
                continue
            if pending < MAX_PENDING:
                if isinstance(terminal,RobotTerminal):
                    try:
                        events=terminal.read()
                        for event in events:
                            if event.get('kind') not in ('data','exit'):raise ValueError('invalid_robot_terminal_event')
                            self.output({**event,'session_id':sid})
                            pending+=len(event.get('data',''))
                        if any(event['kind']=='exit' for event in events):
                            terminal.close();del self.terminals[sid];self.closed_sessions.add(sid)
                    except (ValueError,OSError,KeyError,TypeError):
                        terminal.close();del self.terminals[sid];self.closed_sessions.add(sid)
                        self.output({'session_id':sid,'kind':'exit','code':-signal.SIGKILL})
                    continue
                chunks = []
                remaining = min(65536, (MAX_PENDING - pending) * 3 // 4)
                eof = False
                while remaining > 0:
                    try:
                        chunk = os.read(terminal.master, min(8192, remaining))
                    except OSError as exc:
                        if exc.errno not in (errno.EAGAIN, errno.EIO):
                            raise
                        eof = exc.errno == errno.EIO
                        break
                    if not chunk:
                        eof = True
                        break
                    chunks.append(chunk)
                    remaining -= len(chunk)
                data = b''.join(chunks) if chunks else b'' if eof else None

                if data:
                    encoded = base64.b64encode(data).decode()
                    self.output({'session_id': sid, 'kind': 'data', 'data': encoded})
                    pending += len(encoded)
                elif data == b'' and terminal.process.poll() is not None:
                    code = terminal.process.returncode
                    terminal.close()
                    del self.terminals[sid]
                    self.closed_sessions.add(sid)
                    self.output({'session_id': sid, 'kind': 'exit', 'code': code})

    def close(self):
        self.stopping.set()
        for terminal in self.terminals.values():
            terminal.close()
        self.terminals.clear()
        self.executor.shutdown(wait=True, cancel_futures=True)
        if self.lock_fd is not None:
            os.close(self.lock_fd)
            self.lock_fd = None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('exchange redirects are forbidden')


def routed_host_ip(server_url):
    """Ask the kernel for the configured server route's source; send no payload."""
    if not server_url:
        return None
    import ipaddress
    try:
        server = urllib.parse.urlsplit(server_url)
        port = server.port or (443 if server.scheme == 'https' else 80)
        addresses = socket.getaddrinfo(server.hostname, port, type=socket.SOCK_DGRAM)
        for family, kind, protocol, _canonical, destination in addresses:
            try:
                with socket.socket(family, kind, protocol) as route:
                    route.connect(destination)
                    address = ipaddress.ip_address(route.getsockname()[0])
                    if not address.is_unspecified and not address.is_multicast:
                        return str(address)
            except OSError:
                continue
    except (OSError, ValueError, TypeError):
        pass
    return None


def diagnostic_capability(local):
    """Only advertise the fixed adapter actually present in the running DAQ."""
    if local is None:return None
    from file_browser import local_launcher_request
    try:
        result=local_launcher_request(local,{'action':'inspect'},diagnostics=True,timeout=3)
        capability=result.get('capabilities',{})
        if (isinstance(capability,dict) and capability.get('protocol')=='daq-configuration-v1'
                and capability.get('semantic_validation') is True
                and capability.get('supported_repairs')==['restore_invalid_initial_joint_states']):
            observed = {'protocol':'daq-configuration-v1','ready':True}
            if capability.get('approval_protocol') == 'robot-config-repair-approval-v1':
                observed['approval_protocol'] = capability['approval_protocol']
            return observed
    except (OSError, ValueError, TypeError):
        pass
    return None


def identity(policy=None, server_url=None):
    try:
        boot_id = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    except OSError:
        boot_id = str(uuid.uuid4())
    result = {'username': getpass.getuser(), 'hostname': socket.gethostname(), 'boot_id': boot_id,
              'host_ip': routed_host_ip(server_url)}
    if policy is not None:
        # Observed local capabilities only. Server-owned enrollment context remains
        # authoritative; these device claims cannot grant tools or root access.
        result['capabilities'] = {
            'network': {'ip_address': result['host_ip']},
            'terminal': {'ready': Path('/bin/bash').is_file() and Path('/usr/bin/python3').is_file(),
                         'backend': 'host-pty', 'max_sessions': 2, 'max_input_bytes': 4096,
                         'executor_instance': EXECUTOR_INSTANCE},
            'file_browser': {'ready': policy.file_browser_enabled, 'read_only': True, 'max_bytes': 256 * 1024 * 1024},
            'tools': {'ready': bool(policy.allowed), 'approved_root': str(policy.root),
                      'allowed_commands': policy.allowed, 'file_patch': True,
                      'specialists_probed': False},
        }
        from file_browser import robot_status, application_status
        result['capabilities']['robot']=robot_status(policy.daq_local_api)
        application=application_status(policy.daq_local_api)
        if application is not None:result['capabilities']['application']=application
        diagnostic=diagnostic_capability(policy.daq_local_api)
        if diagnostic:result['capabilities']['diagnostics']=diagnostic
        try:
            peer = json.loads((policy.root / 'robot-peer.json').read_text())
            username = peer.get('username', '')
            host = peer.get('host', '')
            if isinstance(username, str) and isinstance(host, str):
                result['capabilities']['simulation_robot'] = {'username': username[:120], 'host': host[:120], 'via': 'operator'}
                if policy.daq_local_api is None:
                    result['capabilities']['robot'].update(username=username[:120],host=host[:120],via='simulation')
        except (OSError, ValueError, TypeError, AttributeError):
            pass
    return result


class PersistentExchangeOpener:
    """Reuse only the validated single platform origin; never follow redirects."""
    def __init__(self):
        self.connection = None
        self.origin = None

    def open(self, request, timeout=5):
        parsed = urllib.parse.urlsplit(request.full_url)
        origin = (parsed.scheme, parsed.hostname, parsed.port)
        if self.origin is not None and self.origin != origin:
            raise ValueError('exchange origin changed')
        self.origin = origin
        if self.connection is None:
            connection_type = http.client.HTTPSConnection if parsed.scheme == 'https' else http.client.HTTPConnection
            self.connection = connection_type(parsed.hostname, parsed.port, timeout=timeout)
        try:
            self.connection.request(request.get_method(), urllib.parse.urlunsplit(('', '', parsed.path, parsed.query, '')),
                body=request.data, headers=dict(request.header_items()))
            response = self.connection.getresponse()
            if response.status != 200:
                response.close(); self.close()
                raise ValueError('exchange rejected')
            return response
        except (OSError, http.client.HTTPException):
            self.close()
            raise urllib.error.URLError('exchange transport interrupted')

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None


def exchange(opener, url, token, payload):
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), method='POST',
                                     headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    with opener.open(request, timeout=5) as response:
        data = response.read(1024 * 1024 + 1)
    if len(data) > 1024 * 1024:
        raise ValueError('exchange response too large')
    decoded = json.loads(data)
    if not isinstance(decoded, dict) or not isinstance(decoded.get('commands'), list) or len(decoded['commands']) > 100:
        raise ValueError('invalid exchange response')
    return decoded


def validate_server(url, allow_private_http=False, allow_insecure_public_http=False):
    server = urllib.parse.urlsplit(url)
    if (not server.hostname or server.username or server.password or server.query or server.fragment):
        raise ValueError('server URL requires a host and must not contain credentials, query or fragment')
    if server.scheme == 'https':
        return
    if server.scheme != 'http':
        raise ValueError('server must use HTTPS, or explicitly authorized HTTP')
    import ipaddress
    try:
        address = ipaddress.ip_address(server.hostname)
    except ValueError as exc:
        raise ValueError('HTTP requires a literal IP address') from exc
    if address.is_unspecified or address.is_multicast:
        raise ValueError('HTTP server address cannot be unspecified or multicast')
    if allow_private_http and address.is_private:
        return
    if allow_insecure_public_http and address.is_global and not address.is_loopback:
        return
    raise ValueError('use HTTPS; private LAN HTTP and insecure public HTTP each require their explicit flag')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server', required=True)
    parser.add_argument('--policy', required=True)
    parser.add_argument('--allow-http-private-lan', '--allow-http', action='store_true', help='explicitly permit trusted LAN HTTP')
    parser.add_argument('--allow-insecure-public-http', action='store_true',
                        help='TEST ONLY: permit plaintext HTTP to a literal public IP; token and terminal traffic are unencrypted')
    args = parser.parse_args()
    if os.geteuid() == 0:
        parser.error('run as the authorized unprivileged operator user, never root')
    try:
        validate_server(args.server, args.allow_http_private_lan, args.allow_insecure_public_http)
    except ValueError as exc:
        parser.error(str(exc))
    token = os.environ.pop(TOKEN_ENV, None) or getpass.getpass('Remote enrollment token: ')
    if not token.startswith('rw_') or len(token) < 12 or any(c.isspace() for c in token):
        parser.error('invalid enrollment token')
    policy = Policy(json.loads(Path(args.policy).read_text()))
    operator = identity(policy, args.server)
    engine = Engine(policy, operator['host_ip'])
    opener = PersistentExchangeOpener()
    url = args.server.rstrip('/') + '/api/quality-auth/remote-diagnostics/exchange/'
    def stop(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    stream = None
    next_stream_retry = 0.0
    last_stream_heartbeat = 0.0
    next_robot_refresh=0.0
    robot_refresh = None
    next_diagnostic_refresh=0.0
    diagnostic_refresh=None
    next_application_refresh=0.0
    application_refresh=None
    next_cache_cleanup=0.0
    cache_cleanup=None
    status_executor = ThreadPoolExecutor(max_workers=1)
    try:
        while True:
            if cache_cleanup is not None and cache_cleanup.done():
                try:cache_cleanup.result()
                except (OSError,ValueError):pass
                cache_cleanup=None
            if cache_cleanup is None and not engine.tasks and time.monotonic()>=next_cache_cleanup:
                from file_browser import cleanup_expired_transfers
                cache_cleanup=status_executor.submit(cleanup_expired_transfers,Path.home())
                next_cache_cleanup=time.monotonic()+60
            if application_refresh is not None and application_refresh.done():
                application=application_refresh.result()
                if application is not None:
                    previous=operator['capabilities'].get('application',{})
                    for key in ('version','revision'):
                        if application.get(key) is None:application[key]=previous.get(key)
                    operator['capabilities']['application']=application
                application_refresh=None
            if policy.daq_local_api is not None and application_refresh is None and time.monotonic()>=next_application_refresh:
                from file_browser import application_status
                application_refresh=status_executor.submit(application_status,policy.daq_local_api)
                next_application_refresh=time.monotonic()+5
            if robot_refresh is not None and robot_refresh.done():
                operator['capabilities']['robot'] = robot_refresh.result()
                robot_refresh = None
            if policy.daq_local_api is not None and robot_refresh is None and time.monotonic() >= next_robot_refresh:
                from file_browser import robot_status
                robot_refresh = status_executor.submit(robot_status, policy.daq_local_api)
                next_robot_refresh = time.monotonic() + 3
            if diagnostic_refresh is not None and diagnostic_refresh.done():
                diagnostic=diagnostic_refresh.result()
                if diagnostic:operator['capabilities']['diagnostics']=diagnostic
                else:operator['capabilities'].pop('diagnostics',None)
                diagnostic_refresh=None
            if policy.daq_local_api is not None and diagnostic_refresh is None and time.monotonic()>=next_diagnostic_refresh:
                diagnostic_refresh=status_executor.submit(diagnostic_capability,policy.daq_local_api)
                next_diagnostic_refresh=time.monotonic()+30
            if stream is None and time.monotonic()>=next_stream_retry:
                try:
                    from station_stream import StationStream
                    stream=StationStream(args.server,token)
                    operator["capabilities"]["terminal"]["transport"]="websocket"
                    operator["capabilities"]["terminal"]["transport_version"]="stream-20261119-r3"
                    operator["capabilities"]["terminal"].pop("transport_error", None)
                    last_stream_heartbeat=0
                except (ImportError,OSError,ValueError,RuntimeError):
                    stream=None
                next_stream_retry=time.monotonic()+30
            engine.pump()
            outputs, results = engine.outputs[:100], engine.results[:100]
            if stream is not None:
                try:
                    stream.poll(engine)
                    engine.pump()
                    operator["capabilities"]["terminal"]["transport_rtt_ms"] = stream.last_roundtrip_ms
                    outputs, results = engine.outputs[:100], engine.results[:100]
                    if outputs or results or time.monotonic()-last_stream_heartbeat>=3:
                        if stream.send(operator,outputs,results):last_stream_heartbeat=time.monotonic()
                    time.sleep(.01 if engine.terminals else .05)
                    continue
                except (OSError,ValueError) as error:
                    operator["capabilities"]["terminal"]["transport_error"]=str(error)[:80]
                    stream.close();stream=None;next_stream_retry=time.monotonic()+30
                    operator["capabilities"]["terminal"]["transport"]="http"
            try:
                response = exchange(opener, url, token, {'identity': operator, 'outputs': outputs, 'results': results})
                engine.acknowledge(len(outputs), len(results))
                engine.last_exchange = time.monotonic()
                for command in response['commands']:
                    if isinstance(command, dict):engine.accept(command)
            except (urllib.error.URLError, OSError, ValueError):
                pass
            time.sleep(0 if engine.outputs or engine.results else 0.05 if engine.terminals else 0.15)
    except KeyboardInterrupt:
        pass
    finally:
        if stream is not None:stream.close()
        status_executor.shutdown(wait=False, cancel_futures=True)
        opener.close()
        engine.close()


if __name__ == '__main__':
    main()
