"""Local client for the ephemeral, user-authorized SSH broker; never handles credentials."""

import argparse
import json
import socket
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("script", type=Path)
parser.add_argument("output", type=Path)
parser.add_argument("--helpers", type=Path)
parser.add_argument(
    "--socket",
    default="/home/engram/Documents/tmp/artifacts/knowledge-migration-2026-11-09/readonly-reader.sock",
)
args = parser.parse_args()
code = args.script.read_text()
if args.helpers:
    helper = args.helpers.read_text().split("def build_plan")[0]
    code = (
        "import types, sys\n"
        "helpers=types.ModuleType('hub_migration_helpers')\n"
        "sys.modules[helpers.__name__]=helpers\n"
        + "exec("
        + repr(helper)
        + ", helpers.__dict__)\n"
        + code
    )
with socket.socket(socket.AF_UNIX) as connection:
    connection.connect(args.socket)
    connection.sendall(
        json.dumps(
            {"command": "python3 - <<'HUB_READONLY'\n" + code + "\nHUB_READONLY"}
        ).encode()
        + b"\n"
    )
    connection.shutdown(socket.SHUT_WR)
    parts = []
    while chunk := connection.recv(1024 * 1024):
        parts.append(chunk)
result = json.loads(b"".join(parts))
if result["exit_code"]:
    raise SystemExit("Remote read failed; no export written")
value = json.loads(result["stdout"])
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(value, ensure_ascii=False, indent=2))
args.output.chmod(0o600)
print(json.dumps({"output": str(args.output), "bytes": args.output.stat().st_size}))
