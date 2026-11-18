"""Run with the isolated Holmes Python; synthetic model and local HTTP gateway only."""
import importlib.util
import json
from pathlib import Path
import threading
import unittest
import subprocess
import sys
import os
from urllib.request import Request, urlopen
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SPEC = importlib.util.spec_from_file_location("holmes_runner", Path(__file__).with_name("holmes_runner.py"))
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class HolmesTest(unittest.TestCase):
    def test_real_holmes_investigation_uses_only_fixed_readonly_tool(self):
        from holmes.core.llm import DefaultLLM
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append((self.path, body))
                if self.path == '/rpc':
                    result = {'exit_code': 0, 'stdout': 'telemetry_enabled=false', 'stderr': ''}
                else:
                    count = sum(path == '/v1/chat/completions' for path, _ in requests)
                    if count == 1:
                        message = {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'read1', 'type': 'function',
                            'function': {'name': 'inspect_authorized_device', 'arguments': '{}'}}]}
                    else:
                        message = {'role': 'assistant', 'content': '配置禁用了遥测；尚未修复。'}
                    result = {'id': 'synthetic', 'object': 'chat.completion', 'created': 1, 'model': 'gpt-4o-mini',
                        'choices': [{'index': 0, 'message': message, 'finish_reason': 'tool_calls' if count == 1 else 'stop'}],
                        'usage': {'prompt_tokens': 20, 'completion_tokens': 10, 'total_tokens': 30}}
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(result).encode())
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f'http://127.0.0.1:{server.server_port}'
        try:
            payload = {'config': {'model': 'gpt-4o-mini', 'api_key': 'synthetic-model-key', 'base_url': origin+'/v1'},
                'tool_token': 'synthetic-tool-token', 'gateway_url': origin+'/rpc', 'inspect_argv': ['fixed-inspect'], 'problem': '遥测中断'}
            result = runner.investigate(payload)
            self.assertTrue(result['investigation_executed'])
            self.assertEqual(result['inspection_calls'], 1)
            self.assertIn('遥测', result['summary'])
            device = [body for path, body in requests if path == '/rpc']
            self.assertEqual(device, [{'operation': 'run', 'argv': ['fixed-inspect'], 'cwd': '.', 'timeout': 25, 'purpose': 'inspect'}])
            self.assertNotIn('synthetic-model-key', json.dumps(device))
            requests.clear()
            child = subprocess.run([sys.executable, str(Path(__file__).with_name('holmes_runner.py'))],
                input=json.dumps(payload), capture_output=True, text=True, timeout=30,
                env={'PATH': os.environ.get('PATH', ''), 'LITELLM_LOCAL_MODEL_COST_MAP': 'true'}, check=False)
            self.assertEqual(child.returncode, 0)
            self.assertTrue(json.loads(child.stdout)['investigation_executed'])
            self.assertEqual(json.loads(child.stdout)['successful_inspections'], 1)
            self.assertNotIn('synthetic-model-key', child.stdout+child.stderr)
            self.assertNotIn('synthetic-tool-token', child.stdout+child.stderr)
            if os.environ.get('HOLMES_TEST_SERVICE_URL'):
                requests.clear()
                url = os.environ['HOLMES_TEST_SERVICE_URL'].rstrip('/') + '/investigate'
                request = Request(url, data=json.dumps(payload).encode(), headers={'Content-Type':'application/json',
                    'Authorization':'Bearer '+os.environ['HOLMES_TEST_SERVICE_TOKEN']}, method='POST')
                with urlopen(request, timeout=40) as response:
                    service = json.load(response)
                self.assertTrue(service['ready'])
                self.assertEqual(service['successful_inspections'], 1)
                self.assertNotIn('synthetic-model-key', json.dumps(service))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()

class BudgetTest(unittest.TestCase):
    def test_unknown_model_output_budget_fits_the_configured_context(self):
        from holmes.core.llm import DefaultLLM
        llm=DefaultLLM(model='openai/unknown-field-model',api_key='synthetic',api_base='http://127.0.0.1:1/v1',args={'max_tokens':1800,'custom_args':{'max_context_size':32000}})
        self.assertLess(llm.get_maximum_output_token(),llm.get_context_window_size())
        self.assertEqual(llm.get_maximum_output_token(),1800)
