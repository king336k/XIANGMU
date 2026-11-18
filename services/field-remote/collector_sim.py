#!/usr/bin/env python3
"""Inspect/verify an isolated robot HTTP simulator; record local JSONL telemetry."""

import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import socket
import time
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args):
        raise ValueError('simulation redirects are forbidden')


def load(root):
    root = Path(root).resolve(strict=True)
    config_path = root / 'collector-config.json'
    if config_path.is_symlink():
        raise ValueError('collector config must not be a symlink')
    raw = config_path.read_bytes()
    if len(raw) > 8192:
        raise ValueError('collector config too large')
    config = json.loads(raw)
    host = ipaddress.ip_address(config['robot_host'])
    if not host.is_private or host.is_unspecified or host.is_multicast:
        raise ValueError('simulation requires literal private LAN address')
    for key in ('robot_port', 'expected_robot_port'):
        if type(config[key]) is not int or not 1 <= config[key] <= 65535:
            raise ValueError('invalid robot port')
    if config.get('simulation') is not True:
        raise ValueError('explicit simulation flag required')
    return root, config, hashlib.sha256(raw).hexdigest()


def request(config, path, payload=None):
    # The capability is a fixed simulation endpoint, not a generic URL fetch tool.
    host = config['robot_host']
    if ':' in host:
        host = '[' + host + ']'
    url = f'http://{host}:{config["robot_port"]}{path}'
    token = os.environ.get('FIELD_SIM_TOKEN', '')
    if not token and config.get('token_file'):
        credential = Path(config['token_file'])
        fd = os.open(credential, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd) as stream:
            info = os.fstat(stream.fileno())
            if info.st_uid != os.getuid() or info.st_mode & 0o777 != 0o600 or info.st_size > 4096 or info.st_nlink != 1:
                raise ValueError('invalid private simulation credential file')
            token = stream.read(4096).strip()
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    outgoing = urllib.request.Request(url, data=None if payload is None else json.dumps(payload).encode(),
                                     headers=headers)
    opener = urllib.request.build_opener(NoRedirect, urllib.request.ProxyHandler({}))
    with opener.open(outgoing, timeout=2) as response:
        raw = response.read(8193)
    if len(raw) > 8192:
        raise ValueError('simulation response too large')
    result = json.loads(raw)
    if result.get('simulation') is not True:
        raise ValueError('remote endpoint is not the isolated simulator')
    return result


def inspect(root):
    _, config, sha = load(root)
    result = {'simulation': True, 'config_sha256': sha,
              'configured_robot_port': config['robot_port'],
              'expected_robot_port': config['expected_robot_port'],
              'port_matches': config['robot_port'] == config['expected_robot_port'],
              'robot_host': config['robot_host'], 'collector_hostname': socket.gethostname()}
    try:
        health = request(config, '/health')
        result.update(reachable=True, robot_service=health.get('service'))
    except (urllib.error.URLError, OSError, ValueError):
        result.update(reachable=False, error='simulation endpoint unavailable or invalid')
    return result


def verify(root):
    root, config, sha = load(root)
    health = request(config, '/health')
    if health.get('service') != 'field-robot-sim':
        raise ValueError('not the expected simulator service')
    sequence = time.time_ns()
    targets = [0.02, -0.02, 0.01, -0.01, 0.0, 0.0]
    ack = request(config, '/command', {'simulation': True, 'sequence': sequence, 'joint_targets': targets})
    telemetry = request(config, '/telemetry')
    if ack.get('ack') != sequence or telemetry.get('sequence') != sequence or telemetry.get('joint_positions') != targets:
        raise ValueError('simulation command ack/telemetry mismatch')
    record = {'simulation': True, 'verified_at': time.time(), 'sequence': sequence,
              'command_ack': ack['ack'], 'telemetry': telemetry, 'config_sha256': sha,
              'collector_hostname': socket.gethostname(), 'robot_host': config['robot_host'],
              'robot_port': config['robot_port']}
    output = root / 'simulation-records.jsonl'
    fd = os.open(output, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        if os.fstat(fd).st_size > 10 * 1024 * 1024:
            raise ValueError('simulation record file reached 10 MiB limit; rotate it locally')
        os.write(fd, (json.dumps(record, separators=(',', ':')) + '\n').encode())
        os.fsync(fd)
    finally:
        os.close(fd)
    return {'simulation': True, 'verified': True, 'command_ack': sequence,
            'telemetry_sequence': telemetry['sequence'], 'record_path': str(output),
            'record_sha256': hashlib.sha256(output.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('inspect', 'verify'))
    parser.add_argument('--root', default=str(Path(__file__).resolve().parent))
    args = parser.parse_args()
    try:
        result = inspect(args.root) if args.operation == 'inspect' else verify(args.root)
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, OSError, urllib.error.URLError, KeyError) as exc:
        # Print a stable failure class, never token-bearing HTTP response content.
        print(json.dumps({'simulation': True, 'verified': False, 'error': type(exc).__name__}))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
