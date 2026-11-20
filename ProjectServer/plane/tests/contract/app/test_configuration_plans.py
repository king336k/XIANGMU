"""Human approval is device/snapshot scoped, not an arbitrary model write grant."""
import copy
import json
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from plane.quality.models import Defect
from plane.quality.remote_diagnostics import identity_key
from plane.quality.remote_models import RemoteAgentRun, RemoteCommand, RemoteWorkstation
from plane.tests.contract.app.test_remote_diagnostics import BASE, heartbeat

pytest_plugins = ['plane.tests.contract.app.test_remote_diagnostics']
pytestmark = [pytest.mark.contract, pytest.mark.django_db]
URL = BASE + 'configuration-plans/'


@pytest.fixture
def candidate(remote):
    client, edge, device, project = remote
    actor = {'username': 'collector', 'hostname': 'pc', 'boot_id': 'boot', 'capabilities': {
        'diagnostics': {'protocol': 'daq-configuration-v1', 'ready': True,
                        'approval_protocol': 'robot-config-repair-approval-v1'},
        'robot': {'connected': True, 'host': '10.2.0.1', 'username': 'robot', 'target_revision': 'a' * 64}}}
    assert heartbeat(edge, identity=actor).status_code == 200
    station = RemoteWorkstation.objects.get(pk=device)
    defect = Defect.objects.create(project=project, title='configuration fixture')
    from plane.quality.remote_models import RemoteFeedbackBinding
    RemoteFeedbackBinding.objects.create(workstation=station, defect=defect, created_by=station.agent.owner)
    run = RemoteAgentRun.objects.create(workstation=station, defect=defect, owner=station.agent.owner,
        status='completed', mode='repair', identity_key=identity_key(station),
        expires_at=timezone.now() + timedelta(minutes=5), completed_at=timezone.now())
    configuration = {'state': 'fail', 'robot': 'custom', 'repair_allowed': False,
        'repair_authority': 'release_candidate', 'blocked_reason': 'baseline_not_approved_for_device',
        'target_revision': 'a' * 64, 'snapshot_sha256': 'b' * 64,
        'baseline': {'state': 'available', 'manifest_sha256': 'c' * 64},
        'findings': [{'code': 'joint_limit_violation', 'field': 'initial_joint_states.arm[0]', 'value': 5.3}],
        'suggested_changes': [{'key': 'initial_joint_states.arm[0]', 'before': 5.3, 'after': .3}],
        'evaluated_source': 'effective',
        'files': [{'role': 'effective', 'path': '/fixed/state/custom/robot_description.yaml', 'present': True}]}
    receipt = {'observed_at': timezone.now().isoformat(), 'configuration': configuration}
    command = RemoteCommand.objects.create(workstation=station, run=run, status='done',
        payload={'kind': 'run', 'argv': ['daq-local-diagnostics-v1', 'inspect']},
        result={'ok': True, 'exit_code': 0, 'stdout': json.dumps(receipt)}, expires_at=run.expires_at)
    return client, edge, station, defect, run, command, receipt


def proposal(candidate):
    client, _, _, defect, _, _, _ = candidate
    response = client.get(URL, {'defect_id': str(defect.id)})
    assert response.status_code == 200, response.content
    return response.data['proposal']


def confirm(candidate, data=None):
    client, _, _, _, run, _, _ = candidate
    plan = proposal(candidate)
    return client.post(URL, data or {'source_run_id': str(run.id), 'plan_digest': plan['plan_digest'],
                                    'confirmation': 'confirmed'}, format='json')


def test_proposal_is_actual_receipt_and_confirmation_is_single_intent(candidate, django_capture_on_commit_callbacks):
    client, _, station, defect, source, _, _ = candidate
    plan = proposal(candidate)
    assert plan['changes'] == [{'key': 'initial_joint_states.arm[0]', 'before': 5.3, 'after': .3}]
    assert plan['path'] == '/fixed/state/custom/robot_description.yaml' and plan['can_approve'] is True
    with patch('plane.quality.remote_tasks.remote_repair.apply_async') as dispatch:
        with django_capture_on_commit_callbacks(execute=True):
            first = confirm(candidate)
        assert first.status_code == 201, first.content
        with django_capture_on_commit_callbacks(execute=True):
            second = confirm(candidate)
        assert second.status_code == 200 and second.data['id'] == first.data['id']
        assert dispatch.call_count == 1
    run = RemoteAgentRun.objects.get(pk=first.data['id'])
    approval = run.result['configuration_approval']
    assert approval['changes'] == plan['changes'] and approval['snapshot_sha256'] == 'b' * 64
    assert approval['actor'] == (station.agent.owner.username or 'user:' + str(station.agent.owner_id))
    assert approval['source'] == 'operator_confirmation'
    assert run.mode == 'repair' and run.workstation_id == station.id and run.defect_id == defect.id


