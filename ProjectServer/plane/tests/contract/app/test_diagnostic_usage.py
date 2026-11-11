"""Provider usage is numeric metadata, never untrusted provider text."""

import json
from types import SimpleNamespace
import pytest


@pytest.mark.parametrize(
    "usage,expected",
    [
        (
            {"requests": 2, "input_tokens": 1234, "output_tokens": 500},
            {"requests": 2, "input_tokens": 1234, "output_tokens": 500},
        ),
        ({"requests": True, "input_tokens": -1, "output_tokens": "500", "api_key": "synthetic"}, {}),
        (["not-a-dictionary"], {}),
        (None, {}),
    ],
)
def test_agent_usage_is_optional_and_only_nonnegative_integer_counters_survive(mocker, usage, expected):
    from plane.quality.diagnostic_model import analyze_diagnostic

    output = {
        "answer": "连接被拒绝，待核对监听服务。",
        "suggested_actions": [],
        "verification_steps": [],
        "citations": ["DESCRIPTION"],
        "model_usage": usage,
    }
    mocker.patch.dict("os.environ", {"DIAGNOSTIC_AGENT_PYTHON": "/synthetic/python"})
    mocker.patch(
        "plane.quality.diagnostic_model.subprocess.run", return_value=SimpleNamespace(stdout=json.dumps(output))
    )
    result = analyze_diagnostic(
        {"api_key": "synthetic", "base_url": "http://local.invalid", "model": "test"}, "连接拒绝", [], []
    )
    assert result.get("model_usage", {}) == expected
    assert "api_key" not in str(result)


def test_legacy_agent_result_remains_compatible(mocker):
    from plane.quality.diagnostic_model import analyze_diagnostic

    output = {"answer": "材料不足。", "suggested_actions": [], "verification_steps": [], "citations": ["DESCRIPTION"]}
    mocker.patch.dict("os.environ", {"DIAGNOSTIC_AGENT_PYTHON": "/synthetic/python"})
    mocker.patch(
        "plane.quality.diagnostic_model.subprocess.run", return_value=SimpleNamespace(stdout=json.dumps(output))
    )
    result = analyze_diagnostic({"api_key": "synthetic"}, "连接拒绝", [], [])
    assert "model_usage" not in result


def test_direct_provider_usage_is_reported_without_changing_report_contract(mocker):
    from plane.quality.diagnostic_model import analyze_diagnostic

    output = {"answer": "材料不足。", "suggested_actions": [], "verification_steps": [], "citations": ["DESCRIPTION"]}
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(output)))],
        usage=SimpleNamespace(prompt_tokens=72, completion_tokens=31),
    )
    mocker.patch.dict("os.environ", {}, clear=True)
    client = mocker.MagicMock()
    client.__enter__.return_value.chat.completions.create.return_value = response
    mocker.patch("plane.quality.diagnostic_model.OpenAI", return_value=client)
    result = analyze_diagnostic(
        {"api_key": "synthetic", "base_url": "http://local.invalid", "model": "test"}, "连接拒绝", [], []
    )
    assert result["model_usage"] == {"requests": 1, "input_tokens": 72, "output_tokens": 31}
