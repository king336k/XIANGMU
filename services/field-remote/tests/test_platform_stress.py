from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import tempfile
import unittest
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from platform_stress import Http, ApiError, validate_manifest, wait_for_markers, mixed_overlap


def fixture():
    return {'test_environment':True,'isolation_id':'synthetic-isolation','base_url':'http://127.0.0.1:12345',
            'model_mode':'controlled_stub','users':[{'id':'user1','headers':{'Authorization':'synthetic-fixture-only'}}],
            'stations':[{'device_id':str(uuid.uuid4()),'owner_user_id':'user1','allowed_user_ids':['user1'],
                         'token':'rw_synthetic-unused-fixture','defect_ids':[str(uuid.uuid4()),str(uuid.uuid4())],
                         'initial_config':{'fixed':False},'expected_repair_config':{'fixed':True}}]}


class PlatformStressTests(unittest.TestCase):
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
