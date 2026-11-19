"""Scan full diagnostic text, retaining bounded error context rather than only file headers."""

from collections import deque
import json
import re
import time

ERROR = re.compile(rb"\berror\b|exception|traceback|fatal|failed|refused|timed out|\bwarn(?:ing)?\b|E-[A-Z0-9-]+", re.I)
FAULT = re.compile(rb"\berror\b|exception|traceback|fatal|failed|refused|timed out|E-[A-Z0-9-]+", re.I)
LOWER_FAULT = re.compile(rb"\berror\b|exception|traceback|fatal|failed|refused|timed out|e-[a-z0-9-]+")
LOWER_WARNING = re.compile(rb"\bwarn(?:ing)?\b")
LIMIT = 256 * 1024
NODE_FAULT = re.compile(r"error|exception|traceback|fatal|failed|refused|timed out|invalid|violation|aborted|异常|失败", re.I)
FAULT_HINTS = (b"error", b"exception", b"traceback", b"fatal", b"failed", b"refused", b"timed out", b"e-")
WARNING = re.compile(rb"\bwarn(?:ing)?\b", re.I)
LEADING_TIME = re.compile(rb"^\s*(?:\d{4}-\d{2}-\d{2}[T ][0-9:.+Z-]+|\d+(?:\.\d+)?)\s+")


# Repeated targets often interleave. Group only within one bounded scan block,
# the same UTC epoch-minute bucket and exact payload (including target and cause).
EPOCH_RECORDS = re.compile(rb"(?m)^(?P<epoch>[0-9]{9,12})\.[0-9]{1,9}(?P<payload>[ \t]+[^\r\n]*)\r?\n")


def compact_repeated_records(data):
    """Retain original first/last records per exact retry identity and epoch-minute bucket.

    C regex finds complete records; Python builds context only for retained
    representatives. Every original byte is still read for ZIP CRC/counts.
    """
    groups, pieces = {}, []
    previous = 0
    repeated = False
    for match in EPOCH_RECORDS.finditer(data):
        start, end = match.span()
        if start > previous:
            pieces.append((previous, data[previous:start]))
        key = int(match['epoch']) // 60, match['payload']
        group = groups.get(key)
        if group is None:
            groups[key] = [start, end, start, end, 1]
        else:
            group[2], group[3], group[4] = start, end, group[4] + 1
            repeated |= group[4] > 2
        previous = end
    if not repeated:
        return data
    if previous < len(data):
        pieces.append((previous, data[previous:]))
    for first, first_end, last, last_end, count in groups.values():
        pieces.append((first, data[first:first_end]))
        if last != first:
            marker = (b"[omitted_identical_records=" + str(count - 2).encode()
                      + b"; same epoch minute and exact payload]\n") if count > 2 else b""
            pieces.append((last, marker + data[last:last_end]))
    return b"".join(value for _, value in sorted(pieces))


