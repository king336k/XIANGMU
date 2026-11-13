"""Failure metadata retains bounded transport classes without payloads or secrets."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('safe_failure_runner', Path(__file__).with_name('runner.py'))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class SafeFailureTests(unittest.TestCase):
    def test_bounded_class_chain_and_status_without_messages(self):
        low = ConnectionError('sensitive transport message')
        high = RuntimeError('sensitive provider body')
        high.__cause__ = low
        info = runner.safe_failure(high)
        self.assertEqual(info['error_type'], 'RuntimeError')
        self.assertEqual([x['error_type'] for x in info['error_chain']], ['RuntimeError', 'ConnectionError'])
        self.assertNotIn('sensitive', str(info))

    def test_cycle_and_long_chain_are_bounded(self):
        error = RuntimeError('private')
        error.__cause__ = error
        self.assertEqual(len(runner.safe_failure(error)['error_chain']), 1)
        for _ in range(30):
            next_error = RuntimeError('private')
            next_error.__cause__ = error
            error = next_error
        self.assertEqual(len(runner.safe_failure(error)['error_chain']), 8)
