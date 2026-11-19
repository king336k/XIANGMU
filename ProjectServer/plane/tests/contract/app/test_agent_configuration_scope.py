"""Configuration receipts never substitute for original business acceptance."""
import json
from datetime import timedelta

import pytest
from django.utils import timezone

from plane.quality.agent_lifecycle import readonly_verified, terminal_state, preload_processing
from plane.quality.models import Defect
from plane.quality.remote_diagnostics import identity_key
from plane.quality.remote_models import RemoteAgentRun, RemoteCommand, RemoteWorkstation
from plane.quality.remote_tasks import finish
from plane.tests.contract.app.test_remote_diagnostics import heartbeat

pytest_plugins = ['plane.tests.contract.app.test_remote_diagnostics']
pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def configuration_job(remote):
    _, edge, device, project = remote
    heartbeat(edge)
    station = RemoteWorkstation.objects.get(pk=device)
    station.capabilities['agent_context'] = {'verification_scope': 'configuration_validation'}
    station.save()
    defect = Defect.objects.create(project=project, title='reset failure')
    run = RemoteAgentRun.objects.create(workstation=station, defect=defect, owner=station.agent.owner,
        status='running', started_at=timezone.now(), identity_key=identity_key(station),
        result={'defect_state_version': defect.edit_version,
                'display_policy_snapshot': {'verification_scope': 'configuration_validation'}},
        expires_at=timezone.now() + timedelta(minutes=5))
    return defect, run


def command(run, action, *, state='applied', success=True):
    changes = [{'path': '/state/robot_config_overrides/robot/custom/initial_joint_states.yaml',
                'key': 'initial_joint_states.arm[0]', 'line': 3, 'before': 3.3, 'after': 0.3,
                'backup': '/state/initial_joint_states.yaml.backup', 'target_kind': 'collector'}]
    body = {'scope': 'configuration_validation', 'verified': success,
            'configuration': {'state': 'pass' if success else 'fail'}}
    argv = ['daq-local-diagnostics-v1', action]
    if action == 'repair':
        argv.append('a' * 64)
        body['configuration']['repair'] = {'state': state, 'changes': changes}
        body['changes'] = changes
    return RemoteCommand.objects.create(workstation=run.workstation, run=run, status='done',
        expires_at=run.expires_at, payload={'kind': 'run', 'argv': argv},
        result={'ok': success, 'exit_code': 0 if success else 1, 'stdout': json.dumps(body)})


@pytest.mark.parametrize('scope', ['configuration_validation', 'read_only_connectivity', 'readonly_connectivity'])
@pytest.mark.parametrize('claimed_repaired', [True, False])
def test_limited_scope_never_becomes_business_terminal_or_pending_tech(configuration_job, scope, claimed_repaired):
    defect, run = configuration_job
    result = {'summary': 'limited check', 'verification_scope': scope,
              'repaired': claimed_repaired, 'verification_passed': True, 'outcome': 'verified'}
    run.status = 'completed'; run.result = result
    assert readonly_verified(run) is False
    assert terminal_state(run) == 'unresolved'
    run.status = 'running'; run.result = {'defect_state_version': defect.edit_version}
    run.save()
    finish(run.id, result)
    run.refresh_from_db(); defect.refresh_from_db()
    assert defect.status == 'needs_tech'
    assert run.result['repaired'] is False and run.result['outcome'] == 'unresolved'
    assert 'Agent 远程处理：验证通过' not in run.comment.content
    assert 'Agent 远程处理：已修复' not in run.comment.content
    preload_processing([defect])
    assert defect._agent_processing['state'] == 'unresolved'


def test_real_configuration_repair_requires_post_write_verify_and_keeps_locations(configuration_job):
    defect, run = configuration_job
    command(run, 'repair'); command(run, 'verify')
    finish(run.id, {'summary': 'configuration recovery', 'configuration_repaired': False,
                    'configuration_verified': False, 'repaired': True, 'verification_passed': True,
                    'outcome': 'repaired', 'verification_scope': 'business'})
    run.refresh_from_db(); defect.refresh_from_db()
    assert run.result['configuration_repaired'] is True
    assert run.result['configuration_verified'] is True
    assert run.result['repaired'] is False and run.result['outcome'] == 'unresolved'
    assert defect.status == 'needs_tech'
    assert run.comment.content.startswith('Agent 远程处理：配置已修复，待业务验证')
    assert 'initial_joint_states.arm[0]' in run.comment.content
    assert '/state/robot_config_overrides/robot/custom/initial_joint_states.yaml:3' in run.comment.content


@pytest.mark.parametrize('scenario', ['no_receipts', 'verify_only', 'failed_latest_verify', 'later_write', 'written_unverified'])
def test_model_claims_cannot_forge_verified_configuration_repair(configuration_job, scenario):
    defect, run = configuration_job
    if scenario != 'no_receipts':
        if scenario != 'verify_only':
            command(run, 'repair', state='written_runtime_unverified' if scenario == 'written_unverified' else 'applied',
                    success=scenario != 'written_unverified')
        command(run, 'verify')
        if scenario == 'failed_latest_verify': command(run, 'verify', success=False)
        if scenario == 'later_write': command(run, 'repair')
    finish(run.id, {'summary': 'model claim', 'configuration_repaired': True, 'configuration_verified': True,
                    'repair_locations': [{'path': '/forged/location', 'line': 99}],
                    'repaired': True, 'verification_passed': True, 'outcome': 'verified'})
    run.refresh_from_db(); defect.refresh_from_db()
    assert run.result['configuration_repaired'] is False
    assert defect.status == 'needs_tech'
    assert '配置已修复' not in run.comment.content
    assert '/forged/location' not in run.comment.content
    if scenario in {'failed_latest_verify', 'later_write', 'no_receipts'}:
        assert run.result['configuration_verified'] is False
    if scenario == 'written_unverified':
        assert run.result['repair_locations'][0]['key'] == 'initial_joint_states.arm[0]'


def test_empty_mutation_receipt_cannot_establish_configuration_repaired(configuration_job):
    _, run = configuration_job
    row = command(run, 'repair')
    receipt = json.loads(row.result['stdout'])
    receipt['changes'] = []
    receipt['configuration']['repair']['changes'] = [{}]
    row.result['stdout'] = json.dumps(receipt); row.save()
    command(run, 'verify')
    finish(run.id, {'summary': 'no actual change', 'configuration_repaired': True,
                    'repaired': True, 'verification_passed': True})
    run.refresh_from_db()
    assert run.result['configuration_repaired'] is False
    assert run.result['repair_locations'] == []


def test_limited_verification_passed_flag_requires_actual_check_receipt(configuration_job):
    _, run = configuration_job
    finish(run.id, {'summary': 'invented check', 'verification_passed': True,
                    'configuration_verified': True, 'repaired': False})
    run.refresh_from_db()
    assert run.result['verification_passed'] is False


def test_later_failed_configuration_inspection_invalidates_old_verification(configuration_job):
    _, run = configuration_job
    command(run, 'repair'); command(run, 'verify'); command(run, 'inspect', success=False)
    finish(run.id, {'summary': 'stale successful verify', 'configuration_repaired': True,
                    'verification_passed': True, 'repaired': True})
    run.refresh_from_db()
    assert run.result['configuration_repaired'] is False
    assert run.result['configuration_verified'] is False
