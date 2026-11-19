"""Diagnostic context retains confirmed writes even when final report generation failed."""
import json
from datetime import timedelta

import pytest
from django.utils import timezone

from plane.quality.models import Defect,DiagnosticJob
from plane.quality.remote_models import RemoteAgentRun,RemoteCommand,RemoteWorkstation
from plane.quality.remote_diagnostics import identity_key
from plane.quality.diagnostic_context import diagnostic_context
from plane.tests.contract.app.test_remote_diagnostics import heartbeat

pytest_plugins=['plane.tests.contract.app.test_remote_diagnostics']
pytestmark=[pytest.mark.contract,pytest.mark.django_db]


def test_latest_readonly_verification_does_not_hide_earlier_actual_config_write(remote):
    _,edge,device,project=remote;heartbeat(edge)
    station=RemoteWorkstation.objects.get(pk=device)
    defect=Defect.objects.create(project=project,title='reset failed')
    old=RemoteAgentRun.objects.create(workstation=station,defect=defect,owner=station.agent.owner,
        mode='repair',status='failed',error='UsageLimitExceeded',identity_key=identity_key(station),
        result={'summary':'report not finalized','configuration_repaired':True},expires_at=timezone.now()+timedelta(minutes=1))
    from plane.quality.models import DefectComment
    old.comment=DefectComment.objects.create(project=project,defect=defect,created_by=station.agent.owner,
        visibility='public',content='Agent 远程处理：配置已修复，待业务验证')
    old.save()
    path='/state/robot_config_overrides/robot/custom/initial_joint_states.yaml'
    change={'path':path,'key':'initial_joint_states.arm[0]','before':3.3,'after':.3,'line':2}
    RemoteCommand.objects.create(workstation=station,run=old,status='done',expires_at=old.expires_at,
        payload={'kind':'run','argv':['daq-local-diagnostics-v1','repair','a'*64]},
        result={'ok':True,'exit_code':0,'changes':[change]})
    latest=RemoteAgentRun.objects.create(workstation=station,defect=defect,owner=station.agent.owner,
        mode='verify',status='completed',identity_key=identity_key(station),
        result={'summary':'current configuration passed','configuration_verified':True},expires_at=old.expires_at,
        comment=DefectComment.objects.create(project=project,defect=defect,created_by=station.agent.owner,
            visibility='public',content='Agent 远程处理：配置检查通过，待业务验证'))
    job=DiagnosticJob.objects.create(project=project,defect=defect,mode='auto',request_id=__import__('uuid').uuid4())
    refs=diagnostic_context(job)
    actual=next(ref for ref in refs if ref['reference']=='PLATFORM-FIELD-CHANGES')
    content=json.loads(actual['content'].split('\n',1)[0])
    assert content['changes'][0]['path']==path
    assert content['changes'][0]['before']==3.3 and content['changes'][0]['after']==.3
    assert content['source_run_status']=='failed'
    assert content['business_verified'] is False
