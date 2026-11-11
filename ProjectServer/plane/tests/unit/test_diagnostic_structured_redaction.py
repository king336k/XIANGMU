import json
from plane.quality.diagnostic_materials import redact
from plane.knowledge.retrieval import scan_content


def test_already_redacted_daq_log_keeps_unique_long_record_error():
    line=json.dumps({"access_token":"***REDACTED***","padding":"x"*70000,"error":"UNIQUE-EVIDENCE-9527 ConnectionRefusedError errno111"})
    assert not scan_content(line)
    assert "UNIQUE-EVIDENCE-9527" in redact(line)


def test_raw_structured_secret_is_removed_without_dropping_fault_and_nested_context():
    raw=json.dumps({"token":"SYNTHETIC_ONLY_SECRET","nested":{"password":"SYNTHETIC_OTHER_SECRET","code":"ENOSPC errno28"},"message":"output mismatch 7B 8273920B"})
    sanitized=redact(raw)
    assert "SYNTHETIC" not in sanitized
    assert "ENOSPC errno28" in sanitized and "output mismatch" in sanitized
    assert not scan_content(sanitized)


def test_escaped_key_and_long_series_of_safe_placeholders_cannot_hide_real_secret():
    escaped='{"pass\\u0077ord":"RAW_SYNTHETIC_SECRET","error":"errno111"}'
    assert scan_content(escaped)
    assert "RAW_SYNTHETIC_SECRET" not in redact(escaped)
    many=json.dumps({"items":[{"token":"***REDACTED***"} for _ in range(35)]+[{"token":"RAW_SYNTHETIC_SECRET"}],"error":"errno28"})
    assert scan_content(many)
    assert "RAW_SYNTHETIC_SECRET" not in redact(many)
    assert "errno28" in redact(many)


def test_pretty_cross_line_values_and_encoded_nested_json_are_private():
    for text in ['{\n"password":\n"RAW_SYNTHETIC_SECRET",\n"error":"errno111"\n}', json.dumps({"payload":json.dumps({"password":"RAW_SYNTHETIC_SECRET"}),"error":"errno28"},indent=2)]:
        result=redact(text)
        assert "RAW_SYNTHETIC_SECRET" not in result
        assert "errno" in result
