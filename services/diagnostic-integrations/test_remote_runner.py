"""Regression tests using synthetic credentials and a real local HTTP gateway."""
import importlib.util
import json
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
import asyncio
import io
import hashlib
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SPEC = importlib.util.spec_from_file_location("remote_runner", Path(__file__).parents[1] / "diagnostic-agent/remote_runner.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class GatewayTest(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.responder = None
        fixture = self
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
                if fixture.responder is not None:
                    response=fixture.responder(body)
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

    def test_configuration_repair_uses_observed_snapshot_without_model_copying_hash(self):
        self.gateway.verification_scope='configuration_validation'
        self.gateway.repair_argv=['daq-local-diagnostics-v1','repair']
        self.gateway.inspect_argv=['daq-local-diagnostics-v1','inspect']
        self.responder=lambda body: {'exit_code':1,'stdout':json.dumps({
            'scope':'configuration_validation','checks':[{'state':'fail'}],
            'configuration':{'state':'fail','repair_allowed':True,'repair_authority':'verified_device_baseline',
                             'snapshot_sha256':'a'*64}})} if body.get('argv')==self.gateway.inspect_argv else {'exit_code':0}
        self.gateway.run_command(self.gateway.inspect_argv)
        self.gateway.apply_configuration_repair()
        self.assertEqual(self.requests[-1][1]['argv'],['daq-local-diagnostics-v1','repair','a'*64])
        self.assertEqual(self.requests[-1][1]['purpose'],'repair')

    def test_configuration_repair_never_guesses_an_unobserved_snapshot(self):
        self.gateway.verification_scope='configuration_validation'
        self.gateway.repair_argv=['daq-local-diagnostics-v1','repair']
        with self.assertRaisesRegex(ValueError,'configuration_snapshot_not_observed'):
            self.gateway.apply_configuration_repair()
        self.assertEqual(self.requests,[])

    def test_source_page_registers_only_the_read_file_lines(self):
        self.gateway.observe_locations({'source':'local_source_snapshot','path':'src/solver.cpp',
            'content_start_line':42,'content':'actual source\n/never/read.cpp:999\n'})
        self.assertIn(('src/solver.cpp',42),self.gateway.observed_locations)
        self.assertIn(('src/solver.cpp',43),self.gateway.observed_locations)
        self.assertNotIn(('/never/read.cpp',999),self.gateway.observed_locations)
        self.assertNotIn(('src/solver.cpp',44),self.gateway.observed_locations)

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

    def test_fixed_robot_repair_and_allowlisted_collector_patch_share_final_verification(self):
        gateway=runner.Gateway('http://unused','synthetic',inspect_argv=['inspect-both'],verify_argv=['verify-both'],
            repair_argv=['robot-repair','--expected-sha256'],editable_files=['collector-config.json'],require_knowledge=True)
        with patch.object(gateway,'rpc',return_value={'ok':True,'exit_code':0}):gateway.run_command(['inspect-both'])
        with patch.object(gateway,'rpc',return_value={'content':'old collector config','sha256':'a'*64}):gateway.read_file('collector-config.json')
        with self.assertRaises(ValueError):gateway.patch_file('collector-config.json','a'*64,'new collector config')
        gateway.knowledge_searched=True
        with self.assertRaises(ValueError):gateway.patch_file('collector-config.json','b'*64,'new collector config')
        with patch.object(gateway,'rpc',return_value={'ok':True,'exit_code':0}):
            gateway.run_command(['robot-repair','--expected-sha256','c'*64],purpose='repair')
            gateway.run_command(['verify-both'],purpose='verify')
        self.assertTrue(gateway.repair_verified)
        with patch.object(gateway,'rpc',return_value={'ok':True,'sha256':'d'*64}):
            gateway.patch_file('collector-config.json','a'*64,'new collector config')
        self.assertFalse(gateway.repair_verified or gateway.verification_passed)
        self.assertEqual(gateway.mutation,2)
        with patch.object(gateway,'rpc',return_value={'ok':True,'exit_code':0}):gateway.run_command(['verify-both'],purpose='verify')
        self.assertTrue(gateway.repair_verified)
        self.assertIn('写入授权文件完成：collector-config.json',gateway.execution_summary()[0])
        self.assertEqual(gateway.repair_locations,[])  # no invented line numbers for generic patch

    def test_collector_patch_allowlist_does_not_authorize_other_paths_or_readonly_tasks(self):
        gateway=runner.Gateway('http://unused','synthetic',repair_argv=['robot-repair'],editable_files=['collector-config.json'])
        gateway.inspected=True;gateway.read_hashes={'collector-config.json':'a'*64,'other-config.json':'a'*64}
        with patch.object(gateway,'rpc') as rpc:
            with self.assertRaises(ValueError):gateway.patch_file('other-config.json','a'*64,'new')
            gateway.repair_allowed=False
            with self.assertRaises(ValueError):gateway.patch_file('collector-config.json','a'*64,'new')
        rpc.assert_not_called()

    def test_absolute_patch_alias_is_only_from_successful_allowlisted_read_receipt(self):
        gateway=runner.Gateway('http://unused','synthetic',repair_argv=['robot-repair'],editable_files=['collector-config.json'])
        gateway.inspected=True
        with patch.object(gateway,'rpc',return_value={'ok':True,'content':'before','sha256':'a'*64,
            'resolved_path':'/approved/collector-config.json'}):
            gateway.read_file('collector-config.json')
        with patch.object(gateway,'rpc') as rpc:
            with self.assertRaises(runner.ToolValidationError):gateway.patch_file('/approved/collector-config.json','c'*64,'after')
            gateway.repair_allowed=False
            with self.assertRaises(runner.ToolValidationError):gateway.patch_file('/approved/collector-config.json','a'*64,'after')
            gateway.repair_allowed=True;gateway.require_knowledge=True
            with self.assertRaises(runner.ToolValidationError):gateway.patch_file('/approved/collector-config.json','a'*64,'after')
            gateway.knowledge_searched=True
        rpc.assert_not_called()
        with patch.object(gateway,'rpc',return_value={'ok':True,'sha256':'b'*64}) as rpc:
            gateway.patch_file('/approved/collector-config.json','a'*64,'after')
        self.assertEqual(rpc.call_args.args[0]['path'],'collector-config.json')
        self.assertEqual(rpc.call_count,1)

    def test_unapproved_or_failed_read_cannot_grant_an_absolute_patch_alias(self):
        gateway=runner.Gateway('http://unused','synthetic',repair_argv=['robot-repair'],editable_files=['collector-config.json'])
        gateway.inspected=True
        with patch.object(gateway,'rpc',return_value={'ok':True,'content':'before','sha256':'a'*64,
            'resolved_path':'/unapproved/other.json'}):gateway.read_file('other.json')
        with patch.object(gateway,'rpc',return_value={'ok':False,'exit_code':1,'content':'failed','sha256':'a'*64,
            'resolved_path':'/approved/collector-config.json'}):gateway.read_file('collector-config.json')
        with patch.object(gateway,'rpc') as rpc:
            for path in ['/unapproved/other.json','/approved/collector-config.json','/unknown/collector-config.json']:
                with self.assertRaises(runner.ToolValidationError):gateway.patch_file(path,'a'*64,'after')
        rpc.assert_not_called()

    def test_agent_can_patch_successful_read_absolute_receipt_alias_and_verify(self):
        from pydantic_ai.models.function import FunctionModel
        from pydantic_ai.messages import ModelResponse,ToolCallPart
        turns=[]
        def respond(body):
            if body['operation']=='read_file':return {'ok':True,'content':'before','sha256':'a'*64,'resolved_path':'/approved/collector-config.json'}
            if body['operation']=='patch_file':
                self.assertEqual(body['path'],'collector-config.json')
                return {'ok':True,'sha256':'b'*64,'resolved_path':'/approved/collector-config.json'}
            return {'ok':True,'exit_code':0}
        self.responder=respond
        def model(messages,info):
            index=len(turns);turns.append(index)
            sequence=[('run_command',{'argv':['inspect']}),('read_file',{'path':'collector-config.json'}),
                ('patch_file',{'path':'/approved/collector-config.json','expected_sha256':'a'*64,'content':'after'}),
                ('run_command',{'argv':['check'],'purpose':'verify'})]
            if index<len(sequence):
                name,args=sequence[index];return ModelResponse(parts=[ToolCallPart(name,args)])
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,{'summary':'已修复并复测','root_cause':'已读取配置异常',
                'actions':[],'verification':[],'solution':'继续观察','repaired':True})])
        with patch.object(runner,'OpenAIChatModel',return_value=FunctionModel(model)):
            result=asyncio.run(runner.analyze({'config':{'model':'test','api_key':'synthetic','base_url':'https://invalid.example/v1'},
                'gateway_url':self.gateway.url,'tool_token':'synthetic-token','problem':'修复',
                'context':{'inspect_argv':['inspect'],'verify_argv':['check'],'repair_argv':['robot-repair'],
                    'editable_files':['collector-config.json']}}))
        self.assertTrue(result['repaired'])
        self.assertEqual(len(turns),5)

    def test_agent_forwards_only_trusted_context_collector_editable_files(self):
        from pydantic_ai.models.function import FunctionModel
        from pydantic_ai.messages import ModelResponse,ToolCallPart
        turns=[]
        def model(messages,info):
            index=len(turns);turns.append(index)
            sequence=[('run_command',{'argv':['inspect']}),('read_file',{'path':'collector-config.json'}),
                ('patch_file',{'path':'collector-config.json','expected_sha256':'a'*64,'content':'after'}),
                ('run_command',{'argv':['check'],'purpose':'verify'})]
            if index<len(sequence):
                name,args=sequence[index];return ModelResponse(parts=[ToolCallPart(name,args)])
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,{'summary':'采集机配置已修复并复测',
                'root_cause':'当前已读取的采集机配置异常','actions':[],'verification':[],
                'solution':'继续观察','repaired':True})])
        with patch.object(runner,'OpenAIChatModel',return_value=FunctionModel(model)):
            result=asyncio.run(runner.analyze({'config':{'model':'test','api_key':'synthetic','base_url':'https://invalid.example/v1'},
                'gateway_url':self.gateway.url,'tool_token':'synthetic-token','problem':'修复采集机',
                'context':{'operation_mode':'repair','inspect_argv':['inspect'],'verify_argv':['check'],
                    'repair_argv':['robot-repair'],'editable_files':['collector-config.json']}}))
        self.assertTrue(result['repaired'] and result['verification_passed'])
        self.assertEqual([body['operation'] for _,body in self.requests],['run','read_file','patch_file','run'])

    def test_actual_http_joint_receipts_replace_model_locations_with_targeted_absolute_paths(self):
        from pydantic_ai.models.function import FunctionModel
        from pydantic_ai.messages import ModelResponse,ToolCallPart
        turns=[]
        collector={'target_kind':'collector','target_username':'operator','target_ip':'10.10.10.195',
            'target_hostname':'collector195','path':'/approved/collector-config.json','key':'robot_port',
            'before':8001,'after':8002,'backup':'/approved/.collector-config.json.backup'}
        robot={'target_kind':'robot','target_username':'engram','target_ip':'10.10.10.177',
            'target_hostname':'robot177','path':'/approved/robot-config.json','key':'telemetry_enabled',
            'before':False,'after':True,'after_line':4,'before_line':1,'backup':'/approved/.robot-config.json.backup'}
        def respond(body):
            if body['operation']=='read_file':return {'content':'{"robot_port":8001}', 'sha256':'a'*64,
                'resolved_path':'/approved/collector-config.json','target_kind':'collector'}
            if body['operation']=='patch_file':return {'ok':True,'sha256':'b'*64,
                'resolved_path':'/approved/collector-config.json','changes':[collector]}
            if body['operation']=='run' and body['argv'][:1]==['robot-repair']:
                return {'ok':True,'exit_code':0,'stdout':json.dumps({'changes':[robot]})}
            return {'ok':True,'exit_code':0}
        self.responder=respond
        def model(messages,info):
            index=len(turns);turns.append(index)
            sequence=[('run_command',{'argv':['inspect']}),('read_file',{'path':'collector-config.json'}),
                ('patch_file',{'path':'collector-config.json','expected_sha256':'a'*64,'content':'{"robot_port":8002}'}),
                ('run_command',{'argv':['robot-repair','b'*64],'purpose':'repair'}),
                ('run_command',{'argv':['check'],'purpose':'verify'})]
            if index<len(sequence):
                name,args=sequence[index];return ModelResponse(parts=[ToolCallPart(name,args)])
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,{'summary':'两端复测完成','root_cause':'本轮配置已核实',
                'actions':[],'verification':[],'solution':'继续观察','repaired':True,
                'repair_locations':[{'path':'/invented/model.py','line':195}]})])
        with patch.object(runner,'OpenAIChatModel',return_value=FunctionModel(model)):
            value=asyncio.run(runner.analyze({'config':{'model':'test','api_key':'synthetic','base_url':'https://invalid.example/v1'},
                'gateway_url':self.gateway.url,'tool_token':'synthetic-token','problem':'联合已授权修复',
                'context':{'inspect_argv':['inspect'],'verify_argv':['check'],'repair_argv':['robot-repair'],
                    'editable_files':['collector-config.json']}}))
        self.assertTrue(value['repaired'])
        self.assertEqual(len(value['repair_locations']),2)
        actual_collector,actual_robot=value['repair_locations']
        self.assertEqual(actual_collector['target'],'采集电脑：operator@10.10.10.195')
        self.assertEqual(actual_collector['path'],collector['path'])
        self.assertIsNone(actual_collector.get('line'))
        self.assertEqual(actual_collector['before'],8001)
        self.assertEqual(actual_robot['target'],'机器人：engram@10.10.10.177')
        self.assertEqual(actual_robot['line'],4)
        self.assertIn('写入授权文件完成：/approved/collector-config.json',value['actions'])
        self.assertNotIn('/invented/',json.dumps(value))

    def test_model_corrects_invalid_repair_arguments_then_completes_joint_repair(self):
        from pydantic_ai.models.function import FunctionModel
        from pydantic_ai.messages import ModelResponse,ToolCallPart
        turns=[];runtime={}
        def model(messages,info):
            index=len(turns);turns.append(index)
            sequence=[('run_command',{'argv':['inspect']}),('search_project_knowledge',{'query':'collector robot config'}),
                ('read_file',{'path':'collector-config.json'}),
                ('run_command',{'argv':['robot-repair','wrong-sha'],'purpose':'repair'}),
                ('patch_file',{'path':'collector-config.json','expected_sha256':'a'*64,'content':'after'}),
                ('run_command',{'argv':['robot-repair','--expected-sha256','b'*64],'purpose':'repair'}),
                ('run_command',{'argv':['check'],'purpose':'verify'})]
            if index==4:
                self.assertEqual(runtime['gateway'].last_tool_validation_error,'use_configured_repair_prefix_with_current_sha256')
                self.assertEqual(runtime['gateway'].mutation,0)
            if index<len(sequence):
                name,args=sequence[index];return ModelResponse(parts=[ToolCallPart(name,args)])
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,{'summary':'两端已修复并复测',
                'root_cause':'本轮读取的配置异常','actions':[],'verification':[],'solution':'继续观察','repaired':True})])
        with patch.object(runner,'OpenAIChatModel',return_value=FunctionModel(model)):
            value=asyncio.run(runner.analyze({'config':{'model':'test','api_key':'synthetic','base_url':'https://invalid.example/v1'},
                'gateway_url':self.gateway.url,'tool_token':'synthetic-token','problem':'联合修复',
                'context':{'operation_mode':'repair','inspect_argv':['inspect'],'verify_argv':['check'],
                    'repair_argv':['robot-repair','--expected-sha256'],'editable_files':['collector-config.json'],
                    'require_knowledge_search':True}},runtime))
        self.assertTrue(value['repaired'] and value['verification_passed'])
        self.assertEqual(len(turns),8)
        self.assertEqual(runtime['gateway'].mutation,2)
        self.assertFalse(any(body.get('argv')==['robot-repair','wrong-sha'] for _,body in self.requests))

    def test_failed_report_exposes_only_fixed_tool_validation_reason(self):
        gateway=runner.Gateway('http://unused','synthetic',repair_allowed=False)
        gateway.inspected=True
        with patch.object(gateway,'rpc') as rpc:
            with self.assertRaises(runner.ToolValidationError) as error:
                gateway.run_command(['arbitrary-secret-command'],purpose='inspect')
        rpc.assert_not_called()
        value=runner.failed_analysis({'context':{}},{'gateway':gateway},error.exception)
        self.assertEqual(value['agent_error_code'],'ToolValidationError')
        self.assertEqual(value['tool_validation_reason'],'repair_not_authorized')
        self.assertNotIn('arbitrary-secret-command',json.dumps(value))

    def test_model_can_correct_patch_sha_without_dispatching_the_invalid_write(self):
        from pydantic_ai.models.function import FunctionModel
        from pydantic_ai.messages import ModelResponse,ToolCallPart
        turns=[]
        def model(messages,info):
            index=len(turns);turns.append(index)
            sequence=[('run_command',{'argv':['inspect']}),('read_file',{'path':'collector-config.json'}),
                ('patch_file',{'path':'collector-config.json','expected_sha256':'b'*64,'content':'after'}),
                ('patch_file',{'path':'collector-config.json','expected_sha256':'a'*64,'content':'after'}),
                ('run_command',{'argv':['check'],'purpose':'verify'})]
            if index<len(sequence):
                name,args=sequence[index];return ModelResponse(parts=[ToolCallPart(name,args)])
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,{'summary':'采集机修复已复测','root_cause':'已读取配置异常',
                'actions':[],'verification':[],'solution':'继续观察','repaired':True})])
        with patch.object(runner,'OpenAIChatModel',return_value=FunctionModel(model)):
            value=asyncio.run(runner.analyze({'config':{'model':'test','api_key':'synthetic','base_url':'https://invalid.example/v1'},
                'gateway_url':self.gateway.url,'tool_token':'synthetic-token','problem':'修复采集机',
                'context':{'inspect_argv':['inspect'],'verify_argv':['check'],'editable_files':['collector-config.json'],
                    'repair_argv':['robot-repair']}}))
        self.assertTrue(value['repaired'])
        writes=[body for _,body in self.requests if body['operation']=='patch_file']
        self.assertEqual(len(writes),1)
        self.assertEqual(writes[0]['expected_sha256'],'a'*64)

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

    def test_model_cannot_publish_unexecuted_repair_or_verification_as_actions(self):
        from pydantic_ai.models.function import FunctionModel
        from pydantic_ai.messages import ModelResponse, ToolCallPart
        turns=[]
        def model(messages,info):
            turns.append(1)
            if len(turns)==1:
                return ModelResponse(parts=[ToolCallPart('run_command',{'argv':['inspect']})])
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,{'summary':'证据待补','root_cause':'尚未确认',
                'actions':['已修改 /invented/source.cpp 第999行'],'verification':['测试通过'],
                'solution':'建议补充配置证据','repaired':False})])
        with patch.object(runner,'OpenAIChatModel',return_value=FunctionModel(model)):
            result=asyncio.run(runner.analyze({'config':{'model':'test','api_key':'synthetic','base_url':'https://invalid.example/v1'},
                'gateway_url':self.gateway.url,'tool_token':'synthetic-token','problem':'diagnose',
                'context':{'inspect_argv':['inspect'],'repair_allowed':False,'operation_mode':'diagnose'}}))
        self.assertNotIn('/invented/source.cpp',json.dumps(result['actions']))
        self.assertNotIn('测试通过',result['verification'])
        self.assertIn('未执行固定复测',' '.join(result['verification']))
        self.assertFalse(result['repaired'])

    def test_invented_root_cause_path_line_retries_instead_of_publishing(self):
        from pydantic_ai.models.function import FunctionModel
        from pydantic_ai.messages import ModelResponse, ToolCallPart
        turns=[]
        def model(messages,info):
            turns.append(1)
            if len(turns)==1:
                return ModelResponse(parts=[ToolCallPart('run_command',{'argv':['inspect']})])
            if len(turns)==3:
                retries=[part.content for message in messages for part in message.parts if getattr(part,'part_kind','') in {'retry-prompt','tool-return'}]
                self.assertTrue(any('/invented/Dockerfile' in str(value) and 'untrusted_model_claim' in str(value) for value in retries))
            root_cause='/invented/Dockerfile:999 的参数错误' if len(turns)==2 else '当前证据不足，未读取源码'
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,{'summary':'待查','root_cause':root_cause,
                'actions':[],'verification':[],'solution':'补充源码后定位','repaired':False})])
        runtime={}
        with patch.object(runner,'OpenAIChatModel',return_value=FunctionModel(model)):
            result=asyncio.run(runner.analyze({'config':{'model':'test','api_key':'synthetic','base_url':'https://invalid.example/v1'},
                'gateway_url':self.gateway.url,'tool_token':'synthetic-token','problem':'diagnose',
                'context':{'inspect_argv':['inspect'],'repair_allowed':False}},runtime))
        self.assertEqual(len(turns),3)
        self.assertNotIn('/invented/Dockerfile',result['root_cause'])
        self.assertEqual(runtime['gateway'].last_validation_error,'')
        self.assertEqual(runtime['gateway'].validation_mismatches,[])

    def test_current_file_line_reference_remains_supported(self):
        from pydantic_ai.models.function import FunctionModel
        from pydantic_ai.messages import ModelResponse, ToolCallPart
        turns=[]
        def model(messages,info):
            turns.append(1)
            if len(turns)==1:
                return ModelResponse(parts=[ToolCallPart('read_file',{'path':'/actual/config.py'})])
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,{'summary':'已读取当前配置',
                'root_cause':'机器人（engram@10.10.10.177:18777）；/actual/config.py:1 为实际读取内容，原因待进一步确认','actions':[],
                'verification':[],'solution':'继续只读核查','repaired':False})])
        with patch.object(runner,'OpenAIChatModel',return_value=FunctionModel(model)):
            result=asyncio.run(runner.analyze({'config':{'model':'test','api_key':'synthetic','base_url':'https://invalid.example/v1'},
                'gateway_url':self.gateway.url,'tool_token':'synthetic-token','problem':'diagnose',
                'context':{'repair_allowed':False}}))
        self.assertEqual(len(turns),2)
        self.assertIn('/actual/config.py:1',result['root_cause'])
        self.assertEqual(result['actions'],['读取现场文件完成：/actual/config.py'])

    def test_path_line_handles_do_not_treat_network_ports_as_source_lines(self):
        self.assertEqual(runner.path_lines('10.10.10.177:8093 与 https://example.com:443 是端点'),set())
        self.assertEqual(runner.path_lines('/actual/Dockerfile:9 与 src/main.py:12'),
                         {('/actual/Dockerfile',9),('src/main.py',12)})
        self.assertEqual(runner.path_lines('机器人（engram@10.10.10.177:18777），实际配置 /path.json:4'),
                         {('/path.json',4)})
        self.assertEqual(runner.path_lines('/files/engram@10.10.10.177:4'),{('/files/engram@10.10.10.177',4)})

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

    def test_one_agent_repairs_two_faults_and_requires_the_same_round_final_check(self):
        from pydantic_ai.models.function import FunctionModel
        from pydantic_ai.messages import ModelResponse,ToolCallPart
        state={'telemetry_enabled':False,'accept_commands':False}
        observed=[];turns=[];runtime={}
        def digest():return hashlib.sha256(json.dumps(state,sort_keys=True).encode()).hexdigest()
        def respond(body):
            if body['operation']=='knowledge':
                return {'source':'project_knowledge','results':[{'title':'连接与指令配置核查','content':'两项均需就绪后复测。'}],'case_history':[]}
            argv=body['argv']
            if argv==['inspect-multi']:
                return {'ok':True,'exit_code':0,'stdout':json.dumps({'config':state,'config_sha256':digest()})}
            if argv[:2]==['repair-multi','--expected-sha256']:
                self.assertEqual(argv[2],digest())
                key=next(key for key,value in state.items() if value is False)
                state[key]=True
                observed.append('repair:'+key)
                return {'ok':True,'exit_code':0,'stdout':json.dumps({'config_sha256':digest(),'changes':[{'path':'/robot/config.json',
                    'key':key,'line':2 if key=='telemetry_enabled' else 3,'before':False,'after':True}]})}
            self.assertEqual(argv,['verify-multi'])
            unresolved=[key for key,value in state.items() if value is False]
            observed.append('verify:'+('failed' if unresolved else 'passed'))
            return {'ok':not unresolved,'exit_code':1 if unresolved else 0,'stdout':json.dumps({'unresolved':unresolved,'config_sha256':digest()})}
        self.responder=respond
        def model(messages,info):
            index=len(turns);turns.append(index)
            known_sha=''
            for message in messages:
                for part in message.parts:
                    if getattr(part,'part_kind','')=='tool-return' and isinstance(part.content,dict):
                        try:receipt=json.loads(part.content.get('stdout','{}'))
                        except (ValueError,TypeError):continue
                        if isinstance(receipt,dict) and isinstance(receipt.get('config_sha256'),str):
                            known_sha=receipt['config_sha256']
            sequence=[('run_command',{'argv':['inspect-multi']}),
                ('search_project_knowledge',{'query':'连接与指令配置'}),
                ('run_command',{'argv':['repair-multi','--expected-sha256',known_sha],'purpose':'repair'}),
                ('run_command',{'argv':['verify-multi'],'purpose':'verify'})]
            if index<len(sequence):
                name,args=sequence[index];return ModelResponse(parts=[ToolCallPart(name,args)])
            if index==4:
                self.assertFalse(runtime['gateway'].repair_verified)
                return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,{'summary':'第一项已恢复',
                    'root_cause':'仍有指令配置未就绪','actions':[],'verification':[],'solution':'继续处理剩余项','repaired':True})])
            if index==5:
                self.assertEqual(runtime['gateway'].last_validation_error,'repair_not_verified')
                return ModelResponse(parts=[ToolCallPart('run_command',{'argv':['repair-multi','--expected-sha256',known_sha],'purpose':'repair'})])
            if index==6:
                self.assertFalse(runtime['gateway'].verification_passed)
                return ModelResponse(parts=[ToolCallPart('run_command',{'argv':['verify-multi'],'purpose':'verify'})])
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,{'summary':'两项配置均恢复并通过本轮最终复测',
                'root_cause':'遥测与指令配置分别未启用','actions':[],'verification':[],'solution':'无需额外处理','repaired':True})])
        with patch.object(runner,'OpenAIChatModel',return_value=FunctionModel(model)):
            result=asyncio.run(runner.analyze({'config':{'model':'test','api_key':'synthetic','base_url':'https://invalid.example/v1'},
                'gateway_url':self.gateway.url,'tool_token':'synthetic-token','problem':'整套诊断与修复',
                'context':{'operation_mode':'repair','inspect_argv':['inspect-multi'],'verify_argv':['verify-multi'],
                    'repair_argv':['repair-multi','--expected-sha256'],'require_knowledge_search':True}},runtime))
        self.assertEqual(observed,['repair:telemetry_enabled','verify:failed','repair:accept_commands','verify:passed'])
        self.assertEqual([body['operation'] for _,body in self.requests],['run','knowledge','run','run','run','run'])
        self.assertEqual(len(turns),8)
        self.assertTrue(result['repaired'] and result['verification_passed'])
        self.assertEqual(result['outcome'],'repaired')
        self.assertEqual([row['key'] for row in result['repair_locations']],['telemetry_enabled','accept_commands'])

    def test_partial_multi_fault_repair_remains_unresolved_and_reports_remaining_fault(self):
        from pydantic_ai.models.function import FunctionModel
        from pydantic_ai.messages import ModelResponse,ToolCallPart
        state={'telemetry_enabled':False,'accept_commands':False};turns=[]
        def respond(body):
            if body['operation']=='knowledge':return {'results':[],'case_history':[]}
            argv=body['argv']
            if argv==['inspect-partial']:
                return {'ok':True,'exit_code':0,'stdout':json.dumps({'config':state})}
            if argv[:1]==['repair-first']:
                state['telemetry_enabled']=True
                return {'ok':True,'exit_code':0,'stdout':'{"changes":[]}'}
            self.assertEqual(argv,['verify-partial'])
            return {'ok':False,'exit_code':1,'stdout':'{"unresolved":["accept_commands"]}'}
        self.responder=respond
        def model(messages,info):
            index=len(turns);turns.append(index)
            sequence=[('run_command',{'argv':['inspect-partial']}),('search_project_knowledge',{'query':'telemetry commands'}),
                ('run_command',{'argv':['repair-first','a'*64],'purpose':'repair'}),
                ('run_command',{'argv':['verify-partial'],'purpose':'verify'})]
            if index<len(sequence):
                name,args=sequence[index];return ModelResponse(parts=[ToolCallPart(name,args)])
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,{'summary':'遥测项已处理，整体仍未恢复',
                'root_cause':'accept_commands 尚未就绪；遥测项已处理','actions':[],
                'verification':[],'solution':'accept_commands 需要现场授权后处理，再执行固定复测。','repaired':False})])
        with patch.object(runner,'OpenAIChatModel',return_value=FunctionModel(model)):
            result=asyncio.run(runner.analyze({'config':{'model':'test','api_key':'synthetic','base_url':'https://invalid.example/v1'},
                'gateway_url':self.gateway.url,'tool_token':'synthetic-token','problem':'处理两项异常',
                'context':{'operation_mode':'repair','inspect_argv':['inspect-partial'],'verify_argv':['verify-partial'],
                    'repair_argv':['repair-first'],'require_knowledge_search':True}}))
        self.assertEqual(state,{'telemetry_enabled':True,'accept_commands':False})
        self.assertFalse(result['repaired'] or result['verification_passed'])
        self.assertEqual(result['outcome'],'unresolved')
        self.assertIn('accept_commands',result['root_cause'])
        self.assertIn('现场授权',result['solution'])
        self.assertIn('失败',' '.join(result['verification']))
        self.assertEqual(len(turns),5)

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
        response = SimpleNamespace(returncode=0, stdout=json.dumps({'integration': 'holmes', 'ready': True, 'investigation_executed':True,
            'successful_inspections': 1, 'inspection_calls': 1, 'summary': '当前配置异常'}))
        with patch.object(runner, 'OpenAIChatModel', return_value=FunctionModel(model)), \
             patch.object(runner.os.path, 'isfile', return_value=True), \
             patch.object(runner.subprocess, 'run', return_value=response) as process:
            result = asyncio.run(runner.analyze({'config': {'api_key': 'synthetic-key', 'base_url': 'https://invalid.example/v1', 'model': 'test'},
                'gateway_url': self.gateway.url, 'tool_token': 'synthetic-token', 'problem': 'synthetic', 'context': {'inspect_argv': ['fixed-inspect'], 'required_specialists': ['holmes']}}))
        self.assertFalse(result['repaired'])
        self.assertIn('Holmes 只读检查完成',result['actions'])
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


