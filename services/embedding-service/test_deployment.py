"""Deployment contracts: fake Docker/subprocess/platform DB; no live mutations or inference."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

import docker
import pytest

ROOT = Path(__file__).parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    # The old scripts mutate at import. Boundary mocks keep RED tests harmless.
    inspected = [{"Config": {"Env": ["EMBEDDING_API_KEY=mock-only-key"]},
                  "NetworkSettings": {"Networks": {"plane-local-20261106_default": {"IPAddress": "172.1.2.3"}}}}]
    with patch("docker.from_env") as docker_factory, patch("subprocess.check_output", return_value=json.dumps(inspected).encode()), patch("subprocess.run", return_value=SimpleNamespace(returncode=1)):
        spec.loader.exec_module(module)
        assert not docker_factory.called, "Import must not connect to or mutate Docker"
    return module


@pytest.fixture
def model_dir(tmp_path):
    # pytest --basetemp points to the task artifact directory, never /tmp.
    directory = tmp_path / "models with spaces"
    directory.mkdir()
    for name in ["model.onnx", "tokenizer.json"]:
        (directory / name).write_bytes(b"deployment-contract-placeholder")
    return directory


def docker_client(existing=False):
    client = MagicMock()
    client.containers.get.side_effect = None if existing else docker.errors.NotFound("absent")
    client.containers.get.return_value.attrs = {"NetworkSettings": {"Networks": {"engramproject_default": {}}}}
    return client


def test_imports_have_no_side_effects():
    load("start_local")
    load("configure_platform")


def test_start_defaults_to_check_only(model_dir, capsys):
    module = load("start_local")
    client = docker_client()
    with patch.object(module.docker, "from_env", return_value=client):
        assert module.main(["--model-dir", str(model_dir)]) == 0
    client.containers.run.assert_not_called()
    client.networks.create.assert_not_called()
    assert '"applied": false' in capsys.readouterr().out


def test_start_apply_uses_explicit_path_network_name_and_loopback(model_dir, capsys):
    module = load("start_local")
    client = docker_client()
    with patch.object(module.docker, "from_env", return_value=client):
        assert module.main(["--apply", "--model-dir", str(model_dir), "--service-name", "new-embedding", "--network", "new-platform_default", "--host-port", "19885"]) == 0
    args, options = client.containers.run.call_args
    assert options["name"] == "new-embedding" and options["network"] == "new-platform_default"
    assert options["volumes"] == {str(model_dir.resolve()): {"bind": "/model", "mode": "ro"}}
    assert options["ports"] == {"18885/tcp": ("127.0.0.1", 19885)}
    assert options["environment"]["EMBEDDING_API_KEY"] not in capsys.readouterr().out


def test_existing_service_is_never_recreated_or_restarted(model_dir):
    module = load("start_local")
    client = docker_client(existing=True)
    with patch.object(module.docker, "from_env", return_value=client):
        assert module.main(["--apply", "--model-dir", str(model_dir)]) == 0
    client.containers.run.assert_not_called()
    client.containers.get.return_value.restart.assert_not_called()
    client.containers.get.return_value.remove.assert_not_called()


def test_existing_service_on_wrong_network_is_preserved_but_not_reported_ready(model_dir):
    module = load("start_local")
    client = docker_client(existing=True)
    client.containers.get.return_value.attrs["NetworkSettings"]["Networks"] = {"other-network": {}}
    with patch.object(module.docker, "from_env", return_value=client):
        assert module.main(["--apply", "--model-dir", str(model_dir)]) == 1
    client.containers.run.assert_not_called()
    client.containers.get.return_value.restart.assert_not_called()


def test_missing_network_is_not_created(model_dir):
    module = load("start_local")
    client = docker_client()
    client.networks.get.side_effect = docker.errors.NotFound("absent")
    with patch.object(module.docker, "from_env", return_value=client):
        assert module.main(["--apply", "--model-dir", str(model_dir)]) == 1
    client.networks.create.assert_not_called()
    client.containers.run.assert_not_called()


def test_internal_service_can_explicitly_skip_host_publication(model_dir, capsys):
    module = load("start_local")
    client = docker_client()
    with patch.object(module.docker, "from_env", return_value=client):
        assert module.main(["--apply", "--model-dir", str(model_dir), "--no-publish"]) == 0
    assert client.containers.run.call_args.kwargs["ports"] == {}
    assert json.loads(capsys.readouterr().out)["local_endpoint"] is None


def test_missing_model_is_rejected_without_start(tmp_path):
    module = load("start_local")
    with patch.object(module.docker, "from_env") as factory:
        assert module.main(["--apply", "--model-dir", str(tmp_path)]) == 1
    factory.assert_not_called()


def configured_client(network="new-net", api_network=True):
    service = SimpleNamespace(attrs={"Config": {"Env": ["EMBEDDING_API_KEY=mock-only-secret"]}, "NetworkSettings": {"Networks": {network: {"IPAddress": "172.30.1.99", "Aliases": ["new-embedding"]}}}})
    api = SimpleNamespace(attrs={"NetworkSettings": {"Networks": {network: {}} if api_network else {}}})
    client = MagicMock()
    client.containers.get.side_effect = [service, api]
    return client


@pytest.mark.parametrize("apply", [False, True])
def test_configure_uses_stable_dns_and_stdin_only(apply, capsys):
    module = load("configure_platform")
    client = configured_client()
    result = {"applied": apply, "verified": True, "base_url": "http://new-embedding:18885/v1", "dimensions": 512, "test_vectors": 2, "chat_configuration_unchanged": True, "model": "bge-small-zh-v1.5"}
    with patch.object(module.docker, "from_env", return_value=client), patch.object(module.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=json.dumps(result))) as runner:
        assert module.main(["--service-name", "new-embedding", "--network", "new-net", "--api-container", "new-api"] + (["--apply"] if apply else [])) == 0
    args, kwargs = runner.call_args
    assert "new-api" in args[0] and "mock-only-secret" not in str(args)
    values = json.loads(kwargs["input"])
    assert values["base_url"] == "http://new-embedding:18885/v1" and values["apply"] is apply
    assert values["api_key"] == "mock-only-secret"
    assert "mock-only-secret" not in capsys.readouterr().out


def test_configure_rejects_network_mismatch_without_exec():
    module = load("configure_platform")
    with patch.object(module.docker, "from_env", return_value=configured_client(api_network=False)), patch.object(module.subprocess, "run") as runner:
        assert module.main(["--service-name", "new-embedding", "--network", "new-net", "--api-container", "new-api"]) == 1
    runner.assert_not_called()


def test_configure_failure_never_echoes_process_output(capsys):
    module = load("configure_platform")
    with patch.object(module.docker, "from_env", return_value=configured_client()), patch.object(module.subprocess, "run", return_value=SimpleNamespace(returncode=1, stdout="mock-only-secret", stderr="mock-only-secret")):
        assert module.main(["--service-name", "new-embedding", "--network", "new-net", "--api-container", "new-api", "--apply"]) == 1
    assert "mock-only-secret" not in capsys.readouterr().out


def run_platform_program(program, values, failure=False):
    """Execute exact Docker payload against a transaction-aware in-memory platform fake."""
    state = {"CHAT_MODEL": {"value": "unchanged"}, "KNOWLEDGE_EMBEDDING_MODEL": {"value": "old"}}
    original = copy.deepcopy(state)

    class Atomic:
        def __enter__(self):
            self.before = copy.deepcopy(state)
        def __exit__(self, typ, exc, tb):
            if typ:
                state.clear(); state.update(self.before)

    class Manager:
        def update_or_create(self, key, defaults):
            state[key] = copy.deepcopy(defaults)

    def config():
        return {"configured": True, "enabled": True, "base_url": state["KNOWLEDGE_EMBEDDING_BASE_URL"]["value"], "model": state["KNOWLEDGE_EMBEDDING_MODEL"]["value"]}

    def embed(texts, current):
        if failure:
            raise RuntimeError("mock inference failure with secret omitted")
        return [[1.0] + [0.0] * 511 for _ in texts]

    modules = {}
    def fake(name, **attrs):
        module = ModuleType(name); module.__dict__.update(attrs); modules[name] = module; return module
    fake("django", setup=lambda: None)
    fake("django.db", transaction=SimpleNamespace(atomic=Atomic))
    fake("plane"); fake("plane.license")
    fake("plane.license.models", InstanceConfiguration=SimpleNamespace(objects=Manager()))
    fake("plane.license.utils"); fake("plane.license.utils.encryption", encrypt_data=lambda value: "encrypted:"+value)
    assistant = SimpleNamespace(provider_config=lambda: {"model": state["CHAT_MODEL"]["value"]})
    semantic = SimpleNamespace(configuration=config, valid_embedding_url=lambda url: True, embed=embed)
    fake("plane.knowledge", assistant=assistant, semantic_provider=semantic)
    with patch.dict(sys.modules, modules), patch("sys.stdin", io.StringIO(json.dumps(values))), patch("sys.stdout", io.StringIO()):
        if failure:
            with pytest.raises(RuntimeError):
                exec(program, {"__name__": "__main__"})
        else:
            exec(program, {"__name__": "__main__"})
    return original, state


@pytest.mark.parametrize("apply,failure", [(False, False), (True, True), (True, False)])
def test_platform_configuration_check_rollback_and_chat_preservation(apply, failure):
    module = load("configure_platform")
    original, state = run_platform_program(module.PLATFORM_PROGRAM, {"base_url": "http://new-embedding:18885/v1", "api_key": "mock-only-secret", "model": "bge-small-zh-v1.5", "apply": apply}, failure)
    assert state["CHAT_MODEL"] == original["CHAT_MODEL"]
    if not apply or failure:
        assert state == original
    else:
        assert state["KNOWLEDGE_EMBEDDING_BASE_URL"]["value"] == "http://new-embedding:18885/v1"
        assert state["KNOWLEDGE_EMBEDDING_API_KEY"]["is_encrypted"] is True


def test_env_parameters_and_cli_override(model_dir, monkeypatch):
    module = load("start_local")
    monkeypatch.setenv("EMBEDDING_MODEL_DIR", str(model_dir))
    monkeypatch.setenv("EMBEDDING_SERVICE_NAME", "env-embedding")
    monkeypatch.setenv("EMBEDDING_DOCKER_NETWORK", "env_default")
    client = docker_client()
    with patch.object(module.docker, "from_env", return_value=client):
        assert module.main(["--apply", "--service-name", "cli-embedding"]) == 0
    assert client.containers.run.call_args.kwargs["name"] == "cli-embedding"
    assert client.containers.run.call_args.kwargs["network"] == "env_default"
