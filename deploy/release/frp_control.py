"""A deployment owns one optional FRP proxy; credentials exist only in a runtime tmpfs."""

import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import time
import sys
import secrets
from urllib.request import urlopen

LABELS = {
    "io.engram.project": "engram_project",
    "io.engram.component": "frp",
    "io.engram.frp-schema": "1",
}


def safe_path(value):
    path = Path(value)
    if (
        any(ord(char) < 32 or char == "," for char in str(path))
        or not path.is_absolute()
        or ".." in path.parts
        or any(part.is_symlink() for part in [path, *path.parents])
    ):
        raise ValueError("absolute non-symlink path required")
    return path


def port(value):
    if type(value) is not int or not 1 <= value <= 65535:
        raise ValueError("invalid TCP port")
    return value


def identity(root):
    root = safe_path(root)
    suffix = hashlib.sha256(str(root).encode()).hexdigest()[:12]
    return "engramproject-frp-" + suffix, {**LABELS, "io.engram.deploy-root": str(root)}


def proxy_config(source, name, local_port, remote_port, admin_port=None):
    if (
        source.get("serverAddr") != "180.153.172.19"
        or source.get("serverPort", 7000) != 7000
    ):
        raise ValueError("FRP source server does not match the authorized server")
    config = {
        key: source[key]
        for key in ["serverAddr", "serverPort", "auth", "transport"]
        if key in source
    }
    config.update(
        loginFailExit=True,
        log={"to": "/dev/null"},
        proxies=[
            {
                "name": name,
                "type": "tcp",
                "localIP": "127.0.0.1",
                "localPort": port(local_port),
                "remotePort": port(remote_port),
            }
        ],
    )
    if admin_port:
        config["webServer"] = {"addr": "127.0.0.1", "port": port(admin_port)}
    return config


CHILD = """import json,os,tomllib
try:
 source=tomllib.load(open('/run/source/frpc.toml','rb'))
 if source.get('serverAddr')!='180.153.172.19' or source.get('serverPort',7000)!=7000: raise ValueError()
 config={k:source[k] for k in ['serverAddr','serverPort','auth','transport'] if k in source}
 config.update(loginFailExit=True,log={'to':'/dev/null'},webServer={'addr':'127.0.0.1','port':int(os.environ['FRP_STATUS_PORT'])},proxies=[{'name':os.environ['FRP_PROXY_NAME'],'type':'tcp','localIP':'127.0.0.1','localPort':int(os.environ['FRP_LOCAL_PORT']),'remotePort':int(os.environ['FRP_REMOTE_PORT'])}])
 os.umask(0o077)
 with open('/run/frp/frpc.json','w') as target: json.dump(config,target)
 os.execv('/run/bin/frpc',['frpc','-c','/run/frp/frpc.json'])
except Exception:
 print('Managed FRP startup refused; private configuration suppressed.',flush=True)
 raise SystemExit(1)
"""


def command(args, timeout=30):
    try:
        result = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except subprocess.SubprocessError:
        raise ValueError(
            "managed FRP command timed out; private command details suppressed"
        ) from None
    if result.returncode and not (
        args[:3] == ["systemctl", "--user", "show"]
        and b"LoadState=not-found" in result.stdout
    ):
        raise ValueError(
            "managed FRP Docker command failed; private diagnostics suppressed"
        )
    return result.stdout


def inspect_managed(root, run):
    name, labels = identity(root)
    ids = (
        run(["docker", "ps", "-aq", "--filter", "name=^/" + name + "$"])
        .decode()
        .split()
    )
    if not ids:
        return None
    if len(ids) != 1:
        raise ValueError("ambiguous managed FRP container")
    row = json.loads(run(["docker", "inspect", ids[0]]))[0]
    actual = row.get("Config", {}).get("Labels") or {}
    if any(actual.get(key) != value for key, value in labels.items()):
        raise ValueError("FRP container ownership mismatch")
    return row


def read_state(root):
    path = safe_path(Path(root) / "shared/frp-state.json")
    if not path.exists():
        return {"schema_version": 1, "deploy_root": str(root), "enabled": False}
    value = json.loads(path.read_text())
    if (
        value.get("schema_version") != 1
        or value.get("deploy_root") != str(root)
        or type(value.get("enabled")) is not bool
    ):
        raise ValueError("invalid managed FRP state")
    return value