class DiagnosticReasoningTest(unittest.TestCase):
    setUp=GatewayTest.setUp
    tearDown=GatewayTest.tearDown
    # Reuse the local HTTP gateway fixture without inheriting the existing cases.
    def test_configuration_verification_never_proves_business_recovery(self):
        self.gateway.verification_scope='configuration_validation'
        self.gateway.run_command(['inspect'])
        with patch.object(self.gateway,'rpc',return_value={'exit_code':0,'stdout':json.dumps({'configuration':{
            'repair':{'state':'applied','changed':True}}})}):
            self.gateway.run_command(['repair'],purpose='repair')
        self.gateway.run_command(['check'],purpose='verify')
        self.assertTrue(self.gateway.verification_passed)
        self.assertFalse(self.gateway.repair_verified)
        self.assertTrue(self.gateway.configuration_repaired)
        self.assertIn('配置',' '.join(self.gateway.execution_summary()[1]))
        self.assertIn('业务',' '.join(self.gateway.execution_summary()[1]))

    def test_limited_verify_mode_does_not_emit_business_verified_outcome(self):
        from pydantic_ai.models.function import FunctionModel
        from pydantic_ai.messages import ModelResponse,ToolCallPart
        for scope in ('configuration_validation','read_only_connectivity','readonly_connectivity'):
            turns=[]
            def model(messages,info):
                index=len(turns);turns.append(index)
                if index==0:return ModelResponse(parts=[ToolCallPart('run_command',{'argv':['inspect']})])
                if index==1:return ModelResponse(parts=[ToolCallPart('run_command',{'argv':['check'],'purpose':'verify'})])
                return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,{'summary':'限定检查通过，业务待验收',
                    'root_cause':'本轮检查未覆盖原业务故障','actions':[],'verification':[],
                    'solution':'原失败业务操作须单独验收','repaired':False})])
            with patch.object(runner,'OpenAIChatModel',return_value=FunctionModel(model)):
                value=asyncio.run(runner.analyze({'config':{'model':'test','api_key':'synthetic','base_url':'https://invalid.example/v1'},
                    'gateway_url':self.gateway.url,'tool_token':'synthetic-token','context':{'inspect_argv':['inspect'],
                        'verify_argv':['check'],'operation_mode':'verify','verification_scope':scope,'repair_allowed':False}}))
            self.assertEqual(value['outcome'],'unresolved')
            self.assertTrue(value['verification_passed'])
            self.assertFalse(value['business_verified'])
            self.assertTrue(value['needs_business_verification'])
            self.assertEqual(value['configuration_verified'],scope=='configuration_validation')

    def test_written_runtime_unverified_receipt_keeps_actual_changes_without_success_claim(self):
        gateway=runner.Gateway(self.gateway.url,'synthetic-token',inspect_argv=['inspect'],verify_argv=['check'],
            repair_argv=['repair-config'],verification_scope='configuration_validation')
        change={'path':'/state/overrides/config.yaml','key':'initial_joint_states.arm[0]',
            'before':3.3,'after':0.3,'backup':'/state/overrides/config.yaml.backup','target_kind':'collector'}
        self.responder=lambda body: {'ok':False,'exit_code':1,'stdout':json.dumps({'scope':'configuration_validation',
            'configuration':{'repair':{'state':'written_runtime_unverified','changed':['initial_joint_states.arm[0]'],
                'changes':[change]}}})} if body.get('argv',[])[:1]==['repair-config'] else             {'ok':False,'exit_code':1} if body.get('argv')==['check'] else {'exit_code':0}
        gateway.run_command(['inspect'])
        gateway.run_command(['repair-config','a'*64],purpose='repair')
        gateway.run_command(['check'],purpose='verify')
        self.assertFalse(gateway.repair_verified or gateway.configuration_repaired or gateway.verification_passed)
        self.assertEqual(gateway.successful_mutation,0)
        self.assertEqual(gateway.repair_locations[0]['path'],change['path'])
        self.assertEqual(gateway.repair_locations[0]['backup'],change['backup'])
        self.assertIn('配置已写入，验证未通过',gateway.execution_summary()[0])
        result=runner.failed_analysis({'context':{}},{'gateway':gateway},TimeoutError())
        self.assertEqual(result['repair_locations'][0]['path'],change['path'])
        with self.assertRaisesRegex(runner.ToolValidationError,'unchanged_repair_already_attempted'):
            gateway.run_command(['repair-config','a'*64],purpose='repair')

    def test_same_repair_without_changed_current_evidence_is_not_replayed(self):
        self.gateway.run_command(['inspect'])
        with patch.object(self.gateway,'rpc',return_value={'exit_code':1}):
            self.gateway.run_command(['repair'],purpose='repair')
            self.gateway.run_command(['check'],purpose='verify')
        self.gateway.run_command(['inspect'])
        with self.assertRaisesRegex(runner.ToolValidationError,'unchanged_repair_already_attempted'):
            self.gateway.run_command(['repair'],purpose='repair')
        self.assertEqual(len([body for _,body in self.requests if body.get('argv')==['repair']]),0)
        # A different, observed state permits one new attempt; retries remain bounded.
        with patch.object(self.gateway,'rpc',return_value={'exit_code':0,'stdout':'new service state'}):
            self.gateway.run_command(['inspect'])
        self.gateway.run_command(['repair'],purpose='repair')
        self.assertEqual(self.gateway.mutation,2)

    def test_uploaded_observation_and_configuration_repair_are_separate_from_business(self):
        from pydantic_ai.models.function import FunctionModel
        from pydantic_ai.messages import ModelResponse,ToolCallPart
        turns=[]
        def respond(body):
            if body.get('argv')==['repair-config','a'*64]:
                return {'ok':True,'exit_code':0,'stdout':json.dumps({'changes':[{'path':'/approved/settings.yaml',
                    'key':'start_pose','before':3.3,'after':0.3,'backup':'/approved/settings.yaml.backup'}]})}
            return {'ok':True,'exit_code':0,'stdout':'configuration semantic validation passed'}
        self.responder=respond
        def model(messages,info):
            index=len(turns);turns.append(index)
            sequence=[('get_diagnostic_state',{}),('run_command',{'argv':['inspect']}),
                ('run_command',{'argv':['repair-config','a'*64],'purpose':'repair'}),
                ('run_command',{'argv':['check'],'purpose':'verify'})]
            if index==1:
                returned=[part.content for message in messages for part in message.parts if getattr(part,'part_kind','')=='tool-return' and getattr(part,'tool_name','')=='get_diagnostic_state']
                self.assertIn('joint limit violation',json.dumps(returned))
                self.assertIn('historical',json.dumps(returned))
            if index<len(sequence):
                name,args=sequence[index];return ModelResponse(parts=[ToolCallPart(name,args)])
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,{'summary':'配置已修复，运动待验收',
                'root_cause':'上传日志明确目标无效；配置修复回执已返回。','actions':[],'verification':[],
                'solution':'由获授权现场人员验证原失败操作。','repaired':False,
                'findings':[{'kind':'observed','statement':'历史日志出现joint limit violation','evidence_refs':['uploaded:0']}],
                'remaining_gaps':['原失败业务操作尚未复测']})])
        with patch.object(runner,'OpenAIChatModel',return_value=FunctionModel(model)):
            value=asyncio.run(runner.analyze({'config':{'model':'test','api_key':'synthetic','base_url':'https://invalid.example/v1'},
                'gateway_url':self.gateway.url,'tool_token':'synthetic-token','problem':'修复',
                'context':{'inspect_argv':['inspect'],'verify_argv':['check'],'repair_argv':['repair-config'],
                    'verification_scope':'configuration_validation','feedback_materials':{'sources':[
                        {'name':'feedback.json','sha256':'b'*64,'excerpt':'reset goal is invalid: joint limit violation'}]}}}))
        self.assertFalse(value['repaired'])
        self.assertTrue(value['configuration_repaired'])
        self.assertEqual(value['verification_scope'],'configuration_validation')
        self.assertEqual(value['outcome'],'unresolved')
        self.assertEqual(value['findings'][0]['evidence_refs'],['uploaded:0'])
        self.assertEqual(value['remaining_gaps'],['原失败业务操作尚未复测'])

    def test_offline_approved_configuration_is_not_blocked_by_unrelated_robot_connection(self):
        from pydantic_ai.models.function import FunctionModel
        from pydantic_ai.messages import ModelResponse,ToolCallPart
        turns=[];repaired=[]
        def respond(body):
            if body.get('operation')=='knowledge':return {'results':[]}
            if body.get('argv')==['daq-local-diagnostics-v1','repair','a'*64]:
                repaired.append(True)
                return {'ok':True,'exit_code':0,'stdout':json.dumps({'configuration':{'repair':{'state':'applied','changed':['initial_joint_states.arm[0]']}}})}
            return {'ok':True,'exit_code':0,'stdout':json.dumps({'scope':'configuration_validation','checks':[{'state':'fail'}],
                'configuration':{'state':'pass'if repaired else 'fail','current_scope':'offline_configuration_validation',
                    'repair_allowed':True,'repair_authority':'explicit_repair_plan','snapshot_sha256':'a'*64}})}
        self.responder=respond
        def model(messages,info):
            index=len(turns);turns.append(index)
            calls=[('run_command',{'argv':['daq-local-diagnostics-v1','inspect']}),('search_project_knowledge',{'query':'reset failure'})]
            if index<len(calls):return ModelResponse(parts=[ToolCallPart(*calls[index])])
            if index==3:
                self.assertTrue(any('不需要启动或连接机器人' in str(getattr(part,'content',''))
                    for message in messages for part in message.parts))
                return ModelResponse(parts=[ToolCallPart('apply_configuration_repair',{})])
            if repaired and index==4:return ModelResponse(parts=[ToolCallPart('run_command',{'argv':['daq-local-diagnostics-v1','verify'],'purpose':'verify'})])
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,{'summary':'配置修复待处理'if not repaired else '配置已修复，业务待验收',
                'root_cause':'配置检查发现异常。','actions':[],'verification':[],'solution':'先连接机器人再修改配置。'if not repaired else '另行验收机器人复位。','repaired':False})])
        with patch.object(runner,'OpenAIChatModel',return_value=FunctionModel(model)):
            result=asyncio.run(runner.analyze({'config':{'model':'test','api_key':'synthetic','base_url':'https://invalid.example/v1'},
                'gateway_url':self.gateway.url,'research_url':self.gateway.url,'tool_token':'synthetic','problem':'排查修复',
                'context':{'operation_mode':'repair','repair_allowed':True,'verification_scope':'configuration_validation',
                    'require_knowledge_search':True,'inspect_argv':['daq-local-diagnostics-v1','inspect'],
                    'repair_argv':['daq-local-diagnostics-v1','repair'],'verify_argv':['daq-local-diagnostics-v1','verify']}}))
        self.assertTrue(repaired)
        self.assertTrue(result['configuration_repaired'])
        self.assertFalse(result['repaired'])

    def test_receipt_scope_restricts_default_context_business_claim(self):
        self.gateway.run_command(['inspect'])
        self.gateway.run_command(['repair'],purpose='repair')
        with patch.object(self.gateway,'rpc',return_value={'exit_code':0,'stdout':json.dumps({'scope':'read_only_connectivity'})}):
            self.gateway.run_command(['check'],purpose='verify')
        self.assertFalse(self.gateway.repair_verified)
        self.assertEqual(self.gateway.verification_scope,'read_only_connectivity')

    def test_configuration_blocked_or_noop_is_not_an_applied_repair(self):
        for state in ('blocked','not_needed'):
            gateway=runner.Gateway('http://unused','synthetic',inspect_argv=['inspect'],verify_argv=['check'],
                verification_scope='configuration_validation')
            with patch.object(gateway,'rpc',return_value={'exit_code':0}):gateway.run_command(['inspect'])
            with patch.object(gateway,'rpc',return_value={'exit_code':0,'stdout':json.dumps({'configuration':{
                'repair':{'state':state,'blocked_reason':'baseline_missing'}}})}):
                gateway.run_command(['repair'],purpose='repair')
            with patch.object(gateway,'rpc',return_value={'exit_code':0}):gateway.run_command(['check'],purpose='verify')
            self.assertFalse(gateway.configuration_repaired)
            self.assertNotIn('授权修复完成',gateway.execution_summary()[0])

    def test_openai_request_timeout_retries_same_request_without_repeating_tools(self):
        import httpx
        calls=[]
        def response(name,args):
            return httpx.Response(200,json={'id':'synthetic','object':'chat.completion','created':1,'model':'test',
                'choices':[{'index':0,'finish_reason':'tool_calls','message':{'role':'assistant','content':None,
                    'tool_calls':[{'id':'call'+str(len(calls)),'type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}}],
                'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}})
        async def handle(request):
            calls.append(json.loads(request.content))
            sequence=[('run_command',{'argv':['inspect']}),('run_command',{'argv':['repair'],'purpose':'repair'}),
                ('run_command',{'argv':['check'],'purpose':'verify'})]
            if len(calls)<=3:return response(*sequence[len(calls)-1])
            if len(calls)==4:raise httpx.ReadTimeout('synthetic timeout',request=request)
            return response('final_result',{'summary':'已修复并复测','root_cause':'当前配置异常','actions':[],
                'verification':[],'solution':'继续观察','repaired':True})
        client=httpx.AsyncClient(transport=httpx.MockTransport(handle))
        with patch.object(runner,'DefaultAsyncHttpxClient',return_value=client):
            value=asyncio.run(runner.analyze({'config':{'model':'test','api_key':'synthetic','base_url':'https://provider.invalid/v1'},
                'gateway_url':self.gateway.url,'tool_token':'synthetic-token','context':{'inspect_argv':['inspect'],'verify_argv':['check']}}))
        self.assertTrue(value['repaired'])
        self.assertEqual(len(calls),5)
        self.assertEqual(calls[3],calls[4])
        self.assertEqual([body['argv'] for _,body in self.requests],[['inspect'],['repair'],['check']])

    def test_persistent_provider_timeout_preserves_receipts_without_repair_replay(self):
        import httpx
        calls=[];runtime={}
        async def handle(request):
            calls.append(json.loads(request.content))
            if len(calls)<=3:
                argv=[['inspect'],['repair'],['check']][len(calls)-1]
                args={'argv':argv,'purpose':'verify' if argv==['check'] else 'repair' if argv==['repair'] else 'inspect'}
                return httpx.Response(200,json={'id':'synthetic','object':'chat.completion','created':1,'model':'test',
                    'choices':[{'index':0,'finish_reason':'tool_calls','message':{'role':'assistant','content':None,
                        'tool_calls':[{'id':str(len(calls)),'type':'function','function':{'name':'run_command','arguments':json.dumps(args)}}]}}],
                    'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}})
            raise httpx.ReadTimeout('synthetic secret provider body',request=request)
        payload={'config':{'model':'test','api_key':'synthetic','base_url':'https://provider.invalid/v1'},
            'gateway_url':self.gateway.url,'tool_token':'synthetic-token','context':{'inspect_argv':['inspect'],'verify_argv':['check']}}
        client=httpx.AsyncClient(transport=httpx.MockTransport(handle))
        with patch.object(runner,'DefaultAsyncHttpxClient',return_value=client):
            try:asyncio.run(runner.analyze(payload,runtime))
            except Exception as error:value=runner.failed_analysis(payload,runtime,error)
        self.assertEqual(len(calls),5)
        self.assertFalse(value['repaired'])
        self.assertTrue(value['verification_passed'])
        self.assertIn('现场取证完成',value['actions'])
        self.assertEqual(len(self.requests),3)
        self.assertNotIn('provider body',json.dumps(value))

    def test_provider_authentication_failure_is_not_retried(self):
        import httpx
        calls=[]
        async def handle(request):
            calls.append(1)
            return httpx.Response(401,json={'error':{'message':'synthetic provider body','type':'authentication_error'}})
        client=httpx.AsyncClient(transport=httpx.MockTransport(handle))
        with patch.object(runner,'DefaultAsyncHttpxClient',return_value=client):
            with self.assertRaises(Exception):
                asyncio.run(runner.analyze({'config':{'model':'test','api_key':'synthetic','base_url':'https://provider.invalid/v1'},
                    'gateway_url':self.gateway.url,'tool_token':'synthetic-token','context':{}}))
        self.assertEqual(len(calls),1)
        self.assertEqual(len(self.requests),0)

    def test_connectivity_only_report_must_account_for_available_uploaded_fault(self):
        from pydantic_ai.models.function import FunctionModel
        from pydantic_ai.messages import ModelResponse,ToolCallPart
        turns=[]
        def model(messages,info):
            index=len(turns);turns.append(index)
            if index==0:return ModelResponse(parts=[ToolCallPart('run_command',{'argv':['inspect']})])
            report={'summary':'当前连通，故障待定位','root_cause':'当前配置未取证','actions':[],'verification':[],
                'solution':'按上传故障检查实际运行输入','repaired':False}
            if index==2:
                report['findings']=[{'kind':'observed','statement':'上传证据显示服务调用失败',
                    'evidence_refs':['uploaded:0']}]
                report['remaining_gaps']=['故障发生时对应服务与当前进程状态尚未关联']
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,report)])
        with patch.object(runner,'OpenAIChatModel',return_value=FunctionModel(model)):
            value=asyncio.run(runner.analyze({'config':{'model':'test','api_key':'synthetic','base_url':'https://invalid.example/v1'},
                'gateway_url':self.gateway.url,'tool_token':'synthetic-token','context':{'inspect_argv':['inspect'],
                    'repair_allowed':False,'feedback_materials':{'sources':[{'excerpt':'service request timed out'}]}}}))
        self.assertEqual(len(turns),3)
        self.assertEqual(value['findings'][0]['evidence_refs'],['uploaded:0'])

    def test_different_fault_categories_continue_after_failed_verification(self):
        from pydantic_ai.models.function import FunctionModel
        from pydantic_ai.messages import ModelResponse,ToolCallPart
        for category in ('dependency_environment_mismatch','service_not_ready','storage_mount_not_ready'):
            state={'config_ready':False,'downstream_ready':False};turns=[]
            self.requests.clear()
            def digest():return hashlib.sha256(json.dumps(state,sort_keys=True).encode()).hexdigest()
            def respond(body):
                if body['operation']!='run':return {'results':[]}
                argv=body['argv']
                if argv==['inspect']:
                    return {'exit_code':0,'stdout':json.dumps({'state':state,'sha256':digest(),'failure':category})}
                if argv[:1]==['repair-allowed']:
                    self.assertEqual(argv[-1],digest())
                    key='config_ready' if not state['config_ready'] else 'downstream_ready'
                    state[key]=True
                    return {'exit_code':0,'stdout':json.dumps({'changes':[{'path':'/approved/settings.json',
                        'key':key,'before':False,'after':True}]})}
                unresolved=not all(state.values())
                return {'exit_code':1 if unresolved else 0,'stdout':json.dumps({'remaining_fault':category if unresolved else None})}
            self.responder=respond
            def model(messages,info):
                index=len(turns);turns.append(index)
                sequence=[('run_command',{'argv':['inspect']}),
                    ('run_command',{'argv':['repair-allowed',digest()],'purpose':'repair'}),
                    ('run_command',{'argv':['check'],'purpose':'verify'}),
                    ('run_command',{'argv':['inspect']}),
                    ('run_command',{'argv':['repair-allowed',digest()],'purpose':'repair'}),
                    ('run_command',{'argv':['check'],'purpose':'verify'})]
                if index<len(sequence):
                    name,args=sequence[index];return ModelResponse(parts=[ToolCallPart(name,args)])
                return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,{'summary':'两项故障均通过最终验收',
                    'root_cause':category+'与配置状态分别异常','actions':[],'verification':[],
                    'solution':'保留本轮结果','repaired':True})])
            with patch.object(runner,'OpenAIChatModel',return_value=FunctionModel(model)):
                value=asyncio.run(runner.analyze({'config':{'model':'test','api_key':'synthetic','base_url':'https://invalid.example/v1'},
                    'gateway_url':self.gateway.url,'tool_token':'synthetic-token','context':{'inspect_argv':['inspect'],
                        'verify_argv':['check'],'repair_argv':['repair-allowed']}}))
            self.assertTrue(value['repaired'])
            self.assertEqual(state,{'config_ready':True,'downstream_ready':True})
            self.assertEqual(len(self.requests),6)
            self.assertIn(category,value['root_cause'])

    def test_negative_structured_inspection_is_valid_fault_evidence_before_repair(self):
        gateway=runner.Gateway(self.gateway.url,'synthetic-token',inspect_argv=['inspect'],verify_argv=['check'],
            repair_argv=['repair-config'])
        self.responder=lambda body: {'exit_code':1,'ok':False,'stdout':json.dumps({'scope':'configuration_validation',
            'checks':[{'name':'configuration','state':'fail'}],'configuration':{'state':'fail','snapshot_sha256':'a'*64}})} if body.get('argv')==['inspect'] else {'exit_code':0}
        result=gateway.run_command(['inspect'])
        self.assertTrue(gateway.inspected)
        self.assertFalse(gateway.verification_passed)
        self.assertEqual(result['exit_code'],1)
        gateway.run_command(['repair-config','a'*64],purpose='repair')
        self.assertEqual(len(self.requests),2)

    def test_report_cannot_promote_prediction_or_unknown_source_to_observed_fact(self):
        from pydantic_ai.models.function import FunctionModel
        from pydantic_ai.messages import ModelResponse,ToolCallPart
        for invalid in ({'kind':'observed','statement':'依赖缺失','evidence_refs':[]},
                        {'kind':'observed','statement':'服务已恢复','evidence_refs':['tool:999']}):
            turns=[]
            def model(messages,info):
                index=len(turns);turns.append(index)
                if index==0:return ModelResponse(parts=[ToolCallPart('run_command',{'argv':['inspect']})])
                finding=invalid if index==1 else {'kind':'predicted','statement':'依赖状态需要当前环境验证','evidence_refs':[]}
                return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,{'summary':'当前证据不足',
                    'root_cause':'尚不能证实依赖或服务故障','actions':[],'verification':[],
                    'solution':'补充该进程实际解释器及服务失败日志','repaired':False,'findings':[finding]})])
            with patch.object(runner,'OpenAIChatModel',return_value=FunctionModel(model)):
                value=asyncio.run(runner.analyze({'config':{'model':'test','api_key':'synthetic','base_url':'https://invalid.example/v1'},
                    'gateway_url':self.gateway.url,'tool_token':'synthetic-token','context':{'inspect_argv':['inspect'],'repair_allowed':False}}))
            self.assertEqual(len(turns),3)
            self.assertEqual(value['findings'][0]['kind'],'predicted')

    def test_timeout_retry_is_once_per_task_and_obeys_original_deadline(self):
        from pydantic_ai.models.function import FunctionModel
        calls=[]
        def model(messages,info):
            calls.append(1)
            raise runner.ModelTimeoutError('synthetic','provider detail')
        wrapper=runner.TimeoutRetryModel(FunctionModel(model),runner.time.monotonic()+10)
        from pydantic_ai.models import ModelRequestParameters
        for _ in range(2):
            with self.assertRaises(runner.ModelTimeoutError):
                asyncio.run(wrapper.request([],None,ModelRequestParameters()))
        self.assertEqual(len(calls),3)  # First request retries once; next request never retries again.
        expired=runner.TimeoutRetryModel(FunctionModel(model),runner.time.monotonic()-1)
        with self.assertRaises(TimeoutError):asyncio.run(expired.request([],None,ModelRequestParameters()))
        self.assertEqual(len(calls),3)

    def test_invalid_configuration_does_not_authorize_a_release_default_repair(self):
        self.responder=lambda body: {'exit_code':1,'stdout':json.dumps({'scope':'configuration_validation',
            'checks':[{'name':'configuration','state':'fail'}],
            'configuration':{'state':'fail','repair_allowed':False,'baseline':{'state':'candidate'},
                'capabilities':{'supported_repairs':[],'service_dependency_connection_repair':False},
                'blocked_reason':'device_calibration_provenance_required'}})}
        self.gateway.run_command(['inspect'])
        with self.assertRaisesRegex(runner.ToolValidationError,'configuration_repair_plan_not_supported'):
            self.gateway.run_command(['repair'],purpose='repair')
        capability=self.gateway.capability_state()
        self.assertFalse(capability['configuration']['repair_allowed'])
        self.assertIn('device_calibration_provenance_required',json.dumps(capability))
        self.assertEqual(len(self.requests),1)

    def test_diagnose_mode_blocks_mutation_even_if_context_repair_flag_is_true(self):
        from pydantic_ai.models.function import FunctionModel
        from pydantic_ai.messages import ModelResponse,ToolCallPart
        turns=[]
        def model(messages,info):
            index=len(turns);turns.append(index)
            if index==0:return ModelResponse(parts=[ToolCallPart('run_command',{'argv':['inspect']})])
            if index==1:return ModelResponse(parts=[ToolCallPart('run_command',{'argv':['repair'],'purpose':'repair'})])
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,{'summary':'只读诊断','root_cause':'待查',
                'actions':[],'verification':[],'solution':'需授权','repaired':False})])
        with patch.object(runner,'OpenAIChatModel',return_value=FunctionModel(model)):
            asyncio.run(runner.analyze({'config':{'model':'test','api_key':'synthetic','base_url':'https://invalid.example/v1'},
                'gateway_url':self.gateway.url,'tool_token':'synthetic-token','context':{'inspect_argv':['inspect'],
                    'operation_mode':'diagnose','repair_allowed':True}}))
        self.assertFalse(any(body.get('argv')==['repair'] for _,body in self.requests))

