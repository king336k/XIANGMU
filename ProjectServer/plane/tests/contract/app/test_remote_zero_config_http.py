"""Fresh host private configuration -> real enrollment HTTP -> actual PTY."""
import base64
import importlib.util
import json
from pathlib import Path
import sys
import time
from uuid import uuid4

import pytest
from django.test import Client
from plane.license.models import InstanceConfiguration
from plane.quality.remote_models import RemoteWorkstation
from plane.tests.contract.app.test_remote_diagnostics import BASE

pytest_plugins=['plane.tests.contract.app.test_remote_diagnostics']
pytestmark=[pytest.mark.contract,pytest.mark.django_db(transaction=True),pytest.mark.skipif(not Path('/daq/scripts/remote-diagnostics/bootstrap.py').exists(),reason='isolated /daq source mount required')]


def test_fresh_login_enrolls_once_and_real_terminal_works(remote,live_server,tmp_path,monkeypatch):
    _,_,_,project=remote
    manual=RemoteWorkstation.objects.first()
    InstanceConfiguration.objects.update_or_create(key='QUALITY_REMOTE_AUTO_ENROLLMENT',defaults={'value':json.dumps({'enabled':True,'project_id':str(project.id),'owner_user_id':str(manual.agent.owner_id)})})
    spec=importlib.util.spec_from_file_location('zero_bootstrap','/daq/scripts/remote-diagnostics/bootstrap.py')
    bootstrap=importlib.util.module_from_spec(spec);spec.loader.exec_module(bootstrap)
    monkeypatch.setattr(bootstrap,'machine_fingerprint',lambda:'a'*64)
    runtime=tmp_path/'runtime';(runtime/'project-feedback').mkdir(parents=True);config=tmp_path/'config'
    import socket
    origin=live_server.url.replace('0.0.0.0',socket.gethostbyname(socket.gethostname())).replace('localhost',socket.gethostbyname(socket.gethostname()))
    installation=str(uuid4())
    path=runtime/'project-feedback/connection.json';path.write_text(json.dumps({'url':origin,'device_id':installation,'secret':'report-only-synthetic-never-used-for-shell'}));path.chmod(0o600)
    assert bootstrap.bootstrap(runtime,config,enroll=True)['state']=='approval_required'
    sys.path.insert(0,'/daq/src/engram_Teleop_DAQ_web/backend')
    from app.feedback.remote_enrollment import authorize_after_login
    monkeypatch.setenv('PROJECT_FEEDBACK_CONFIG_FILE',str(path))
    assert authorize_after_login({'id':17,'username':'new-collector'}) is True
    first=bootstrap.bootstrap(runtime,config,enroll=True)
    assert first['state']=='active',first
    token=(config/'token').read_text();assert token.startswith('rw_')
    claim=(config/'bootstrap.json').read_bytes()
    second=bootstrap.bootstrap(runtime,config,enroll=True)
    assert second==first and claim==(config/'bootstrap.json').read_bytes() and token==(config/'token').read_text()
    assert RemoteWorkstation.objects.filter(pk=installation).count()==1
    assert json.loads((runtime/'remote-diagnostics/identity.json').read_text())['workstation_id']==installation
    sys.path.insert(0,'/repo/services/field-remote')
    from connector import Engine,Policy,identity
    from urllib.request import Request,build_opener,ProxyHandler
    engine=Engine(Policy(json.loads((config/'policy.json').read_text())),'127.0.0.1')
    opener=build_opener(ProxyHandler({}))
    actor=identity(engine.policy,origin)
    def exchange():
        engine.pump();outputs=engine.outputs[:100];results=engine.results[:100]
        request=Request(origin+BASE+'exchange/',data=json.dumps({'identity':actor,'outputs':outputs,'results':results}).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+token})
        with opener.open(request,timeout=10)as response:value=json.load(response)
        engine.acknowledge(len(outputs),len(results));engine.last_exchange=time.monotonic()
        for command in value['commands']:engine.accept(command)
    client=Client();client.force_login(manual.agent.owner)
    try:
        exchange()
        response=client.post(BASE,json.dumps({'action':'open','device_id':installation,'target':'operator'}),content_type='application/json')
        assert response.status_code==201
        sid=response.json()['id'];session=BASE+'sessions/'+sid+'/'
        exchange();exchange()
        payload={'action':'input','data':base64.b64encode(b"printf 'ZERO_%s\\n' 'CONFIG_HTTP_OK'\n").decode()}
        assert client.post(session,json.dumps(payload),content_type='application/json').status_code==200
        observed=b'';deadline=time.monotonic()+10;cursor=0
        while time.monotonic()<deadline:
            exchange();value=client.get(session,{'after':cursor}).json();cursor=value['cursor']
            observed+=b''.join(base64.b64decode(event['data'])for event in value['events'])
            if b'ZERO_CONFIG_HTTP_OK' in observed:break
            time.sleep(.03)
        assert b'ZERO_CONFIG_HTTP_OK' in observed
        actor['capabilities']['network']['ip_address']='10.3.2.1';exchange()
        assert RemoteWorkstation.objects.filter(pk=installation).count()==1
        assert client.get(BASE).json()['results']
        client.post(session,json.dumps({'action':'close'}),content_type='application/json');exchange()
    finally:engine.close()
    assert json.loads((config/'config.json').read_text())['workstation_id']==installation
