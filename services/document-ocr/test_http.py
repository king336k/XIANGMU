"""Real loopback HTTP guards; fake extraction only where explicitly labelled."""
import hashlib
import http.client
import importlib.util
import json
from pathlib import Path
import threading
import time
import unittest

ROOT=Path(__file__).parent

class ServiceTests(unittest.TestCase):
 def setUp(self):
  spec=importlib.util.spec_from_file_location('ocr_server',ROOT/'server.py');self.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.module)
  self.started=threading.Event();self.release=threading.Event()
  def fake(raw,kind,digest):
   self.started.set();self.release.wait(1)
   return {'status':'completed','source_sha256':digest,'engine':'tesseract','segments':[{'key':'ocr-1','text':'explicit fake guard fixture','method':'ocr','width':1,'height':1}],'failures':[],'requires_review':True}
  self.server=self.module.create_server(('127.0.0.1',0),'test-only-guard-key',fake);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
 def tearDown(self):
  self.release.set();self.server.shutdown();self.server.server_close()
 def request(self,method,path,raw=b'png fixture',headers=None):
  c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3);h={'Content-Type':'application/octet-stream','Content-Length':str(len(raw)),'Authorization':'Bearer test-only-guard-key','X-Document-Type':'png','X-Content-SHA256':hashlib.sha256(raw).hexdigest()};h.update(headers or {});c.request(method,path,raw,h);r=c.getresponse();body=json.loads(r.read());c.close();return r.status,body
 def test_health_no_secret(self):
  status,body=self.request('GET','/health');self.assertEqual(status,200);self.assertNotIn('test-only-guard-key',json.dumps(body))
 def test_missing_auth(self):self.assertEqual(self.request('POST','/v1/extract',headers={'Authorization':'Bearer bad'})[0],401)
 def test_mismatch_hash(self):self.assertEqual(self.request('POST','/v1/extract',headers={'X-Content-SHA256':'0'*64})[0],400)
 def test_bad_type(self):self.assertEqual(self.request('POST','/v1/extract',headers={'X-Document-Type':'jpeg'})[0],400)
 def test_oversized_body_declared_rejected_before_read(self):self.assertEqual(self.request('POST','/v1/extract',headers={'Content-Length':str(20*1024*1024+1)})[0],413)
 def test_chunked_transfer_rejected(self):self.assertEqual(self.request('POST','/v1/extract',headers={'Transfer-Encoding':'chunked'})[0],400)
 def test_request_log_contains_status_but_not_key_or_document(self):
  from contextlib import redirect_stdout
  from io import StringIO
  output=StringIO();self.release.set()
  with redirect_stdout(output):status,_=self.request('POST','/v1/extract',raw=b'private-document-marker')
  events=[json.loads(line) for line in output.getvalue().splitlines()]
  self.assertEqual(status,200);self.assertTrue(events);self.assertEqual(events[-1]['component'],'document-ocr');self.assertEqual(events[-1]['status'],200)
  self.assertNotIn('test-only-guard-key',str(events));self.assertNotIn('private-document-marker',str(events))
 def test_metadata_response_is_bounded(self):
  self.release.set()
  self.server.shutdown();self.server.server_close()
  self.server=self.module.create_server(('127.0.0.1',0),'test-only-guard-key',lambda *args:{'text':'x'*(2*1024*1024)})
  self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
  status,body=self.request('POST','/v1/extract');self.assertEqual(status,500);self.assertEqual(body['error'],'metadata_budget')
 def test_one_job_busy429_and_review_always_required(self):
  result=[];t=threading.Thread(target=lambda:result.append(self.request('POST','/v1/extract')));t.start();self.assertTrue(self.started.wait(1));self.assertEqual(self.request('POST','/v1/extract')[0],429);self.release.set();t.join();self.assertEqual(result[0][0],200);self.assertTrue(result[0][1]['requires_review'])

if __name__=='__main__':unittest.main()
