import io


def test_full_large_log_is_scanned_and_middle_tail_errors_reach_model_material():
    from plane.quality.log_evidence import collect

    raw = (
        b"INFO stable recording\n" * 80000
        + b"ERROR camera subscription failed E-CAMERA-731\n"
        + b"INFO regular sample\n" * 80000
        + b"ERROR recorder stopped E-DISK-992\n"
    )
    sample, scanned, truncated = collect(io.BytesIO(raw), len(raw))
    assert b"E-CAMERA-731" in sample and b"E-DISK-992" in sample
    assert scanned == len(raw) and truncated is False
    assert len(sample) <= 256 * 1024


def test_log_context_keeps_lines_before_and_after_the_error():
    from plane.quality.log_evidence import collect

    raw = b"INFO device=unit7\nERROR camera timeout\nINFO recovered transport\n"
    sample, scanned, truncated = collect(io.BytesIO(raw), len(raw))
    assert b"device=unit7" in sample and b"recovered transport" in sample


def test_model_summary_keeps_error_after_verbose_header_with_bounded_context():
    from plane.quality.log_evidence import summarize

    text = "INFO startup healthy\n" * 3000 + "ERROR connection refused target=127.0.0.1:65123\n" + "INFO idle\n" * 3000
    result = summarize(text, 8000)
    assert "target=127.0.0.1:65123" in result
    assert len(result) <= 8000


def test_small_model_summary_keeps_complete_unicode_text():
    from plane.quality.log_evidence import summarize

    text = "设备启动正常\nERROR 录制失败\n"
    assert summarize(text, 8000) == text


def test_single_long_json_log_line_keeps_fault_beyond_first_four_kilobytes():
    from plane.quality.log_evidence import collect

    raw = b"x" * 12000 + b" ERROR disk full E-DISK-410 " + b"x" * (300 * 1024)
    sample, scanned, incomplete = collect(io.BytesIO(raw), len(raw))
    assert scanned == len(raw) and not incomplete
    assert b"E-DISK-410" in sample


def test_summary_repeated_warnings_cannot_hide_the_only_root_error():
    from plane.quality.log_evidence import summarize

    text = (
        "WARNING periodic heartbeat\n" * 10000
        + "ERROR connection refused target=127.0.0.1:65123\n"
        + "WARNING periodic heartbeat\n" * 10000
    )
    result = summarize(text, 8000)
    assert "target=127.0.0.1:65123" in result
    assert len(result) <= 8000


def test_warning_flood_after_fault_does_not_discard_fault_from_scanned_evidence():
    from plane.quality.log_evidence import collect

    raw = b"INFO setup\n" * 1000 + b"ERROR connection refused E-NET-917\n" + b"WARNING periodic heartbeat\n" * 40000
    sample, scanned, incomplete = collect(io.BytesIO(raw), len(raw))
    assert b"E-NET-917" in sample
    assert scanned == len(raw) and not incomplete


def test_dense_fault_windows_never_evict_final_fault_from_bounded_sample():
    from plane.quality.log_evidence import collect

    raw = (b"ERROR noise " + b"x" * 4000 + b"\n") * 100 + b"2026-11-09T05:06:07Z ERROR E-FULL-TAIL connection refused\n"
    sample, scanned, incomplete = collect(io.BytesIO(raw), len(raw))
    assert scanned == len(raw) and not incomplete
    assert len(sample) <= 256 * 1024
    assert b"E-FULL-TAIL" in sample


def test_long_final_line_preserves_fault_at_end_after_an_earlier_match():
    from plane.quality.log_evidence import collect

    raw = b"INFO padding\n" * 30000 + b"ERROR old " + b"x" * 40000 + b" ERROR E-FULL-TAIL connection refused\n"
    sample, scanned, incomplete = collect(io.BytesIO(raw), len(raw))
    assert scanned == len(raw) and not incomplete
    assert b"E-FULL-TAIL" in sample


def test_structured_record_preflight_keeps_timestamp_task_and_diagnosis_together():
    import json
    from plane.quality.log_evidence import summarize

    record = {
        "time": "2026-11-10T01:19:07Z",
        "level": "WARNING",
        "msg": "Recording preflight blocked",
        "record_preflight": {
            "code": "record_topic_health_failed",
            "mode": "ros2_full",
            "task_id": 4,
            "diagnosis": {
                "results": [
                    {
                        "topic": "/flow158/camera/color/compressed",
                        "code": "topic_missing",
                        "details": "采集节点未启动" * 400,
                    }
                ],
            },
        },
    }
    text = (
        "ERROR historical initialization failure\n" * 200
        + json.dumps(record, ensure_ascii=False)
        + "\n"
        + "INFO healthy\n" * 300
    )
    excerpt = summarize(text)
    lines = [
        json.loads(line)
        for line in excerpt.splitlines()
        if line.startswith("{") and line.endswith("}") and "record_preflight" in line
    ]
    assert len(lines) == 1
    assert lines[0]["time"] == record["time"]
    assert lines[0]["record_preflight"]["task_id"] == 4
    assert lines[0]["record_preflight"]["diagnosis"]["results"][0]["code"] == "topic_missing"
    assert len(excerpt) <= 8000