def save_state(root, value):
    path = safe_path(Path(root) / "shared/frp-state.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = safe_path(path.with_name(".frp-state.json." + secrets.token_hex(6)))
    with os.fdopen(
        os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
    ) as output:
        json.dump(value, output)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


def running_status(state, run, fetch=None):
    row = inspect_managed(state["deploy_root"], run)
    if not row or not row.get("State", {}).get("Running"):
        return False
    fetch = fetch or (lambda url: json.load(urlopen(url, timeout=3)))
    try:
        result = fetch(
            "http://127.0.0.1:" + str(port(state["status_port"])) + "/api/status"
        )
        return any(
            item.get("name") == state["proxy_name"]
            and item.get("status") == "running"
            and str(item.get("remote_addr", "")).endswith(
                ":" + str(state["remote_port"])
            )
            for item in result.get("tcp", [])
        )
    except (OSError, ValueError, KeyError):
        return False


def systemd_unit(root, run):
    name = identity(root)[0] + ".service"
    raw = run(
        [
            "systemctl",
            "--user",
            "show",
            name,
            "--property=LoadState,ActiveState,Description,ExecStart",
        ]
    ).decode()
    values = dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)
    if values.get("LoadState") == "not-found":
        return name, None
    if values.get("Description") != "EngramProject managed FRP " + str(
        root
    ) or "frp_control.py" not in values.get("ExecStart", ""):
        raise ValueError("FRP user unit ownership mismatch")
    return name, values


def systemd_registered(state, run, fetch=None):
    _name, values = systemd_unit(Path(state["deploy_root"]), run)
    if not values or values.get("ActiveState") != "active":
        return False
    fetch = fetch or (lambda url: json.load(urlopen(url, timeout=3)))
    try:
        result = fetch(
            "http://127.0.0.1:" + str(port(state["status_port"])) + "/api/status"
        )
        return any(
            item.get("name") == state["proxy_name"]
            and item.get("status") == "running"
            and str(item.get("remote_addr", "")).endswith(
                ":" + str(state["remote_port"])
            )
            for item in result.get("tcp", [])
        )
    except (OSError, ValueError, KeyError):
        return False


def systemd_reconcile(
    root,
    local_port,
    action,
    state,
    run,
    source_config,
    fetch,
    attempts,
    python_executable,
):
    if action not in {None, "open", "close"}:
        raise ValueError("invalid FRP action")
    if action is None and not state["enabled"]:
        return state
    unit, existing = systemd_unit(root, run)
    if action != "close":
        container = inspect_managed(root, run)
        if container and (
            container.get("State", {}).get("Running")
            or container.get("HostConfig", {}).get("RestartPolicy", {}).get("Name")
            not in {"no", ""}
        ):
            raise ValueError(
                "managed Docker proxy must be stopped with restart disabled before process fallback"
            )
    if action == "close":
        if existing:
            run(["systemctl", "--user", "stop", unit])
            _unit, after = systemd_unit(root, run)
            if after and after.get("ActiveState") not in {"inactive", "failed"}:
                raise ValueError("managed FRP unit did not stop")
            if after and after.get("ActiveState") == "failed":
                run(["systemctl", "--user", "reset-failed", unit])
        runtime_config = safe_path(Path("/dev/shm") / identity(root)[0] / "frpc.json")
        if runtime_config.exists():
            if runtime_config.stat().st_uid != os.getuid():
                raise ValueError("FRP memory configuration ownership mismatch")
            runtime_config.unlink()
        state.update(enabled=False, backend="systemd-user")
        save_state(root, state)
        return state
    if (
        existing
        and state.get("local_port") == local_port
        and systemd_registered(state, run, fetch)
    ):
        state["enabled"] = True
        save_state(root, state)
        return state
    if existing and existing.get("ActiveState") not in {"inactive", "failed"}:
        raise ValueError(
            "managed FRP user unit must be closed before changing its endpoint"
        )
    if existing:
        run(["systemctl", "--user", "reset-failed", unit])
        _name, remaining = systemd_unit(root, run)
        if remaining:
            raise ValueError(
                "old managed unit has not unloaded yet; retry opening shortly"
            )
    source = safe_path(
        source_config or state.get("source_config", "/opt/frpc/frpc.toml")
    )
    binary = safe_path(root / "shared/frp/frpc")
    if (
        not source.is_file()
        or source.stat().st_mode & 0o022
        or not binary.is_file()
        or binary.stat().st_mode & 0o022
    ):
        raise ValueError("safe source TOML and managed static FRP binary required")
    interpreter = safe_path(
        Path(
            python_executable or state.get("python_executable") or sys.executable
        ).resolve()
    )
    if not interpreter.is_file():
        raise ValueError("Python 3.11 or later interpreter required")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        status_port = probe.getsockname()[1]
    name, _labels = identity(root)
    proposed = {
        "schema_version": 1,
        "deploy_root": str(root),
        "enabled": True,
        "backend": "systemd-user",
        "unit": unit,
        "server_addr": "180.153.172.19",
        "server_port": 7000,
        "remote_port": 18886,
        "local_port": local_port,
        "managed_container": name,
        "proxy_name": name.replace("engramproject-frp-", "engramproject-"),
        "source_config": str(source),
        "binary_path": str(binary),
        "status_port": status_port,
        "python_executable": str(interpreter),
    }
    # The process reads only this public metadata; the token never enters argv, env or a persistent file.
    save_state(root, {**proposed, "enabled": False})
    args = [
        "systemd-run",
        "--user",
        "--collect",
        "--unit=" + unit,
        "--description=EngramProject managed FRP " + str(root),
        "--property=Restart=on-failure",
        "--property=RestartSec=5",
        "--property=NoNewPrivileges=yes",
        "--property=StandardOutput=null",
        "--property=StandardError=null",
        str(interpreter),
        str(Path(__file__).absolute()),
        "--serve-root",
        str(root),
    ]
    try:
        run(args)
        for _ in range(attempts):
            if systemd_registered(proposed, run, fetch):
                save_state(root, proposed)
                return proposed
            time.sleep(0.5)
        raise ValueError("managed FRP user unit registration failed")
    except (ValueError, OSError, subprocess.SubprocessError):
        _unit, current = systemd_unit(root, run)
        if current:
            run(["systemctl", "--user", "stop", unit])
        save_state(root, {**proposed, "enabled": False})
        raise ValueError(
            "managed FRP user unit failed; only managed unit stopped"
        ) from None


