"""Assign only a unique module tied to verified failure evidence, never model prose."""

import json
import re
from .models import Defect, DefectEvent, ModuleOwner, PackageFile, ProblemPackage
from .module_owners import eligible_technician, module_options, module_record

FAILURE = re.compile(
    r"\b(?:error|fatal|exception|traceback|failed|failure)\b|connection refused|timed out|异常|失败|故障", re.I
)
FIELD = re.compile(
    r"""(?<![\w])(?:["']?(?:module|module_key|scope|component|受影响模块|问题范围|模块)["']?)\s*[:：=]\s*["']?([^\n\r,;，；}\]"']+)""",
    re.I,
)


def log_failure(line):
    if re.search(r"\bno errors?\b|\berrors?\s*[:=]\s*(?:0|none|null|false)\b", line, re.I):
        return False
    confirmation = re.search(r"\bfreq low\s*\(confirming ([0-9]{1,6})/([0-9]{1,6})\)", line, re.I)
    if (
        confirmation
        and re.search(r"\bchannel_status=ERROR\b", line)
        and 0 < int(confirmation[1]) < int(confirmation[2])
        and not re.search(r"\bmodule_error_bit=true\b", line, re.I)
        and not FAILURE.search(
            re.sub(
                r"^(?:SIMULATED\s+)?(?:\[TopicMonitor\]\s+)?WARN(?:ING)?\s+",
                "",
                re.sub(r"\bchannel_status=ERROR\b", "", line),
                flags=re.I,
            )
        )
    ):
        return False
    return bool(FAILURE.search(line))


def identified(text, options):
    names = {}
    for row in options:
        for value in (row["key"], row["name"]):
            names.setdefault(value.casefold(), set()).add(row["key"])
    values = [match.strip().casefold() for match in FIELD.findall(text)]
    result = set()
    # A canonical unquoted scalar may be followed by an English diagnostic message.
    # Do not apply this to human scope labels, quoted multi-value fields or conjunctions.
    for scalar, remainder in re.findall(
        r"\b(?:module|module_key|component)\s*=\s*([a-z][a-z0-9_-]*)([^\n\r,;]*)", text, re.I
    ):
        tail = remainder.strip().casefold()
        if scalar.casefold() in names and not re.match(r"(?:and|or|和|与|及|、)\b", tail):
            if not any(re.search(r"(?<![\w])" + re.escape(name) + r"(?![\w])", tail) for name in names):
                result.update(names[scalar.casefold()])
    for value in values:
        # In log lines the scalar label may be followed by the failure itself.
        if value in names:
            result.update(names[value])
        else:
            for name, keys in names.items():
                if re.match(
                    re.escape(name) + r"\s+(?:error|fatal|exception|timeout|connection|failed|failure)\b", value, re.I
                ):
                    result.update(keys)
    return result


def failing_components(value, options):
    found = set()
    if isinstance(value, dict):
        if value.get("failure_kind") in {"not_started", "not_running", "never_started"}:
            return found
        state = str(value.get("status", "")).casefold()
        if state in {"failed", "error", "crashed", "unhealthy"}:
            for field in ("module", "module_key", "scope", "component"):
                if isinstance(value.get(field), str):
                    aliases = {
                        "DAQ 采集": {"daq"},
                        "DAQ采集": {"daq"},
                        "遥操与 DAQ": {"daq", "teleop"},
                        "遥操与DAQ": {"daq", "teleop"},
                    }
                    found.update(aliases.get(value[field], identified(f"module={value[field]}", options)))
        for key, child in value.items():
            if key not in {"history", "logs", "startupLog", "preceding_lines"}:
                found.update(failing_components(child, options))
    elif isinstance(value, list):
        for child in value:
            found.update(failing_components(child, options))
    return found


def producer_modules(document):
    """Recognize bounded producer observations; idle and not_started are never faults."""
    if not isinstance(document, dict):
        return set()
    evidence = document.get("evidence")
    observations = evidence.get("observations") if isinstance(evidence, dict) else None
    if not isinstance(observations, dict):
        return set()

    def failed(value):
        if isinstance(value, dict):
            if value.get("failure_kind") in {"not_started", "not_running", "never_started"}:
                return False
            if str(value.get("state", value.get("phase", value.get("status", "")))).casefold() in {
                "error",
                "failed",
                "crashed",
                "unhealthy",
            }:
                return True
            if isinstance(value.get("error"), str) and value["error"].strip():
                return True
            code = value.get("exit_code")
            if type(code) is int and code != 0:
                return True
            return any(
                failed(child)
                for key, child in value.items()
                if key not in {"history", "logs", "startupLog", "preceding_lines"}
            )
        if isinstance(value, list):
            return any(failed(child) for child in value)
        return False

    result = set()
    for key in ("daq", "teleop"):
        observation = observations.get(key)
        if (
            isinstance(observation, dict)
            and observation.get("status") == "available"
            and failed(observation.get("data"))
        ):
            result.add(key)
    return result


