import base64
from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from plane.db.models import Project, ProjectMember
from plane.license.models import Instance, InstanceAdmin
from plane.quality.remote_models import RemoteCommand, RemoteWorkstation

pytestmark = [pytest.mark.contract, pytest.mark.django_db]
BASE = "/api/quality-auth/remote-diagnostics/"


@pytest.fixture
def remote(workspace, create_user):
    instance = Instance.objects.create(
        instance_name="remote",
        instance_id=str(uuid4()),
        current_version="test",
        last_checked_at=timezone.now(),
    )
    InstanceAdmin.objects.create(instance=instance, user=create_user)
    project = Project.objects.create(workspace=workspace, name="Remote", identifier="REMOTE")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    client = APIClient()
    client.force_authenticate(create_user)
    response = client.post(
        BASE, {"action": "register", "project_id": str(project.id), "name": "operator"}, format="json"
    )
    assert response.status_code == 201, response.content
    edge = APIClient()
    edge.credentials(HTTP_AUTHORIZATION="Bearer " + response.data["token"])
    return client, edge, response.data["id"], project


def heartbeat(edge, **values):
    return edge.post(
        BASE + "exchange/",
        {
            "identity": {"username": "caozuo1", "hostname": "operator195", "boot_id": "boot1", "capabilities": {"file_browser": {"ready": True}}},
            "outputs": [],
            "results": [],
            **values,
        },
        format="json",
    )


def test_outbound_terminal_identity_bytes_and_dedup(remote):
    client, edge, device, _ = remote
    assert heartbeat(edge).status_code == 200
    listing = client.get(BASE).data["results"]
    assert listing[0]["username"] == "caozuo1" and listing[0]["online"]
    response = client.post(
        BASE, {"action": "open", "device_id": device, "cols": 80, "rows": 24}, format="json"
    )
    assert response.status_code == 201
    sid = response.data["id"]
    commands = heartbeat(edge).data["commands"]
    assert commands[0]["kind"] == "terminal_open"
    heartbeat(edge, results=[{"id": commands[0]["id"], "ok": True}])
    data = base64.b64encode("caozuo1@195$ 中文\r\n".encode()).decode()
    event = {"id": "event1", "session_id": sid, "kind": "data", "data": data}
    assert heartbeat(edge, outputs=[event]).status_code == 200
    assert heartbeat(edge, outputs=[event]).status_code == 200
    response = client.get(BASE + f"sessions/{sid}/")
    assert len(response.data["events"]) == 1 and response.data["events"][0]["data"] == data
    assert client.post(BASE + f"sessions/{sid}/", {"action": "close"}, format="json").status_code == 200
    assert (
        client.post(BASE + f"sessions/{sid}/", {"action": "input", "data": data}, format="json").status_code
        == 409
    )


def test_expiry_and_cross_device_results_are_rejected(remote):
    client, edge, device, project = remote
    heartbeat(edge)
    station = RemoteWorkstation.objects.get(pk=device)
    foreign = RemoteCommand.objects.create(
        workstation=station, payload={"kind": "run"}, expires_at=timezone.now() - timedelta(seconds=1)
    )
    assert foreign.id not in {row["id"] for row in heartbeat(edge).data["commands"]}
    unknown = heartbeat(edge, results=[{"id": str(uuid4()), "ok": True}])
    assert unknown.status_code == 400
    station.credential_expires_at = timezone.now() - timedelta(seconds=1)
    station.save()
    assert heartbeat(edge).status_code == 401


def test_regular_members_cannot_acquire_shell(remote, create_user, workspace):
    client, edge, device, project = remote
    heartbeat(edge)
    from plane.db.models import User, WorkspaceMember

    other = User.objects.create(username="observer", email="observer@invalid.example")
    WorkspaceMember.objects.create(workspace=workspace, member=other, role=15)
    ProjectMember.objects.create(project=project, member=other, role=15)
    other_client = APIClient()
    other_client.force_authenticate(other)
    assert other_client.post(BASE, {"action": "open", "device_id": device}, format="json").status_code == 403
    assert other_client.get(BASE).data["results"] == []


def test_boot_change_invalidates_existing_terminal(remote):
    client, edge, device, _ = remote
    heartbeat(edge)
    sid = client.post(BASE, {"action": "open", "device_id": device}, format="json").data["id"]
    heartbeat(edge, identity={"username": "caozuo1", "hostname": "operator195", "boot_id": "boot2"})
    assert client.get(BASE + f"sessions/{sid}/").data["status"] == "closed"


