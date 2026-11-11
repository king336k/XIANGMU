import importlib.util
import os
import unittest
from unittest.mock import patch
from pathlib import Path
spec=importlib.util.spec_from_file_location("bridge",Path(__file__).with_name("bridge.py"));bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)
class Tests(unittest.TestCase):
    def test_default_only_checks_and_missing_values_never_launch(self):
        with patch.dict(os.environ,{},clear=True), patch.object(bridge.subprocess,"Popen") as launch:
            self.assertEqual(bridge.main(["daq"]),2);launch.assert_not_called()
    def test_public_or_wildcard_bind_is_rejected(self):
        for ip in ["0.0.0.0","8.8.8.8","127.0.0.1","169.254.169.254","224.0.0.1"]:
            values={k:"test-fixture" for k in bridge.REQUIRED['cloud']};values['CLOUD_PRIVATE_BIND_IP']=ip
            with patch.dict(os.environ,values,clear=True),patch.object(bridge.subprocess,"Popen") as launch:
                self.assertEqual(bridge.main(["cloud"]),2);launch.assert_not_called()
if __name__=="__main__":unittest.main()
