"""Scan full diagnostic text, retaining bounded error context rather than only file headers."""

from collections import deque
import json
import re
import time

ERROR = re.compile(rb"\berror\b|exception|traceback|fatal|failed|refused|timed out|\bwarn(?:ing)?\b|E-[A-Z0-9-]+", re.I)
FAULT = re.compile(rb"\berror\b|exception|traceback|fatal|failed|refused|timed out|E-[A-Z0-9-]+", re.I)
LIMIT = 256 * 1024
ERROR_HINTS = (b"error", b"exception", b"traceback", b"fatal", b"failed", b"refused", b"timed out", b"warn", b"e-")


def feedback_observations(text, budget):
    """Keep the latest producer observations whole before generic log sampling."""
    try:
        document = json.loads(text)
    except (ValueError, TypeError):
        return []
    if not isinstance(document, dict) or document.get("sourceSystem") != "ENGRAM_TELEOP_DAQ":
        return []
    evidence = document.get("evidence")
    observations = evidence.get("observations", {}) if isinstance(evidence, dict) else {}
    if not isinstance(observations, dict):
        observations = {}
    candidates = []
    snapshot = document.get("deploymentSnapshot")
    if isinstance(snapshot, dict) and isinstance(snapshot.get("components"), list):
        fields = ("key", "label", "status", "version", "branch", "commit", "source", "image", "builtAt", "generatedAt",
                  "dirty", "sourceSnapshotSha256", "sourceFileCount")
        rows = []
        for item in snapshot["components"][:32]:
            if not isinstance(item, dict):
                continue
            row = {}
            for key in fields:
                value = item.get(key)
                if isinstance(value, str):
                    row[key] = value[:160]
                elif key == "dirty" and type(value) is bool:
                    row[key] = value
                elif key == "sourceFileCount" and type(value) is int and value >= 0:
                    row[key] = value
            if len(json.dumps([*rows, row], ensure_ascii=False)) > 1800:
                break
            rows.append(row)
        candidates.append({"observation": "deploymentSnapshot", "event_id": document.get("eventId"),
                           "captured_at": snapshot.get("capturedAt"), "source": snapshot.get("source"),
                           "components": rows, "omitted_components": len(snapshot["components"]) - len(rows),
                           "scope": "uploaded snapshot at collection time; full metadata remains in attachment"})
    for key, observation in observations.items():
        if not isinstance(observation, dict):
            continue
        data = observation.get("data")
        provenance = {"observation": key, "source": observation.get("source"),
                      "captured_at": observation.get("capturedAt"), "status": observation.get("status")}
        if isinstance(data, dict) and isinstance(data.get("observations"), dict):
            nodes = data["observations"].get("nodes", {})
            node_data = nodes.get("data") if isinstance(nodes, dict) else None
            processes = node_data.get("processes", []) if isinstance(node_data, dict) else []
            for process in processes[:16] if isinstance(processes, list) else []:
                if not isinstance(process, dict) or not isinstance(process.get("lines"), list):
                    continue
                lines = process["lines"]
                candidates.append({**provenance, "process": process.get("name"), "latest_lines": lines[-3:],
                                   "preceding_lines": lines[-6:-3],
                                   "omitted_earlier_lines": max(0, len(lines) - 6)})
        if key != "teleop":
            candidates.append({**provenance, "data": data, "reason": observation.get("reason")})
    rows = []
    for value in candidates:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        # Older producer rows help correlate an incident, but must never evict
        # the latest complete observations merely because the preview is full.
        while "process" in value and value["preceding_lines"] and len(encoded) + 1 > min(budget, 2400):
            value["preceding_lines"].pop(0)
            value["omitted_earlier_lines"] += 1
            encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if len(encoded) + 1 > budget:
            continue
        rows.append(encoded)
        budget -= len(encoded) + 1
    return rows


