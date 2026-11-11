# SPDX-License-Identifier: AGPL-3.0-only
"""Verify request-bound device signatures for the dedicated DAQ reporting boundary."""

import base64
import hashlib
import hmac
import json
import re
import time
from urllib.parse import urlsplit
from django.core.cache import cache
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed


def encode(value):
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def target_path(value):
    parts = urlsplit(value)
    if parts.scheme or parts.netloc or parts.fragment or not value.startswith("/"):
        raise AuthenticationFailed("无效的桥接请求路径。")

    def normalize(match):
        char = chr(int(match.group(1), 16))
        if ord(char) < 32 or ord(char) == 127 or char == "\\":
            raise AuthenticationFailed("无效的桥接请求路径。")
        return char if char.isascii() and (char.isalnum() or char in "-._~") else "%" + match.group(1).upper()

    if re.search(r"%(?![a-fA-F0-9]{2})", value) or re.search(r"[\x00-\x20\x7f\\]", value):
        raise AuthenticationFailed("无效的桥接请求路径。")
    path = re.sub(r"%([a-fA-F0-9]{2})", normalize, value)
    if any(piece in [".", ".."] for piece in path.split("?")[0].split("/")):
        raise AuthenticationFailed("无效的桥接请求路径。")
    return path


class PlatformBridgeAuthentication(BaseAuthentication):
    def project_scope(self, request, config):
        return request.parser_context["kwargs"].get("project_id")

    def verified_principal(self, request):
        """Verify the same V2 signature and consume its nonce before choosing any scope."""
        headers = request.headers
        if not headers.get("X-Issue-Identity-Version"):
            return None
        if headers.get("X-Issue-Identity-Version") != "2":
            raise AuthenticationFailed("仅接受可信身份V2。")
        try:
            config = self.key_config(headers.get("X-Issue-Key-Id"))
        except (ValueError, TypeError, AttributeError):
            raise AuthenticationFailed("桥接签名配置无效。")
        if not config or not config.get("secret"):
            raise AuthenticationFailed("桥接签名未配置或密钥编号无效。")
        audience = headers.get("X-Issue-Audience", "")
        key_id = headers.get("X-Issue-Key-Id", "")
        principal = headers.get("X-Issue-Principal", "")
        stamp = headers.get("X-Issue-Principal-Timestamp", "")
        nonce = headers.get("X-Issue-Principal-Nonce", "")
        if (
            audience != config.get("audience")
            or len(principal) > 2000
            or not re.fullmatch(r"[a-zA-Z0-9_-]{16,80}", nonce)
        ):
            raise AuthenticationFailed("桥接身份格式无效。")
        try:
            if abs(time.time() - int(stamp)) > 60:
                raise ValueError()
            user = json.loads(principal)
            external_id = user["id"]
            if not isinstance(external_id, int) or isinstance(external_id, bool) or external_id <= 0:
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            raise AuthenticationFailed("桥接身份已过期或无效。")
        if request.method in ["GET", "HEAD"]:
            body_digest = "-"
        else:
            from io import BytesIO

            raw_request = request._request
            # Read a bounded stream and restore it for DRF's normal parser.
            body = raw_request.read(50 * 1024 * 1024 + 1)
            if len(body) > 50 * 1024 * 1024:
                raise AuthenticationFailed("桥接请求超过允许大小。")
            raw_request._body = body
            raw_request._stream = BytesIO(body)
            content_type = headers.get("Content-Type", "")
            body_digest = (
                multipart_digest(body, content_type)
                if content_type.lower().startswith("multipart/")
                else hashlib.sha256(body).hexdigest()
            )
        if not hmac.compare_digest(body_digest, headers.get("X-Issue-Content-SHA256", "")):
            raise AuthenticationFailed("桥接内容摘要不匹配。")
        canonical = "\n".join(
            [
                "ISSUE-IDENTITY-V2",
                encode(audience),
                encode(key_id),
                stamp,
                encode(nonce),
                request.method.upper(),
                encode(target_path(request.get_full_path())),
                body_digest,
                encode(principal),
            ]
        )
        signature = (
            base64.urlsafe_b64encode(hmac.new(config["secret"].encode(), canonical.encode(), hashlib.sha256).digest())
            .decode()
            .rstrip("=")
        )
        if not hmac.compare_digest(signature, headers.get("X-Issue-Principal-Signature", "")):
            raise AuthenticationFailed("桥接签名无效。")
        replay = "quality-bridge-nonce:" + hashlib.sha256((key_id + ":" + nonce).encode()).hexdigest()
        if not cache.add(replay, True, timeout=125):
            raise AuthenticationFailed("桥接请求已使用，请重新签发。")
        return config, external_id

    def key_config(self, key_id):
        # The retired data-platform signature cannot authorize platform APIs.
        return None

    def authenticate(self, request):
        if request.headers.get("X-Issue-Identity-Version"):
            raise AuthenticationFailed("仅独立DAQ反馈接口接受设备签名。")
        return None


def multipart_digest(body, content_type):
    from email.parser import BytesParser
    from email.policy import default

    if len(body) > 50 * 1024 * 1024:
        raise AuthenticationFailed("桥接附件超过允许大小。")
    # The platform bridge emits one plain name and optional filename per part.
    for match in re.finditer(rb"(?im)^Content-Disposition:[^\r\n]*", body):
        header = match.group().decode("latin-1")
        params = re.findall(r";\s*([^=;\s]+)\s*=", header)
        normalized = [name.lower() for name in params]
        if any("*" in name for name in normalized) or len(normalized) != len(set(normalized)):
            raise AuthenticationFailed("桥接附件包含重复或扩展参数。")
    message = BytesParser(policy=default).parsebytes(
        ("Content-Type: " + content_type + "\r\nMIME-Version: 1.0\r\n\r\n").encode() + body
    )
    if not message.is_multipart():
        raise AuthenticationFailed("桥接附件格式无效。")
    parts = list(message.iter_parts())
    if len(parts) > 16:
        raise AuthenticationFailed("桥接附件数量超限。")
    lines = ["ISSUE-MULTIPART-MANIFEST-V1"]
    aggregate = 0
    for index, part in enumerate(parts):
        if part.get("Content-Transfer-Encoding") or any(
            len(part.get_all(header, [])) > 1 for header in ["Content-Disposition", "Content-Type"]
        ):
            raise AuthenticationFailed("桥接附件包含不支持的编码或重复元数据。")
        name = part.get_param("name", header="content-disposition") or ""
        filename = part.get_filename() or ""
        kind = str(part.get("Content-Type", ""))
        raw = part.get_payload(decode=True)
        if not isinstance(raw, bytes) or len(raw) > 20 * 1024 * 1024:
            raise AuthenticationFailed("桥接附件格式或大小无效。")
        aggregate += len(raw)
        if aggregate > 50 * 1024 * 1024:
            raise AuthenticationFailed("桥接附件总大小超限。")
        lines.extend(
            [str(index), encode(name), encode(filename), encode(kind), str(len(raw)), hashlib.sha256(raw).hexdigest()]
        )
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()
