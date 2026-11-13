"""Bound a model severity suggestion to verified current FILE evidence; never mutate a defect."""

import json
import re

from plane.knowledge.retrieval import scan_content
from .models import PackageFile, ProblemPackage
from .module_routing import log_failure, source_fault_modules, SOURCE_DAQ_CODES

LEVELS = ("trivial", "minor", "major", "critical")
PENDING = "材料尚不足以核验影响程度，待评估。"
NEGATED = re.compile(
    r"不存在|没有|未发生|尚未确认|未确认|可能|假设|示例|文档引用|历史事件|旧事件|"
    r"(?:未|无|不)(?:危及|设备损坏|涉及|存在)|"
    r"\b(?:may|might|hypothetical|example|documentation|not confirmed|no evidence)\b",
    re.I,
)
SIMULATED = re.compile(
    r"\b(?:simulated|synthetic)[\"']?\s*[:=]\s*(?:[\"']?true)\b|"
    r"\b(?:simulated|synthetic)\b(?![\"']?\s*[:=])|模拟|合成",
    re.I,
)
RECOVERY = re.compile(
    r"复核.{0,25}(?:完整|(?<!不)可恢复|无损)|已确认.{0,15}(?:数据完整|(?<!不)可恢复)|confirmed.{0,20}(?<!ir)recoverable",
    re.I,
)


def observations(text):
    """Keep JSON observation structure; histories and quoted messages are not current facts."""

    def human(value):
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [line for item in value[:100] for line in human(item)]
        if isinstance(value, dict):
            rows = document(value)
            for key, item in value.items():
                if key not in {
                    "history",
                    "examples",
                    "example",
                    "documentation",
                    "previous",
                    "preceding_lines",
                    "startupLog",
                    "status",
                    "state",
                    "raw_status",
                    "derived_status",
                    "failure_class",
                    "failure_reason",
                    "code",
                    "error_code",
                    "queue_drops",
                    "write_errors",
                    "lost_frames",
                    "route",
                    "message",
                    "record_preflight",
                    "observation",
                    "observations",
                    "data",
                    "diagnosis",
                    "results",
                    "routes",
                }:
                    rows.extend(human(item))
            return rows
        return []

    def document(value):
        if not isinstance(value, dict):
            return []
        state = str(value.get("status", value.get("state", ""))).casefold()
        summary_ok = state in {"ok", "healthy", "success", "passed", "completed", "idle"}
        fields = {
            "status",
            "state",
            "raw_status",
            "derived_status",
            "failure_class",
            "failure_reason",
            "code",
            "error_code",
            "queue_drops",
            "write_errors",
            "lost_frames",
            "route",
        }
        line = " ".join(
            f"{key}={item}"
            for key, item in value.items()
            if key in fields and isinstance(item, (str, int)) and not isinstance(item, bool)
        )
        level = str(value.get("level", value.get("levelname", ""))).casefold()
        active = (
            state in {"failed", "error", "blocked", "crashed", "unhealthy"}
            or level in {"error", "fatal", "warn", "warning"}
            or value.get("raw_status") in ("failed", "interrupted")
            or value.get("failure_class") == "raw_failed"
        )
        if active:
            line = "ERROR " + line
            if not summary_ok and isinstance(value.get("message"), str):
                line += " " + value["message"]
        rows = [line] if line else []
        if "observations" in value:
            rows += human(value["observations"])
        for key in {"record_preflight", "observation", "data", "diagnosis", "results", "routes"}:
            child = value.get(key)
            if isinstance(child, dict):
                rows += document(child)
            elif isinstance(child, list):
                for item in child[:100]:
                    rows += document(item)
        return rows

    def bounded(value):
        stack, count = [(value, 0)], 0
        while stack:
            item, depth = stack.pop()
            count += 1
            if depth > 24 or count > 10000:
                return False
            if isinstance(item, dict):
                stack.extend((child, depth + 1) for child in item.values())
            elif isinstance(item, list):
                stack.extend((child, depth + 1) for child in item)
        return True

    try:
        full = json.loads(text)
    except (ValueError, TypeError, RecursionError):
        full = None
    if isinstance(full, dict):
        return document(full) if bounded(full) else []
    if isinstance(full, list):
        return human(full) if bounded(full) else []
    rows = []
    for line in text.splitlines():
        try:
            value = json.loads(line)
        except (ValueError, TypeError, RecursionError):
            value = None
        if isinstance(value, dict):
            if not bounded(value):
                return []
            rows += document(value)
        elif not line.lstrip().startswith(("{", '"', "[{", '["')):
            rows.append(line)
    return rows


