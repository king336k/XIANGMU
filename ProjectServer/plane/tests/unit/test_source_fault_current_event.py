import json
import pytest
from plane.quality.module_routing import source_fault_modules


@pytest.mark.parametrize(
    "value",
    [
        {"status": "ok", "history": "ERROR code=topic_rate_too_low"},
        {"status": "ok", "error": "", "code": "topic_rate_too_low"},
        {"status": "ok", "history": {"status": "failed", "code": "topic_rate_too_low"}},
    ],
)
def test_success_and_history_are_not_current_source_fault(value):
    assert source_fault_modules(json.dumps(value), value) == set()


@pytest.mark.parametrize(
    "line",
    [
        "WARN no errors [VR_INPUT_MODE_CONFLICT]",
        "WARN [VR_INPUT_MODE_CONFLICT] active=false cleared=true",
        "ERROR unrelated parser failed; documentation example: code=topic_rate_too_low",
    ],
)
def test_explicit_clear_or_example_is_not_an_active_alarm(line):
    assert source_fault_modules(line) == set()
