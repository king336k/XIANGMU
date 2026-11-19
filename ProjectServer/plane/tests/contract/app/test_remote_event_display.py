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
    assert value['remote_process']['command']['ok'] is True and value['remote_process']['command']['status']=='done'
    assert value['remote_process']['target']['username']==station.username
    assert value['remote_process']['target']['host']=='10.10.10.195'
    assert value['remote_process']['target']['identity_source']=='current_registration'
    run.result={'target_snapshot':{'collector':{'username':'collector-old','host':'10.10.10.194'}}};run.save(update_fields=['result'])
    frozen=EventSerializer(event,context={}).data['remote_process']['target']
    assert frozen['username']=='collector-old' and frozen['host']=='10.10.10.194' and frozen['identity_source']=='execution_snapshot'
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


def test_patch_details_use_actual_changes_and_hide_secret_values(remote):
    _,edge,device,project=remote;heartbeat(edge)
    station=RemoteWorkstation.objects.get(pk=device)
    defect=Defect.objects.create(project=project,title='readable JSON change',description='readable JSON change')
    run=RemoteAgentRun.objects.create(workstation=station,defect=defect,owner=station.agent.owner,expires_at=timezone.now()+timedelta(minutes=5))
    result={'ok':True,'exit_code':0,'resolved_path':'/approved/collector-config.json','backup':'/approved/collector-config.json.backup-real','sha256':'b'*64,
        'changes':[{'path':'/approved/collector-config.json','key':'robot_port','before':18778,'after':18777,'before_exists':True,'after_exists':True,'before_line':3,'after_line':4},
            {'path':'/approved/collector-config.json','key':'password','before':'private-old','after':'private-new','before_exists':True,'after_exists':True}]}
    command=RemoteCommand.objects.create(workstation=station,run=run,payload={'kind':'patch_file','path':'collector-config.json','expected_sha256':'a'*64},result=result,status='done',expires_at=run.expires_at)
    event=DefectEvent.objects.create(project=project,defect=defect,created_by=station.agent.owner,status=defect.status,previous_status=defect.status,note=f'Agent 配置修复：工具执行完成；任务 {run.id}；命令 {command.id}。')
    value=EventSerializer(event,context={}).data['remote_process']
    assert value['details']=='修改配置文件'
    assert value['command']['changes'][0]['before']==18778 and value['command']['changes'][0]['after']==18777
    assert value['command']['changes'][0]['after_line']==4
    assert 'private-old' not in str(value) and 'private-new' not in str(value)


def test_shell_credentials_and_secret_alias_keys_never_reach_details(remote):
    import json
    for argv,secret in [(['bash','-lc','sshpass -p synthetic-shell-secret ssh host'],'synthetic-shell-secret'),
        (['tool','--access-token','synthetic-token-secret'],'synthetic-token-secret'),
        (['mysql','-psynthetic-attached-secret'],'synthetic-attached-secret'),
        (['mysql','-p384729'],'384729')]:
        assert secret not in str(safe_argv(argv))
    from plane.quality.remote_event_display import sensitive_name
    assert all(sensitive_name(key)for key in ['ssh_password','robot_password','apiToken','API_KEY'])
    from plane.quality.remote_event_display import safe_change_value
    nested=safe_change_value({'robot':{'ssh_password':'synthetic-nested-secret'},'port':18777})
    assert 'synthetic-nested-secret' not in str(nested) and nested['port']==18777


def test_fixed_robot_repair_uses_actual_stdout_identity_and_changes(remote):
    import json
    _,edge,device,project=remote;heartbeat(edge)
    station=RemoteWorkstation.objects.get(pk=device)
    station.capabilities={'network':{'ip_address':'10.10.10.195'},'agent_context':{'repair_argv':['fixed','repair']}};station.save()
    defect=Defect.objects.create(project=project,title='robot receipt',description='robot receipt')
    run=RemoteAgentRun.objects.create(workstation=station,defect=defect,owner=station.agent.owner,expires_at=timezone.now()+timedelta(minutes=5))
    change={'target_kind':'robot','target_username':'engram','target_ip':'10.10.10.177','path':'/robot/robot-config.json','key':'telemetry_enabled','before':False,'after':True,'before_line':4,'after_line':4}
    command=RemoteCommand.objects.create(workstation=station,run=run,payload={'kind':'run','argv':['fixed','repair','--expected-sha256','a'*64]},result={'ok':True,'exit_code':0,'stdout':json.dumps({'simulation':True,'repaired':True,'changes':[change]})},status='done',expires_at=run.expires_at)
    event=DefectEvent.objects.create(project=project,defect=defect,created_by=station.agent.owner,status=defect.status,previous_status=defect.status,note=f'Agent 现场修复：任务 {run.id}；命令 {command.id}。')
    value=EventSerializer(event,context={}).data['remote_process']
    assert value['target']['label']=='机器人' and value['target']['host']=='10.10.10.177'
    assert value['command']['changes'][0]['key']=='telemetry_enabled'
    assert value['command']['changes'][0]['before'] is False
    command.payload={'kind':'run','argv':['unrelated','command']};command.save()
    ignored=EventSerializer(event,context={}).data['remote_process']
    assert ignored['command']['changes']==[] and ignored['target']['label'].startswith('采集电脑')