def test_exit_keeps_final_output_and_failed_open_is_visible(remote):
    client, edge, device, _ = remote
    heartbeat(edge)
    sid = client.post(BASE, {"action": "open", "device_id": device}, format="json").data["id"]
    data = base64.b64encode(b"final-output\r\n").decode()
    response = heartbeat(edge, outputs=[{"id":"tail", "session_id":sid,"kind":"data","data":data},{"id":"exit","session_id":sid,"kind":"exit","code":0}])
    assert response.status_code == 200
    result = client.get(BASE+f"sessions/{sid}/").data
    assert result["status"]=="closed" and result["events"][0]["data"]==data
    sid2=client.post(BASE,{"action":"open","device_id":device},format="json").data["id"]
    opening=next(c for c in heartbeat(edge).data["commands"] if c.get("session_id")==sid2 and c["kind"]=="terminal_open")
    heartbeat(edge,results=[{"id":opening["id"],"ok":False}])
    failed=client.get(BASE+f"sessions/{sid2}/").data
    assert failed["status"]=="closed" and failed["error"]


def test_revocation_expires_pending_repairs_and_origin_guard(remote):
    from plane.quality.models import Defect
    from plane.quality.remote_models import RemoteAgentRun
    client,edge,device,project=remote
    heartbeat(edge)
    station=RemoteWorkstation.objects.get(pk=device)
    defect=Defect.objects.create(project=project,title="test",description="simulation",created_by=project.created_by)
    run=RemoteAgentRun.objects.create(workstation=station,defect=defect,owner=station.agent.owner,expires_at=timezone.now()+timedelta(minutes=1),status="running")
    row=RemoteCommand.objects.create(workstation=station,run=run,payload={"kind":"run","argv":["true"]},expires_at=run.expires_at)
    denied=client.post(BASE,{"action":"revoke","device_id":device},format="json",HTTP_ORIGIN="https://wrong.invalid")
    assert denied.status_code==403
    assert client.post(BASE,{"action":"revoke","device_id":device},format="json").status_code==200
    row.refresh_from_db();run.refresh_from_db()
    assert row.status=="expired" and run.status=="failed"
    assert heartbeat(edge).status_code==401


def test_feedback_list_and_run_refuse_another_computers_same_project_feedback(remote):
    from unittest.mock import patch
    from plane.quality.models import Defect, SourceLink, DefectEvent
    from plane.quality.daq_incidents import SALT, fingerprint
    from django.core import signing
    import json
    client, edge, device, project = remote
    heartbeat(edge)
    own = Defect.objects.create(project=project, title="own", description="own")
    foreign = Defect.objects.create(project=project, title="foreign", description="foreign")
    own_link = SourceLink.objects.create(project=project, defect=own, source_system="ENGRAM_DAQ", source_instance="device-source", record_type="daq_incident", record_id="own", device=device)
    payload = {"device": device}
    record = {"linkId":str(own_link.id), "defectId":str(own.id), "projectId":str(project.id), "sourceInstance":own_link.source_instance, "recordId":"own", "actorId":str(own_link.created_by_id), "requestHash":fingerprint(payload), "payload":payload, "authorityMode":"report_only"}
    DefectEvent.objects.create(project=project, defect=own, status="open", note=json.dumps({"incidentSignature":signing.dumps(record,salt=SALT)}))
    SourceLink.objects.create(project=project, defect=foreign, source_system="ENGRAM_DAQ", source_instance="device-source", record_type="daq_incident", record_id="foreign", device=str(uuid4()))
    forged = Defect.objects.create(project=project, title="forged", description="forged")
    SourceLink.objects.create(project=project, defect=forged, source_system="ENGRAM_DAQ", source_instance="device-source", record_type="daq_incident", record_id="forged", device=device)
    listed = client.get(BASE + "feedback/", {"device_id": device})
    assert {row["id"] for row in listed.data["results"]} == {str(own.id)}
    with patch("plane.quality.remote_tasks.remote_repair.apply_async"):
        denied = client.post(BASE + "agent-runs/", {"device_id": device, "defect_id": str(foreign.id), "problem": "repair"}, format="json")
        assert denied.status_code == 404
        accepted = client.post(BASE + "agent-runs/", {"device_id": device, "defect_id": str(own.id), "problem": "repair"}, format="json")
        assert accepted.status_code == 201


