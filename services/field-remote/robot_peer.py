#!/usr/bin/env python3
"""Fixed 195 -> SSH 177 simulation inspection/repair; no arbitrary remote command."""

import argparse
import difflib
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

from connector import Policy, kill_group, safe_environment
import collector_sim

FLAGS = ('telemetry_enabled', 'accept_commands', 'hardware_required')


def config_locations(raw, path, hostname):
    """Locate parsed top-level keys in the exact bytes read, including escaped keys."""
    text = raw.decode('utf-8')
    decoder = json.JSONDecoder()
    index = len(text) - len(text.lstrip())
    if text[index:index+1] != '{':
        raise ValueError('robot config must be a JSON object')
    index += 1
    locations = {}
    while True:
        while index < len(text) and text[index].isspace(): index += 1
        if text[index:index+1] == '}': break
        start = index
        key, index = decoder.raw_decode(text, index)
        while index < len(text) and text[index].isspace(): index += 1
        if text[index:index+1] != ':': raise ValueError('invalid robot config key')
        index += 1
        while index < len(text) and text[index].isspace(): index += 1
        value, index = decoder.raw_decode(text, index)
        if key in locations: raise ValueError('duplicate robot config key has ambiguous line evidence')
        locations[key] = {'hostname': hostname, 'path': str(path),
                          'line': text.count('\n', 0, start) + 1, 'value': value}
        while index < len(text) and text[index].isspace(): index += 1
        if text[index:index+1] == '}': break
        if text[index:index+1] != ',': raise ValueError('invalid robot config separator')
        index += 1
    return locations


def robot_config(root):
    policy = Policy({'approved_root': str(root), 'editable_files': ['robot-config.json']})
    raw = policy.read('robot-config.json')
    if len(raw) > 8192:
        raise ValueError('simulation config too large')
    config = json.loads(raw)
    if set(config) != set(FLAGS) or any(type(config[key]) is not bool for key in FLAGS):
        raise ValueError('robot config must contain exactly three simulation flags')
    return policy, raw, config


def remote_operation(root, operation, payload=None):
    policy, raw, config = robot_config(root)
    hostname = __import__('socket').gethostname()
    path = policy.root / 'robot-config.json'
    before_locations = config_locations(raw, path, hostname)
    evidence = {'simulation': True, 'config': config, 'config_sha256': hashlib.sha256(raw).hexdigest(),
                'requires_onsite': config['hardware_required'],
                'robot_hostname': hostname, 'config_locations': before_locations,
                'robot_config_path': str(path)}
    if operation == 'inspect':
        return evidence
    if operation != 'repair' or not isinstance(payload, dict) or set(payload) != {'expected_sha256'}:
        raise ValueError('unsupported fixed remote operation')
    if config['hardware_required']:
        return {**evidence, 'changes': [], 'repaired': False, 'reason': 'hardware_requires_onsite_intervention'}
    before = dict(config)
    config = {**config, 'telemetry_enabled': True, 'accept_commands': True}
    result = policy.patch('robot-config.json', payload['expected_sha256'],
                          json.dumps(config, sort_keys=True, indent=2) + '\n')
    after_raw = policy.read('robot-config.json')
    if hashlib.sha256(after_raw).hexdigest() != result['sha256']:
        raise ValueError('robot config changed after patch; inspect actual state before reporting')
    after_locations = config_locations(after_raw, path, hostname)
    backup = policy.root / result['backup']
    changes = [
        {'target_hostname': hostname, 'path': str(path), 'key': key,
         'line': after_locations[key]['line'], 'before_line': before_locations[key]['line'],
         'after_line': after_locations[key]['line'], 'before': before[key], 'after': config[key],
         'backup': str(backup), 'before_sha256': evidence['config_sha256'],
         'after_sha256': result['sha256']}
        for key in FLAGS if before[key] != config[key]
    ]
    diff = ''.join(difflib.unified_diff(raw.decode().splitlines(keepends=True),
                                      after_raw.decode().splitlines(keepends=True),
                                      fromfile=str(backup), tofile=str(path)))
    return {**evidence, 'config': config, 'config_before': before, 'config_locations': after_locations,
            'config_locations_before': before_locations, 'changes': changes, 'config_diff': diff,
            'config_sha256_before': evidence['config_sha256'], 'config_sha256': result['sha256'],
            'backup': result['backup'], 'repaired': True}


