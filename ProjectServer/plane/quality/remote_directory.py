"""Authorized device directory, feedback summaries and execution target queries."""

import secrets
from datetime import timedelta
from django.db import transaction
from django.db.models import Q, OuterRef, Subquery, Case, When, Value, CharField, Count
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from plane.db.models import Project
from .models import FieldAgent, Defect
from .permissions import is_administrator, writable_member
from .remote_access import digest, online, permitted, station_for
from .remote_models import RemoteWorkstation, RemoteAgentRun
from .remote_sessions import close_session, open_session
from .remote_bindings import daq_binding, feedback_for
from .remote_run_state import fail_runs, run_queue
from .remote_sessions import SessionResult


def card(value, user, can_connect=None):
    return {
        "id": str(value.id),
        "username": value.username or value.agent.name,
        "hostname": value.hostname,
        "ip_address": value.capabilities.get("network", {}).get("ip_address", ""),
        "name": value.agent.name,
        "online": online(value),
        "last_seen_at": value.last_seen_at,
        "project_id": str(value.agent.project_id),
        "workspace_slug": value.agent.project.workspace.slug,
        "can_connect": permitted(user, value) if can_connect is None else can_connect,
        "capabilities": value.capabilities,
    }


def list_devices(user, data):
    stations = RemoteWorkstation.objects.select_related("agent__project__workspace").order_by("username", "id")
    if data.get("workspace"):
        stations = stations.filter(agent__project__workspace__slug=data["workspace"])
    if data.get("project"):
        stations = stations.filter(agent__project_id=data["project"])
    params = data
    paged = any(key in params for key in ("page", "per_page", "search", "status", "active"))
    page = serializers.IntegerField(min_value=1).run_validation(params.get("page", 1))
    size = (
        serializers.ChoiceField(choices=(6, 12, 24)).run_validation(int(params.get("per_page", 6)))
        if str(params.get("per_page", 6)).isdigit()
        else None
    )
    if size is None:
        raise ValidationError({"per_page": "请选择6、12或24台。"})
    state = serializers.ChoiceField(choices=("all", "online", "offline")).run_validation(params.get("status", "all"))
    active = [
        str(serializers.UUIDField().run_validation(value)) for value in params.get("active", "").split(",") if value
    ]
    if len(active) > 2:
        raise ValidationError({"active": "最多保留两台当前操作电脑。"})
    # Permissions are memoized only within this request and checked before counts or pins.
    access = {}
    allowed = []
    for station in stations:
        key = (station.agent.project_id, station.agent.owner_id, station.enabled, station.agent.enabled)
        if key not in access:
            access[key] = permitted(user, station)
        if access[key]:
            allowed.append(station)
    if not paged:
        return SessionResult(
            {"results": [card(station, user, True) for station in allowed], "can_manage": is_administrator(user)}
        )
    selected = [station for station in allowed if str(station.id) in active]
    search = str(params.get("search", "")).strip().casefold()[:200]
    visible = [
        station
        for station in allowed
        if (state == "all" or online(station) == (state == "online"))
        and (
            not search
            or search
            in " ".join(
                [
                    station.username,
                    station.hostname,
                    station.agent.name,
                    str(station.capabilities.get("network", {}).get("ip_address", "")),
                ]
            ).casefold()
        )
    ]
    count = len(visible)
    page = min(page, max(1, (count + size - 1) // size))
    return SessionResult(
        {
            "results": [card(station, user, True) for station in visible[(page - 1) * size : page * size]],
            "active_results": [card(station, user, True) for station in selected],
            "count": count,
            "page": page,
            "per_page": size,
            "can_manage": is_administrator(user),
        }
    )


@transaction.atomic
def change_directory(user, data):
    action = data.get("action")
    if action == "register":
        if not is_administrator(user):
            raise PermissionDenied("仅管理员可登记远程采集电脑。")
        project = get_object_or_404(Project, pk=data.get("project_id"), archived_at__isnull=True)
        if not writable_member(project.id, user.id, project.workspace.slug):
            raise PermissionDenied()
        name = str(data.get("name", "采集电脑")).strip()[:120]
        agent = FieldAgent.objects.create(project=project, created_by=user, owner=user, name=name)
        raw = "rw_" + secrets.token_urlsafe(36)
        station = RemoteWorkstation.objects.create(
            agent=agent,
            credential_hash=digest(raw),
            credential_expires_at=timezone.now() + timedelta(days=30),
        )
        return SessionResult({**card(station, user), "token": raw}, status_code=201)
    if action == "revoke":
        station = station_for(user, data.get("device_id"))
        station.enabled = False
        station.save(update_fields=["enabled"])
        for session in station.remoteterminal_set.exclude(status="closed"):
            close_session(session)
        station.commands.filter(status__in=["pending", "delivered"]).update(status="expired", payload={})
        fail_runs(station, "设备授权已撤销")
        return SessionResult({"enabled": False})
    if action != "open":
        raise ValidationError("未知操作。")
    result = open_session(user, data)
    return result


def list_feedback(user, data):
    station = station_for(user, data.get("device_id"))
    from .models import BusinessNumber

    rows = feedback_for(station)
    query = str(data.get("q", "")).strip()[:200]
    if query:
        numbered = BusinessNumber.objects.filter(resource="quality.defect", code__icontains=query).values("object_id")
        rows = rows.filter(Q(title__icontains=query) | Q(description__icontains=query) | Q(pk__in=numbered))
    latest = RemoteAgentRun.objects.filter(workstation=station, defect_id=OuterRef("pk")).order_by("-created_at", "-id")
    from .agent_lifecycle import with_mutation_evidence

    latest = with_mutation_evidence(latest)
    rows = rows.annotate(latest_mutation=Subquery(latest.values("processing_mutation")[:1]))
    rows = rows.annotate(
        latest_run_status=Subquery(latest.values("status")[:1]),
        latest_mode=Subquery(latest.values("mode")[:1]),
        latest_outcome=Subquery(latest.values("result__outcome")[:1]),
        latest_repaired=Subquery(latest.values("result__repaired")[:1]),
        latest_verified=Subquery(latest.values("result__verification_passed")[:1]),
        latest_run_id=Subquery(latest.values("id")[:1]),
        run_count=Count("remoteagentrun", filter=Q(remoteagentrun__workstation=station), distinct=True),
    )
    rows = rows.annotate(
        latest_status=Case(
            When(latest_run_status__in=["queued", "running"], then=Value("running")),
            When(latest_run_status="completed", latest_repaired=True, latest_verified=True, then=Value("repaired")),
            When(
                latest_run_status="completed",
                latest_outcome__in=["verified", "verified_without_repair"],
                latest_verified=True,
                latest_mutation=False,
                then=Value("verified"),
            ),
            When(latest_run_status__isnull=True, then=Value("pending")),
            default=Value("unresolved"),
            output_field=CharField(),
        )
    )
    state = serializers.ChoiceField(
        choices=["all", "needs_attention", "pending", "running", "repaired", "unresolved"]
    ).run_validation(data.get("state", "all"))
    if state == "needs_attention":
        rows = rows.exclude(latest_status__in=["repaired", "verified"])
    elif state == "repaired":
        rows = rows.filter(latest_status__in=["repaired", "verified"])
    elif state != "all":
        rows = rows.filter(latest_status=state)
    page = serializers.IntegerField(min_value=1).run_validation(data.get("page", 1))
    size = serializers.IntegerField(min_value=1, max_value=50).run_validation(data.get("per_page", 20))
    count = rows.count()
    rows = list(rows.order_by("-created_at", "-id")[(page - 1) * size : page * size])
    from .numbering import preload

    preload(rows)
    return SessionResult(
        {
            "count": count,
            "page": page,
            "per_page": size,
            "results": [
                {
                    "id": str(d.id),
                    "title": d.title,
                    "code": d.code,
                    "latest_status": d.latest_status,
                    "latest_run_id": str(d.latest_run_id) if d.latest_run_id else None,
                    "run_count": d.run_count,
                    "created_at": d.created_at,
                }
                for d in rows
            ],
        }
    )


def list_defect_targets(user, data):
    defect = get_object_or_404(Defect, pk=data.get("defect_id"))
    if not writable_member(defect.project_id, user.id, defect.project.workspace.slug):
        raise PermissionDenied()
    binding, fixed = daq_binding(defect)
    if binding["kind"] == "daq":
        available = [fixed] if fixed is not None and permitted(user, fixed) else []
    else:
        stations = RemoteWorkstation.objects.filter(agent__project_id=defect.project_id).select_related(
            "agent__project__workspace"
        )
        available = [
            station for station in stations if permitted(user, station) and feedback_for(station, defect.id).exists()
        ]
    active = (
        RemoteAgentRun.objects.filter(
            defect=defect,
            owner=user,
            workstation__in=available,
            status__in=["queued", "running"],
            expires_at__gt=timezone.now(),
        )
        .select_related("workstation__agent__project__workspace")
        .order_by("-created_at")
        .first()
    )
    return SessionResult(
        {
            "binding": binding,
            "results": [card(station, user) for station in available],
            "active_run": {
                "id": str(active.id),
                "status": active.status,
                "queue": run_queue(active),
                "error": active.error,
            }
            if active
            else None,
        }
    )
