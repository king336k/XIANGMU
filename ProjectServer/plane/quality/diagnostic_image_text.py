"""Bounded local screenshot OCR. Returned text is unreviewed derived material only."""

import hashlib
import json
import math
import re
import struct
import time
from urllib.parse import urlsplit
import zlib

import requests

MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_RESPONSE_BYTES = 256 * 1024


def outcome(status, reason, text=""):
    return {"text": text, "status": status, "reason": reason}


def png_dimensions(raw):
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("invalid PNG")
    offset, chunks, dimensions, image_data = 8, 0, None, False
    while offset + 12 <= len(raw):
        length = struct.unpack(">I", raw[offset : offset + 4])[0]
        kind = raw[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > len(raw) or length > MAX_IMAGE_BYTES or chunks >= 4096:
            raise ValueError("invalid PNG chunk")
        data = raw[offset + 8 : offset + 8 + length]
        crc = struct.unpack(">I", raw[offset + 8 + length : end])[0]
        if crc != zlib.crc32(kind + data) & 0xFFFFFFFF:
            raise ValueError("invalid PNG checksum")
        if chunks == 0:
            if kind != b"IHDR" or length != 13:
                raise ValueError("missing PNG header")
            width, height = struct.unpack(">II", data[:8])
            if not 0 < width <= 3508 or not 0 < height <= 3508 or width * height > 9_000_000:
                raise ValueError("PNG dimensions exceed budget")
            dimensions = width, height
        elif kind == b"IHDR":
            raise ValueError("duplicate PNG header")
        if kind == b"IDAT":
            image_data = image_data or length > 0
        if kind == b"IEND":
            if length != 0 or end != len(raw) or not image_data:
                raise ValueError("invalid PNG end")
            return dimensions
        offset, chunks = end, chunks + 1
    raise ValueError("incomplete PNG")


def extract_png(file, handle, remaining_seconds):
    """Return local OCR candidate text; never treat it as verified runtime/module/severity evidence.

    The caller owns image-count and the enclosing inspection budget. HTTP socket
    phases and response size are bounded; monotonic checks reject late results.
    """
    from . import document_ocr
    from .document_imports import sensitive_content
    from ..knowledge.retrieval import scan_content

    if type(remaining_seconds) not in {int, float} or not math.isfinite(remaining_seconds) or remaining_seconds < 2:
        return outcome("unavailable", "ocr_time_budget")
    deadline = time.monotonic() + remaining_seconds
    if type(file.size) is not int or not 0 < file.size <= MAX_IMAGE_BYTES:
        return outcome("invalid", "image_size")
    if not isinstance(file.sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", file.sha256):
        return outcome("invalid", "image_integrity")
    try:
        handle.seek(0)
        raw = handle.read(MAX_IMAGE_BYTES + 1)
        if len(raw) != file.size or hashlib.sha256(raw).hexdigest() != file.sha256:
            return outcome("invalid", "image_integrity")
        width, height = png_dimensions(raw)
    except (OSError, ValueError, TypeError, struct.error):
        return outcome("invalid", "image_format")
    try:
        base, key = document_ocr.configuration()
        parts = urlsplit(base)
        if (
            parts.scheme != "http"
            or parts.hostname != "document-ocr"
            or parts.path
            or parts.query
            or parts.fragment
            or parts.username
            or parts.password
            or parts.port is None
            or not 1 <= parts.port <= 65535
        ):
            return outcome("unavailable", "ocr_configuration")
    except (document_ocr.OcrUnavailable, ValueError, TypeError):
        return outcome("unavailable", "ocr_configuration")
    remaining = deadline - time.monotonic()
    if remaining < 2:
        return outcome("unavailable", "ocr_time_budget")
    budget = min(8.0, remaining)
    connect = min(2.0, budget / 4)
    read = min(6.0, budget - connect)
    response = None
    try:
        with requests.Session() as session:
            session.trust_env = False
            response = session.post(
                base + "/v1/extract",
                data=raw,
                headers={
                    "Authorization": "Bearer " + key,
                    "Content-Type": "application/octet-stream",
                    "X-Document-Type": "png",
                    "X-Content-SHA256": file.sha256,
                },
                timeout=(connect, read),
                allow_redirects=False,
                stream=True,
            )
            if response.status_code == 429:
                return outcome("unavailable", "ocr_busy")
            if 300 <= response.status_code < 400:
                return outcome("unavailable", "ocr_redirect_rejected")
            if response.status_code != 200:
                return outcome("unavailable", "ocr_unavailable")
            data = bytearray()
            for block in response.iter_content(8192):
                if time.monotonic() >= deadline:
                    return outcome("unavailable", "ocr_time_budget")
                data.extend(block)
                if len(data) > MAX_RESPONSE_BYTES:
                    return outcome("invalid", "ocr_response_budget")
            result = json.loads(data)
            segments, failures = document_ocr.checked_result(result, file, ".png")
            if failures:
                if not segments and all(f.get("error") == "no_recognized_text" for f in result.get("failures", [])):
                    return outcome("no_text", "ocr_no_text")
                return outcome("unavailable", "ocr_incomplete")
            if any((s["width"], s["height"]) != (width, height) for s in segments):
                return outcome("invalid", "ocr_dimensions")
            text = "\n".join(s["text"] for s in segments).strip()
            if not text:
                return outcome("no_text", "ocr_no_text")
            if sensitive_content(text) or scan_content(text):
                return outcome("invalid", "ocr_sensitive_text")
            if time.monotonic() >= deadline:
                return outcome("unavailable", "ocr_time_budget")
            return outcome("read", "ocr_unreviewed", text)
    except requests.Timeout:
        return outcome("unavailable", "ocr_timeout")
    except requests.RequestException:
        return outcome("unavailable", "ocr_unavailable")
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        return outcome("invalid", "ocr_response_invalid")
    finally:
        if response is not None:
            response.close()