def test_unknown_values_and_source_digest_are_never_accepted(candidate):
    _, _, _, _, run, _, _ = candidate
    plan = proposal(candidate)
    bad = confirm(candidate, {'source_run_id': str(run.id), 'plan_digest': plan['plan_digest'],
        'confirmation': 'confirmed', 'changes': [{'key': 'joint_limits', 'after': 100}]})
    assert bad.status_code == 400
    bad = confirm(candidate, {'source_run_id': str(run.id), 'plan_digest': 'd' * 64, 'confirmation': 'confirmed'})
    assert bad.status_code == 409
    assert RemoteAgentRun.objects.filter(status='queued').count() == 0


def test_confirmed_worker_uses_fixed_plan_without_model_or_arbitrary_command(candidate):
    from plane.quality.remote_tasks import remote_repair

    _, _, _, _, _, _, receipt = candidate
    accepted = confirm(candidate)
    assert accepted.status_code == 201
    after = copy.deepcopy(receipt)
    after.update(scope='configuration_validation', verified=True)
    after['configuration'].update(state='pass', findings=[])
    repaired = copy.deepcopy(after)
    repaired['repair'] = {'state': 'applied', 'actual_write': True, 'changes': [
        {'key': 'initial_joint_states.arm[0]', 'before': 5.3, 'after': .3,
         'path': '/fixed/state/override.yaml', 'line': 2}]}
    repaired['configuration']['repair'] = repaired['repair']
    outputs = [receipt, repaired, after]

    def execute(run_id, action, approval=None):
        run = RemoteAgentRun.objects.get(pk=run_id)
        if action == 'repair':
            assert approval['changes'][0]['after'] == .3
        body = outputs.pop(0)
        RemoteCommand.objects.create(workstation=run.workstation, run=run, status='done',
            payload={'kind': 'run', 'argv': (
                ['daq-local-diagnostics-v1', action] + (['b' * 64] if action == 'repair' else []))},
            result={'ok': True, 'exit_code': 0, 'stdout': json.dumps(body)}, expires_at=run.expires_at)
        return body

    with patch('plane.quality.remote_tasks.provider_config',
               side_effect=AssertionError('confirmed plan is not replanned')):
        with patch('plane.quality.configuration_plans.execute_step', side_effect=execute) as step:
            remote_repair.run(accepted.data['id'])
    assert [call.args[1] for call in step.call_args_list] == ['inspect', 'repair', 'verify']
    run = RemoteAgentRun.objects.get(pk=accepted.data['id'])
    assert run.status == 'completed' and run.result['configuration_repaired'] is True
    assert run.result['business_verified'] is False and run.comment_id
    assert confirm(candidate).data['id'] == str(run.id)


def test_changed_snapshot_stops_before_repair_and_writes_failure_reply(candidate):
    from plane.quality.remote_tasks import remote_repair

    _, _, _, _, _, _, receipt = candidate
    accepted = confirm(candidate)
    changed = copy.deepcopy(receipt)
    changed['configuration']['snapshot_sha256'] = 'd' * 64
    with patch('plane.quality.configuration_plans.execute_step', return_value=changed) as step:
        remote_repair.run(accepted.data['id'])
    assert step.call_count == 1
    run = RemoteAgentRun.objects.get(pk=accepted.data['id'])
    assert run.status == 'failed' and run.comment_id
    assert '变化' in run.error and run.result['configuration_repaired'] is False


def test_worker_exception_is_reported_without_replaying_or_leaking_details(candidate):
    from plane.quality.remote_tasks import remote_repair

    accepted = confirm(candidate)
    with patch('plane.quality.configuration_plans.execute_step',
               side_effect=RuntimeError('private-runtime-detail')) as step:
        remote_repair.run(accepted.data['id'])
    assert step.call_count == 1
    run = RemoteAgentRun.objects.get(pk=accepted.data['id'])
    assert run.status == 'failed' and run.comment_id
    assert 'private-runtime-detail' not in run.error + run.comment.content


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(not __import__('pathlib').Path('/daq/scripts/remote-diagnostics/connector.py').exists(),
                    reason='isolated /daq source mount required for the actual edge adapter')
