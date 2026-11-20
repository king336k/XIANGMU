import hashlib
import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from plane.quality.models import Defect
from plane.quality.remote_models import RemoteAgentRun, RemoteCommand, RemoteWorkstation
from plane.quality.remote_diagnostics import identity_key
from plane.tests.contract.app.test_remote_diagnostics import BASE, heartbeat

pytest_plugins=['plane.tests.contract.app.test_remote_diagnostics']
pytestmark=[pytest.mark.contract,pytest.mark.django_db]


@pytest.fixture
def target_run(remote):
    _,edge,device,project=remote
    heartbeat(edge)
    station=RemoteWorkstation.objects.get(pk=device)
    station.capabilities['agent_context']={'repair_allowed':True,
        'inspect_argv':['daq-local-diagnostics-v1','inspect'],
        'verify_argv':['daq-local-diagnostics-v1','verify'],
        'repair_argv':['daq-local-diagnostics-v1','repair']}
    station.save()
    token='rr_synthetic_configuration_target'
    defect=Defect.objects.create(project=project,title='reset failed')
    run=RemoteAgentRun.objects.create(workstation=station,defect=defect,owner=station.agent.owner,
        status='running',identity_key=identity_key(station),tool_credential_hash=hashlib.sha256(token.encode()).hexdigest(),
        result={'configuration_target':'profile-a'},expires_at=timezone.now()+timedelta(minutes=5))
    client=APIClient();client.credentials(HTTP_AUTHORIZATION='Bearer '+token)
    return client,run


def test_repair_binds_server_feedback_target_and_observed_configuration_revision(target_run):
    client,run=target_run
    RemoteCommand.objects.create(workstation=run.workstation,run=run,status='done',
        payload={'kind':'run','argv':['daq-local-diagnostics-v1','inspect'],'configuration_target':'profile-a'},
        result={'stdout':json.dumps({'configuration':{'target_revision':'b'*64,'snapshot_sha256':'a'*64}})},
        expires_at=run.expires_at)
    response=SimpleNamespace(status='done',result={'ok':True},refresh_from_db=lambda:None)
    with patch('plane.quality.remote_tool_operations.command',return_value=response)as dispatch:
        result=client.post(BASE+'agent-tool/',{'operation':'run','argv':['daq-local-diagnostics-v1','repair','a'*64],
            'timeout':20,'configuration_target':'forged-target'},format='json')
    assert result.status_code==200,result.content
    assert dispatch.call_args.args[1]['configuration_target']=='profile-a'
    assert dispatch.call_args.args[1]['expected_configuration_revision']=='b'*64
    assert 'expected_target_revision' not in dispatch.call_args.args[1]


def test_repair_without_matching_observed_snapshot_is_never_dispatched(target_run):
    client,run=target_run
    with patch('plane.quality.remote_tool_operations.command')as dispatch:
        result=client.post(BASE+'agent-tool/',{'operation':'run','argv':['daq-local-diagnostics-v1','repair','a'*64]},format='json')
    assert result.status_code==409,result.content
    dispatch.assert_not_called()
