"""Severity suggestions require current verified incident evidence, never model wording alone."""

import hashlib
from uuid import uuid4

import pytest

from plane.quality.models import Defect, DiagnosticJob, PackageFile, ProblemPackage
from plane.db.models import Project

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def incident(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="严重程度", identifier="SEVERITY")

    def make(text, severity="major", quote=None):
        defect = Defect.objects.create(project=project, created_by=create_user, title="普通反馈")
        package = ProblemPackage.objects.create(
            project=project,
            created_by=create_user,
            defect=defect,
            name="材料",
            status="files_verified",
            source_system="test",
            external_id=str(uuid4()),
        )
        file = PackageFile.objects.create(
            project=project,
            created_by=create_user,
            package=package,
            name="incident.log",
            storage_key=uuid4().hex,
            size=len(text.encode()),
            sha256=hashlib.sha256(text.encode()).hexdigest(),
        )
        reference = f"FILE-{file.id}"
        result = {
            "input": {"files": [str(file.id)]},
            "sources": [
                {
                    "file_id": str(file.id),
                    "sha256": file.sha256,
                    "excerpt": text,
                    "read_bytes": file.size,
                    "scanned_bytes": file.size,
                    "file_bytes": file.size,
                    "scan_incomplete": False,
                }
            ],
            "citations": [{"reference": reference}],
            "severity_assessment": {
                "severity": severity,
                "basis": "当前材料中的直接影响证据。",
                "evidence": [{"reference": reference, "quote": quote or text}],
            },
        }
        job = DiagnosticJob.objects.create(
            project=project,
            created_by=create_user,
            defect=defect,
            request_id=uuid4(),
            mode="manual",
            status="completed",
            result=result,
        )
        return job, result, file

    return make


def assess(job, result):
    # Dynamic import keeps RED as an assertion about missing behavior, not collection failure.
    import importlib.util

    assert importlib.util.find_spec("plane.quality.diagnostic_severity"), "Verified severity proposal helper is missing"
    from plane.quality.diagnostic_severity import propose

    return propose(job, result)


