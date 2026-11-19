"""Async internal service auth, policy and admission checks; no provider or database."""
import importlib.util
import json
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import subprocess
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer

spec=importlib.util.spec_from_file_location('code_worker_server',Path(__file__).with_name('server.py'))
server_module=importlib.util.module_from_spec(spec);spec.loader.exec_module(server_module)
TOKEN='synthetic-service-bearer-token-min24'


class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.release=threading.Event();self.seen=[]
        def execute(payload):
            self.seen.append(payload);self.release.wait(3)
            return {'code_verified':True,'business_verified':False,'diff':'synthetic diff','tool_receipts':[]}
        self.jobs=server_module.Jobs(TOKEN,{'source':{'repository_commit':'a'*40,'argv':['python','-m','pytest','-q']}},execute)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),server_module.handler(self.jobs))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.body={'config':{'model':'synthetic','api_key':'synthetic-private','base_url':'https://provider.invalid/v1'},
            'task':{'project_id':'project','source_id':'source','repository_commit':'a'*40,'problem':'Original test failed'}}

    def tearDown(self):
        self.release.set();self.server.shutdown();self.server.server_close();self.thread.join()

    def call(self,path='/jobs',body=None,token=TOKEN):
        data=json.dumps(self.body if body is None else body).encode()
        request=Request(f'http://127.0.0.1:{self.server.server_port}'+path,data=data if path=='/jobs' else None,
            headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
        try:
            with urlopen(request,timeout=3) as response:return response.status,json.load(response)
        except HTTPError as error:return error.code,json.load(error)

    def test_auth_single_job_busy_and_async_receipts(self):
        self.assertEqual(self.call(token='wrong')[0],401)
        status,submitted=self.call();self.assertEqual(status,202)
        self.assertEqual(self.call()[0],503)
        self.assertEqual(self.call('/jobs/'+submitted['job_id'])[1]['status'],'running')
        self.release.set()
        deadline=time.monotonic()+3
        while self.jobs.get(submitted['job_id'])['status']=='running' and time.monotonic()<deadline:time.sleep(.01)
        status,result=self.call('/jobs/'+submitted['job_id'])
        self.assertEqual(status,200);self.assertTrue(result['result']['code_verified'])
        self.assertNotIn('synthetic-private',json.dumps(result))
        self.assertEqual(self.seen[0]['test_command'],'python -m pytest -q')

    def test_request_cannot_choose_test_shell_or_unapproved_version(self):
        self.assertEqual(self.call(body={**self.body,'test_command':'arbitrary command'})[0],400)
        self.assertEqual(self.call(body={**self.body,'task':{**self.body['task'],'repository_commit':'b'*40}})[0],400)
        self.assertEqual(self.call(body={**self.body,'task':{**self.body['task'],'source_id':'unapproved'}})[0],400)
        self.assertEqual(self.seen,[])

    def test_timed_out_worker_only_cleans_its_labelled_sandbox(self):
        calls=[]
        def execute(argv,**kwargs):
            calls.append((argv,kwargs))
            if argv[0]==server_module.sys.executable:raise subprocess.TimeoutExpired(argv,300)
            if argv[:3]==['docker','ps','-aq']:return SimpleNamespace(stdout='a'*12+'\n')
            return SimpleNamespace(stdout='')
        with patch.object(server_module.subprocess,'run',side_effect=execute):
            with self.assertRaises(subprocess.TimeoutExpired):server_module.Jobs.execute({'config':{},'task':{}})
        self.assertTrue(calls[1][0][-1].startswith('label=engram.code-repair-job='))
        ownership=calls[0][1]['env']['CODE_REPAIR_JOB_ID']
        self.assertEqual(calls[1][0][-1],'label=engram.code-repair-job='+ownership)
        self.assertEqual(calls[2][0],['docker','rm','-f','a'*12])

    def test_body_and_endpoint_limits(self):
        request=Request(f'http://127.0.0.1:{self.server.server_port}/jobs',data=b'x'*(1024*1024+1),headers={'Authorization':'Bearer '+TOKEN})
        with self.assertRaises(HTTPError) as error:urlopen(request,timeout=3)
        self.assertEqual(error.exception.code,413)
        self.assertEqual(self.call('/jobs/not-a-job')[0],404)
        self.assertEqual(self.call('/jobs/'+'a'*32)[0],404)


if __name__=='__main__':unittest.main()
