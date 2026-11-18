import importlib.util
from pathlib import Path
import tempfile
import os
import sys
import unittest
from unittest.mock import patch

SCRIPT=Path(__file__).resolve().parents[1]/'stress_harness.py'
sys.path.insert(0,str(SCRIPT.parent))
spec=importlib.util.spec_from_file_location('stress_harness',SCRIPT)
stress=importlib.util.module_from_spec(spec)
spec.loader.exec_module(stress)
ARTIFACTS=Path('/home/engram/Documents/tmp/artifacts/remote-diagnostics-2026-11-18/mixed-edge-stress')
ARTIFACTS.mkdir(parents=True,exist_ok=True)


class MixedStressTests(unittest.TestCase):
    def test_statistics_preserve_counts_errors_and_quantiles(self):
        samples=[{'operation':'upload','ok':True,'elapsed_ms':1},
                 {'operation':'upload','ok':False,'elapsed_ms':3},
                 {'operation':'terminal','ok':True,'elapsed_ms':7}]
        result=stress.summarize(samples)
        self.assertEqual(result['upload']['count'],2)
        self.assertEqual(result['upload']['errors'],1)
        self.assertEqual(result['upload']['p50_ms'],2)
        self.assertEqual(result['upload']['p95_ms'],3)
        self.assertEqual(result['terminal']['p95_ms'],7)

    def test_one_real_station_checks_pty_files_patch_expiry_and_cleanup(self):
        with tempfile.TemporaryDirectory(dir=ARTIFACTS) as directory:
            root=Path(directory)/'load-1';root.mkdir()
            with patch.dict(os.environ):
                result=stress.station((str(root),0,1,1024))
            self.assertTrue(result['ok'],result['unexpected'])
            operations=stress.summarize(result['samples'])
            for name in ('terminal_open','terminal_input','terminal_resize','terminal_close','offline_cancel',
                         'fixed_command','command_dedup','patch_atomic_backup','patch_dedup','expiry_rejection',
                         'upload_start','upload_chunk','upload_finish','upload_retry_dedup',
                         'download_prepare','download_chunk','directory_archive_prepare'):
                self.assertGreater(operations[name]['count'],0)
                self.assertEqual(operations[name]['errors'],0)
            self.assertEqual(result['counters']['sha_checks'],3)
            self.assertEqual(result['counters']['crossstation_rejections'],1)


if __name__=='__main__':unittest.main()
