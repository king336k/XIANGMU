"""INFO mechanism field names survive retrieval without forwarding raw values."""

import json

import pytest

from plane.quality.diagnostic_materials import diagnostic_search_query

pytestmark = [pytest.mark.contract]


def test_message_type_observation_keys_replace_generic_query_without_values():
    excerpt = (
        "SIMULATED INFO topic_alias=fixture_input publisher_type=teleop_interface_msgs/msg/TeleopFloat64Array\n"
        "SIMULATED INFO topic_alias=fixture_input monitor_config_type=sensor_msgs/msg/JointState callback_received=0\n"
        "SIMULATED INFO source_publisher_counter_advancing=true network_loss_measured=false"
    )
    query = diagnostic_search_query("generic", [{"excerpt": excerpt}])
    assert set(query.split()) == {
        "publisher_type",
        "monitor_config_type",
        "callback_received",
        "监控",
        "订阅",
        "消息类型",
        "QoS",
    }
    assert "TeleopFloat64Array" not in query and "JointState" not in query and "0" not in query


def test_upload_restart_state_keys_are_retained_without_status_values():
    excerpt = (
        "INFO persisted_status=UPLOADING service_restart=planned manualPaused=false\n"
        "INFO restored_status=INTERRUPTED speed=0 pauseReason=服务重启，等待断点续传\n"
        "INFO final_complete_response=not_observed"
    )
    query = diagnostic_search_query("generic", [{"excerpt": excerpt}])
    assert set(query.split()) == {
        "persisted_status",
        "manualPaused",
        "restored_status",
        "pauseReason",
        "final_complete_response",
        "上传",
        "续传",
        "分片",
    }
    for value in ["UPLOADING", "planned", "false", "INTERRUPTED", "speed=0", "服务重启", "断点续传", "not_observed"]:
        assert value not in query


def test_fixed_monitor_keys_keep_error_and_preflight_priority():
    error = {"excerpt": "ERROR RuntimeError: source failed\nINFO callback_received=0"}
    assert diagnostic_search_query("generic", [error]) == "RuntimeError"
    preflight = {
        "excerpt": json.dumps(
            {"record_preflight": {"code": "record_topic_health_failed", "diagnosis": {"results": []}}}
        )
        + "\nINFO restored_status=INTERRUPTED"
    }
    assert diagnostic_search_query("generic", [preflight]) == "record_topic_health_failed"


def test_fixed_monitor_keys_are_discarded_on_sensitive_lines():
    excerpt = "INFO persisted_status=UPLOADING password=do-not-leak\nINFO callback_received=private-account"
    query = diagnostic_search_query("generic", [{"excerpt": excerpt}])
    assert query == "callback_received"
    assert "password" not in query and "private-account" not in query and "UPLOADING" not in query


def test_same_file_message_type_tuple_adds_only_fixed_contract_aliases():
    excerpt = (
        "INFO topic_alias=input publisher_type=TeleopArray\nINFO monitor_config_type=JointState callback_received=0"
    )
    query = diagnostic_search_query("neutral", [{"excerpt": excerpt}])
    assert set(query.split()) == {
        "publisher_type",
        "monitor_config_type",
        "callback_received",
        "监控",
        "订阅",
        "消息类型",
        "QoS",
    }
    assert "TeleopArray" not in query and "JointState" not in query and "0" not in query


def test_upload_continuation_alias_requires_complete_same_file_state_tuple():
    excerpt = (
        "INFO persisted_status=UPLOADING service_restart=planned manualPaused=false\n"
        "INFO restored_status=INTERRUPTED speed=0 pauseReason=service_restart\n"
        "INFO final_complete_response=not_observed"
    )
    query = diagnostic_search_query("neutral", [{"excerpt": excerpt}])
    assert {"上传", "续传", "分片"} <= set(query.split())
    assert all(value not in query for value in ["UPLOADING", "INTERRUPTED", "service_restart", "false", "not_observed"])


def test_incomplete_or_cross_file_upload_states_do_not_add_contract_aliases():
    incomplete = "INFO persisted_status=UPLOADING restored_status=INTERRUPTED"
    pieces = [
        {"excerpt": "INFO persisted_status=UPLOADING"},
        {"excerpt": "INFO restored_status=INTERRUPTED final_complete_response=not_observed"},
    ]
    assert not {"上传", "续传", "分片"} & set(diagnostic_search_query("neutral", [{"excerpt": incomplete}]).split())
    assert not {"上传", "续传", "分片"} & set(diagnostic_search_query("neutral", pieces).split())


