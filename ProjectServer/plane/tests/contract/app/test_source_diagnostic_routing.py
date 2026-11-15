import hashlib
import json
from uuid import uuid4
import pytest
from plane.quality.module_routing import evidence_modules
from plane.quality.models import PackageFile
from plane.tests.contract.app.test_module_owners import ready_job
from plane.tests.contract.app.test_module_owners import routing as routing

pytestmark = [pytest.mark.contract, pytest.mark.django_db]
MATRIX = [
    {
        "id": "teleop_ros_registration_missing_during_running_service",
        "line": (
            'SIMULATED ERROR HTTP=503 detail="ROS node not initialized"\n'
            "SIMULATED INFO expected_service_phase=running control_status_read=true node_registry_present=false\n"
            "SIMULATED INFO previous_exit_log=not_observed"
        ),
        "expected_modules": ["teleop"],
    },
    {
        "id": "generic_ros_http_503_without_control_evidence_stays_triage",
        "line": 'SIMULATED ERROR HTTP=503 detail="ROS node not initialized"',
        "expected_modules": [],
        "expected_routing": "triage",
    },
    {
        "id": "ros_registration_expected_start_is_not_teleop_evidence",
        "line": (
            'SIMULATED ERROR HTTP=503 detail="ROS node not initialized"\n'
            "SIMULATED INFO expected_service_phase=starting control_status_read=true node_registry_present=false"
        ),
        "expected_modules": [],
        "expected_routing": "triage",
    },
    {
        "id": "ros_registration_present_is_not_teleop_evidence",
        "line": (
            'SIMULATED ERROR HTTP=503 detail="ROS node not initialized"\n'
            "SIMULATED INFO expected_service_phase=running control_status_read=true node_registry_present=true"
        ),
        "expected_modules": [],
        "expected_routing": "triage",
    },
    {
        "id": "ros_registration_evidence_cannot_be_joined_across_sources",
        "source_lines": [
            'SIMULATED ERROR HTTP=503 detail="ROS node not initialized"',
            "SIMULATED INFO expected_service_phase=running control_status_read=true node_registry_present=false",
        ],
        "expected_modules": [],
        "expected_routing": "triage",
    },
    {
        "id": "teleop_media_main_admission_source",
        "line": "FATAL failed to start: media encoder admission failed: selected media backend is unavailable",
        "expected_modules": ["teleop"],
    },
    {
        "id": "generic_other_service_start_is_not_teleop",
        "line": "FATAL failed to start: unrelated fixture unavailable",
        "expected_modules": [],
    },
    {
        "id": "forced_stop_source_warning",
        "line": "WARN 录制已强制停止，本段数据可能不完整：fixture backend stop failure",
        "expected_modules": ["daq"],
    },
    {
        "id": "upload_deferred_source_message",
        "line": "ERROR UploadDeferred: 存储节点分片上传暂不可用，将自动重试：fixture unavailable",
        "expected_modules": ["daq"],
    },
    {
        "id": "generic_http_unavailable_is_not_daq_evidence",
        "line": "WARN HTTP 503 unavailable",
        "expected_modules": [],
    },
    {
        "id": "monitor_pending_confirmation_recovers",
        "line": (
            'WARN channel_status=ERROR message="freq low (confirming 1/3)"\n'
            "INFO next_channel_status=OK consecutive_error_cycles=0 module_error_bit=false"
        ),
        "description": "问题范围：遥操",
        "expected_modules": [],
    },
    {
        "id": "monitor_pending_confirmation_not_active_failure",
        "line": '[TopicMonitor] WARN channel_status=ERROR message="freq low (confirming 2/4)"',
        "description": "问题范围：遥操",
        "expected_modules": [],
    },
    {
        "id": "monitor_confirmed_failure",
        "line": 'ERROR channel_status=ERROR message="freq low (confirming 3/3)" module_error_bit=true',
        "description": "问题范围：遥操",
        "expected_modules": ["teleop"],
    },
    {
        "id": "monitor_pending_does_not_hide_separate_failure",
        "line": (
            'WARN channel_status=ERROR message="freq low (confirming 1/3)"\nERROR Error in dual hand retargeting loop'
        ),
        "description": "问题范围：遥操",
        "expected_modules": ["teleop"],
    },
    {
        "id": "monitor_confirmation_explicit_active_bit",
        "line": 'WARN channel_status=ERROR message="freq low (confirming 1/3)" module_error_bit=true',
        "description": "问题范围：遥操",
        "expected_modules": ["teleop"],
    },
    {
        "id": "topic_low",
        "line": "ERROR code=topic_rate_too_low actual_hz=12",
        "expected_modules": ["daq"],
        "reason": "Source-specific preflight blocked code",
    },
    {
        "id": "topic_header_json",
        "structured": {"status": "blocked", "code": "topic_header_timestamp_invalid"},
        "expected_modules": ["daq"],
    },
    {"id": "raw_failed", "line": "ERROR failure_class=raw_failed", "expected_modules": ["daq"]},
    {"id": "derived_failed", "line": "ERROR failure_class=derived_failed", "expected_modules": ["daq"]},
    {"id": "quota", "line": "ERROR metadata_storage_quota_exceeded", "expected_modules": ["daq"]},
    {
        "id": "camera_config",
        "line": (
            "ERROR operation=NativeCameraService::reload_cameras error=Invalid camera stream geometry or frame rate"
        ),
        "expected_modules": ["daq"],
    },
    {"id": "mcap_drop_warn", "line": "WARN MCAP queue full queue_drops=10", "expected_modules": ["daq"]},
    {
        "id": "vr_mode_warn",
        "line": "WARN [VR_INPUT_MODE_CONFLICT] selected_mode=hand pico_input=controller",
        "expected_modules": ["teleop"],
    },
    {
        "id": "vr_hand_warn",
        "line": "WARN [VR_RAW_HAND_INVALID] hand=left status=missing_joint_locations",
        "expected_modules": ["teleop"],
    },
    {
        "id": "pico_heartbeat_warn",
        "line": "WARN [PICO_HEARTBEAT] timeout tracking_recent=true diagnosis=heartbeat_timeout_while_tracking_active",
        "expected_modules": ["teleop"],
    },
    {"id": "retarget", "line": "ERROR Error in dual hand retargeting loop", "expected_modules": ["teleop"]},
    {
        "id": "video_config",
        "line": "ERROR invalid video_input_mode 'custom_fixture' for robot galbot",
        "expected_modules": ["teleop"],
    },
    {
        "id": "two_known",
        "line": "ERROR code=topic_rate_too_low\nWARN [VR_INPUT_MODE_CONFLICT] selected_mode=hand pico_input=controller",
        "expected_modules": ["daq", "teleop"],
        "expected_routing": "triage",
    },
    {
        "id": "case12_exact",
        "line": (
            "ERROR simulated=true module=daq MCAP queue full queue_drops=12\n"
            "ERROR simulated=true module=teleop VR connection timeout"
        ),
        "expected_modules": ["daq", "teleop"],
        "expected_routing": "triage",
    },
    {
        "id": "explicit_failed_alias",
        "structured": {"status": "failed", "scope": "DAQ 采集"},
        "expected_modules": ["daq"],
    },
    {
        "id": "explicit_failed_combined",
        "structured": {"status": "failed", "scope": "遥操与 DAQ"},
        "expected_modules": ["daq", "teleop"],
        "expected_routing": "triage",
    },
    {
        "id": "material_file_missing",
        "line": "ERROR isolated evidence preparation FileNotFoundError: disposable probe log missing",
        "description": "问题范围：DAQ 采集",
        "expected_modules": [],
        "expected_routing": "triage",
    },
    {
        "id": "feedback_transport",
        "line": "ERROR feedback HTTPException URLError ConnectionRefusedError",
        "description": "问题范围：遥操与 DAQ",
        "expected_modules": [],
        "expected_routing": "triage",
    },
    {
        "id": "normal_idle",
        "line": "INFO state=idle executing=false frequency_check=paused",
        "description": "问题范围：遥操",
        "expected_modules": [],
    },
    {
        "id": "vr_cleared",
        "line": "INFO [VR_INPUT_MODE_CONFLICT_CLEARED] selected_mode=hand pico_input=hand",
        "expected_modules": [],
    },
    {"id": "hand_recovered", "line": "INFO [VR_RAW_HAND_RECOVERED] hand=left", "expected_modules": []},
    {
        "id": "shm_present",
        "line": "INFO shared_memory_config_enabled=true integrated_roudi_identity_unchanged=true",
        "expected_modules": [],
    },
    {
        "id": "resource_expected_wait",
        "line": (
            "WARN exception_type=MediaResourcesBusy\n"
            "INFO status=converting derived_status=pending conversion_phase=waiting_media_capacity"
        ),
        "expected_modules": [],
    },
    {
        "id": "protective_repeat",
        "line": "ERROR operation=record.preflight code=record_already_active\nINFO recording=true phase=RECORDING",
        "expected_modules": [],
    },
    {"id": "unknown_code", "line": "ERROR code=topic_arbitrary_fixture", "expected_modules": []},
    {
        "id": "same_line_explicit_conflict",
        "line": "ERROR module=teleop code=topic_rate_too_low",
        "expected_modules": ["daq", "teleop"],
        "expected_routing": "triage",
    },
    {
        "id": "model_only",
        "model_answer": "DAQ硬盘故障",
        "knowledge_title": "DAQ录制失败",
        "line": "INFO current_state=not_observed",
        "expected_modules": [],
    },
    {
        "id": "bad_integrity",
        "line": "ERROR code=topic_rate_too_low",
        "material_hash_matches": False,
        "expected_modules": [],
        "reason": "Evidence integrity gate overrides recognizable code",
    },
]


