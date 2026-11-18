import importlib.util
import json
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

SPEC = importlib.util.spec_from_file_location('service', Path(__file__).with_name('holmes_service.py'))
service = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(service)


class ServiceBoundaryTest(unittest.TestCase):
    def setUp(self):
        service.TOKEN = 'synthetic-service-token-minimum24'
        self.server = service.ThreadingHTTPServer(('127.0.0.1', 0), service.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}/investigate'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_authentication_required_before_subprocess(self):
        with patch.object(service.subprocess, 'run') as child:
            with self.assertRaises(HTTPError) as failure:
                urlopen(Request(self.url, data=b'{}'), timeout=2)
            self.assertEqual(failure.exception.code, 401)
            child.assert_not_called()

    def test_oversized_body_rejected(self):
        with self.assertRaises(HTTPError) as failure:
            urlopen(Request(self.url, data=b'{}', headers={'Authorization':'Bearer '+service.TOKEN,
                'Content-Length':str(1024*1024+1)}), timeout=2)
        self.assertEqual(failure.exception.code, 413)

    def test_fixed_subprocess_receives_json_only_in_stdin(self):
        raw = json.dumps({'config':{'api_key':'synthetic-provider-key'}}).encode()
        result = SimpleNamespace(returncode=0, stdout=b'{"ready":true}')
        with patch.object(service.subprocess, 'run', return_value=result) as child:
            with urlopen(Request(self.url, data=raw, headers={'Authorization':'Bearer '+service.TOKEN}), timeout=2) as response:
                self.assertTrue(json.load(response)['ready'])
        self.assertEqual(child.call_args.kwargs['input'], raw)
        self.assertNotIn('synthetic-provider-key', json.dumps(child.call_args.args))
        self.assertNotIn('HOLMES_SERVICE_TOKEN', child.call_args.kwargs['env'])


if __name__ == '__main__':
    unittest.main()