def test_real_connector_local_http_adapter_and_controller_finish_one_plan(candidate, tmp_path, monkeypatch):
    """Real edge transport and real file changes, with isolated robot state only."""
    import importlib.util
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from pathlib import Path
    import sys
    import threading
    import time

    daq = Path('/daq')
    if not (daq / 'scripts/remote-diagnostics/connector.py').exists():
        pytest.fail('this integration requires the /daq source mount')
    sys.path.insert(0, str(daq / 'src/engram_Teleop_DAQ_web/backend'))
    fixture_path = daq / 'src/engram_Teleop_DAQ_web/backend/tests/test_configuration_diagnostics.py'
    spec = importlib.util.spec_from_file_location('real_configuration_fixture', fixture_path)
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    service, source_file, state = fixture.fixture(tmp_path)
    service.approval_file.unlink()
    original = source_file.read_bytes()
    client, edge, station, _, run, source_command, _ = candidate
    config = service.inspect('custom')
    assert config['repair_allowed'] is False
    source_command.result['stdout'] = json.dumps({'configuration': {
        **config, 'target_revision': service.target_revision}, 'observed_at': timezone.now().isoformat()})
    source_command.save(update_fields=['result'])
    token_file = tmp_path / 'local-token'
    token_file.write_text('synthetic-local-adapter-credential')
    token_file.chmod(0o600)
    requests = []

    class LocalAdapter(BaseHTTPRequestHandler):
        def do_POST(self):
            assert self.headers.get('Authorization') == 'Bearer synthetic-local-adapter-credential'
            value = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            from app.launcher.robot.configuration_diagnostics import validate_diagnostic_payload
            validate_diagnostic_payload(value)
            requests.append(value['action'])
            repair = None
            if value['action'] == 'repair':
                repair = service.repair_with_approval('custom', 'joint limit violation', lambda: True,
                    value['expected_sha256'], value['configuration_approval'])
            observed = service.inspect('custom')
            observed['target_revision'] = service.target_revision
            if repair:
                observed['repair'] = repair
            response = {'scope': 'configuration_validation', 'configuration': observed,
                        'verified': observed['state'] == 'pass'}
            if repair:
                response.update(repair=repair, changes=repair.get('changes', []))
            raw = json.dumps(response).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 11452), LocalAdapter)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    sys.path.insert(0, str(daq / 'scripts/remote-diagnostics'))
    import connector
    import file_browser
    # Status is a separate API; keep this local fixture's peer fixed.
    monkeypatch.setattr(file_browser, 'robot_status', lambda _local: {'connected': True, 'target_revision': 'a' * 64})
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    policy = connector.Policy({'approved_root': str(workspace), 'allowed_commands': [],
        'daq_local_api': {'url': 'http://127.0.0.1:11452/api/launcher/remote-robot-files',
                          'token_file': str(token_file)}})
    engine = connector.Engine(policy, '127.0.0.1')
    with patch('plane.quality.remote_tasks.remote_repair.apply_async'):
        accepted = confirm(candidate)
    assert accepted.status_code == 201
    from plane.quality.remote_tasks import remote_repair
    from django.db import close_old_connections
    failures = []

    def worker():
        try:
            remote_repair.run(accepted.data['id'])
        except Exception as error:
            failures.append(type(error).__name__)
        finally:
            close_old_connections()

    actor = {'username': station.username, 'hostname': station.hostname, 'boot_id': station.boot_id,
             'capabilities': station.capabilities}
    thread = threading.Thread(target=worker)
    thread.start()
    try:
        deadline = time.monotonic() + 25
        while thread.is_alive() and time.monotonic() < deadline:
            engine.pump()
            outputs, results = engine.outputs[:100], engine.results[:100]
            response = heartbeat(edge, identity=actor, outputs=outputs, results=results)
            assert response.status_code == 200
            engine.acknowledge(len(outputs), len(results))
            for command in response.data['commands']:
                engine.accept(command)
            time.sleep(.03)
        thread.join(timeout=1)
        assert not thread.is_alive() and not failures
        result = RemoteAgentRun.objects.get(pk=accepted.data['id'])
        details = [{'argv': row.payload.get('argv'), 'ok': row.result.get('ok'),
                    'stderr': row.result.get('stderr'), 'stdout': row.result.get('stdout')}
                   for row in result.remotecommand_set.all()]
        assert result.status == 'completed' and result.result['configuration_repaired'] is True, details
        assert result.comment_id and result.result['business_verified'] is False
        assert requests == ['inspect', 'repair', 'verify']
        assert service.inspect('custom')['state'] == 'pass'
        assert source_file.read_bytes() == original
        assert not service.approval_file.exists()
        assert [row['after'] for row in result.result['repair_locations']] == [.3]
    finally:
        engine.close()
        server.shutdown()
        server.server_close()