@pytest.mark.parametrize(
    "text,requested,expected",
    [
        ("ERROR recording_start_failed core_capture_blocked=true", "major", "major"),
        ("ERROR failure_class=raw_failed raw_status=failed", "major", "major"),
        ("WARN MCAP queue full queue_drops=12", "major", "major"),
        ('{"status":"failed","failure_class":"raw_failed","raw_status":"failed"}', "major", "major"),
        ("ERROR record_preflight status=blocked code=topic_type_mismatch", "major", "major"),
        ("ERROR MCAP write failed: input/output error", "major", "major"),
        ("ERROR Error in dual hand retargeting loop", "minor", "minor"),
        ("WARN [pico_video] media failure stage=decode_wait", "minor", "minor"),
        ("ERROR DAQ_MCAP_STORAGE_PRESET must be auto, none, zstd_fast, or zstd_small", "minor", "minor"),
        ("ERROR MCAP message limit requires max_cache_size=0 and snapshot_mode=false", "minor", "minor"),
        ("ERROR RECORDING_DURABILITY_FAILED", "minor", "minor"),
        ("ERROR Invalid camera stream geometry or frame rate", "minor", "minor"),
        ("ERROR raw accounting missing/invalid counter", "minor", ""),
        ("ERROR CaptureService raw accounting missing/invalid counter: written", "major", "major"),
        ("ERROR MCAP metadata message count conflicts with CaptureService write accounting", "major", "major"),
        ("ERROR recording primary routes exceed encoder capacity", "major", "major"),
        ("WARN [VR_INPUT_MODE_CONFLICT] selected_mode=hand pico_input=controller", "minor", "minor"),
        ("INFO [VR_INPUT_MODE_CONFLICT_CLEARED] selected_mode=hand pico_input=hand", "trivial", "trivial"),
        ("ERROR 已确认原始数据不可恢复丢失", "critical", "critical"),
        ("ERROR 当前事件经现场确认设备损坏并危及人员安全", "critical", "critical"),
        ("WARN [VR_RAW_HAND_INVALID] hand=left status=missing_joint_locations", "minor", "minor"),
        ("WARN route=needs_rebuild failure_reason=packet_timeline_failed", "minor", "minor"),
        ("INFO 显示文字轻微错位，采集功能正常", "trivial", "trivial"),
        ("INFO [VR_RAW_HAND_RECOVERED] hand=left", "trivial", "trivial"),
        ("INFO state=idle frequency_check=paused", "trivial", "trivial"),
        ("ERROR arbitrary failure", "major", ""),
        ("INFO no errors", "major", ""),
        ("INFO record_preflight status=passed code=topic_type_mismatch", "major", ""),
        ("INFO raw_status=finalized derived_status=pending", "major", ""),
        ("ERROR connection refused", "critical", ""),
        ("INFO 不存在不可恢复数据丢失", "critical", ""),
        ("WARN 可能危及人员安全，尚未确认", "critical", ""),
        ("ERROR simulated=true 已确认原始数据不可恢复丢失", "critical", "major"),
        ("ERROR failure_class=raw_failed\nINFO [VR_RAW_HAND_RECOVERED] hand=left", "trivial", ""),
        ('{"status":"ok","message":"ERROR raw_status=failed"}', "major", ""),
        ('{"status":"ok","history":{"raw_status":"failed"}}', "major", ""),
        ('{"status":"ok","raw_status":"failed","failure_class":"raw_failed"}', "trivial", ""),
        ('{"status":"ok","raw_status":"failed","failure_class":"raw_failed"}', "major", "major"),
        ('{"status":"ok","routes":[{"status":"failed","failure_reason":"packet_timeline_failed"}]}', "trivial", ""),
        ('{"status":"ok","routes":[{"status":"failed","failure_reason":"packet_timeline_failed"}]}', "minor", "minor"),
        ('{"status":"failed","history":{"raw_status":"failed"}}', "major", ""),
        ("INFO 已确认未危及人员安全", "critical", ""),
        ("INFO 已确认无设备损坏", "critical", ""),
        ("INFO 文档引用：“已确认原始数据不可恢复丢失”", "critical", ""),
        ("INFO irrecoverable_data_loss=true", "critical", ""),
        ("INFO simulated=false 已确认原始数据不可恢复丢失", "critical", "critical"),
        ("ERROR incident=x 已确认原始数据不可恢复丢失\nINFO incident=x 复核确认原始数据完整且可恢复", "critical", ""),
    ],
)
def test_evidence_sets_severity_bounds(incident, text, requested, expected):
    job, result, _ = incident(text, requested)
    got = assess(job, result)
    assert got["severity"] == expected
    assert got["basis"]
    if expected:
        assert got["evidence"][0]["reference"].startswith("FILE-")


@pytest.mark.parametrize(
    "invalid",
    [
        "missing",
        "unknown",
        "empty_reason",
        "no_quote",
        "invented_quote",
        "knowledge",
        "description",
        "uncited",
        "foreign_file",
        "foreign_input",
        "bad_hash",
        "zero_read",
        "incomplete",
        "incomplete_package",
        "failed_job",
        "wrong_project",
        "duplicate_source",
        "sensitive_reason",
        "long_quote",
        "malformed_sources",
        "malformed_evidence",
        "malformed_citation",
        "mismatched_bytes",
        "source_sensitive",
        "archive_path",
    ],
)
def test_invalid_or_unverifiable_model_suggestion_stays_pending(incident, invalid):
    job, result, file = incident("ERROR failure_class=raw_failed raw_status=failed")
    suggestion = result["severity_assessment"]
    if invalid == "missing":
        result.pop("severity_assessment")
    elif invalid == "unknown":
        suggestion["severity"] = "catastrophic"
    elif invalid == "empty_reason":
        suggestion["basis"] = " "
    elif invalid == "no_quote":
        suggestion["evidence"][0].pop("quote")
    elif invalid == "invented_quote":
        suggestion["evidence"][0]["quote"] = "ERROR recording_start_failed"
    elif invalid in {"knowledge", "description"}:
        suggestion["evidence"][0]["reference"] = "KN-reference" if invalid == "knowledge" else "DESCRIPTION"
        result["citations"] = [suggestion["evidence"][0]]
    elif invalid == "uncited":
        result["citations"] = []
    elif invalid == "foreign_file":
        result["sources"][0]["file_id"] = str(uuid4())
    elif invalid == "foreign_input":
        result["input"]["files"] = [str(uuid4())]
    elif invalid == "bad_hash":
        result["sources"][0]["sha256"] = "a" * 64
    elif invalid == "zero_read":
        result["sources"][0]["read_bytes"] = 0
    elif invalid == "incomplete":
        result["sources"][0]["scan_incomplete"] = True
    elif invalid == "incomplete_package":
        file.package.status = "uploading"
        file.package.save(update_fields=["status"])
    elif invalid == "failed_job":
        job.status = "failed"
    elif invalid == "wrong_project":
        job.project_id = uuid4()
    elif invalid == "duplicate_source":
        result["sources"].append(dict(result["sources"][0]))
    elif invalid == "sensitive_reason":
        suggestion["basis"] = "password=unsafe-example"
    elif invalid == "long_quote":
        suggestion["evidence"][0]["quote"] = "x" * 1601
    elif invalid == "malformed_sources":
        result["sources"] = [None]
    elif invalid == "malformed_evidence":
        suggestion["evidence"] = [None]
    elif invalid == "malformed_citation":
        result["citations"] = [{"reference": []}]
    elif invalid == "mismatched_bytes":
        result["sources"][0]["scanned_bytes"] = 1
    elif invalid == "source_sensitive":
        result["sources"][0]["excerpt"] += "\npassword=unsafe-example"
    elif invalid == "archive_path":
        result["sources"][0]["archive_entry"] = "../../outside.log"
    assert assess(job, result)["severity"] == ""


