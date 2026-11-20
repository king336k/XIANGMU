"""Receipt-derived, single-snapshot operator confirmation for supported DAQ repairs."""
from datetime import timedelta
import hashlib
import json
import math
import re
import time

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from plane.app.views.base import BaseAPIView
from .models import Defect, DefectEvent
from .remote_access import browser_boundary, identity_key, online, permitted
from .remote_bindings import daq_binding, feedback_for
from .remote_run_state import run_queue
from .remote_models import RemoteAgentRun, RemoteWorkstation
from .errors import Conflict

PROTOCOL = 'robot-config-repair-approval-v1'
FIELD = re.compile(r'^initial_joint_states\.[A-Za-z0-9_-]{1,80}(?:\[[0-9]{1,3}\])?$')
SHA256 = re.compile(r'^[a-f0-9]{64}$')
LIFETIME = timedelta(minutes=15)


def finite_value(value):
    try:
        if isinstance(value, list):
            return 0 < len(value) <= 128 and all(type(item) in {int, float} and math.isfinite(item) for item in value)
        return type(value) in {int, float} and math.isfinite(value)
    except (OverflowError, ValueError):
        return False


def candidate(command):
    """Only a matching, stored fixed-tool receipt can propose an operation."""
    reads = [['daq-local-diagnostics-v1', 'inspect'], ['daq-local-diagnostics-v1', 'verify']]
    if command.payload.get('argv') not in reads:
        return None
    try:
        if command.result.get('timed_out') or command.result.get('truncated') or command.result.get('error'):
            return None
        result = json.loads(command.result.get('stdout', ''), parse_constant=lambda value: None)
        configuration = result['configuration']
        changes = configuration.get('suggested_changes')
        baseline = configuration['baseline']
        if (configuration.get('state') != 'fail' or baseline.get('state') != 'available'
                or configuration.get('blocked_reason') not in {None, 'baseline_not_approved_for_device'}
                or not isinstance(changes, list) or not 0 < len(changes) <= 32
                or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', configuration.get('robot', ''))
                or not all(isinstance(value, str) and SHA256.fullmatch(value) for value in (
                    configuration.get('snapshot_sha256'), configuration.get('target_revision'),
                    baseline.get('manifest_sha256')))):
            return None
        fields = []
        for change in changes:
            if (not isinstance(change, dict) or set(change) != {'key', 'before', 'after'}
                    or not isinstance(change['key'], str) or not FIELD.fullmatch(change['key'])
                    or not finite_value(change['after'])):
                return None
            fields.append(change['key'])
        if len(set(fields)) != len(fields):
            return None
        source = configuration.get('evaluated_source')
        files = [row for row in configuration.get('files', []) if row.get('role') == source
                 and row.get('present') is True and isinstance(row.get('path'), str) and row['path'].startswith('/')]
        if len(files) != 1:
            return None
        return {'kind': 'configuration', 'schema': PROTOCOL, 'robot': configuration['robot'],
                'snapshot_sha256': configuration['snapshot_sha256'],
                'target_revision': configuration['target_revision'],
                'baseline_manifest_sha256': baseline['manifest_sha256'],
                'path': files[0]['path'], 'changes': changes,
                'configuration_target': command.payload.get('configuration_target'),
                'observed_at': result.get('observed_at') or command.created_at.isoformat()}
    except (ValueError, TypeError, KeyError, AttributeError):
        return None


def plan_for(run, station, defect):
    command = run.remotecommand_set.filter(status='done', payload__kind='run').order_by('-created_at', '-id')
    command = next((row for row in command[:30] if row.payload.get('argv') in [
        ['daq-local-diagnostics-v1', 'inspect'], ['daq-local-diagnostics-v1', 'verify']]), None)
    if command is None:
        return None
    proposal = candidate(command)
    if proposal is None:
        return None
    expires = command.created_at + LIFETIME
    binding, _ = daq_binding(defect)
    reason = ''
    if defect.status == 'closed' or defect.archived_at:
        reason = '缺陷已关闭或归档。'
    elif run.identity_key != identity_key(station):
        reason = '设备连接已变化，请重新诊断。'
    elif expires <= timezone.now():
        reason = '现场配置已过期，请重新诊断。'
    elif not online(station):
        reason = '采集电脑未连接。'
    elif station.capabilities.get('diagnostics', {}).get('approval_protocol') != PROTOCOL:
        reason = '请先更新 DAQ，再重新诊断。'
    elif binding.get('execution_scope') == 'verify_only':
        reason = '这条历史反馈仅支持重新验证。'
    elif run.status in {'queued', 'running'}:
        reason = '请等待当前诊断结束。'
    elif run.result.get('configuration_approval_run_id'):
        reason = '计划已提交，请查看处理记录。'
    elif (RemoteAgentRun.objects.filter(workstation=station, defect=defect, created_at__gt=run.created_at)
          .exclude(pk=run.result.get('configuration_approval_run_id')).exists()):
        reason = '已有更新的诊断，请读取最新计划。'
    material = {'source_run_id': str(run.pk), 'command_id': str(command.pk), 'station_id': str(station.pk),
                'identity_key': run.identity_key, **proposal}
    canonical = json.dumps(material, sort_keys=True, separators=(',', ':'), allow_nan=False)
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    return {**proposal, 'source_run_id': str(run.pk), 'plan_digest': digest,
            'device': {'username': station.username,
                       'ip_address': station.capabilities.get('network', {}).get('ip_address')},
            'expires_at': expires.isoformat(), 'can_approve': not reason, 'blocked_reason': reason}


