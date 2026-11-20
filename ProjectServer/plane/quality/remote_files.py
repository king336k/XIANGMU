"""HTTP adapter for bounded operator and robot file requests."""
from rest_framework.response import Response
from plane.app.views.base import BaseAPIView
from .remote_access import browser_boundary
from .remote_file_operations import (
    create_file_request, read_file_request, record_upload_result as record_upload_result,
)


class RemoteFiles(BaseAPIView):
    def post(self, request):
        browser_boundary(request)
        return Response(create_file_request(request.user, request.data), status=201)

    def get(self, request, pk):
        return Response(read_file_request(request.user, pk))