def test_model_answer_title_and_knowledge_cannot_establish_severity(incident):
    job, result, _ = incident("ERROR generic issue", "major")
    job.defect.title = "不可恢复丢失且无法启动"
    result["answer"] = "已确认原始数据不可恢复丢失"
    result["knowledge"] = [{"content": "raw_status=failed"}]
    assert assess(job, result)["severity"] == ""


def test_quote_selection_cannot_hide_active_major_impact(incident):
    job, result, _ = incident(
        "ERROR raw_status=failed\nINFO [VR_RAW_HAND_RECOVERED] hand=left",
        "trivial",
        quote="INFO [VR_RAW_HAND_RECOVERED] hand=left",
    )
    assert assess(job, result)["severity"] == ""


def test_proposal_has_no_mutation_side_effect(incident):
    job, result, _ = incident("ERROR raw_status=failed")
    before = (job.defect.severity, job.defect.edit_version, job.defect.events.count())
    assert assess(job, result)["severity"] == "major"
    job.defect.refresh_from_db()
    assert (job.defect.severity, job.defect.edit_version, job.defect.events.count()) == before


def test_archive_entry_is_scoped_by_exact_reference(incident):
    job, result, _ = incident("ERROR raw_status=failed")
    result["sources"][0]["archive_entry"] = "logs/incident.log"
    reference = result["citations"][0]["reference"] + ":logs/incident.log"
    result["citations"] = [{"reference": reference}]
    result["severity_assessment"]["evidence"][0]["reference"] = reference
    assert assess(job, result)["severity"] == "major"


def test_simulation_scope_in_current_input_caps_physical_critical_claim(incident):
    job, result, _ = incident("ERROR 已确认原始数据不可恢复丢失", "critical")
    result["input"]["description"] = "模拟压力验证，未运行真实设备。"
    assert assess(job, result)["severity"] == "major"


def test_excerpt_substring_cannot_remove_negation_context(incident):
    job, result, _ = incident("WARN 尚未确认已确认原始数据不可恢复丢失", "critical", quote="已确认原始数据不可恢复丢失")
    assert assess(job, result)["severity"] == ""


def test_each_quote_retains_its_own_proposition_not_another_matching_grade(incident):
    job, result, _ = incident(
        "INFO 尚未确认已确认原始数据不可恢复丢失\nERROR 已确认设备损坏",
        "critical",
        quote="已确认原始数据不可恢复丢失",
    )
    assert assess(job, result)["severity"] == ""


def test_recovery_contradiction_stays_pending_for_manual_scope_review(incident):
    job, result, _ = incident(
        "ERROR incident=x raw_status=failed\nINFO incident=x 复核确认原始数据完整且可恢复", "major"
    )
    assert assess(job, result)["severity"] == ""


def test_truncated_excerpt_never_implies_complete_incident_context(incident):
    job, result, _ = incident("ERROR 已确认原始数据不可恢复丢失", "critical")
    result["sources"][0]["preview_truncated"] = True
    assert assess(job, result)["severity"] == ""