def test_boot_change_expires_delivered_repair_and_existing_run(remote):
    from plane.quality.models import Defect
    from plane.quality.remote_models import RemoteAgentRun
    client, edge, device, project = remote
    heartbeat(edge)
    station = RemoteWorkstation.objects.get(pk=device)
    defect = Defect.objects.create(project=project, title="repair", description="repair")
    run = RemoteAgentRun.objects.create(workstation=station, defect=defect, owner=station.agent.owner, status="running", tool_credential_hash="synthetic", expires_at=timezone.now()+timedelta(minutes=1))
    row = RemoteCommand.objects.create(workstation=station, run=run, payload={"kind":"patch_file", "path":"config.json", "content":"{}"}, status="delivered", expires_at=run.expires_at)
    response = heartbeat(edge, identity={"username":"caozuo1", "hostname":"operator195", "boot_id":"boot2"})
    assert response.status_code == 200
    assert str(row.id) not in {command["id"] for command in response.data["commands"]}
    run.refresh_from_db(); row.refresh_from_db()
    assert run.status == "failed" and not run.tool_credential_hash and row.status == "expired"


def test_expired_terminal_post_commits_close_even_when_input_is_rejected(remote):
    from plane.quality.remote_models import RemoteTerminal
    client, edge, device, _ = remote
    heartbeat(edge)
    sid = client.post(BASE, {"action":"open", "device_id":device}, format="json").data["id"]
    RemoteTerminal.objects.filter(pk=sid).update(expires_at=timezone.now()-timedelta(seconds=1))
    response = client.post(BASE + f"sessions/{sid}/", {"action":"input", "data":"YQ=="}, format="json")
    assert response.status_code == 409
    assert RemoteTerminal.objects.get(pk=sid).status == "closed"


def test_permission_denied_terminal_post_commits_close(remote):
    from plane.quality.remote_models import RemoteTerminal
    client, edge, device, project = remote
    heartbeat(edge)
    sid = client.post(BASE, {"action":"open", "device_id":device}, format="json").data["id"]
    RemoteWorkstation.objects.filter(pk=device).update(enabled=False)
    response = client.post(BASE + f"sessions/{sid}/", {"action":"input", "data":"YQ=="}, format="json")
    assert response.status_code == 403
    assert RemoteTerminal.objects.get(pk=sid).status == "closed"


def test_explicit_feedback_binding_allows_legacy_without_fabricating_source(remote):
    from unittest.mock import patch
    from plane.quality.models import Defect, SourceLink
    from plane.quality.remote_models import RemoteFeedbackBinding, RemoteAgentRun
    from plane.quality.remote_diagnostics import identity_key
    client, edge, device, project = remote
    heartbeat(edge)
    station = RemoteWorkstation.objects.get(pk=device)
    defect = Defect.objects.create(project=project, title="legacy", description="legacy")
    assert client.get(BASE + "feedback/", {"device_id": device}).data["results"] == []
    RemoteFeedbackBinding.objects.create(workstation=station, defect=defect, created_by=station.agent.owner)
    assert client.get(BASE + "feedback/", {"device_id": device}).data["results"][0]["id"] == str(defect.id)
    with patch("plane.quality.remote_tasks.remote_repair.apply_async"):
        response = client.post(BASE + "agent-runs/", {"device_id":device, "defect_id":str(defect.id), "problem":"inspect"}, format="json")
    assert response.status_code == 201
    assert RemoteAgentRun.objects.get(pk=response.data["id"]).identity_key == identity_key(station)
    assert not SourceLink.objects.filter(defect=defect).exists()


def test_live_hostname_change_fails_old_run_and_rejects_late_result(remote):
    from plane.quality.models import Defect
    from plane.quality.remote_models import RemoteAgentRun
    from plane.quality.remote_diagnostics import identity_key
    client, edge, device, project = remote
    heartbeat(edge)
    station = RemoteWorkstation.objects.get(pk=device)
    defect = Defect.objects.create(project=project, title="repair", description="repair")
    run = RemoteAgentRun.objects.create(workstation=station, defect=defect, owner=station.agent.owner, identity_key=identity_key(station), status="running", tool_credential_hash="synthetic", expires_at=timezone.now()+timedelta(minutes=1))
    row = RemoteCommand.objects.create(workstation=station, run=run, payload={"kind":"run"}, status="delivered", expires_at=run.expires_at)
    response = heartbeat(edge, identity={"username":"caozuo1", "hostname":"different-computer", "boot_id":"boot1"}, results=[{"id":str(row.id), "ok":True, "exit_code":0}])
    assert response.status_code == 200
    run.refresh_from_db(); row.refresh_from_db()
    assert run.status == "failed" and row.status == "expired" and not row.result