def test_mixed_warning_and_later_fault_keep_both_context_and_true_fault_priority():
    from plane.quality.log_evidence import collect

    raw = (
        b"INFO normal\n" * 30000 + b"WARNING preliminary then ERROR E-FINAL-991 connection refused\n"
        + b"INFO regular\n" * 30000
    )
    sample, scanned, incomplete = collect(io.BytesIO(raw), len(raw))
    assert scanned == len(raw) and not incomplete
    assert b"WARNING preliminary then ERROR E-FINAL-991 connection refused" in sample
    assert len(sample) <= 256 * 1024


def test_trimming_a_long_normal_record_cannot_invent_error_or_warning_word_boundaries():
    from plane.quality.log_evidence import collect

    prefix = b"INFO normal\n" * 25000
    suffix = b"INFO after\n" * 4000
    for word, stem in [(b"errors", b"error"), (b"warnable", b"warn")]:
        record = b"n" * (4095 - len(stem)) + b" " + word + b" regular\n"
        raw = prefix + record + suffix
        sample, scanned, incomplete = collect(io.BytesIO(raw), len(raw))
        assert scanned == len(raw) and not incomplete
        context = sample.split(b"[fault context]\n", 1)[1].split(b"[log tail]\n", 1)[0]
        assert b"n" * 50 not in context


def test_combined_feedback_summary_preserves_latest_node_observation_and_its_time():
    import json
    from plane.quality.log_evidence import summarize

    lines = [json.dumps({"at": f"2026-11-11T00:{index:02}:00Z", "header_stamp": {"sec": 100 + index},
                         "parameters": {"use_sim_time": False}, "clock_publishers": 0}) for index in range(50)]
    latest = {"at": "2026-11-11T01:00:00Z", "header_stamp": {"sec": 0, "nanosec": 0},
              "parameters": {"use_sim_time": True}, "clock_publishers": 0}
    document = {"sourceSystem": "ENGRAM_TELEOP_DAQ", "eventId": "case", "reportedAt": "2026-11-11T01:00:03Z",
        "evidence": {"observations": {"teleop": {"source": "/api/launcher/feedback-context", "capturedAt": "2026-11-11T01:00:02Z",
          "data": {"observations": {"nodes": {"status": "available", "data": {"processes": [{"name": "source", "lines": [*lines, json.dumps(latest)]}]}}}}}},
          "unrelated": "x" * 20000}}
    result = summarize(json.dumps(document), 8000)
    parsed = [json.loads(line) for line in result.splitlines() if line.startswith('{') and line.endswith('}')]
    node = next(row for row in parsed if row.get("process") == "source")
    assert json.loads(node["latest_lines"][-1]) == latest
    assert node["source"] == "/api/launcher/feedback-context"
    assert node["captured_at"] == "2026-11-11T01:00:02Z"
    assert node["omitted_earlier_lines"] == 45
    assert len(result) <= 8000


def test_native_audit_preflight_summary_keeps_outer_time_with_nested_diagnosis():
    import json
    from plane.quality.log_evidence import summarize

    event = {"time": "2026-11-11T01:00:00Z", "action": "record.preflight", "result": "failure",
             "detail": {"record_preflight": {"task_id": 7, "code": "record_topic_health_failed",
               "diagnosis": {"results": [{"topic": "/camera", "code": "topic_header_timestamp_invalid", "message_count": 76}]}}}}
    text = "WARNING historical noise\n" * 300 + json.dumps(event) + "\n" + "INFO normal\n" * 400
    result = summarize(text, 8000)
    records = [json.loads(line) for line in result.splitlines() if line.startswith('{') and line.endswith('}')]
    assert event in records


def test_combined_version_snapshot_is_retained_as_structured_evidence_with_provenance():
    import json
    from plane.quality.log_evidence import summarize

    snapshot = {"schemaVersion": 1, "eventId": "case-version", "capturedAt": "2026-11-11T01:00:03Z",
                "source": "combined_client_info", "components": [{"key": "project", "status": "available",
                "version": "v3", "commit": "abc123", "branch": "develop_v2", "password": "never-copy"}]}
    document = {"sourceSystem": "ENGRAM_TELEOP_DAQ", "eventId": "case-version", "deploymentSnapshot": snapshot,
                "evidence": {"observations": {}}, "noise": "x" * 20000}
    result = summarize(json.dumps(document), 8000)
    records = [json.loads(line) for line in result.splitlines() if line.startswith('{') and line.endswith('}')]
    version = next(row for row in records if row.get("observation") == "deploymentSnapshot")
    assert version["event_id"] == "case-version"
    assert version["captured_at"] == snapshot["capturedAt"]
    assert version["components"][0]["commit"] == "abc123"
    assert "password" not in version["components"][0]
    assert len(result) <= 8000