def serve(root):
    import tomllib

    root = safe_path(root)
    state = read_state(root)
    if state.get("backend") != "systemd-user":
        raise ValueError("invalid managed FRP process backend")
    source = safe_path(state["source_config"])
    config = proxy_config(
        tomllib.loads(source.read_text()),
        state["proxy_name"],
        state["local_port"],
        state["remote_port"],
        state["status_port"],
    )
    runtime = safe_path(Path("/dev/shm") / identity(root)[0])
    runtime.mkdir(mode=0o700, exist_ok=True)
    if runtime.stat().st_uid != os.getuid() or runtime.stat().st_mode & 0o077:
        raise ValueError("unsafe FRP memory directory")
    path = safe_path(runtime / "frpc.json")
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(descriptor, "w") as output:
        json.dump(config, output)
    binary = safe_path(state["binary_path"])
    os.execv(str(binary), [str(binary), "-c", str(path)])


def reconcile(
    root,
    local_port,
    action=None,
    run=command,
    source_container="frpc",
    source_config=None,
    runtime_container=None,
    fetch=None,
    attempts=120,
    backend=None,
    python_executable=None,
):
    root = safe_path(root)
    port(local_port)
    state = read_state(root)
    selected_backend = state.get("backend", "docker")
    if state.get("enabled") and backend and backend != selected_backend:
        raise ValueError(
            "close the persisted managed FRP backend before switching backend"
        )
    if (
        action == "close"
        and backend
        and state.get("backend")
        and backend != selected_backend
    ):
        raise ValueError("close must use the persisted managed FRP backend")
    backend = backend or selected_backend
    if backend == "systemd-user":
        return systemd_reconcile(
            root,
            local_port,
            action,
            state,
            run,
            source_config,
            fetch,
            attempts,
            python_executable,
        )
    if backend != "docker":
        raise ValueError("unknown managed FRP backend")
    if action not in {None, "open", "close"}:
        raise ValueError("invalid FRP action")
    if action is None and not state["enabled"]:
        return state
    name, labels = identity(root)
    old = inspect_managed(root, run)
    if action == "close":
        if old:
            run(["docker", "update", "--restart", "no", old["Id"]])
            run(["docker", "stop", "--time", "10", old["Id"]])
            after = inspect_managed(root, run)
            if after and (
                after.get("State", {}).get("Running")
                or after.get("State", {}).get("Restarting")
            ):
                raise ValueError("managed FRP container did not stop")
        state.update(enabled=False)
        save_state(root, state)
        return state
    if action is None and state.get("local_port") == local_port:
        if not running_status(state, run, fetch):
            raise ValueError("enabled managed FRP is not registered")
        return state
    if (
        old
        and state.get("local_port") == local_port
        and running_status(state, run, fetch)
    ):
        state["enabled"] = True
        save_state(root, state)
        return state
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", source_container):
        raise ValueError("invalid source container name")
    existing = json.loads(run(["docker", "inspect", source_container]))[0]
    if not existing.get("State", {}).get("Running"):
        raise ValueError("source FRP container must be running")
    if source_config is None:
        source_config = state.get("source_config") or next(
            (
                row["Source"]
                for row in existing.get("Mounts", [])
                if row.get("Destination") == "/etc/frp/frpc.toml"
                and row.get("Type") == "bind"
            ),
            None,
        )
    source = safe_path(source_config or "")
    if not source.is_file() or source.stat().st_mode & 0o022:
        raise ValueError("FRP source TOML is unavailable")
    record = json.loads(safe_path(root / "shared/deployment.json").read_text())
    if record.get("deploy_root", str(root)) != str(root) or not re.fullmatch(
        r"[a-z0-9][a-z0-9_-]{0,62}", record.get("project_name", "")
    ):
        raise ValueError("managed deployment record mismatch")
    runtime_container = runtime_container or record["project_name"] + "-api-1"
    runtime = json.loads(run(["docker", "inspect", runtime_container]))[0]
    image = runtime.get("Image", "")
    if (runtime.get("Config", {}).get("Labels") or {}).get(
        "com.docker.compose.project"
    ) != record["project_name"]:
        raise ValueError("runtime image source belongs to another deployment")
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", image):
        raise ValueError("immutable runtime image required")
    directory = safe_path(root / "shared/frp")
    directory.mkdir(mode=0o700, exist_ok=True)
    binary = safe_path(directory / "frpc")
    if binary.exists() and (not binary.is_file() or binary.stat().st_mode & 0o022):
        raise ValueError("unsafe managed FRP binary")
    if not binary.exists():
        executable = (
            run(["docker", "exec", source_container, "sh", "-c", "command -v frpc"])
            .decode()
            .strip()
        )
        if (
            not re.fullmatch(r"/[A-Za-z0-9_./-]+", executable)
            or ".." in Path(executable).parts
        ):
            raise ValueError("invalid source FRP executable")
        run(["docker", "cp", source_container + ":" + executable, str(binary)])
        binary.chmod(0o755)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        status_port = probe.getsockname()[1]
    suffix = name.removeprefix("engramproject-frp-")
    proposed = {
        "schema_version": 1,
        "deploy_root": str(root),
        "enabled": True,
        "server_addr": "180.153.172.19",
        "server_port": 7000,
        "remote_port": 18886,
        "local_port": local_port,
        "managed_container": name,
        "proxy_name": "engramproject-" + suffix,
        "source_container": source_container,
        "source_config": str(source),
        "image": image,
        "frpc_image": existing["Image"],
        "binary_path": str(binary),
        "status_port": status_port,
    }
    backup = name + "-rollback"
    if old:
        if run(["docker", "ps", "-aq", "--filter", "name=^/" + backup + "$"]).strip():
            raise ValueError(
                "FRP rollback container already exists; preserved for review"
            )
        run(["docker", "stop", "--time", "10", old["Id"]])
        run(["docker", "rename", old["Id"], backup])
    args = [
        "docker",
        "create",
        "--name",
        name,
        "--network",
        "host",
        "--restart",
        "no",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--tmpfs",
        "/run/frp:rw,noexec,nosuid,size=1m,mode=0700",
        "--mount",
        "type=bind,src=" + str(source) + ",dst=/run/source/frpc.toml,readonly",
        "--mount",
        "type=bind,src=" + str(binary) + ",dst=/run/bin/frpc,readonly",
        "--entrypoint",
        "python3",
    ]
    for key, value in labels.items():
        args += ["--label", key + "=" + value]
    for key, value in {
        "FRP_STATUS_PORT": status_port,
        "FRP_PROXY_NAME": proposed["proxy_name"],
        "FRP_LOCAL_PORT": local_port,
        "FRP_REMOTE_PORT": 18886,
    }.items():
        args += ["--env", key + "=" + str(value)]
    try:
        run([*args, image, "-c", CHILD])
        created = inspect_managed(root, run)
        if not created:
            raise ValueError("managed FRP creation not verified")
        run(["docker", "start", created["Id"]])
        for _ in range(attempts):
            if running_status(proposed, run, fetch):
                run(["docker", "update", "--restart", "unless-stopped", name])
                save_state(root, proposed)
                if old:
                    run(["docker", "rm", backup])
                return proposed
            time.sleep(0.5)
        raise ValueError("managed FRP registration failed")
    except (ValueError, OSError, subprocess.SubprocessError):
        current = inspect_managed(root, run)
        if current:
            run(["docker", "stop", "--time", "10", current["Id"]])
            run(["docker", "rm", current["Id"]])
        if old:
            run(["docker", "rename", backup, name])
            if old.get("State", {}).get("Running"):
                run(["docker", "start", name])
                state["enabled"] = running_status(state, run, fetch)
        else:
            state["enabled"] = False
        save_state(root, state)
        raise ValueError(
            "managed FRP registration failed; previous managed state restored when healthy"
        )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve-root", required=True)
    args = parser.parse_args()
    try:
        serve(args.serve_root)
    except Exception:
        raise SystemExit(
            "Managed FRP process refused; private diagnostics suppressed."
        ) from None