def feedback_observations(text, budget, window=None):
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
            for process in processes[:1000] if isinstance(processes, list) else []:
                if not isinstance(process, dict) or not isinstance(process.get("lines"), list):
                    continue
                lines = [line for line in process["lines"] if isinstance(line, str)]
                line_indices = list(range(len(lines)))
                selection = {}
                if window is not None:
                    from .diagnostic_time_window import select_line_indices
                    line_indices, selection = select_line_indices(lines, window)
                    selection['selection_input_scope'] = 'uploaded_producer_log_lines'
                    lines = [lines[index] for index in line_indices]
                faults = [(line_indices[index], line) for index, line in enumerate(lines) if NODE_FAULT.search(line)]
                # Prioritize abnormal producers from any node, including faults
                # followed by healthy output. Preserve each original record whole.
                retained_faults = faults if len(faults) <= 6 else faults[:3] + faults[-3:]
                value = {**provenance, "process": process.get("name"), "latest_lines": lines[-3:],
                         "preceding_lines": lines[-6:-3], "log_file": process.get("log_file"),
                         "node_source": nodes.get("source"), "node_captured_at": nodes.get("capturedAt"),
                         "line_offset": process.get("offset"), "line_total": process.get("total"),
                         "producer_truncated": process.get("truncated"), "file_key": process.get("file_key"),
                         "omitted_earlier_lines": max(0, len(lines) - 6)}
                value.update(selection)
                if retained_faults:
                    value.update(fault_lines=[line for _, line in retained_faults],
                                 fault_line_numbers=[index + 1 for index, _ in retained_faults],
                                 omitted_fault_lines=len(faults) - len(retained_faults))
                candidates.append(value)
        if key != "teleop":
            candidates.append({**provenance, "data": data, "reason": observation.get("reason")})
    rows = []
    candidates.sort(key=lambda value: not bool(value.get("fault_lines")))
    for value in candidates:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        # Older producer rows help correlate an incident, but must never evict
        # the latest complete observations merely because the preview is full.
        while "process" in value and value["preceding_lines"] and len(encoded.encode()) + 1 > min(budget, 2400):
            value["preceding_lines"].pop(0)
            value["omitted_earlier_lines"] += 1
            encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        while value.get("fault_lines") and value.get("latest_lines") and len(encoded.encode()) + 1 > min(budget, 2400):
            value["latest_lines"].pop(0)
            encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode()) + 1 > budget:
            continue
        rows.append(encoded)
        budget -= len(encoded.encode()) + 1
    return rows


def summarize(text, limit=8000):
    """Keep fault context from throughout the scanned log within the model budget."""
    if len(text) <= limit:
        return text
    producer_rows = feedback_observations(text, max(0, limit - 2))
    if producer_rows:
        # Replacing the document with atomic producer rows avoids reintroducing
        # broken JSON fragments through the generic head/tail fallback below.
        return "\n".join(producer_rows)
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
    # inspect() produces JSONL observations inside a multi-file text. A second
    # summary must retain these normal producer facts, even when unrelated
    # errors would otherwise consume the entire preview.
    observation_budget = structured_budget
    for line in sorted(lines, key=lambda line: '"fault_lines"' not in line):
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


