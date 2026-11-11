"""Launch only a disposable branch-built authority; credentials stay in process memory."""
import json
from pathlib import Path
import subprocess
import sys

NAME = "project-bridge-verification-20261109"
root = Path(sys.argv[1])
source = json.loads(subprocess.check_output(["docker", "inspect", "account-interop-20261107-iam-service-1"]))[0]
env = dict(row.split("=", 1) for row in source["Config"]["Env"])
env.update({"ISSUE_BRIDGE_KEY_ID": "latest-native-20261109", "ISSUE_BRIDGE_AUDIENCE": "project-management",
            "SPRING_SERVLET_MULTIPART_MAX_FILE_SIZE": "6MB",
            "SPRING_SERVLET_MULTIPART_MAX_REQUEST_SIZE": "6MB",
            "SPRING_SERVLET_MULTIPART_FILE_SIZE_THRESHOLD": "0"})
existing = subprocess.run(["docker", "inspect", NAME], capture_output=True)
if existing.returncode == 0:
    current = json.loads(existing.stdout)[0]
    current_env = dict(row.split("=", 1) for row in current["Config"]["Env"])
    # Keep DAQ signing state and every existing validation setting during a reload.
    current_env.update({key: env[key] for key in ["SPRING_SERVLET_MULTIPART_MAX_FILE_SIZE",
                       "SPRING_SERVLET_MULTIPART_MAX_REQUEST_SIZE", "SPRING_SERVLET_MULTIPART_FILE_SIZE_THRESHOLD"]})
    env = current_env
    subprocess.run(["docker", "rm", "-f", NAME], check=True, capture_output=True)
network = next(key for key in source["NetworkSettings"]["Networks"] if "account-test" in key)
args = ["docker", "create", "--name", NAME, "--network", network, "--restart", "unless-stopped",
        "--memory", "768m", "--cpus", "1.5", "-p", "127.0.0.1:16335:6324", "-v",
        str(root / "DataPlatformServer/build/libs/data_platform-0.0.1-SNAPSHOT.jar") + ":/acceptance/app.jar:ro",
        "--entrypoint", "java"]
for key, value in env.items():
    args += ["-e", key + "=" + value]
args += [source["Config"]["Image"], "-jar", "/acceptance/app.jar"]
for command in [args, ["docker", "network", "connect", "plane-local-20261106_default", NAME], ["docker", "start", NAME]]:
    result = subprocess.run(command, capture_output=True)
    if result.returncode:
        raise SystemExit("Isolated authority launch failed")
item = json.loads(subprocess.check_output(["docker", "inspect", NAME]))[0]
print(json.dumps({"container": NAME, "plane_ip": item["NetworkSettings"]["Networks"]["plane-local-20261106_default"]["IPAddress"],
                  "host_url": "http://127.0.0.1:16335"}))
