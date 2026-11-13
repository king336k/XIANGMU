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


def inspect(job, materials=None):
    """Optionally retain authorized, bounded sanitized text in memory, never job.result."""
    snapshot = job.result.get("input", {})
    text = redact(snapshot.get("title", job.defect.title) + "\n" + snapshot.get("description", job.defect.description))
    sources = []
    remaining = TOTAL_BYTES
    deadline = time.monotonic() + 18
    query = PackageFile.objects.filter(project=job.project, package__defect=job.defect)
    if "files" in snapshot:
        query = query.filter(pk__in=snapshot["files"])
    for file in query.order_by("created_at")[:1000]:
        if time.monotonic() >= deadline:
            sources.append(incomplete(file, "材料扫描总时间预算耗尽"))
            break
        path = directory() / file.storage_key
        if path.parent != directory() or path.is_symlink():
            continue
        suffix = Path(file.name).suffix.lower()
        if suffix not in TEXT_TYPES | {".zip"}:
            continue
        try:
            if path.stat().st_size != file.size or file.size > MAX_DIAGNOSTIC_BYTES:
                sources.append(incomplete(file, "材料大小校验失败"))
                continue
            with path.open("rb") as handle:
                digest = digest_stream(handle)
            if digest != file.sha256:
                sources.append(incomplete(file, "材料SHA256校验失败"))
                continue
            if suffix == ".zip":
                with path.open("rb") as handle:
                    validate_archive(handle, file.name)
                with zipfile.ZipFile(path) as archive:
                    for entry in archive.infolist():
                        if time.monotonic() >= deadline:
                            sources.append(incomplete(file, "ZIP材料扫描总时间预算耗尽"))
                            break
                        if entry.is_dir() or Path(entry.filename).suffix.lower() not in TEXT_TYPES:
                            continue
                        with archive.open(entry) as stream:
                            sample, scanned, scan_incomplete = collect(stream, entry.file_size, deadline)
                            sample = bounded_preview(sample.decode("utf-8", errors="replace"), remaining)
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
                        text += "\n[" + f"FILE-{file.id}:{entry.filename}" + "]\n" + summarize(clean, 8000)
                        sources.append(
                            {
                                "file_id": str(file.id),
                                "name": file.name,
                                "archive_entry": entry.filename,
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
                    sample, scanned, scan_incomplete = collect(handle, file.size, deadline)
                    sample = bounded_preview(sample.decode("utf-8", errors="replace"), remaining)
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
                text += "\n[" + f"FILE-{file.id}" + "]\n" + summarize(clean, 8000)
                sources.append(
                    {
                        "file_id": str(file.id),
                        "name": file.name,
                        "excerpt": summarize(clean),
                        "sha256": file.sha256,
                        "read_bytes": len(sample),
                        "file_bytes": file.size,
                        "scanned_bytes": scanned,
                        "scan_incomplete": scan_incomplete,
                        "preview_truncated": len(clean) > 8000,
                        "truncated": file.size > len(sample),
                    }
                )
        except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, ValidationError):
            sources.append(incomplete(file, "材料读取或ZIP校验失败"))
            continue
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
    # Non-error material retains the prior natural-language retrieval behavior, with sensitive lines removed.
    safe = redact(text.split("\n[FILE-", 1)[0]) if isinstance(text, str) else ""
    return summarize(safe, 2000) if safe else ""
