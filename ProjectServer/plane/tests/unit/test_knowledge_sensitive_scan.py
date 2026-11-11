import pytest
from plane.knowledge.retrieval import scan_content


@pytest.mark.unit
@pytest.mark.parametrize(
    "content",
    [
        '{"api_key":"SYNTHETIC_TEST_ONLY"}',
        "{'password':'1'}",
        "password=1",
        "Authorization: Bearer SYNTHETIC_TEST_ONLY",
        "Cookie: session-id=SYNTHETIC_TEST_ONLY",
        "access_token=SYNTHETIC_TEST_ONLY",
        "密钥：SYNTHETIC_TEST_ONLY",
        '{"Authorization":"Bearer SYNTHETIC_TEST_ONLY"}',
    ],
)
def test_structured_and_short_credentials_are_flagged_without_returning_the_value(content):
    findings = scan_content(content)
    assert findings
    assert all(set(row) == {"kind", "line", "message"} for row in findings)
    assert "SYNTHETIC_TEST_ONLY" not in str(findings)


@pytest.mark.unit
@pytest.mark.parametrize("content", ["password=[已移除]", "api_key=<已脱敏>", "普通故障知识：检查时间戳顺序。"])
def test_explicit_redaction_placeholders_do_not_block_publication(content):
    assert not scan_content(content)


@pytest.mark.unit
def test_article_findings_point_to_field_and_its_own_line():
    from plane.knowledge.retrieval import scan_article

    findings = scan_article("普通标题", "普通第一行\npassword=SYNTHETIC_TEST_ONLY", ["普通标签"])
    assert len(findings) == 1
    assert findings[0]["field"] == "content" and findings[0]["line"] == 2


@pytest.mark.unit
def test_long_single_record_scan_has_bounded_regex_work():
    import signal
    def expired(*_):
        raise TimeoutError("long record credential scan exceeded 2 seconds")
    prior=signal.signal(signal.SIGALRM,expired)
    signal.setitimer(signal.ITIMER_REAL,2)
    try:
        assert scan_content('x'*100000+' tail=ordinary')==[]
        assert scan_content('x'*100000+' contact: person@example.test')
    finally:
        signal.setitimer(signal.ITIMER_REAL,0)
        signal.signal(signal.SIGALRM,prior)


@pytest.mark.unit
def test_nested_json_credential_encoding_is_scanned_before_publication():
    import json
    assert scan_content(json.dumps({"payload":json.dumps({"password":"RAW_SYNTHETIC_SECRET"})}))
    assert scan_content('{"pass\\u0077ord":"RAW_SYNTHETIC_SECRET"}')