def test_dispatch_expires_commands_after_run_owners_permission_is_removed(remote):
    from plane.db.models import User, WorkspaceMember
    from plane.license.models import InstanceAdmin
    from plane.quality.models import Defect
    from plane.quality.remote_models import RemoteAgentRun
    from plane.quality.remote_diagnostics import identity_key
    client, edge, device, project = remote
    heartbeat(edge)
    station = RemoteWorkstation.objects.get(pk=device)
    other = User.objects.create(username="revoked-owner", email="revoked@invalid.example")
    InstanceAdmin.objects.create(instance=InstanceAdmin.objects.first().instance, user=other)
    WorkspaceMember.objects.create(workspace=project.workspace, member=other, role=20)
    membership = ProjectMember.objects.create(project=project, member=other, role=20)
    defect = Defect.objects.create(project=project, title="repair", description="repair")
    run = RemoteAgentRun.objects.create(workstation=station, defect=defect, owner=other, identity_key=identity_key(station), status="running", expires_at=timezone.now()+timedelta(minutes=1))
    row = RemoteCommand.objects.create(workstation=station, run=run, payload={"kind":"run"}, status="pending", expires_at=run.expires_at)
    membership.is_active = False; membership.save()
    response = heartbeat(edge)
    assert response.status_code == 200
    assert str(row.id) not in {command["id"] for command in response.data["commands"]}
    run.refresh_from_db(); row.refresh_from_db()
    assert run.status == "failed" and row.status == "expired"


def test_agent_completed_tools_append_safe_process_events_once(remote):
    from plane.quality.models import Defect, DefectEvent
    from plane.quality.remote_models import RemoteAgentRun
    from plane.quality.remote_diagnostics import identity_key
    client, edge, device, project = remote
    heartbeat(edge)
    station = RemoteWorkstation.objects.get(pk=device)
    station.capabilities = {"agent_context": {"inspect_argv": ["/usr/bin/inspect-simulation"]}}
    station.save()
    defect = Defect.objects.create(project=project, title="process", description="process")
    run = RemoteAgentRun.objects.create(workstation=station, defect=defect, owner=station.agent.owner,
        identity_key=identity_key(station), status="running", expires_at=timezone.now()+timedelta(minutes=1))
    row = RemoteCommand.objects.create(workstation=station, run=run, payload={"kind":"run", "argv":["/usr/bin/inspect-simulation"]}, status="delivered", expires_at=run.expires_at)
    result = {"id":str(row.id), "ok":True, "exit_code":0, "stdout":"private-output-not-for-timeline"}
    assert heartbeat(edge, results=[result]).status_code == 200
    assert heartbeat(edge, results=[result]).status_code == 200
    events = list(DefectEvent.objects.filter(defect=defect))
    assert len(events) == 1
    assert "Agent 现场排查" in events[0].note and "完成" in events[0].note
    assert "private-output" not in events[0].note
    assert events[0].status == defect.status and events[0].previous_status == defect.status


def test_file_requests_require_owner_identity_and_preserve_binary_result(remote,create_user,workspace):
    from plane.quality.remote_files import RemoteFiles
    from plane.quality.remote_models import RemoteFileRequest
    from plane.db.models import User
    client,edge,device,project=remote
    heartbeat(edge,identity={'username':'caozuo1','hostname':'operator195','boot_id':'boot1','capabilities':{'file_browser':{'ready':True}}})
    created=client.post(BASE+'files/',{'device_id':device,'action':'list','target':'robot','path':''},format='json')
    assert created.status_code==201,created.content
    assert client.post(BASE+'files/',{'device_id':device,'action':'upload','target':'operator'},format='json').status_code==400
    job=RemoteFileRequest.objects.get(pk=created.data['id'])
    dispatched=heartbeat(edge).data['commands'];assert dispatched[0]['kind']=='file_browser'
    heartbeat(edge,results=[{'id':str(job.command_id),'ok':True,'exit_code':0,'file_result':{'entries':[{'name':'a.bin','kind':'file'}]}}])
    response=client.get(BASE+'files/'+str(job.id)+'/')
    assert response.data['result']['entries'][0]['name']=='a.bin'
    other=User.objects.create(email='fileother@example.test',username='fileother');ProjectMember.objects.create(project=project,member=other,role=20)
    other_client=APIClient();other_client.force_authenticate(other)
    assert other_client.get(BASE+'files/'+str(job.id)+'/').status_code==404

    assert heartbeat(edge,identity={'username':'caozuo1','hostname':'operator195','boot_id':'boot2'}).status_code==200
    assert client.get(BASE+'files/'+str(job.id)+'/').status_code==409