def test_sensitive_lines_do_not_block_a_separate_valid_contract_observation():
    excerpt = (
        "INFO publisher_type=TeleopArray monitor_config_type=JointState callback_received=0 password=secret\n"
        "INFO publisher_type=TeleopArray monitor_config_type=JointState callback_received=0"
    )
    query = diagnostic_search_query("neutral", [{"excerpt": excerpt}])
    assert {"监控", "订阅", "消息类型", "QoS"} <= set(query.split())
    assert "secret" not in query and "TeleopArray" not in query


def test_aliases_do_not_join_attachments_or_infer_from_normal_states():
    pieces = [
        {"excerpt": "INFO publisher_type=TeleopArray"},
        {"excerpt": "INFO monitor_config_type=JointState callback_received=0"},
    ]
    assert not {"监控", "订阅", "消息类型", "QoS"} & set(diagnostic_search_query("neutral", pieces).split())
    normal = "INFO persisted_status=SUCCESS restored_status=SUCCESS final_complete_response=not_observed"
    assert not {"上传", "续传", "分片"} & set(diagnostic_search_query("neutral", [{"excerpt": normal}]).split())
    sensitive = "INFO publisher_type=TeleopArray monitor_config_type=JointState callback_received=0 password=private"
    assert diagnostic_search_query("neutral", [{"excerpt": sensitive}]) == "neutral"


def test_regular_info_and_deep_unstructured_text_keep_fallback():
    assert (
        diagnostic_search_query("说明", [{"excerpt": 'INFO message=ready source=example arbitrary="private"'}])
        == "说明"
    )
    nested = "[" * 2500 + "unstructured-private-value" + "]" * 2500
    assert diagnostic_search_query("说明", [{"excerpt": nested}]) == "说明"


def test_later_nonmatching_upload_state_does_not_reuse_earlier_continuation_tuple():
    excerpt = (
        "INFO persisted_status=UPLOADING restored_status=INTERRUPTED final_complete_response=not_observed\n"
        "INFO restored_status=SUCCESS"
    )
    query = diagnostic_search_query("neutral", [{"excerpt": excerpt}])
    assert not {"上传", "续传", "分片"} & set(query.split())


def test_upload_fixed_enums_reject_status_prefixes_and_keep_json_delimiters():
    base = "persisted_status=UPLOADING restored_status=INTERRUPTED final_complete_response=not_observed"
    for original, changed in [
        ("UPLOADING", "UPLOADING-old"),
        ("INTERRUPTED", "INTERRUPTED-old"),
        ("not_observed", "not_observed-more"),
    ]:
        query = diagnostic_search_query("neutral", [{"excerpt": "INFO " + base.replace(original, changed)}])
        assert not {"上传", "续传", "分片"} & set(query.split()), changed
        later = diagnostic_search_query(
            "neutral", [{"excerpt": "INFO " + base + "\nINFO " + base.replace(original, changed)}]
        )
        assert not {"上传", "续传", "分片"} & set(later.split()), ("later", changed)
    valid = '{"persisted_status":"UPLOADING","restored_status":"INTERRUPTED","final_complete_response":"not_observed"}'
    assert {"上传", "续传", "分片"} <= set(diagnostic_search_query("neutral", [{"excerpt": valid}]).split())


def test_mode_switch_current_action_and_requested_mode_retrieve_only_contract_context():
    excerpt = "INFO current_action=hand requested_input_mode=controller\nWARN switch_response HTTP=409"
    query = diagnostic_search_query("neutral", [{"excerpt": excerpt}])
    assert {"current_action", "requested_input_mode", "模式切换", "接口", "状态"} <= set(query.split())
    assert "hand" not in query and "controller" not in query and "409" not in query
    assert "模式切换" not in diagnostic_search_query("neutral", [{"excerpt": "INFO current_action=hand"}])
    assert "模式切换" not in diagnostic_search_query(
        "neutral", [{"excerpt": "INFO current_action=hand"}, {"excerpt": "INFO requested_input_mode=controller"}]
    )
    sensitive = "INFO current_action=hand requested_input_mode=controller password=private"
    assert diagnostic_search_query("neutral", [{"excerpt": sensitive}]) == "neutral"
