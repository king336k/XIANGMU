import json
from types import SimpleNamespace
import subprocess
import pytest


@pytest.mark.parametrize("value,expected", [(None, 300), ("90", 90), ("900", 600), ("1", 60), ("bad", 300)])
def test_diagnostic_budget_is_bounded_and_task_limit_covers_agent(monkeypatch, value, expected):
    from plane.quality.diagnostic_limits import timeout_seconds, task_limits

    if value is None:
        monkeypatch.delenv("DIAGNOSTIC_TIMEOUT_SECONDS", raising=False)
    else:
        monkeypatch.setenv("DIAGNOSTIC_TIMEOUT_SECONDS", value)
    assert timeout_seconds() == expected
    soft, hard = task_limits()
    assert expected + 10 < soft < hard


@pytest.mark.parametrize(
    "error,code",
    [
        ({"error_type": "ModelHTTPError", "status_code": 429}, "AGENT_PROVIDER_UNAVAILABLE"),
        ({"error_type": "ModelHTTPError", "status_code": 401}, "AGENT_PROVIDER_AUTH"),
        ({"error_type": "UnexpectedModelBehavior"}, "AGENT_INVALID_OUTPUT"),
    ],
)
def test_agent_failure_exposes_only_safe_error_category(monkeypatch, mocker, error, code):
    from plane.quality.diagnostic_model import analyze_diagnostic

    monkeypatch.setenv("DIAGNOSTIC_AGENT_PYTHON", "/synthetic/python")
    mocker.patch(
        "plane.quality.diagnostic_model.subprocess.run",
        side_effect=subprocess.CalledProcessError(1, [], stderr=json.dumps(error)),
    )
    with pytest.raises(ValueError, match=code):
        analyze_diagnostic({"model": "test", "api_key": "synthetic"}, "material", [], [])


def test_configured_timeout_reaches_agent_and_subprocess(monkeypatch, mocker):
    from plane.quality.diagnostic_model import analyze_diagnostic

    monkeypatch.setenv("DIAGNOSTIC_TIMEOUT_SECONDS", "420")
    monkeypatch.setenv("DIAGNOSTIC_AGENT_PYTHON", "/synthetic/python")
    child = mocker.patch(
        "plane.quality.diagnostic_model.subprocess.run",
        return_value=SimpleNamespace(
            stdout=json.dumps(
                {"answer": "材料不足", "suggested_actions": [], "verification_steps": [], "citations": ["DESCRIPTION"]}
            )
        ),
    )
    analyze_diagnostic({"model": "test", "api_key": "synthetic"}, "material", [], [])
    assert child.call_args.kwargs["timeout"] == 430
    assert json.loads(child.call_args.kwargs["input"])["config"]["diagnostic_timeout_seconds"] == 420


def test_multiple_feedback_jobs_use_dedicated_queue_and_allow_long_backlog(mocker):
    from plane.quality.diagnostics import enqueue

    child = mocker.patch("plane.quality.tasks.run_diagnostic.apply_async")
    for index in range(30):
        enqueue(str(index))
    assert child.call_count == 30
    assert all(
        call.kwargs["queue"] == "diagnostics" and call.kwargs["expires"] == 21600 for call in child.call_args_list
    )


def test_pydantic_model_timeout_is_not_unknown_agent_failure(monkeypatch, mocker):
    from plane.quality.diagnostic_model import analyze_diagnostic

    monkeypatch.setenv("DIAGNOSTIC_AGENT_PYTHON", "/synthetic/python")
    mocker.patch(
        "plane.quality.diagnostic_model.subprocess.run",
        side_effect=subprocess.CalledProcessError(1, [], stderr=json.dumps({"error_type": "ModelTimeoutError"})),
    )
    with pytest.raises(TimeoutError):
        analyze_diagnostic({"model": "test", "api_key": "synthetic"}, "material", [], [])
