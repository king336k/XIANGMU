#!/usr/bin/env python3
"""Native ROS 2 simulation on domain 173 and fixed isolated topics only."""

import argparse
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import socket
import stat
import time

DOMAIN = '173'
COMMAND_TOPIC = '/remote_diagnostic_sim/command'
TELEMETRY_TOPIC = '/remote_diagnostic_sim/telemetry'
STATUS_TOPIC = '/remote_diagnostic_sim/status'
FLAGS = ('telemetry_enabled', 'accept_commands', 'hardware_required')
TARGETS = [0.02, -0.02, 0.01, -0.01, 0.0, 0.0]


def configure_environment():
    if os.environ.get('ROS_DOMAIN_ID', DOMAIN) != DOMAIN:
        raise ValueError('isolated simulation requires ROS_DOMAIN_ID=173')
    os.environ['ROS_DOMAIN_ID'] = DOMAIN
    os.environ.setdefault('RMW_IMPLEMENTATION', 'rmw_cyclonedds_cpp')
    if os.environ.get('ROS_LOCALHOST_ONLY', '0') != '0':
        raise ValueError('cross-host simulation requires ROS_LOCALHOST_ONLY=0')


def load_config(path):
    path = Path(path)
    if path.is_dir():
        path = path / 'robot-config.json'
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 8192:
            raise ValueError('isolated configuration must be a bounded regular file')
        config = json.loads(stream.read(8193))
    if set(config) != set(FLAGS) or any(type(config[key]) is not bool for key in FLAGS):
        raise ValueError('robot configuration requires exactly three boolean simulation flags')
    return config


def validate_command(raw):
    if not isinstance(raw, str) or len(raw.encode()) > 4096:
        raise ValueError('bounded simulation command required')
    command = json.loads(raw)
    if (not isinstance(command, dict) or command.get('simulation') is not True
            or type(command.get('sequence')) is not int or command['sequence'] < 1
            or not isinstance(command.get('joint_targets'), list) or len(command['joint_targets']) != 6
            or any(type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 0.025
                   for value in command['joint_targets'])):
        raise ValueError('only six finite simulated joint targets within +/-0.025 are permitted')
    return command


def matches(command, telemetry):
    return (isinstance(telemetry, dict) and telemetry.get('simulation') is True
            and telemetry.get('transport') == 'native_ros2'
            and telemetry.get('sequence') == command['sequence']
            and telemetry.get('joint_positions') == command['joint_targets']
            and isinstance(telemetry.get('robot_hostname'), str) and bool(telemetry['robot_hostname']))


