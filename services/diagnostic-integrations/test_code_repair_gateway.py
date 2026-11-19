"""Project/run scoped code-worker gateway, with real local HTTP and no database."""
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import threading
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
SPEC=importlib.util.spec_from_file_location('code_gateway',ROOT/'ProjectServer/plane/quality/remote_code_repair.py')


class Cache:
    def __init__(self):self.values={}
    def get(self,key,default=None):return self.values.get(key,default)
    def set(self,key,value,timeout=None):self.values[key]=value
    def add(self,key,value,timeout=None):
        if key in self.values:return False
        self.values[key]=value;return True
    def delete(self,key):self.values.pop(key,None)


class GatewayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(cls.module)

    def setUp(self):
        self.cache=Cache();self.requests=[];self.busy=False;self.large=False;fixture=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));fixture.requests.append((self.headers.get('Authorization'),body))
                self.send_response(503 if fixture.busy else 202);self.end_headers()
                self.wfile.write(json.dumps({'error':'busy'} if fixture.busy else {'job_id':str(len(fixture.requests)).zfill(32),'status':'running'}).encode())
            def do_GET(self):
                fixture.requests.append((self.headers.get('Authorization'),self.path))
                self.send_response(200);self.end_headers()
                self.wfile.write(json.dumps({'status':'completed','result':{'code_verified':True,'business_verified':True,
                    'production_deployed':True,'repaired':True,'source_id':'approved','repository_commit':'a'*40,'diff':'synthetic-provider-secret synthetic-service-token-'+('x'*300000 if fixture.large else 'change'),
                    'verification':{'exit_code':0},'tool_receipts':[]}}).encode())
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.env=patch.dict(os.environ,{'REMOTE_CODE_REPAIR_URL':f'http://127.0.0.1:{self.server.server_port}',
            'REMOTE_CODE_REPAIR_TOKEN':'synthetic-service-token-minimum24','QUALITY_REMOTE_SOURCE_SNAPSHOTS_ROOT':'/administrator/snapshots'})
        self.env.start()
        self.patches=[patch.object(self.module,'_cache',return_value=self.cache),
            patch.object(self.module,'_provider',return_value={'configured':True,'model':'synthetic','api_key':'synthetic-provider-secret','base_url':'https://provider.invalid/v1'}),
            patch.object(self.module,'_catalog',return_value={'sources':[{'id':'approved','repository_commit':'a'*40}]})]
        for item in self.patches:item.start()
        project=SimpleNamespace(id='project-a',workspace_id='workspace-a')
        self.run=SimpleNamespace(pk='run-a',owner_id='owner-a',mode='repair',defect=SimpleNamespace(project_id='project-a',project=project),
            workstation=SimpleNamespace(agent=SimpleNamespace(project_id='project-a')))

    def tearDown(self):
        for item in reversed(self.patches):item.stop()
        self.env.stop();self.server.shutdown();self.server.server_close();self.thread.join()

    def test_start_injects_server_commit_and_memory_only_model_config(self):
        result=self.module.start(self.run,'approved','Investigate actual failing code')
        self.assertEqual(result['status'],'running');self.assertEqual(result['repository_commit'],'a'*40)
        auth,body=self.requests[0]
        self.assertEqual(body['task']['repository_commit'],'a'*40)
        self.assertEqual(body['config']['api_key'],'synthetic-provider-secret')
        self.assertNotIn('synthetic-provider-secret',json.dumps(result))
        self.assertNotIn('synthetic-provider-secret',json.dumps(self.cache.values))
        self.assertNotIn('test_command',body)

    def test_status_is_run_owner_project_bound_and_never_business_success(self):
        started=self.module.start(self.run,'approved','Failure')
        job=started['job_id'];self.assertEqual(self.module.status(SimpleNamespace(**{**vars(self.run),'pk':'other'}),job)['error'],'code_job_not_owned')
        self.assertEqual(self.module.status(SimpleNamespace(**{**vars(self.run),'owner_id':'other'}),job)['error'],'code_job_not_owned')
        result=self.module.status(self.run,job)
        self.assertTrue(result['result']['code_verified'])
        self.assertFalse(result['result']['business_verified'] or result['result']['production_deployed'] or result['result']['repaired'])
        self.assertNotIn('synthetic-provider-secret',json.dumps(result))

    def test_readonly_mode_unknown_source_and_two_job_budget(self):
        for mode in ('diagnose','verify'):
            self.run.mode=mode;self.assertEqual(self.module.start(self.run,'approved','Failure')['error'],'code_repair_mode_required')
        self.run.mode='repair'
        self.assertEqual(self.module.start(self.run,'unapproved','Failure')['error'],'code_source_not_authorized')
        self.module.start(self.run,'approved','Failure one');self.module.start(self.run,'approved','Failure two')
        self.assertEqual(self.module.start(self.run,'approved','Failure three')['error'],'code_job_budget_exhausted')
        self.assertEqual(len(self.requests),2)

    def test_busy_does_not_consume_job_budget_or_leak_response(self):
        self.busy=True
        result=self.module.start(self.run,'approved','Failure')
        self.assertEqual(result['error'],'code_worker_busy');self.assertIn('正忙',result['note'])
        self.busy=False
        self.assertEqual(self.module.start(self.run,'approved','Retry')['status'],'running')

    def test_cross_project_binding_unknown_outcome_and_transport_uncertainty_are_bounded(self):
        started=self.module.start(self.run,'approved','Failure');job=started['job_id']
        other=SimpleNamespace(**vars(self.run));other.defect=SimpleNamespace(project_id='other',project=other.defect.project)
        self.assertEqual(self.module.status(other,job)['error'],'code_job_not_owned')
        self.cache.values.clear()
        with patch.object(self.module,'_request',return_value={'error':'code_worker_unavailable'}):
            self.module.start(self.run,'approved','Unknown first')
            self.module.start(self.run,'approved','Unknown second')
            self.assertEqual(self.module.start(self.run,'approved','No duplicate flood')['error'],'code_job_budget_exhausted')
        self.assertNotIn('synthetic-provider-secret',json.dumps(self.cache.values))

    def test_wrong_source_or_version_receipt_cannot_count_as_code_verified(self):
        job=self.module.start(self.run,'approved','Failure')['job_id']
        with patch.object(self.module,'_request',return_value={'status':'completed','result':{
            'source_id':'other','repository_commit':'b'*40,'code_verified':True}}):
            result=self.module.status(self.run,job)
        self.assertFalse(result['result']['code_verified']);self.assertFalse(result['result']['provenance_verified'])
        self.assertIn('固定提交',result['result']['provenance_gap'])

    def test_fixed_configuration_rejects_credentials_redirect_paths_and_proxy_inputs(self):
        for value in ('file:///etc/passwd','http://user:secret@127.0.0.1','http://127.0.0.1/path','http://127.0.0.1?token=value'):
            with patch.dict(os.environ,{'REMOTE_CODE_REPAIR_URL':value}):
                result=self.module.start(self.run,'approved','Failure')
                self.assertEqual(result['error'],'code_worker_unavailable')
        self.assertEqual(self.requests,[])

    def test_oversized_result_is_explicit_incomplete_not_success(self):
        job=self.module.start(self.run,'approved','Failure')['job_id'];self.large=True
        result=self.module.status(self.run,job)
        self.assertTrue(result['result_incomplete'])
        self.assertFalse(result.get('code_verified',False))
        self.assertEqual(result['error'],'code_worker_response_limit')


if __name__=='__main__':unittest.main()
