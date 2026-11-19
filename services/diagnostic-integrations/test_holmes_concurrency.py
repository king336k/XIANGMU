"""Real HTTP concurrency against a controlled child stub, not provider capacity."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout,redirect_stderr
import importlib.util
import io
import json
import os
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request,urlopen

SPEC=importlib.util.spec_from_file_location('holmes_http',Path(__file__).with_name('holmes_service.py'))
service=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(service)


class ConcurrencyTest(unittest.TestCase):
    def test_concurrency_setting_is_default_four_and_bounded_one_to_eight(self):
        with patch.dict(os.environ,{},clear=True):self.assertEqual(service.concurrency_limit(),4)
        for value in ('1','4','8'):
            with patch.dict(os.environ,{'HOLMES_MAX_CONCURRENCY':value}):
                self.assertEqual(service.concurrency_limit(),int(value))
        for value in ('0','9','-1','abc','4.0'):
            with self.subTest(value=value),patch.dict(os.environ,{'HOLMES_MAX_CONCURRENCY':value}):
                with self.assertRaises(ValueError):service.concurrency_limit()

    def test_four_enter_concurrently_and_fifth_gets_429_without_logging_body(self):
        service.TOKEN='synthetic-service-token-at-least24'
        service.SLOTS=threading.BoundedSemaphore(service.concurrency_limit())
        server=service.ThreadingHTTPServer(('127.0.0.1',0),service.Handler)
        server.daemon_threads=True
        serving=threading.Thread(target=server.serve_forever,daemon=True);serving.start()
        url=f'http://127.0.0.1:{server.server_port}/investigate'
        entered=threading.Condition();release=threading.Event();count=0
        def child(*args,**kwargs):
            nonlocal count
            self.assertIn('synthetic-body-secret',kwargs['input'].decode())
            with entered:count+=1;entered.notify_all()
            if not release.wait(5):raise TimeoutError('controlled child not released')
            return SimpleNamespace(returncode=0,stdout=b'{"ready":true}')
        def post():
            request=Request(url,data=json.dumps({'config':{'api_key':'synthetic-body-secret'}}).encode(),
                headers={'Content-Type':'application/json','Authorization':'Bearer '+service.TOKEN},method='POST')
            try:
                with urlopen(request,timeout=7) as response:return response.status,json.load(response)
            except HTTPError as response:
                with response:return response.code,json.load(response)
        output=io.StringIO();errors=io.StringIO()
        try:
            with patch.object(service.subprocess,'run',side_effect=child),redirect_stdout(output),redirect_stderr(errors),ThreadPoolExecutor(max_workers=4) as pool:
                futures=[pool.submit(post) for _ in range(4)]
                try:
                    with entered:self.assertTrue(entered.wait_for(lambda:count==4,timeout=4))
                    status,result=post()
                    self.assertEqual((status,result.get('reason')),(429,'service_busy'))
                    self.assertEqual(count,4)
                finally:release.set()
                self.assertEqual([future.result()[0] for future in futures],[200]*4)
                self.assertEqual(post()[0],200)  # slots released after completion
            self.assertEqual(output.getvalue()+errors.getvalue(),'')
        finally:
            release.set();server.shutdown();server.server_close();serving.join()


if __name__=='__main__':unittest.main()
