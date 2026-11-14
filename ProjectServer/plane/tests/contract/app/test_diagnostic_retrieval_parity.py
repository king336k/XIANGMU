"""Same authorized evidence gets relevance ranking without conflating access policies."""

import json
from types import SimpleNamespace

import pytest

from plane.knowledge import diagnostic_retrieval
from plane.quality.diagnostic_materials import diagnostic_search_query

pytestmark = [pytest.mark.contract]


def revision(identity, title, content, tags=None):
    return SimpleNamespace(id=identity, title=title, content=content, tags=tags or [])


def test_warn_stop_and_audit_keys_replace_generic_report_noise():
    query = diagnostic_search_query(
        "generic title template",
        [
            {
                "excerpt": (
                    "WARN simulated=true stop_response HTTP=200 ok=true forced=true warning=backend_stop_failed\n"
                    "INFO simulated=true audit capture_aborted=false phase=IDLE\n"
                )
            }
        ],
    )
    assert "backend_stop_failed" in query and "capture_aborted" in query and "forced" in query
    assert "generic" not in query and "IDLE" not in query and "200" not in query


def test_warn_mcap_accounting_and_filter_keys_retain_mechanism():
    query = diagnostic_search_query(
        "generic title template",
        [
            {
                "excerpt": (
                    "WARN simulated=true MCAP queue full\n"
                    "INFO received=100 queued=90 written=90 queue_drops=10 write_errors=0\n"
                    "WARN simulated=true IMAGE_TIMESTAMP_FILTER_DROP count=5\n"
                )
            }
        ],
    )
    assert {"received", "queued", "written", "queue_drops", "write_errors", "IMAGE_TIMESTAMP_FILTER_DROP"} <= set(
        query.split()
    )
    assert all(value not in query.split() for value in ["100", "90", "10", "5", "generic"])


def test_warn_mechanism_preserves_error_and_preflight_priority():
    source = {"excerpt": "RuntimeError: blocked\nWARN warning=backend_stop_failed\nINFO queue_drops=10"}
    assert diagnostic_search_query("generic", [source]) == "RuntimeError"
    query = diagnostic_search_query(
        "generic",
        [
            {
                "excerpt": json.dumps(
                    {
                        "record_preflight": {
                            "code": "record_topic_health_failed",
                            "diagnosis": {"results": [{"ok": False, "code": "topic_missing"}]},
                        }
                    }
                )
                + "\nWARN queue_drops=10"
            }
        ],
    )
    assert "topic_missing" in query and "queue_drops" not in query


def test_sensitive_and_unrecognized_normal_warning_do_not_leak_or_fabricate_mechanism():
    assert diagnostic_search_query("generic", [{"excerpt": "WARN queue_drops=10 password=private-marker"}]) == "generic"
    assert (
        diagnostic_search_query("generic", [{"excerpt": "WARN arbitrary_field=private-marker message=ready"}])
        == "generic"
    )
    query = diagnostic_search_query("generic", [{"excerpt": "WARN queue_drops=private-marker"}])
    assert query == "queue_drops" and "private" not in query


def test_pure_ranker_replaces_first_five_and_keeps_non_daq_publications():
    rows = [revision(f"noise-{n}", "已发布运行说明", "一般部署事项") for n in range(5)]
    target = revision("target", "权限恢复契约", "recovery_contract 对照当前发布，不自动提权", ["platform"])
    rows.append(target)
    assert target not in rows[:5], "Fixture reproduces first-five candidate starvation"
    rank = diagnostic_retrieval.rank_diagnostic_rows
    assert rank(rows, "recovery_contract") == [target]
    assert "daq-diagnostic-approved" not in target.tags


def test_pure_ranker_exact_signature_and_stable_id_order_match_approved_contract():
    exact = revision("z", "证据契约", "backend_stop_failed")
    substring = revision("a", "backend_stop_failed_extra", "backend_stop_failed_extra")
    tie1 = revision("one", "队列", "queue_drops")
    tie2 = revision("two", "队列", "queue_drops")
    rank = diagnostic_retrieval.rank_diagnostic_rows
    assert rank([substring, exact], "backend_stop_failed")[0] is exact
    assert rank([tie2, tie1], "queue_drops") == [tie1, tie2]
    assert rank([exact], "backend_stop_failed", 0) == []
    assert len(rank([exact] * 10, "backend_stop_failed", 99)) <= 5


def test_ranker_consumes_one_pass_generator_and_zero_limit_reads_nothing():
    rank = diagnostic_retrieval.rank_diagnostic_rows
    seen = []

    def values():
        for n in range(10000):
            seen.append(n)
            yield revision(f"{n:05d}", "运行说明", "queue_drops" if n >= 9995 else "普通内容")

    result = rank(values(), "queue_drops")
    assert [row.id for row in result] == ["09995", "09996", "09997", "09998", "09999"]
    assert seen == list(range(10000))
    seen.clear()
    assert rank(values(), "queue_drops", 0) == [] and not seen


def test_nonmechanism_warning_values_are_not_copied_into_query():
    assert diagnostic_search_query("generic", [{"excerpt": "WARN warning=ready message=normal"}]) == "generic"
