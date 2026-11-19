"""Agent evidence changes triage, never substitutes for human closure."""
from datetime import timedelta
from unittest.mock import patch
import pytest
from django.utils import timezone
from plane.db.models import Notification, ProjectMember, User, WorkspaceMember
from plane.quality.models import BusinessRole, Defect
from plane.quality.remote_models import RemoteAgentRun, RemoteCommand, RemoteWorkstation
from plane.quality.remote_diagnostics import identity_key, invalidate_run
from plane.quality.remote_tasks import finish
from plane.quality.serializers import DefectSerializer
from plane.tests.contract.app.test_remote_diagnostics import heartbeat

pytest_plugins=['plane.tests.contract.app.test_remote_diagnostics']
pytestmark=[pytest.mark.contract,pytest.mark.django_db]


@pytest.fixture
def job(remote):
    client,edge,device,project=remote;heartbeat(edge)
    station=RemoteWorkstation.objects.get(pk=device)
    defect=Defect.objects.create(project=project,title='actual Agent triage',created_by=station.agent.owner)
    run=RemoteAgentRun.objects.create(workstation=station,defect=defect,owner=station.agent.owner,
        status='running',started_at=timezone.now(),identity_key=identity_key(station),
        result={'defect_state_version':defect.edit_version},expires_at=timezone.now()+timedelta(minutes=5))
    return client,station,defect,run


@pytest.mark.parametrize('result,status,expected',[
    ({'repaired':True,'verification_passed':True},'completed','pending_tech'),
    ({'repaired':True,'verification_passed':False},'completed','needs_tech'),
    ({'repaired':False,'outcome':'verified_without_repair','verification_passed':True},'completed','pending_tech'),
    ({'repaired':False,'outcome':'verified','verification_passed':True},'completed','pending_tech'),
    ({'repaired':False,'verification_passed':False},'completed','needs_tech'),
    ({'repaired':True,'verification_passed':True},'failed','needs_tech'),
])
def test_agent_terminal_result_updates_triage_without_claiming_human_closure(job,result,status,expected):
    _,_,defect,run=job
    finish(run.id,{'summary':'actual evidence',**result},status)
    defect.refresh_from_db();run.refresh_from_db()
    assert defect.status==expected and defect.resolved_at is None and not defect.fixed_build
    assert run.comment_id and defect.edit_version==2
    assert defect.events.filter(previous_status='open',status=expected).exists()


@pytest.mark.parametrize('protection',['closed','archived','manual','newer_run','resolved'])
def test_old_agent_result_never_reopens_or_overwrites_human_progress(job,protection):
    _,station,defect,run=job
    if protection=='closed':defect.status='closed'
    elif protection=='archived':defect.archived_at=timezone.now()
    elif protection=='resolved':defect.status='resolved'
    elif protection=='manual':defect.edit_version+=1;defect.status='in_progress'
    else:RemoteAgentRun.objects.create(workstation=station,defect=defect,owner=run.owner,expires_at=run.expires_at)
    defect.save();expected=defect.status;version=defect.edit_version
    finish(run.id,{'summary':'late result','repaired':True,'verification_passed':True})
    defect.refresh_from_db()
    assert defect.status==expected and defect.edit_version==version


def test_interruption_is_actionable_and_finishing_again_is_idempotent(job):
    _,_,defect,run=job
    invalidate_run(run,'device identity changed')
    defect.refresh_from_db()
    assert defect.status=='needs_tech'
    count=defect.events.count();version=defect.edit_version
    invalidate_run(run,'device identity changed')
    finish(run.id,{'summary':'late','repaired':True,'verification_passed':True})
    defect.refresh_from_db()
    assert defect.edit_version==version and defect.events.count()==count


