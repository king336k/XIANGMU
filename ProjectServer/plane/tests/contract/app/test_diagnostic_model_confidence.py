"""Model self-assessment is bounded, attributed evidence, never a correctness probability."""

from types import SimpleNamespace
import json
import pytest
from plane.quality.diagnostic_model import DiagnosticAnswer, analyze_diagnostic

pytestmark = [pytest.mark.contract]


def payload(**values):
    return {
        "answer": "实际日志支持本次连接拒绝，但服务根因待核查。",
        "suggested_actions": [],
        "verification_steps": [],
        "citations": ["FILE-local"],
        **values,
    }


@pytest.mark.parametrize("value", [10**400, -0.01, 1.01, float("nan"), float("inf"), True, False, "0.8"])
def test_invalid_confidence_is_rejected(value):
    parsed = DiagnosticAnswer(
        data=payload(
            model_confidence=value,
            evidence_assessment="partial",
            confidence_basis="有连接失败栈但缺服务状态",
            confidence_references=["FILE-local"],
        )
    )
    assert not parsed.is_valid()


def test_legacy_output_is_compatible_but_missing_is_not_zero():
    parsed = DiagnosticAnswer(data=payload())
    assert parsed.is_valid(), parsed.errors
    assert parsed.validated_data["model_confidence"] is None
    assert parsed.validated_data["evidence_assessment"] is None


@pytest.mark.parametrize("confidence", [0, 0.5, 1])
def test_finite_confidence_has_reviewable_basis(confidence):
    parsed = DiagnosticAnswer(
        data=payload(
            model_confidence=confidence,
            evidence_assessment="partial",
            confidence_basis="日志确认连接被拒，尚无服务进程状态。",
            confidence_references=["FILE-local"],
        )
    )
    assert parsed.is_valid(), parsed.errors
    assert parsed.validated_data["model_confidence"] == confidence


@pytest.mark.parametrize(
    "extra",
    [
        {"confidence_basis": ""},
        {"confidence_references": []},
        {"evidence_assessment": None},
        {"evidence_assessment": "certain"},
    ],
)
def test_numeric_self_assessment_requires_basis_and_supported_enum(extra):
    parsed = DiagnosticAnswer(
        data=payload(
            **{
                "model_confidence": 0.8,
                "evidence_assessment": "partial",
                "confidence_basis": "日志证据",
                "confidence_references": ["FILE-local"],
                **extra,
            }
        )
    )
    assert not parsed.is_valid()


def test_confidence_reference_must_be_a_valid_final_citation(mocker, monkeypatch):
    monkeypatch.delenv("DIAGNOSTIC_AGENT_PYTHON", raising=False)
    mock = mocker.patch("plane.quality.diagnostic_model.OpenAI")
    client = mock.return_value.__enter__.return_value
    value = payload(
        model_confidence=0.7,
        evidence_assessment="partial",
        confidence_basis="日志证据",
        confidence_references=["KN-foreign"],
    )
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(value)))], usage=None
    )
    with pytest.raises(ValueError, match="INVALID_DIAGNOSTIC_CONFIDENCE_REFERENCE"):
        analyze_diagnostic(
            {"api_key": "fixture", "base_url": "https://api.openai.com/v1", "model": "fixture"},
            "neutral",
            [{"file_id": "local", "name": "log", "read_bytes": 10, "excerpt": "Connection refused"}],
            [],
        )


def test_result_records_safe_model_and_instruction_provenance(mocker, monkeypatch):
    monkeypatch.delenv("DIAGNOSTIC_AGENT_PYTHON", raising=False)
    mock = mocker.patch("plane.quality.diagnostic_model.OpenAI")
    client = mock.return_value.__enter__.return_value
    value = payload(
        model_confidence=0.7,
        evidence_assessment="partial",
        confidence_basis="日志显示连接拒绝，服务状态待核查",
        confidence_references=["FILE-local"],
    )
    client.chat.completions.create.return_value = SimpleNamespace(
        model="actual-provider-model",
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(value)))],
        usage=None,
    )
    result = analyze_diagnostic(
        {"api_key": "fixture-private-key", "base_url": "https://api.openai.com/v1", "model": "configured-model"},
        "neutral",
        [{"file_id": "local", "name": "log", "read_bytes": 10, "excerpt": "Connection refused"}],
        [],
    )
    assert result["model_info"]["model"] == "actual-provider-model"
    assert result["model_info"]["instruction_version"] == "diagnostic-evidence-impact-v4"
    assert len(result["model_info"]["boundary_code_sha256"]) == 64
    assert result["confidence_references"][0]["reference"] == "FILE-local"
    assert "fixture-private-key" not in json.dumps(result)


def test_agent_connection_failure_is_a_provider_error_without_exposing_message(mocker, monkeypatch):
    import subprocess

    monkeypatch.setenv("DIAGNOSTIC_AGENT_PYTHON", "fixture-python")
    mocker.patch(
        "plane.quality.diagnostic_model.subprocess.run",
        side_effect=subprocess.CalledProcessError(
            1, ["runner"], stderr=json.dumps({"error_type": "ModelConnectionError"})
        ),
    )
    with pytest.raises(ValueError, match="^AGENT_PROVIDER_UNAVAILABLE$"):
        analyze_diagnostic(
            {"api_key": "fixture-private-key", "base_url": "https://api.openai.com/v1", "model": "fixture"},
            "neutral", [{"file_id": "local", "name": "log", "read_bytes": 10, "excerpt": "Connection refused"}], [],
        )
