#!/usr/bin/env python3
"""Isolated HTTP robot simulator; never imports ROS or connects to a robot."""

import argparse
import getpass
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import math
import os
from pathlib import Path
import threading
import time


def private_address(value):
    address = ipaddress.ip_address(value)
    if not address.is_private or address.is_unspecified or address.is_multicast:
        raise ValueError('bind must be a literal private LAN or loopback address')
    return address


class RobotServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, token, config_path=None):
        private_address(address[0])
        if not token and not ipaddress.ip_address(address[0]).is_loopback:
            raise ValueError('a token is required outside loopback')
        self.token = token
        self.config_path = Path(config_path) if config_path else None
        self.lock = threading.Lock()
        self.telemetry = {'simulation': True, 'sequence': 0, 'joint_positions': [0.0] * 6,
                          'received_at': None}
        super().__init__(address, Handler)

    def config(self):
        defaults = {'telemetry_enabled': True, 'accept_commands': True, 'hardware_required': False}
        if self.config_path:
            if self.config_path.is_symlink() or self.config_path.stat().st_size > 8192:
                raise ValueError('unsafe simulation config')
            loaded = json.loads(self.config_path.read_text())
            for key in defaults:
                if key in loaded and type(loaded[key]) is not bool:
                    raise ValueError('invalid simulation flag')
            defaults.update({key: loaded[key] for key in defaults if key in loaded})
        return defaults


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def send_json(self, code, payload):
        raw = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def authorized(self):
        expected = 'Bearer ' + self.server.token
        if self.server.token and not hmac.compare_digest(self.headers.get('Authorization', ''), expected):
            self.send_json(401, {'error': 'unauthorized'})
            return False
        return True

    def do_GET(self):
        if not self.authorized():
            return
        try:
            config = self.server.config()
        except (ValueError, OSError):
            self.send_json(503, {'simulation': True, 'error': 'simulation config unavailable'})
            return
        if self.path == '/health':
            self.send_json(200, {'simulation': True, 'service': 'field-robot-sim', 'status': 'ok'})
        elif self.path == '/status':
            self.send_json(200, {'simulation': True, 'service': 'field-robot-sim', **config})
        elif self.path == '/telemetry':
            if not config['telemetry_enabled'] or config['hardware_required']:
                self.send_json(503, {'simulation': True, 'error': 'telemetry disabled',
                                     'requires_onsite': config['hardware_required']})
                return
            with self.server.lock:
                self.send_json(200, self.server.telemetry)
        else:
            self.send_json(404, {'error': 'unknown simulator endpoint'})

    def do_POST(self):
        if not self.authorized():
            return
        try:
            config = self.server.config()
            if not config['accept_commands'] or config['hardware_required']:
                self.send_json(409, {'simulation': True, 'error': 'simulator command refused',
                                     'requires_onsite': config['hardware_required']})
                return
            length = int(self.headers.get('Content-Length', '0'))
            if self.path != '/command' or not 0 < length <= 4096:
                raise ValueError('invalid command request')
            data = json.loads(self.rfile.read(length))
            joints = data['joint_targets']
            sequence = data['sequence']
            if (data.get('simulation') is not True or type(sequence) is not int or sequence < 1
                    or not isinstance(joints, list) or len(joints) != 6
                    or any(type(value) not in (int, float) or not math.isfinite(value)
                           or abs(value) > 0.25 for value in joints)):
                raise ValueError('only six bounded simulated joint targets are permitted')
            with self.server.lock:
                if sequence <= self.server.telemetry['sequence']:
                    raise ValueError('sequence must increase')
                self.server.telemetry = {'simulation': True, 'sequence': sequence,
                                         'joint_positions': joints, 'received_at': time.time()}
            self.send_json(200, {'simulation': True, 'ack': sequence})
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            self.send_json(400, {'error': 'invalid bounded simulation command'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bind', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=18777)
    parser.add_argument('--no-auth-loopback', action='store_true')
    parser.add_argument('--config', help='isolated robot-config.json, hot read on every request')
    args = parser.parse_args()
    private_address(args.bind)
    token = os.environ.pop('FIELD_SIM_TOKEN', '')
    if not token and not args.no_auth_loopback:
        token = getpass.getpass('Simulation token: ')
        if not token:
            parser.error('simulation token required')
    if args.no_auth_loopback and not ipaddress.ip_address(args.bind).is_loopback:
        parser.error('--no-auth-loopback requires loopback bind')
    server = RobotServer((args.bind, args.port), token, args.config)
    try:
        print('Isolated robot simulator listening; no motor or DAQ connection', flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
