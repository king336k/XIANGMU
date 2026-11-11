# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import re

from django.core.exceptions import RequestDataTooBig
from django.http import JsonResponse


class RequestBodySizeLimitMiddleware:
    """
    Middleware to catch RequestDataTooBig exceptions and return
    413 Request Entity Too Large instead of 400 Bad Request.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Parse this bounded multipart route as a stream; other routes keep their existing limit.
        if (
            request.method == "POST"
            and re.fullmatch(r"/api/workspaces/[^/]+/projects/[0-9a-fA-F-]{36}/quality/document-imports/", request.path)
            and request.content_type == "multipart/form-data"
        ):
            try:
                length = int(request.META.get("CONTENT_LENGTH", "0"))
            except (TypeError, ValueError):
                length = -1
            if 0 < length <= 22 * 1024 * 1024:
                return self.get_response(request)
            if length > 22 * 1024 * 1024:
                return JsonResponse(
                    {"error": "REQUEST_BODY_TOO_LARGE", "detail": "文档上传不能超过20MiB。"}, status=413
                )
        try:
            _ = request.body
        except RequestDataTooBig:
            return JsonResponse(
                {
                    "error": "REQUEST_BODY_TOO_LARGE",
                    "detail": "请求内容超过允许大小。",
                },
                status=413,
            )

        # If body size is OK, continue with the request
        return self.get_response(request)
