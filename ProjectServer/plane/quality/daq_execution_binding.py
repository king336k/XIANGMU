"""One-defect, centrally approved read-only execution binding for historical sources."""
import json
import re
from datetime import timedelta

from django.core import signing
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied,ValidationError
from plane.license.models import InstanceAdmin
from .daq_incidents import signed_record
from .diagnostic_materials import redact
from .models import Defect,DefectEvent,SourceLink
from .remote_models import RemoteFeedbackBinding,RemoteWorkstation

SALT='daq-execution-binding-v1'
SIGNATURE='executionBindingSignature'
SCOPE='verify_only'
MAX_AGE=timedelta(days=30)


def active_admin(actor_id):
    return InstanceAdmin.objects.filter(user_id=actor_id,role=20,user__is_active=True,user__is_bot=False).exists()


def active_station(station):
    return bool(station.enabled and station.agent.enabled and station.credential_hash
        and station.credential_expires_at>timezone.now() and station.agent.source_instance
        and station.agent.project.archived_at is None and station.agent.project.deleted_at is None
        and station.agent.project.workspace.deleted_at is None)


def trusted_source(station,link):
    if (not link.source_instance or link.project_id!=station.agent.project_id or str(link.device)!=str(station.pk)
            or link.defect.project_id!=link.project_id):return False
    record=signed_record(link)
    return bool(record and record.get('authorityMode')=='report_only'
        and record.get('payload',{}).get('device')==str(station.pk))


def identity_fields(station,link):
    return {'link_id':str(link.pk),'defect_id':str(link.defect_id),'project_id':str(link.project_id),
        'station_id':str(station.pk),'old_source':link.source_instance,'current_source':station.agent.source_instance,
        'machine_fingerprint':station.machine_fingerprint,'enrollment_claim_hash':station.enrollment_claim_hash,
        'scope':SCOPE}


def source_matches(station,link,context=None):
    """Authorization is always checked live; no cached admin/credential decisions."""
    if not active_station(station) or not trusted_source(station,link):return False
    if link.source_instance==station.agent.source_instance:return True
    if not (re.fullmatch(r'[0-9a-f]{64}',station.machine_fingerprint or '')
            and re.fullmatch(r'[0-9a-f]{64}',station.enrollment_claim_hash or '')):return False
    if not RemoteFeedbackBinding.objects.filter(workstation=station,defect_id=link.defect_id).exists():return False
    expected=identity_fields(station,link)
    # Only conflicting sources read approval events, capped independently of history size.
    events=DefectEvent.objects.filter(project_id=link.project_id,defect_id=link.defect_id,
        note__contains='"'+SIGNATURE+'"').order_by('-created_at','-id')[:32]
    for event in events:
        try:
            envelope=json.loads(event.note)
            value=signing.loads(envelope[SIGNATURE],salt=SALT,max_age=MAX_AGE)
            actor=value.get('actor_id')
            if (all(value.get(key)==item for key,item in expected.items()) and str(event.created_by_id)==actor
                    and active_admin(actor) and isinstance(value.get('reason'),str) and value['reason'].strip()):
                return True
        except (ValueError,TypeError,KeyError,signing.BadSignature):continue
    return False


@transaction.atomic
def approve_execution_binding(*,actor,defect_id,station_id,reason,expected_current_source,apply=False):
    if not active_admin(getattr(actor,'pk',None)):
        raise PermissionDenied('只有当前有效实例管理员可以审批单条反馈的只读执行绑定。')
    if not isinstance(reason,str) or not reason.strip() or len(reason)>1000:
        raise ValidationError({'reason':'请填写1至1000字的单条反馈审批原因。'})
    reason=redact(reason.strip())
    station=RemoteWorkstation.objects.select_for_update(of=('self',)).select_related(
        'agent__project__workspace').get(pk=station_id)
    defect=Defect.objects.select_for_update().get(pk=defect_id)
    if (not active_station(station) or defect.project_id!=station.agent.project_id or defect.archived_at
            or defect.status=='closed' or expected_current_source!=station.agent.source_instance
            or not re.fullmatch(r'[0-9a-f]{64}',station.machine_fingerprint or '')
            or not re.fullmatch(r'[0-9a-f]{64}',station.enrollment_claim_hash or '')):
        raise ValidationError('当前设备、项目、来源或私有接入身份不满足审批条件。')
    links=list(SourceLink.objects.filter(defect=defect,project_id=defect.project_id,
        source_system='ENGRAM_DAQ',record_type='daq_incident').select_related('defect')[:3])
    if len(links)!=1 or not trusted_source(station,links[0]):
        raise ValidationError('必须是签名有效且设备ID与当前采集电脑完全一致的单条DAQ反馈。')
    link=links[0]
    if link.source_instance==station.agent.source_instance:
        raise ValidationError('反馈来源已与当前设备一致，无需迁移审批。')
    result={**identity_fields(station,link),'eligible':True,'created':False,'applied':False,
        'approved_scope':SCOPE,'reason':reason}
    # Claim hash is needed inside the signature but never in command output.
    result.pop('enrollment_claim_hash')
    if source_matches(station,link):return {**result,'already_approved':True}
    if not apply:return result
    RemoteFeedbackBinding.objects.get_or_create(workstation=station,defect=defect,defaults={'created_by':actor})
    value={**identity_fields(station,link),'actor_id':str(actor.pk),'reason':reason,'issued_at':timezone.now().isoformat()}
    note={'message':'管理员批准此反馈在原采集电脑只读复核：'+reason,
        SIGNATURE:signing.dumps(value,salt=SALT,compress=True)}
    event=DefectEvent.objects.create(project_id=defect.project_id,defect=defect,created_by=actor,
        previous_status=defect.status,status=defect.status,note=json.dumps(note,ensure_ascii=False))
    return {**result,'created':True,'applied':True,'event_id':str(event.pk)}