def test_frozen_display_policy_survives_registration_changes(remote):
    import json
    _,edge,device,project=remote;heartbeat(edge)
    station=RemoteWorkstation.objects.get(pk=device)
    station.capabilities={'agent_context':{'repair_argv':['replacement','repair']}};station.save()
    defect=Defect.objects.create(project=project,title='historical robot receipt',description='historical robot receipt')
    run=RemoteAgentRun.objects.create(workstation=station,defect=defect,owner=station.agent.owner,
        result={'display_policy_snapshot':{'repair_argv':['fixed','repair']}},expires_at=timezone.now()+timedelta(minutes=5))
    change={'target_kind':'robot','target_username':'robot-old','target_ip':'10.10.10.177','path':'/robot/config.json','key':'telemetry_enabled','before':False,'after':True,'after_line':4}
    command=RemoteCommand.objects.create(workstation=station,run=run,payload={'kind':'run','argv':['fixed','repair']},
        result={'ok':True,'exit_code':0,'stdout':json.dumps({'simulation':True,'changes':[change]})},status='done',expires_at=run.expires_at)
    event=DefectEvent.objects.create(project=project,defect=defect,created_by=station.agent.owner,status=defect.status,previous_status=defect.status,note=f'Agent 现场修复：任务 {run.id}；命令 {command.id}。')
    value=EventSerializer(event,context={}).data['remote_process']
    assert value['target']['host']=='10.10.10.177' and value['command']['changes'][0]['after_line']==4
    assert value['policy_source']=='execution_snapshot'
    run.result={};run.save(update_fields=['result'])
    legacy=EventSerializer(event,context={}).data['remote_process']
    assert legacy['policy_source']=='current_registration' and legacy['policy_label']=='当前登记上下文'


