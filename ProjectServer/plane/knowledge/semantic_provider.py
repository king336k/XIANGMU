"""Use the existing encrypted key, destination allowlist and installed OpenAI SDK."""

import hashlib
import json
import os
import ipaddress
import re
from urllib.parse import urlsplit
from openai import OpenAI


def configuration():
    from .assistant import model_option, provider_config

    builtin_url = os.environ.get("KNOWLEDGE_BUILTIN_EMBEDDING_BASE_URL", "").strip().rstrip("/")
    builtin_key = os.environ.get("KNOWLEDGE_BUILTIN_EMBEDDING_API_KEY", "")
    builtin_model = os.environ.get("KNOWLEDGE_BUILTIN_EMBEDDING_MODEL", "bge-small-zh-v1.5").strip()
    builtin_available = bool(builtin_url and builtin_key and valid_builtin_url(builtin_url))
    mode = model_option("KNOWLEDGE_EMBEDDING_MODE", "auto")
    legacy_url = model_option("KNOWLEDGE_EMBEDDING_BASE_URL", "").strip().rstrip("/")
    builtin = mode == "builtin" or (mode == "auto" and builtin_available and legacy_url in {"", builtin_url})
    enabled = (
        str(
            model_option(
                "KNOWLEDGE_SEMANTIC_ENABLED",
                os.environ.get("KNOWLEDGE_SEMANTIC_ENABLED", "true" if builtin else "false"),
            )
        ).lower()
        == "true"
    )
    model = model_option("KNOWLEDGE_EMBEDDING_MODEL", os.environ.get("KNOWLEDGE_EMBEDDING_MODEL", "")).strip()
    config = provider_config()
    separate_url = model_option("KNOWLEDGE_EMBEDDING_BASE_URL", "").strip().rstrip("/")
    source = "shared"
    if builtin:
        model = builtin_model
        source = "builtin"
        config = {"base_url": builtin_url, "api_key": builtin_key, "configured": builtin_available}
    elif separate_url:
        source = "external"
        separate_key = model_option("KNOWLEDGE_EMBEDDING_API_KEY", "")
        config = {
            "base_url": separate_url,
            "api_key": separate_key,
            "configured": bool(separate_key and valid_embedding_url(separate_url)),
        }
    elif mode == "external":
        source = "external"
        config = {"base_url": "", "api_key": "", "configured": False}
    fingerprint = hashlib.sha256(
        json.dumps([config.get("base_url", ""), model, "text-v2-350"], ensure_ascii=False).encode()
    ).hexdigest()
    return {
        **config,
        "enabled": enabled,
        "configured": bool(enabled and model and config.get("configured")),
        "model": model,
        "source": source,
        "fingerprint": fingerprint,
    }


def valid_builtin_url(url):
    try:
        parsed = urlsplit(url)
        if parsed.scheme != "http" or not valid_embedding_url(url):
            return False
        host = parsed.hostname or ""
        try:
            address = ipaddress.ip_address(host)
            return address.is_private and not (
                address.is_loopback or address.is_link_local or address.is_unspecified or address.is_multicast
            )
        except ValueError:
            return bool(re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9-]{0,62}", host)) and host.lower() != "localhost"
    except ValueError:
        return False


def valid_embedding_url(url):
    from .assistant import valid_provider_url

    if valid_provider_url(url):
        return True
    try:
        parsed = urlsplit(url)
        allowed = {
            origin.strip().rstrip("/")
            for origin in os.environ.get("KNOWLEDGE_EMBEDDING_ALLOWED_HTTP_ORIGINS", "").split(",")
            if origin.strip()
        }
        hostname = parsed.hostname or ""
        try:
            address = ipaddress.ip_address(hostname)
            private_destination = (
                address.is_private
                and not address.is_loopback
                and not address.is_link_local
                and not address.is_unspecified
                and not address.is_multicast
            )
        except ValueError:
            # Only an operator-supplied exact origin can enable a container DNS destination.
            private_destination = bool(re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?", hostname))
        return (
            parsed.scheme == "http"
            and private_destination
            and f"http://{parsed.netloc}" in allowed
            and not parsed.username
            and not parsed.password
            and not parsed.query
            and not parsed.fragment
            and parsed.port is not None
            and 1 <= parsed.port <= 65535
        )
    except ValueError:
        return False


def public_status(config=None):
    config = config or configuration()
    return {
        "enabled": config["enabled"],
        "configured": config["configured"],
        "model": config.get("model", ""),
        "source": config.get("source", "external"),
        "managed": config.get("source") == "builtin",
        "status": "disabled" if not config["enabled"] else "ready" if config["configured"] else "unconfigured",
    }


def embed(texts, config):
    from .semantic import normalized_vector
    from .retrieval import scan_content

    if not config.get("enabled") or not config.get("configured"):
        raise ValueError("EMBEDDING_UNCONFIGURED")
    if not 1 <= len(texts) <= 16 or any(
        not isinstance(text, str) or not text or len(text) > 2000 or scan_content(text) for text in texts
    ):
        raise ValueError("EMBEDDING_INPUT_REJECTED")
    with OpenAI(api_key=config["api_key"], base_url=config["base_url"], timeout=12, max_retries=0) as client:
        result = client.embeddings.create(model=config["model"], input=texts, encoding_format="float")
    ordered = sorted(result.data, key=lambda value: value.index)
    if [value.index for value in ordered] != list(range(len(texts))):
        raise ValueError("EMBEDDING_COUNT_MISMATCH")
    vectors = [normalized_vector(value.embedding) for value in ordered]
    if len({len(vector) for vector in vectors}) != 1:
        raise ValueError("EMBEDDING_DIMENSION_MISMATCH")
    return vectors