def collect(stream, size, deadline=None, *, window=None):
    """Read sequential blocks to EOF (including ZIP CRC), sampling complete records.

    Dense warnings must not cause a Python read and context allocation per line.
    Search faults across every byte; warning windows are representative per block.
    """
    head, tail, windows = bytearray(), bytearray(), deque()
    faults = deque()
    fault_bytes = warning_bytes = scanned = 0
    first_faults = bytearray()
    distinct_faults, distinct_signatures = bytearray(), set()
    document = bytearray() if size <= 1024 * 1024 else None
    deadline = min(deadline, time.monotonic() + 20) if deadline is not None else time.monotonic() + 20
    pending = b""
    previous_signature = None
    overlap = False

    def context(block, position):
        start = block.rfind(b"\n", 0, position) + 1
        end = block.find(b"\n", position)
        end = len(block) if end < 0 else end + 1
        before = start
        after = end
        for _ in range(2):
            before = max(0, block.rfind(b"\n", 0, max(0, before - 1)) + 1)
            next_end = block.find(b"\n", after)
            after = len(block) if next_end < 0 else next_end + 1
        # For oversized records retain the match; the actual record end is
        # separately retained in tail. Never classify a sliced normal record.
        if after - before > 8192:
            before, after = max(start, position - 1024), min(end, position + 3072)
        return block[before:after], end

    while scanned < size and time.monotonic() < deadline:
        block = stream.read(min(256 * 1024, size - scanned))
        if not block:
            break
        scanned += len(block)
        if document is not None:
            document.extend(block)
        if len(head) < 4096:
            head.extend(block[:4096 - len(head)])
        tail.extend(block)
        del tail[:-32 * 1024]
        data = pending + block
        skip_prefix = overlap
        overlap = False
        boundary = data.rfind(b"\n") + 1
        # Retain a boundary record across blocks, but bound pathological lines.
        scan_end = len(data)
        if scanned < size:
            if boundary and len(data) - boundary <= 64 * 1024:
                data, pending = data[:boundary], data[boundary:]
                scan_end = len(data)
            else:
                # Long serialized records can cross any byte boundary. Carry
                # overlap and only finalize matches with their following bytes
                # available, so splitting neither loses nor invents a token.
                scan_end = max(0, len(data) - 4096)
                pending = data[max(0, scan_end - 1):]
                overlap = scan_end > 0
        else:
            pending = b""
        position = int(skip_prefix)
        lowered = data.lower()
        has_fault_hint = any(hint in lowered for hint in FAULT_HINTS)
        if has_fault_hint:
            unfinalized = len(data) - scan_end
            data = compact_repeated_records(data)
            scan_end = len(data) - unfinalized
            lowered = data.lower()
        repeated_last = b""
        while has_fault_hint:
            match = LOWER_FAULT.search(lowered, position)
            if not match or match.start() >= scan_end:
                break
            start = data.rfind(b"\n", 0, match.start()) + 1
            end = data.find(b"\n", match.start())
            end = len(data) if end < 0 else end + 1
            record = data[start:end]
            # Only normalize a leading logger timestamp; different targets,
            # codes and payloads remain distinct evidence. Dense retries retain
            # the actual latest record rather than allocating overlapping windows.
            signature = LEADING_TIME.sub(b"", record) if len(record) <= 8192 else record
            if signature not in distinct_signatures and len(distinct_faults) < 48 * 1024:
                # Retry representatives can still fill the recency queue. Keep
                # the first original record for each distinct target/cause so
                # a unique middle root survives later retry epochs.
                distinct_signatures.add(signature)
                distinct_faults.extend(record[:min(4096, 48 * 1024 - len(distinct_faults))])
            position = end
            if signature == previous_signature:
                repeated_last = record
                continue
            previous_signature = signature
            repeated_last = b""
            value, _ = context(data, match.start())
            if len(first_faults) < 16 * 1024:
                first_faults.extend(value[:16 * 1024 - len(first_faults)])
            faults.append(value)
            fault_bytes += len(value)
            while fault_bytes > 96 * 1024 and faults:
                fault_bytes -= len(faults.popleft())
        if repeated_last:
            faults.append(repeated_last)
            fault_bytes += len(repeated_last)
            while fault_bytes > 96 * 1024 and faults:
                fault_bytes -= len(faults.popleft())
        # Keep first and last warning contexts per block, rather than building
        # an overlapping eight-line window for every duplicate queue warning.
        warning = LOWER_WARNING.search(lowered, int(skip_prefix)) if b"warn" in lowered else None
        if warning:
            value, _ = context(data, warning.start())
            windows.append(value)
            warning_bytes += len(value)
            last_start = max(0, data.rfind(b"\n", 0, max(0, len(data) - 1)) + 1)
            last = data[last_start:]
            if last != value:
                windows.append(last[-8192:])
                warning_bytes += len(last[-8192:])
            while warning_bytes > 96 * 1024 and windows:
                warning_bytes -= len(windows.popleft())
    if scanned == size and document is not None:
        document_text = document.decode("utf-8", errors="replace")
        if window is not None:
            from .diagnostic_time_window import merge_context
            merge_context(window, document_text)
            rows = feedback_observations(document_text, LIMIT - 1, window=window)
            if rows:
                return "\n".join(rows).encode(), scanned, False
        if size <= LIMIT:
            return bytes(document), scanned, False
        # Structured producer observations must be extracted before lossy log
        # sampling breaks the JSON envelope. The attachment stays authoritative.
        rows = feedback_observations(document_text, LIMIT - 1)
        if rows:
            return "\n".join(rows).encode(), scanned, False
    fault_sample = bytes(first_faults) + bytes(distinct_faults) + b"".join(faults)
    last = bytes(tail)
    warning_sample = b"".join(windows)[-(LIMIT - len(head) - len(last) - len(fault_sample) - 128):]
    sample = (bytes(head) + b"\n[fault context]\n" + fault_sample
              + b"\n[matched error context]\n" + warning_sample + b"\n[log tail]\n" + last)
    return sample[:LIMIT], scanned, scanned < size
