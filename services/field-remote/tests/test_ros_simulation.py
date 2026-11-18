import importlib.util
import json
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'ros_simulation.py'
spec = importlib.util.spec_from_file_location('ros_simulation', SCRIPT)
ros_simulation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ros_simulation)

ARTIFACTS = Path('/home/engram/Documents/tmp/artifacts/field-remote-tests-20261118')
ARTIFACTS.mkdir(parents=True, exist_ok=True)


class RosSimulationTests(unittest.TestCase):
    def test_rejects_wrong_domain_and_topics_are_isolated(self):
        with patch.dict(os.environ, {'ROS_DOMAIN_ID': '0'}):
            with self.assertRaisesRegex(ValueError, '173'):
                ros_simulation.configure_environment()
        with patch.dict(os.environ, {'ROS_DOMAIN_ID': '173'}):
            ros_simulation.configure_environment()
        self.assertEqual(ros_simulation.COMMAND_TOPIC, '/remote_diagnostic_sim/command')
        self.assertEqual(ros_simulation.TELEMETRY_TOPIC, '/remote_diagnostic_sim/telemetry')

    def test_command_must_be_simulated_bounded_and_finite(self):
        valid = {'simulation': True, 'sequence': 123, 'joint_targets': [0.02] * 6}
        self.assertEqual(ros_simulation.validate_command(json.dumps(valid)), valid)
        for change in ({'simulation': False}, {'sequence': -1}, {'sequence': True},
                       {'joint_targets': [99] * 6}, {'joint_targets': [math.nan] * 6},
                       {'joint_targets': [0] * 5}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                ros_simulation.validate_command(json.dumps({**valid, **change}))

    def test_hot_config_and_hardware_refusal(self):
        with tempfile.TemporaryDirectory(dir=ARTIFACTS) as folder:
            config = Path(folder) / 'robot-config.json'
            state = {'telemetry_enabled': False, 'accept_commands': True, 'hardware_required': False}
            config.write_text(json.dumps(state))
            self.assertFalse(ros_simulation.load_config(config)['telemetry_enabled'])
            state['telemetry_enabled'] = True
            config.write_text(json.dumps(state))
            self.assertTrue(ros_simulation.load_config(config)['telemetry_enabled'])
            state['hardware_required'] = True
            config.write_text(json.dumps(state))
            self.assertTrue(ros_simulation.load_config(config)['hardware_required'])

    def test_evidence_requires_matching_sequence_and_targets(self):
        command = {'simulation': True, 'sequence': 123, 'joint_targets': [0.02] * 6}
        telemetry = {'simulation': True, 'sequence': 123, 'joint_positions': [0.02] * 6,
                     'robot_hostname': 'robot177', 'transport': 'native_ros2'}
        self.assertTrue(ros_simulation.matches(command, telemetry))
        for change in ({'sequence': 124}, {'simulation': False}, {'joint_positions': [0] * 6},
                       {'transport': 'http'}):
            self.assertFalse(ros_simulation.matches(command, {**telemetry, **change}))

    def test_append_evidence_stays_jsonl_and_refuses_symlink(self):
        with tempfile.TemporaryDirectory(dir=ARTIFACTS) as folder:
            output = Path(folder) / 'native.jsonl'
            ros_simulation.append_record(output, {'sequence': 1, 'native_daq_verified': False})
            self.assertEqual(json.loads(output.read_text())['sequence'], 1)
            symlink = Path(folder) / 'link.jsonl'
            symlink.symlink_to(output)
            with self.assertRaises(OSError):
                ros_simulation.append_record(symlink, {'sequence': 2})


if __name__ == '__main__':
    unittest.main()