def normal_context(text):
    """Require a complete current observation combination, never one nominal marker."""

    text = "\n".join(line for line in text.splitlines() if not NEGATED.search(line))

    def all_markers(*values):
        return all(value in text for value in values)

    repeated = re.search(r"before_request[^\n]*recording=true[^\n]*session_alias=([\w-]+)", text)
    if repeated and all_markers("code=record_already_active", "phase=RECORDING"):
        if re.search(r"after_request[^\n]*recording=true[^\n]*session_alias=" + re.escape(repeated[1]) + r"\b", text):
            return True
    grant = re.search(r"grant_age_sec=(\d+)[^\n]*grant_expires_in_sec=(\d+)", text)
    if (
        grant
        and int(grant[1]) > int(grant[2])
        and all_markers(
            "same_actor=true",
            "same_task=true",
            "same_mode=true",
            "latest_preflight_ok=true",
            "recording=true",
            "phase=RECORDING",
        )
    ):
        return True
    if all_markers(
        "hand_only", "IK remains idle (retarget only)", "hand_qpos_counter_advancing=true", "arm_command_counter=0"
    ):
        return True
    if all_markers(
        "active_mode=hand",
        "ingress_stamp_advancing=true",
        "each_conflict_span_below_configured_delay=true",
        "module_bit32=false",
        "module_bit33=false",
    ):
        return True
    if all_markers(
        "prior_controller_active=true",
        "consecutive_inactive_frames_below_debounce=true",
        "published_controller_active=true",
        "ingress_stamp_advancing=true",
    ):
        return True
    if all_markers(
        "waiting for first message",
        "first_message_received=false",
        "subscribed_elapsed_below_grace=true",
        "confirmed_error_bit=false",
    ):
        return True
    cycle = re.search(r"freq low \(confirming (\d{1,6})/(\d{1,6})\)", text)
    return bool(
        cycle
        and 0 < int(cycle[1]) < int(cycle[2])
        and all_markers(
            "next_channel_status=OK",
            "consecutive_error_cycles=0",
            "module_error_bit=false",
        )
    )


def impact(text):
    """Recognize direct reported impact, separately from generic ERROR/log severity."""
    found = set()
    for line in observations(text):
        if NEGATED.search(line):
            continue
        failed = log_failure(line)
        if source_fault_modules(line):
            found.add("minor")
        if re.search(r"(?:已确认|经现场确认).{0,30}(?:不可恢复.{0,10}(?:丢失|损坏)|危及人员安全|设备损坏)", line):
            found.add("critical")
        if (
            failed
            and re.search(
                r"\b(?:raw_status\s*[:=]\s*(?:failed|interrupted)|failure_class\s*[:=]\s*raw_failed|"
                r"recording_start_failed|core_capture_blocked\s*[:=]\s*true|core_function_blocked\s*[:=]\s*true|"
                r"data_loss_confirmed\s*[:=]\s*true)\b|"
                r"MCAP write failed|C\+\+ CaptureService raw MCAP integrity check failed|"
                r"CaptureService raw accounting missing/invalid counter|"
                r"MCAP metadata message count conflicts with CaptureService write accounting|"
                r"recording primary routes exceed encoder capacity|"
                r"pico_video\]?\s*:?\s*failed to start:\s*media (?:encoder|backend) admission failed:|"
                r"\bFATAL\]?\s+failed to start:\s*media (?:encoder|backend) admission failed:|"
                r"(?:采集|录制|启动|核心功能)(?:被阻断|无法继续|失败)|已确认.{0,20}(?:数据丢失|数据损坏)",
                line,
                re.I,
            )
            or re.search(r"\b(?:queue_drops|write_errors|lost_frames)\s*[:=]\s*[1-9]\d*\b", line, re.I)
            or re.search(r"\bstatus\s*[:=]\s*blocked\b", line, re.I)
            and any(re.search(r"\b" + re.escape(code) + r"\b", line) for code in SOURCE_DAQ_CODES)
        ):
            found.add("major")
        if re.search(
            r"\b(?:needs_rebuild|packet_timeline_failed|derived_failed)\b|\[VR_RAW_HAND_INVALID(?:_BEGIN)?\]|"
            r"Error in dual hand retargeting loop|\[pico_video\] media failure stage=|"
            r"局部功能.{0,15}(?:不可用|失败)|影响有限|可恢复.{0,15}(?:失败|异常)",
            line,
            re.I,
        ):
            found.add("minor")
        if re.search(
            r"\[VR_RAW_HAND_RECOVERED\]|\[VR_INPUT_MODE_CONFLICT_CLEARED\]|"
            r"\bstate=idle\b|\bstatus=(?:healthy|ok)\b|功能正常|轻微.{0,10}(?:显示|错位)|显示.{0,10}轻微|已恢复正常",
            line,
            re.I,
        ):
            found.add("trivial")
    if normal_context("\n".join(observations(text))):
        found.add("trivial")
    return found


