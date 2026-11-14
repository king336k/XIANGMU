"""Server opts into actionable typed generation without rewriting stored legacy reports."""

import json
from types import SimpleNamespace

import pytest

from plane.quality.diagnostic_model import DiagnosticAnswer, analyze_diagnostic

pytestmark = [pytest.mark.contract]


def test_server_requires_actionable_generation_and_keeps_budget(mocker, monkeypatch):
    monkeypatch.setenv("DIAGNOSTIC_AGENT_PYTHON", "fixture-python")
    monkeypatch.setenv("DIAGNOSTIC_AGENT_SCRIPT", "/no-real-runner/fixture.py")
    captured = []
    output = {
        "answer": "根因待核验。",
        "suggested_actions": ["只读核对同一事件最早异常及当前有效配置。"],
        "verification_steps": ["证据不足时保留未验证，不执行机器人动作。"],
        "citations": ["DESCRIPTION"],
    }

    def run(args, **kwargs):
        captured.append(json.loads(kwargs["input"]))
        assert kwargs["capture_output"] and kwargs["check"]
        return SimpleNamespace(stdout=json.dumps(output))

    mocker.patch("plane.quality.diagnostic_model.subprocess.run", side_effect=run)
    result = analyze_diagnostic(
        {
            "api_key": "synthetic",
            "base_url": "https://synthetic.invalid",
            "model": "offline",
            "require_actionable_report": True,
        },
        "当前缺少错误阶段",
        [],
        [],
    )
    assert captured[0]["require_actionable_report"] is True
    assert captured[0]["config"]["require_actionable_report"] is True
    assert result["model_info"]["instruction_version"] == "diagnostic-evidence-impact-v5"
    assert result["verification_steps"] == output["verification_steps"]


def test_legacy_report_deserialization_stays_compatible():
    old = {
        "answer": "历史诊断，具体结论待核验。",
        "suggested_actions": [],
        "verification_steps": [],
        "citations": ["DESCRIPTION"],
    }
    parsed = DiagnosticAnswer(data=old)
    assert parsed.is_valid(), parsed.errors
    assert parsed.validated_data["verification_steps"] == []


@pytest.mark.parametrize("typed", [True, False])
def test_versioned_generation_rejects_empty_steps(mocker, monkeypatch, typed):
    value = {"answer": "原因待确认。", "suggested_actions": [], "verification_steps": [], "citations": ["DESCRIPTION"]}
    if typed:
        monkeypatch.setenv("DIAGNOSTIC_AGENT_PYTHON", "fixture-python")
        mocker.patch(
            "plane.quality.diagnostic_model.subprocess.run", return_value=SimpleNamespace(stdout=json.dumps(value))
        )
    else:
        monkeypatch.delenv("DIAGNOSTIC_AGENT_PYTHON", raising=False)
        client = mocker.patch("plane.quality.diagnostic_model.OpenAI").return_value.__enter__.return_value
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(value)))], usage=None
        )
    with pytest.raises(ValueError, match="INVALID_DIAGNOSTIC_OUTPUT"):
        analyze_diagnostic(
            {
                "api_key": "synthetic",
                "base_url": "https://synthetic.invalid",
                "model": "offline",
                "require_actionable_report": True,
            },
            "同事件材料",
            [],
            [],
        )


@pytest.mark.django_db
def test_diagnostic_task_always_requests_current_actionable_contract(workspace, create_user, mocker):
    from plane.quality.tasks import run_diagnostic
    from plane.tests.contract.app.test_diagnostic_finalization import diagnostic

    _, job = diagnostic(workspace, create_user, mocker)
    model = mocker.patch(
        "plane.quality.tasks.analyze_diagnostic",
        return_value={
            "answer": "材料限定诊断，根因待验证。",
            "suggested_actions": ["只读核对同事件错误。"],
            "verification_steps": ["证据不足继续待验证。"],
            "citations": [],
        },
    )
    run_diagnostic(job.id)
    assert model.call_args.args[0]["require_actionable_report"] is True
