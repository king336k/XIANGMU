"""Safe transport/deadline metadata never contains exception messages or provider data."""
import importlib.util
import json
import unittest
from pathlib import Path

from openai._base_client import httpx2
from pydantic_ai.exceptions import (
    ModelConnectionError,
    ModelRequestTimeout,
    ModelTimeoutError,
)

spec = importlib.util.spec_from_file_location('timeout_runner', Path(__file__).with_name('runner.py'))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
PRIVATE = 'PRIVATE_TOKEN_URL_BODY_DO_NOT_PERSIST'


class TimeoutMetadataTests(unittest.TestCase):
    def test_typed_phases_survive_wrappers_without_body(self):
        for phase in ['connect', 'read', 'write', 'pool', None]:
            with self.subTest(phase=phase):
                cause = ModelTimeoutError(model_name=PRIVATE, message=PRIVATE, phase=phase, body=PRIVATE)
                error = RuntimeError(PRIVATE)
                error.__cause__ = cause
                info = runner.safe_failure(error)
                self.assertEqual(info['model_failure'], {'source': 'agent_transport',
                    'transport_phase': phase or 'unknown', 'deadline_kind': 'unknown'})
                self.assertNotIn(PRIVATE, json.dumps(info))

    def test_actual_transport_cause_can_refine_unknown_typed_phase(self):
        for phase, kind in [('connect', httpx2.ConnectTimeout), ('read', httpx2.ReadTimeout),
                            ('write', httpx2.WriteTimeout), ('pool', httpx2.PoolTimeout)]:
            with self.subTest(phase=phase):
                error = ModelTimeoutError(model_name=PRIVATE, message=PRIVATE)
                error.__cause__ = kind(PRIVATE)
                self.assertEqual(runner.safe_failure(error)['model_failure']['transport_phase'], phase)

    def test_request_deadlines_are_distinct_from_transport(self):
        for setting in ['request_timeout', 'first_event_timeout']:
            error = ModelRequestTimeout(model_name=PRIVATE, timeout=30, setting=setting)
            self.assertEqual(runner.safe_failure(error)['model_failure'], {
                'source': 'agent_deadline', 'transport_phase': 'unknown', 'deadline_kind': setting})

    def test_bare_timeout_does_not_guess_network_phase(self):
        info = runner.safe_failure(TimeoutError('connect read ' + PRIVATE))
        self.assertEqual(info['model_failure'], {'source': 'agent_deadline',
                         'transport_phase': 'unknown', 'deadline_kind': 'agent_run'})
        self.assertNotIn(PRIVATE, json.dumps(info))

    def test_explicit_request_deadline_is_not_relabelled_by_inner_transport_timeout(self):
        error = ModelRequestTimeout(model_name=PRIVATE, timeout=30, setting='request_timeout')
        error.__cause__ = httpx2.ReadTimeout(PRIVATE)
        wrapped = RuntimeError(PRIVATE)
        wrapped.__cause__ = error
        self.assertEqual(runner.safe_failure(wrapped)['model_failure'], {
            'source': 'agent_deadline', 'transport_phase': 'unknown', 'deadline_kind': 'request_timeout'})

    def test_unknown_phase_and_cycle_do_not_leak_or_loop(self):
        error = ModelConnectionError(model_name=PRIVATE, message=PRIVATE)
        error.phase = PRIVATE
        error.__cause__ = error
        info = runner.safe_failure(error)
        self.assertEqual(len(info['error_chain']), 1)
        self.assertEqual(info['model_failure']['transport_phase'], 'unknown')
        self.assertNotIn(PRIVATE, json.dumps(info))

    def test_non_timeout_schema_error_does_not_claim_provider_call(self):
        self.assertNotIn('model_failure', runner.safe_failure(ValueError(PRIVATE)))


if __name__ == '__main__':
    unittest.main()