class ReceiptFinalizationTest(unittest.TestCase):
    def test_budget_after_verified_write_uses_one_tool_free_report_without_replaying(self):
        from pydantic_ai.models.function import FunctionModel
        from pydantic_ai.messages import ModelResponse,ToolCallPart
        from pydantic_ai.exceptions import UsageLimitExceeded
        requests=[];dispatched=[];runtime={}
        def rpc(gateway,body):
            dispatched.append(body)
            if body['argv']==['repair','a'*64]:
                return {'exit_code':0,'stdout':json.dumps({'changes':[{'path':'/approved/config.yaml','key':'pose',
                    'before':3.3,'after':0.3,'backup':'/approved/config.backup'}]})}
            return {'exit_code':0,'stdout':'actual check'}
        def model(messages,info):
            requests.append(info)
            if not info.function_tools:
                text=json.dumps([getattr(part,'content','') for message in messages for part in message.parts])
                self.assertIn('using_receipts',text);self.assertIn('/approved/config.yaml',text)
                return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,{'summary':'配置已修改并通过配置复查，业务待验收',
                    'root_cause':'本轮配置变更和检查已有真实回执','actions':[],'verification':[],
                    'solution':'由获授权人员验收原业务操作','repaired':False})])
            index=len(requests)-1
            sequence=[('run_command',{'argv':['inspect']}),('run_command',{'argv':['repair','a'*64],'purpose':'repair'}),
                ('run_command',{'argv':['verify'],'purpose':'verify'})]
            if index<len(sequence):
                name,args=sequence[index];return ModelResponse(parts=[ToolCallPart(name,args)])
            raise UsageLimitExceeded('synthetic-private-provider-body')
        with patch.object(runner,'OpenAIChatModel',return_value=FunctionModel(model)),patch.object(runner.Gateway,'rpc',rpc):
            result=asyncio.run(runner.analyze({'config':{'model':'test','api_key':'synthetic','base_url':'https://invalid.example/v1'},
                'gateway_url':'http://unused','tool_token':'synthetic-token','context':{'inspect_argv':['inspect'],
                    'verify_argv':['verify'],'repair_argv':['repair'],'verification_scope':'configuration_validation'}},runtime))
        self.assertEqual(len(dispatched),3);self.assertEqual(len(requests),5)
        self.assertTrue(result['configuration_repaired']);self.assertFalse(result['repaired'])
        self.assertEqual(result['finalization_stage'],'receipt_only');self.assertTrue(result['using_receipts'])
        self.assertEqual(result['analysis_stop_reason'],'UsageLimitExceeded')
        self.assertNotIn('synthetic-private-provider-body',json.dumps(result))

    def test_exhausted_analysis_token_budget_leaves_one_no_tool_report_request(self):
        from pydantic_ai.models.function import FunctionModel
        from pydantic_ai.messages import ModelResponse,ToolCallPart
        from pydantic_ai.usage import RequestUsage
        requests=[]
        def model(messages,info):
            requests.append(info)
            if not info.function_tools:
                return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,{'summary':'现场已取证，原因待进一步验证',
                    'root_cause':'当前回执仅支持检查已完成','actions':[],'verification':[],
                    'solution':'补充原故障业务验收','repaired':False})],usage=RequestUsage(input_tokens=10,output_tokens=200))
            return ModelResponse(parts=[ToolCallPart('run_command',{'argv':['inspect']})],
                usage=RequestUsage(input_tokens=10,output_tokens=12000))
        with patch.object(runner,'OpenAIChatModel',return_value=FunctionModel(model)),patch.object(runner.Gateway,'rpc',return_value={'exit_code':0}):
            result=asyncio.run(runner.analyze({'config':{'model':'test','api_key':'synthetic','base_url':'https://invalid.example/v1'},
                'gateway_url':'http://unused','tool_token':'synthetic-token','context':{'inspect_argv':['inspect']}},{}))
        self.assertEqual(len(requests),2)
        self.assertEqual(result['analysis_usage']['output_tokens'],12000)
        self.assertEqual(result['finalization_usage']['output_tokens'],200)
        self.assertEqual(result['finalization_stage'],'receipt_only')
        self.assertFalse(result['repaired'])

    def test_partial_or_unverified_receipts_cannot_be_promoted_by_finalizer(self):
        from pydantic_ai.models.function import FunctionModel
        from pydantic_ai.messages import ModelResponse,ToolCallPart
        from pydantic_ai.exceptions import UsageLimitExceeded
        calls=[];runtime={}
        def model(messages,info):
            calls.append(info)
            if not info.function_tools:
                return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,{'summary':'未完成验证','root_cause':'现有证据不足',
                    'actions':[],'verification':[],'solution':'先重新确认当前状态','repaired':True})])
            if len(calls)==1:return ModelResponse(parts=[ToolCallPart('run_command',{'argv':['inspect']})])
            raise UsageLimitExceeded('synthetic')
        with patch.object(runner,'OpenAIChatModel',return_value=FunctionModel(model)),patch.object(runner.Gateway,'rpc',return_value={'exit_code':0}):
            with self.assertRaises(UsageLimitExceeded) as error:
                asyncio.run(runner.analyze({'config':{'model':'test','api_key':'synthetic','base_url':'https://invalid.example/v1'},
                    'gateway_url':'http://unused','tool_token':'synthetic-token','context':{'inspect_argv':['inspect']}},runtime))
        result=runner.failed_analysis({'context':{}},runtime,error.exception)
        self.assertFalse(result['repaired'] or result['configuration_repaired'])
        self.assertEqual(len(calls),3)
        self.assertEqual(result['finalization_stage'],'failed')