def test_worker_freezes_only_safe_display_policy_and_finish_preserves_it(remote):
    import json
    from types import SimpleNamespace
    from unittest.mock import patch
    from plane.quality.remote_tasks import remote_repair
    _,edge,device,project=remote;heartbeat(edge)
    station=RemoteWorkstation.objects.get(pk=device)
    station.capabilities={'agent_context':{'inspect_argv':['fixed','inspect'],'verify_argv':['fixed','verify'],
        'repair_argv':['fixed','repair','--token','synthetic-policy-secret'],'verification_scope':'read_only_connectivity',
        'unrelated_token':'synthetic-unrelated-secret'}};station.save()
    defect=Defect.objects.create(project=project,title='frozen safe policy',description='frozen safe policy')
    run=RemoteAgentRun.objects.create(workstation=station,defect=defect,owner=station.agent.owner,identity_key=identity_key(station),expires_at=timezone.now()+timedelta(minutes=5))
    with patch('plane.quality.remote_tasks.provider_config',return_value={'configured':True}),patch('plane.quality.remote_tasks.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps({'summary':'finished','repaired':False}))):
        remote_repair.run(str(run.id))
    run.refresh_from_db()
    snapshot=run.result['display_policy_snapshot']
    assert set(snapshot)=={'inspect_argv','verify_argv','repair_argv','verification_scope'}
    assert snapshot['inspect_argv']==['fixed','inspect'] and snapshot['verify_argv']==['fixed','verify']
    assert snapshot['verification_scope']=='read_only_connectivity'
    assert 'synthetic-policy-secret' not in str(snapshot) and 'synthetic-unrelated-secret' not in str(snapshot)
    station.capabilities={'agent_context':{'repair_argv':['replacement','repair']}};station.save()
    command=RemoteCommand.objects.create(workstation=station,run=run,
        payload={'kind':'run','argv':['fixed','repair','--token','synthetic-policy-secret']},status='done',expires_at=run.expires_at,
        result={'ok':True,'exit_code':0,'stdout':json.dumps({'simulation':True,'changes':[{'target_kind':'robot','target_username':'robot','target_ip':'10.10.10.177','key':'enabled','after':True,'after_line':4}]})})
    event=DefectEvent.objects.create(project=project,defect=defect,created_by=station.agent.owner,status=defect.status,previous_status=defect.status,note=f'Agent 现场修复：任务 {run.id}；命令 {command.id}。')
    display=EventSerializer(event,context={}).data['remote_process']
    assert display['target']['host']=='10.10.10.177' and display['command']['changes'][0]['after_line']==4
    assert 'synthetic-policy-secret' not in str(display)


def test_public_reply_projects_only_its_observed_repair_locations(remote):
    from plane.quality.models import DefectComment
    from plane.quality.sources import CommentSerializer
    _,edge,device,project=remote;heartbeat(edge)
    station=RemoteWorkstation.objects.get(pk=device)
    defect=Defect.objects.create(project=project,title='reply diff',description='reply diff')
    comment=DefectComment.objects.create(project=project,defect=defect,created_by=station.agent.owner,visibility='public',content='Agent 远程处理：已修复')
    run=RemoteAgentRun.objects.create(workstation=station,defect=defect,owner=station.agent.owner,comment=comment,expires_at=timezone.now()+timedelta(minutes=5),
        result={'repair_locations':[{'target':'采集电脑：collector@10.0.0.195','path':'/approved/config.json','key':'robot_port','before':18778,'after':18777,'line':4,'before_line':4,'backup':'/approved/config.json.backup-actual'},
        {'target':'采集电脑','path':'/approved/config.json','key':'robot_password','before':'synthetic-old-secret','after':'synthetic-new-secret'}]})
    value=CommentSerializer(comment).data
    assert value['repair_changes'][0]['before']==18778 and value['repair_changes'][0]['after']==18777
    assert value['repair_changes'][0]['line']==4 and 'after_line' not in value['repair_changes'][0]
    assert 'synthetic-old-secret' not in str(value) and 'synthetic-new-secret' not in str(value)
    run.defect=Defect.objects.create(project=project,title='other feedback',description='other feedback');run.save()
    assert CommentSerializer(comment).data['repair_changes']==[]


def test_command_output_is_actual_bounded_and_redacted(remote):
    from plane.quality.models import DefectComment
    from plane.quality.sources import CommentSerializer
    from plane.quality.remote_event_display import safe_output
    client,edge,device,project=remote;heartbeat(edge)
    station=RemoteWorkstation.objects.get(pk=device)
    defect=Defect.objects.create(project=project,title='command output',description='command output')
    comment=DefectComment.objects.create(project=project,defect=defect,created_by=station.agent.owner,visibility='public',content='Agent 远程处理：未自动修复')
    run=RemoteAgentRun.objects.create(workstation=station,defect=defect,owner=station.agent.owner,comment=comment,expires_at=timezone.now()+timedelta(minutes=5))
    RemoteCommand.objects.create(workstation=station,run=run,payload={'kind':'run','argv':['pip','check']},result={'ok':False,'exit_code':1,'stdout':'dependency check ran','stderr':'missing package'},status='done',expires_at=run.expires_at)
    value=CommentSerializer(comment).data
    command=value['command_operations'][0]
    assert command['argv']==['pip','check'] and command['stdout']=='dependency check ran'
    assert command['exit_code']==1 and command['ok'] is False and command['stderr']=='missing package'
    assert 'synthetic-value' not in safe_output('{"robot":{"ssh_password":"synthetic-value"}}')
    assert 'synthetic-value' not in safe_output('ssh_password=synthetic-value')
    assert 'synthetic-value' not in safe_output('+ sshpass -p synthetic-value ssh robot')
    assert 'synthetic-value' not in safe_output('{"execution_steps":[{"argv":["sshpass","-p","synthetic-value","ssh","robot"]}]}')
    assert 'synthetic-value' not in safe_output('{"stdout":"+ sshpass -p synthetic-value ssh robot"}')
    assert 'synthetic-value' not in safe_output('ssh_password:\n  synthetic-value\nstatus: stopped')
    assert len(safe_output('x'*70000))<=8192
    response=client.get(f'/api/workspaces/{project.workspace.slug}/projects/{project.id}/quality/defects/{defect.id}/collaboration/')
    assert response.status_code==200,response.data
    assert response.data['results'][0]['command_operations'][0]['exit_code']==1


def test_reply_line_evidence_never_crosses_targets_and_robot_command_target_is_actual(remote):
    import json
    from plane.quality.models import DefectComment
    from plane.quality.sources import CommentSerializer
    _,edge,device,project=remote;heartbeat(edge)
    station=RemoteWorkstation.objects.get(pk=device)
    defect=Defect.objects.create(project=project,title='target scoped lines',description='target scoped lines')
    comment=DefectComment.objects.create(project=project,defect=defect,created_by=station.agent.owner,visibility='public',content='Agent 远程处理：已修复')
    location={'target':'采集电脑：collector@10.0.0.195','target_kind':'collector','username':'collector','ip_address':'10.0.0.195','path':'/shared/config.json','key':'port','before':2,'after':1}
    run=RemoteAgentRun.objects.create(workstation=station,defect=defect,owner=station.agent.owner,comment=comment,expires_at=timezone.now()+timedelta(minutes=5),result={'repair_locations':[location]})
    change={'target_kind':'robot','target_username':'robot','target_ip':'10.0.0.177','path':'/shared/config.json','key':'port','before':2,'after':1,'after_line':10}
    command=RemoteCommand.objects.create(workstation=station,run=run,payload={'kind':'run','argv':['fixed','repair']},status='done',result={'ok':True,'exit_code':0,'stdout':json.dumps({'simulation':True,'changes':[change]})},expires_at=run.expires_at)
    value=CommentSerializer(comment).data
    assert 'after_line' not in value['repair_changes'][0]
    assert value['command_operations'][0]['target']=='机器人：robot@10.0.0.177'
    change.update(target_kind='collector',target_username='collector',target_ip='10.0.0.195',after_line=4)
    command.result={'ok':True,'exit_code':0,'changes':[change]};command.save()
    assert CommentSerializer(comment).data['repair_changes'][0]['after_line']==4
