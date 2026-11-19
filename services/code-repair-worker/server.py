#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Single-job internal gateway; no request-selected paths, test commands or Docker policy."""
import hmac
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import threading
import time
import uuid

MAX_BODY=1024*1024
WORKER=Path(__file__).with_name('worker.py')


class Jobs:
    def __init__(self,token,runners,executor=None):
        if not isinstance(token,str) or len(token)<24:raise ValueError('service_token_required')
        self.token=token;self.runners=runners;self.executor=executor or self.execute
        self.active=threading.Lock();self.lock=threading.Lock();self.jobs={}

    @staticmethod
    def execute(payload):
        environment={key:value for key,value in os.environ.items() if key in {'PATH','LANG','LC_ALL','PYTHONPATH',
            'QUALITY_REMOTE_SOURCE_SNAPSHOTS_ROOT','CODE_REPAIR_WORK_ROOT','CODE_REPAIR_DEPENDENCIES','CODE_REPAIR_IMAGE'}}
        ownership=uuid.uuid4().hex
        environment['CODE_REPAIR_JOB_ID']=ownership
        try:
            process=subprocess.run([sys.executable,str(WORKER)],input=json.dumps(payload),text=True,capture_output=True,
                timeout=300,check=False,env=environment)
            if process.returncode!=0:raise ValueError('worker_process_failed')
            result=json.loads(process.stdout)
            if not isinstance(result,dict):raise ValueError('worker_result_invalid')
            return result
        finally:
            # A killed controller child cannot run Sandbox.close(); remove only this job's labelled sandbox.
            try:
                containers=subprocess.run(['docker','ps','-aq','--filter','label=engram.code-repair-job='+ownership],
                    capture_output=True,text=True,timeout=10,check=False).stdout.split()
                for identifier in containers:
                    if re.fullmatch(r'[a-f0-9]{12,64}',identifier):
                        subprocess.run(['docker','rm','-f',identifier],capture_output=True,timeout=10,check=False)
            except (OSError,subprocess.SubprocessError):pass

    def submit(self,body):
        if not isinstance(body,dict) or set(body)-{'config','task'}:raise ValueError('invalid_job')
        config=body.get('config');task=body.get('task')
        if not isinstance(config,dict) or not isinstance(task,dict):raise ValueError('invalid_job')
        for key in ('model','api_key','base_url'):
            if not isinstance(config.get(key),str) or not 1<=len(config[key])<=8192:raise ValueError('invalid_model_configuration')
        for key in ('project_id','source_id','repository_commit','problem'):
            if not isinstance(task.get(key),str) or not 1<=len(task[key])<=(20000 if key=='problem' else 200):raise ValueError('invalid_task')
        runner=self.runners.get(task['source_id'])
        if not isinstance(runner,dict) or runner.get('repository_commit')!=task['repository_commit']:
            raise ValueError('test_runner_not_configured_for_source_commit')
        argv=runner.get('argv')
        if not isinstance(argv,list) or not argv or not all(isinstance(arg,str) and 0<len(arg)<2000 for arg in argv):
            raise ValueError('test_runner_not_configured_for_source_commit')
        if not self.active.acquire(blocking=False):return None
        job_id=uuid.uuid4().hex
        with self.lock:
            # Bounded in-memory receipts, no model configuration saved in job records.
            if len(self.jobs)>=100:
                oldest=next(iter(self.jobs));self.jobs.pop(oldest)
            self.jobs[job_id]={'job_id':job_id,'status':'running','scope':'isolated_code_snapshot'}
        payload={'config':{key:config[key] for key in ('model','api_key','base_url')},'task':dict(task),
            'test_command':shlex.join(argv)}
        def run():
            try:result=self.executor(payload);value={'job_id':job_id,'status':'completed','result':result}
            except Exception as error:value={'job_id':job_id,'status':'failed','error_class':type(error).__name__}
            finally:
                with self.lock:self.jobs[job_id]=value
                self.active.release()
        threading.Thread(target=run,daemon=True).start()
        return job_id

    def get(self,job_id):
        with self.lock:return self.jobs.get(job_id)


def handler(jobs):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup();self.connection.settimeout(10)
        def log_message(self,*args):pass
        def response(self,status,value):
            raw=json.dumps(value,ensure_ascii=False).encode()
            self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)))
            self.end_headers();self.wfile.write(raw)
        def authorized(self):
            auth=self.headers.get('Authorization','')
            if len(auth)>8192:return False
            return hmac.compare_digest(auth.encode(),('Bearer '+jobs.token).encode())
        def do_POST(self):
            if not self.authorized():return self.response(401,{'error':'unauthorized'})
            if self.path!='/jobs':return self.response(404,{'error':'unknown_endpoint'})
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=MAX_BODY:return self.response(413,{'error':'request_body_limit'})
                value=json.loads(self.rfile.read(length));job_id=jobs.submit(value)
            except (ValueError,TypeError,KeyError):return self.response(400,{'error':'invalid_or_unconfigured_job'})
            if job_id is None:return self.response(503,{'error':'worker_busy','retryable':True})
            return self.response(202,{'job_id':job_id,'status':'running','poll_path':'/jobs/'+job_id})
        def do_GET(self):
            if not self.authorized():return self.response(401,{'error':'unauthorized'})
            match=re.fullmatch(r'/jobs/([a-f0-9]{32})',self.path)
            if not match:return self.response(404,{'error':'unknown_endpoint'})
            value=jobs.get(match.group(1))
            return self.response(200,value) if value else self.response(404,{'error':'unknown_job'})
    return Handler


def main():
    try:
        runners=json.loads(os.environ.get('CODE_REPAIR_TEST_RUNNERS','{}'))
        if not isinstance(runners,dict):raise ValueError()
        jobs=Jobs(os.environ.get('CODE_REPAIR_SERVICE_TOKEN',''),runners)
        server=ThreadingHTTPServer((os.environ.get('CODE_REPAIR_BIND','127.0.0.1'),int(os.environ.get('CODE_REPAIR_PORT','8094'))),handler(jobs))
        server.serve_forever()
    except (ValueError,OSError):raise SystemExit('code_repair_service_configuration_invalid') from None


if __name__=='__main__':main()
