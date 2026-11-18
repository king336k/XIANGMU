from uuid import uuid4
import json
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from plane.license.models import InstanceConfiguration
from plane.quality.remote_models import RemoteWorkstation, RemoteAgentRun, RemoteCommand
from plane.quality.remote_diagnostics import identity_key
from plane.quality.models import Defect
from plane.tests.contract.app.test_remote_diagnostics import heartbeat, BASE

pytest_plugins=["plane.tests.contract.app.test_remote_diagnostics"]
pytestmark=[pytest.mark.contract,pytest.mark.django_db]


def test_enrollment_is_durable_and_not_derived_from_ip_or_daq_version(remote):
    _, _, _, project=remote
    owner=RemoteWorkstation.objects.first().agent.owner
    InstanceConfiguration.objects.update_or_create(key="QUALITY_REMOTE_AUTO_ENROLLMENT",defaults={"value":json.dumps({"enabled":True,"project_id":str(project.id),"owner_user_id":str(owner.id)})})
    body={"protocol":"daq-remote-enrollment-v1","installation_id":str(uuid4()),"claim_secret":"synthetic-claim-"+uuid4().hex,"machine_fingerprint":"a"*64,"identity":{"username":"collector1","hostname":"same-machine","boot_id":"boot1"}}
    client=APIClient()
    first=client.post(BASE+"enroll/",body,format="json")
    assert first.status_code==201,first.content
    assert first.data["status"]=="active" and first.data["token"].startswith("rw_")
    body['identity']['hostname']='renamed-same-machine'
    second=client.post(BASE+"enroll/",body,format="json")
    assert second.status_code==200 and second.data['token']==first.data['token']
    assert second.data['workstation_id']==first.data['workstation_id']==body['installation_id']
    assert RemoteWorkstation.objects.filter(pk=body['installation_id']).count()==1
    body['claim_secret']='different-claim-'+uuid4().hex
    assert client.post(BASE+'enroll/',body,format='json').status_code==409


def test_enrollment_never_reissues_manual_or_revoked_device(remote):
    _, _, device, project=remote
    station=RemoteWorkstation.objects.get(pk=device)
    InstanceConfiguration.objects.update_or_create(key='QUALITY_REMOTE_AUTO_ENROLLMENT',defaults={'value':json.dumps({'enabled':True,'project_id':str(project.id),'owner_user_id':str(station.agent.owner_id)})})
    body={'protocol':'daq-remote-enrollment-v1','installation_id':device,'claim_secret':'x'*40,'machine_fingerprint':'a'*64,'identity':{'username':'old'}}
    assert APIClient().post(BASE+'enroll/',body,format='json').status_code==409
    body['installation_id']=str(uuid4())
    assert APIClient().post(BASE+'enroll/',body,format='json').status_code==201
    station=RemoteWorkstation.objects.get(pk=body['installation_id']);station.enabled=False;station.save()
    assert APIClient().post(BASE+'enroll/',body,format='json').status_code==409


def test_robot_terminal_binds_active_peer_and_dhcp_preserves_card(remote):
    client,edge,device,_=remote
    identity={'username':'collector','hostname':'same-pc','boot_id':'same-boot','capabilities':{'network':{'ip_address':'10.1.2.3'},'robot':{'connected':True,'username':'robotuser','host':'10.1.1.10','target_revision':'a'*64}}}
    assert heartbeat(edge,identity=identity).status_code==200
    response=client.post(BASE,{'action':'open','device_id':device,'target':'robot','expected_target_revision':'a'*64},format='json')
    assert response.status_code==201,response.content
    assert response.data['identity']=={'username':'robotuser','host':'10.1.1.10'}
    sid=response.data['id']
    identity['capabilities']['network']['ip_address']='10.1.2.4'
    assert heartbeat(edge,identity=identity).status_code==200
    assert client.get(BASE+'sessions/'+sid+'/').data['status']=='open'
    assert client.get(BASE).data['results'][0]['id']==device
    identity['capabilities']['robot'].update(host='10.1.1.11',target_revision='b'*64)
    heartbeat(edge,identity=identity)
    assert client.get(BASE+'sessions/'+sid+'/').data['status']=='closed'
    assert client.post(BASE,{'action':'open','device_id':device,'target':'robot','expected_target_revision':'a'*64},format='json').status_code==409


def test_peer_switch_invalidates_agent_commands_without_new_collector_card(remote):
    client,edge,device,project=remote
    identity={'username':'collector','hostname':'pc','boot_id':'boot','capabilities':{'robot':{'connected':True,'username':'robot','host':'10.2.0.1','target_revision':'a'*64}}}
    heartbeat(edge,identity=identity)
    station=RemoteWorkstation.objects.get(pk=device)
    defect=Defect.objects.create(project=project,title='robot A task',description='robot A task')
    run=RemoteAgentRun.objects.create(workstation=station,defect=defect,owner=station.agent.owner,status='running',identity_key=identity_key(station),expires_at=timezone.now()+timedelta(minutes=2))
    row=RemoteCommand.objects.create(workstation=station,run=run,payload={'kind':'run','argv':['/fixed']},expires_at=run.expires_at)
    identity['capabilities']['robot'].update(host='10.2.0.2',target_revision='b'*64)
    response=heartbeat(edge,identity=identity)
    run.refresh_from_db();row.refresh_from_db()
    assert run.status=='failed' and row.status=='expired'
    assert str(row.id) not in {item['id']for item in response.data['commands']}
    assert client.get(BASE).data['results'][0]['id']==device


def test_enrollment_requires_enabled_policy_and_machine_ownership(remote):
    _,_,_,project=remote
    client=APIClient()
    body={'protocol':'daq-remote-enrollment-v1','installation_id':str(uuid4()),'claim_secret':'x'*48,'machine_fingerprint':'a'*64,'identity':{'username':'collector'}}
    assert client.post(BASE+'enroll/',body,format='json').status_code==409
    owner=RemoteWorkstation.objects.first().agent.owner
    InstanceConfiguration.objects.update_or_create(key='QUALITY_REMOTE_AUTO_ENROLLMENT',defaults={'value':json.dumps({'enabled':True,'project_id':str(project.id),'owner_user_id':str(owner.id)})})
    assert client.post(BASE+'enroll/',body,format='json').status_code==201
    body['machine_fingerprint']='b'*64
    assert client.post(BASE+'enroll/',body,format='json').status_code==409
