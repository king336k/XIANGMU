"""Real database/API regressions for mixed remote operations."""
from datetime import timedelta
from unittest.mock import patch

import pytest
from celery.exceptions import Retry
from django.utils import timezone

from plane.quality.models import Defect
from plane.quality.remote_models import RemoteAgentRun, RemoteFeedbackBinding, RemoteWorkstation, RemoteTerminal, RemoteCommand
from plane.quality.remote_diagnostics import identity_key
from plane.tests.contract.app.test_remote_diagnostics import heartbeat, BASE

pytest_plugins = ["plane.tests.contract.app.test_remote_diagnostics"]

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def bound(remote, title="queue"):
    client, edge, device, project = remote
    heartbeat(edge)
    station = RemoteWorkstation.objects.get(pk=device)
    defect = Defect.objects.create(project=project, title=title, description=title)
    RemoteFeedbackBinding.objects.create(workstation=station, defect=defect)
    return station, defect


def run_for(station, defect, **values):
    return RemoteAgentRun.objects.create(workstation=station, defect=defect, owner=station.agent.owner,
        identity_key=identity_key(station), expires_at=timezone.now()+timedelta(minutes=8), **values)


def test_busy_device_accepts_different_feedback_and_reports_queue(remote):
    client, edge, device, project = remote
    station, defect = bound(remote)
    run_for(station, defect)
    second = Defect.objects.create(project=project, title="second", description="second")
    RemoteFeedbackBinding.objects.create(workstation=station, defect=second)
    with patch("plane.quality.remote_tasks.remote_repair.apply_async"):
        response = client.post(BASE+"agent-runs/", {"device_id": device,"defect_id":str(second.id),"problem":"inspect","mode":"diagnose"},format="json")
    assert response.status_code == 201, response.content
    detail = client.get(BASE+"agent-runs/"+response.data["id"]+"/")
    assert detail.data["queue"] == {"position":1,"reason":"device_busy","stage":"queued"}
    with patch("plane.quality.remote_tasks.remote_repair.apply_async"):
        duplicate = client.post(BASE+"agent-runs/", {"device_id":device,"defect_id":str(second.id),"problem":"inspect"},format="json")
    assert duplicate.status_code == 409
    assert RemoteAgentRun.objects.filter(workstation=station,status="queued").count() == 2


def test_terminal_busy_request_is_queued_until_terminal_closed(remote):
    client, edge, device, _ = remote
    station, defect = bound(remote)
    opened = client.post(BASE,{"action":"open","device_id":device},format="json")
    assert opened.status_code == 201
    with patch("plane.quality.remote_tasks.remote_repair.apply_async"):
        response = client.post(BASE+"agent-runs/",{"device_id":device,"defect_id":str(defect.id),"problem":"inspect"},format="json")
    assert response.status_code == 201
    assert client.get(BASE+"agent-runs/"+response.data["id"]+"/").data["queue"]["reason"] == "terminal_open"
    from plane.quality.remote_tasks import remote_repair
    with patch.object(remote_repair,"retry",side_effect=Retry()), patch("plane.quality.remote_tasks.provider_config") as provider:
        with pytest.raises(Retry): remote_repair.run(response.data["id"])
    provider.assert_not_called()
    assert RemoteAgentRun.objects.get(pk=response.data["id"]).status == "queued"


def test_worker_cannot_overtake_earlier_device_task(remote):
    station, defect = bound(remote)
    first = run_for(station,defect)
    later = run_for(station,defect)
    from plane.quality.remote_tasks import remote_repair
    with patch.object(remote_repair,"retry",side_effect=Retry()), patch("plane.quality.remote_tasks.provider_config") as provider:
        with pytest.raises(Retry): remote_repair.run(str(later.id))
    provider.assert_not_called()
    first.refresh_from_db(); later.refresh_from_db()
    assert first.status == later.status == "queued"


def test_provider_failure_finishes_claimed_run_instead_of_blocking_device(remote):
    station, defect = bound(remote)
    run = run_for(station,defect)
    from plane.quality.remote_tasks import remote_repair
    with patch("plane.quality.remote_tasks.provider_config",side_effect=RuntimeError("controlled unavailable")):
        remote_repair.run(str(run.id))
    run.refresh_from_db()
    assert run.status == "failed" and not run.tool_credential_hash


