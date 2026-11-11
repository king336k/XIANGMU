"""Rule confidence is a declared rule score, never an empirical accuracy probability."""

import importlib.util
from pathlib import Path
import pytest

path = Path(__file__).resolve().parents[2] / "quality" / "diagnostic_rules.py"
spec = importlib.util.spec_from_file_location("rule_confidence_module", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_existing_yaml_rule_keeps_original_numeric_confidence_and_source():
    findings = module.evaluate({"declaredSteps": 100, "actualSteps": 40})
    finding = next(row for row in findings if row["kind"] == "DATA_COMPLETENESS_STEP_MISMATCH_SEVERE")
    assert finding["confidence"] == 0.90
    assert finding["confidence_source"] == "rule"
    assert isinstance(finding["confidence"], float)
    assert "需结合现场日志核实" in finding["basis"]


@pytest.mark.parametrize("value", [None, "0.9", True, False, float("nan"), float("inf"), -0.1, 1.01, 10**1000, {}, []])
def test_invalid_or_unknown_rule_scores_are_omitted_not_coerced(monkeypatch, value):
    monkeypatch.setattr(
        module,
        "rules",
        lambda: [{"id": "TEST", "result": {"causeTitle": "规则", "causeDescription": "来源", "confidence": value}}],
    )
    finding = module.evaluate({})[0]
    assert "confidence" not in finding
    assert "confidence_source" not in finding


@pytest.mark.parametrize("value", [0, 1, 0.8])
def test_valid_rule_score_boundaries_are_preserved(monkeypatch, value):
    monkeypatch.setattr(
        module,
        "rules",
        lambda: [{"id": "TEST", "result": {"causeTitle": "规则", "causeDescription": "来源", "confidence": value}}],
    )
    finding = module.evaluate({})[0]
    assert finding["confidence"] == value
    assert finding["confidence_source"] == "rule"