LOG_COMPONENTS = {
    "daq": re.compile(
        r"\b(?:mcap(?:[ _-]writer)?|rosbag2(?:_transport)?|recording_controller|recording_manager)\b", re.I
    ),
    "teleop": re.compile(
        r"\b(?:vr_node|ik_solver|remote_control_robot|robot_implementation|teleop_controller)\b", re.I
    ),
}


SOURCE_DAQ_CODES = frozenset(
    {
        "topic_not_discovered",
        "topic_not_matched",
        "topic_first_message_timeout",
        "topic_discovery_unavailable",
        "topic_missing",
        "topic_type_mismatch",
        "topic_header_timestamp_invalid",
        "topic_sample_insufficient",
        "topic_rate_unstable",
        "topic_no_messages",
        "topic_length_unavailable",
        "topic_length_mismatch",
        "topic_rate_too_low",
        "record_topic_health_failed",
        "record_topic_preflight_failed",
        "record_topics_empty",
        "record_network_link_unhealthy",
        "raw_failed",
        "derived_failed",
        "metadata_storage_quota_exceeded",
        "RECORDING_DURABILITY_FAILED",
        "packet_timeline_failed",
        "no_video_frames",
    }
)
SOURCE_DAQ_PHRASES = (
    "MCAP queue full",
    "MCAP write failed",
    "C++ CaptureService raw MCAP integrity check failed",
    "Invalid camera stream geometry or frame rate",
    "Camera configuration must be an array",
    "Camera name is not a safe artifact name",
    "Camera provider returned no source",
    "SDK camera readiness failed",
    "Mixed encoder admission failed",
    "recording primary routes exceed encoder capacity",
    "CaptureService raw accounting missing/invalid counter",
    "MCAP metadata message count conflicts with CaptureService write accounting",
    "DAQ_MCAP_STORAGE_PRESET must be",
    "DAQ_MCAP_MAX_MESSAGES_PER_FILE must be",
    "MCAP message limit requires",
    "Session has no frozen recording topic rules",
    "Stopped recording has no conversion source",
    "Recording interrupted by unexpected service shutdown",
    "Raw MCAP changed during timestamp inspection",
    "候选 MCAP 的逐 Topic 消息数量校验失败",
    "realtime master changed after CaptureService hand-off",
    "timestamp count mismatch: sidecar=",
    "depth source mapping digest or record count mismatch",
    "上传会话分片参数不完整",
    "存储节点分片上传暂不可用，将自动重试：",
)
SOURCE_TELEOP_PHRASES = (
    "Retarget error (left)",
    "Retarget error (right)",
    "Error in dual hand retargeting loop",
    "invalid video_input_mode",
    "unsupported robot",
    "stereo video input requires distinct, non-empty left and right topics",
    "relay_source_topics and relay_local_topics must have the same length",
    "relay local topic is also configured as a source",
    "invalid requested SBS output size",
    "Pico signaling failed to start",
    "ENGRAM_TELEOP_INSTALL_PREFIX is required",
    "[PICO_RECENTER] failed",
    "[RESET_ERROR] type=feedback_unavailable",
    "[pico_video] video session open failed",
    "[pico_video] media failure stage=",
    "failed to start: media encoder admission failed:",
    "failed to start: media backend admission failed:",
)
SOURCE_TELEOP_WARN_TAGS = ("[VR_INPUT_MODE_CONFLICT]", "[VR_RAW_HAND_INVALID]", "[VR_RAW_HAND_INVALID_BEGIN]")