def append_record(output, record):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(output, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 10 * 1024 * 1024:
            raise ValueError('evidence file must be a bounded regular file')
        raw = (json.dumps(record, ensure_ascii=False, separators=(',', ':')) + '\n').encode()
        written = os.write(fd, raw)
        if written != len(raw):
            raise OSError('incomplete evidence record write')
        os.fsync(fd)
    finally:
        os.close(fd)


def capabilities():
    result = {'simulation': True, 'domain': DOMAIN, 'transport': 'native_ros2',
              'hostname': socket.gethostname(), 'native_daq_verified': False,
              'rmw_implementation': os.environ.get('RMW_IMPLEMENTATION')}
    for name in ('rclpy', 'std_msgs.msg', 'rosbag2_py'):
        try:
            module = importlib.import_module(name)
            result[name] = {'available': True}
            if name == 'rosbag2_py':
                probe = getattr(module, 'get_registered_writers', None)
                result['rosbag2_storage_plugins'] = sorted(probe()) if probe else None
        except ImportError:
            result[name] = {'available': False}
    return result


class BagRecorder:
    def __init__(self, destination, requested_storage):
        import rosbag2_py
        from rclpy.serialization import serialize_message
        self.serialize = serialize_message
        path = Path(destination)
        if path.exists():
            raise ValueError('bag destination must be new; never overwrite previous evidence')
        probe = getattr(rosbag2_py, 'get_registered_writers', None)
        plugins = set(probe()) if probe else set()
        storage = requested_storage
        if storage == 'auto':
            storage = 'mcap' if 'mcap' in plugins else 'sqlite3'
        self.storage = storage
        self.path = path
        self.writer = rosbag2_py.SequentialWriter()
        self.writer.open(rosbag2_py.StorageOptions(uri=str(path), storage_id=storage),
                         rosbag2_py.ConverterOptions(input_serialization_format='cdr',
                                                     output_serialization_format='cdr'))
        for topic in (COMMAND_TOPIC, TELEMETRY_TOPIC):
            self.writer.create_topic(rosbag2_py.TopicMetadata(name=topic, type='std_msgs/msg/String',
                                                             serialization_format='cdr'))

    def write(self, topic, message):
        self.writer.write(topic, self.serialize(message), time.time_ns())

    def close(self):
        if self.writer is not None:
            close = getattr(self.writer, 'close', None)
            if close:
                close()
            self.writer = None

    def evidence(self):
        files = []
        for file in sorted(self.path.rglob('*')):
            if file.is_file() and not file.is_symlink():
                files.append({'path': str(file.resolve()), 'bytes': file.stat().st_size,
                              'sha256': hashlib.sha256(file.read_bytes()).hexdigest()})
        return {'storage': self.storage, 'path': str(self.path.resolve()), 'files': files}


def robot(args):
    import rclpy
    from std_msgs.msg import String
    configure_environment()
    load_config(args.config)
    rclpy.init(args=[])
    node = rclpy.create_node('field_remote_isolated_robot')
    telemetry = node.create_publisher(String, TELEMETRY_TOPIC, 10)
    status = node.create_publisher(String, STATUS_TOPIC, 10)
    latest_sequence = 0

    def state():
        try:
            return load_config(args.config)
        except (ValueError, OSError):
            return {'telemetry_enabled': False, 'accept_commands': False, 'hardware_required': True}

    def receive(message):
        nonlocal latest_sequence
        try:
            command = validate_command(message.data)
        except (ValueError, TypeError):
            return
        config = state()
        if not config['accept_commands'] or config['hardware_required'] or command['sequence'] < latest_sequence:
            return
        latest_sequence = command['sequence']
        if not config['telemetry_enabled']:
            return
        response = String()
        response.data = json.dumps({'simulation': True, 'transport': 'native_ros2', 'domain': DOMAIN,
                                    'sequence': command['sequence'], 'joint_positions': command['joint_targets'],
                                    'robot_hostname': socket.gethostname(), 'robot_received_at_ns': time.time_ns(),
                                    'config': config})
        telemetry.publish(response)

    def publish_status():
        response = String()
        response.data = json.dumps({'simulation': True, 'transport': 'native_ros2', 'domain': DOMAIN,
                                    'robot_hostname': socket.gethostname(), 'config': state(),
                                    'last_sequence': latest_sequence})
        status.publish(response)

    subscription = node.create_subscription(String, COMMAND_TOPIC, receive, 10)
    timer = node.create_timer(0.5, publish_status)
    print(json.dumps({'simulation': True, 'role': 'robot', 'ready': True, 'domain': DOMAIN,
                      'robot_hostname': socket.gethostname(), 'topics': [COMMAND_TOPIC, TELEMETRY_TOPIC, STATUS_TOPIC]}), flush=True)
    deadline = time.monotonic() + args.duration
    try:
        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
    finally:
        node.destroy_timer(timer)
        node.destroy_subscription(subscription)
        node.destroy_node()
        rclpy.shutdown()
    return 0


def collect(args):
    import rclpy
    from std_msgs.msg import String
    configure_environment()
    if not args.output:
        raise ValueError('collect requires --output JSONL evidence path')
    rclpy.init(args=[])
    node = rclpy.create_node('field_remote_isolated_collector')
    command = {'simulation': True, 'sequence': time.time_ns(), 'joint_targets': TARGETS}
    publisher = node.create_publisher(String, COMMAND_TOPIC, 10)
    received, statuses = [], []
    bag = None
    started = time.time_ns()
    record = {'simulation': True, 'transport': 'native_ros2', 'domain': DOMAIN,
              'native_daq_verified': False, 'collector_hostname': socket.gethostname(),
              'command': command, 'started_at_ns': started,
              'command_topic': COMMAND_TOPIC, 'telemetry_topic': TELEMETRY_TOPIC}

    def receive(message):
        try:
            response = json.loads(message.data)
        except (ValueError, TypeError):
            return
        if matches(command, response) and not received:
            received.append(response)
            if bag:
                bag.write(TELEMETRY_TOPIC, message)

    def status(message):
        try:
            response = json.loads(message.data)
            if response.get('simulation') is True and len(statuses) < 4:
                statuses.append(response)
        except (ValueError, TypeError, AttributeError):
            pass

    subscription = node.create_subscription(String, TELEMETRY_TOPIC, receive, 10)
    status_subscription = node.create_subscription(String, STATUS_TOPIC, status, 10)
    try:
        if args.bag:
            bag = BagRecorder(args.bag, args.bag_storage)
        deadline = time.monotonic() + args.duration
        last_publish = 0.0
        while rclpy.ok() and time.monotonic() < deadline and not received:
            # Discovery must complete before publish; retry the same sequence so
            # a repaired hot configuration can recover without a new session.
            if publisher.get_subscription_count() and time.monotonic() - last_publish >= 0.5:
                outgoing = String()
                outgoing.data = json.dumps(command)
                if bag:
                    bag.write(COMMAND_TOPIC, outgoing)
                publisher.publish(outgoing)
                last_publish = time.monotonic()
            rclpy.spin_once(node, timeout_sec=0.1)
        record.update(verified=bool(received), completed_at_ns=time.time_ns(), status_samples=statuses)
        if received:
            record['telemetry'] = received[0]
        else:
            record['error'] = 'no_matching_native_ros2_telemetry_before_deadline'
            record['requires_onsite'] = any(item.get('config', {}).get('hardware_required') for item in statuses)
    finally:
        if bag:
            bag.close()
            record['rosbag2'] = bag.evidence()
        node.destroy_subscription(subscription)
        node.destroy_subscription(status_subscription)
        node.destroy_node()
        rclpy.shutdown()
    append_record(args.output, record)
    summary = {key: record[key] for key in ('simulation', 'transport', 'domain', 'verified',
                                            'native_daq_verified', 'collector_hostname')}
    summary.update(sequence=command['sequence'], output=str(Path(args.output).resolve()))
    if bag:
        summary['rosbag2'] = record['rosbag2']
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 0 if received else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('role', choices=('robot', 'collect', 'probe'))
    parser.add_argument('--config', help='isolated robot-config.json or directory (robot role)')
    parser.add_argument('--duration', type=float, default=8)
    parser.add_argument('--output', help='collector JSONL evidence file')
    parser.add_argument('--bag', help='new rosbag2 directory; writes actual serialized ROS messages')
    parser.add_argument('--bag-storage', choices=('auto', 'mcap', 'sqlite3'), default='auto')
    args = parser.parse_args()
    try:
        configure_environment()
        if not math.isfinite(args.duration) or not 0 < args.duration <= 3600:
            raise ValueError('duration must be between 0 and 3600 seconds')
        if args.role == 'probe':
            print(json.dumps(capabilities(), ensure_ascii=False))
            return
        if args.role == 'robot' and not args.config:
            raise ValueError('robot role requires an explicit isolated --config')
        raise SystemExit(robot(args) if args.role == 'robot' else collect(args))
    except (ImportError, ValueError, OSError, RuntimeError) as exc:
        print(json.dumps({'simulation': True, 'transport': 'native_ros2', 'verified': False,
                          'native_daq_verified': False, 'error': type(exc).__name__, 'detail': str(exc)[:300]}), flush=True)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
