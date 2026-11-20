import unittest
from unittest.mock import MagicMock,patch
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from file_browser import application_status

class ApplicationStatusTests(unittest.TestCase):
    def test_readiness_uses_actual_local_frontend_and_version_not_robot_state(self):
        response=MagicMock(status=200)
        response.read.return_value=b'<!doctype html><html><body><div id="app"></div></body></html>'
        opener=MagicMock();opener.open.return_value.__enter__.return_value=response
        with (patch('file_browser.local_launcher_request',return_value={
            'protocol':'daq-application-status-v1','version':'v1.0.5','revision':'a'*40})as local,
            patch('file_browser.build_opener',return_value=opener)):
            value=application_status({'test':'local'})
        self.assertTrue(value['web_ready']);self.assertEqual(value['version'],'v1.0.5')
        self.assertEqual(local.call_args.kwargs,{'application':True,'timeout':1})

    def test_unavailable_service_is_not_ready_and_missing_local_policy_is_unknown(self):
        self.assertIsNone(application_status(None))
        with patch('file_browser.local_launcher_request',side_effect=ValueError('unavailable')):
            self.assertFalse(application_status({})['web_ready'])
        with patch('file_browser.local_launcher_request',return_value={'legacy':True}):
            self.assertIsNone(application_status({})['web_ready'])

if __name__=='__main__':unittest.main()
