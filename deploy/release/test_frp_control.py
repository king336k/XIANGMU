"""FRP switch owns one dedicated container and never mutates the pre-existing frpc."""

import importlib.util
import json
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location(
    "release_frp", Path(__file__).with_name("frp_control.py")
)


def module():
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def test_fresh_default_does_not_touch_docker(tmp_path):
    mod = module()
    assert (
        mod.reconcile(
            tmp_path,
            8886,
            run=lambda *_a, **_k: pytest.fail("no default Docker mutation"),
        )["enabled"]
        is False
    )


def test_child_config_keeps_only_common_connection_and_single_proxy():
    mod = module()
    raw = {
        "serverAddr": "180.153.172.19",
        "serverPort": 7000,
        "auth": {"method": "token", "token": "synthetic-secret"},
        "transport": {"tls": {"enable": True}},
        "webServer": {"port": 9999},
        "proxies": [{"name": "ssh", "remotePort": 19030}],
    }
    result = mod.proxy_config(raw, "engramproject-test", 8886, 18886)
    assert result["auth"] == raw["auth"] and result["transport"] == raw["transport"]
    assert "webServer" not in result
    assert result["proxies"] == [
        {
            "name": "engramproject-test",
            "type": "tcp",
            "localIP": "127.0.0.1",
            "localPort": 8886,
            "remotePort": 18886,
        }
    ]
    assert result["loginFailExit"] is True


def test_managed_container_identity_is_stable_and_deployment_specific(tmp_path):
    mod = module()
    name, labels = mod.identity(tmp_path)
    assert (
        name == mod.identity(tmp_path)[0]
        and name != mod.identity(tmp_path / "other")[0]
    )
    assert labels["io.engram.deploy-root"] == str(tmp_path)
    assert labels["io.engram.component"] == "frp"


def test_close_refuses_unowned_named_container_and_never_stops_existing_frpc(tmp_path):
    mod = module()
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return json.dumps(
            [{"Id": "foreign", "Config": {"Labels": {}}, "State": {"Running": True}}]
        ).encode()

    with pytest.raises(ValueError):
        mod.reconcile(tmp_path, 8886, action="close", run=run)
    assert all(args[1] not in {"stop", "rm"} for args in calls)


class Docker:
    def __init__(self, root, config):
        self.root, self.config, self.rows, self.calls = root, config, {}, []
        self.image = "sha256:" + "a" * 64

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        if args[1] == "ps":
            name = args[-1].removeprefix("name=^/").removesuffix("$")
            return (name if name in self.rows else "").encode()
        if args[1] == "inspect":
            name = args[2]
            if name == "frpc":
                row = {
                    "Image": self.image,
                    "State": {"Running": True},
                    "Mounts": [
                        {
                            "Source": str(self.config),
                            "Destination": "/etc/frp/frpc.toml",
                            "Type": "bind",
                        }
                    ],
                }
            elif name == "platform-api-1":
                row = {
                    "Image": self.image,
                    "Config": {"Labels": {"com.docker.compose.project": "platform"}},
                }
            else:
                row = self.rows[name]
            return json.dumps([row]).encode()
        if args[1:3] == ["exec", "frpc"]:
            return b"/usr/bin/frpc\n"
        if args[1] == "cp":
            Path(args[3]).write_bytes(b"fake-frpc-binary")
        if args[1] in {"create", "run"}:
            name = args[args.index("--name") + 1]
            labels = dict(
                args[index + 1].split("=", 1)
                for index, arg in enumerate(args)
                if arg == "--label"
            )
            self.rows[name] = {
                "Id": name,
                "Config": {"Labels": labels},
                "State": {"Running": args[1] == "run"},
            }
            return name.encode()
        if args[1] in {"stop", "start"}:
            self.rows[args[-1]]["State"]["Running"] = args[1] == "start"
        if args[1] == "rm":
            self.rows.pop(args[-1], None)
        if args[1] == "rename":
            self.rows[args[3]] = self.rows.pop(args[2])
            self.rows[args[3]]["Id"] = args[3]
        return b""


@pytest.fixture
def target(tmp_path):
    root = tmp_path / "platform"
    (root / "shared").mkdir(parents=True)
    (root / "shared/deployment.json").write_text(
        json.dumps({"project_name": "platform"})
    )
    config = tmp_path / "frpc.toml"
    config.write_text(
        'serverAddr="180.153.172.19"\nserverPort=7000\n[auth]\ntoken="synthetic-never-persist"\n'
    )
    config.chmod(0o644)
    return root, Docker(root, config)


