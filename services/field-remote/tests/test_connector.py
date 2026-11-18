import base64
import hashlib
import json
import os
import pwd
import socket
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, Mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from connector import Engine, Policy, run_command, exchange, NoRedirect, identity, validate_server, routed_host_ip
from collector_sim import inspect, verify
from robot_sim import RobotServer
from robot_peer import remote_operation, ssh_operation, ssh_server_ip
import threading


ARTIFACTS = Path('/home/engram/Documents/tmp/artifacts/field-remote-tests-20261118')
ARTIFACTS.mkdir(parents=True, exist_ok=True)


class ConnectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ARTIFACTS)
        self.root = Path(self.temp.name)
        self.policy = Policy({'approved_root': str(self.root),
                              'editable_files': ['config.json', 'collector-config.json'],
                              'allowed_commands': [['/usr/bin/printf'], ['/usr/bin/sleep']]})
        self.engine = Engine(self.policy)

    def tearDown(self):
        self.engine.close()
        self.temp.cleanup()

    def command(self, kind, **kwargs):
        return {'id': str(time.monotonic_ns()), 'expires_at': time.time() + 30,
                'kind': kind, **kwargs}

    def test_expiry_and_dedup_do_not_execute(self):
        target = self.root / 'config.json'
        target.write_text('old')
        command = self.command('patch_file', path='config.json',
                               expected_sha256=hashlib.sha256(b'old').hexdigest(), content='new')
        command['expires_at'] = time.time() - 1
        self.engine.accept(command)
        self.assertFalse(self.engine.results[-1]['ok'])
        self.assertEqual(target.read_text(), 'old')
        command['expires_at'] = time.time() + 30
        self.engine.accept(command)
        self.assertEqual(target.read_text(), 'old')

    def test_patch_sha_conflict_and_backup(self):
        target = self.root / 'config.json'
        target.write_text('old')
        with self.assertRaises(ValueError):
            self.policy.patch('config.json', '0' * 64, 'new')
        result = self.policy.patch('config.json', hashlib.sha256(b'old').hexdigest(), 'new')
        self.assertEqual(target.read_text(), 'new')
        self.assertEqual((self.root / result['backup']).read_text(), 'old')
        self.assertEqual(result['sha256'], hashlib.sha256(b'new').hexdigest())

    def test_path_escape_and_secret_refused(self):
        (self.root / 'escape').symlink_to('/etc')
        for path in ('../outside', '/etc/passwd', 'escape/passwd', '.env', 'id_rsa', '.ssh/key'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.policy.read(path)

    def test_policy_forbids_shell_and_unapproved_command(self):
        for argv in (['/bin/sh', '-c', 'echo unsafe'], ['/usr/bin/id'],
                     ['/usr/bin/printf', '../../secret'], ['/usr/bin/printf', '--root=../outside'],
                     ['/usr/bin/printf', '/etc/passwd']):
            with self.subTest(argv=argv), self.assertRaises(ValueError):
                self.policy.argv(argv)

    def test_patch_requires_explicit_editable_file_allowlist(self):
        target = self.root / 'connector.py'
        target.write_text('trusted-code')
        with self.assertRaisesRegex(ValueError, 'editable_files'):
            self.policy.patch('connector.py', hashlib.sha256(b'trusted-code').hexdigest(), 'injected')
        unconfigured = Policy({'approved_root': str(self.root)})
        config = self.root / 'config.json'
        config.write_text('old')
        with self.assertRaisesRegex(ValueError, 'editable_files'):
            unconfigured.patch('config.json', hashlib.sha256(b'old').hexdigest(), 'new')
        self.assertEqual(target.read_text(), 'trusted-code')

    def test_robot_peer_arguments_cannot_switch_remote_mode_or_root(self):
        script = self.root / 'robot_peer.py'
        script.write_text('trusted')
        prefix = ['/usr/bin/python3', str(script), 'inspect']
        policy = Policy({'approved_root': str(self.root), 'allowed_commands': [prefix]})
        policy.argv(prefix + ['--root', str(self.root)])
        for suffix in (['--remote', '--root', str(self.root)],
                       ['--root', str(self.root / 'nested')],
                       ['--root=' + str(self.root / 'nested')],
                       ['--root', str(self.root), '--expected-sha256', '0' * 64]):
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                policy.argv(prefix + suffix)

    def test_run_timeout_and_output_bound(self):
        result = run_command(self.policy, ['/usr/bin/sleep', '10'], '.', 0.05)
        self.assertTrue(result['timed_out'])
        result = run_command(self.policy, ['/usr/bin/printf', 'x' * 10000], '.', 2, max_output=1024)
        self.assertEqual(len(result['stdout']), 1024)
        self.assertTrue(result['truncated'])
        self.assertEqual(run_command(self.policy, ['/usr/bin/printf', 'ok'], '', 2)['stdout'], 'ok')

    def test_real_pty_utf8_resize_and_exit(self):
        self.engine.accept(self.command('terminal_open', session_id='pty-test', cols=93, rows=28))
        payload = "printf '终端测试\\n'; stty size; exit 7\n".encode()
        self.engine.accept(self.command('terminal_input', session_id='pty-test',
                                        data=base64.b64encode(payload).decode()))
        for _ in range(100):
            self.engine.pump()
            if any(x['kind'] == 'exit' for x in self.engine.outputs):
                break
            time.sleep(0.02)
        raw = b''.join(base64.b64decode(x['data']) for x in self.engine.outputs if x['kind'] == 'data')
        self.assertIn('终端测试'.encode(), raw)
        self.assertIn(b'28 93', raw)
        self.assertEqual([x['code'] for x in self.engine.outputs if x['kind'] == 'exit'], [7])

    def test_session_close_reaps_process_group(self):
        self.engine.accept(self.command('terminal_open', session_id='close-test', cols=80, rows=24))
        pid = self.engine.terminals['close-test'].pid
        self.engine.accept(self.command('terminal_close', session_id='close-test'))
        with self.assertRaises(ProcessLookupError):
            os.killpg(pid, 0)

    def test_terminal_prompt_uses_real_identity_and_ansi_colors(self):
        self.engine.host_ip='10.10.10.195'
        self.engine.accept(self.command('terminal_open', session_id='identity', cols=120, rows=28))
        for _ in range(100):
            self.engine.pump()
            raw = b''.join(base64.b64decode(x['data']) for x in self.engine.outputs if x['kind'] == 'data')
            if b'$ ' in raw or b'# ' in raw:
                break
            time.sleep(0.02)
        expected = f"{pwd.getpwuid(os.getuid()).pw_name}@10.10.10.195".encode()
        self.assertIn(expected, raw)
        self.assertIn(b'\x1b[', raw)
        self.assertNotIn(b'bash-5.', raw)
        payload = b'printf "TERM_CHECK=%s COLOR_CHECK=%s\\n" "$TERM" "$COLORTERM"; exit\n'
        self.engine.accept(self.command('terminal_input', session_id='identity', data=base64.b64encode(payload).decode()))
        for _ in range(100):
            self.engine.pump()
            if any(x['kind'] == 'exit' for x in self.engine.outputs):
                break
            time.sleep(0.02)

        raw = b''.join(base64.b64decode(x['data']) for x in self.engine.outputs if x['kind'] == 'data')
        self.assertIn(b'TERM_CHECK=xterm-256color COLOR_CHECK=truecolor', raw)

    def test_routed_ip_uses_only_configured_destination_source_and_no_hostname_guess(self):
        route=Mock();route.__enter__=Mock(return_value=route);route.__exit__=Mock(return_value=False)
        route.getsockname.return_value=('10.10.10.195',45000)
        address=(socket.AF_INET,socket.SOCK_DGRAM,17,'',('180.153.172.19',18886))
        with patch('connector.socket.getaddrinfo',return_value=[address]) as resolve,patch('connector.socket.socket',return_value=route):
            self.assertEqual(routed_host_ip('http://180.153.172.19:18886'),'10.10.10.195')
            resolve.assert_called_once_with('180.153.172.19',18886,type=socket.SOCK_DGRAM)
            route.connect.assert_called_once_with(('180.153.172.19',18886))
            route.send.assert_not_called();route.sendto.assert_not_called()
            self.assertEqual(identity(self.policy,'http://180.153.172.19:18886')['capabilities']['network']['ip_address'],'10.10.10.195')
        with patch('connector.socket.getaddrinfo',side_effect=OSError('unavailable')):
            self.assertIsNone(routed_host_ip('https://configured.invalid'))
            self.assertIsNone(identity(server_url='https://configured.invalid')['host_ip'])

    def test_robot_ip_is_only_ssh_server_address_or_none(self):
        with patch.dict(os.environ,{'SSH_CONNECTION':'10.10.10.195 44000 10.10.10.177 22'}):
            self.assertEqual(ssh_server_ip(),'10.10.10.177')
            config=self.root/'robot-config.json'
            config.write_text(json.dumps({'telemetry_enabled':False,'accept_commands':True,'hardware_required':False}))
            before=remote_operation(self.root,'inspect')
            self.assertEqual(before['robot_ip'],'10.10.10.177')
            after=remote_operation(self.root,'repair',{'expected_sha256':before['config_sha256']})
            self.assertEqual(after['changes'][0]['target_ip'],'10.10.10.177')
        for connection in ('','bad 22 host-name 22','10.10.10.195 44000 0.0.0.0 22'):
            with patch.dict(os.environ,{'SSH_CONNECTION':connection}):self.assertIsNone(ssh_server_ip())

    def test_robot_target_forwards_local_capability_bytes_without_local_shell(self):
        revision='a'*64
        responses=[{'identity':{'username':'engram','host':'10.10.10.177'}}, {'ok':True},
                   {'events':[{'seq':1,'id':'remote-event','kind':'data','data':'eA=='}],'cursor':1},
                   {'closed':True}]
        with patch('file_browser.local_launcher_request',side_effect=responses) as call:
            self.engine.accept(self.command('terminal_open',target='robot',session_id='robot-test',target_revision=revision,cols=80,rows=24))
            self.assertTrue(self.engine.results[-1]['ok'])
            self.assertEqual(self.engine.results[-1]['identity']['host'],'10.10.10.177')
            self.engine.accept(self.command('terminal_input',session_id='robot-test',data='eA=='))
            self.engine.pump()
            self.assertEqual(self.engine.outputs[-1]['id'],'remote-event')
            self.assertEqual(self.engine.outputs[-1]['session_id'],'robot-test')
            self.engine.accept(self.command('terminal_close',session_id='robot-test'))
            self.assertEqual([row.args[1]['action'] for row in call.call_args_list],['open','input','read','close'])
            self.assertTrue(all(row.args[1]['expected_target_revision']==revision for row in call.call_args_list))

    def test_robot_status_does_not_promote_fixed_sim_peer_when_local_api_fails(self):
        self.policy.daq_local_api={'url':'http://127.0.0.1:11452/api/launcher/remote-robot-files','token_file':'/missing'}
        (self.root/'robot-peer.json').write_text(json.dumps({'username':'engram','host':'10.10.10.177'}))
        value=identity(self.policy)['capabilities']
        self.assertFalse(value['robot']['connected'])
        self.assertIsNone(value['robot']['host'])
        self.assertEqual(value['simulation_robot']['host'],'10.10.10.177')

    def test_local_diagnostics_exact_logical_commands_never_launch_subprocess(self):
        self.policy.daq_local_api={'url':'http://127.0.0.1:11452/api/launcher/remote-robot-files','token_file':'/private'}
        for op in ('inspect','verify'):
            self.assertEqual(self.policy.argv(['daq-local-diagnostics-v1',op]),['daq-local-diagnostics-v1',op])
        for argv in (['daq-local-diagnostics-v1','repair'],['daq-local-diagnostics-v1','inspect','/etc/passwd']):
            with self.assertRaises(ValueError):self.policy.argv(argv)
        with patch('file_browser.local_launcher_request',return_value={'scope':'read_only_connectivity','verified':False,'robot':{'connected':False}}) as call,patch('connector.subprocess.Popen') as process:
            for op in ('inspect','verify'):
                command=self.command('run',argv=['daq-local-diagnostics-v1',op],cwd='.',timeout=2)
                self.engine.accept(command)
                for _ in range(100):
                    self.engine.pump()
                    rows=[result for result in self.engine.results if result['id']==command['id']]
                    if rows:break
                    time.sleep(.005)
                self.assertEqual(rows[0]['exit_code'],0 if op=='inspect' else 1)
                self.assertEqual(json.loads(rows[0]['stdout'])['scope'],'read_only_connectivity')
                self.assertFalse(json.loads(rows[0]['stdout'])['robot']['connected'])
            process.assert_not_called()
            self.assertTrue(all(row.kwargs.get('diagnostics') for row in call.call_args_list))

    def test_patch_duplicate_cached_and_restart_not_reexecuted(self):
        target = self.root / 'config.json'
        target.write_text('before')
        command = self.command('patch_file', path='config.json',
                               expected_sha256=hashlib.sha256(b'before').hexdigest(), content='after')
        self.engine.accept(command)
        first = self.engine.results[-1]
        self.engine.accept(command)
        self.assertEqual(self.engine.results[-1], first)
        self.assertEqual(len(list(self.root.glob('*.backup-*'))), 1)
        self.engine.close()
        second = Engine(self.policy)
        try:
            second.accept(command)
            self.assertTrue(second.results[-1]['recovered'])
            self.assertEqual(target.read_text(), 'after')
            self.assertEqual(len(list(self.root.glob('*.backup-*'))), 1)
        finally:
            second.close()
        state = (self.root / '.field-remote-state.json').read_text()
        self.assertNotIn('before', state)
        self.assertNotIn('after', state)
        self.assertEqual((self.root / '.field-remote-state.json').stat().st_mode & 0o777, 0o600)

    def test_terminal_duplicate_input_and_late_open_refused(self):
        opened = self.command('terminal_open', session_id='dedup', cols=80, rows=24)
        self.engine.accept(opened)
        command = self.command('terminal_input', session_id='dedup',
                               data=base64.b64encode(b"printf x >> execution-count;\n").decode())
        self.engine.accept(command)
        self.engine.accept(command)
        for _ in range(100):
            self.engine.pump()
            if (self.root / 'execution-count').exists():
                break
            time.sleep(0.01)
        self.assertEqual((self.root / 'execution-count').read_text(), 'x')
        self.assertEqual(len({x['id'] for x in self.engine.outputs}), len(self.engine.outputs))
        self.engine.accept(self.command('terminal_close', session_id='dedup'))
        self.engine.accept(self.command('terminal_open', session_id='dedup', cols=80, rows=24))
        self.assertFalse(self.engine.results[-1]['ok'])

    def test_disconnect_closes_idle_terminal(self):
        self.engine.accept(self.command('terminal_open', session_id='disconnect', cols=80, rows=24))
        self.engine.last_exchange = time.monotonic() - 31
        self.engine.pump()
        self.assertFalse(self.engine.terminals)
        self.assertEqual(self.engine.outputs[-1]['kind'], 'exit')

    def test_exchange_retries_stable_batch_and_acknowledges(self):
        received = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                received.append(body)
                self.send_response(503 if len(received) == 1 else 200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"commands": []}')

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.engine.output({'session_id': 'example', 'kind': 'data', 'data': 'eA=='})
        batch = {'identity': identity(), 'outputs': self.engine.outputs[:], 'results': []}
        opener = urllib.request.build_opener(NoRedirect, urllib.request.ProxyHandler({}))
        url = f'http://127.0.0.1:{server.server_address[1]}/exchange/'
        try:
            with self.assertRaises(urllib.error.HTTPError):
                exchange(opener, url, 'noncredential-test-value', batch)
            self.assertEqual(len(self.engine.outputs), 1)
            exchange(opener, url, 'noncredential-test-value', batch)
            self.assertEqual(received[0], received[1])
            self.engine.acknowledge(1, 0)
            self.assertFalse(self.engine.outputs)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_exclusive_root_lock(self):
        with self.assertRaisesRegex(ValueError, 'another connector'):
            Engine(self.policy)

    def test_public_http_requires_dedicated_insecure_flag(self):
        public = 'http://180.153.172.19:18886'
        for kwargs in ({}, {'allow_private_http': True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                validate_server(public, **kwargs)
        validate_server(public, allow_insecure_public_http=True)
        validate_server('https://central.example')
        validate_server('http://10.10.10.4:8886', allow_private_http=True)
        for address in ('0.0.0.0', '127.0.0.1', '224.0.0.1', 'central.example'):
            with self.subTest(address=address), self.assertRaises(ValueError):
                validate_server('http://' + address, allow_insecure_public_http=True)

    def test_simulator_rejects_out_of_bounds_joint_target(self):
        server = RobotServer(('127.0.0.1', 0), '')
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = urllib.request.Request(
                f'http://127.0.0.1:{server.server_address[1]}/command',
                data=json.dumps({'simulation': True, 'sequence': 1, 'joint_targets': [99] * 6}).encode(),
                headers={'Content-Type': 'application/json'})
            with self.assertRaises(urllib.error.HTTPError) as context:
                urllib.request.urlopen(request)
            self.assertEqual(context.exception.code, 400)
            self.assertEqual(server.telemetry['sequence'], 0)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_simulation_fault_patch_and_record(self):
        server = RobotServer(('127.0.0.1', 0), '')
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            config = {'simulation': True, 'robot_host': '127.0.0.1',
                      'robot_port': 1, 'expected_robot_port': port}
            target = self.root / 'collector-config.json'
            target.write_text(json.dumps(config))
            with patch.dict(os.environ, {'FIELD_SIM_TOKEN': ''}):
                before = inspect(self.root)
                self.assertFalse(before['reachable'])
                self.assertFalse(before['port_matches'])
                config['robot_port'] = port
                self.policy.patch('collector-config.json', before['config_sha256'], json.dumps(config))
                result = verify(self.root)
            self.assertTrue(result['verified'])
            record = json.loads((self.root / 'simulation-records.jsonl').read_text())
            self.assertEqual(record['command_ack'], record['telemetry']['sequence'])
            self.assertEqual(record['robot_port'], port)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_ssh_preserves_confirmed_onsite_evidence_instead_of_generic_failure(self):
        process = Mock(returncode=2)
        process.communicate.return_value = (json.dumps({'simulation': True, 'requires_onsite': True,
            'config': {'hardware_required': True}, 'repaired': False}).encode(), b'')
        with patch('robot_peer.peer_config', return_value={'host':'10.10.10.177','username':'engram',
                'remote_root':'/isolated','ssh_key':'/key','known_hosts':'/known'}), patch('robot_peer.subprocess.Popen', return_value=process):
            evidence = ssh_operation(self.root, 'inspect')
        self.assertTrue(evidence['requires_onsite'])
        self.assertTrue(evidence['config']['hardware_required'])

    def test_remote_fault_hot_repair_and_onsite_refusal(self):
        config_path = self.root / 'robot-config.json'
        config = {'telemetry_enabled': False, 'accept_commands': True, 'hardware_required': False}
        config_path.write_text(json.dumps(config))
        server = RobotServer(('127.0.0.1', 0), '', config_path)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        collector_config = {'simulation': True, 'robot_host': '127.0.0.1',
                            'robot_port': server.server_address[1], 'expected_robot_port': server.server_address[1]}
        (self.root / 'collector-config.json').write_text(json.dumps(collector_config))
        try:
            with patch.dict(os.environ, {'FIELD_SIM_TOKEN': ''}):
                with self.assertRaises(urllib.error.HTTPError):
                    verify(self.root)
                before = remote_operation(self.root, 'inspect')
                with self.assertRaisesRegex(ValueError, 'SHA256 conflict'):
                    remote_operation(self.root, 'repair', {'expected_sha256': '0' * 64})
                repaired = remote_operation(self.root, 'repair', {'expected_sha256': before['config_sha256']})
                self.assertTrue(repaired['repaired'])
                self.assertEqual(json.loads((self.root / repaired['backup']).read_text()), config)
                self.assertTrue(verify(self.root)['verified'])
                config['hardware_required'] = True
                config_path.write_text(json.dumps(config))
                before = remote_operation(self.root, 'inspect')
                refused = remote_operation(self.root, 'repair', {'expected_sha256': before['config_sha256']})
                self.assertTrue(refused['requires_onsite'])
                self.assertFalse(refused['repaired'])
                self.assertEqual(json.loads(config_path.read_text()), config)
                with self.assertRaises(urllib.error.HTTPError):
                    verify(self.root)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_remote_repair_reports_actual_host_file_lines_values_and_diff(self):
        configs = [
            ('{"telemetry_enabled":false,"accept_commands":false,"hardware_required":false}',
             {'telemetry_enabled':1,'accept_commands':1,'hardware_required':1}),
            ('{\n  "telemetry_enabled": false,\n\n  "accept_commands": false,\n\n  "hardware_required": false\n}\n',
             {'telemetry_enabled':2,'accept_commands':4,'hardware_required':6}),
        ]
        for raw, lines in configs:
            with self.subTest(lines=lines):
                target=self.root/'robot-config.json';target.write_text(raw)
                before=remote_operation(self.root,'inspect')
                for key,line in lines.items():
                    location=before['config_locations'][key]
                    self.assertEqual(location['line'],line)
                    self.assertEqual(location['value'],False)
                    self.assertEqual(location['path'],str(target))
                    self.assertEqual(location['hostname'],before['robot_hostname'])
                result=remote_operation(self.root,'repair',{'expected_sha256':before['config_sha256']})
                after=target.read_text()
                self.assertEqual(len(result['changes']),2)
                for change in result['changes']:
                    self.assertEqual(change['before'],False)
                    self.assertEqual(change['after'],True)
                    self.assertEqual(change['before_line'],lines[change['key']])
                    actual_line=next(n for n,text in enumerate(after.splitlines(),1) if '"'+change['key']+'"' in text)
                    self.assertEqual(change['after_line'],actual_line)
                    self.assertEqual(change['line'],actual_line)
                    self.assertEqual(change['path'],str(target))
                    self.assertEqual(change['target_hostname'],before['robot_hostname'])
                    self.assertEqual(Path(change['backup']).read_text(),raw)
                    self.assertEqual(change['before_sha256'],hashlib.sha256(raw.encode()).hexdigest())
                    self.assertEqual(change['after_sha256'],hashlib.sha256(after.encode()).hexdigest())
                self.assertTrue(any(line.startswith('-') and 'false' in line for line in result['config_diff'].splitlines()))
                self.assertIn('+  "telemetry_enabled": true',result['config_diff'])

    def test_fixed_ssh_argv_and_no_remote_command_input(self):
        key = self.root / 'dedicated-test-key'
        known = self.root / 'known-hosts'
        key.write_text('test-fixture-only')
        known.write_text('test-fixture-only')
        config = {'host': '192.168.1.177', 'username': 'engram', 'ssh_key': str(key),
                  'known_hosts': str(known), 'remote_root': '/isolated/robot-sim'}
        (self.root / 'robot-peer.json').write_text(json.dumps(config))
        with self.assertRaises(ValueError):
            ssh_operation(self.root, 'arbitrary-command')
        process = unittest.mock.Mock()
        process.communicate.return_value = (b'{"simulation":true,"requires_onsite":false}', b'')
        process.returncode = 0
        with patch('robot_peer.subprocess.Popen', return_value=process) as popen:
            ssh_operation(self.root, 'inspect')
        argv = popen.call_args.args[0]
        self.assertIn('StrictHostKeyChecking=yes', argv)
        self.assertIn('BatchMode=yes', argv)
        self.assertEqual(argv[-1], '/usr/bin/python3 /isolated/robot-sim/robot_peer.py --remote inspect --root /isolated/robot-sim')


if __name__ == '__main__':
    unittest.main()
