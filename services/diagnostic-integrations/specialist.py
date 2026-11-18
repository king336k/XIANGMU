# SPDX-License-Identifier: AGPL-3.0-only
"""Fixed read-only specialist bridge. Run in each framework's isolated environment."""
import contextlib
import importlib
import importlib.metadata
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import time


def health(name):
    modules = {"rosa": "rosa.tools.ros2", "rai": "rai.tools.ros.native", "holmes": "holmes", "langgraph": "langgraph.graph"}
    result = {"integration": name, "ready": False, "python": platform.python_version(),
              "ros_distro": os.environ.get("ROS_DISTRO", ""), "scope": "local_process_environment"}
    if name == "rai" and os.environ.get("ROS_DISTRO") not in {"humble", "jazzy"}:
        return {**result, "reason": "source_supported_ros_runtime_rai110_humble_or_jazzy"}
    try:
        importlib.import_module(modules[name])
        if name in {"rosa", "rai"}:
            importlib.import_module("rclpy")
            if not shutil.which("ros2"):
                return {**result, "reason": "ros2_runtime_not_sourced"}
        return {**result, "ready": True, "reason": "imports_and_runtime_prerequisites_present_not_robot_acceptance"}
    except Exception:
        return {**result, "reason": "dependency_or_runtime_unavailable"}


def inspect(name):
    status = health(name)
    if not status["ready"]:
        return status
    if name == "rosa":
        # Actual ROSA LangChain tools, not a reimplementation of their ROS commands.
        tools = importlib.import_module("rosa.tools.ros2")
        return {**status, "observations": {
            "nodes": tools.ros2_node_list.invoke({}),
            "topics": tools.ros2_topic_list.invoke({}),
            "services": tools.ros2_service_list.invoke({}),
        }}
    if name == "rai":
        # Official 1.1.0 API supports ROS Humble and Python 3.10.
        import rclpy
        from rai.tools.ros.native import Ros2GetTopicsNamesAndTypesTool
        rclpy.init()
        node = rclpy.create_node("remote_diagnostic_rai_readonly")
        try:
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                rclpy.spin_once(node, timeout_sec=0.1)
            observations = Ros2GetTopicsNamesAndTypesTool(node=node).invoke({})
            return {**status, "observations": observations, "source_version": "official_1.1.0_api"}
        finally:
            node.destroy_node()
            rclpy.shutdown()
    if name == "holmes":
        # Same fixed, read-only data source consumed by holmes-toolsets.yaml.
        result = subprocess.run(["systemctl", "--failed", "--no-pager", "--plain"],
                                capture_output=True, text=True, timeout=15, check=False)
        return {**status, "observations": {"loadavg": os.getloadavg(),
                "disk_free_bytes": shutil.disk_usage("/").free,
                "failed_services": result.stdout[:20000], "exit_code": result.returncode}}
    return status


def main():
    try:
        name, operation = sys.argv[1:]
        if name not in {"rosa", "rai", "holmes", "langgraph"} or operation not in {"health", "inspect"}:
            raise ValueError()
        # Some third-party imports write banners; the bridge always emits exactly one JSON object.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = health(name) if operation == "health" else inspect(name)
    except Exception:
        result = {"ready": False, "reason": "specialist_execution_failed"}
    print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
