"""Shared business errors; transport adapters preserve their existing status contract."""

from rest_framework.exceptions import APIException


class Conflict(APIException):
    status_code = 409
    default_detail = "数据已变更，请刷新后重试。"