def test_complete_material_context_preserves_negation_and_current_observations(incident):
    from plane.quality.diagnostic_severity import propose

    text = "WARN 尚未确认已确认原始数据不可恢复丢失"
    job, result, _ = incident(text, "critical", quote="已确认原始数据不可恢复丢失")
    result["sources"][0]["excerpt"] = "已确认原始数据不可恢复丢失"
    result["sources"][0]["preview_truncated"] = True
    reference = result["citations"][0]["reference"]
    assert propose(job, result, {reference: {"content": text, "truncated": False}})["severity"] == ""


def test_complete_material_can_support_a_quote_outside_stored_excerpt(incident):
    from plane.quality.diagnostic_severity import propose

    text = "INFO initial check\nERROR MCAP write failed: input/output error"
    job, result, _ = incident(text, "major", quote="ERROR MCAP write failed: input/output error")
    result["sources"][0]["excerpt"] = "INFO initial check"
    result["sources"][0]["preview_truncated"] = True
    reference = result["citations"][0]["reference"]
    got = propose(job, result, {reference: {"content": text, "truncated": False}})
    assert got["severity"] == "major"


@pytest.mark.parametrize(
    "line,severity,expected",
    [
        (
            "[FATAL] [pico_video]: failed to start: media encoder admission failed: "
            "encoder session request exceeds capacity",
            "major",
            "major",
        ),
        ("FATAL pico_video failed to start: media backend admission failed: MediaResourcesBusy", "major", "major"),
        (
            "FATAL failed to start: media encoder admission failed: selected media backend is unavailable",
            "major",
            "major",
        ),
        ("ERROR unrelated failed to start: encoder session request exceeds capacity", "major", ""),
        ("ERROR Pico signaling failed to start; camera relay remains active", "minor", "minor"),
        ("ERROR [pico_video] video session open failed: encoder session request exceeds capacity", "minor", "minor"),
        ("[pico_video] media failure stage=decode_wait error=timeout", "minor", "minor"),
    ],
)
def test_pico_process_start_failure_differs_from_local_media_failure(incident, line, severity, expected):
    job, result, _ = incident(line, severity)
    assert assess(job, result)["severity"] == expected


@pytest.mark.parametrize("path,expected", [("routes", "minor"), ("history", ""), ("examples", "")])
def test_bounded_complete_json_observation_quote_retains_its_current_path(incident, path, expected):
    import json

    observation = {"status": "failed", "failure_reason": "packet_timeline_failed"}
    quote = json.dumps(observation)
    text = json.dumps({"status": "ok", path: [observation], "padding": "x" * 1800})
    job, result, _ = incident(text, "minor", quote=quote)
    assert assess(job, result)["severity"] == expected


def test_json_sub_observation_cannot_borrow_a_different_path_with_matching_grade(incident):
    import json

    historical = {"status": "failed", "failure_reason": "packet_timeline_failed"}
    current = {"status": "failed", "failure_reason": "derived_failed"}
    text = json.dumps({"status": "ok", "history": [historical], "routes": [current]})
    job, result, _ = incident(text, "minor", quote=json.dumps(historical))
    assert assess(job, result)["severity"] == ""


def test_untrusted_observation_field_shapes_remain_pending_without_crashing(incident):
    job, result, _ = incident('{"raw_status": [], "failure_class": {"status":"raw_failed"}}', "major")
    assert assess(job, result)["severity"] == ""


@pytest.mark.parametrize("simulated,expected", [(False, "critical"), (True, "major")])
def test_json_simulation_boolean_preserves_explicit_false(incident, simulated, expected):
    import json

    text = json.dumps(
        {"synthetic": simulated, "status": "error", "message": "已确认原始数据不可恢复丢失"}, ensure_ascii=False
    )
    job, result, _ = incident(text, "critical")
    assert assess(job, result)["severity"] == expected


@pytest.mark.parametrize(
    "observation,severity,expected",
    [
        (["INFO [VR_RAW_HAND_RECOVERED] hand=left"], "trivial", "trivial"),
        ({"capture": "ERROR MCAP write failed: input/output error"}, "major", "major"),
        ([{"status": "failed", "raw_status": "failed"}], "major", "major"),
        ({"history": "ERROR raw_status=failed", "current": "INFO status=healthy"}, "trivial", "trivial"),
        (["INFO 可能已确认设备损坏"], "critical", ""),
        (["WARN 尚未确认采集失败"], "major", ""),
    ],
)
def test_human_observations_container_preserves_current_impact_not_history(incident, observation, severity, expected):
    import json

    text = json.dumps({"observations": observation}, ensure_ascii=False)
    job, result, _ = incident(text, severity)
    assert assess(job, result)["severity"] == expected