def test_latest_agent_processing_is_separate_from_main_status_and_batched(job,django_assert_num_queries):
    _,station,defect,run=job
    RemoteCommand.objects.create(workstation=station,run=run,payload={'kind':'patch_file'},expires_at=run.expires_at)
    rows=[defect]
    for index in range(4):
        other=Defect.objects.create(project=defect.project,title=f'agent batch {index}')
        RemoteAgentRun.objects.create(workstation=station,defect=other,owner=run.owner,status='completed',
            result={'repaired':False,'outcome':'verified_without_repair','verification_passed':True},expires_at=run.expires_at)
        rows.append(other)
    from plane.quality.agent_lifecycle import preload_processing
    with django_assert_num_queries(2):preload_processing(rows)
    assert defect._agent_processing['state']=='repair'
    assert all(row._agent_processing['state']=='verified' for row in rows[1:])
    assert DefectSerializer(defect).data['agent_processing']['run_id']==str(run.id)


def test_agent_notifies_only_active_responsible_technician_or_manager_once(job):
    _,_,defect,run=job
    owner=User.objects.create(username='agent-responsible',email='agent-responsible@invalid.example')
    WorkspaceMember.objects.create(workspace=defect.project.workspace,member=owner,role=15)
    ProjectMember.objects.create(project=defect.project,member=owner,role=15)
    BusinessRole.objects.create(project=defect.project,user=owner,role='TECHNICIAN')
    defect.assignee=owner;defect.save()
    finish(run.id,{'summary':'repair verified','repaired':True,'verification_passed':True})
    rows=Notification.objects.filter(entity_identifier=defect.id)
    assert list(rows.values_list('receiver_id',flat=True))==[owner.id]
    finish(run.id,{'summary':'duplicate','repaired':True,'verification_passed':True})
    assert rows.count()==1


def test_new_triage_states_can_resume_but_cannot_bypass_fixed_build_or_closure(job):
    client,_,defect,_=job
    base=f'/api/workspaces/{defect.project.workspace.slug}/projects/{defect.project_id}/quality/defects/{defect.id}/'
    for state in ['pending_tech','needs_tech']:
        Defect.objects.filter(pk=defect.pk).update(status=state)
        assert client.patch(base,{'status':'closed'},format='json').status_code==409
        assert client.patch(base,{'status':'resolved'},format='json').status_code==400
        response=client.patch(base,{'status':'in_progress'},format='json')
        assert response.status_code==200,response.content


def test_readonly_result_never_hides_partial_mutation_and_public_header_is_evidence_gated(job):
    _,station,defect,run=job
    RemoteCommand.objects.create(workstation=station,run=run,status='done',expires_at=run.expires_at,
        payload={'kind':'run','argv':['fixed','repair']},result={'ok':False,'exit_code':1,
            'stdout':'{"changes":[{"key":"flag","before":false,"after":true}]}'})
    finish(run.id,{'summary':'partial mutation','outcome':'verified_without_repair','verification_passed':True,'repaired':False})
    defect.refresh_from_db();run.refresh_from_db()
    assert defect.status=='needs_tech' and run.comment.content.startswith('Agent 远程处理：未自动修复')


def test_no_mutation_verified_without_repair_in_repair_mode_has_verified_public_header(job):
    _,_,defect,run=job
    finish(run.id,{'summary':'read only verified','outcome':'verified_without_repair','verification_passed':True,'repaired':False})
    run.refresh_from_db()
    assert run.comment.content.startswith('Agent 远程处理：验证通过')


def test_notification_falls_back_to_managers_without_valid_technician(job):
    _,_,defect,run=job
    finish(run.id,{'summary':'unresolved','verification_passed':False,'repaired':False})
    assert Notification.objects.filter(entity_identifier=defect.id,receiver=run.owner).count()==1


def test_worker_progress_captures_queue_version_and_does_not_reset_manual_changes(job):
    _,_,defect,run=job
    from plane.quality.agent_lifecycle import mark_started
    mark_started(run)
    defect.refresh_from_db()
    assert defect.status=='in_progress' and run.result['defect_state_version']==defect.edit_version
    run.save(update_fields=['result'])
    defect.title='human updated';defect.edit_version+=1;defect.save()
    finish(run.id,{'summary':'late successful result','repaired':True,'verification_passed':True})
    defect.refresh_from_db()
    assert defect.status=='in_progress' and defect.title=='human updated'


