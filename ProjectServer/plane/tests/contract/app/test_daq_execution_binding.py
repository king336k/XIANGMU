import json
from datetime import timedelta
from uuid import uuid4

import pytest
from django.core import signing
from django.utils import timezone
from rest_framework.exceptions import ValidationError,PermissionDenied
from plane.db.models import User
from plane.license.models import InstanceAdmin
from plane.quality.models import Defect,DefectEvent,SourceLink
from plane.quality.daq_incidents import SALT,fingerprint,signed_record
from plane.quality.remote_models import RemoteFeedbackBinding,RemoteWorkstation
from plane.quality.daq_execution_binding import approve_execution_binding,source_matches
from plane.tests.contract.app.test_remote_diagnostics import heartbeat

pytest_plugins=['plane.tests.contract.app.test_remote_diagnostics']
pytestmark=[pytest.mark.contract,pytest.mark.django_db]


@pytest.fixture
def binding(remote):
    _,edge,device,project=remote;heartbeat(edge)
    station=RemoteWorkstation.objects.select_related('agent__project__workspace','agent__owner').get(pk=device)
    station.enrollment_claim_hash='a'*64;station.machine_fingerprint='b'*64;station.save()
    station.agent.source_instance='daq-auto:'+str(station.id);station.agent.save()
    defect=Defect.objects.create(project=project,title='historical same computer',created_by=station.agent.owner)
    payload={'eventId':str(uuid4()),'device':str(station.id)}
    link=SourceLink.objects.create(project=project,defect=defect,created_by=station.agent.owner,
        source_system='ENGRAM_DAQ',source_instance='daq-auto:'+str(uuid4()),record_type='daq_incident',record_id='227:'+payload['eventId'],device=str(station.id))
    record={'linkId':str(link.id),'defectId':str(defect.id),'projectId':str(project.id),
        'sourceInstance':link.source_instance,'recordId':link.record_id,'actorId':str(link.created_by_id),
        'requestHash':fingerprint(payload),'payload':payload,'authorityMode':'report_only','externalActor':227}
    DefectEvent.objects.create(project=project,defect=defect,created_by=station.agent.owner,status='open',
        note=json.dumps({'incidentSignature':signing.dumps(record,salt=SALT)}))
    assert signed_record(link)
    return station,link


def approve(binding,**extra):
    station,link=binding
    return approve_execution_binding(actor=station.agent.owner,defect_id=link.defect_id,station_id=station.id,
        reason='用户要求在原电脑只读重新复核此反馈',expected_current_source=station.agent.source_instance,**extra)


def test_dryrun_changes_no_record_and_apply_preserves_original_signed_source(binding):
    station,link=binding
    original=link.__class__.objects.values().get(pk=link.pk)
    original_event=link.defect.events.get().note
    assert source_matches(station,link) is False
    assert approve(binding)['eligible'] is True
    assert not RemoteFeedbackBinding.objects.filter(defect=link.defect).exists()
    assert link.defect.events.count()==1
    applied=approve(binding,apply=True)
    assert applied['created'] and applied['scope']=='verify_only'
    assert source_matches(station,link) is True
    assert link.__class__.objects.values().get(pk=link.pk)==original
    assert link.defect.events.filter(note=original_event).exists()
    assert link.defect.events.count()==2
    assert approve(binding,apply=True)['created'] is False
    assert link.defect.events.count()==2


def test_generic_old_binding_never_bypasses_conflicting_source(binding):
    station,link=binding
    RemoteFeedbackBinding.objects.create(workstation=station,defect=link.defect,created_by=station.agent.owner)
    assert source_matches(station,link) is False


@pytest.mark.parametrize('invalid',['device','signature','source','fingerprint','claim','disabled','agent_disabled','expired','nonadmin','inactive_admin'])
def test_invalid_approval_cannot_write_or_authorize(binding,invalid):
    station,link=binding
    if invalid=='device':link.device=str(uuid4());link.save()
    elif invalid=='signature':link.defect.events.all().delete()
    elif invalid=='source':station.agent.source_instance='';station.agent.save()
    elif invalid=='fingerprint':station.machine_fingerprint='';station.save()
    elif invalid=='claim':station.enrollment_claim_hash='';station.save()
    elif invalid=='disabled':station.enabled=False;station.save()
    elif invalid=='agent_disabled':station.agent.enabled=False;station.agent.save()
    elif invalid=='expired':station.credential_expires_at=timezone.now()-timedelta(seconds=1);station.save()
    elif invalid=='nonadmin':InstanceAdmin.objects.filter(user=station.agent.owner).delete()
    else:station.agent.owner.is_active=False;station.agent.owner.save()
    with pytest.raises((ValidationError,PermissionDenied)):approve(binding,apply=True)
    assert link.defect.events.count()<2
    assert not RemoteFeedbackBinding.objects.filter(defect=link.defect).exists()