NORMAL_CONTEXTS = [
    "grant_age_sec=12 grant_expires_in_sec=10 same_actor=true same_task=true same_mode=true\n"
    "preflight_invocations=2 latest_preflight_ok=true\nrecording=true phase=RECORDING",
    "before_request recording=true phase=RECORDING session_alias=current\n"
    "ERROR code=record_already_active\nafter_request recording=true phase=RECORDING session_alias=current",
    "action=hand_only\nIK remains idle (retarget only)\nhand_qpos_counter_advancing=true arm_command_counter=0",
    "active_mode=hand\ningress_stamp_advancing=true\neach_conflict_span_below_configured_delay=true "
    "module_bit32=false module_bit33=false",
    "prior_controller_active=true consecutive_inactive_frames_below_debounce=true\n"
    "published_controller_active=true ingress_stamp_advancing=true",
    'channel_status=UNKNOWN message="waiting for first message"\n'
    "first_message_received=false subscribed_elapsed_below_grace=true confirmed_error_bit=false",
    'WARN channel_status=ERROR message="freq low (confirming 1/3)"\n'
    "next_channel_status=OK consecutive_error_cycles=0 module_error_bit=false",
]


@pytest.mark.parametrize("text", NORMAL_CONTEXTS)
def test_complete_normal_context_can_support_trivial_but_does_not_hide_raw_failure(incident, text):
    job, result, _ = incident(text, "trivial")
    assert assess(job, result)["severity"] == "trivial"
    job, result, _ = incident(text + "\nERROR MCAP write failed write_errors=1", "trivial")
    assert assess(job, result)["severity"] == ""


@pytest.mark.parametrize(
    "text",
    [
        "latest_preflight_ok=true",
        "module_bit32=false module_bit33=false",
        "consecutive_inactive_frames_below_debounce=true",
        "subscribed_elapsed_below_grace=true",
        "next_channel_status=OK",
        "hand_qpos_counter_advancing=true arm_command_counter=0",
    ],
)
def test_single_normal_marker_does_not_prove_normal_context(incident, text):
    job, result, _ = incident(text, "trivial")
    assert assess(job, result)["severity"] == ""


@pytest.mark.parametrize(
    "text",
    [
        '{"raw_status":{},"status":[]}',
        '{"observations":[null,1,false,{}]}',
        '{"data":' * 30 + '{"status":"failed","raw_status":"failed"}' + "}" * 30,
    ],
)
def test_malformed_and_deep_observations_are_bounded_pending(incident, text):
    job, result, _ = incident(text, "major")
    assert assess(job, result)["severity"] == ""


@pytest.mark.parametrize(
    "quoted,path,expected",
    [
        ("ERROR MCAP write failed write_errors=1", "observations", "major"),
        ("MCAP write failed write_errors=1", "observations", ""),
        ("ERROR MCAP write failed write_errors=1", "history", ""),
    ],
)
def test_complete_current_human_observation_string_quote_keeps_its_path(incident, quoted, path, expected):
    import json

    text = json.dumps({path: ["ERROR MCAP write failed write_errors=1"], "padding": "x" * 1800})
    job, result, _ = incident(text, "major", quote=quoted)
    assert assess(job, result)["severity"] == expected


def test_normal_combination_must_be_affirmed_not_merely_quoted_under_uncertainty(incident):
    text = (
        "WARN 尚未确认 hand_only IK remains idle (retarget only) hand_qpos_counter_advancing=true arm_command_counter=0"
    )
    job, result, _ = incident(text, "trivial")
    assert assess(job, result)["severity"] == ""


def test_repeat_protection_cannot_hide_an_independent_failure_on_its_line(incident):
    text = NORMAL_CONTEXTS[1].replace(
        "ERROR code=record_already_active", "ERROR code=record_already_active ERROR motor overheated"
    )
    job, result, _ = incident(text, "trivial")
    assert assess(job, result)["severity"] == ""


def test_complete_current_human_observations_array_quote_preserves_normal_combination(incident):
    import json

    items = NORMAL_CONTEXTS[4].splitlines()
    text = json.dumps({"observations": items, "padding": "x" * 1800})
    job, result, _ = incident(text, "trivial", quote=json.dumps(items))
    assert assess(job, result)["severity"] == "trivial"