def peer_config(root):
    policy = Policy({'approved_root': str(root)})
    raw = policy.read('robot-peer.json')
    if len(raw) > 8192:
        raise ValueError('peer config too large')
    config = json.loads(raw)
    if set(config) != {'host', 'username', 'ssh_key', 'known_hosts', 'remote_root'}:
        raise ValueError('invalid fixed peer configuration')
    address = ipaddress.ip_address(config['host'])
    if not address.is_private or address.is_unspecified or address.is_multicast:
        raise ValueError('peer must use a literal private LAN address')
    if not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}', config['username']):
        raise ValueError('invalid fixed peer username')
    for key in ('ssh_key', 'known_hosts'):
        path = Path(config[key])
        if not path.is_absolute() or not path.is_file() or path.is_symlink():
            raise ValueError('SSH credential/host verification path must exist locally')
    remote_root = config['remote_root']
    if (not isinstance(remote_root, str) or not remote_root.startswith('/') or
            not re.fullmatch(r'/[A-Za-z0-9_./-]+', remote_root) or
            any(part in ('', '.', '..') for part in remote_root.split('/')[1:]) or remote_root == '/'):
        raise ValueError('invalid isolated remote root')
    return config


def ssh_operation(root, operation, expected_sha256=None):
    if operation not in ('inspect', 'repair'):
        raise ValueError('only fixed inspect/repair SSH operations are supported')
    config = peer_config(root)
    remote = [
        '/usr/bin/python3', config['remote_root'] + '/robot_peer.py', '--remote',
        operation, '--root', config['remote_root'],
    ]
    argv = ['/usr/bin/ssh', '-T', '-i', config['ssh_key'], '-o', 'BatchMode=yes',
            '-o', 'IdentitiesOnly=yes', '-o', 'PasswordAuthentication=no',
            '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + config['known_hosts'],
            '-o', 'ConnectTimeout=5', config['username'] + '@' + config['host'], shlex.join(remote)]
    payload = {} if operation == 'inspect' else {'expected_sha256': expected_sha256}
    process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               env=safe_environment(), start_new_session=True)
    try:
        stdout, _stderr = process.communicate(json.dumps(payload).encode(), timeout=10)
    except subprocess.TimeoutExpired:
        kill_group(process)
        process.communicate()
        raise ValueError('fixed SSH operation timed out')
    if process.returncode not in (0, 2) or len(stdout) > 64 * 1024:
        raise ValueError('fixed SSH helper failed; check pinned host, dedicated key and remote installation')
    response = json.loads(stdout)
    if not isinstance(response, dict) or response.get('simulation') is not True:
        raise ValueError('invalid fixed SSH helper response')
    if process.returncode == 2 and response.get('requires_onsite') is not True:
        raise ValueError('invalid fixed SSH helper refusal')
    return response


def operation(root, action, expected_sha256=None):
    if action == 'verify':
        peer = ssh_operation(root, 'inspect')
        if peer['requires_onsite']:
            return {**peer, 'verified': False, 'reason': 'hardware_requires_onsite_intervention'}
        return {'simulation': True, 'robot': peer, 'collector': collector_sim.verify(root), 'verified': True}
    result = ssh_operation(root, action, expected_sha256)
    if action == 'inspect':
        result['collector'] = collector_sim.inspect(root)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--remote', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('operation', choices=('inspect', 'repair', 'verify'))
    parser.add_argument('--root', required=True)
    parser.add_argument('--expected-sha256')
    args = parser.parse_args()
    try:
        if args.remote:
            raw = sys.stdin.buffer.read(8193)
            if len(raw) > 8192:
                raise ValueError('request too large')
            result = remote_operation(args.root, args.operation, json.loads(raw or b'{}'))
        else:
            if args.operation == 'repair' and not re.fullmatch(r'[a-f0-9]{64}', args.expected_sha256 or ''):
                raise ValueError('repair requires inspect config_sha256 via --expected-sha256')
            result = operation(args.root, args.operation, args.expected_sha256)
        print(json.dumps(result, ensure_ascii=False))
        # Inspection successfully returning a fault is evidence, not a transport failure.
        if args.operation != 'inspect' and (result.get('requires_onsite') or result.get('verified') is False):
            raise SystemExit(2)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'simulation': True, 'ok': False, 'error': str(exc)[:256]}))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
