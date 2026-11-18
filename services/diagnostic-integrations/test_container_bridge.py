import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location('bridge', Path(__file__).with_name('container_bridge.py'))
bridge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bridge)


class BridgeTest(unittest.TestCase):
    def test_only_fixed_readonly_commands(self):
        argv = bridge.command({'containers': {'rai': 'fixed-rai'}}, 'rai', 'inspect')
        self.assertEqual(argv, ['/usr/bin/docker', 'exec', 'fixed-rai', '/ros_entrypoint.sh',
            '/opt/diagnostic-integrations/rai/bin/python', '/opt/diagnostic-integrations/specialist.py', 'rai', 'inspect'])
        for role, action in [('rai', 'repair'), ('shell', 'inspect'), ('rosa', 'publish')]:
            with self.assertRaises(ValueError):
                bridge.command({'containers': {'rai': 'fixed-rai'}}, role, action)

    def test_unsafe_container_is_rejected(self):
        with self.assertRaises(ValueError):
            bridge.command({'containers': {'rai': 'container; malicious'}}, 'rai', 'health')


if __name__ == '__main__':
    unittest.main()
