"""Credential redaction shared by evidence readers and task results."""

import json
import re
from plane.knowledge.retrieval import scan_content

TOTAL_BYTES = 1024 * 1024


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
