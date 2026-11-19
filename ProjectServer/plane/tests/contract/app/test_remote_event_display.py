from datetime import timedelta
import pytest
from django.utils import timezone
from plane.quality.models import Defect,DefectEvent
from plane.quality.remote_models import RemoteWorkstation,RemoteAgentRun,RemoteCommand,RemoteFeedbackBinding
from plane.quality.remote_diagnostics import identity_key
from plane.quality.serializers import EventSerializer
from plane.quality.remote_event_display import safe_argv
from plane.tests.contract.app.test_remote_diagnostics import BASE,heartbeat

pytest_plugins=['plane.tests.contract.app.test_remote_diagnostics']
pytestmark=[pytest.mark.contract,pytest.mark.django_db]


def test_historical_event_projects_actual_task_command_with_no_credentials(remote):
    _,edge,device,project=remote;heartbeat(edge)
    station=RemoteWorkstation.objects.get(pk=device)
    station.capabilities={'network':{'ip_address':'10.10.10.195'},'agent_context':{'inspect_argv':['fixed','inspect']}};station.save()
    defect=Defect.objects.create(project=project,title='human readable',description='human readable')
    run=RemoteAgentRun.objects.create(workstation=station,defect=defect,owner=station.agent.owner,mode='repair',identity_key=identity_key(station),expires_at=timezone.now()+timedelta(minutes=5))
    command=RemoteCommand.objects.create(workstation=station,run=run,payload={'kind':'run','argv':['fixed','inspect']},status='done',result={'ok':True,'exit_code':0},expires_at=run.expires_at)
    original=f'Agent 现场排查：工具执行完成；任务 {run.id}；命令 {command.id}。'
    event=DefectEvent.objects.create(project=project,defect=defect,created_by=station.agent.owner,status=defect.status,previous_status=defect.status,note=original)
    value=EventSerializer(event,context={}).data
    assert '第1轮诊断修复' in value['remote_process']['summary']
    assert str(run.id) not in value['remote_process']['summary']
    assert value['remote_process']['command']['argv']==['fixed','inspect']
    event.refresh_from_db();assert event.note==original
    masked=safe_argv(['sshpass','-p','very-private','--token=secret-value'])
    assert masked[:3]==['sshpass','-p','[已隐藏]'] and 'secret-value' not in ' '.join(masked)


def test_active_processing_restores_only_visible_owner_run(remote):
    client,edge,device,project=remote;heartbeat(edge)
    station=RemoteWorkstation.objects.get(pk=device)
    defect=Defect.objects.create(project=project,title='restore spinner',description='restore spinner')
    RemoteFeedbackBinding.objects.create(workstation=station,defect=defect)
    run=RemoteAgentRun.objects.create(workstation=station,defect=defect,owner=station.agent.owner,identity_key=identity_key(station),expires_at=timezone.now()+timedelta(minutes=5))
    value=client.get(BASE+'defect-targets/',{'defect_id':str(defect.id)}).data
    assert value['active_run']['id']==str(run.id) and value['active_run']['status']=='queued'
