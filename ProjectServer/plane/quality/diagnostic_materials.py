# SPDX-License-Identifier: AGPL-3.0-only
"""Read bounded text from verified attachments; ZIP entries never become disk paths."""

import json
from pathlib import Path
import time
import zipfile
from .attachments import directory, validate_archive
from rest_framework.exceptions import ValidationError
from .models import PackageFile
from .log_evidence import collect, summarize
from .diagnostic_time_window import event_context, select_sample
from .attachment_chunks import MAX_DIAGNOSTIC_BYTES, digest_stream
from plane.knowledge.retrieval import scan_content
import re

TEXT_TYPES = {".log", ".txt", ".json", ".csv", ".md", ".yaml", ".yml"}
TOTAL_BYTES = 1024 * 1024
FILE_BYTES = 256 * 1024


def bounded_preview(text, budget):
    """Apply a UTF-8 byte budget before sampling so a final fault is not sliced off."""
    limit = min(FILE_BYTES, max(0, budget))
    if not limit:
        return b""
    preview = summarize(text, limit)
    if len(preview.encode()) > limit:
        preview = summarize(text, max(1, limit // 4))
    return preview.encode()[:limit].decode("utf-8", errors="ignore").encode()


def redact(text):
    text = re.sub(
        r"-----BEGIN [^-\n]*PRIVATE KEY-----.*?(?:-----END [^-\n]*PRIVATE KEY-----|\Z)",
        "[私钥内容已隐藏]",
        text,
        flags=re.S,
    )
    sensitive_key = re.compile(
        r"(?i)^(?:password|passwd|pwd|api[_-]?key|client[_-]?secret|access[_-]?token|refresh[_-]?token|secret|token|authorization|proxy-authorization|cookie|set-cookie|密码|密钥|口令|访问令牌)$"
    )

    def sanitize(value, depth=0):
        if depth > 32:
            return "[结构超过解析深度]"
        if isinstance(value, dict):
            return {
                key: "[已脱敏]" if sensitive_key.fullmatch(key) else sanitize(item, depth + 1)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [sanitize(item, depth + 1) for item in value]
        if isinstance(value, str):
            if value.lstrip().startswith(("{", "[")):
                try:
                    return json.dumps(sanitize(json.loads(value), depth + 1), ensure_ascii=False)
                except (ValueError, TypeError, RecursionError):
                    pass
            if scan_content(value):
                return "[已脱敏]"
        return value

    def line_value(line):
        if len(line) <= TOTAL_BYTES and line.lstrip().startswith(("{", "[")):
            try:
                value = json.loads(line)
                cleaned = json.dumps(sanitize(value), ensure_ascii=False)
                if not scan_content(cleaned):
                    return cleaned
            except (ValueError, TypeError, RecursionError):
                pass
        return "[疑似敏感信息已隐藏]" if scan_content(line) else line

    # Whole structured documents may put a credential key and its value on different lines.
    if len(text) <= TOTAL_BYTES and text.lstrip().startswith(("{", "[")):
        try:
            cleaned = json.dumps(sanitize(json.loads(text)), ensure_ascii=False)
            if not scan_content(cleaned):
                return cleaned
        except (ValueError, TypeError, RecursionError):
            pass
    result = "\n".join(line_value(line) for line in text.splitlines())
    return "[疑似敏感信息已隐藏]" if scan_content(result) else result


def inspect(job, materials=None, *, coverage=None):
    """Optionally retain authorized, bounded sanitized text in memory, never job.result."""
    snapshot = job.result.get("input", {})
    text = redact(snapshot.get("title", job.defect.title) + "\n" + snapshot.get("description", job.defect.description))
    sources = []
    window = event_context(redact(snapshot.get("title", job.defect.title)))
    remaining = TOTAL_BYTES
    deadline = time.monotonic() + 18
    query = PackageFile.objects.filter(project=job.project, package__defect=job.defect)
    if "files" in snapshot:
        query = query.filter(pk__in=snapshot["files"])
    files = list(query.order_by("created_at")[:1000])
    entries = {}
    if coverage is not None:
        for file in files:
            suffix = Path(file.name).suffix.lower()
            kind = (
                "text"
                if suffix in TEXT_TYPES
                else "archive"
                if suffix == ".zip"
                else "image"
                if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
                else "other"
            )
            entry = {
                "file_id": str(file.id),
                "name": file.name,
                "kind": kind,
                "status": "not_read",
                "reason": "材料尚未读取",
                "verified": False,
            }
            entries[str(file.id)] = entry
            coverage.append(entry)
    ocr_attempts = 0
    # Scan text first so optional OCR cannot evict a usable log from this task's budget.
    files.sort(key=lambda file: (Path(file.name).suffix.lower() == ".png", file.size))
    for file_index, file in enumerate(files):
        coverage_entry = entries.get(str(file.id))
        source_start = len(sources)
        if time.monotonic() >= deadline:
            if coverage_entry is not None and coverage_entry["kind"] == "image":
                coverage_entry.update(status="not_read", reason="图片读取预算已用完")
                continue
            sources.append(incomplete(file, "材料扫描总时间预算耗尽"))
            break
        path = directory() / file.storage_key
        if path.parent != directory() or path.is_symlink():
            continue
        suffix = Path(file.name).suffix.lower()
        if suffix not in TEXT_TYPES | {".zip"} and coverage is None:
            continue
        try:
            if path.stat().st_size != file.size or file.size > MAX_DIAGNOSTIC_BYTES:
                if coverage_entry is not None:
                    coverage_entry["reason"] = "材料大小校验失败"
                sources.append(incomplete(file, "材料大小校验失败"))
                continue
            with path.open("rb") as handle:
                digest = digest_stream(handle)
            if digest != file.sha256:
                if coverage_entry is not None:
                    coverage_entry["reason"] = "材料SHA256校验失败"
                sources.append(incomplete(file, "材料SHA256校验失败"))
                continue
            if coverage_entry is not None:
                coverage_entry["verified"] = True
            if suffix == ".png" and coverage_entry is not None:
                from .diagnostic_image_text import extract_png

                ocr_attempts += 1
                if ocr_attempts > 3 or remaining <= 0:
                    coverage_entry.update(status="not_read", reason="图片读取预算已用完")
                    continue
                with path.open("rb") as handle:
                    extracted = extract_png(file, handle, max(0, deadline - time.monotonic()))
                reasons = {
                    "ocr_no_text": "未识别到图片文字",
                    "ocr_busy": "图片文字识别繁忙",
                    "ocr_timeout": "图片文字识别超时",
                    "ocr_configuration": "图片文字识别暂不可用",
                    "ocr_unavailable": "图片文字识别暂不可用",
                    "ocr_time_budget": "图片读取预算已用完",
                    "ocr_sensitive_text": "图片文字包含敏感内容，未用于诊断",
                }
                if extracted["status"] != "read":
                    coverage_entry.update(
                        status="not_read", reason=reasons.get(extracted["reason"], "图片文字识别未完成")
                    )
                    continue
                clean = redact(extracted["text"])
                clean = clean.encode()[: min(FILE_BYTES, remaining)].decode("utf-8", errors="ignore")
                if not clean:
                    coverage_entry.update(status="not_read", reason="未取得可用于诊断的图片文字")
                    continue
                reference = f"FILE-{file.id}"
                remaining -= len(clean.encode())
                if materials is not None:
                    materials[reference] = {
                        "content": clean,
                        "truncated": len(clean) < len(extracted["text"]),
                        "origin": "image_ocr",
                        "requires_review": True,
                    }
                text += "\n[" + reference + "] 图片文字识别，未经人工核对，不代表已分析画面\n" + summarize(clean, 8000)
                sources.append(
                    {
                        "file_id": str(file.id),
                        "name": file.name,
                        "sha256": file.sha256,
                        "excerpt": summarize(clean),
                        "read_bytes": len(clean.encode()),
                        "text_bytes": len(clean.encode()),
                        "file_bytes": file.size,
                        "scanned_bytes": file.size,
                        "original_bytes_scope": "image_ocr",
                        "origin": "image_ocr",
                        "requires_review": True,
                        "scan_incomplete": False,
                        "preview_truncated": len(clean) > 8000,
                        "truncated": len(clean) < len(extracted["text"]),
                    }
                )
                coverage_entry.update(status="analyzed", reason="已提取图片文字，需核对原图")
                continue
            if suffix not in TEXT_TYPES | {".zip"}:
                if coverage_entry is not None:
                    coverage_entry.update(
                        status="unsupported",
                        reason="当前诊断未读取图片内容"
                        if coverage_entry["kind"] == "image"
                        else "当前诊断不支持此文件格式",
                    )
                continue
            if suffix == ".zip":
                with path.open("rb") as handle:
                    validate_archive(handle, file.name)
                with zipfile.ZipFile(path) as archive:
                    readable = sorted(
                        (entry for entry in archive.infolist()
                         if not entry.is_dir() and Path(entry.filename).suffix.lower() in TEXT_TYPES),
                        key=lambda entry: entry.file_size,
                    )
                    for entry_index, entry in enumerate(readable):
                        # Reserve output for every remaining entry/attachment.
                        # Small metadata and node logs cannot be starved by the
                        # first high-volume capture stream in ZIP insertion order.
                        slots = len(readable) - entry_index + len(files) - file_index - 1
                        entry_budget = remaining // max(1, slots)
                        if time.monotonic() >= deadline:
                            source = incomplete(file, "ZIP材料扫描总时间预算耗尽")
                            source.update(archive_entry=entry.filename, file_bytes=entry.file_size)
                            sources.append(source)
                            continue
                        with archive.open(entry) as stream:
                            bytes_left = sum(item.file_size for item in readable[entry_index:])
                            now = time.monotonic()
                            entry_deadline = min(deadline, now + max(0.05, max(0, deadline - now) * entry.file_size / max(1, bytes_left)))
                            sample, scanned, scan_incomplete = collect(stream, entry.file_size, entry_deadline, window=window)
                            sample, selection = select_sample(sample, window)
                            selection.update(integrity_scan_scope='incomplete' if scan_incomplete else 'full_sequential',
                                             integrity_scanned_bytes=scanned, model_selected_bytes=len(sample))
                            sample = bounded_preview(sample.decode("utf-8", errors="replace"), entry_budget)
                        clean = redact(sample.decode("utf-8", errors="replace"))
                        clean_bytes = clean.encode()
                        clean = clean_bytes[: min(FILE_BYTES, remaining)].decode("utf-8", errors="ignore")
                        remaining -= len(clean.encode())
                        if materials is not None:
                            materials[f"FILE-{file.id}:{entry.filename}"] = {
                                "content": clean,
                                "truncated": scan_incomplete
                                or entry.file_size > len(sample)
                                or len(clean.encode()) < len(clean_bytes),
                            }
                        text += "\n[" + f"FILE-{file.id}:{entry.filename}" + "]\n" + json.dumps({'evidence_selection': selection}, ensure_ascii=False) + "\n" + summarize(clean, 8000)
                        sources.append(
                            {
                                "file_id": str(file.id),
                                "name": file.name,
                                "archive_entry": entry.filename,
                                **selection,
                                "excerpt": summarize(clean),
                                "sha256": file.sha256,
                                "read_bytes": len(sample),
                                "file_bytes": entry.file_size,
                                "scanned_bytes": scanned,
                                "scan_incomplete": scan_incomplete,
                                "preview_truncated": len(clean) > 8000,
                                "truncated": entry.file_size > len(sample),
                            }
                        )
            else:
                with path.open("rb") as handle:
                    sample, scanned, scan_incomplete = collect(handle, file.size, deadline, window=window)
                    sample, selection = select_sample(sample, window)
                    selection.update(integrity_scan_scope='incomplete' if scan_incomplete else 'full_sequential',
                                     integrity_scanned_bytes=scanned, model_selected_bytes=len(sample))
                    file_budget = remaining // max(1, len(files) - file_index)
                    sample = bounded_preview(sample.decode("utf-8", errors="replace"), file_budget)
                clean = redact(sample.decode("utf-8", errors="replace"))
                clean_bytes = clean.encode()
                clean = clean_bytes[: min(FILE_BYTES, remaining)].decode("utf-8", errors="ignore")
                remaining -= len(clean.encode())
                if materials is not None:
                    materials[f"FILE-{file.id}"] = {
                        "content": clean,
                        "truncated": scan_incomplete
                        or file.size > len(sample)
                        or len(clean.encode()) < len(clean_bytes),
                    }
                text += "\n[" + f"FILE-{file.id}" + "]\n" + json.dumps({'evidence_selection': selection}, ensure_ascii=False) + "\n" + summarize(clean, 8000)
                sources.append(
                    {
                        "file_id": str(file.id),
                        "name": file.name,
                        "excerpt": summarize(clean),
                        "sha256": file.sha256,
                        "read_bytes": len(sample),
                        "file_bytes": file.size,
                        "scanned_bytes": scanned,
                        **selection,
                        "scan_incomplete": scan_incomplete,
                        "preview_truncated": len(clean) > 8000,
                        "truncated": file.size > len(sample),
                    }
                )
        except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, ValidationError):
            if coverage_entry is not None:
                coverage_entry.update(status="not_read", reason="材料读取或ZIP校验失败")
            sources.append(incomplete(file, "材料读取或ZIP校验失败"))
            continue
        if coverage_entry is not None:
            read = sources[source_start:]
            if (
                read
                and any(row.get("read_bytes", 0) > 0 for row in read)
                and not any(row.get("scan_incomplete") for row in read)
            ):
                coverage_entry.update(status="analyzed", reason="")
            elif not read:
                coverage_entry.update(status="unsupported", reason="压缩包内没有可读取的文本")
            else:
                coverage_entry.update(status="not_read", reason="材料未完整读取")
    findings = []
    for key, title, pattern in [
        ("timeout", "超时", r"\btimeout\b(?!\s*[:=]\s*\d)|\b(?:API)?TimeoutError\b|timed out|超时"),
        ("connection", "连接失败", r"connection refused|连接失败|network unreachable"),
        ("error", "错误记录", r"\berror\b|exception|traceback|异常"),
    ]:
        matches = [line[:300] for line in text.splitlines() if re.search(pattern, line, re.I)][:10]
        if matches:
            findings.append({"kind": key, "title": title, "samples": matches})
    return text, sources, findings


def incomplete(file, reason):
    return {
        "file_id": str(file.id),
        "name": file.name,
        "sha256": file.sha256,
        "excerpt": reason,
        "read_bytes": 0,
        "file_bytes": file.size,
        "scanned_bytes": 0,
        "scan_incomplete": True,
        "preview_truncated": False,
        "truncated": True,
    }


def diagnostic_search_query(text, sources):
    """Retrieve by observed exception/code facts before lossy summaries and metadata tokens."""
    preflights = []
    for source in sources[:1000] if isinstance(sources, (list, tuple)) else []:
        excerpt = source.get("excerpt", "") if isinstance(source, dict) else ""
        if not isinstance(excerpt, str):
            continue
        for line in excerpt[:FILE_BYTES].splitlines():
            if '"record_preflight"' not in line or scan_content(line):
                continue
            try:
                record = json.loads(line)
            except (TypeError, ValueError):
                continue
            if not isinstance(record, dict):
                continue
            event = record.get("record_preflight")
            if isinstance(event, dict) and isinstance(event.get("diagnosis"), dict):
                preflights.append((str(record.get("time", "")), event))
    if preflights:
        _, event = max(preflights, key=lambda row: row[0])
        tokens = [event.get("code", "")]
        results = event["diagnosis"].get("results", [])
        for row in results[:100] if isinstance(results, list) else []:
            if isinstance(row, dict) and row.get("ok") is False:
                tokens.append(row.get("code", ""))
        valid = [
            token for token in tokens if isinstance(token, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{1,119}", token)
        ]
        if valid:
            return " ".join(dict.fromkeys(valid))[:2000]
    tokens = []
    for source in sources[:1000] if isinstance(sources, (list, tuple)) else []:
        excerpt = source.get("excerpt", "") if isinstance(source, dict) else ""
        if not isinstance(excerpt, str):
            continue
        # Logger tracebacks are often escaped inside one JSON record. Do not parse/evaluate log code.
        for line in excerpt[:FILE_BYTES].replace("\\n", "\n").replace("\\r", "\r").splitlines():
            if scan_content(line):
                continue
            tokens.extend(re.findall(r"\b([A-Za-z_][A-Za-z0-9_]{0,80}(?:Error|Exception))\b", line))
            tokens.extend(re.findall(r"\bE-[A-Z][A-Z0-9]*(?:-[A-Z0-9]+){0,4}\b", line))
            tokens.extend(
                re.findall(
                    r"(?i)\b(?:code|failure_class|failure_reason|exception_type)[\"']?\s*[:=]\s*[\"']?([a-z][a-z0-9_]{2,119})",
                    line,
                )
            )
            tokens.extend(
                re.findall(r"\b[a-z][a-z0-9_]{2,100}_(?:quota_exceeded|integrity_failed|timestamp_invalid)\b", line)
            )
            tokens.extend(re.findall(r"\b[A-Z][A-Z0-9_]{2,60}_(?:MISSING|REQUIRED|INVALID|FAILED|UNAVAILABLE)\b", line))
            tokens.extend("errno" + code for code in re.findall(r"\b(?:Errno|errno)[ =:]*([0-9]{1,4})\b", line))
            tokens.extend(
                re.findall(
                    r"\b(?:connection refused|no space left on device|permission denied|network unreachable)\b",
                    line,
                    re.I,
                )
            )
            tokens.extend(
                re.findall(r"\b([a-z][a-z0-9_]{1,60})\s*(?:不能为空|缺失|is required|is missing)", line, re.I)
            )
    if tokens:
        return " ".join(dict.fromkeys(tokens))[:2000]
    signatures = []
    for source in sources[:1000] if isinstance(sources, (list, tuple)) else []:
        excerpt = source.get("excerpt", "") if isinstance(source, dict) else ""
        if not isinstance(excerpt, str):
            continue
        for line in excerpt[:FILE_BYTES].replace("\\n", "\n").splitlines():
            if scan_content(line):
                continue
            match = re.search(r"(?<![A-Za-z0-9_=])(?:ERROR|FATAL)(?:\s|:)([^\r\n]{1,300})", line)
            if match:
                signature = re.sub(r"\b(?:synthetic|simulated)=true\s*", "", match[1]).strip()
                if signature:
                    signatures.append(signature)
    if signatures:
        return " ".join(dict.fromkeys(signatures))[:2000]
    # Normal/status observations also carry mechanism identity; generic report templates do not.
    status_tokens = []
    message_type_observed = False
    upload_resume_observed = False
    mode_switch_observed = False
    fields = {
        "active_mode",
        "sequence_input",
        "ingress_stamp_advancing",
        "each_conflict_span_below_configured_delay",
        "module_bit32",
        "module_bit33",
        "input_mode",
        "video_input_mode",
        "preflight_invocations",
        "latest_preflight_ok",
        "grant_age_sec",
        "grant_expires_in_sec",
        "input_mode_conflict_warning_delay_sec",
        "channel_status",
        "next_channel_status",
        "error_confirm_cycles",
        "consecutive_error_cycles",
        "module_error_bit",
        "forced",
        "capture_aborted",
        "raw_status",
        "derived_status",
        "received",
        "queued",
        "written",
        "queue_drops",
        "write_errors",
        "image_timestamp_drops",
        "current_action",
        "requested_input_mode",
        # Fixed monitor/continuation observations; preserve field names, never values.
        "publisher_type",
        "monitor_config_type",
        "callback_received",
        "persisted_status",
        "restored_status",
        "manualPaused",
        "pauseReason",
        "final_complete_response",
    }
    for source in sources[:1000] if isinstance(sources, (list, tuple)) else []:
        excerpt = source.get("excerpt", "") if isinstance(source, dict) else ""
        if not isinstance(excerpt, str):
            continue
        excerpt_fields = set()
        excerpt_statuses = {}
        for line in excerpt[:FILE_BYTES].replace("\\n", "\n").splitlines()[:1000]:
            if scan_content(line):
                continue
            status_tokens.extend(re.findall(r"\[([A-Z][A-Z0-9]{1,30}(?:_[A-Z0-9]{1,30})+)\]", line))
            status_tokens.extend(re.findall(r"\bIMAGE_TIMESTAMP_FILTER_DROP\b", line))
            status_tokens.extend(
                re.findall(
                    r"\bwarning[\"']?\s*[:=]\s*[\"']?([a-z][a-z0-9_]{2,80}_(?:failed|unavailable|aborted))\b",
                    line,
                )
            )
            # Match logger assignments and JSON keys without decoding/traversing arbitrary payloads.
            for key in re.findall(r"\b([A-Za-z][A-Za-z0-9_]{2,80})[\"']?\s*[:=]", line):
                if key in fields:
                    status_tokens.append(key)
                    excerpt_fields.add(key)
            for key, value in re.findall(
                r"\b(persisted_status|restored_status|final_complete_response)"
                r"[\"']?\s*[:=]\s*[\"']?([^\s\"',;}\]]{1,120})[^\s\"',;}\]]*(?=$|[\s\"',;}\]]|\\n)",
                line,
            ):
                normalized = value.casefold()
                excerpt_statuses[key] = (
                    normalized
                    if normalized in {"uploading", "interrupted", "not_observed", "false", "missing"}
                    else None
                )
        if {"publisher_type", "monitor_config_type", "callback_received"} <= excerpt_fields:
            message_type_observed = True
        if {"current_action", "requested_input_mode"} <= excerpt_fields:
            mode_switch_observed = True
        if (
            excerpt_statuses.get("persisted_status") == "uploading"
            and excerpt_statuses.get("restored_status") == "interrupted"
            and excerpt_statuses.get("final_complete_response") in {"not_observed", "false", "missing"}
        ):
            upload_resume_observed = True
    if status_tokens:
        if message_type_observed:
            status_tokens.extend(["监控", "订阅", "消息类型", "QoS"])
        if upload_resume_observed:
            status_tokens.extend(["上传", "续传", "分片"])
        if mode_switch_observed:
            status_tokens.extend(["模式切换", "接口", "状态"])
        return " ".join(dict.fromkeys(status_tokens))[:2000]
    # Non-error material retains the prior natural-language retrieval behavior, with sensitive lines removed.
    safe = redact(text.split("\n[FILE-", 1)[0]) if isinstance(text, str) else ""
    return summarize(safe, 2000) if safe else ""
