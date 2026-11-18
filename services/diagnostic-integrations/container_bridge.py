# SPDX-License-Identifier: AGPL-3.0-only
"""Fixed specialist entrypoint for a preconfigured local or pinned SSH container."""
import ipaddress
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys


def command(config, role, operation):
    if role not in {"rosa", "rai"} or operation not in {"health", "inspect"}:
        raise ValueError("unsupported_specialist_operation")
    container = config["containers"][role]
    if not isinstance(container, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", container):
        raise ValueError("invalid_fixed_container")
    argv = ["/usr/bin/docker", "exec", container, "/ros_entrypoint.sh",
            "/opt/diagnostic-integrations/" + role + "/bin/python",
            "/opt/diagnostic-integrations/specialist.py", role, operation]
    peer = config.get("ssh")
    if peer:
        address = ipaddress.ip_address(peer["host"])
        if not address.is_private or address.is_unspecified or address.is_multicast:
            raise ValueError("private_fixed_peer_required")
        if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", peer["username"]):
            raise ValueError("invalid_peer_username")
        for name in ("identity", "known_hosts"):
            path = Path(peer[name])
            if not path.is_absolute() or not path.is_file() or path.is_symlink():
                raise ValueError("pinned_peer_files_required")
        argv = ["/usr/bin/ssh", "-T", "-i", peer["identity"], "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
                "-o", "PasswordAuthentication=no", "-o", "StrictHostKeyChecking=yes", "-o",
                "UserKnownHostsFile=" + peer["known_hosts"], "-o", "ConnectTimeout=5",
                peer["username"] + "@" + peer["host"], shlex.join(argv)]
    return argv


def main():
    try:
        role, operation = sys.argv[1:]
        path = Path(__file__).resolve().with_name("container-bridge.json")
        if path.is_symlink() or path.stat().st_mode & 0o022:
            raise ValueError("admin_only_bridge_config_required")
        config = json.loads(path.read_text())
        process = subprocess.run(command(config, role, operation), capture_output=True, text=True, timeout=29, check=False,
                                 env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"})
        result = json.loads(process.stdout)
        if process.returncode or not isinstance(result, dict) or result.get("integration") != role:
            raise ValueError("specialist_bridge_failed")
    except Exception:
        result = {"ready": False, "reason": "fixed_container_specialist_unavailable"}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
