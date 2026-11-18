"""Regression tests using synthetic credentials and a real local HTTP gateway."""
import importlib.util
import json
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
import asyncio
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SPEC = importlib.util.spec_from_file_location("remote_runner", Path(__file__).parents[1] / "diagnostic-agent/remote_runner.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class GatewayTest(unittest.TestCase):
    def setUp(self):
        self.requests = []
        requests = self.requests
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                requests.append((self.headers["Authorization"], body))
                response = {"exit_code": 0, "stdout": "healthy", "stderr": ""}
                if body["operation"] == "read_file":
                    response = {"content": "before", "sha256": "a" * 64}
                elif body['operation']=='knowledge':
                    response={'source':'project_knowledge','results':[],'case_history':[]}
                elif body['operation']=='catalog':
                    response={'sources':[{'id':'rai','kind':'github'}]}
                elif body['operation']=='read_source':
                    response={'source_id':'rai','content':'official reference','revision':'a'*40}
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps(response).encode())
            def log_message(self, *args):
                pass
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.gateway = runner.Gateway(f"http://127.0.0.1:{self.server.server_port}/rpc", "synthetic-token",
                                      inspect_argv=['inspect'], verify_argv=['check'])

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_rpc_auth_and_fresh_inspection_required_before_mutation(self):
        with self.assertRaises(ValueError):
            self.gateway.patch_file("/config", "a" * 64, "after")
        self.gateway.run_command(['inspect'])
        self.gateway.read_file("/config")
        self.gateway.patch_file("/config", "a" * 64, "after")
        self.assertFalse(self.gateway.repair_verified)
        self.gateway.run_command(["check"], purpose="verify")
        self.assertTrue(self.gateway.repair_verified)
        self.assertEqual(self.requests[0][0], "Bearer synthetic-token")
        self.assertEqual(self.requests[-1][1]["operation"], "run")

    def test_no_repair_claim_without_mutation_and_postcheck(self):
        self.gateway.run_command(["inspect"], purpose="inspect")
        self.gateway.run_command(["check"], purpose="verify")
        self.assertFalse(self.gateway.repair_verified)
        self.gateway.run_command(["repair"], purpose="repair")
        self.assertFalse(self.gateway.repair_verified)

    def test_configured_verification_and_readonly_scope_are_enforced(self):
        self.gateway.inspect_argv = ['inspect-original-target']
        with self.assertRaises(ValueError):
            self.gateway.run_command(['unrelated-health'], purpose='inspect')
        self.assertFalse(self.gateway.inspected)
        self.gateway.run_command(['inspect-original-target'], purpose='inspect')
        self.assertTrue(self.gateway.inspected)
        self.gateway.verify_argv = ["check-original-fault"]
        self.gateway.run_command(["inspect"], purpose="inspect")
        with self.assertRaises(ValueError):
            self.gateway.run_command(["true"], purpose="verify")
        self.gateway.repair_allowed = False
        with self.assertRaises(ValueError):
            self.gateway.run_command(["repair"], purpose="repair")
        with self.assertRaises(ValueError):
            self.gateway.run_command(["repair"], purpose="inspect")

    def test_tool_budget_is_bounded(self):
        self.gateway.max_calls = 1
        self.gateway.read_file("/config")
        with self.assertRaises(ValueError):
            self.gateway.read_file("/config")

    def test_empty_patch_response_is_not_successful_mutation(self):
        self.gateway.run_command(['inspect'])
        self.gateway.read_file('/config')
        with patch.object(self.gateway, 'rpc', return_value={}):
            self.gateway.patch_file('/config', 'a'*64, 'after')
        self.gateway.run_command(['check'], purpose='verify')
        self.assertFalse(self.gateway.repair_verified)

    def test_trusted_repair_prefix_is_exact_and_requires_sha(self):
        self.gateway.run_command(['inspect'])
        self.gateway.repair_argv = ['fixed-repair', '--expected-sha256']
        with self.assertRaises(ValueError):
            self.gateway.patch_file('/config', 'a'*64, 'after')
        with self.assertRaises(ValueError):
            self.gateway.run_command(['other-repair', 'a'*64], purpose='inspect')
        with self.assertRaises(ValueError):
            self.gateway.run_command(['fixed-repair', '--expected-sha256', 'invalid'], purpose='repair')
        self.gateway.run_command(['fixed-repair', '--expected-sha256', 'a'*64], purpose='inspect')
        self.assertEqual(self.gateway.mutation, 1)
        self.assertFalse(self.gateway.repair_verified)

    def test_required_kb_lookup_precedes_mutation(self):
        self.gateway.require_knowledge=True
        self.gateway.run_command(['inspect'])
        with self.assertRaises(ValueError):
            self.gateway.run_command(['repair'],purpose='repair')
        self.gateway.knowledge_searched=True
        self.gateway.run_command(['repair'],purpose='repair')
        self.assertEqual(self.gateway.mutation,1)

    def test_failed_mutation_cannot_be_declared_repaired_by_later_check(self):
        self.gateway.run_command(['inspect'], purpose='inspect')
        with patch.object(self.gateway, 'rpc', return_value={'exit_code': 1, 'error': 'failed'}):
            self.gateway.run_command(['repair'], purpose='repair')
        self.gateway.run_command(['check'], purpose='verify')
        self.assertFalse(self.gateway.repair_verified)

    def test_latest_failed_verification_invalidates_old_success(self):
        self.gateway.run_command(['inspect'])
        self.gateway.run_command(['repair'], purpose='repair')
        self.gateway.run_command(['check'], purpose='verify')
        self.assertTrue(self.gateway.repair_verified)
        with patch.object(self.gateway, 'rpc', return_value={'exit_code': 1}):
            self.gateway.run_command(['check'], purpose='verify')
        self.assertFalse(self.gateway.repair_verified)

    def test_any_new_mutation_invalidates_previous_verification(self):
        self.gateway.run_command(['inspect'])
        self.gateway.run_command(['check'], purpose='verify')
        self.assertTrue(self.gateway.verification_passed)
        with patch.object(self.gateway,'rpc',return_value={'ok':False,'exit_code':1}):
            self.gateway.run_command(['repair'],purpose='repair')
        self.assertFalse(self.gateway.verification_passed)
        self.assertFalse(self.gateway.verification_attempted)
        self.gateway.run_command(['check'],purpose='verify')
        self.assertTrue(self.gateway.verification_passed)
        self.gateway.read_file('/config')
        with patch.object(self.gateway,'rpc',return_value={'ok':False,'exit_code':1}):
            self.gateway.patch_file('/config','a'*64,'after')
        self.assertFalse(self.gateway.verification_passed)
        self.assertFalse(self.gateway.verification_attempted)
        self.assertFalse(self.gateway.verification_passed)
        with patch.object(self.gateway, 'rpc', return_value={'exit_code': 0, 'timed_out': True}):
            self.gateway.run_command(['repair'], purpose='repair')
            self.gateway.run_command(['check'], purpose='verify')
        self.assertFalse(self.gateway.repair_verified)

    def test_verify_only_state_is_grounded_without_any_mutation(self):
        self.gateway.run_command(['check'], purpose='verify')
        self.assertTrue(self.gateway.verification_attempted)
        self.assertTrue(self.gateway.verification_passed)
        self.assertFalse(self.gateway.repair_verified)
        with patch.object(self.gateway, 'rpc', return_value={'exit_code':1}):
            self.gateway.run_command(['check'], purpose='verify')
        self.assertFalse(self.gateway.verification_passed)

    def test_typed_verify_only_report_outputs_verified_not_repaired(self):
        from pydantic_ai.models.function import FunctionModel
        from pydantic_ai.messages import ModelResponse, ToolCallPart
        calls = []
        def model(messages, info):
            calls.append(1)
            if len(calls)==1:
                return ModelResponse(parts=[ToolCallPart('run_command',{'argv':['inspect']})])
            if len(calls)==2:
                return ModelResponse(parts=[ToolCallPart('run_command',{'argv':['check'],'purpose':'verify'})])
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,{'summary':'复测正常','root_cause':'当前无异常',
                'actions':[],'verification':['固定复测通过'],'solution':'继续观察','repaired':False})])
        with patch.object(runner,'OpenAIChatModel',return_value=FunctionModel(model)):
            value=asyncio.run(runner.analyze({'config':{'model':'test','api_key':'synthetic','base_url':'https://invalid.example/v1'},
                'gateway_url':self.gateway.url,'tool_token':'synthetic-token','problem':'verify',
                'context':{'inspect_argv':['inspect'],'verify_argv':['check'],'operation_mode':'verify','repair_allowed':False}}))
        self.assertEqual(value['outcome'],'verified')
        self.assertTrue(value['verification_passed'])
        self.assertFalse(value['repaired'])

    def test_research_pipeline_orders_current_inspection_then_kb_then_approved_source(self):
        from pydantic_ai.models.function import FunctionModel
        from pydantic_ai.messages import ModelResponse, ToolCallPart
        calls=[]
        def model(messages,info):
            calls.append(1)
            sequence=[('research_sources',{'operation':'catalog'}),
                ('run_command',{'argv':['inspect']}),('search_project_knowledge',{'query':'telemetry'}),
                ('research_sources',{'operation':'catalog'}),
                ('research_sources',{'operation':'read_source','source_id':'rai','path':'README.md','gap':'KB未说明当前Humble兼容范围'})]
            if len(calls)<=len(sequence):
                name,args=sequence[len(calls)-1];return ModelResponse(parts=[ToolCallPart(name,args)])
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,{'summary':'已检索并确认待查','root_cause':'证据不足',
                'actions':[],'verification':['已取当前证据'],'solution':'参考官方兼容说明继续核查','repaired':False})])
        with patch.object(runner,'OpenAIChatModel',return_value=FunctionModel(model)):
            value=asyncio.run(runner.analyze({'config':{'model':'test','api_key':'synthetic','base_url':'https://invalid.example/v1'},
                'gateway_url':self.gateway.url,'tool_token':'synthetic-token','problem':'diagnose',
                'context':{'inspect_argv':['inspect'],'repair_allowed':False,'require_knowledge_search':True}}))
        self.assertFalse(value['repaired'])
        self.assertEqual([body['operation'] for _,body in self.requests],['run','knowledge','catalog','read_source'])

    def test_secret_redaction(self):
        value = runner.redact({"summary": "synthetic-token key-value", "items": ["key-value"], "synthetic-token": "safe"}, ["synthetic-token", "key-value"])
        self.assertNotIn("synthetic-token", json.dumps(value))
        self.assertNotIn("key-value", json.dumps(value))

    def test_real_typed_agent_and_langgraph_lifecycle(self):
        from pydantic_ai.models.function import FunctionModel
        from pydantic_ai.messages import ModelResponse, ToolCallPart
        calls = []
        def model(messages, info):
            index = len(calls)
            calls.append(index)
            if index == 0:
                return ModelResponse(parts=[ToolCallPart("read_file", {"path": "/config"})])
            if index == 1:
                return ModelResponse(parts=[ToolCallPart("patch_file", {"path": "/config", "expected_sha256": "a" * 64, "content": "after"})])
            if index == 2:
                return ModelResponse(parts=[ToolCallPart("run_command", {"argv": ["check-config"], "purpose": "verify"})])
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {
                "summary": "已验证", "root_cause": "配置不一致", "actions": ["更新配置"],
                "verification": ["检查返回0"], "solution": "已更新", "repaired": True,
            })])
        with patch.object(runner, "OpenAIChatModel", return_value=FunctionModel(model)):
            result = asyncio.run(runner.analyze({"config": {"api_key": "synthetic-key", "base_url": "https://invalid.example/v1", "model": "test"},
                "gateway_url": self.gateway.url, "tool_token": "synthetic-token", "problem": "synthetic", "context": {'verify_argv':['check-config']}}))
        self.assertTrue(result["repaired"])
        self.assertEqual(len(self.requests), 3)

    def test_holmes_subprocess_receives_secrets_only_via_stdin(self):
        from pydantic_ai.models.function import FunctionModel
        from pydantic_ai.messages import ModelResponse, ToolCallPart
        calls = []
        def model(messages, info):
            calls.append(1)
            if len(calls) == 1:
                return ModelResponse(parts=[ToolCallPart('consult_specialist', {'name': 'holmes'})])
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {'summary': '只读调查',
                'root_cause': '待进一步定位', 'actions': [], 'verification': ['已读取'], 'solution': '待处理', 'repaired': False})])
        response = SimpleNamespace(returncode=0, stdout=json.dumps({'integration': 'holmes', 'ready': True,
            'successful_inspections': 1, 'inspection_calls': 1, 'summary': '当前配置异常'}))
        with patch.object(runner, 'OpenAIChatModel', return_value=FunctionModel(model)), \
             patch.object(runner.os.path, 'isfile', return_value=True), \
             patch.object(runner.subprocess, 'run', return_value=response) as process:
            result = asyncio.run(runner.analyze({'config': {'api_key': 'synthetic-key', 'base_url': 'https://invalid.example/v1', 'model': 'test'},
                'gateway_url': self.gateway.url, 'tool_token': 'synthetic-token', 'problem': 'synthetic', 'context': {'inspect_argv': ['fixed-inspect'], 'required_specialists': ['holmes']}}))
        self.assertFalse(result['repaired'])
        argv = process.call_args.args[0]
        self.assertNotIn('synthetic-key', json.dumps(argv))
        self.assertNotIn('synthetic-token', json.dumps(argv))
        child = json.loads(process.call_args.kwargs['input'])
        self.assertEqual(child['inspect_argv'], ['fixed-inspect'])
        self.assertEqual(child['config']['api_key'], 'synthetic-key')

    def test_holmes_internal_http_service_works_without_local_dependencies(self):
        from pydantic_ai.models.function import FunctionModel
        from pydantic_ai.messages import ModelResponse, ToolCallPart
        calls = []
        def model(messages, info):
            calls.append(1)
            if len(calls) == 1:
                return ModelResponse(parts=[ToolCallPart('consult_specialist', {'name': 'holmes'})])
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {'summary':'只读调查', 'root_cause':'待定位',
                'actions':[], 'verification':['已读取'], 'solution':'未修改', 'repaired':False})])
        response = SimpleNamespace(read=lambda n: json.dumps({'integration':'holmes', 'ready':True, 'successful_inspections':1}).encode())
        from unittest.mock import MagicMock
        manager = MagicMock()
        manager.__enter__.return_value = response
        opener = SimpleNamespace(open=MagicMock(return_value=manager))
        with patch.dict(runner.os.environ, {'HOLMES_AGENT_URL':'http://internal-holmes:8093', 'HOLMES_SERVICE_TOKEN':'synthetic-service-token-minimum24'}), \
             patch.object(runner, 'OpenAIChatModel', return_value=FunctionModel(model)), \
             patch.object(runner, 'build_opener', return_value=opener), \
             patch.object(runner.os.path, 'isfile', return_value=False):
            result = asyncio.run(runner.analyze({'config': {'model':'test', 'api_key':'synthetic-key', 'base_url':'https://invalid.example/v1'},
                'gateway_url':self.gateway.url, 'tool_token':'synthetic-tool', 'problem':'synthetic',
                'context':{'inspect_argv':['fixed-inspect'], 'required_specialists':['holmes']}}))
        self.assertFalse(result['repaired'])
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, 'http://internal-holmes:8093/investigate')
        self.assertEqual(json.loads(request.data)['inspect_argv'], ['fixed-inspect'])


if __name__ == "__main__":
    unittest.main()

class LocationReceiptTest(unittest.TestCase):
    def test_repair_location_is_extracted_only_from_successful_execution_receipt(self):
        gateway=runner.Gateway('http://unused','synthetic',inspect_argv=['inspect'],verify_argv=['verify'],repair_argv=['repair','--sha'])
        gateway.inspected=True
        receipt={'changes':[{'target_hostname':'robot177','path':'/robot/config.json','key':'telemetry_enabled','before_line':1,'after_line':4,'before':False,'after':True,'backup':'/robot/config.json.backup-1'}]}
        with patch.object(gateway,'rpc',return_value={'ok':True,'exit_code':0,'stdout':json.dumps(receipt)}):
            gateway.run_command(['repair','--sha','a'*64],purpose='repair')
        self.assertEqual(gateway.repair_locations[0]['path'],'/robot/config.json')
        self.assertEqual(gateway.repair_locations[0]['line'],4)
        self.assertEqual(gateway.repair_locations[0]['before_line'],1)
        self.assertFalse(gateway.repair_verified)