def test_new_boot_and_revoked_membership_cannot_approve(candidate):
    client, edge, station, defect, run, _, _ = candidate
    plan = proposal(candidate)
    heartbeat(edge, identity={'username': 'collector', 'hostname': 'pc', 'boot_id': 'new-boot'})
    rejected = client.post(URL, {'source_run_id': str(run.id), 'plan_digest': plan['plan_digest'],
                                'confirmation': 'confirmed'}, format='json')
    assert rejected.status_code == 409


def test_confirmation_rechecks_owner_permission(candidate):
    from plane.db.models import ProjectMember

    client, _, station, _, run, _, _ = candidate
    plan = proposal(candidate)
    ProjectMember.objects.filter(project_id=station.agent.project_id,
                                 member_id=station.agent.owner_id).update(is_active=False)
    rejected = client.post(URL, {'source_run_id': str(run.id), 'plan_digest': plan['plan_digest'],
                                'confirmation': 'confirmed'}, format='json')
    assert rejected.status_code == 403
    assert not RemoteAgentRun.objects.filter(status='queued').exists()


def test_incomplete_receipt_and_newer_diagnosis_cannot_authorize(candidate):
    _, _, station, defect, run, command, _ = candidate
    command.result['truncated'] = True
    command.save(update_fields=['result'])
    assert proposal(candidate) is None
    command.result.pop('truncated')
    command.save(update_fields=['result'])
    plan = proposal(candidate)
    RemoteAgentRun.objects.create(workstation=station, defect=defect, owner=run.owner,
        status='completed', identity_key=run.identity_key, expires_at=run.expires_at)
    client = candidate[0]
    rejected = client.post(URL, {'source_run_id': str(run.id), 'plan_digest': plan['plan_digest'],
                                'confirmation': 'confirmed'}, format='json')
    assert rejected.status_code == 409


def test_confirmation_waits_for_human_terminal_then_reuses_same_queue(candidate):
    from plane.quality.remote_models import RemoteTerminal
    from plane.quality.remote_tasks import remote_repair

    client, _, station, _, _, _, _ = candidate
    row = RemoteTerminal.objects.create(workstation=station, owner=station.agent.owner,
        expires_at=timezone.now()+timedelta(minutes=2), last_read_at=timezone.now())
    accepted = confirm(candidate)
    assert accepted.status_code == 201 and accepted.data['queue']['reason'] == 'terminal_open'
    with patch('plane.quality.remote_tasks.remote_repair.retry', side_effect=RuntimeError('queued')):
        with pytest.raises(RuntimeError, match='queued'):
            remote_repair.run(accepted.data['id'])
    assert RemoteAgentRun.objects.get(pk=accepted.data['id']).status == 'queued'
    assert RemoteTerminal.objects.get(pk=row.pk).status == 'open'


def test_old_executor_explains_upgrade_without_granting_mutation(candidate):
    _, _, station, _, _, _, _ = candidate
    station.capabilities['diagnostics'].pop('approval_protocol')
    station.save(update_fields=['capabilities'])
    plan = proposal(candidate)
    assert plan['can_approve'] is False and 'DAQ' in plan['blocked_reason']
    assert confirm(candidate).status_code == 409


def test_expired_snapshot_and_completed_defect_are_rejected(candidate):
    _, _, _, defect, _, command, _ = candidate
    RemoteCommand.objects.filter(pk=command.pk).update(created_at=timezone.now()-timedelta(minutes=16))
    plan = proposal(candidate)
    assert plan['can_approve'] is False
    assert confirm(candidate).status_code == 409
    defect.status = 'closed'
    defect.save(update_fields=['status'])
    assert proposal(candidate)['can_approve'] is False


@pytest.mark.parametrize('changes', [[], [{'key': 'joint_limits.arm', 'before': 1, 'after': 2}],
                                     [{'key': 'initial_joint_states.arm[0]', 'before': 5.3, 'after': True}]])
def test_unsupported_or_ambiguous_repairs_have_no_proposal(candidate, changes):
    _, _, _, _, _, command, receipt = candidate
    receipt = copy.deepcopy(receipt)
    receipt['configuration']['suggested_changes'] = changes
    command.result['stdout'] = json.dumps(receipt)
    command.save(update_fields=['result'])
    assert proposal(candidate) is None