def test_stale_terminal_cannot_be_revived_after_agent_claim(remote):
    client, edge, device, _ = remote
    station, defect = bound(remote)
    response=client.post(BASE,{"action":"open","device_id":device},format="json")
    terminal=RemoteTerminal.objects.get(pk=response.data["id"])
    terminal.last_read_at=timezone.now()-timedelta(seconds=61);terminal.save()
    run_for(station,defect,status="running")
    response=client.get(BASE+"sessions/"+str(terminal.id)+"/")
    assert response.data["status"] == "closed"
    assert client.post(BASE+"sessions/"+str(terminal.id)+"/",{"action":"input","data":"bHMK"},format="json").status_code == 409


def test_file_dispatch_serializes_tasks_but_keeps_terminal_transport(remote):
    client, edge, device, _ = remote
    station, _ = bound(remote)
    ids=[]
    for _ in range(2):
        response=client.post(BASE+"files/",{"device_id":device,"action":"list","target":"operator","path":""},format="json")
        assert response.status_code == 201,response.content
        ids.append(response.data["id"])
    dispatched=heartbeat(edge).data["commands"]
    assert len(dispatched) == 1
    assert len(heartbeat(edge).data["commands"]) == 1
    heartbeat(edge,results=[{"id":dispatched[0]["id"],"ok":True,"file_result":{"entries":[]}}])
    second=heartbeat(edge).data["commands"]
    assert len(second)==1 and second[0]["id"] != dispatched[0]["id"]


def test_running_agent_blocks_new_file_requests_instead_of_stealing_executor_slot(remote):
    client, _, device, _ = remote
    station, defect = bound(remote)
    run_for(station,defect,status="running")
    response=client.post(BASE+"files/",{"device_id":device,"action":"list","target":"robot","path":""},format="json")
    assert response.status_code == 409
    assert not RemoteCommand.objects.filter(workstation=station,payload__kind="file_browser").exists()


def test_terminal_get_commits_permission_revocation_cleanup(remote):
    client, _, device, project = remote
    station, _ = bound(remote)
    opened=client.post(BASE,{"action":"open","device_id":device},format="json")
    station.enabled=False
    station.save(update_fields=["enabled"])
    response=client.get(BASE+"sessions/"+opened.data["id"]+"/")
    assert response.status_code == 403
    assert RemoteTerminal.objects.get(pk=opened.data["id"]).status=="closed"


def test_signed_feedback_automatically_queues_while_terminal_busy_and_replay_is_idempotent(remote, settings, django_capture_on_commit_callbacks):
    import json
    from uuid import uuid4
    from plane.license.models import InstanceConfiguration
    from plane.tests.contract.app.test_daq_incidents import signature
    from rest_framework.test import APIClient
    client, edge, device, project = remote
    heartbeat(edge)
    station=RemoteWorkstation.objects.get(pk=device)
    station.agent.source_instance='daq-device';station.agent.save(update_fields=['source_instance'])
    station.capabilities={'agent_context':{'auto_diagnose':True}};station.save(update_fields=['capabilities'])
    settings.QUALITY_DAQ_REPORT_KEYS={'test-incidents':{'secret':'synthetic-incidents-only','audience':'plane-quality','source_instance':'daq-device'}}
    InstanceConfiguration.objects.update_or_create(key='QUALITY_DAQ_PROJECT_GRANTS',defaults={'value':json.dumps({'projects':[str(project.id)],'revision':1})})
    assert client.post(BASE,{'action':'open','device_id':device},format='json').status_code==201
    path='/api/quality-auth/daq-reports/'
    with patch('plane.quality.remote_tasks.remote_repair.apply_async') as dispatch:
        for index in range(4):
            body=json.dumps({'hubProjectId':str(project.id),'eventId':str(uuid4()),'kind':'startup_failure','occurredAt':timezone.now().isoformat(),'title':f'auto burst {index}','description':'isolated queue','device':device})
            with django_capture_on_commit_callbacks(execute=True):
                first=APIClient().post(path,body,content_type='application/json',**signature(path,body))
            assert first.status_code==201,first.content
        with django_capture_on_commit_callbacks(execute=True):
            replay=APIClient().post(path,body,content_type='application/json',**signature(path,body))
        assert replay.status_code==200 and replay.data['issueId']==first.data['issueId']
    queued=RemoteAgentRun.objects.filter(workstation=station,status='queued')
    assert queued.count()==4 and dispatch.call_count==4
    from plane.quality.remote_diagnostics import run_queue
    assert all(run_queue(run)['reason']=='terminal_open' for run in queued)
