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