def test_triage_states_share_list_statistics_owner_and_overview_scopes(job):
    client,_,defect,run=job
    base=f'/api/workspaces/{defect.project.workspace.slug}/projects/{defect.project_id}/quality/'
    Defect.objects.filter(pk=defect.pk).update(status='pending_tech',assignee=run.owner)
    other=Defect.objects.create(project=defect.project,title='requires technician',status='needs_tech',assignee=run.owner)
    for state in ['pending_tech','needs_tech']:
        listed=client.get(base+'defects/',{'status':state})
        assert listed.status_code==200 and listed.data['count']==1
        assert listed.data['results'][0]['status']==state
        owners=client.get(base+'owner-statistics/',{'source':'defects','metric':state})
        assert owners.status_code==200 and owners.data['total']==1
    statistics=client.get(base+'defect-statistics/').data
    assert statistics['unclosed']==2
    assert {item['value']:item['count'] for item in statistics['by_status']}=={'pending_tech':1,'needs_tech':1}


def test_processing_uses_two_queries_and_never_selects_command_output(job,django_assert_num_queries):
    _,station,defect,run=job
    from django.test.utils import CaptureQueriesContext
    from django.db import connection
    from plane.quality.agent_lifecycle import preload_processing
    for index in range(45):
        RemoteCommand.objects.create(workstation=station,run=run,payload={'kind':'run','argv':['fixed','inspect']},
            result={'ok':True,'exit_code':0,'stdout':'large-output-'+('x'*65536)},expires_at=run.expires_at)
    # Even a mutation older than the latest display command excludes read-only claims.
    RemoteCommand.objects.create(workstation=station,run=run,payload={'kind':'patch_file'},status='done',
        result={'ok':False,'changes':[{'key':'partially_modified'}]},expires_at=run.expires_at)
    run.status='completed';run.result={'verification_passed':True,'outcome':'verified_without_repair','repaired':False};run.save()
    with CaptureQueriesContext(connection) as queries:preload_processing([defect])
    assert len(queries)==2
    assert len(defect._latest_agent_runs[0]._processing_commands)==1
    command_sql=queries.captured_queries[-1]['sql']
    assert 'processing_result' in command_sql and "'stdout'" not in command_sql and '"result",' not in command_sql
    assert defect._agent_processing['state']=='unresolved'


@pytest.mark.parametrize('status',['queued','running'])
def test_expired_runs_become_needs_tech_through_existing_detail_expiry(job,status):
    client,_,defect,run=job
    run.status=status;run.expires_at=timezone.now()-timedelta(seconds=1);run.save()
    from plane.tests.contract.app.test_remote_diagnostics import BASE
    response=client.get(BASE+f'agent-runs/{run.id}/')
    assert response.status_code==200,response.content
    defect.refresh_from_db();run.refresh_from_db()
    assert defect.status=='needs_tech' and run.status=='failed'
    assert Notification.objects.filter(entity_identifier=defect.id).count()==1


def test_actual_target_identity_change_invalidates_and_hands_off_once(job,remote):
    _,_,defect,run=job
    _,edge,_,_=remote
    assert heartbeat(edge,identity={'username':'caozuo1','hostname':'operator195','boot_id':'changedboot'}).status_code==200
    defect.refresh_from_db();run.refresh_from_db()
    assert run.status=='failed' and defect.status=='needs_tech'
    assert Notification.objects.filter(entity_identifier=defect.id).count()==1


