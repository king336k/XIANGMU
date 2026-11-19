from datetime import timedelta
import pytest
from django.utils import timezone
from plane.quality.remote_models import RemoteWorkstation
from plane.quality.models import FieldAgent
from plane.tests.contract.app.test_remote_diagnostics import BASE,heartbeat
pytest_plugins=['plane.tests.contract.app.test_remote_diagnostics']
pytestmark=[pytest.mark.contract,pytest.mark.django_db]

@pytest.fixture
def directory(remote):
    client,edge,device,project=remote;heartbeat(edge)
    original=RemoteWorkstation.objects.get(pk=device)
    for i in range(25):
        agent=FieldAgent.objects.create(project=project,owner=original.agent.owner,name=f'采集电脑{i:02}')
        RemoteWorkstation.objects.create(agent=agent,username=f'collector{i:02}',hostname=f'host{i:02}',
            credential_hash='test',credential_expires_at=timezone.now()+timedelta(hours=1),
            last_seen_at=timezone.now()if i%2 else timezone.now()-timedelta(minutes=2),
            capabilities={'network':{'ip_address':f'10.0.0.{i+1}'}})
    return client,device

def test_directory_pages_filters_and_keeps_active_device_outside_page(directory):
    client,device=directory
    first=client.get(BASE,{'page':1,'per_page':6,'active':device})
    assert first.status_code==200 and first.data['count']==26
    assert len(first.data['results'])==6 and len(first.data['active_results'])==1
    last=client.get(BASE,{'page':5,'per_page':6,'active':device})
    assert last.status_code==200 and len(last.data['results'])==2
    assert last.data['active_results'][0]['id']==device
    result=client.get(BASE,{'page':1,'per_page':6,'search':'host21'})
    assert result.status_code==200 and result.data['count']==1
    assert result.data['results'][0]['hostname']=='host21'
    online=client.get(BASE,{'page':1,'per_page':24,'status':'online'})
    assert online.status_code==200 and online.data['count']==13
    assert all(row['online']for row in online.data['results'])
    assert len(client.get(BASE).data['results'])==26,'legacy clients retain unpaged contract'

def test_directory_active_pin_never_discloses_disabled_device(directory):
    client,device=directory
    RemoteWorkstation.objects.filter(pk=device).update(enabled=False)
    response=client.get(BASE,{'page':1,'per_page':6,'active':device})
    assert response.status_code==200
    assert response.data['active_results']==[]
    assert all(row['id']!=device for row in response.data['results'])

@pytest.mark.parametrize('params',[{'page':'x'},{'page':0},{'per_page':500},{'status':'unknown'},{'active':'not-a-uuid'}])
def test_directory_rejects_invalid_paging(directory,params):
    client,_=directory
    assert client.get(BASE,params).status_code==400