def source_fault_modules(line, structured=None):
    """Finite producer signatures identify responsibility, never an unobserved root cause."""
    if isinstance(structured, dict):
        state = str(structured.get("status", structured.get("state", ""))).casefold()
        if state in {"ok", "success", "completed", "healthy", "idle", "pending", "not_started", "not_running"}:
            return set()
        level = str(structured.get("level", structured.get("levelname", ""))).casefold()
        active = state in {"failed", "error", "blocked", "crashed", "unhealthy"} or level in {
            "error",
            "fatal",
            "warning",
            "warn",
        }
        active = active or bool(isinstance(structured.get("error"), str) and structured["error"].strip())
        result = set()
        if active:
            values = [
                str(structured[key])
                for key in [
                    "code",
                    "error_code",
                    "failure_class",
                    "failure_reason",
                    "exception_type",
                    "error",
                    "message",
                    "msg",
                    "detail",
                ]
                if isinstance(structured.get(key), (str, int))
            ]
            result.update(
                source_fault_modules(("WARN " if level in {"warning", "warn"} else "ERROR ") + " ".join(values))
            )
        return result
    if re.search(
        r"\bno errors?\b|\bactive=false\b|\bcleared=true\b|documentation example|示例[：:]|\bexample:", line, re.I
    ):
        return set()
    failed = log_failure(line)
    tokens = set(re.findall(r"(?<![A-Za-z0-9_])([A-Za-z][A-Za-z0-9_]{2,119})(?![A-Za-z0-9_])", line))
    result = set()
    if failed and (
        tokens & SOURCE_DAQ_CODES or any(value.casefold() in line.casefold() for value in SOURCE_DAQ_PHRASES)
    ):
        result.add("daq")
    if failed and re.search(r"\bvalidation_error=相机 [^\n]{1,100} 的 (?:color|depth) 重复", line):
        result.add("daq")
    if failed and any(value.casefold() in line.casefold() for value in SOURCE_TELEOP_PHRASES):
        result.add("teleop")
    if re.search(r"\bWARN(?:ING)?\b", line, re.I):
        if "录制已强制停止，本段数据可能不完整：" in line:
            result.add("daq")
        if "MCAP queue full" in line and re.search(r"\bqueue_drops=[1-9][0-9]*\b", line):
            result.add("daq")
        if any(tag in line for tag in SOURCE_TELEOP_WARN_TAGS):
            result.add("teleop")
        if any(
            phrase in line
            for phrase in (
                "[pico_video] media failure stage=",
                "Discarded invalid retargeting sample",
                "[TopicMonitor] Unknown msg_type",
                "[JointStateProvider] rejected msg.robot_name=",
                "Dropping source image with invalid or non-increasing timestamp",
            )
        ):
            result.add("teleop")
        if "IMAGE_TIMESTAMP_FILTER_DROP" in line and "reason=backwards_header_timestamp" in line:
            result.add("daq")
        if "[PICO_HEARTBEAT]" in line and "diagnosis=heartbeat_timeout_while_tracking_active" in line:
            result.add("teleop")
    return result


def teleop_registration_mismatch(lines):
    """Recognize one narrowly bounded same-source ROS control-registration failure."""
    has_uninitialized_node = any(
        re.search(r'\bHTTP=503\b', line)
        and re.search(r'\bdetail="ROS node not initialized"', line)
        for line in lines
    )
    has_missing_registration_while_running = any(
        re.search(
            r"\bexpected_service_phase=running\b.*\bcontrol_status_read=true\b.*\bnode_registry_present=false\b",
            line,
        )
        for line in lines
    )
    return has_uninitialized_node and has_missing_registration_while_running


def evidence_modules(job, defect, materials=None):
    result = job.result or {}
    sources = result.get("sources", [])
    if not sources or any(row.get("scan_incomplete") for row in sources):
        return set(), "现场材料缺失或扫描不完整，待人工指派。"
    if ProblemPackage.objects.filter(defect=defect).exclude(status="files_verified").exists():
        return set(), "现场材料尚未全部校验完成，待人工指派。"
    files = {
        str(row.id): row
        for row in PackageFile.objects.filter(
            project_id=defect.project_id, package__defect=defect, package__status="files_verified"
        )
    }
    options = module_options()
    candidates = set()
    has_failure = False
    for source in sources:
        if source.get("origin") == "image_ocr" or source.get("requires_review") is True:
            continue
        file = files.get(str(source.get("file_id")))
        if not file or source.get("sha256") != file.sha256 or not source.get("read_bytes"):
            return set(), "诊断材料引用未通过项目和完整性校验，待人工指派。"
        reference = f"FILE-{file.id}" + (f":{source['archive_entry']}" if source.get("archive_entry") else "")
        material = materials.get(reference, {}) if isinstance(materials, dict) else {}
        text = material.get("content", source.get("excerpt", ""))
        if not isinstance(text, str):
            continue
        source_lines = text.splitlines()
        if teleop_registration_mismatch(source_lines):
            candidates.add("teleop")
            has_failure = True
        try:
            document = json.loads(text)
        except (ValueError, TypeError, RecursionError):
            document = None
        structured = (
            failing_components(document, options) | producer_modules(document) | source_fault_modules("", document)
        )
        if structured:
            has_failure = True
            candidates.update(structured)
        # Summary may be JSONL; parse complete observations individually without trusting cut JSON.
        for line in text.splitlines():
            try:
                value = json.loads(line)
            except (ValueError, TypeError, RecursionError):
                value = None
            if isinstance(value, dict):
                structured = (
                    failing_components(value, options) | producer_modules(value) | source_fault_modules(line, value)
                )
                observation = value.get("observation")
                if observation in {"daq", "teleop"}:
                    structured |= producer_modules({"evidence": {"observations": {observation: value}}})
                if structured:
                    has_failure = True
                    candidates.update(structured)
            elif document is None and not line.lstrip().startswith(("{", '"')):
                specific = source_fault_modules(line)
                if log_failure(line) or specific:
                    has_failure = True
                    candidates.update(specific)
                    candidates.update(identified(line, options))
                    candidates.update(key for key, pattern in LOG_COMPONENTS.items() if pattern.search(line))
    if has_failure and not candidates:
        # Structured DAQ descriptions can narrow an otherwise generic verified failure.
        # Ordinary titles, keywords and model answers never establish a module.
        candidates.update(identified(defect.description, options))
    if not candidates:
        return candidates, "现场证据未能高可信确认单一模块，待人工指派。"
    if len(candidates) != 1:
        return candidates, "现场证据涉及多个模块，待人工指派。"
    citations = ", ".join(
        f"FILE-{source['file_id']}" + (f":{source['archive_entry']}" if source.get("archive_entry") else "")
        for source in sources[:5]
    )
    return candidates, f"已校验现场材料中的异常与结构化模块信息一致；引用：{citations}。"


