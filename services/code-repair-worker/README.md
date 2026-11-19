# Isolated OpenHands code repair worker

This is a separate Python 3.12 environment using the actual OpenHands Software Agent SDK, not a replacement for the field diagnostic gateway. Its registered `SandboxTool` executes only through `docker exec` in a disposable container. The controller owns the Docker CLI and model configuration; neither is exposed to model tools.

`requirements.in` pins SDK/tools/workspace/agent-server to the matched official 1.62.0 release and `requirements.lock` pins all 193 resolved distributions with SHA256 hashes. This slice runs the SDK Agent/Conversation and custom ToolDefinition/ToolExecutor; it does not start the optional browser, AgentServer or DockerWorkspace. The official DockerWorkspace currently lacks CPU/memory run options, so containers are provisioned explicitly with 2 CPU, 2 GiB, network none, a read-only root, 128 MiB workspace tmpfs plus 64 MiB temporary tmpfs, no capabilities, no privilege escalation, no devices, no production mounts, and no Docker socket.

The SDK dependency environment remains outside the repository under a dedicated task artifact directory. Do not install it into ROS, the central diagnostics environment, or platform Python. On a supported Python 3.12 host:

```sh
uv venv --python python3.12 /approved/artifacts/openhands/venv
uv pip sync --python /approved/artifacts/openhands/venv/bin/python --require-hashes services/code-repair-worker/requirements.lock
uv pip check --python /approved/artifacts/openhands/venv/bin/python
```

The installed environment measured about 594 MiB for this experiment. This is an observed installation size, not a memory requirement or a guarantee that a ROS/C++ build fits in 2 GiB. No full ROS build or browser download is part of this slice.

## Controller contract

`worker.py` reads one JSON object from stdin:

```json
{
  "config": { "model": "configured-model", "base_url": "configured-provider", "api_key": "stdin-only" },
  "task": {
    "project_id": "authorized-project",
    "source_id": "approved-source-id",
    "repository_commit": "exact-40-or-64-hex-commit",
    "problem": "Original failure and available observations, without a hidden answer"
  },
  "test_command": "python -m pytest -q"
}
```

The entire stdin object is controller/admin input, not model-selected policy. `test_command` is an administrator-configured acceptance command. A future platform endpoint must resolve project/source/commit and test command server-side before invoking this worker.

Environment variables supplied by the administrator:

- `QUALITY_REMOTE_SOURCE_SNAPSHOTS_ROOT`: the deployed read-only snapshot root.
- `CODE_REPAIR_WORK_ROOT`: an approved task artifact root for new writable workspaces/results.
- `CODE_REPAIR_DEPENDENCIES`: the isolated Python 3.12 site-packages directory, mounted read-only for pytest in the sandbox.
- `CODE_REPAIR_IMAGE`: default `python:3.12-slim`; deployment should pin a reviewed image digest and matching build toolchain.

The source adapter verifies project permission, manifest immutability, exact repository commit, file sizes/hashes and symlink safety before making the workspace copy. Model input cannot select a host directory, Git ref, container image, dependency mount or Docker command. Its bash commands run only as the fixed unprivileged tool UID inside `/workspace` in the isolated container. PID1 is a root `sleep` process with every capability dropped; it never executes model commands. The model has no writable host workspace mount. The model key remains in controller memory. Conversation persistence is disabled; the SDK uses its actual InMemoryFileStore.

The worker executes the fixed baseline test and runs the actual SDK conversation. It then kills every other process of the unprivileged tool UID, confirms no writer remains, streams a bounded regular-file-only candidate tar, and deletes the original sandbox. A fresh container mounts that candidate read-only and executes the fixed final test. Only then does the controller collect a diff from the same frozen candidate using directory FDs and no-follow opens. Command output is streamed with a 64 KiB hard cap; timeout or excess output removes the whole sandbox. The result includes provenance, `baseline`, `verification`, actual `tool_receipts`, `diff`, `agent_error_class`, `code_verified`, and fixed false `business_verified`/`production_deployed`. Added, deleted or modified test/control files invalidate `code_verified` (including conftest, pytest configuration, test directories, CMake and `_test.cpp`). For pytest the final output must include at least one passing test and no fewer passes than the baseline executed count (passed plus failed); exit 0 with all skips is insufficient. A model report alone cannot make it pass. Exceptions retain collected receipts; raw provider error messages and model credentials are not written to the result.

The workspace and patch remain artifacts for review. This worker does not merge, publish, deploy, access a robot or prove business recovery. A real source fix still needs project-specific review/build and an authorized deployment/acceptance chain.

## Actual checks and real-model experiment

