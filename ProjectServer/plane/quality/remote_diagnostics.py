"""Thin HTTP adapters; compatibility exports retain existing caller paths."""

from rest_framework.response import Response
from plane.app.views.base import BaseAPIView
from .errors import Conflict as Conflict
from .remote_commands import command as command
from .remote_sessions import (
    close_session as close_session,
    robot_target as robot_target,
    terminal_snapshot as terminal_snapshot,
    terminal_target_valid as terminal_target_valid,
    open_session as open_session,
    read_session,
    change_session,
)
from .remote_access import (
    browser_boundary,
    digest as digest,
    identity_key as identity_key,
    online as online,
    permitted as permitted,
    station_for as station_for,
)
from .remote_bindings import (
    daq_binding as daq_binding,
    defect_agent_availability as defect_agent_availability,
    feedback_for as feedback_for,
)
from .remote_exchange import exchange_station
from .remote_run_state import (
    invalidate_run as invalidate_run,
    fail_runs as fail_runs,
    record_tool_completion as record_tool_completion,
    run_queue as run_queue,
)
from .remote_run_requests import create_run, read_run
from .remote_tool_operations import execute_tool
from .remote_auth import ToolAuthentication, WorkstationAuthentication as WorkstationAuthentication
from .remote_directory import card as card, list_devices, change_directory, list_feedback, list_defect_targets


class RemoteDirectory(BaseAPIView):
    def get(self, request):
        result = list_devices(request.user, request.query_params)
        return Response(result.data, status=result.status_code)

    def post(self, request):
        browser_boundary(request)
        result = change_directory(request.user, request.data)
        return Response(result.data, status=result.status_code)


class RemoteSession(BaseAPIView):
    def perform_authentication(self, request):
        # Current owner/device authorization is checked by the shared application.
        request.user

    def get(self, request, pk):
        result = read_session(request.user, pk, request.query_params.get("after", 0))
        return Response(result.data, status=result.status_code)

    def post(self, request, pk):
        browser_boundary(request)
        result = change_session(request.user, pk, request.data)
        return Response(result.data, status=result.status_code)


class RemoteFeedback(BaseAPIView):
    def get(self, request):
        result = list_feedback(request.user, request.query_params)
        return Response(result.data, status=result.status_code)


class RemoteRuns(BaseAPIView):
    def post(self, request):
        browser_boundary(request)
        return Response(create_run(request.user, request.data), status=201)


class RemoteDefectTargets(BaseAPIView):
    def get(self, request):
        result = list_defect_targets(request.user, request.query_params)
        return Response(result.data, status=result.status_code)


class RemoteRunDetail(BaseAPIView):
    def get(self, request, pk):
        return Response(read_run(request.user, pk))


class RemoteTool(BaseAPIView):
    authentication_classes = [ToolAuthentication]

    def post(self, request):
        data, status_code = execute_tool(request.auth, request.data)
        return Response(data, status=status_code)


class RemoteExchange(BaseAPIView):
    authentication_classes = [WorkstationAuthentication]

    def perform_authentication(self, request):
        request.user

    def post(self, request):
        result = exchange_station(
            request.auth.pk,
            request.data,
            previous_identity=getattr(request._request, "remote_stream_previous_identity", None),
            poll_only=getattr(request._request, "remote_stream_poll_only", False),
        )
        return Response(result.data, status=result.status_code)