def summarize(text, limit=8000):
    """Keep fault context from throughout the scanned log within the model budget."""
    if len(text) <= limit:
        return text
    lines = text.splitlines(keepends=True)
    # Keep the latest structured preflight event whole: cutting inside its
    # diagnosis loses the timestamp/task that distinguishes it from old faults.
    structured = []
    structured_budget = max(0, limit - 2)
    for line in reversed(lines):
        if '"record_preflight"' not in line:
            continue
        try:
            record = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(record, dict):
            continue
        event = record.get("record_preflight") or (record.get("detail", {}).get("record_preflight") if isinstance(record.get("detail"), dict) else None)
        if not isinstance(event, dict):
            continue
        compact = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        if len(compact) + 1 > structured_budget:
            compact = json.dumps({"time": record.get("time"), "action": record.get("action"),
                                  "record_preflight_omitted": "latest event exceeds summary budget; read original attachment"},
                                 ensure_ascii=False, separators=(",", ":"))
        structured.append(compact)
        structured_budget -= len(compact) + 1
        break
    for row in feedback_observations(text, min(limit // 2, structured_budget)):
        structured.append(row)
        structured_budget -= len(row) + 1
    # inspect() produces JSONL observations inside a multi-file text. A second
    # summary must retain these normal producer facts, even when unrelated
    # errors would otherwise consume the entire preview.
    observation_budget = structured_budget
    for line in lines:
        if '"observation"' not in line:
            continue
        try:
            record = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(record, dict) or not (
            record.get("observation") == "deploymentSnapshot"
            or isinstance(record.get("process"), str) and isinstance(record.get("latest_lines"), list)
        ):
            continue
        compact = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        if compact not in structured and len(compact) + 1 <= observation_budget:
            structured.append(compact)
            observation_budget -= len(compact) + 1
    faults, warnings, seen = [], [], set()
    for index, line in enumerate(lines):
        encoded = line.encode("utf-8", errors="replace")
        match = FAULT.search(encoded)
        if not match and not ERROR.search(encoded):
            continue
        if line in seen:
            continue
        seen.add(line)
        context = "".join(lines[max(0, index - 1) : min(len(lines), index + 3)])
        if len(context) > 1800:
            # A log record may itself contain a long serialized JSON value.
            position = match.start() if match else 0
            context = encoded[max(0, position - 256) : position + 1400].decode("utf-8", errors="replace")
        (faults if match else warnings).append(context)
    selected = (faults + warnings)[:64]
    prefix = "\n".join(structured)
    budget = max(0, limit * 3 // 4 - len(prefix) - 1)
    share = budget // max(1, len(selected))
    important = "\n".join([prefix, *(row[: share - 1] for row in selected if share > 1)]).strip()
    remaining = max(0, limit - len(important) - 2)
    return (important + "\n" + text[: remaining // 2] + "\n" + text[-(remaining - remaining // 2) :])[:limit]


def collect(stream, size, deadline=None):
    head, tail, windows = bytearray(), deque(maxlen=24), deque()
    faults = deque()
    previous = deque(maxlen=8)
    kept = scanned = following = fault_bytes = 0
    deadline = min(deadline, time.monotonic() + 20) if deadline is not None else time.monotonic() + 20
    while scanned < size and time.monotonic() < deadline:
        line = stream.readline(64 * 1024)
        if not line:
            break
        scanned += len(line)
        if len(head) < 4096:
            head.extend(line[: 4096 - len(head)])
        # Tail stores the actual end of the record even when an earlier fault
        # match selects a different window from a long serialized record.
        tail.append(line[-4096:])
        # ERROR contains every FAULT alternative. Normal records need one scan,
        # and a fault still takes priority over an earlier warning in the same record.
        lowered = line.lower()
        error_match = ERROR.search(line) if any(hint in lowered for hint in ERROR_HINTS) else None
        fault_match = FAULT.search(line) if error_match else None
        match = fault_match or error_match
        if len(line) > 4096 and match:
            line = line[max(0, match.start() - 1024) : match.start() + 3072]
        else:
            line = line[:4096]
        if fault_match:
            fault_context = b"".join(previous) + line
            faults.append(fault_context)
            fault_bytes += len(fault_context)
            while fault_bytes > LIMIT // 2 and faults:
                fault_bytes -= len(faults.popleft())
        if error_match:
            context = b"".join(previous) + line
            following = 8
        elif following:
            context = line
            following -= 1
        else:
            context = b""
        if context:
            windows.append(context)
            kept += len(context)
            while kept > LIMIT // 2 - 16 * 1024 and windows:
                kept -= len(windows.popleft())
        previous.append(line)
    if scanned <= LIMIT and scanned == size:
        # For small files the original complete text fits within the evidence budget.
        try:
            stream.seek(0)
            return stream.read(size), scanned, False
        except (OSError, AttributeError):
            pass
    # Reserve the tail before packing earlier windows; dense errors can fill
    # both queues, and slicing their concatenation used to evict the final fault.
    last = b"".join(tail)[-32 * 1024 :]
    fault_sample = b"".join(faults)[-96 * 1024 :]
    warning_sample = b"".join(windows)[-(LIMIT - len(head) - len(last) - len(fault_sample) - 128) :]
    sample = (
        bytes(head)
        + b"\n[fault context]\n"
        + fault_sample
        + b"\n[matched error context]\n"
        + warning_sample
        + b"\n[log tail]\n"
        + last
    )
    return sample[:LIMIT], scanned, scanned < size