def pending(code="evidence_or_assessment_unverified"):
    return {"severity": "", "basis": PENDING, "evidence": [], "validation_code": code, "method": "pending"}


def boolean_context_fragment(quote, text):
    """Allow literal provenance flags together only when one current JSON object contains them."""
    try:
        fields = json.loads("{" + quote + "}")
    except (ValueError, TypeError, RecursionError):
        return False
    if not isinstance(fields, dict) or not fields or not all(type(value) is bool for value in fields.values()):
        return False
    visits = 0

    def current(value, depth=0):
        nonlocal visits
        visits += 1
        if depth > 24 or visits > 10000:
            return False
        if isinstance(value, dict):
            if all(type(value.get(key)) is bool and value[key] == expected for key, expected in fields.items()):
                return True
            return any(
                current(child, depth + 1)
                for key, child in value.items()
                if key
                not in {"history", "examples", "example", "documentation", "previous", "preceding_lines", "startupLog"}
            )
        if isinstance(value, list):
            return any(current(child, depth + 1) for child in value[:100])
        return False

    for candidate in [text, *text.splitlines()]:
        if quote not in candidate:
            continue
        try:
            document = json.loads(candidate)
        except (ValueError, TypeError, RecursionError):
            continue
        if current(document):
            return True
    return False


def quote_supported(quote, text):
    """A quoted substring must retain its own line/JSON observation's qualifications."""
    claimed = impact(quote)
    if not claimed and boolean_context_fragment(quote, text):
        return True
    try:
        document = json.loads(text)
    except (ValueError, TypeError, RecursionError):
        document = None
    if isinstance(document, dict):
        try:
            selected = json.loads(quote)
        except (ValueError, TypeError, RecursionError):
            selected = quote

        visits = 0

        def current_node(value, human=False, depth=0):
            nonlocal visits
            visits += 1
            if depth > 24 or visits > 10000:
                return False
            if isinstance(value, str):
                return human and value == selected and claimed.issubset(impact(value))
            if isinstance(value, list):
                if human and value == selected and claimed.issubset(impact(json.dumps(value, ensure_ascii=False))):
                    return True
                return any(current_node(item, human, depth + 1) for item in value[:100])
            if not isinstance(value, dict):
                return False
            if claimed and any(
                NEGATED.search(value[key]) for key in ("context", "description") if isinstance(value.get(key), str)
            ):
                return False
            if value == selected and claimed.issubset(impact(json.dumps(value, ensure_ascii=False))):
                return True
            keys = {"record_preflight", "observation", "observations", "data", "diagnosis", "results", "routes"}
            if human:
                keys |= set(value) - {
                    "history",
                    "examples",
                    "example",
                    "documentation",
                    "previous",
                    "preceding_lines",
                    "startupLog",
                }
            for key in keys:
                child = value.get(key)
                if current_node(child, human or key == "observations", depth + 1):
                    return True
            return False

        return current_node(document)
    offset = text.find(quote)
    while offset >= 0:
        first = text.rfind("\n", 0, offset) + 1
        last = text.find("\n", offset + len(quote))
        context = text[first : last if last >= 0 else len(text)]
        if context.lstrip().startswith("{") and quote.strip() != context.strip():
            offset = text.find(quote, offset + 1)
            continue
        if not claimed and quote.strip() == context.strip():
            return True
        if claimed and claimed.issubset(impact(context)):
            return True
        offset = text.find(quote, offset + 1)
    return False


