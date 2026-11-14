"""Status-only material must retain mechanism identity without copying values."""

import json

import pytest

from plane.quality.diagnostic_materials import FILE_BYTES, diagnostic_search_query

pytestmark = [pytest.mark.contract]


def test_json_observation_strings_retain_monitor_mechanism_keys():
    excerpt = json.dumps(
        {
            "observations": [
                "INFO channel_status=ERROR reason=freq low (confirming 1/3)",
                "INFO next_channel_status=OK consecutive_error_cycles=0 module_error_bit=false",
            ]
        }
    )
    query = diagnostic_search_query("generic", [{"excerpt": excerpt}])
    assert set(query.split()) == {
        "channel_status",
        "next_channel_status",
        "consecutive_error_cycles",
        "module_error_bit",
    }
    assert "ERROR" not in query and "false" not in query and "1/3" not in query


def test_structured_status_json_keeps_field_names_without_values():
    excerpt = json.dumps(
        {"channel_status": "WARN", "error_confirm_cycles": 7, "consecutive_error_cycles": 2}
    )
    query = diagnostic_search_query("generic", [{"excerpt": excerpt}])
    assert set(query.split()) == {"channel_status", "error_confirm_cycles", "consecutive_error_cycles"}
    assert "WARN" not in query and "7" not in query


def test_plain_status_text_and_existing_error_priority_remain():
    source = {"excerpt": "INFO channel_status=OK consecutive_error_cycles=0"}
    assert diagnostic_search_query("generic", [source]) == "channel_status consecutive_error_cycles"
    error = {"excerpt": "ERROR RuntimeError: request failed\nINFO module_error_bit=false"}
    assert diagnostic_search_query("generic", [error]) == "RuntimeError"


def test_sensitive_observation_is_excluded_without_query_pollution():
    source = {
        "excerpt": json.dumps(
            {"observations": ["INFO channel_status=ERROR password=example-private-value"]}
        )
    }
    assert diagnostic_search_query("说明", [source]) == "说明"
    query = diagnostic_search_query(
        "generic",
        [{"excerpt": "INFO module_error_bit=private-account-id\nINFO arbitrary_field=private-device-id"}],
    )
    assert query == "module_error_bit"


def test_nested_large_input_is_bounded_and_never_copies_arbitrary_values():
    prefix = json.dumps({"observations": ["INFO channel_status=OK"]}) + "\n"
    excerpt = prefix + ("x" * FILE_BYTES) + "\nINFO error_confirm_cycles=private-tail-value"
    query = diagnostic_search_query("generic", [{"excerpt": excerpt}])
    assert query == "channel_status" and len(query) <= 2000
    nested = "[" * 2500 + "private-unstructured-value" + "]" * 2500
    assert diagnostic_search_query("说明", [{"excerpt": nested}]) == "说明"


def test_ordinary_nonfault_json_keeps_natural_language_fallback():
    source = {"excerpt": json.dumps({"message": "ready", "sample": 12, "healthy": True})}
    assert diagnostic_search_query("检查状态", [source]) == "检查状态"