def initial_candidates(description):
    """Initial claims guide triage; combined scopes never masquerade as one module."""
    options = module_options()
    modules = identified(description, options)
    scopes = re.findall(r"(?:问题范围|scope)\s*[:：=]\s*([^\n\r,;，；]+)", description, re.I)
    for scope in scopes:
        value = scope.strip().casefold()
        if value in {"combined", "遥操与 daq", "遥操与daq"}:
            modules.update({"daq", "teleop"})
        elif value in {"daq 采集", "daq采集"}:
            modules.add("daq")
        elif value == "遥操":
            modules.add("teleop")
    labels = re.findall(r"受影响模块\s*[:：=]\s*([^\n\r]+)", description)
    for label in labels:
        selected = {part.strip() for part in label.split("、")}
        if selected & {"DAQ 录制", "转换 / 质检", "数据上传"}:
            modules.add("daq")
        if selected & {"VR / 输入设备", "IK / 重定向", "标定 / 复位", "机器人 / 末端执行器"}:
            modules.add("teleop")
    if not modules:
        stages = re.findall(r"(?:发生阶段|stage)\s*[:：=]\s*([^\n\r,;，；]+)", description, re.I)
        for stage in stages:
            if stage.strip().casefold() in {
                "recording",
                "数据录制",
                "转换 / 质检",
                "数据上传",
                "采集",
                "录制",
                "upload",
            }:
                modules.add("daq")
            elif stage.strip().casefold() in {"control", "遥操", "遥操作", "遥操控制", "teleop"}:
                modules.add("teleop")
    return modules


def triage_user(project):
    from plane.db.models import User
    from plane.license.models import InstanceAdmin
    from .notifications import managers
    from .permissions import is_administrator

    manager_ids = list(managers(project))
    for user in User.objects.filter(pk__in=manager_ids, is_active=True, is_bot=False).order_by("id"):
        if not is_administrator(user):
            return user
    for user in User.objects.filter(
        pk__in=InstanceAdmin.objects.filter(role=20).values("user_id"), is_active=True, is_bot=False
    ).order_by("id"):
        if is_administrator(user):
            return user
    from django.db.models import Q
    from .models import BusinessRole

    legacy_ids = BusinessRole.objects.filter(
        Q(role="PLATFORM_ADMIN") | Q(additional_roles__contains=["PLATFORM_ADMIN"])
    ).values("user_id")
    for user in User.objects.filter(pk__in=legacy_ids, is_active=True, is_bot=False).order_by("id"):
        if is_administrator(user):
            return user
    return None


