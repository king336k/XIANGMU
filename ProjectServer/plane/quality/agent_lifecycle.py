"""Agent progress and evidence-gated handoff; human verification owns closure."""
import json
from types import SimpleNamespace

from django.db import transaction
from django.db.models import Exists, OuterRef, Prefetch, Q, prefetch_related_objects
from django.utils import timezone

from .diagnostic_redaction import redact
from .models import Defect, DefectEvent
from .remote_models import RemoteAgentRun, RemoteCommand

DEFECT_STATUSES = ('open', 'in_progress', 'pending_tech', 'needs_tech', 'resolved', 'closed')
ACTIVE_DEFECT_STATUSES = DEFECT_STATUSES[:-1]
STATUS_LABELS = {'open':'待处理','in_progress':'处理中','pending_tech':'待技术确认',
    'needs_tech':'待技术处理','resolved':'待回归','closed':'已关闭'}
PROCESS_LABELS = {'analysis':'分析中','queued':'排队中','inspect':'排查中','repair':'修复中','verify':'复测中',
    'repaired':'已修复','verified':'复核通过','unresolved':'未解决','interrupted':'已中断'}


LIMITED_VERIFICATION_SCOPES = {'configuration_validation', 'read_only_connectivity', 'readonly_connectivity'}


def limited_verification_scope(run, result=None):
    """A model report cannot broaden server-owned or previously observed coverage."""
    result = run.result if result is None else result
    snapshot = run.result.get('display_policy_snapshot') or {}
    state = getattr(run, '_state', None)
    station = state.fields_cache.get('workstation') if state is not None else None
    context = station.capabilities.get('agent_context', {}) if station is not None else {}
    for value in (result.get('verification_scope'), snapshot.get('verification_scope'), context.get('verification_scope')):
        if isinstance(value, str) and value in LIMITED_VERIFICATION_SCOPES:
            return value
    return None


def configuration_receipts(run):
    """Derive configuration progress from this run's fixed adapter receipts."""
    scope = None
    last_write = last_applied = last_verify = -1
    verified = config_verified = False
    locations = []
    for index, command in enumerate(run.remotecommand_set.order_by('created_at', 'id')):
        payload, receipt = command.payload, command.result
        argv = payload.get('argv', [])
        if payload.get('kind') == 'patch_file':
            last_write = index
        if payload.get('kind') != 'run':
            continue
        if not isinstance(argv, list) or argv[:1] != ['daq-local-diagnostics-v1']:
            last_write = index
            continue
        try:
            body = json.loads(receipt.get('stdout', '{}'))
        except (ValueError, TypeError):
            body = {}
        body = body if isinstance(body, dict) else {}
        observed_scope = body.get('scope', body.get('verification_scope'))
        if isinstance(observed_scope, str) and observed_scope in LIMITED_VERIFICATION_SCOPES:
            scope = observed_scope
        complete = (command.status == 'done' and receipt.get('ok') is not False
                    and receipt.get('exit_code') == 0 and not receipt.get('timed_out')
                    and not receipt.get('error') and not receipt.get('truncated'))
        configuration = body.get('configuration', {})
        configuration = configuration if isinstance(configuration, dict) else {}
        if (argv == ['daq-local-diagnostics-v1', 'inspect'] and
                configuration.get('state') in {'fail', 'unknown'}):
            verified = config_verified = False
        if argv == ['daq-local-diagnostics-v1', 'verify']:
            last_verify = index
            verified = (complete and isinstance(observed_scope, str) and observed_scope in LIMITED_VERIFICATION_SCOPES and body.get('verified') is True
                        and (observed_scope != 'configuration_validation' or configuration.get('state') == 'pass'))
            config_verified = verified and observed_scope == 'configuration_validation'
        elif len(argv) == 3 and argv[:2] == ['daq-local-diagnostics-v1', 'repair']:
            last_write = index
            repair = configuration.get('repair', {})
            repair = repair if isinstance(repair, dict) else {}
            changes = repair.get('changes', body.get('changes', []))
            if (command.status == 'done' and repair.get('state') in {'applied', 'written_runtime_unverified'}
                    and isinstance(changes, list)):
                valid_changes = 0
                for change in changes[:10]:
                    if (not isinstance(change, dict) or not isinstance(change.get('path'), str) or not change['path']
                            or not isinstance(change.get('key'), str) or not change['key'].startswith('initial_joint_states.')
                            or 'before' not in change or 'after' not in change or change['before'] == change['after']):
                        continue
                    valid_changes += 1
                    row = {key: change[key] for key in ('path', 'key', 'before', 'after', 'backup') if key in change}
                    row.update(target_kind='collector', target='采集电脑')
                    if type(change.get('line')) is int and change['line'] > 0:
                        row['line'] = change['line']
                    locations.append(row)
                if complete and repair.get('state') == 'applied' and valid_changes and run.mode == 'repair':
                    last_applied = index
    verified = verified and last_verify > last_write
    config_verified = verified and config_verified
    return {'scope': scope, 'verification_passed': verified, 'configuration_verified': config_verified,
            'configuration_repaired': config_verified and last_applied >= 0 and last_applied == last_write,
            'repair_locations': locations[-10:]}