def verified_sources(job, result, materials=None):
    """One current-material authority gate shared by model and native-rule assessments."""
    if not isinstance(result, dict) or job.status != "completed" or job.project_id != job.defect.project_id:
        return None, "source_integrity_unverified"
    sources, snapshot = result.get("sources"), result.get("input")
    if not isinstance(sources, list) or not sources or len(sources) > 1000 or not isinstance(snapshot, dict):
        return None, "source_integrity_unverified"
    selected = snapshot.get("files")
    if not isinstance(selected, list) or not selected or any(not isinstance(pk, str) for pk in selected):
        return None, "source_integrity_unverified"
    if ProblemPackage.objects.filter(defect_id=job.defect_id).exclude(status="files_verified").exists():
        return None, "source_integrity_unverified"
    # String comparison avoids trusting UUID-shaped model input in ORM conversion.
    files = {
        str(row.pk): row
        for row in PackageFile.objects.filter(
            project_id=job.project_id,
            package__defect_id=job.defect_id,
            package__status="files_verified",
        )
    }
    verified = {}
    for source in sources:
        if not isinstance(source, dict):
            return None, "source_integrity_unverified"
        file_id = source.get("file_id")
        file = files.get(file_id) if isinstance(file_id, str) else None
        text, count, scanned, original = (
            source.get(key) for key in ("excerpt", "read_bytes", "scanned_bytes", "file_bytes")
        )
        if (
            file is None
            or file_id not in selected
            or source.get("sha256") != file.sha256
            or source.get("scan_incomplete") is not False
            or not isinstance(text, str)
            or len(text) > 256 * 1024
            or type(count) is not int
            or count <= 0
            or type(original) is not int
            or original <= 0
            or type(scanned) is not int
            or scanned < original
            or count > original
            or scan_content(text)
        ):
            return None, "source_integrity_unverified"
        entry = source.get("archive_entry")
        if entry is not None and (
            not isinstance(entry, str)
            or not entry
            or len(entry) > 500
            or entry.startswith("/")
            or "\\" in entry
            or ".." in entry.split("/")
        ):
            return None, "source_integrity_unverified"
        if entry is None and original != file.size:
            return None, "source_integrity_unverified"
        reference = f"FILE-{file_id}" + (f":{entry}" if entry else "")
        if reference in verified:
            return None, "source_integrity_unverified"
        material = materials.get(reference) if isinstance(materials, dict) else None
        if (
            isinstance(material, dict)
            and material.get("truncated") is False
            and isinstance(material.get("content"), str)
        ):
            text = material["content"]
        elif source.get("preview_truncated") or source.get("truncated") or len(text.encode()) < original:
            return None, "source_integrity_unverified"
        if len(text) > 256 * 1024 or scan_content(text):
            return None, "source_integrity_unverified"
        verified[reference] = text
    return verified, "verified"


def model_proposal(result, verified):
    """Verify the model's own assessment against already authorized current material."""
    suggestion = result.get("severity_assessment")
    if not isinstance(suggestion, dict):
        return pending("model_assessment_missing_or_invalid")
    severity, basis, evidence = (suggestion.get(key) for key in ("severity", "basis", "evidence"))
    if (
        severity not in LEVELS
        or not isinstance(basis, str)
        or not basis.strip()
        or len(basis) > 1500
        or scan_content(basis)
        or not isinstance(evidence, list)
        or not 1 <= len(evidence) <= 10
    ):
        return pending("model_assessment_missing_or_invalid")
    snapshot = result["input"]
    citations = result.get("citations")
    if not isinstance(citations, list):
        return pending("quote_context_unverified")
    references = [row.get("reference") if isinstance(row, dict) else row for row in citations]
    if any(not isinstance(value, str) for value in references):
        return pending("quote_context_unverified")
    cited = set(references)
    quotes, safe_evidence, seen = [], [], set()
    for row in evidence:
        if not isinstance(row, dict):
            return pending()
        reference, quote = row.get("reference"), row.get("quote")
        if (
            not isinstance(reference, str)
            or reference not in verified
            or reference not in cited
            or not isinstance(quote, str)
            or not quote.strip()
            or len(quote) > 1500
            or quote not in verified[reference]
            or scan_content(quote)
            or not quote_supported(quote, verified[reference])
        ):
            return pending("quote_context_unverified")
        pair = (reference, quote)
        if pair in seen:
            continue
        seen.add(pair)
        # Context can explain scope without independently establishing impact.
        # Never concatenate non-impact snippets into a new grade-bearing claim.
        if impact(quote):
            quotes.append(quote)
        safe_evidence.append({"reference": reference, "quote": quote})
    observed = set().union(*(impact(quote) for quote in quotes))
    all_text = "\n".join(verified.values())
    broader = impact(all_text)
    if not observed or not broader or not observed.issubset(broader):
        return pending()
    if broader & {"critical", "major"} and RECOVERY.search(all_text):
        return pending()
    strongest = max(observed, key=LEVELS.index)
    # A local recovery cannot erase another active failure elsewhere in this job.
    if LEVELS.index(severity) < max(map(LEVELS.index, broader)):
        return pending()
    normal = normal_context("\n".join(observations(all_text)))

    def protected_repeat(line):
        if not normal or "code=record_already_active" not in line:
            return False
        remainder = line.replace("code=record_already_active", "")
        remainder = re.sub(r"^\s*(?:SIMULATED\s+)?ERROR\b", "", remainder)
        return not log_failure(remainder)

    if severity == "trivial" and any(
        log_failure(line) and not protected_repeat(line) for line in observations(all_text)
    ):
        return pending()
    if severity != strongest:
        return pending()
    # Input can restrict a simulation claim, but cannot establish incident severity.
    scope = all_text + "\n" + str(snapshot.get("description", ""))
    if severity == "critical" and SIMULATED.search(scope):
        return {
            "severity": "major",
            "basis": "模拟材料支持严重影响语义，实际人员、设备及不可恢复损失尚未验证；" + basis.strip()[:1400],
            "evidence": safe_evidence,
        }
    if severity == "critical":
        basis = "材料所述当前严重影响，待现场确认；" + basis.strip()[:1450]
    return {"severity": severity, "basis": basis.strip(), "evidence": safe_evidence}