def initial_assign(defect, actor):
    """The accepted report has one accountable person before material analysis finishes."""
    from django.db import transaction

    with transaction.atomic():
        current = Defect.objects.select_for_update().select_related("project__workspace").get(pk=defect.pk)
        if current.assignee_id or current.assignment_origin == "manual":
            return current
        modules = initial_candidates(current.description)
        module = module_record(next(iter(modules))) if len(modules) == 1 else None
        owner = (
            ModuleOwner.objects.filter(workspace_id=current.project.workspace_id, module=module).first()
            if module
            else None
        )
        target = owner.user if owner and eligible_technician(current.project, owner.user_id) else None
        origin = "initial" if target else "triage"
        reason = (
            "初步分派：依据上报结构化模块选择默认负责人，尚待现场材料诊断确认。"
            if target
            else "初步分诊：模块不明确或无有效模块负责人，由项目经理或管理员排查并改派。"
        )
        target = target or triage_user(current.project)
        if not target:
            from rest_framework.exceptions import APIException

            class OwnerUnavailable(APIException):
                status_code = 503
                default_detail = "负责人未配置，请先配置有效项目经理或管理员后重试。"
                default_code = "OWNER_NOT_CONFIGURED"

            raise OwnerUnavailable()
        current.module = module
        current.assignee = target
        current.assignment_origin = origin
        current.assignment_reason = reason
        current.edit_version += 1
        current.save(
            update_fields=["module", "assignee", "assignment_origin", "assignment_reason", "edit_version", "updated_at"]
        )
        DefectEvent.objects.create(
            project=current.project,
            defect=current,
            created_by=actor,
            previous_status=current.status,
            status=current.status,
            note=f"初步分派：未指派 → {target.display_name or target.username} ({target.id})；{reason}",
        )
        from .notifications import defect_notice

        defect_notice(current, actor, "反馈已初步分派，请排查并确认负责人")
        return current


def route_completed(job, materials=None):
    """Called inside diagnostic finalization's transaction; defect lock serializes all jobs."""
    if job.status != "completed":
        return
    defect = Defect.objects.select_for_update().select_related("project__workspace").get(pk=job.defect_id)
    if (
        (defect.assignee_id and defect.assignment_origin not in {"initial", "triage"})
        or defect.pending_assignee_id
        or defect.assignment_origin == "manual"
        or defect.archived_at
        or defect.status == "closed"
    ):
        return
    modules, reason = evidence_modules(job, defect, materials)
    module = module_record(next(iter(modules))) if len(modules) == 1 else None
    owner = (
        ModuleOwner.objects.filter(workspace_id=defect.project.workspace_id, module=module).first() if module else None
    )
    target = owner.user_id if owner and eligible_technician(defect.project, owner.user_id) else None
    origin = "diagnostic"
    if not target and defect.assignee_id:
        # Unconfirmed automatic module claims return to triage; manual choices are guarded above.
        if defect.assignment_origin == "triage":
            if module:
                reason += " 该模块尚无当前项目的有效技术负责人，待人工指派。"
            reason = reason[:2000]
            if defect.assignment_reason != reason:
                defect.assignment_reason = reason
                defect.edit_version += 1
                defect.save(update_fields=["assignment_reason", "edit_version", "updated_at"])
                from .agent_lifecycle import advance_after_metadata
                advance_after_metadata(defect,defect.edit_version-1)
                DefectEvent.objects.create(
                    project=defect.project, defect=defect, created_by=job.created_by,
                    previous_status=defect.status, status=defect.status,
                    note=f"诊断待分诊原因：{reason} 保留现有分诊负责人，未自动改派。",
                )
            return
        triager = triage_user(defect.project)
        if not triager:
            return
        target = triager.id
        origin = "triage"
    if module and not target:
        reason += " 该模块尚无当前项目的有效技术负责人，待人工指派。"
    reason = reason[:2000]
    if defect.module_id == getattr(module, "key", None) and defect.assignment_reason == reason:
        return
    previous = defect.assignee
    defect.module = module
    defect.assignment_reason = reason
    if target:
        defect.assignee_id = target
        defect.assignment_origin = origin
    defect.edit_version += 1
    defect.save(
        update_fields=["module", "assignment_reason", "assignment_origin", "assignee", "edit_version", "updated_at"]
    )
    from .agent_lifecycle import advance_after_metadata
    advance_after_metadata(defect,defect.edit_version-1)
    if target:
        DefectEvent.objects.create(
            project=defect.project,
            defect=defect,
            created_by=job.created_by,
            previous_status=defect.status,
            status=defect.status,
            note=(
                f"诊断自动指派：{(previous.display_name or previous.username) if previous else '未指派'} "
                f"({previous.id if previous else '-'}) → "
                f"{defect.assignee.display_name or defect.assignee.username} ({target})；"
                f"模块：{module.name if module else '待确认'}；{reason}"
            ),
        )
        from .notifications import defect_notice

        defect_notice(
            defect,
            job.created_by,
            "诊断待分诊，请确认负责人" if origin == "triage" else "诊断已确认模块负责人",
            [previous.id] if previous else [],
        )