def readonly_verified(run, result=None):
    result = run.result if result is None else result
    if (limited_verification_scope(run, result) or result.get('verification_passed') is not True or result.get('repaired') is True
            or result.get('outcome') not in {'verified','verified_without_repair'}
            or result.get('repair_locations')):
        return False
    if hasattr(run,'processing_mutation'):
        return not run.processing_mutation
    rows = command_rows(run)
    if rows is None:
        rows = run.remotecommand_set.all()
    for command in rows:
        # A failing command may already have applied part of a patch.
        if command.payload.get('kind') == 'patch_file' and command.status in {'delivered','done'}:return False
        receipt = command.result
        if receipt.get('changes'):return False
        if isinstance(receipt.get('stdout'),str):
            try:receipt=json.loads(receipt['stdout'])
            except (ValueError,TypeError):pass
        if isinstance(receipt,dict) and receipt.get('changes'):return False
    return True


def terminal_state(run):
    if run.status in {'failed','cancelled','expired'} or (run.result or {}).get('invalidated_at'):
        return 'interrupted'
    if limited_verification_scope(run):
        return 'unresolved'
    if run.status == 'completed' and run.result.get('verification_passed') is True:
        if run.result.get('repaired') is True:return 'repaired'
        if readonly_verified(run):return 'verified'
    return 'unresolved'


def latest_run(run):
    return not RemoteAgentRun.objects.filter(defect_id=run.defect_id).filter(
        Q(created_at__gt=run.created_at) | Q(created_at=run.created_at,id__gt=run.id)).exists()


def advance_after_metadata(defect, previous_version):
    """Trusted automatic metadata may advance ownership, never a manual edit.

    Defer run locking until the diagnostic's defect lock has been released.
    Consecutive automatic writes form a CAS chain; a manual version breaks it.
    """
    if defect.status != 'in_progress':return
    run=RemoteAgentRun.objects.filter(defect=defect).order_by('-created_at','-id').first()
    if run is None or run.status not in {'queued','running'}:return
    next_version=defect.edit_version
    transaction.on_commit(lambda:advance_metadata_version(run.id,previous_version,next_version))


@transaction.atomic
def advance_metadata_version(run_id,previous_version,next_version):
    from .remote_models import RemoteWorkstation
    station_id=RemoteAgentRun.objects.values_list('workstation_id',flat=True).get(pk=run_id)
    RemoteWorkstation.objects.select_for_update(of=('self',)).get(pk=station_id)
    run=RemoteAgentRun.objects.select_for_update(of=('self',)).get(pk=run_id)
    defect=Defect.objects.select_for_update().get(pk=run.defect_id)
    if (not latest_run(run) or defect.archived_at or defect.status!='in_progress'
            or run.result.get('defect_state_version') != previous_version):return
    run.result={**run.result,'defect_state_version':next_version}
    run.save(update_fields=['result'])
    if run.status not in {'queued','running'}:handoff(run)


