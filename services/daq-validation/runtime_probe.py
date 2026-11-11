"""Run real DAQ modules in an isolated deployment runtime, with controlled faults."""
import hashlib
import json
import os
from pathlib import Path
import socket
import time
import traceback
import zipfile

root = Path("/verification")
logs, records = root / "logs", root / "records"
logs.mkdir(exist_ok=True, parents=True)
records.mkdir(exist_ok=True, parents=True)
os.environ["ENGRAM_DAQ_LOG_DIR"] = str(logs)
from backend.utils.logger import get_logger
from backend.services.diagnostic_bundle_service import DiagnosticBundleService
from backend.utils.runtime_preflight import validate_ros1_config

logger = get_logger("deployment_validation")
port_socket = socket.socket()
port_socket.bind(("127.0.0.1", 0))
unused_port = port_socket.getsockname()[1]
port_socket.close()
failures = []
try:
    with socket.create_connection(("127.0.0.1", unused_port), timeout=1):
        pass
except OSError as error:
    logger.exception("Controlled camera service connection failed: host=127.0.0.1 port=%s", unused_port)
    failures.append({"fault": "local_endpoint_not_listening", "error_type": type(error).__name__,
                     "expected_cause": "隔离环境目标端口未监听，不是机器人硬件故障"})
try:
    validate_ros1_config({})
except Exception as error:
    logger.exception("Controlled ROS configuration validation failed")
    failures.append({"fault": "ros_configuration_missing", "error_type": type(error).__name__,
                     "expected_cause": "隔离配置缺少ROS1必要项"})

session = records / "DAQ-DEPLOYMENT-FAULT"
session.mkdir(exist_ok=True)
(session / "recording.log").write_text(
    "Controlled deployment validation; no physical robot connected.\n"
    + "Recording stopped after connection failure; review DAQ system logs.\n"
)
(root / "version_info.yaml").write_text("version: daq-bridge-f4f621c\nvalidation: isolated\n")
# Ensure a regular diagnostic source exists even when the logger's sink is a container directory.

service = DiagnosticBundleService(
    logs_root=logs, records_root=records, version_info_paths=[root / "version_info.yaml"],
    runtime_summary={"validation": "real-daq-runtime-controlled-faults", "robot_connected": False},
    max_uncompressed_bytes=2 * 1024 * 1024, max_archive_bytes=2 * 1024 * 1024,
)
bundle = service.build(hours=24, include_latest_recording_log=True)
raw = bundle.archive_path.read_bytes()
(root / "real-daq-diagnostics.zip").write_bytes(raw)
with zipfile.ZipFile(bundle.archive_path) as archive:
    names = archive.namelist()
    samples = [archive.read(n).decode(errors="replace") for n in names if n.endswith((".log", ".json", ".txt"))]
proof = {"runtime": "engram-daq-backend:latest", "daq_commit": "f4f621caf4642c4aee60fdacbaea990b51b3c090",
         "original_modules": ["DiagnosticBundleService", "validate_ros1_config", "get_logger"],
         "controlled_faults": failures, "zip_sha256": hashlib.sha256(raw).hexdigest(),
         "zip_bytes": len(raw), "entries": names, "contains_failure_material": any("local_endpoint_not_listening" in x for x in samples),
         "physical_robot_used": False}
(root / "daq-runtime-proof.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2))
bundle.cleanup()
print(json.dumps(proof,ensure_ascii=False))