def rules_proposal(result, verified):
    """Grade finite native observations and complete normal contexts, never unbounded model prose."""
    all_text = "\n".join(verified.values())
    if "critical" in impact(all_text):
        return pending("critical_requires_review")
    evidence = []
    native_state = re.compile(r"\b(?:raw_status[=:]\s*(?:failed|interrupted)|failure_class[=:]\s*raw_failed)\b")
    native_start = re.compile(
        r"\bFATAL\]?\s+(?:pico_video\s+)?failed to start:\s*media (?:encoder|backend) admission failed:", re.I
    )
    for reference, text in verified.items():
        lines = observations(text)

        def native_line(line):
            return not NEGATED.search(line) and (
                source_fault_modules(line) or native_state.search(line) or native_start.search(line)
            )

        def native_levels(line):
            if not native_line(line):
                return set()
            # A finite local fault tag grants its own impact only. Unrelated
            # claims on the same line cannot promote that tag's authority.
            raw_failure = native_state.search(line) or re.search(
                r"MCAP write failed|C\+\+ CaptureService raw MCAP integrity check failed|"
                r"CaptureService raw accounting missing/invalid counter|"
                r"MCAP metadata message count conflicts with CaptureService write accounting|"
                r"recording primary routes exceed encoder capacity",
                line,
                re.I,
            )
            raw_counts = re.search(r"\bMCAP\b", line, re.I) and re.search(
                r"\b(?:queue_drops|write_errors|lost_frames)\s*[:=]\s*[1-9]\d*\b", line, re.I
            )
            preflight_blocked = re.search(r"\bstatus\s*[:=]\s*blocked\b", line, re.I) and any(
                re.search(r"\b" + re.escape(code) + r"\b", line) for code in SOURCE_DAQ_CODES
            )
            return {"major" if raw_failure or raw_counts or preflight_blocked or native_start.search(line) else "minor"}

        known = any(native_line(line) for line in lines)
        normal = normal_context("\n".join(lines))
        if not known and not normal:
            continue
        candidates = [text] if len(text) <= 1500 else text.splitlines()
        for quote in candidates:
            if len(quote) > 1500 or not impact(quote) or not quote_supported(quote, text):
                continue
            allowed = set().union(*(native_levels(line) for line in observations(quote)))
            claimed = impact(quote)
            if known and (not allowed or max(map(LEVELS.index, claimed)) > max(map(LEVELS.index, allowed))):
                continue
            if not known and not normal_context("\n".join(observations(quote))):
                continue
            evidence.append({"reference": reference, "quote": quote})
            if len(evidence) >= 10:
                break
        if len(evidence) >= 10:
            break
    if not evidence:
        return pending("rules_impact_not_supported")
    supported = set().union(*(impact(row["quote"]) for row in evidence))
    if not supported or "critical" in supported:
        return pending("rules_impact_not_supported")
    grade = max(supported, key=LEVELS.index)
    assessment = {
        "severity": grade,
        "basis": "依据已校验当前材料中的有限源码契约与直接影响观测判级；规则判断范围以所列引用为准。",
        "evidence": evidence,
    }
    return model_proposal(
        {
            **result,
            "severity_assessment": assessment,
            "citations": [{"reference": row["reference"]} for row in evidence],
        },
        verified,
    )


def propose(job, result, materials=None):
    """Return an attributed, evidence-bound assessment without persisting or taking safety actions."""
    verified, code = verified_sources(job, result, materials)
    if verified is None:
        return pending(code)
    model = model_proposal(result, verified)
    if model["severity"]:
        return {**model, "method": "model_verified", "validation_code": "verified", "model_rejection_code": ""}
    rules = rules_proposal(result, verified)
    return {
        **rules,
        "method": "evidence_rules" if rules["severity"] else "pending",
        "validation_code": "verified" if rules["severity"] else rules["validation_code"],
        "model_rejection_code": model["validation_code"],
    }