def mark_started(run):
    defect = Defect.objects.select_for_update().get(pk=run.defect_id)
    expected = run.result.get('defect_state_version')
    if (not latest_run(run) or defect.archived_at or defect.status not in {'open','in_progress','pending_tech','needs_tech'}
            or expected != defect.edit_version):return
    if defect.status != 'in_progress':
        previous = defect.status
        defect.status='in_progress';defect.edit_version+=1
        defect.save(update_fields=['status','edit_version','updated_at'])
        DefectEvent.objects.create(project_id=defect.project_id,defect=defect,created_by=run.owner,
            previous_status=previous,status=defect.status,note=f'Agent 开始现场排查；任务 {run.id}。')
    run.result={**run.result,'defect_state_version':defect.edit_version}


@transaction.atomic
def handoff(run):
    locked=RemoteAgentRun.objects.select_for_update().get(pk=run.pk)
    run.result=locked.result
    if run.result.get('lifecycle_finalized'):return
    defect=Defect.objects.select_for_update().select_related('project__workspace').get(pk=run.defect_id)
    if (not latest_run(run) or defect.archived_at or defect.status not in {'open','in_progress','pending_tech','needs_tech'}
            or run.result.get('defect_state_version') != defect.edit_version):return
    state=terminal_state(run)
    next_status='pending_tech' if state in {'repaired','verified'} else 'needs_tech'
    previous=defect.status
    defect.status=next_status;defect.edit_version+=1
    defect.save(update_fields=['status','edit_version','updated_at'])
    DefectEvent.objects.create(project_id=defect.project_id,defect=defect,created_by=run.owner,
        previous_status=previous,status=next_status,note=f'Agent 结果已交技术跟进：{STATUS_LABELS[next_status]}；任务 {run.id}。')
    from .module_owners import eligible_technician
    from .notifications import managers,notify
    from .permissions import writable_member
    valid=defect.assignee_id and eligible_technician(defect.project,defect.assignee_id) and writable_member(
        defect.project_id,defect.assignee_id,defect.project.workspace.slug)
    receivers=[defect.assignee_id] if valid else managers(defect.project)
    notify(defect.project,None,receivers,defect.id,f'Agent处理结束，{STATUS_LABELS[next_status]}：{defect.title}',f'defects?defect={defect.id}')
    run.result={**run.result,'lifecycle_finalized':True}
    run.save(update_fields=['result'])


def processing(run):
    if run is None:return None
    now=timezone.now()
    if run.status in {'queued','running'} and run.expires_at<=now:state='interrupted'
    elif run.status=='queued':state='queued'
    elif run.status=='running':
        from .remote_run_state import run_queue
        state=run_queue(run)['stage']
    else:state=terminal_state(run)
    commands=getattr(run,'_processing_commands',[])
    updated=run.completed_at or (commands[0].created_at if commands else None) or run.started_at or run.created_at
    return {'state':state,'label':PROCESS_LABELS[state],'run_id':str(run.id),'updated_at':updated.isoformat(),
        'summary':redact(str(run.result.get('summary') or PROCESS_LABELS[state]))[:300]}


def processing_prefetch():
    from django.db.models import F
    from django.db.models.functions import JSONObject
    commands=RemoteCommand.objects.only('id','run_id','status','created_at').annotate(
        processing_payload=JSONObject(kind=F('payload__kind'),argv=F('payload__argv')),
        processing_result=JSONObject(ok=F('result__ok'),exit_code=F('result__exit_code')),
    ).order_by('-created_at','-id')[:1]
    runs=with_mutation_evidence(RemoteAgentRun.objects.all()).select_related('workstation').prefetch_related(
        Prefetch('remotecommand_set',queryset=commands,to_attr='_processing_commands')).order_by('-created_at','-id')[:1]
    return Prefetch('remoteagentrun_set',queryset=runs,to_attr='_latest_agent_runs')


