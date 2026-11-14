"""Timeout observations retain fixed categories, never provider text or credentials."""

import json
import subprocess
import pytest
from plane.quality.diagnostic_model import analyze_diagnostic
from plane.quality.tasks import run_diagnostic
from plane.tests.contract.app.test_diagnostic_finalization import diagnostic

pytestmark = [pytest.mark.contract]


def analyze_failure(mocker, monkeypatch, failure):
    monkeypatch.setenv("DIAGNOSTIC_AGENT_PYTHON", "fixture-python")
    mocker.patch("plane.quality.diagnostic_model.subprocess.run", side_effect=failure)
    with pytest.raises(TimeoutError) as caught:
        analyze_diagnostic(
            {"api_key": "PRIVATE-SENTINEL", "base_url": "https://private.invalid", "model": "offline"},
            "neutral",
            [],
            [],
        )
    return caught.value


@pytest.mark.parametrize("phase", ["connect", "read", "write", "pool"])
def test_agent_timeout_retains_only_safe_fixed_metadata(mocker, monkeypatch, phase):
    failure = {
        "source": "agent_transport",
        "transport_phase": phase,
        "deadline_kind": "unknown",
        "provider_called": False,
        "url": "PRIVATE-SENTINEL",
        "message": "PRIVATE-SENTINEL",
    }
    error = analyze_failure(
        mocker,
        monkeypatch,
        subprocess.CalledProcessError(
            1, ["runner"], stderr=json.dumps({"error_type": "ModelTimeoutError", "model_failure": failure})
        ),
    )
    assert str(error) == "AGENT_PROVIDER_TIMEOUT"
    assert error.model_failure == {k: v for k, v in failure.items() if k not in {"url", "message"}}
    assert "PRIVATE" not in json.dumps(error.model_failure)


@pytest.mark.parametrize(
    "failure,source,kind",
    [
        (subprocess.TimeoutExpired(["runner"], 310), "subprocess_deadline", "subprocess_deadline"),
        (subprocess.CalledProcessError(124, ["runner"], stderr="PRIVATE-SENTINEL"), "agent_deadline", "unknown"),
    ],
)
def test_deadline_origin_is_fixed_and_not_guessed(mocker, monkeypatch, failure, source, kind):
    error = analyze_failure(mocker, monkeypatch, failure)
    assert str(error) == "AGENT_DEADLINE"
    assert error.model_failure == {"source": source, "transport_phase": "unknown", "deadline_kind": kind}


def test_metadata_unknown_fields_and_types_are_not_trusted():
    from plane.quality.diagnostic_failures import safe_model_failure

    assert safe_model_failure(
        {
            "source": "PRIVATE",
            "transport_phase": ["connect"],
            "deadline_kind": True,
            "provider_called": 1,
            "error_chain": "PRIVATE",
            "message": "PRIVATE",
        }
    ) == {"source": "unknown", "transport_phase": "unknown", "deadline_kind": "unknown"}


def test_legacy_timeout_is_still_compatible_without_invented_phase(mocker, monkeypatch):
    error = analyze_failure(
        mocker,
        monkeypatch,
        subprocess.CalledProcessError(1, ["runner"], stderr=json.dumps({"error_type": "ModelTimeoutError"})),
    )
    assert str(error) == "AGENT_PROVIDER_TIMEOUT"
    assert error.model_failure == {"source": "unknown", "transport_phase": "unknown", "deadline_kind": "unknown"}


def test_exit124_keeps_agent_run_metadata(mocker, monkeypatch):
    metadata = {"source": "agent_deadline", "transport_phase": "unknown", "deadline_kind": "agent_run"}
    error = analyze_failure(
        mocker,
        monkeypatch,
        subprocess.CalledProcessError(
            124, ["runner"], stderr=json.dumps({"error_type": "TimeoutError", "model_failure": metadata})
        ),
    )
    assert str(error) == "AGENT_DEADLINE" and error.model_failure == metadata


def test_typed_model_request_timeout_is_observed_without_message_parsing(mocker, monkeypatch):
    metadata = {"source": "agent_deadline", "transport_phase": "unknown", "deadline_kind": "request_timeout"}
    error = analyze_failure(
        mocker,
        monkeypatch,
        subprocess.CalledProcessError(
            1, ["runner"], stderr=json.dumps({"error_type": "ModelRequestTimeout", "model_failure": metadata})
        ),
    )
    assert str(error) == "AGENT_PROVIDER_TIMEOUT" and error.model_failure == metadata