def test_readonly_run_mode_rejects_mutation_even_if_model_labels_inspection(remote):
    import hashlib
    from plane.quality.models import Defect
    from plane.quality.remote_models import RemoteAgentRun
    from plane.quality.remote_diagnostics import identity_key
    client,edge,device,project=remote;heartbeat(edge)
    station=RemoteWorkstation.objects.get(pk=device)
    station.capabilities={'agent_context':{'repair_allowed':True,'repair_argv':['/fixed-repair','--sha'],'editable_files':['config.json']}};station.save()
    defect=Defect.objects.create(project=project,title='readonly',description='readonly')
    token='rr_synthetic-readonly-mode'
    run=RemoteAgentRun.objects.create(workstation=station,defect=defect,owner=station.agent.owner,mode='diagnose',identity_key=identity_key(station),status='running',tool_credential_hash=hashlib.sha256(token.encode()).hexdigest(),expires_at=timezone.now()+timedelta(minutes=2))
    tool=APIClient();tool.credentials(HTTP_AUTHORIZATION='Bearer '+token)
    response=tool.post(BASE+'agent-tool/',{'operation':'patch_file','path':'config.json','content':'{}','expected_sha256':'a'*64,'purpose':'inspect'},format='json')
    assert response.status_code==403
    assert not RemoteCommand.objects.filter(run=run).exists()


def test_feedback_search_pagination_and_latest_run_status(remote):
    from plane.quality.models import Defect
    from plane.quality.remote_models import RemoteFeedbackBinding,RemoteAgentRun
    from plane.quality.remote_diagnostics import identity_key
    client,edge,device,project=remote;heartbeat(edge)
    station=RemoteWorkstation.objects.get(pk=device)
    for index in range(25):
        defect=Defect.objects.create(project=project,title=f'camera fault {index}',description='camera')
        RemoteFeedbackBinding.objects.create(workstation=station,defect=defect)
    repaired=RemoteAgentRun.objects.create(workstation=station,defect=defect,owner=station.agent.owner,identity_key=identity_key(station),status='completed',result={'repaired':True},expires_at=timezone.now()+timedelta(minutes=1))
    data=client.get(BASE+'feedback/',{'device_id':device,'per_page':10,'page':2,'q':'camera','state':'all'}).data
    assert data['count']==25 and len(data['results'])==10
    passed=client.get(BASE+'feedback/',{'device_id':device,'state':'repaired'}).data
    assert passed['count']==1 and passed['results'][0]['latest_status']=='repaired'
    assert client.get(BASE+'feedback/',{'device_id':device,'state':'needs_attention'}).data['count']==24