def with_mutation_evidence(queryset):
    mutations=RemoteCommand.objects.filter(run_id=OuterRef('pk')).filter(
        Q(payload__kind='patch_file',status__in=['delivered','done'])
        | (Q(result__changes__isnull=False) & ~Q(result__changes=[]) & ~Q(result__changes=None))
        | Q(result__stdout__regex=r'"changes"\s*:\s*\[\s*\{')
        | Q(status__in=['delivered','done'],payload__kind='run',
            payload__argv__contains=OuterRef('result__display_policy_snapshot__repair_argv')))
    return queryset.annotate(processing_mutation=Exists(mutations))


def preload_processing(defects):
    if not defects:return
    prefetch_related_objects(defects,processing_prefetch())
    for defect in defects:
        runs=defect._latest_agent_runs
        if runs:command_rows(runs[0])
        defect._agent_processing=processing(runs[0] if runs else None)


def command_rows(run):
    rows=getattr(run,'_processing_commands',None)
    if rows is not None and rows and hasattr(rows[0],'processing_payload'):
        rows=[SimpleNamespace(id=row.id,created_at=row.created_at,status=row.status,
            payload=row.processing_payload,result=row.processing_result) for row in rows]
        run._processing_commands=rows
    return rows


def agent_processing(defect):
    if not hasattr(defect,'_agent_processing'):
        if hasattr(defect,'_latest_agent_runs'):
            runs=defect._latest_agent_runs
            if runs:command_rows(runs[0])
            defect._agent_processing=processing(runs[0] if runs else None)
        else:preload_processing([defect])
    return defect._agent_processing


@transaction.atomic
def reconcile(run, apply=False):
    """Conservative opt-in reconciliation; dry runs never change run/history/notifications."""
    from .remote_models import RemoteWorkstation
    station_id=RemoteAgentRun.objects.values_list('workstation_id',flat=True).get(pk=run.pk)
    RemoteWorkstation.objects.select_for_update(of=('self',)).get(pk=station_id)
    run=RemoteAgentRun.objects.select_for_update(of=('self',)).select_related('owner').get(pk=run.pk)
    defect=Defect.objects.select_for_update().get(pk=run.defect_id)
    response={'run_id':str(run.id),'defect_id':str(defect.id),'status':defect.status,'eligible':False,'applied':False}
    reason=''
    if run.status in {'queued','running'}:reason='run_active'
    elif run.result.get('lifecycle_finalized'):reason='already_finalized'
    elif not latest_run(run):reason='newer_run'
    elif defect.archived_at or defect.status=='closed':reason='closed_or_archived'
    elif defect.status not in {'open','in_progress'}:reason='human_workflow_state'
    elif run.completed_at is None:reason='missing_completion_time'
    elif defect.updated_at>run.completed_at:reason='updated_after_run'
    elif defect.events.filter(created_at__gte=run.created_at).exclude(note__startswith='Agent ').exists():reason='human_or_other_workflow_event'
    elif defect.status=='in_progress' and not defect.events.filter(
        status='in_progress',note__startswith='Agent ',created_at__gte=run.created_at).exists():reason='not_agent_owned'
    elif run.result.get('defect_state_version') not in {None,defect.edit_version}:reason='version_changed'
    if reason:return {**response,'reason':reason}
    state=terminal_state(run)
    response.update(eligible=True,next_status='pending_tech' if state in {'repaired','verified'} else 'needs_tech',reason='safe_latest_terminal')
    if apply:
        run.result={**run.result,'defect_state_version':defect.edit_version}
        run.save(update_fields=['result'])
        handoff(run)
        run.refresh_from_db()
        response['applied']=run.result.get('lifecycle_finalized') is True
    return response