def test_auth_status_still_takes_precedence_over_timeout_metadata(mocker, monkeypatch):
    monkeypatch.setenv("DIAGNOSTIC_AGENT_PYTHON", "fixture-python")
    mocker.patch(
        "plane.quality.diagnostic_model.subprocess.run",
        side_effect=subprocess.CalledProcessError(
            1,
            ["runner"],
            stderr=json.dumps(
                {
                    "error_type": "ModelTimeoutError",
                    "model_failure": {"source": "agent_transport", "transport_phase": "read"},
                    "error_chain": [{"error_type": "ModelHTTPError", "status_code": 401}],
                }
            ),
        ),
    )
    with pytest.raises(ValueError, match="^AGENT_PROVIDER_AUTH$"):
        analyze_diagnostic(
            {"api_key": "PRIVATE", "base_url": "https://private.invalid", "model": "offline"}, "neutral", [], []
        )


@pytest.mark.django_db
def test_premodel_timeout_records_not_called_and_retry_history(workspace, create_user, mocker):
    _, job = diagnostic(workspace, create_user, mocker)
    provider = mocker.patch("plane.quality.tasks.analyze_diagnostic")
    mocker.patch("plane.quality.tasks.time.monotonic", side_effect=[100, 121, 122])
    run_diagnostic(job.id)
    job.refresh_from_db()
    assert job.result["model_error_code"] == "MODEL_TIMEOUT" and job.status == "queued"
    assert job.result["model_failure"] == {
        "source": "pre_model_materials",
        "transport_phase": "unknown",
        "deadline_kind": "pre_model_materials",
        "provider_called": False,
    }
    assert job.result["attempt_failures"][0]["provider_called"] is False
    assert job.result["attempt_failures"][0]["attempt"] == 1
    provider.assert_not_called()


@pytest.mark.django_db
def test_failed_attempt_metadata_survives_successful_retry(workspace, create_user, mocker):
    from plane.quality.diagnostic_failures import DiagnosticTimeoutFailure

    _, job = diagnostic(workspace, create_user, mocker)
    details = {"source": "agent_transport", "transport_phase": "connect", "deadline_kind": "unknown"}
    mocker.patch(
        "plane.quality.tasks.analyze_diagnostic",
        side_effect=DiagnosticTimeoutFailure("AGENT_PROVIDER_TIMEOUT", details),
    )
    run_diagnostic(job.id)
    job.refresh_from_db()
    assert job.result["model_failure"] == details and len(job.result["attempt_failures"]) == 1
    mocker.patch("plane.quality.tasks.analyze_diagnostic", return_value={"answer": "正常材料", "citations": []})
    run_diagnostic(job.id)
    job.refresh_from_db()
    assert job.result["model_status"] == "completed" and "model_failure" not in job.result
    assert job.result["attempt_failures"][0]["transport_phase"] == "connect"


def test_failure_history_is_bounded_sanitized_and_attempt_idempotent():
    from plane.quality.diagnostic_failures import append_attempt_failure

    result = {
        "model_error_code": "MODEL_TIMEOUT",
        "duration_ms": 30000,
        "model_failure": {"source": "agent_transport", "transport_phase": "read", "deadline_kind": "unknown"},
        "retry": {"count": 3},
        "attempt_failures": [
            {"attempt": n, "code": "MODEL_TIMEOUT", "duration_ms": 1, "source": "PRIVATE", "message": "PRIVATE"}
            for n in range(1, 10)
        ],
    }
    append_attempt_failure(result)
    append_attempt_failure(result)
    history = result["attempt_failures"]
    assert len(history) <= 4 and len({r["attempt"] for r in history}) == len(history)
    assert history[-1]["attempt"] == 4 and history[-1]["duration_ms"] == 30000
    assert "PRIVATE" not in json.dumps(history)


def test_agent_connection_error_retains_phase_without_changing_code(mocker, monkeypatch):
    monkeypatch.setenv("DIAGNOSTIC_AGENT_PYTHON", "fixture-python")
    metadata = {"source": "agent_transport", "transport_phase": "connect", "deadline_kind": "unknown"}
    mocker.patch(
        "plane.quality.diagnostic_model.subprocess.run",
        side_effect=subprocess.CalledProcessError(
            1, ["runner"], stderr=json.dumps({"error_type": "ModelConnectionError", "model_failure": metadata})
        ),
    )
    with pytest.raises(ValueError, match="^AGENT_PROVIDER_UNAVAILABLE$") as caught:
        analyze_diagnostic(
            {"api_key": "PRIVATE", "base_url": "https://private.invalid", "model": "offline"}, "neutral", [], []
        )
    assert caught.value.model_failure == metadata