`test_worker.py` runs the real SDK Agent/Conversation against a synthetic HTTP provider, a real disposable Docker container, actual file reads/writes and actual pytest. It proves the integration/control chain. It does not count as a real-model reasoning evaluation.

```sh
/approved/artifacts/openhands/venv/bin/python -m unittest discover -s services/code-repair-worker -p test_worker.py -v
```

`run_case.py` accepts model configuration only on stdin and creates a fresh immutable calculator fixture snapshot. The model sees the original source/tests and a generic failing-tests problem; it is not given the repair. This fixture uses an explicitly labelled deterministic fixture identity, not a deployment commit. Root runs the real provider experiment and records its outcome separately:

```sh
provider-config-command | /approved/artifacts/openhands/venv/bin/python services/code-repair-worker/run_case.py \
  --project-id AUTHORIZED_PROJECT_ID --output-root /approved/artifacts/openhands-real-model
```

No credentials should be passed as command arguments or saved in fixture files. Do not infer real-model or production acceptance from successful import, a synthetic-provider test, or a patch alone.

## Official sources and license

- SDK and tools: https://github.com/OpenHands/software-agent-sdk
- Official API/docs: https://docs.openhands.dev/sdk
- Matched package installation: https://docs.openhands.dev/sdk/getting-started
- SDK upstream MIT license: https://github.com/OpenHands/software-agent-sdk/blob/main/LICENSE

The integration code follows this repository's AGPL-3.0-only notice. The SDK's MIT license does not substitute for a full transitive-dependency/image/model-license audit. Public wheels were installed in an isolated environment; no private source was sent to a package service.

## Internal async service

`server.py` is a private controller endpoint. Set `CODE_REPAIR_SERVICE_TOKEN` to a random bearer of at least 24 characters. Comparison is constant time. One active job is accepted; additional submissions receive HTTP 503, with no queue. POST bodies are capped at 1 MiB. Model configuration exists only in the accepted request and worker stdin, and is not included in job status or logs. The child worker has a 300-second process deadline.

`CODE_REPAIR_TEST_RUNNERS` is administrator JSON keyed by approved `source_id`. Every entry must match the exact repository commit and supply a fixed test argv, for example:

```json
{ "approved-python-source": { "repository_commit": "exact-commit", "argv": ["python", "-m", "pytest", "-q"] } }
```

The public/model request cannot supply `test_command`, an arbitrary shell or a test runner. A C++/ROS source without a configured matching build/acceptance command is rejected; it is not guessed to be Python.

- `POST /jobs` with `{config, task}` returns HTTP 202 with `{job_id, status, poll_path}`.
- `GET /jobs/<job_id>` returns running/completed/failed; completed jobs contain the worker result, diff and actual receipts.
- Both endpoints require the service bearer. There is no arbitrary URL, file, terminal or deployment endpoint.

The central platform must authorize project/source/commit before submission, retain job ownership and poll only its fixed configured service origin. A standalone job is not evidence that the central diagnostic Agent invoked it. Platform integration and real-model results are verified separately by the Controller.

Build from the repository root. Use the `sandbox` target for the model-tool container and `controller` target for the trusted controller. Only the controller may receive Docker daemon access. Never mount that socket in the sandbox; avoid providing the host's Python site-packages path in deployed operation by baking reviewed dependencies into the sandbox image.

```sh
docker build -f services/code-repair-worker/Dockerfile --target sandbox -t code-repair-sandbox:1.62.0 .
docker build -f services/code-repair-worker/Dockerfile --target controller -t code-repair-controller:1.62.0 .
```

Use `CODE_REPAIR_IMAGE=code-repair-sandbox:1.62.0` and omit `CODE_REPAIR_DEPENDENCIES` when dependencies are baked in. Mount the source snapshot root read-only, and mount the artifact/work root at the **same absolute path** on host and controller because only the frozen candidate is passed to the fresh read-only checking container. The model workspace is tmpfs, so its disk writes cannot fill the host artifact filesystem. Configure CPU/memory limits for the controller as well. Bind the service only to the approved internal network; its bearer does not substitute for the platform's project permissions.

The multi-stage Dockerfile is supplied for deployment; this task's verified smoke uses the already-installed isolated environment and a real `python:3.12-slim` tool container. An image build is not claimed until its logs and runtime checks exist.

Actual-model acceptance for this task was performed by the Controller against the calculator fixture: the original pytest failed, the real model changed the source, the unchanged test passed, and an actual diff was retained. This is a tiny isolated code fixture. It does not establish a DAQ/ROS source fix, deployment safety, or hardware recovery. A field configuration defect such as D499 stays on the scoped configuration-diagnosis/repair path; sending it to a coding worker would not replace its required evidence or motion acceptance.
