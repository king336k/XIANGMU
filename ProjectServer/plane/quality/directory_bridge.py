# SPDX-License-Identifier: AGPL-3.0-only
"""Sign only bounded legacy-directory GETs using a server-approved identity and origin."""

import hashlib
import hmac
import json
import os
import time
from uuid import uuid4
from django.conf import settings
import requests
from .identity import encode
from .platform import PlatformUnavailable


def directory_headers(config, path, params):
    if config.get("kind") != "legacy_hub" or path != "/api/admin/users":
        raise PlatformUnavailable("签名连接仅允许只读账号目录查询。")
    if (
        not isinstance(params, dict)
        or set(params) != {"page", "size"}
        or type(params["page"]) is not int
        or not 1 <= params["page"] <= 40
        or params["size"] != 100
    ):
        raise PlatformUnavailable("账号目录分页参数无效。")
    try:
        keys = getattr(settings, "QUALITY_BRIDGE_KEYS", None)
        if keys is None:
            keys = json.loads(os.environ.get("QUALITY_BRIDGE_KEYS_JSON", "{}"))
        key_id = config.get("directory_key_id")
        key = keys.get(key_id)
        origin = config.get("base_url", "").rstrip("/")
        user_id = config.get("directory_user_id")
        username = config.get("directory_username", "")
        if (
            not isinstance(key, dict)
            or not key.get("secret")
            or not key.get("audience")
            or not isinstance(key.get("directory_origins"), list)
            or origin not in key["directory_origins"]
            or type(user_id) is not int
            or user_id <= 0
            or user_id != key.get("directory_user_id")
            or not isinstance(username, str)
            or not username.strip()
            or len(username) > 64
            or not username.isascii()
            or any(ord(char) < 32 for char in username)
        ):
            raise ValueError()
        principal = json.dumps({"id": user_id, "username": username, "displayName": username}, separators=(",", ":"))
        stamp, nonce = str(int(time.time())), uuid4().hex
        target = requests.Request("GET", origin + path, params=params).prepare().path_url
        canonical = "\n".join(
            [
                "ISSUE-IDENTITY-V2",
                encode(key["audience"]),
                encode(key_id),
                stamp,
                encode(nonce),
                "GET",
                encode(target),
                "-",
                encode(principal),
            ]
        )
        signature = encode_bytes(hmac.new(key["secret"].encode(), canonical.encode(), hashlib.sha256).digest())
    except (ValueError, TypeError, AttributeError, KeyError):
        raise PlatformUnavailable("目录签名未获得服务器的源站与身份授权。")
    return {
        "X-Issue-Identity-Version": "2",
        "X-Issue-Key-Id": key_id,
        "X-Issue-Audience": key["audience"],
        "X-Issue-Principal": principal,
        "X-Issue-Principal-Timestamp": stamp,
        "X-Issue-Principal-Nonce": nonce,
        "X-Issue-Content-SHA256": "-",
        "X-Issue-Principal-Signature": signature,
    }


def encode_bytes(value):
    import base64

    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def directory_ready(config):
    if config.get("directory_auth", "bearer") != "trusted_v2":
        return bool(config.get("service_token"))
    try:
        directory_headers(config, "/api/admin/users", {"page": 1, "size": 100})
        return True
    except PlatformUnavailable:
        return False