@pytest.mark.parametrize("item", MATRIX, ids=[r["id"] for r in MATRIX])
def test_verified_source_code_routing_never_uses_model_text_or_generic_scope(routing, item):
    text = json.dumps(item["structured"], ensure_ascii=False) if "structured" in item else item.get("line", "")
    job = ready_job(routing, text, item.get("description", ""))
    if "source_lines" in item:
        excerpt = item["source_lines"][1]
        source_file = PackageFile.objects.get(pk=job.result["sources"][0]["file_id"])
        digest = hashlib.sha256(excerpt.encode()).hexdigest()
        other_file = PackageFile.objects.create(
            project=source_file.project,
            created_by=source_file.created_by,
            package=source_file.package,
            name="另一份现场记录.log",
            storage_key=uuid4().hex,
            size=len(excerpt.encode()),
            sha256=digest,
        )
        job.result["sources"].append(
            {
                "file_id": str(other_file.id),
                "sha256": digest,
                "excerpt": excerpt,
                "read_bytes": len(excerpt.encode()),
                "scan_incomplete": False,
            }
        )
    job.result["answer"] = item.get("model_answer", "")
    if item.get("material_hash_matches") is False:
        job.result["sources"][0]["sha256"] = "wrong"
    got, _ = evidence_modules(job, job.defect)
    assert got == set(item["expected_modules"]), (item["id"], got)


@pytest.mark.parametrize("cycle", ["0/3", "4/3", "1/0", "-1/3", "1/x", "1/"])
def test_malformed_confirmation_does_not_suppress_failure(cycle):
    from plane.quality.module_routing import log_failure

    assert log_failure(f'ERROR channel_status=ERROR message="freq low (confirming {cycle})"')


def test_confirmation_does_not_hide_an_independent_error_on_the_same_line():
    from plane.quality.module_routing import log_failure

    assert log_failure('WARN channel_status=ERROR message="freq low (confirming 1/3)" ERROR MCAP write failed')


def test_unreviewed_image_ocr_cannot_auto_assign_a_module(routing):
    job = ready_job(routing, "ERROR module=daq connection refused")
    job.result["sources"][0].update(origin="image_ocr", requires_review=True)
    modules, _ = evidence_modules(job, job.defect)
    assert modules == set()