def test_combined_node_summary_retains_observations_before_the_last_three_lines():
    import json
    from plane.quality.log_evidence import feedback_observations

    lines = [json.dumps({"at": f"2026-11-11T01:00:{i:02d}Z", "parameters": {"clock": i >= 3}}) for i in range(12)]
    document = {"sourceSystem": "ENGRAM_TELEOP_DAQ", "evidence": {"observations": {"teleop": {"data": {
        "observations": {"nodes": {"data": {"processes": [{"name": "source", "lines": lines}]}}}}}}}}
    rows = [json.loads(row) for row in feedback_observations(json.dumps(document), 4000)]
    node = next(row for row in rows if row.get("process") == "source")
    assert node["latest_lines"] == lines[-3:]
    assert any(json.loads(line)["at"] < "2026-11-11T01:00:09Z" for line in node["preceding_lines"])


def test_combined_preview_handles_malformed_optional_evidence_without_crashing():
    import json
    from plane.quality.log_evidence import summarize

    for evidence in (None, [], {"observations": None}, {"observations": {"teleop": {"data": {
        "observations": {"nodes": {"data": None}}
    }}}}):
        document = {"sourceSystem": "ENGRAM_TELEOP_DAQ", "evidence": evidence, "large": "x" * 20000}
        assert len(summarize(json.dumps(document), 8000)) <= 8000


def test_resummarizing_multiple_attachments_keeps_version_and_producer_rows_atomic():
    import json
    from plane.quality.log_evidence import summarize

    producer = {"observation": "teleop", "source": "/api/launcher/feedback-context",
                "captured_at": "2026-11-11T01:00:05Z", "process": "camera_source",
                "latest_lines": [json.dumps({"at": "2026-11-11T01:00:03Z", "parameters": {
                    "camera_topic": "/renamed/image", "image_qos": "reliable"}, "normal": "x" * 550})] * 3}
    version = {"observation": "deploymentSnapshot", "captured_at": "2026-11-11T01:00:05Z",
               "components": [{"key": f"part-{i}", "commit": "a" * 40, "source": "/path/" + "x" * 120, "status": "available"} for i in range(6)]}
    preflight = {"time": "2026-11-11T01:00:02Z", "action": "record.preflight",
                 "detail": {"record_preflight": {"code": "topic_not_discovered", "task_id": 6}}}
    text = "[FILE-1]\n" + json.dumps(version) + "\n" + json.dumps(producer) + "\n"
    text += "".join(f"ERROR unrelated module {i} " + "diagnostic context " * 30 + "\n" for i in range(150))
    text += json.dumps(preflight) + "\n" + "INFO normal\n" * 500
    result = summarize(text, 12000)
    records = [json.loads(line) for line in result.splitlines() if line.startswith('{') and line.endswith('}')]
    assert producer in records
    assert version in records
    assert preflight in records
    assert len(result) <= 12000


def test_invalid_optional_observations_do_not_erase_valid_root_version_snapshot():
    import json
    from plane.quality.log_evidence import feedback_observations

    snapshot = {"capturedAt": "time", "components": [{"key": "project", "version": "v1"}]}
    rows = feedback_observations(json.dumps({"sourceSystem": "ENGRAM_TELEOP_DAQ", "deploymentSnapshot": snapshot,
                                            "evidence": {"observations": None}}), 4000)
    assert any(json.loads(row).get("observation") == "deploymentSnapshot" for row in rows)


def test_latest_preflight_is_prioritized_instead_of_falling_back_to_smaller_old_event():
    import json
    from plane.quality.log_evidence import summarize

    producer = {"observation": "teleop", "process": "camera", "latest_lines": ["x" * 2300]}
    version = {"observation": "deploymentSnapshot", "components": [{"key": "part", "version": "v" * 2200}]}
    old = {"time": "old", "record_preflight": {"code": "old_failure"}}
    latest = {"time": "latest", "record_preflight": {"code": "latest_failure", "detail": "x" * 6000}}
    text = "\n".join(map(json.dumps, [version, producer, old, latest])) + "\n" + "noise\n" * 3000
    short = summarize(text, 12000)
    records = []
    for line in short.splitlines():
        try: records.append(json.loads(line))
        except ValueError: pass
    assert latest in records
    assert version in records
    assert producer in records
    assert old not in records
    assert len(short) <= 12000


def test_feedback_summary_retains_dirty_and_source_identity():
    import json
    from plane.quality.log_evidence import feedback_observations

    identity = {"dirty": True, "sourceSnapshotSha256": "a" * 64, "sourceFileCount": 321}
    document = {"sourceSystem": "ENGRAM_TELEOP_DAQ", "deploymentSnapshot": {
        "components": [{"key": "daq", "version": "v1", **identity}]
    }}
    rows = feedback_observations(json.dumps(document), 4000)
    row = next(json.loads(item) for item in rows if json.loads(item).get("observation") == "deploymentSnapshot")
    assert all(row["components"][0][key] == value for key, value in identity.items())
