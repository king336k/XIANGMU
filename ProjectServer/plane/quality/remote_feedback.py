"""Enroll signed DAQ feedback into the opted-in workstation repair loop."""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import SourceLink, DefectEvent
from .daq_reporting import signed_record
from .remote_models import RemoteWorkstation, RemoteFeedbackBinding, RemoteAgentRun
from .remote_access import online, permitted, identity_key


def blocked_followup(defect_id,station,reason):
    """Expose a trusted report's blocked intake without inventing field work."""
    from .models import Defect
    defect=Defect.objects.select_for_update().select_related('project__workspace').get(pk=defect_id)
    if defect.archived_at or defect.status!='open' or RemoteAgentRun.objects.filter(defect=defect).exists():return
    previous=defect.status;defect.status='needs_tech';defect.edit_version+=1
    defect.save(update_fields=['status','edit_version','updated_at'])
    DefectEvent.objects.create(project=defect.project,defect=defect,created_by=station.agent.owner,
        previous_status=previous,status='needs_tech',note='Agent 尚未开始：'+reason)
    from .notifications import defect_notice,managers
    defect_notice(defect,station.agent.owner,'现场接入待恢复',receivers=managers(defect.project))


def received(defect_id):
    link=SourceLink.objects.filter(defect_id=defect_id,source_system="ENGRAM_DAQ",record_type="daq_incident").first()
    if not link or not link.device:return
    record=signed_record(link)
    if not record or record.get("authorityMode")!="report_only" or record.get("payload",{}).get("device")!=link.device:return
    with transaction.atomic():
        station=RemoteWorkstation.objects.select_for_update(of=("self",)).select_related("agent__project__workspace","agent__owner").filter(pk=link.device,agent__project_id=link.project_id,enabled=True).first()
        if not station or not permitted(station.agent.owner,station):return
        if not station.agent.source_instance or station.agent.source_instance!=link.source_instance:
            blocked_followup(defect_id,station,'接入信息不一致，等待同一采集电脑恢复接入。')
            return
        RemoteFeedbackBinding.objects.get_or_create(workstation=station,defect_id=defect_id,defaults={"created_by":station.agent.owner})
        context=station.capabilities.get("agent_context",{})
        if context.get('auto_diagnose') is not True:return
        if not online(station):
            blocked_followup(defect_id,station,'执行端断连，等待原采集电脑恢复接入。')
            return
        if RemoteAgentRun.objects.filter(defect_id=defect_id).exists():return
        if station.remoteagentrun_set.filter(status__in=["queued","running"],expires_at__gt=timezone.now()).count()>=20:return
        from .models import Defect
        defect=Defect.objects.select_for_update().get(pk=defect_id)
        run=RemoteAgentRun.objects.create(workstation=station,defect=defect,owner=station.agent.owner,problem=defect.description,result={'defect_state_version':defect.edit_version},identity_key=identity_key(station),expires_at=timezone.now()+timedelta(minutes=30))
        DefectEvent.objects.create(project_id=link.project_id,defect=link.defect,created_by=station.agent.owner,previous_status=link.defect.status,status=link.defect.status,note=f"Agent 自动诊断：已根据本机签名反馈进入队列；任务 {run.id}。")
        from .remote_tasks import remote_repair
        transaction.on_commit(lambda:remote_repair.apply_async(args=[str(run.id)],queue="field-repairs"))
        return str(run.id)


def resume_pending(station_id):
    station=RemoteWorkstation.objects.select_related("agent").filter(pk=station_id,enabled=True).first()
    if not station or not station.agent.source_instance:return
    if station.remoteagentrun_set.filter(status__in=["queued","running"],expires_at__gt=timezone.now()).count()>=20:return
    # Manual bindings without a signed current DAQ source are never automatic work.
    candidates=SourceLink.objects.filter(project_id=station.agent.project_id,source_system="ENGRAM_DAQ",record_type="daq_incident",source_instance=station.agent.source_instance,device=str(station.pk),defect__remote_bindings__workstation=station).exclude(defect__remoteagentrun__isnull=False).order_by("created_at").values_list("defect_id",flat=True).distinct()
    for defect_id in candidates:
        if received(defect_id):break
