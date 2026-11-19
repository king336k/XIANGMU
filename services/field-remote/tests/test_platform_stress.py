from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import base64
import hashlib
import hmac
from pathlib import Path
import sys
import threading
import tempfile
import unittest
import uuid
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from platform_stress import (Http, ApiError, validate_manifest, wait_for_markers, mixed_overlap,
                             submit_diagnostic, submit_signed_feedback, job_lifecycle_summary, operation_statistics)
from platform_stress import terminal_probe_summary, active_terminal_hold


def fixture():
    return {'test_environment':True,'isolation_id':'synthetic-isolation','base_url':'http://127.0.0.1:12345',
            'model_mode':'controlled_stub','users':[{'id':'user1','headers':{'Authorization':'synthetic-fixture-only'}}],
            'stations':[{'device_id':str(uuid.uuid4()),'owner_user_id':'user1','allowed_user_ids':['user1'],
                         'token':'rw_synthetic-unused-fixture','defect_ids':[str(uuid.uuid4()),str(uuid.uuid4())],
                         'initial_config':{'fixed':False},'expected_repair_config':{'fixed':True}}]}


class PlatformStressTests(unittest.TestCase):
    def test_sustained_probe_executes_unique_roundtrips_until_deadline_without_slow_unit_test(self):
        now=[100.0];seen=[];client=Mock()
        def read(expected):
            seen.append(expected);now[0]+=1
            return True
        result=active_terminal_hold(client,'/api/terminal/',3,100,read,clock=lambda:now[0],pause=lambda _:None)
        self.assertEqual(result['verified_roundtrips'],3)
        self.assertEqual(result['hold_seconds_observed'],3)
        self.assertEqual(len(set(seen)),3)
        self.assertEqual(client.request.call_count,3)
        for call,expected in zip(client.request.call_args_list,seen):
            raw=base64.b64decode(call.args[2]['data']).decode()
            self.assertNotIn(expected,raw)
            self.assertIn('printf',raw)
        client.reset_mock()
        nohold=active_terminal_hold(client,'/api/terminal/',0,100,read,clock=lambda:100,pause=lambda _:None)
        self.assertEqual(nohold['verified_roundtrips'],0);client.request.assert_not_called()
        manifest=fixture();manifest['terminal_probe_hold_seconds']=301
        with self.assertRaises(ValueError):validate_manifest(manifest)
        manifest['terminal_probe_hold_seconds']=-1
        with self.assertRaises(ValueError):validate_manifest(manifest)

    def test_signing_material_stays_in_memory_and_is_signed_at_actual_submission_time(self):
        requests=[];issue_id=str(uuid.uuid4())
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_args):pass
            def do_POST(self):
                raw=self.rfile.read(int(self.headers['Content-Length']))
                requests.append({'headers':dict(self.headers),'raw':raw})
                self.send_response(201);self.send_header('X-Remote-Stress-Isolation','synthetic-isolation')
                self.end_headers();self.wfile.write(json.dumps({'issueId':issue_id,'issueCode':'Q-ONLY-TEST'}).encode())
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            samples=[];client=Http('http://127.0.0.1:'+str(server.server_address[1]),'synthetic-isolation',samples=samples)
            request={'path':'/api/quality-auth/daq-reports/','payload':{'description':'测试载荷','device':'test-only'},
                     'signing':{'key_id':'test-key','audience':'project-feedback','secret':'synthetic-not-a-real-secret',
                                'principal':{'id':123,'username':'test-user'}},
                     'headers':{'X-Issue-Principal-Timestamp':'1'}}
            for timestamp in (1000,1125):
                with patch('platform_stress.time.time',return_value=timestamp):
                    result=submit_signed_feedback(client,request)
                self.assertEqual(result,{'issue_id':issue_id})
            for captured,stamp in zip(requests,('1000','1125')):
                headers={key.lower():value for key,value in captured['headers'].items()}
                self.assertEqual(headers['x-issue-principal-timestamp'],stamp)
                digest=hashlib.sha256(captured['raw']).hexdigest()
                self.assertEqual(headers['x-issue-content-sha256'],digest)
                encode=lambda value:base64.urlsafe_b64encode(value.encode()).decode().rstrip('=')
                canonical='\n'.join(['ISSUE-IDENTITY-V2',encode('project-feedback'),encode('test-key'),stamp,
                                     encode(headers['x-issue-principal-nonce']),'POST',encode(request['path']),digest,
                                     encode(headers['x-issue-principal'])])
                signature=base64.urlsafe_b64encode(hmac.new(request['signing']['secret'].encode(),canonical.encode(),hashlib.sha256).digest()).decode().rstrip('=')
                self.assertEqual(signature,headers['x-issue-principal-signature'])
            nonces=[{key.lower():value for key,value in row['headers'].items()}['x-issue-principal-nonce'] for row in requests]
            self.assertNotEqual(*nonces)
            self.assertNotIn('synthetic-not-a-real-secret',json.dumps(samples))
            self.assertNotIn('测试载荷',json.dumps(samples,ensure_ascii=False))
            self.assertNotIn('X-Issue',json.dumps(samples))
        finally:server.shutdown();server.server_close();thread.join()

    def test_terminal_probe_requires_real_markers_distinct_users_and_common_open_interval(self):
        rows=[{'device_id':str(n),'terminal_probe':{'owner_user_id':str(n),'session_id':'s'+str(n),
               'marker_verified':True,'identity':{'username':'fixture-user','hostname':'station-'+str(n)},
               'opened_at':1+n*.01,'last_read_at':3,'probe_start':2,'probe_end':4,'closed_at':5}}
              for n in range(10)]
        result=terminal_probe_summary(rows)
        self.assertTrue(result['verified'])
        self.assertEqual(result['max_concurrent_open'],10)
        self.assertEqual(result['distinct_users'],10)
        self.assertGreater(result['common_open_interval']['seconds'],0)
        rows[1]['terminal_probe']['owner_user_id']='0'
        self.assertFalse(terminal_probe_summary(rows)['verified'])
        rows[1]['terminal_probe']['owner_user_id']='1'
        rows[2]['terminal_probe']['marker_verified']=False
        self.assertFalse(terminal_probe_summary(rows)['verified'])
        rows[2]['terminal_probe']['marker_verified']=True
        for row in rows:
            row['terminal_probe'].update(hold_seconds_requested=60,hold_started_at=2,hold_completed_at=62,
                                          verified_roundtrips=55)
        self.assertTrue(terminal_probe_summary(rows)['verified'])
        rows[0]['terminal_probe']['hold_completed_at']=61.9
        self.assertFalse(terminal_probe_summary(rows)['verified'])
        rows[0]['terminal_probe']['hold_completed_at']=62
        rows[9]['terminal_probe'].update(opened_at=6,closed_at=7,probe_start=6,probe_end=7)
        self.assertFalse(terminal_probe_summary(rows)['verified'])

    def test_full_job_capacity_uses_real_lifecycle_and_does_not_count_stages(self):
        jobs=[{'id':str(n),'mode':'repair','status':'completed','worker_started_at':start,
               'worker_completed_at':end,'queued_at':start-.5,
               'observations':[{'at':start-.4,'status':'queued'},{'at':start+.1,'status':'running'}],
               'stages':[{'stage':'diagnose'},{'stage':'repair'},{'stage':'verify'}]}
              for n,(start,end) in enumerate(((1,10),(2,8),(3,7),(4,9),(10,11)))]
        report=job_lifecycle_summary([{'device_id':'one','jobs':jobs}],4)
        self.assertEqual(report['job_count'],5)
        self.assertEqual(report['max_concurrent_running'],4)
        self.assertTrue(report['capacity_verified'])
        self.assertFalse(report['capacity_exceeded'])
        self.assertEqual(report['queued_jobs_observed'],5)
        self.assertEqual(report['queue_wait_seconds']['p95'],.5)
        jobs.append({'id':'overflow','mode':'repair','status':'completed','worker_started_at':5,'worker_completed_at':6})
        overflow=job_lifecycle_summary([{'jobs':jobs}],4)
        self.assertEqual(overflow['max_concurrent_running'],5)
        self.assertTrue(overflow['capacity_exceeded'])
        self.assertFalse(overflow['capacity_verified'])

    def test_missing_worker_timing_never_claims_capacity_or_invents_queue_wait(self):
        report=job_lifecycle_summary([{'jobs':[{'id':'one','mode':'repair','status':'completed'}]}],4)
        self.assertIsNone(report['max_concurrent_running'])
        self.assertIsNone(report['queued_jobs_observed'])
        self.assertNotIn('queue_wait_seconds',report)
        self.assertFalse(report['capacity_verified'])
        partial=job_lifecycle_summary([{'jobs':[{'id':'one','worker_started_at':1,'worker_completed_at':2},
                                               {'id':'two'}]}],1)
        self.assertFalse(partial['capacity_verified'])

    def test_http_operation_concurrency_and_expected_409_are_not_worker_jobs(self):
        rows=[{'operation':'files','ok':True,'status':201,'elapsed_ms':1,'started_at':1,'completed_at':4},
              {'operation':'files','ok':True,'status':409,'elapsed_ms':2,'started_at':2,'completed_at':3},
              {'operation':'files','ok':False,'status':500,'elapsed_ms':3,'started_at':4,'completed_at':5}]
        report=operation_statistics(rows)['files']
        self.assertEqual(report['max_concurrent_requests'],2)
        self.assertEqual(report['errors'],1)
        self.assertEqual(report['http_status_counts'],{'201':1,'409':1,'500':1})

    def test_signed_feedback_validates_response_without_reporting_signatures_payload_or_code(self):
        issue=str(uuid.uuid4());client=Mock()
        client.request.return_value={'issueId':issue,'issueCode':'Q-TEST-001'}
        request={'path':'/api/quality-auth/daq-reports/','payload':{'sensitive':'fixture-payload-only'},
                 'headers':{'X-Signature':'fixture-signature-only'}}
        result=submit_signed_feedback(client,request)
        self.assertEqual(result,{'issue_id':issue})
        self.assertNotIn('fixture-',json.dumps(result));self.assertNotIn('Q-TEST',json.dumps(result))
        self.assertEqual(client.request.call_args.kwargs['expected'],(200,201))
        for response in ({'issueId':issue},{'issueCode':'Q-TEST'},{'issueId':'invalid','issueCode':'Q-TEST'}):
            client.request.return_value=response
            with self.assertRaises(AssertionError):submit_signed_feedback(client,request)
        manifest=fixture();manifest['stations'][0]['signed_feedback_requests']=[request]
        validate_manifest(manifest)
        request['path']='https://outside.invalid'
        with self.assertRaises(ValueError):validate_manifest(manifest)

    def test_new_rules_diagnostic_submits_and_requires_real_completed_status(self):
        job_id=str(uuid.uuid4())
        path='/api/workspaces/stress/projects/'+str(uuid.uuid4())+'/quality/defects/'+str(uuid.uuid4())+'/diagnostics/'
        client=Mock()
        client.request.side_effect=[{'id':job_id,'status':'queued'},
                                    {'id':job_id,'status':'running'},
                                    {'id':job_id,'status':'completed','started_at':'start','completed_at':'end'}]
        with patch('platform_stress.time.sleep'):
            result=submit_diagnostic(client,path)
        self.assertEqual(result['status'],'completed')
        self.assertEqual([row['status'] for row in result['observations']],['running','completed'])
        submitted=client.request.call_args_list[0]
        self.assertEqual(submitted.args[:2],('POST',path))
        self.assertEqual(submitted.args[2]['mode'],'rules')
        self.assertIsNotNone(uuid.UUID(submitted.args[2]['request_id']))
        self.assertEqual(client.request.call_args_list[1].args[1],path.split('/defects/')[0]+'/diagnostics/'+job_id+'/')
        client.request.side_effect=[{'id':job_id,'status':'queued'},{'id':job_id,'status':'failed'}]
        with self.assertRaisesRegex(AssertionError,'did not complete'):submit_diagnostic(client,path)

    def test_rejects_public_or_unmarked_environment_and_mixed_real_model(self):
        validate_manifest(fixture())
        for change in ({'test_environment':False},{'base_url':'http://180.153.172.19:18886'},
                       {'base_url':'http://production.example'},{'base_url':'http://user:password@127.0.0.1'},
                       {'model_mode':'unmarked'}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                validate_manifest({**fixture(),**change})
        manifest=fixture();manifest['model_mode']='real_model_e2e'
        manifest['stations'].append({**manifest['stations'][0],'device_id':str(uuid.uuid4())})
        with self.assertRaises(ValueError):validate_manifest(manifest)
        manifest=fixture();manifest['stations'][0]['defect_ids']=['same','same']
        with self.assertRaises(ValueError):validate_manifest(manifest)

    def test_barrier_requires_every_station_and_overlap_uses_actual_intervals(self):
        artifacts=Path('/home/engram/Documents/tmp/artifacts/remote-diagnostics-2026-11-18/mixed-edge-stress')
        artifacts.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=artifacts) as root:
            folder=Path(root)/'ready';folder.mkdir();(folder/'one').touch()
            with self.assertRaises(TimeoutError):wait_for_markers(folder,2,seconds=.01)
            (folder/'two').touch();wait_for_markers(folder,2,seconds=.01)
        stations=[{'device_id':'one','phase_intervals':[{'phase':'files','started_at':1,'completed_at':5}],
                   'file_http_intervals':[{'started_at':3,'completed_at':4}]},
                  {'device_id':'two','phase_intervals':[{'phase':'agent_wait','started_at':2,'completed_at':6}],
                   'run_observations':[{'model_started_at':3.5,'model_completed_at':4.5}]}]
        result=mixed_overlap(stations)
        self.assertTrue(result['cross_station_files_agent_wait_overlap'])
        self.assertTrue(result['cross_station_file_http_model_execution_overlap'])
        self.assertEqual(result['model_execution_pairs'][0]['overlap_seconds'],.5)
        stations[1]['run_observations'][0].update(model_started_at=8,model_completed_at=9)
        self.assertFalse(mixed_overlap(stations)['cross_station_file_http_model_execution_overlap'])

    def test_real_http_requires_marker_and_records_safe_latency_only(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_args):pass
            def do_GET(self):
                self.send_response(409 if self.path.endswith('busy/') else 200)
                if not self.path.endswith('unmarked/'):
                    self.send_header('X-Remote-Stress-Isolation','synthetic-isolation')
                self.end_headers();self.wfile.write(b'{"ok":true}')
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            samples=[]
            client=Http('http://127.0.0.1:'+str(server.server_address[1]),'synthetic-isolation',
                        {'Authorization':'synthetic-private-header'},samples)
            self.assertTrue(client.request('GET','/api/ready/')['ok'])
            self.assertTrue(client.request('GET','/api/busy/',expected=(409,))['ok'])
            with self.assertRaises(ApiError):client.request('GET','/api/busy/')
            with self.assertRaisesRegex(ValueError,'marker'):client.request('GET','/api/unmarked/')
            self.assertNotIn('synthetic-private-header',json.dumps(samples))
            self.assertEqual(len(samples),4)
            self.assertEqual(sum(not item['ok'] for item in samples),2)
            self.assertTrue(all(item['elapsed_ms']>=0 for item in samples))
            with self.assertRaises(ValueError):client.request('GET','https://outside.invalid')
        finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