def test_inline_reference_categories_roundtrip_without_unknown_values(mocker, monkeypatch):
    monkeypatch.setenv("DIAGNOSTIC_AGENT_PYTHON", "fixture-python")
    mocker.patch(
        "plane.quality.diagnostic_model.subprocess.run",
        side_effect=subprocess.CalledProcessError(
            1,
            ["runner"],
            stderr=json.dumps(
                {
                    "error_type": "UnexpectedModelBehavior",
                    "validation_categories": ["inline_reference_not_allowed", "inline_reference_not_cited", "PRIVATE"],
                }
            ),
        ),
    )
    with pytest.raises(ValueError, match="^AGENT_INVALID_OUTPUT$") as caught:
        analyze_diagnostic(
            {"api_key": "PRIVATE", "base_url": "https://private.invalid", "model": "offline"}, "neutral", [], []
        )
    assert caught.value.validation_categories == ["inline_reference_not_allowed", "inline_reference_not_cited"]


def test_all_seven_reference_categories_survive_parent_boundary():
    from plane.quality.diagnostic_model import safe_validation_categories

    categories = [
        "citation_not_in_current_allowlist",
        "confidence_not_in_final_citations",
        "severity_reference_not_allowed",
        "severity_reference_not_cited",
        "severity_reference_not_file",
        "inline_reference_not_allowed",
        "inline_reference_not_cited",
    ]
    assert safe_validation_categories(categories) == categories
    assert safe_validation_categories([*categories, "PRIVATE"]) == categories


@pytest.mark.django_db
def test_provider_unavailable_task_keeps_safe_metadata(workspace, create_user, mocker):
    from plane.quality.diagnostic_failures import DiagnosticProviderFailure

    _, job = diagnostic(workspace, create_user, mocker)
    details = {"source": "agent_transport", "transport_phase": "connect", "deadline_kind": "unknown"}
    mocker.patch(
        "plane.quality.tasks.analyze_diagnostic",
        side_effect=DiagnosticProviderFailure("AGENT_PROVIDER_UNAVAILABLE", details),
    )
    run_diagnostic(job.id)
    job.refresh_from_db()
    assert job.result["model_error_code"] == "AGENT_PROVIDER_UNAVAILABLE"
    assert job.result["model_failure"] == details
    assert job.result["attempt_failures"][0]["transport_phase"] == "connect"


@pytest.mark.django_db
def test_terminal_fourth_failure_keeps_all_attempts_without_increasing_retry_limit(workspace, create_user, mocker):
    from plane.quality.diagnostic_failures import DiagnosticTimeoutFailure

    _, job = diagnostic(workspace, create_user, mocker)
    details = {"source": "agent_transport", "transport_phase": "read", "deadline_kind": "unknown"}
    mocker.patch(
        "plane.quality.tasks.analyze_diagnostic",
        side_effect=DiagnosticTimeoutFailure("AGENT_PROVIDER_TIMEOUT", details),
    )
    mocker.patch("plane.quality.module_routing.route_completed")
    mocker.patch("plane.quality.diagnostic_severity_apply.apply_severity", return_value={})
    for _ in range(4):
        run_diagnostic(job.id)
        job.refresh_from_db()
    assert job.status == "completed" and job.result["retry"]["count"] == 3
    assert job.result["fallback"] == "rules_after_retries"
    assert [r["attempt"] for r in job.result["attempt_failures"]] == [1, 2, 3, 4]
    assert all(r["transport_phase"] == "read" for r in job.result["attempt_failures"])


def test_direct_sdk_timeout_uses_known_transport_class_not_error_text():
    import httpx
    from openai import APITimeoutError
    from plane.quality.diagnostic_failures import failure_from_exception

    error = APITimeoutError(request=httpx.Request("GET", "https://private.invalid"))
    error.__cause__ = httpx.ReadTimeout("PRIVATE connect write pool")
    assert failure_from_exception(error) == {
        "source": "direct_sdk",
        "transport_phase": "read",
        "deadline_kind": "unknown",
    }
    bare = TimeoutError("connect read PRIVATE")
    assert failure_from_exception(bare) == {
        "source": "unknown",
        "transport_phase": "unknown",
        "deadline_kind": "unknown",
    }


def test_malformed_history_cannot_persist_private_or_invalid_numeric_values():
    from plane.quality.diagnostic_failures import safe_attempt_failures

    rows = [
        {"attempt": True, "code": "MODEL_TIMEOUT", "duration_ms": 1},
        {"attempt": 2, "code": "PRIVATE", "duration_ms": 1},
        {"attempt": 3, "code": "MODEL_TIMEOUT", "duration_ms": float("inf")},
        {"attempt": 4, "code": "MODEL_TIMEOUT", "duration_ms": 1, "message": "PRIVATE", "provider_called": "PRIVATE"},
    ]
    assert safe_attempt_failures(rows) == [
        {
            "attempt": 4,
            "code": "MODEL_TIMEOUT",
            "duration_ms": 1,
            "source": "unknown",
            "transport_phase": "unknown",
            "deadline_kind": "unknown",
        }
    ]
