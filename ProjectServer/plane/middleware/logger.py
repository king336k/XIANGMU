# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import hashlib
import hmac
import logging
import time
import re
import json
from io import BytesIO
from plane.utils.logging import safe_log_text, safe_log_value, safe_query, LOG_LIMIT

# Django imports
from django.conf import settings
from django.http import HttpRequest

# Third party imports
from rest_framework.request import Request

# Module imports
from plane.utils.ip_address import get_client_ip
from plane.utils.exception_logger import log_exception
from plane.bgtasks.logger_task import process_logs

api_logger = logging.getLogger("plane.api.request")


def safe_request_path(path):
    return safe_log_text(re.sub(r"(/(?:spaces/)?reset-password/)[^/]+/[^/]+/", r"\1[REDACTED]/[REDACTED]/", path), 2048)


class RequestLoggerMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def _should_log_route(self, request: Request | HttpRequest) -> bool:
        """
        Determines whether a route should be logged based on the request and status code.
        """
        # Don't log health checks
        if request.path == "/" and request.method == "GET":
            return False
        return True

    def __call__(self, request):
        # get the start time
        start_time = time.time()

        # Get the response
        response = self.get_response(request)

        # calculate the duration
        duration = time.time() - start_time

        # Check if logging is required
        log_true = self._should_log_route(request=request)

        # If logging is not required, return the response
        if not log_true:
            return response

        user_id = (
            request.user.id if getattr(request, "user") and getattr(request.user, "is_authenticated", False) else None
        )

        user_agent = request.META.get("HTTP_USER_AGENT", "")

        # Log the request information
        api_logger.info(
            f"{request.method} {safe_request_path(request.path)}" + ("?" + safe_query(request.META.get("QUERY_STRING", "")) if request.META.get("QUERY_STRING") else "") + f" {response.status_code}",
            extra={
                "path": safe_request_path(request.path),
                "method": request.method,
                "status_code": response.status_code,
                "duration_ms": int(duration * 1000),
                "remote_addr": get_client_ip(request),
                "user_agent": safe_log_text(user_agent, 512),
                "user_id": user_id,
            },
        )

        # return the response
        return response


class _PrefixedStream:
    def __init__(self, prefix, stream):
        self.prefix = BytesIO(prefix)
        self.stream = stream
    def read(self, size=-1):
        head = self.prefix.read(size)
        if size < 0:
            return head + self.stream.read()
        return head + self.stream.read(size - len(head)) if len(head) < size else head
    def readline(self, size=-1):
        head = self.prefix.readline(size)
        if head.endswith(b"\n") or (size >= 0 and len(head) >= size):
            return head
        return head + self.stream.readline(-1 if size < 0 else size-len(head))
    def close(self):
        self.prefix.close()
        self.stream.close()


class APITokenLogMiddleware:
    def _credential_endpoint(self, request):
        return (
            request.path.startswith(("/auth/", "/api/quality-auth/"))
            or "/quality/integrations/connections/" in request.path
            or "/knowledge/configuration/" in request.path
            or ("/quality/field-agents/" in request.path and request.path.endswith("/credential/"))
        )

    """
    Middleware to log External API requests to PostgreSQL.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._credential_endpoint(request):
            return self.get_response(request)
        if not request.headers.get("X-Api-Key"):
            return self.get_response(request)
        content_type = request.META.get("CONTENT_TYPE", "").lower()
        length = request.META.get("CONTENT_LENGTH", "")
        try:
            small = 0 <= int(length) <= LOG_LIMIT
        except (TypeError, ValueError):
            small = False
        request_body = b"[body omitted: type or budget]"
        if small and ("json" in content_type or "application/x-www-form-urlencoded" in content_type):
            if hasattr(request, "_body"):
                cached = request._body
                if isinstance(cached, bytes) and len(cached) <= LOG_LIMIT:
                    request_body = cached
            else:
                # Limited read even if an inconsistent Content-Length reaches this layer.
                raw = request.read(LOG_LIMIT + 1)
                if len(raw) <= LOG_LIMIT:
                    request._body = raw
                    request._stream = BytesIO(raw)
                    request_body = raw
                else:
                    # Do not consume the rest; preserve the consumed prefix for the view.
                    request._stream = _PrefixedStream(raw, request._stream)
                    request._read_started = False
        response = self.get_response(request)
        self.process_request(request, response, request_body)
        return response

    def _safe_decode_body(self, content):
        """
        Safely decodes request/response body content, handling binary data.
        Returns None if content is None, or a string representation of the content.
        """
        if content is None or content == b"":
            return None
        if len(content) > LOG_LIMIT:
            return "[body omitted: budget]"
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            return "[body omitted: binary]"
        try:
            return json.dumps(safe_log_value(json.loads(text)), ensure_ascii=False)
        except (ValueError, TypeError):
            if "=" in text and not text.lstrip().startswith(("{", "[")):
                return safe_query(text)
            return safe_log_text(text)

    # Headers whose values must never be persisted in plaintext logs
    SENSITIVE_HEADERS = frozenset({"x-api-key", "authorization", "cookie"})

    def _redacted_headers(self, request):
        """
        Returns the request headers as a string with sensitive values redacted,
        so that credentials such as the API key are never stored in plaintext.
        """
        return str(safe_log_value(dict(request.headers)))

    def process_request(self, request, response, request_body):
        if self._credential_endpoint(request):
            return
        api_key_header = "X-Api-Key"
        api_key = request.headers.get(api_key_header)

        # If the API key is not present, return
        if not api_key:
            return

        try:
            log_data = {
                # Tokenize the (high-entropy) API key into a stable, non-reversible
                # identifier so logs can be correlated to a token without ever
                # persisting the raw key. A keyed HMAC is used rather than a bare
                # hash so the digest cannot be precomputed from a known key value.
                "token_identifier": hmac.new(
                    settings.SECRET_KEY.encode(), api_key.encode(), hashlib.sha256
                ).hexdigest(),
                "path": safe_request_path(request.path),
                "method": request.method,
                "query_params": safe_query(request.META.get("QUERY_STRING", "")),
                "headers": self._redacted_headers(request),
                "body": self._safe_decode_body(request_body) if request_body else None,
                "response_body": "[response omitted: streaming]" if getattr(response, "streaming", False) else self._safe_decode_body(response.content),
                "response_code": response.status_code,
                "ip_address": get_client_ip(request=request),
                "user_agent": safe_log_text(request.META.get("HTTP_USER_AGENT", ""), 512),
            }

            process_logs.delay(log_data=log_data)

        except Exception as e:
            log_exception(e)

        return None