@pytest.mark.parametrize('change',['fingerprint','claim','source','expired','disabled','actor_revoked','signature_tamper'])
def test_approval_is_bound_to_current_identity_and_admin_authority(binding,change):
    station,link=binding;approve(binding,apply=True)
    if change=='fingerprint':station.machine_fingerprint='c'*64;station.save()
    elif change=='claim':station.enrollment_claim_hash='d'*64;station.save()
    elif change=='source':station.agent.source_instance='daq-auto:'+str(uuid4());station.agent.save()
    elif change=='expired':station.credential_expires_at=timezone.now()-timedelta(seconds=1);station.save()
    elif change=='disabled':station.enabled=False;station.save()
    elif change=='actor_revoked':InstanceAdmin.objects.filter(user=station.agent.owner).delete()
    else:
        event=link.defect.events.exclude(previous_status='').first() or link.defect.events.latest('created_at')
        event.note=event.note.replace('executionBindingSignature','invalidSignature');event.save()
    assert source_matches(station,link) is False


def test_expected_source_and_replay_to_another_defect_are_rejected(binding):
    station,link=binding
    with pytest.raises(ValidationError):approve_execution_binding(actor=station.agent.owner,
        defect_id=link.defect_id,station_id=station.id,reason='explicit',expected_current_source='different',apply=True)
    approve(binding,apply=True)
    other=Defect.objects.create(project=link.project,title='other')
    for event in link.defect.events.all():
        DefectEvent.objects.create(project=other.project,defect=other,created_by=event.created_by,status='open',note=event.note)
    clone=SourceLink.objects.create(project=link.project,defect=other,created_by=link.created_by,
        source_system=link.source_system,source_instance=link.source_instance,record_type=link.record_type,
        record_id='227:'+str(uuid4()),device=link.device)
    source=signed_record(link)
    source.update(linkId=str(clone.id),defectId=str(other.id),recordId=clone.record_id)
    DefectEvent.objects.create(project=clone.project,defect=other,created_by=clone.created_by,status='open',
        note=json.dumps({'incidentSignature':signing.dumps(source,salt=SALT)}))
    assert signed_record(clone)
    RemoteFeedbackBinding.objects.create(workstation=station,defect=other,created_by=station.agent.owner)
    assert source_matches(station,clone) is False


def test_approval_expires_and_does_not_authorize_a_different_station(binding):
    from unittest.mock import patch
    import time
    station,link=binding;approve(binding,apply=True)
    assert source_matches(station,link)
    with patch('django.core.signing.time.time',return_value=time.time()+31*86400):
        assert source_matches(station,link) is False
    station.id=uuid4()
    assert source_matches(station,link) is False


def test_approval_requires_same_project_and_explicit_reason(binding):
    from plane.db.models import Project
    station,link=binding
    with pytest.raises(ValidationError):approve_execution_binding(actor=station.agent.owner,defect_id=link.defect_id,
        station_id=station.id,reason='',expected_current_source=station.agent.source_instance,apply=True)
    other=Project.objects.create(workspace=link.project.workspace,name='foreign',identifier='FORBIND')
    station.agent.project=other;station.agent.save()
    with pytest.raises(ValidationError):approve(binding,apply=True)
    assert source_matches(station,link) is False


def test_management_command_is_dryrun_by_default_and_never_creates_an_agent_run(binding):
    from io import StringIO
    from django.core.management import call_command
    from plane.quality.remote_models import RemoteAgentRun
    station,link=binding
    output=StringIO()
    call_command('approve_daq_execution_binding',actor_id=str(station.agent.owner_id),defect_id=str(link.defect_id),
        station_id=str(station.pk),reason='explicit same-computer read-only recheck',
        expected_current_source=station.agent.source_instance,stdout=output)
    assert json.loads(output.getvalue())['applied'] is False
    assert not RemoteFeedbackBinding.objects.filter(defect=link.defect).exists()
    assert not RemoteAgentRun.objects.filter(defect=link.defect).exists()