def test_upload_association_owner_and_terminal_agent_exclusion(remote):
    from plane.quality.models import Defect,DefectEvent
    from plane.quality.remote_models import RemoteUploadedFile,RemoteFeedbackBinding,RemoteAgentRun
    from plane.quality.remote_diagnostics import identity_key
    client,edge,device,project=remote
    heartbeat(edge,identity={'username':'caozuo1','hostname':'operator195','boot_id':'boot1','capabilities':{'file_browser':{'ready':True}}})
    station=RemoteWorkstation.objects.get(pk=device)
    defect=Defect.objects.create(project=project,title='upload patch',description='upload patch')
    RemoteFeedbackBinding.objects.create(workstation=station,defect=defect)
    response=client.post(BASE+'files/',{'device_id':device,'action':'upload_start','target':'robot','path':'patches','filename':'fix.zip','size':3,'sha256':'a'*64,'defect_id':str(defect.id)},format='json')
    assert response.status_code==201,response.content
    queued=heartbeat(edge).data['commands'][0]
    heartbeat(edge,results=[{'id':queued['id'],'ok':True,'exit_code':0,'file_result':{'ticket':'b'*32,'offset':0}}])
    upload=RemoteUploadedFile.objects.get(defect=defect)
    assert upload.ticket_hash and upload.status=='uploading'
    assert client.post(BASE,{'action':'open','device_id':device},format='json').status_code==409
    assert client.post(BASE+'agent-runs/',{'device_id':device,'defect_id':str(defect.id),'problem':'repair'},format='json').status_code==409
    finished=client.post(BASE+'files/',{'device_id':device,'action':'upload_finish','target':'robot','ticket':'b'*32},format='json')
    assert finished.status_code==201,finished.content
    command=heartbeat(edge).data['commands'][0]
    result={'uploaded':True,'path':'/home/robot/patches/fix.zip','sha256':'a'*64,'filename':'fix.zip','size':3}
    heartbeat(edge,results=[{'id':command['id'],'ok':True,'file_result':result}])
    heartbeat(edge,results=[{'id':command['id'],'ok':True,'file_result':result}])
    upload.refresh_from_db();assert upload.status=='uploaded'
    assert DefectEvent.objects.filter(defect=defect,note__startswith='现场文件上传：').count()==1
    assert client.post(BASE+'files/',{'device_id':device,'action':'upload_chunk','target':'operator','ticket':'b'*32,'offset':0,'data':'YWJj'},format='json').status_code==404
    run=RemoteAgentRun.objects.create(workstation=station,defect=defect,owner=station.agent.owner,identity_key=identity_key(station),status='running',expires_at=timezone.now()+timedelta(minutes=1))
    assert client.post(BASE,{'action':'open','device_id':device},format='json').status_code==409
    assert client.post(BASE+'files/',{'device_id':device,'action':'upload_start','target':'robot','path':'','filename':'new.txt','size':0,'sha256':'c'*64},format='json').status_code==409


def test_verify_only_success_is_preserved_as_healthy_without_claiming_mutation(remote):
    from plane.quality.models import Defect
    from plane.quality.remote_models import RemoteAgentRun,RemoteFeedbackBinding
    from plane.quality.remote_diagnostics import identity_key
    from plane.quality.remote_tasks import finish
    client,edge,device,project=remote;heartbeat(edge)
    station=RemoteWorkstation.objects.get(pk=device)
    defect=Defect.objects.create(project=project,title='verify',description='verify')
    RemoteFeedbackBinding.objects.create(workstation=station,defect=defect)
    run=RemoteAgentRun.objects.create(workstation=station,defect=defect,owner=station.agent.owner,mode='verify',identity_key=identity_key(station),status='running',expires_at=timezone.now()+timedelta(minutes=1))
    finish(run.id,{'summary':'current check passed','repaired':False,'outcome':'verified','verification_passed':True,'verification':['verified by fixed live command']})
    run.refresh_from_db();assert run.comment.content.startswith('Agent 远程处理：验证通过\n')
    listing=client.get(BASE+'feedback/',{'device_id':device,'state':'repaired'}).data
    assert listing['count']==1 and listing['results'][0]['latest_status']=='verified'
    assert client.get(BASE+'feedback/',{'device_id':device,'state':'needs_attention'}).data['count']==0


def test_original_diagnostic_can_reference_same_defect_field_repair_evidence(remote):
    from uuid import uuid4
    from plane.quality.models import Defect,DiagnosticJob
    from plane.quality.remote_models import RemoteAgentRun
    from plane.quality.remote_diagnostics import identity_key
    from plane.quality.remote_tasks import finish
    from plane.quality.diagnostic_context import diagnostic_context
    client,edge,device,project=remote;heartbeat(edge)
    station=RemoteWorkstation.objects.get(pk=device)
    defect=Defect.objects.create(project=project,title='report alignment',description='report alignment')
    run=RemoteAgentRun.objects.create(workstation=station,defect=defect,owner=station.agent.owner,identity_key=identity_key(station),status='running',expires_at=timezone.now()+timedelta(minutes=1))
    finish(run.id,{'summary':'repaired exact target','root_cause':'confirmed config','repaired':True,'repair_locations':[{'path':'/robot/config.json','line':4,'key':'enabled','before':False,'after':True}]})
    job=DiagnosticJob.objects.create(project=project,defect=defect,created_by=station.agent.owner,mode='llm',request_id=uuid4())
    ref=next(r for r in diagnostic_context(job) if r['reference']=='PLATFORM-FIELD-CHECK')
    assert 'repaired exact target' in ref['content'] and '/robot/config.json' in ref['content']
    foreign=Defect.objects.create(project=project,title='foreign',description='foreign')
    job.defect=foreign
    assert not any(r['reference']=='PLATFORM-FIELD-CHECK' for r in diagnostic_context(job))
