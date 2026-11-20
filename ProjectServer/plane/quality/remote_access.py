"""Shared workstation access and identity policy, independent of HTTP views.

Decisions always use current membership/device state. Callers may reuse a decision
within one request or output batch, never across requests or different owners.
"""

import hashlib
import json
from urllib.parse import urlsplit

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from .permissions import has_role, is_administrator, writable_member
from .remote_models import RemoteWorkstation


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def permitted(user, station):
    project = station.agent.project
    return bool(
        user.is_authenticated
        and user.is_active
        and station.enabled
        and station.agent.enabled
        and writable_member(project.id, user.id, project.workspace.slug)
        and (
            is_administrator(user)
            or station.agent.owner_id == user.id
            and has_role(project.id, user.id, "TECHNICIAN")
        )
    )


def online(station):
    return bool(station.last_seen_at and (timezone.now() - station.last_seen_at).total_seconds() < 20)


def identity_key(station):
    robot = station.capabilities.get("robot", {})
    peer = (
        [robot.get("username"), robot.get("host"), robot.get("target_revision")]
        if isinstance(robot, dict) and robot.get("connected") is True else None
    )
    # DHCP/DAQ versions are metadata. A robot switch changes the execution target.
    return digest(json.dumps(
        [str(station.pk), station.boot_id, station.hostname, station.username, peer], ensure_ascii=False
    ))


def station_for(user, pk):
    value = get_object_or_404(RemoteWorkstation.objects.select_related("agent__project__workspace"), pk=pk)
    if not permitted(user, value):
        raise PermissionDenied("没有这台采集电脑的远程操作权限。")
    return value


def browser_boundary(request):
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    if not request.content_type.startswith("application/json"):
        raise ValidationError("仅接受JSON请求。")
    origin = request.headers.get("Origin")
    if origin and (
        urlsplit(origin).netloc != request.get_host() or urlsplit(origin).scheme not in {"http", "https"}
    ):
        raise PermissionDenied("请求来源不匹配。")
    if request.headers.get("Sec-Fetch-Site") in {"cross-site", "same-site"}:
        raise PermissionDenied("请求来源不匹配。")
