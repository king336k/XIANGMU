"""Real HTTP/Postgres/Redis/Celery/PTY/file mixed acceptance. No model capacity claim."""
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest
from celery.contrib.testing.worker import start_worker
from django.conf import settings as django_settings
from django.db import close_old_connections
from django.test import Client
from django.utils import timezone

from plane.celery import app
from plane.db.models import User, Workspace, WorkspaceMember, Project, ProjectMember
from plane.license.models import Instance, InstanceAdmin
from plane.license.models import InstanceConfiguration
from plane.quality.models import Defect, DiagnosticJob, FieldAgent
from plane.quality.remote_models import RemoteWorkstation, RemoteAgentRun
from plane.quality.remote_diagnostics import digest
from plane.tests.contract.app.test_daq_incidents import signature

pytestmark=[pytest.mark.contract, pytest.mark.django_db(transaction=True), pytest.mark.skipif(not os.environ.get("REMOTE_STRESS_BROKER"),reason="isolated Redis/HTTP mixed harness is opt-in")]


@pytest.fixture
def isolated_server(settings, request):
    settings.REMOTE_STRESS_ISOLATION=uuid4().hex
    settings.MIDDLEWARE=[*settings.MIDDLEWARE,'plane.tests.remote_stress.middleware.IsolationMarker']
    settings.DEBUG=False
    settings.ALLOWED_HOSTS=['*']
    settings.CELERY_BROKER_URL=os.environ['REMOTE_STRESS_BROKER']
    app.conf.update(broker_url=os.environ['REMOTE_STRESS_BROKER'],worker_prefetch_multiplier=1,task_default_queue='diagnostics')
    return request.getfixturevalue('live_server')