def status(mod, root):
    return lambda _url: {
        "tcp": [
            {
                "name": mod.identity(root)[0].replace(
                    "engramproject-frp-", "engramproject-"
                ),
                "status": "running",
                "remote_addr": ":18886",
            }
        ]
    }


def test_open_close_idempotent_state_is_secret_free_and_never_targets_original(target):
    mod = module()
    root, docker = target
    opened = mod.reconcile(root, 8886, "open", run=docker, fetch=status(mod, root))
    assert opened["enabled"] and opened["local_port"] == 8886
    state = (root / "shared/frp-state.json").read_text()
    assert "synthetic-never-persist" not in state and "token" not in state
    assert all(
        not (args[1] in {"stop", "rm", "rename"} and "frpc" in args[2:])
        for args in docker.calls
    )
    count = sum(args[1] == "create" for args in docker.calls)
    mod.reconcile(root, 8886, "open", run=docker, fetch=status(mod, root))
    assert sum(args[1] == "create" for args in docker.calls) == count
    assert not mod.reconcile(root, 8886, "close", run=docker)["enabled"]
    assert not mod.reconcile(root, 8886, "close", run=docker)["enabled"]
    assert not docker.rows[mod.identity(root)[0]]["State"]["Running"]


def test_registration_failure_stops_new_proxy_and_never_claims_enabled(
    target, monkeypatch
):
    mod = module()
    root, docker = target
    monkeypatch.setattr(mod.time, "sleep", lambda *_: None)
    with pytest.raises(ValueError):
        mod.reconcile(
            root, 8886, "open", run=docker, fetch=lambda _url: {"tcp": []}, attempts=1
        )
    assert not json.loads((root / "shared/frp-state.json").read_text())["enabled"]
    assert all(not row["State"]["Running"] for row in docker.rows.values())


def test_failed_port_change_rolls_back_previous_healthy_managed_proxy(
    target, monkeypatch
):
    mod = module()
    root, docker = target
    monkeypatch.setattr(mod.time, "sleep", lambda *_: None)
    mod.reconcile(root, 8886, "open", run=docker, fetch=status(mod, root))
    count = 0

    def fetch(_url):
        nonlocal count
        count += 1
        return {"tcp": []} if count == 1 else status(mod, root)(_url)

    with pytest.raises(ValueError):
        mod.reconcile(root, 8887, "open", run=docker, fetch=fetch, attempts=1)
    current = json.loads((root / "shared/frp-state.json").read_text())
    assert current["enabled"] and current["local_port"] == 8886
    assert docker.rows[mod.identity(root)[0]]["State"]["Running"]


@pytest.mark.parametrize("value", [0, 65536, True, "8886"])
def test_invalid_local_ports_refused_before_docker(target, value):
    mod = module()
    root, docker = target
    with pytest.raises(ValueError):
        mod.reconcile(root, value, "open", run=docker)
    assert not docker.calls


def test_systemd_fallback_uses_owned_unit_and_memory_only_config(target, monkeypatch):
    mod = module()
    root, docker = target
    (root / "shared/frp").mkdir()
    (root / "shared/frp/frpc").write_bytes(b"static-frpc")
    (root / "shared/frp/frpc").chmod(0o755)
    calls = []
    active = False

    def run(args, **kwargs):
        nonlocal active
        calls.append(args)
        if args[0] == "systemctl":
            if args[2] == "show":
                if not active:
                    return b"LoadState=not-found\n"
                return (
                    "LoadState=loaded\nActiveState=active\nDescription=EngramProject managed FRP "
                    + str(root)
                    + "\nExecStart="
                    + str(Path(spec.origin))
                    + "\n"
                ).encode()
            if args[2] == "stop":
                active = False
            return b""
        if args[0] == "systemd-run":
            active = True
            return b""
        return docker(args, **kwargs)

    result = mod.reconcile(
        root,
        8886,
        "open",
        run=run,
        backend="systemd-user",
        source_config=str(docker.config),
        fetch=status(mod, root),
    )
    assert result["enabled"] and result["backend"] == "systemd-user"
    assert any(args[0] == "systemd-run" for args in calls)
    assert all(args[1:2] != ["run"] for args in calls)
    assert not mod.reconcile(root, 8886, "close", run=run, backend="systemd-user")[
        "enabled"
    ]
    assert "synthetic-never-persist" not in (root / "shared/frp-state.json").read_text()


