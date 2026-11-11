"""Address-only enrollment grants feedback transport only, never a platform login."""

import hashlib
import hmac
from uuid import UUID

from django.conf import settings
from django.core import signing
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from plane.app.views.base import BaseAPIView
from plane.authentication.rate_limit import AuthenticationThrottle

SALT = "daq-report-only-v1"
PREFIX = "daq-auto."


def device_secret(ticket):
    return hmac.new(settings.SECRET_KEY.encode(), ("daq-feedback:" + ticket).encode(), hashlib.sha256).hexdigest()


def automatic_key(key_id):
    if not isinstance(key_id, str) or not key_id.startswith(PREFIX) or len(key_id) > 512:
        return None
    try:
        ticket = key_id[len(PREFIX) :]
        data = signing.loads(ticket, salt=SALT)
        device = str(UUID(data["device_id"]))
        from plane.license.models import InstanceConfiguration

        if InstanceConfiguration.objects.filter(key="DAQ_DISABLED_DEVICE:" + device, value="true").exists():
            return None
    except (ValueError, KeyError, TypeError, signing.BadSignature):
        return None
    return {
        "secret": device_secret(ticket),
        "audience": "project-feedback",
        "source_instance": "daq-auto:" + device,
        "enabled": True,
    }


class ConnectionInput(serializers.Serializer):
    device_id = serializers.UUIDField()


class DaqConnect(BaseAPIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [AuthenticationThrottle]

    def post(self, request):
        parser = ConnectionInput(data=request.data)
        parser.is_valid(raise_exception=True)
        ticket = signing.dumps({"device_id": str(parser.validated_data["device_id"])}, salt=SALT, compress=True)
        response = Response(
            {
                "protocol": "daq-report-only-v1",
                "key_id": PREFIX + ticket,
                "secret": device_secret(ticket),
                "audience": "project-feedback",
                "capabilities": {"can_report": True, "can_login": False},
            }
        )
        response["Cache-Control"] = "no-store"
        return response