@pytest.mark.parametrize('station_count',[int(os.environ.get('REMOTE_STRESS_STATIONS','4'))])
def test_isolated_mixed_http(station_count, settings, isolated_server, monkeypatch):
    settings.CELERY_BROKER_URL=os.environ['REMOTE_STRESS_BROKER']
    app.conf.update(broker_url=os.environ['REMOTE_STRESS_BROKER'],worker_prefetch_multiplier=1,task_default_queue='diagnostics')
    server_url=isolated_server.url.replace('localhost','127.0.0.1')
    isolation=settings.REMOTE_STRESS_ISOLATION
    settings.QUALITY_DAQ_REPORT_KEYS={'test-incidents':{'secret':'synthetic-incidents-only','audience':'plane-quality','source_instance':'isolated-stress'}}
    output=Path('/home/engram/Documents/tmp/artifacts/remote-diagnostics-2026-11-18/mixed-platform-stress')/('platform-'+str(station_count)+'-'+isolation+'.json')
    workspace=Workspace.objects.create(name='Isolated Mixed Stress',slug='stress-'+isolation,owner=User.objects.create(username='owner-'+isolation,email=isolation+'@invalid.test'))
    project=Project.objects.create(workspace=workspace,name='Isolated Remote Load',identifier='STRESS')
    InstanceConfiguration.objects.create(key='QUALITY_DAQ_PROJECT_GRANTS',value=json.dumps({'projects':[str(project.id)],'revision':1}))
    instance=Instance.objects.create(instance_name='stress',instance_id=str(uuid4()),current_version='test',last_checked_at=timezone.now())
    users=[]
    for index in range(4):
        user=User.objects.create(username='stress-'+str(index)+'-'+isolation,email=str(index)+isolation+'@invalid.test')
        WorkspaceMember.objects.create(workspace=workspace,member=user,role=20)
        ProjectMember.objects.create(project=project,member=user,role=20)
        InstanceAdmin.objects.create(instance=instance,user=user)
        client=Client();client.force_login(user)
        users.append({'id':str(user.id),'headers':{'Cookie':django_settings.SESSION_COOKIE_NAME+'='+client.cookies[django_settings.SESSION_COOKIE_NAME].value}})
    stations=[]
    for index in range(station_count):
        raw='rw_'+uuid4().hex+uuid4().hex
        owner=User.objects.get(pk=users[index%len(users)]['id'])
        agent=FieldAgent.objects.create(project=project,created_by=owner,owner=owner,name='isolated-'+str(index),source_instance='isolated-stress')
        from datetime import timedelta
        station=RemoteWorkstation.objects.create(agent=agent,credential_hash=digest(raw),credential_expires_at=timezone.now()+timedelta(hours=1),capabilities={'agent_context':{'repair_allowed':True,'readable_files':['config.json'],'editable_files':['config.json'],'auto_diagnose':False}})
        ids=[];paths=[]
        # Signed DAQ reports pass through the actual HTTP destination/authentication.
        import urllib.request
        for ordinal in range(2):
            path='/api/quality-auth/daq-reports/'
            body=json.dumps({'hubProjectId':str(project.id),'eventId':str(uuid4()),'kind':'startup_failure','occurredAt':timezone.now().isoformat(),'title':f'采集电脑 {index} 故障 {ordinal}','description':'隔离测试配置 fixed=false','device':str(station.id)})
            headers={key[5:].replace('_','-'):value for key,value in signature(path,body).items()}
            request=urllib.request.Request(server_url+path,data=body.encode(),headers={'Content-Type':'application/json',**headers},method='POST')
            with urllib.request.urlopen(request,timeout=15) as response:
                result=json.load(response)
            defect=Defect.objects.get(pk=result['issueId'])
            ids.append(str(defect.id))
            job=DiagnosticJob.objects.create(project=project,defect=defect,created_by=owner,request_id=uuid4(),mode='rules',status='completed',result={'answer':'受控原始诊断，不能被其他反馈或现场处理覆盖。'})
            paths.append(f'/api/workspaces/{workspace.slug}/projects/{project.id}/quality/diagnostics/{job.id}/')
        stations.append({'device_id':str(station.id),'token':raw,'owner_user_id':str(owner.id),'allowed_user_ids':[u['id'] for u in users],
            'defect_ids':ids,'diagnostic_paths':paths,'diagnostic_create_paths':[f'/api/workspaces/{workspace.slug}/projects/{project.id}/quality/defects/{ids[0]}/diagnostics/'],'initial_config':{'station':str(station.id),'fixed':False},'expected_repair_config':{'station':str(station.id),'fixed':True}})
    monkeypatch.setattr('plane.quality.remote_tasks.provider_config',lambda _: {'configured':True})
    monkeypatch.setenv('REMOTE_TOOL_ORIGIN',server_url)
    monkeypatch.setenv('REMOTE_AGENT_SCRIPT','/code/plane/tests/remote_stress/controlled_runner.py')
    monkeypatch.setenv('DIAGNOSTIC_AGENT_PYTHON',sys.executable)
    app.conf.update(broker_url=os.environ['REMOTE_STRESS_BROKER'],worker_prefetch_multiplier=1,task_default_queue='diagnostics')
    manifest={'test_environment':True,'isolation_id':isolation,'base_url':server_url,'model_mode':'controlled_stub','users':users,'stations':stations}
    close_old_connections()
    with start_worker(app,pool='threads',concurrency=4,queues=['diagnostics'],perform_ping_check=False,shutdown_timeout=30,loglevel='ERROR'):
        result=subprocess.run([sys.executable,'/repo/services/field-remote/platform_stress.py','--manifest','-','--output',str(output)],input=json.dumps(manifest),text=True,capture_output=True,timeout=720)
    # Credential payload is never included in an assertion or report.
    assert result.returncode==0, f'isolated client failed; inspect {output}'
    report=json.loads(output.read_text())
    assert report['ok'] and report['station_count']==station_count
    assert all(row['original_diagnostics_unchanged'] for row in report['stations'])
    assert RemoteAgentRun.objects.filter(workstation_id__in=[row['device_id'] for row in stations],status='completed').count()==station_count*2
    assert not RemoteAgentRun.objects.filter(workstation_id__in=[row['device_id'] for row in stations],status__in=['queued','running']).exists()
    os.chown(output,1000,1000)
    print(json.dumps({'report':str(output),'operations':report['operation_count'],'p95_ms':report['p95_ms']}))
