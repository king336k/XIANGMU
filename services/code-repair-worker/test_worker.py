"""Real OpenHands kernel and Docker tools; synthetic provider only for control checks."""
import contextlib
import hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch

import worker

ROOT=Path('/home/engram/Documents/tmp/artifacts/td-d-498-20261119/openhands-worker/tests')


class WorkerTest(unittest.TestCase):
    def setUp(self):
        ROOT.mkdir(parents=True,exist_ok=True);self.root=Path(tempfile.mkdtemp(dir=ROOT))
        self.sources=self.root/'sources';source=self.sources/'synthetic-code';files=source/'files';files.mkdir(parents=True)
        entries={'calculator.py':'def add(a, b):\n    return a - b\n',
            'test_calculator.py':'from calculator import add\n\ndef test_add():\n    assert add(2, 3) == 5\n'}
        manifest={'schema':'remote-source-snapshot-v1','source_id':'synthetic-code','project_ids':['p1'],
            'repository_commit':'a'*40,'source_repository':'https://example.invalid/synthetic','files':{}}
        for path,text in entries.items():
            target=files/path;target.write_text(text);target.chmod(0o444)
            manifest['files'][path]={'sha256':hashlib.sha256(text.encode()).hexdigest(),'size':len(text.encode())}
        (source/'manifest.json').write_text(json.dumps(manifest));(source/'manifest.json').chmod(0o444)
        files.chmod(0o555);source.chmod(0o555)
        self.requests=[];self.weaken_test=False;self.provider_fail=False;fixture=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                value=json.loads(self.rfile.read(int(self.headers['Content-Length'])));fixture.requests.append(value)
                index=len(fixture.requests)
                if fixture.provider_fail and index==2:
                    self.send_response(500);self.end_headers();return
                if index==1:
                    tool=next(item['function']['name'] for item in value['tools'] if 'sandbox' in item['function']['name'])
                    args={'command':'cat calculator.py && python -m pytest -q','timeout':30}
                elif index==2:
                    tool=next(item['function']['name'] for item in value['tools'] if 'sandbox' in item['function']['name'])
                    args={'command':"python -c \"from pathlib import Path; p=Path('calculator.py'); p.write_text(p.read_text().replace('a - b','a + b'))\" && python -m pytest -q",'timeout':30}
                    if fixture.weaken_test:
                        args={'command':"printf 'def test_add(): pass\\n' > test_calculator.py; python -m pytest -q",'timeout':30}
                else:tool='finish';args={'message':'Repaired source and verified pytest in isolated workspace.'}
                response={'id':'synthetic','object':'chat.completion','created':1,'model':'gpt-4o-mini',
                    'choices':[{'index':0,'finish_reason':'tool_calls','message':{'role':'assistant','content':None,
                        'tool_calls':[{'id':str(index),'type':'function','function':{'name':tool,'arguments':json.dumps(args)}}]}}],
                    'usage':{'prompt_tokens':100,'completion_tokens':30,'total_tokens':130}}
                encoded=json.dumps(response).encode();self.send_response(200);self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(encoded)));self.end_headers();self.wfile.write(encoded)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
        for path in self.root.rglob('*'):
            if not path.is_symlink():
                try:path.chmod(0o777 if path.is_dir() else 0o666)
                except PermissionError:pass
        shutil.rmtree(self.root)

    def test_actual_sdk_repairs_real_file_and_executes_real_pytest_in_docker(self):
        deps=Path(__import__('pydantic').__file__).parent.parent
        env={'QUALITY_REMOTE_SOURCE_SNAPSHOTS_ROOT':str(self.sources),'CODE_REPAIR_WORK_ROOT':str(self.root/'runs'),
            'CODE_REPAIR_DEPENDENCIES':str(deps)}
        with patch.dict(os.environ,env):
            result=worker.run({'config':{'model':'cx/gpt-6.1-sol','api_key':'synthetic-key',
                'base_url':f'http://127.0.0.1:{self.server.server_port}/v1'},
                'task':{'project_id':'p1','source_id':'synthetic-code','repository_commit':'a'*40,
                    'problem':'Addition returns the wrong result; inspect and repair the source with its tests.'}})
        self.assertTrue(result['code_verified']);self.assertFalse(result['business_verified'])
        self.assertEqual(result['baseline']['exit_code'],1)
        self.assertEqual(result['verification']['exit_code'],0)
        self.assertIn('-    return a - b',result['diff']);self.assertIn('+    return a + b',result['diff'])
        self.assertEqual(len(self.requests),3)
        self.assertEqual(self.requests[0]['model'],'cx/gpt-6.1-sol')
        self.assertEqual(result['scope'],'isolated_code_snapshot')
        self.assertNotIn('synthetic-key',json.dumps(result))

    def test_test_weakening_never_counts_as_verified_code_repair(self):
        self.weaken_test=True
        deps=Path(__import__('pydantic').__file__).parent.parent
        with patch.dict(os.environ,{'QUALITY_REMOTE_SOURCE_SNAPSHOTS_ROOT':str(self.sources),
            'CODE_REPAIR_WORK_ROOT':str(self.root/'runs'),'CODE_REPAIR_DEPENDENCIES':str(deps)}):
            result=worker.run({'config':{'model':'gpt-4o-mini','api_key':'synthetic-key',
                'base_url':f'http://127.0.0.1:{self.server.server_port}/v1'},
                'task':{'project_id':'p1','source_id':'synthetic-code','repository_commit':'a'*40,'problem':'Repair failing tests'}})
        self.assertFalse(result['code_verified'])
        self.assertEqual(result['protected_test_changes'],['test_calculator.py'])

    def test_provider_failure_preserves_actual_baseline_and_final_test_receipts(self):
        self.provider_fail=True
        deps=Path(__import__('pydantic').__file__).parent.parent
        with patch.dict(os.environ,{'QUALITY_REMOTE_SOURCE_SNAPSHOTS_ROOT':str(self.sources),
            'CODE_REPAIR_WORK_ROOT':str(self.root/'runs'),'CODE_REPAIR_DEPENDENCIES':str(deps)}):
            result=worker.run({'config':{'model':'gpt-4o-mini','api_key':'synthetic-key',
                'base_url':f'http://127.0.0.1:{self.server.server_port}/v1'},
                'task':{'project_id':'p1','source_id':'synthetic-code','repository_commit':'a'*40,'problem':'Repair failing tests'}})
        self.assertFalse(result['code_verified'])
        self.assertTrue(result['agent_error_class'])
        self.assertEqual(result['baseline']['exit_code'],1)
        self.assertEqual(result['verification']['exit_code'],1)
        self.assertGreaterEqual(len(result['tool_receipts']),3)

    def test_new_conftest_skips_are_rejected(self):
        deps=Path(__import__('pydantic').__file__).parent.parent
        def malicious(config,sandbox,workspace,problem):
            code='import pytest\ndef pytest_collection_modifyitems(items):\n    for item in items: item.add_marker(pytest.mark.skip(reason="synthetic"))\n'
            sandbox.command('python -c '+__import__('shlex').quote('from pathlib import Path; Path("conftest.py").write_text('+repr(code)+')'))
        with patch.object(worker,'sdk_agent',side_effect=malicious),patch.dict(os.environ,{
            'QUALITY_REMOTE_SOURCE_SNAPSHOTS_ROOT':str(self.sources),'CODE_REPAIR_WORK_ROOT':str(self.root/'runs'),
            'CODE_REPAIR_DEPENDENCIES':str(deps)}):
            result=worker.run({'config':{'model':'synthetic','api_key':'synthetic','base_url':'https://invalid'},
                'task':{'project_id':'p1','source_id':'synthetic-code','repository_commit':'a'*40,'problem':'Repair'}})
        self.assertFalse(result['code_verified'])
        self.assertIn('conftest.py',result['protected_test_changes'])
        self.assertEqual(result['executed_test_evidence']['final_passed'],0)

    def test_stdout_and_workspace_disk_are_hard_bounded_without_host_write_mount(self):
        workspace=self.root/'work';workspace.mkdir();(workspace/'sample.py').write_text('value=1\n')
        sandbox=worker.Sandbox(workspace)
        try:
            inspect=json.loads(__import__('subprocess').check_output(['docker','inspect',sandbox.name]))[0]
            self.assertEqual(inspect['HostConfig']['Memory'],2*1024**3)
            self.assertIn('/workspace',inspect['HostConfig']['Tmpfs'])
            self.assertNotIn('/workspace',[mount['Destination'] for mount in inspect['Mounts']])
            result=sandbox.command('yes synthetic',timeout=10)
            self.assertTrue(result['output_limit_exceeded']);self.assertTrue(sandbox.closed)
        finally:sandbox.close()

    def test_background_writer_is_stopped_before_candidate_export(self):
        workspace=self.root/'work';workspace.mkdir();(workspace/'sample.py').write_text('value=1\n')
        sandbox=worker.Sandbox(workspace)
        try:
            sandbox.command("python -c \"import time; from pathlib import Path; time.sleep(1); Path('sample.py').write_text('changed')\" >/dev/null 2>&1 &")
            candidate=sandbox.freeze(self.root/'candidate')
            __import__('time').sleep(1.1)
            self.assertEqual((candidate/'sample.py').read_text(),'value=1\n')
            self.assertTrue(sandbox.closed)
        finally:sandbox.close()

    def test_fake_pytest_module_cannot_forge_fixed_checker_success(self):
        deps=Path(__import__('pydantic').__file__).parent.parent
        def malicious(config,sandbox,workspace,problem):
            code='print("999 passed in 0.01s")\n'
            sandbox.command('python -c '+__import__('shlex').quote('from pathlib import Path; Path("pytest.py").write_text('+repr(code)+')'))
        with patch.object(worker,'sdk_agent',side_effect=malicious),patch.dict(os.environ,{
            'QUALITY_REMOTE_SOURCE_SNAPSHOTS_ROOT':str(self.sources),'CODE_REPAIR_WORK_ROOT':str(self.root/'runs'),
            'CODE_REPAIR_DEPENDENCIES':str(deps)}):
            result=worker.run({'config':{'model':'synthetic','api_key':'synthetic','base_url':'https://invalid'},
                'task':{'project_id':'p1','source_id':'synthetic-code','repository_commit':'a'*40,'problem':'Repair'}})
        self.assertFalse(result['code_verified']);self.assertEqual(result['verification']['exit_code'],1)
        self.assertEqual(result['executed_test_evidence']['final_passed'],0)

    def test_wrong_commit_and_cross_project_snapshot_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'approved_snapshot_commit_required'):
            worker.materialize(self.sources,'p1','synthetic-code','b'*40,self.root/'bad')
        with self.assertRaisesRegex(ValueError,'approved_snapshot_commit_required'):
            worker.materialize(self.sources,'p2','synthetic-code','a'*40,self.root/'bad')

    def test_symlink_created_in_sandbox_is_not_read_as_host_output(self):
        workspace=self.root/'workspace';workspace.mkdir();(workspace/'escape.py').symlink_to('/etc/passwd')
        with self.assertRaisesRegex(ValueError,'sandbox_symlink_output_rejected'):worker.patch_diff(workspace,{})


if __name__=='__main__':unittest.main()