def test_systemd_fallback_refuses_foreign_unit(target):
    mod = module()
    root, docker = target

    def run(args, **kwargs):
        if args[0] == "systemctl":
            return b"LoadState=loaded\nActiveState=active\nDescription=foreign\nExecStart=/bin/sleep\n"
        pytest.fail("must not mutate unrelated unit")

    with pytest.raises(ValueError):
        mod.reconcile(root, 8886, "close", run=run, backend="systemd-user")


def test_close_stops_owned_activating_restart_unit_before_recording_disabled(target):
    mod = module()
    root, docker = target
    phase = "activating"
    calls = []

    def run(args, **kwargs):
        nonlocal phase
        calls.append(args)
        if args[0] == "systemctl" and args[2] == "show":
            return (
                "LoadState=loaded\nActiveState="
                + phase
                + "\nDescription=EngramProject managed FRP "
                + str(root)
                + "\nExecStart=frp_control.py\n"
            ).encode()
        if args[0] == "systemctl" and args[2] == "stop":
            phase = "inactive"
            return b""
        return docker(args, **kwargs)

    assert not mod.reconcile(root, 8886, "close", run=run, backend="systemd-user")[
        "enabled"
    ]
    assert any(args[:3] == ["systemctl", "--user", "stop"] for args in calls)
    assert phase == "inactive"


def test_close_cannot_override_persisted_backend_and_silently_leave_public_process(
    target,
):
    mod = module()
    root, docker = target
    mod.save_state(
        root,
        {
            "schema_version": 1,
            "deploy_root": str(root),
            "enabled": True,
            "backend": "systemd-user",
        },
    )
    with pytest.raises(ValueError):
        mod.reconcile(root, 8886, "close", run=docker, backend="docker")
    assert mod.read_state(root)["enabled"]


def test_docker_close_disables_restart_even_for_created_managed_container(target):
    mod = module()
    root, docker = target
    name, labels = mod.identity(root)
    docker.rows[name] = {
        "Id": name,
        "Config": {"Labels": labels},
        "State": {"Running": False, "Status": "created"},
    }
    assert not mod.reconcile(root, 8886, "close", run=docker)["enabled"]
    assert ["docker", "update", "--restart", "no", name] in docker.calls
    assert ["docker", "stop", "--time", "10", name] in docker.calls


@pytest.mark.parametrize("after", [None, "inactive", "failed"])
def test_close_handles_collected_unit_without_resetting_nonexistent_unit(target, after):
    mod = module()
    root, docker = target
    mod.save_state(
        root,
        {
            "schema_version": 1,
            "deploy_root": str(root),
            "enabled": True,
            "backend": "systemd-user",
        },
    )
    stopped = False
    calls = []

    def run(args, **kwargs):
        nonlocal stopped
        calls.append(args)
        if args[:3] == ["systemctl", "--user", "show"]:
            if stopped and after is None:
                return b"LoadState=not-found\n"
            phase = after if stopped else "active"
            return (
                "LoadState=loaded\nActiveState="
                + phase
                + "\nDescription=EngramProject managed FRP "
                + str(root)
                + "\nExecStart=frp_control.py\n"
            ).encode()
        if args[:3] == ["systemctl", "--user", "stop"]:
            stopped = True
            return b""
        if args[:3] == ["systemctl", "--user", "reset-failed"]:
            if after is None:
                raise ValueError("Unit not loaded")
            return b""
        return docker(args, **kwargs)

    assert not mod.reconcile(root, 8886, "close", run=run)["enabled"]
    assert not mod.read_state(root)["enabled"]
    resets = [
        args for args in calls if args[:3] == ["systemctl", "--user", "reset-failed"]
    ]
    assert bool(resets) == (after == "failed")


def test_close_does_not_hide_systemd_stop_failure_or_claim_disabled(target):
    mod = module()
    root, docker = target
    mod.save_state(
        root,
        {
            "schema_version": 1,
            "deploy_root": str(root),
            "enabled": True,
            "backend": "systemd-user",
        },
    )

    def run(args, **kwargs):
        if args[:3] == ["systemctl", "--user", "show"]:
            return (
                "LoadState=loaded\nActiveState=active\nDescription=EngramProject managed FRP "
                + str(root)
                + "\nExecStart=frp_control.py\n"
            ).encode()
        if args[:3] == ["systemctl", "--user", "stop"]:
            raise ValueError("Systemd stop failed")
        return docker(args, **kwargs)

    with pytest.raises(ValueError, match="stop failed"):
        mod.reconcile(root, 8886, "close", run=run)
    assert mod.read_state(root)["enabled"]