class Confirmation(serializers.Serializer):
    source_run_id = serializers.UUIDField()
    plan_digest = serializers.RegexField(r'^[a-f0-9]{64}$')
    confirmation = serializers.ChoiceField(choices=['confirmed'])

    def to_internal_value(self, data):
        if not isinstance(data, dict) or set(data) != {'source_run_id', 'plan_digest', 'confirmation'}:
            raise serializers.ValidationError({'confirmation': ['只能确认平台生成的修复计划。']})
        return super().to_internal_value(data)


class ConfigurationPlans(BaseAPIView):
    def perform_authentication(self, request):
        # Confirmation checks current device/project membership below; do not
        # reproject administrator grants and resurrect a revoked membership.
        request.user

    def get(self, request):
        defect = get_object_or_404(Defect, pk=request.query_params.get('defect_id'))
        run = (RemoteAgentRun.objects.filter(defect=defect)
               .select_related('workstation__agent__project__workspace').order_by('-created_at', '-id').first())
        if run is None:
            from .permissions import writable_member
            if not writable_member(defect.project_id, request.user.id, defect.project.workspace.slug):
                raise PermissionDenied()
            return Response({'proposal': None})
        station = run.workstation
        if not permitted(request.user, station) or not feedback_for(station, defect.id).exists():
            raise PermissionDenied()
        source = run.result.get('configuration_approval_source_run_id')
        if source:
            run = get_object_or_404(RemoteAgentRun, pk=source, defect=defect, workstation=station)
        return Response({'proposal': plan_for(run, station, defect)})

    @transaction.atomic
    def post(self, request):
        browser_boundary(request)
        serializer = Confirmation(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        source = get_object_or_404(RemoteAgentRun, pk=data['source_run_id'])
        station = (RemoteWorkstation.objects.select_for_update(of=('self',))
                   .select_related('agent__project__workspace').get(pk=source.workstation_id))
        if not permitted(request.user, station) or not feedback_for(station, source.defect_id).exists():
            raise PermissionDenied()
        source = RemoteAgentRun.objects.select_for_update().get(pk=source.pk)
        defect = Defect.objects.select_for_update().get(pk=source.defect_id)
        existing = source.result.get('configuration_approval_run_id')
        if existing:
            run = get_object_or_404(RemoteAgentRun, pk=existing, workstation=station, defect=defect)
            if run.result.get('configuration_plan_digest') != data['plan_digest'] or run.owner_id != request.user.id:
                raise Conflict('计划已由其他操作确认，请查看处理记录。')
            return Response({'id': str(run.id), 'mode': run.mode, 'status': run.status, 'queue': run_queue(run)})
        plan = plan_for(source, station, defect)
        if plan is None or plan['plan_digest'] != data['plan_digest']:
            raise Conflict('修复计划已变化，请重新读取。')
        if not plan['can_approve']:
            raise Conflict(plan['blocked_reason'])
        if station.remoteagentrun_set.filter(status__in=['queued', 'running'], expires_at__gt=timezone.now()).exists():
            raise Conflict('该采集电脑正在处理其他任务。')
        approval = {key: plan[key] for key in ['schema', 'robot', 'target_revision', 'snapshot_sha256',
                    'baseline_manifest_sha256', 'changes', 'expires_at']}
        approval.update(authority='explicit_repair_plan', allowed_fields=[row['key'] for row in plan['changes']],
                        actor=request.user.username or 'user:' + str(request.user.pk), source='operator_confirmation',
                        evidence_ref=f'configuration-plan:{source.pk}')
        if plan['configuration_target']:
            approval['evidence_freshness'] = 'historical_runtime'
        run = RemoteAgentRun.objects.create(workstation=station, defect=defect, owner=request.user, mode='repair',
            status='queued', problem='按用户确认的限定配置计划执行修复并复查；不执行机器人复位或运动。',
            identity_key=identity_key(station), expires_at=timezone.now()+timedelta(minutes=15),
            result={'defect_state_version': defect.edit_version, 'configuration_approval': approval,
                    'configuration_plan_digest': plan['plan_digest'],
                    'configuration_approval_source_run_id': str(source.pk),
                    'configuration_target': plan['configuration_target']})
        source.result = {**source.result, 'configuration_approval_run_id': str(run.pk)}
        source.save(update_fields=['result'])
        DefectEvent.objects.create(project=defect.project, defect=defect, created_by=request.user,
            previous_status=defect.status, status=defect.status, note='已确认配置修复计划，将仅修改所列字段并复查。')
        from .remote_tasks import remote_repair
        transaction.on_commit(lambda: remote_repair.apply_async(args=[str(run.pk)], queue='field-repairs'))
        return Response({'id': str(run.pk), 'mode': run.mode, 'status': run.status,
                         'queue': run_queue(run)}, status=201)


def execute_step(run_id, action, approval=None):
    """Use the existing serialized, expiring field-command transport."""
    from .remote_commands import command

    with transaction.atomic():
        station_id = RemoteAgentRun.objects.values_list('workstation_id', flat=True).get(pk=run_id)
        station = (RemoteWorkstation.objects.select_for_update(of=('self',))
                   .select_related('agent__project__workspace').get(pk=station_id))
        run = RemoteAgentRun.objects.select_for_update().select_related('owner').get(pk=run_id)
        if (run.status != 'running' or run.mode != 'repair' or run.expires_at <= timezone.now()
                or not permitted(run.owner, station) or run.identity_key != identity_key(station)
                or not online(station)):
            raise ValueError('修复任务的设备或授权已变化。')
        if station.commands.filter(status__in=['pending', 'delivered'], expires_at__gt=timezone.now(),
                                   payload__kind__in=['run', 'file_browser', 'patch_file', 'read_file']).exists():
            raise ValueError('上一个现场操作尚未完成，未重复执行。')
        allowed = run.result.get('configuration_approval', {})
        if action not in {'inspect', 'repair', 'verify'}:
            raise ValueError('不支持的配置操作。')
        payload = {'kind': 'run', 'argv': ['daq-local-diagnostics-v1', action], 'timeout': 30, 'cwd': '.'}
        target = run.result.get('configuration_target')
        if target:
            payload['configuration_target'] = target
        if action == 'repair':
            if approval != allowed:
                raise ValueError('修复计划与本轮确认不一致。')
            payload['argv'].append(allowed['snapshot_sha256'])
            payload['configuration_approval'] = allowed
            revision_key = 'expected_configuration_revision' if target else 'expected_target_revision'
            payload[revision_key] = allowed['target_revision']
        row = command(station, payload, run=run, lifetime=40)
    deadline = time.monotonic() + 38
    while time.monotonic() < deadline:
        row.refresh_from_db()
        run.refresh_from_db(fields=['status'])
        if run.status != 'running':
            raise ValueError('修复任务已中止，未继续操作。')
        if row.status == 'done':
            if row.result.get('timed_out') or row.result.get('truncated'):
                raise ValueError('现场结果不完整，不能继续修复。')
            try:
                value = json.loads(row.result.get('stdout', ''))
            except (ValueError, TypeError):
                raise ValueError('现场未返回可核验的配置结果。')
            if not isinstance(value, dict):
                raise ValueError('现场配置结果无效。')
            return value
        if row.status == 'expired':
            raise ValueError('现场命令已失效，未重复执行。')
        time.sleep(.15)
    raise ValueError('现场结果未到达，执行状态待核对，未重复提交。')


def execute_confirmed(run):
    from .remote_tasks import finish

    try:
        approval = run.result['configuration_approval']
        expiry = timezone.datetime.fromisoformat(approval['expires_at'])
        if expiry <= timezone.now():
            raise ValueError('确认计划已过期，请重新诊断。')
        observed = execute_step(run.pk, 'inspect')
        config = observed.get('configuration', {})
        if (config.get('snapshot_sha256') != approval['snapshot_sha256']
                or config.get('target_revision') != approval['target_revision']
                or config.get('baseline', {}).get('manifest_sha256') != approval['baseline_manifest_sha256']
                or config.get('suggested_changes') != approval['changes']):
            raise ValueError('现场配置或恢复候选已变化，请重新诊断并确认。')
        repaired = execute_step(run.pk, 'repair', approval=approval)
        repair = repaired.get('repair', repaired.get('configuration', {}).get('repair', {}))
        # Verify even after a blocked or failed write; never infer business recovery.
        verification = execute_step(run.pk, 'verify')
        verified = verification.get('configuration', {}).get('state') == 'pass' and verification.get('verified') is True
        applied = repair.get('state') == 'applied' and repair.get('actual_write') is True
        summary = '配置已修复，待业务验证。' if applied and verified else '配置未完成修复，复查结果见处理记录。'
        finish(run.pk, {'summary': summary,
            'root_cause': '当前有效配置校验失败，已按设备负责人确认的限定计划处理。',
            'actions': ['重新核验现场快照', '执行限定配置修复', '读取配置复查结果'],
            'verification': ['配置复查通过。' if verified else '配置复查未通过。'],
            'verification_scope': 'configuration_validation', 'business_verified': False,
            'repaired': False, 'verification_passed': verified,
            'solution': '未执行机器人复位或运动；业务恢复需按原操作单独验收。'})
    except Exception as error:
        message = str(error) if isinstance(error, ValueError) else '修复流程异常，未继续执行，请核对实际回执。'
        finish(run.pk, {'summary': message, 'repaired': False, 'business_verified': False,
                       'verification_scope': 'configuration_validation'}, 'failed', message)
