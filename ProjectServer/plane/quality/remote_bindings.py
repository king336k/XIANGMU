"""DAQ feedback identity and target binding rules."""

import uuid
from django.db.models import Q, Prefetch
from .remote_models import RemoteWorkstation
from .models import Defect
from .remote_access import online


def daq_binding(defect):
    """A signed DAQ source owns its execution target; legacy bindings cannot replace it."""
    from .daq_incidents import signed_record
    from .models import SourceLink

    links = list(
        SourceLink.objects.filter(
            defect=defect, project_id=defect.project_id, source_system="ENGRAM_DAQ", record_type="daq_incident"
        ).select_related("defect")
    )
    if not links:
        return {"kind": "manual", "state": "matched", "device_id": None, "source_instance": ""}, None
    accepted = []
    for link in links:
        record = signed_record(link)
        if (
            record
            and record.get("authorityMode") == "report_only"
            and link.device
            and record.get("payload", {}).get("device") == link.device
        ):
            accepted.append(link)
    devices = {(link.device, link.source_instance) for link in accepted}
    if len(devices) != 1:
        return {"kind": "daq", "state": "conflict", "device_id": None, "source_instance": ""}, None
    device, source = next(iter(devices))
    try:
        device = str(uuid.UUID(str(device)))
    except (ValueError, TypeError):
        return {"kind": "daq", "state": "conflict", "device_id": None, "source_instance": source}, None
    station = (
        RemoteWorkstation.objects.select_related("agent__project__workspace")
        .filter(pk=device, agent__project_id=defect.project_id)
        .first()
    )
    from .daq_execution_binding import source_matches

    accepted_source = station is not None and (
        not station.agent.source_instance or source_matches(station, accepted[0])
    )
    state = "missing" if station is None else "matched" if accepted_source else "conflict"
    binding = {"kind": "daq", "state": state, "device_id": device, "source_instance": source}
    if state == "matched" and station.agent.source_instance and station.agent.source_instance != source:
        binding["execution_scope"] = "verify_only"
    return binding, station


def defect_agent_availability(defect):
    binding, station = daq_binding(defect)
    if binding["kind"] != "daq":
        return None
    if binding["state"] == "conflict":
        return {"state": "conflict", "summary": "反馈接入来源与原执行端不一致，尚未开始现场处理。"}
    if station is None:
        return {"state": "missing", "summary": "原采集电脑尚未完成远程接入，不能替换为其他电脑执行。"}
    if not online(station):
        return {"state": "offline", "summary": "原采集电脑执行端心跳中断，等待自动恢复连接。"}
    return {"state": "ready", "summary": "原采集电脑已连接，可开始现场处理。"}


def feedback_for(station, defect_id=None):
    from .daq_incidents import signed_record
    from .daq_execution_binding import source_matches
    from .models import SourceLink, DefectEvent

    links = (
        SourceLink.objects.filter(
            project_id=station.agent.project_id,
            source_system="ENGRAM_DAQ",
            record_type="daq_incident",
            device=str(station.id),
        )
        .select_related("defect")
        .prefetch_related(
            Prefetch(
                "defect__events",
                queryset=DefectEvent.objects.filter(status="open", previous_status=""),
                to_attr="_incident_signature_events",
            )
        )
    )
    if defect_id:
        links = links.filter(defect_id=defect_id)
    verified = []
    for link in links.order_by("-created_at"):
        record = signed_record(link)
        if (
            record
            and record.get("authorityMode") == "report_only"
            and record.get("payload", {}).get("device") == str(station.id)
            and (not station.agent.source_instance or source_matches(station, link))
        ):
            verified.append(link.defect_id)
    rows = Defect.objects.filter(project_id=station.agent.project_id)
    if defect_id:
        rows = rows.filter(pk=defect_id)
    # Explicit legacy association is only for records without any DAQ provenance.
    return rows.filter(
        Q(pk__in=verified)
        | (
            Q(remote_bindings__workstation=station)
            & ~Q(sources__source_system="ENGRAM_DAQ", sources__record_type="daq_incident")
        )
    ).distinct()
