"""One queue admission covers inspect, all supported repairs and final verification."""
from datetime import timedelta
from unittest.mock import patch
import json
from types import SimpleNamespace

import pytest
from django.utils import timezone
from plane.quality.remote_models import RemoteAgentRun, RemoteFeedbackBinding, RemoteWorkstation
from plane.quality.models import Defect
from plane.quality.remote_diagnostics import identity_key
from plane.tests.contract.app.test_remote_diagnostics import BASE, heartbeat

pytest_plugins=['plane.tests.contract.app.test_remote_diagnostics']
pytestmark=[pytest.mark.contract,pytest.mark.django_db]


def test_field_job_uses_dedicated_queue_once(remote,django_capture_on_commit_callbacks):
    client,edge,device,project=remote;heartbeat(edge)
    station=RemoteWorkstation.objects.get(pk=device)
    defect=Defect.objects.create(project=project,title='whole repair',description='whole repair')
    RemoteFeedbackBinding.objects.create(workstation=station,defect=defect)
    with patch('plane.quality.remote_tasks.remote_repair.apply_async')as dispatch,django_capture_on_commit_callbacks(execute=True):
        response=client.post(BASE+'agent-runs/',{'device_id':device,'defect_id':str(defect.id),'mode':'repair','problem':'diagnose repair and verify all supported faults'},format='json')
    assert response.status_code==201
    dispatch.assert_called_once_with(args=[response.data['id']],queue='field-repairs')
    assert RemoteAgentRun.objects.filter(workstation=station,defect=defect).count()==1


def test_whole_job_persists_worker_lifetime_and_writes_one_feedback(remote):
    _,edge,device,project=remote;heartbeat(edge)
    station=RemoteWorkstation.objects.get(pk=device)
    defect=Defect.objects.create(project=project,title='two faults',description='two faults')
    run=RemoteAgentRun.objects.create(workstation=station,defect=defect,owner=station.agent.owner,mode='repair',identity_key=identity_key(station),expires_at=timezone.now()+timedelta(minutes=5))
    from plane.quality.remote_tasks import remote_repair
    response={'summary':'two repairs verified','actions':['repair A','repair B'],'verification':['same-session final verify passed'],'repaired':True,'verification_passed':True}
    with patch('plane.quality.remote_tasks.provider_config',return_value={'configured':True}),patch('plane.quality.remote_tasks.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(response)))as execute:
        remote_repair.run(str(run.id))
        remote_repair.run(str(run.id))
    assert execute.call_count==1
    run.refresh_from_db()
    assert run.started_at and run.completed_at and run.completed_at>=run.started_at>=run.created_at
    assert run.result['worker_started_at']==run.started_at.timestamp()
    assert run.result['worker_completed_at']==run.completed_at.timestamp()
    assert run.comment.content.startswith('Agent 远程处理：已修复')
    assert defect.comments.filter(content__startswith='Agent 远程处理：').count()==1


def test_invalidation_ends_job_but_does_not_invent_worker_release(remote):
    _,edge,device,project=remote;heartbeat(edge)
    station=RemoteWorkstation.objects.get(pk=device)
    defect=Defect.objects.create(project=project,title='disconnect mid job',description='disconnect mid job')
    started=timezone.now()
    run=RemoteAgentRun.objects.create(workstation=station,defect=defect,owner=station.agent.owner,status='running',started_at=started,identity_key=identity_key(station),expires_at=timezone.now()+timedelta(minutes=5))
    from plane.quality.remote_diagnostics import fail_runs
    from plane.quality.remote_tasks import finish
    fail_runs(station,'connection changed')
    run.refresh_from_db()
    assert run.status=='failed' and run.completed_at is not None
    assert run.result['worker_started_at']==started.timestamp()
    assert run.result['worker_completed_at'] is None
    finish(run.id,{'summary':'late report must not replace failed identity','repaired':True})
    run.refresh_from_db()
    assert run.status=='failed' and run.result['worker_completed_at'] is not None
    assert run.result.get('repaired') is not True and run.comment_id is None
