# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Unit tests for APITokenLogMiddleware.

Covers the credential-hygiene guarantees of the external API request logger:
- the raw API key is never persisted (a non-reversible hash is stored instead)
- sensitive request headers are redacted before being logged
"""

import hashlib
import hmac
from unittest.mock import Mock, patch

import pytest
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.test import RequestFactory

from plane.middleware.logger import APITokenLogMiddleware


@pytest.fixture
def request_factory():
    return RequestFactory()


@pytest.fixture
def middleware():
    return APITokenLogMiddleware(Mock(return_value=HttpResponse(b"{}")))


@pytest.mark.unit
class TestAPITokenLogMiddleware:
    API_KEY = "plane_api_supersecretvalue"
    AUTHORIZATION = "Bearer secret-bearer-token"
    COOKIE = "sessionid=secret-session-value"

    def _captured_log_data(self, middleware, request_factory):
        request = request_factory.get(
            "/api/v1/workspaces/",
            HTTP_X_API_KEY=self.API_KEY,
            HTTP_AUTHORIZATION=self.AUTHORIZATION,
            HTTP_COOKIE=self.COOKIE,
        )
        request.user = AnonymousUser()
        response = HttpResponse(b"{}")
        with patch("plane.middleware.logger.process_logs") as process_logs:
            middleware.process_request(request, response, request_body=b"")
            assert process_logs.delay.called
            return process_logs.delay.call_args.kwargs["log_data"]

    def test_token_identifier_is_hashed_not_plaintext(self, middleware, request_factory):
        log_data = self._captured_log_data(middleware, request_factory)

        expected_hash = hmac.new(settings.SECRET_KEY.encode(), self.API_KEY.encode(), hashlib.sha256).hexdigest()
        assert log_data["token_identifier"] == expected_hash
        assert self.API_KEY not in log_data["token_identifier"]

    def test_sensitive_headers_are_redacted(self, middleware, request_factory):
        log_data = self._captured_log_data(middleware, request_factory)

        # None of the sensitive header values may appear in the logged headers.
        assert self.API_KEY not in log_data["headers"]
        assert self.AUTHORIZATION not in log_data["headers"]
        assert self.COOKIE not in log_data["headers"]
        assert "[REDACTED]" in log_data["headers"]

    def test_no_log_without_api_key(self, middleware, request_factory):
        request = request_factory.get("/api/v1/workspaces/")
        request.user = AnonymousUser()
        with patch("plane.middleware.logger.process_logs") as process_logs:
            middleware.process_request(request, HttpResponse(b"{}"), request_body=b"")
            assert not process_logs.delay.called

    @pytest.mark.parametrize(
        "path",
        [
            "/api/workspaces/demo/projects/00000000-0000-0000-0000-000000000001/quality/integrations/connections/",
            "/api/workspaces/demo/projects/00000000-0000-0000-0000-000000000001/knowledge/configuration/",
            "/api/workspaces/demo/projects/00000000-0000-0000-0000-000000000001/quality/field-agents/00000000-0000-0000-0000-000000000002/credential/",
        ],
    )
    def test_configuration_and_one_time_credential_bodies_are_never_logged(self, middleware, request_factory, path):
        request = request_factory.post(
            path,
            data={"service_token": "synthetic-private-value"},
            content_type="application/json",
            HTTP_X_API_KEY=self.API_KEY,
        )
        request.user = AnonymousUser()
        with patch("plane.middleware.logger.process_logs") as process_logs:
            middleware.process_request(
                request, HttpResponse(b'{"token":"synthetic-private-value"}'), request_body=request.body
            )
            assert not process_logs.delay.called


def test_request_logger_redacts_query_but_retains_method_status(request_factory):
    from plane.middleware.logger import RequestLoggerMiddleware
    request=request_factory.get('/api/items/?page=2&token=query-secret')
    request.user=AnonymousUser()
    with patch('plane.middleware.logger.api_logger') as logger:
        RequestLoggerMiddleware(Mock(return_value=HttpResponse(b'{}')))(request)
    text=str(logger.info.call_args)
    assert 'query-secret' not in text and 'page=2' in text and '200' in text


def test_api_log_redacts_structured_body_query_and_extended_sensitive_headers(request_factory):
    middleware=APITokenLogMiddleware(Mock(return_value=HttpResponse(b'{}')))
    request=request_factory.post('/api/items/?access_token=query-private',data={'password':'body-private','name':'Keep diagnostic name'},content_type='application/json',HTTP_X_API_KEY='api-private',HTTP_X_CSRFTOKEN='csrf-private',HTTP_PROXY_AUTHORIZATION='proxy-private')
    request.user=AnonymousUser()
    with patch('plane.middleware.logger.process_logs') as process:
        middleware.process_request(request,HttpResponse(b'{"refresh_token":"response-private","result":"failed"}',content_type='application/json'),request.body)
    data=process.delay.call_args.kwargs['log_data'];text=str(data)
    assert all(x not in text for x in ['query-private','body-private','csrf-private','proxy-private','response-private','api-private'])
    assert 'Keep diagnostic name' in text and 'failed' in text


def test_without_api_key_does_not_read_body_and_streaming_response_is_safe(request_factory):
    request=Mock();request.path='/api/items/';request.headers={};type(request).body=__import__('unittest').mock.PropertyMock(side_effect=AssertionError('must not read body'))
    response=HttpResponse(b'ok');middleware=APITokenLogMiddleware(Mock(return_value=response))
    assert middleware(request) is response
    from django.http import StreamingHttpResponse
    real=request_factory.get('/api/items/',HTTP_X_API_KEY='api-private');real.user=AnonymousUser()
    with patch('plane.middleware.logger.process_logs') as process:
        middleware.process_request(real,StreamingHttpResponse(iter([b'data'])),b'')
    assert process.delay.called and 'stream' in str(process.delay.call_args.kwargs['log_data']['response_body']).lower()


def test_large_declared_body_is_not_read(request_factory):
    request=Mock();request.path='/api/items/';request.headers={'X-Api-Key':'fixture-api'};request.META={'CONTENT_LENGTH':str(1024*1024),'CONTENT_TYPE':'application/json'};request.method='POST';type(request).body=__import__('unittest').mock.PropertyMock(side_effect=AssertionError('must not read large body'))
    response=HttpResponse(b'{}');middleware=APITokenLogMiddleware(Mock(return_value=response))
    with patch('plane.middleware.logger.process_logs') as process:
        assert middleware(request) is response
    assert 'omitted' in str(process.delay.call_args.kwargs['log_data']['body']).lower()


def test_bounded_body_capture_preserves_downstream_request_bytes(request_factory):
    raw=b'{"name":"'+b'x'*9000+b'"}'
    request=request_factory.post('/api/items/',data=raw,content_type='application/json',HTTP_X_API_KEY='api-private')
    request.META['CONTENT_LENGTH']='3'  # deliberate inconsistent metadata, not a normal WSGI request
    observed=[]
    middleware=APITokenLogMiddleware(lambda req:(observed.append(req.body) or HttpResponse(b'{}')))
    with patch('plane.middleware.logger.process_logs') as process:
        middleware(request)
    assert observed==[raw]
    assert 'omitted' in str(process.delay.call_args.kwargs['log_data']['body']).lower()


def test_password_reset_path_never_logs_credential_path_segments(request_factory):
    from plane.middleware.logger import RequestLoggerMiddleware
    request=request_factory.get('/auth/reset-password/secret-uid/reset-private-token/?page=1')
    request.user=AnonymousUser()
    with patch('plane.middleware.logger.api_logger') as logger:
        RequestLoggerMiddleware(Mock(return_value=HttpResponse(b'{}')))(request)
    text=str(logger.info.call_args)
    assert 'secret-uid' not in text and 'reset-private-token' not in text and 'reset-password' in text