class LocationReceiptTest(unittest.TestCase):
    def test_failed_patch_receipt_cannot_add_locations_or_ip_as_line(self):
        gateway=runner.Gateway('http://unused','synthetic')
        gateway.inspected=True;gateway.read_hashes['collector-config.json']='a'*64
        result={'ok':False,'exit_code':1,'resolved_path':'/approved/collector-config.json','changes':[
            {'path':'/approved/collector-config.json','target_kind':'collector','line':'10.10.10.195','key':'robot_port'}]}
        with patch.object(gateway,'rpc',return_value=result):gateway.patch_file('collector-config.json','a'*64,'after')
        self.assertEqual(gateway.repair_locations,[])
        gateway.record_changes({**result,'ok':True})
        self.assertNotIn('line',gateway.repair_locations[0])
        self.assertNotIn('before',gateway.repair_locations[0])
        self.assertNotIn('after',gateway.repair_locations[0])

    def test_failed_read_does_not_promote_resolved_path_or_sha_to_evidence(self):
        gateway=runner.Gateway('http://unused','synthetic')
        with patch.object(gateway,'rpc',return_value={'ok':True,'exit_code':1,'content':'not a successful read',
            'sha256':'a'*64,'resolved_path':'/unconfirmed/collector-config.json'}):
            gateway.read_file('collector-config.json')
        self.assertEqual(gateway.read_hashes,{})
        self.assertEqual(gateway.observed_locations,set())
        self.assertNotIn('/unconfirmed/',json.dumps(gateway.execution_summary()))

    def test_exhausted_location_validation_reports_fixed_reason_and_keeps_inspection(self):
        from pydantic_ai.models.function import FunctionModel
        from pydantic_ai.messages import ModelResponse,ToolCallPart
        calls=[]
        def model(messages,info):
            calls.append(1)
            if len(calls)==1:return ModelResponse(parts=[ToolCallPart('run_command',{'argv':['inspect']})])
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,{'summary':'待查',
                'root_cause':'/invented/config.py:999 未核实位置','actions':[],'verification':[],
                'solution':'补充证据','repaired':False})])
        payload={'config':{'model':'test','api_key':'synthetic-secret','base_url':'https://invalid.example/v1'},
            'gateway_url':'http://unused/agent-tool/','tool_token':'synthetic-token','problem':'diagnose',
            'context':{'inspect_argv':['inspect'],'repair_allowed':False}}
        output=io.StringIO()
        with patch.object(runner,'OpenAIChatModel',return_value=FunctionModel(model)), \
             patch.object(runner.Gateway,'rpc',return_value={'ok':True,'exit_code':0}), \
             patch.object(runner.sys,'stdin',SimpleNamespace(buffer=io.BytesIO(json.dumps(payload).encode()))), \
             patch.object(runner.sys,'stdout',output):
            runner.main()
        result=json.loads(output.getvalue())
        self.assertTrue(result['execution_error'])
        self.assertEqual(result['validation_reason'],'unobserved_location')
        self.assertEqual(result['actions'],['现场取证完成'])
        self.assertEqual(result['agent_error_code'],'UnexpectedModelBehavior')
        self.assertEqual(result['validation_mismatches'],[{'path':'/invented/config.py','line':999,'untrusted_model_claim':True}])

    def test_location_mismatch_handles_are_bounded_redacted_untrusted_claims(self):
        gateway=runner.Gateway('http://unused','synthetic-token',secrets=['synthetic-key'])
        claims={(f'/unknown/file{index}.py',index+1) for index in range(10)}
        self.assertEqual(len(gateway.mismatch_handles(claims)),5)
        claims={('/config/synthetic-key.py',1),('/config/api_key.py',2),('/config/'+'a'*48+'.py',3)}
        value=gateway.mismatch_handles(claims)
        self.assertTrue(all(row['untrusted_model_claim'] for row in value))
        self.assertNotIn('synthetic-key',json.dumps(value))
        self.assertNotIn('a'*48,json.dumps(value))
        self.assertNotIn('api_key.py',json.dumps(value))
        self.assertEqual(gateway.mismatch_handles({('/config/value.py',int('9'*40))})[0]['line'],'[untrusted line redacted]')

    def test_validation_failure_records_only_safe_class_chain_and_actual_actions(self):
        from pydantic_ai.exceptions import UnexpectedModelBehavior
        gateway=runner.Gateway('http://unused','synthetic',inspect_argv=['inspect'])
        with patch.object(gateway,'rpc',return_value={'ok':True,'exit_code':0}):
            gateway.run_command(['inspect'])
        cause=runner.ModelRetry('synthetic-secret https://private.invalid/validator-detail')
        failure=UnexpectedModelBehavior('provider body synthetic-secret')
        failure.__cause__=cause
        result=runner.failed_analysis({'context':{'operation_mode':'diagnose'}},{'gateway':gateway},failure)
        self.assertEqual(result['agent_error_code'],'UnexpectedModelBehavior')
        self.assertEqual(result['agent_error_chain'],['UnexpectedModelBehavior','ModelRetry'])
        self.assertEqual(result['actions'],['现场取证完成'])
        self.assertFalse(result['verification_passed'])
        self.assertNotIn('synthetic-secret',json.dumps(result))
        self.assertNotIn('private.invalid',json.dumps(result))

    def test_outer_deadline_retains_completed_gateway_receipt(self):
        gateway=runner.Gateway('http://unused','synthetic',verify_argv=['verify'])
        with patch.object(gateway,'rpc',return_value={'ok':True,'exit_code':0}):
            gateway.run_command(['verify'],purpose='verify')
        result=runner.failed_analysis({'context':{'operation_mode':'verify'}},{'gateway':gateway},TimeoutError('untrusted error body'))
        self.assertEqual(result['agent_error_code'],'TimeoutError')
        self.assertTrue(result['verification_passed'])
        self.assertTrue(result['execution_error'])
        self.assertEqual(result['outcome'],'unresolved')

    def test_main_preserves_receipts_when_actual_model_finalization_fails(self):
        from pydantic_ai.models.function import FunctionModel
        from pydantic_ai.messages import ModelResponse,ToolCallPart
        calls=[]
        def model(messages,info):
            calls.append(1)
            if len(calls)==1:return ModelResponse(parts=[ToolCallPart('run_command',{'argv':['inspect']})])
            if len(calls)==2:return ModelResponse(parts=[ToolCallPart('run_command',{'argv':['verify'],'purpose':'verify'})])
            raise RuntimeError('synthetic-secret https://private-provider.invalid/untrusted-error-body')
        payload={'config':{'model':'test','api_key':'synthetic-secret','base_url':'https://invalid.example/v1'},
            'gateway_url':'http://unused/agent-tool/','tool_token':'synthetic-token','problem':'verify',
            'context':{'inspect_argv':['inspect'],'verify_argv':['verify'],'operation_mode':'verify','repair_allowed':False}}
        stdin=SimpleNamespace(buffer=io.BytesIO(json.dumps(payload).encode()))
        output=io.StringIO()
        with patch.object(runner,'OpenAIChatModel',return_value=FunctionModel(model)), \
             patch.object(runner.Gateway,'rpc',return_value={'ok':True,'exit_code':0,'stdout':'actual device receipt'}), \
             patch.object(runner.sys,'stdin',stdin),patch.object(runner.sys,'stdout',output):
            runner.main()
        result=json.loads(output.getvalue())
        self.assertTrue(result['execution_error'])
        self.assertEqual(result['agent_error_code'],'RuntimeError')
        self.assertTrue(result['verification_passed'])
        self.assertIn('现场取证完成',result['actions'])
        self.assertIn('exit_code=0',' '.join(result['verification']))
        self.assertEqual(result['outcome'],'unresolved')
        self.assertFalse(result['repaired'])
        self.assertNotIn('synthetic-secret',output.getvalue())
        self.assertNotIn('private-provider.invalid',output.getvalue())

    def test_execution_summary_names_real_specialist_phase_and_deduplicates(self):
        prefix=['/usr/bin/python3','/approved/container_bridge.py']
        commands=[prefix+['rosa','health'],prefix+['rosa','inspect'],prefix+['rai','health'],prefix+['rai','inspect']]
        gateway=runner.Gateway('http://unused','synthetic',inspect_argv=['inspect'],specialist_argv=commands)
        with patch.object(gateway,'rpc',return_value={'ok':True,'exit_code':0,'stdout':'{}'}):
            gateway.run_command(['inspect'])
            for argv in commands:
                gateway.run_command(argv)
            gateway.run_command(['inspect'])
            gateway.run_command(commands[1])
        actions,_=gateway.execution_summary()
        self.assertEqual(actions,['现场取证完成','ROSA 健康探测完成','ROSA 只读检查完成','RAI 健康探测完成','RAI 只读检查完成'])

    def test_execution_summary_keeps_unavailable_specialist_and_file_receipts_honest(self):
        argv=['/usr/bin/python3','/approved/bridge.py','rosa','health']
        gateway=runner.Gateway('http://unused','synthetic',specialist_argv=[argv])
        with patch.object(gateway,'rpc',return_value={'ok':True,'exit_code':0,'stdout':'{"ready":false}'}):
            gateway.run_command(argv)
        with patch.object(gateway,'rpc',return_value={'content':'before','sha256':'a'*64}):
            gateway.read_file('/actual/config.py')
        with patch.object(gateway,'rpc',return_value={'ok':True,'sha256':'b'*64}):
            gateway.patch_file('/actual/config.py','a'*64,'after')
        actions,_=gateway.execution_summary()
        self.assertEqual(actions,['ROSA 健康探测失败或结果未确认','读取现场文件完成：/actual/config.py','写入授权文件完成：/actual/config.py'])

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