def test_human_triage_confirmation_requires_current_version_and_verified_latest_run(job):
    client,_,defect,run=job
    url=f'/api/workspaces/{defect.project.workspace.slug}/projects/{defect.project_id}/quality/defects/{defect.id}/'
    assert client.patch(url,{'status':'pending_tech','expected_version':1},format='json').status_code==400
    run.status='completed';run.result={'repaired':True,'verification_passed':False};run.save()
    assert client.patch(url,{'status':'pending_tech','expected_version':1},format='json').status_code==400
    run.result={'repaired':True,'verification_passed':True};run.save()
    assert client.patch(url,{'status':'pending_tech'},format='json').status_code==400
    response=client.patch(url,{'status':'pending_tech','expected_version':1,'resolution':'人工复核当前Agent结果后交技术确认'},format='json')
    assert response.status_code==200,response.content
    defect.refresh_from_db()
    assert defect.status=='pending_tech'
    assert client.patch(url,{'status':'needs_tech','expected_version':1},format='json').status_code==409


def test_human_can_route_unresolved_to_needs_tech_without_claiming_verified(job):
    client,_,defect,run=job
    url=f'/api/workspaces/{defect.project.workspace.slug}/projects/{defect.project_id}/quality/defects/{defect.id}/'
    response=client.patch(url,{'status':'needs_tech','expected_version':1,'resolution':'人工复核未解决结果，技术跟进'},format='json')
    assert response.status_code==200,response.content
    run.status='completed';run.result={'outcome':'unresolved','verification_passed':False,'repaired':False};run.save()
    assert client.patch(url,{'status':'pending_tech','expected_version':2},format='json').status_code==400


@pytest.mark.parametrize('manual',[False,True])
def test_automatic_triage_advances_only_its_own_agent_version_chain(job,manual,django_capture_on_commit_callbacks):
    from types import SimpleNamespace
    from plane.quality.agent_lifecycle import mark_started
    from plane.quality.module_routing import route_completed
    _,_,defect,run=job
    defect.assignee=run.owner;defect.assignment_origin='triage';defect.assignment_reason='initial';defect.save()
    mark_started(run);run.save(update_fields=['result']);defect.refresh_from_db()
    if manual:
        defect.edit_version+=1;defect.title='human handled';defect.save()
    diagnostic=SimpleNamespace(status='completed',defect_id=defect.id,created_by=run.owner)
    with django_capture_on_commit_callbacks(execute=True),patch('plane.quality.module_routing.evidence_modules',return_value=(set(),'trusted metadata')):
        route_completed(diagnostic)
    run.refresh_from_db()
    finish(run.id,{'summary':'verified','repaired':True,'verification_passed':True})
    defect.refresh_from_db()
    assert defect.status==('in_progress' if manual else 'pending_tech')
    if manual:assert defect.title=='human handled'


def test_agent_lifecycle_events_have_readable_actions_without_run_ids_in_summary(job):
    from plane.quality.agent_lifecycle import mark_started
    from plane.quality.serializers import EventSerializer
    _,_,defect,run=job
    mark_started(run);run.save(update_fields=['result'])
    finish(run.id,{'summary':'verified','repaired':True,'verification_passed':True})
    events=defect.events.filter(note__startswith='Agent ')
    summaries=[EventSerializer(event,context={}).data['remote_process']['summary'] for event in events]
    assert any('开始排查' in value for value in summaries)
    assert any('待技术确认' in value for value in summaries)
    assert all(str(run.id) not in value for value in summaries)


def test_valid_json_stdout_cannot_hide_outer_partial_mutation_receipt(job):
    _,station,defect,run=job
    RemoteCommand.objects.create(workstation=station,run=run,status='done',expires_at=run.expires_at,
        payload={'kind':'run','argv':['fixed','repair']},result={'ok':False,'exit_code':1,
            'changes':[{'key':'partially_modified','before':False,'after':True}],
            'stdout':'{"simulation":true,"ok":false}'})
    finish(run.id,{'summary':'verified after a partial change','outcome':'verified_without_repair',
        'verification_passed':True,'repaired':False})
    defect.refresh_from_db();run.refresh_from_db()
    assert defect.status=='needs_tech'
    assert run.comment.content.startswith('Agent 远程处理：未自动修复')
    assert DefectSerializer(defect).data['agent_processing']['state']=='unresolved'
