#!/usr/bin/env python3
"""Isolated real platform HTTP + Engine mixed test. Credentials enter via stdin only.

Standard library only; use Ubuntu22 Docker with a writable Documents/tmp/artifacts
mount, the code read-only, and isolated central server reachable. The controller
must pipe a memory-built fixture to --manifest -; never put cookies/tokens in argv
or persistent JSON. Requires real users/stations/feedback seeded by the fixture,
the X-Remote-Stress-Isolation response marker and a functioning task worker.
controlled_stub bulk and single-station real_model_e2e must be separate reports.
"""

import argparse
import base64
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import hashlib
import hmac
import ipaddress
import json
import math
import multiprocessing
import os
from pathlib import Path
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime

from connector import Engine, Policy, identity, NoRedirect
from stress_harness import summarize, percentile

BASE='/api/quality-auth/remote-diagnostics/'


class ApiError(RuntimeError):
    def __init__(self,status):
        self.status=status
        super().__init__('unexpected HTTP status '+str(status))


class DiagnosticFailed(AssertionError):
    def __init__(self,result):
        self.result=result
        super().__init__('new rules diagnostic did not complete: '+str(result['status']))


def validate_manifest(value):
    if not isinstance(value,dict) or value.get('test_environment') is not True:
        raise ValueError('explicit isolated test environment required')
    parsed=urllib.parse.urlsplit(value.get('base_url',''))
    address=ipaddress.ip_address(parsed.hostname)
    if (parsed.scheme not in ('http','https') or not address.is_private or address.is_unspecified
            or address.is_multicast or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ('','/')):
        raise ValueError('only literal isolated loopback/private platform root URLs are permitted')
    if not isinstance(value.get('isolation_id'),str) or not 8<=len(value['isolation_id'])<=100:
        raise ValueError('isolation_id required')
    if value.get('model_mode') not in ('controlled_stub','real_model_e2e'):
        raise ValueError('explicit model_mode required')
    if type(value.get('full_job_lifecycle',False)) is not bool:
        raise ValueError('full_job_lifecycle must be boolean')
    if type(value.get('terminal_concurrency_probe',False)) is not bool:
        raise ValueError('terminal_concurrency_probe must be boolean')
    capacity=value.get('expected_worker_concurrency')
    if capacity is not None and (type(capacity) is not int or not 1<=capacity<=16):
        raise ValueError('expected worker concurrency must be 1..16')
    users=value.get('users',[]);stations=value.get('stations',[])
    if not isinstance(users,list) or not 1<=len(users)<=16 or not isinstance(stations,list) or not 1<=len(stations)<=16:
        raise ValueError('1..16 users and stations required')
    identifiers={user['id'] for user in users}
    if len(identifiers)!=len(users) or any(not isinstance(user.get('headers'),dict) for user in users):
        raise ValueError('distinct users with authentication headers required')
    devices={row['device_id'] for row in stations}
    if len(devices)!=len(stations):raise ValueError('distinct device registrations required')
    for row in stations:
        uuid.UUID(str(row['device_id']))
        if (row.get('owner_user_id') not in identifiers or not isinstance(row.get('defect_ids'),list)
                or len(set(row['defect_ids']))<2
                or not isinstance(row.get('token'),str) or not row['token'].startswith('rw_')
                or not set(row.get('allowed_user_ids',[])).issubset(identifiers)
                or 'initial_config' not in row or 'expected_repair_config' not in row):
            raise ValueError('invalid isolated station fixture')
        for path in row.get('diagnostic_paths',[])+row.get('diagnostic_create_paths',[]):
            if not isinstance(path,str) or not path.startswith('/api/') or path.startswith('//'):
                raise ValueError('diagnostic paths must be local API paths')
        if any('/quality/defects/' not in path or not path.endswith('/diagnostics/')
               for path in row.get('diagnostic_create_paths',[])):
            raise ValueError('diagnostic create paths must name a defect diagnostic collection')
        signed=row.get('signed_feedback_requests',[])
        if not isinstance(signed,list) or len(signed)>8 or any(
            not isinstance(item,dict) or item.get('path')!='/api/quality-auth/daq-reports/'
            or not isinstance(item.get('payload'),dict) or not isinstance(item.get('headers',{}),dict)
            or ('signing' not in item and 'headers' not in item)
            for item in signed):
            raise ValueError('bounded signed feedback fixture requests required')
        for item in signed:
            if 'signing' in item:validate_signing(item['signing'])
    if value['model_mode']=='real_model_e2e' and len(stations)!=1:
        raise ValueError('real model evidence must be a separate single-station run')
    return value


class Http:
    def __init__(self,url,isolation,headers=None,samples=None):
        self.url=url.rstrip('/');self.isolation=isolation;self.headers=headers or {};self.samples=samples if samples is not None else []

    def request(self,method,path,payload=None,expected=(200,),operation=None,signing=None):
        if not path.startswith('/api/') or path.startswith('//'):raise ValueError('relative local API path required')
        started=time.perf_counter();started_at=time.time();status=0;ok=False
        headers={**self.headers,'Content-Type':'application/json'}
        body=None if payload is None else json.dumps(payload).encode()
        if signing:
            # Sign the exact bytes handed to urllib, immediately before send;
            # fixture creation and queue delays must not age the timestamp.
            headers={key:value for key,value in headers.items() if not key.lower().startswith('x-issue-')}
            headers.update(fresh_signature(signing,method,path,body or b''))
        request=urllib.request.Request(self.url+path,data=body,
                                       headers=headers,method=method)
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect)
        try:
            try:response=opener.open(request,timeout=45)
            except urllib.error.HTTPError as exc:response=exc
            with response:
                status=response.code
                if response.headers.get('X-Remote-Stress-Isolation')!=self.isolation:
                    raise ValueError('isolated server response marker missing or mismatched')
                raw=response.read(2*1024*1024+1)
            if len(raw)>2*1024*1024:raise ValueError('platform response too large')
            if status not in expected:raise ApiError(status)
            ok=True
            return json.loads(raw) if raw else {}
        finally:
            self.samples.append({'operation':operation or method+' '+path.split('?')[0],
                                 'status':status,'ok':ok,'started_at':started_at,'completed_at':time.time(),
                                 'elapsed_ms':(time.perf_counter()-started)*1000})


def poll(function,accept,seconds=120):
    deadline=time.monotonic()+seconds
    while True:
        value=function()
        if accept(value):return value
        if time.monotonic()>deadline:raise TimeoutError('isolated platform operation deadline exceeded')
        time.sleep(.05)


def submit_diagnostic(client,path):
    created=client.request('POST',path,{'request_id':str(uuid.uuid4()),'mode':'rules'},expected=(201,),operation='diagnostic_create')
    job_id=str(uuid.UUID(created['id']))
    project_prefix=path.split('/defects/',1)[0]
    detail_path=project_prefix+'/diagnostics/'+job_id+'/'
    observations=[]
    def read():
        state=client.request('GET',detail_path,operation='diagnostic_poll')
        observations.append({'at':time.time(),'status':state.get('status')})
        return state
    completed=poll(read,lambda state:state.get('status') in ('completed','failed','cancelled','unconfigured'),180)
    result={'id':job_id,'mode':'rules','status':completed.get('status'),'observations':observations,
            'started_at':completed.get('started_at'),'completed_at':completed.get('completed_at')}
    if result['status']!='completed':raise DiagnosticFailed(result)
    return result


def submit_signed_feedback(client,request):
    options={'signing':request['signing']} if 'signing' in request else {}
    response=client.request('POST',request['path'],request['payload'],expected=(200,201),operation='signed_feedback_submit',**options)
    issue_id=response.get('issueId');issue_code=response.get('issueCode')
    try:uuid.UUID(str(issue_id))
    except (ValueError,TypeError,AttributeError):raise AssertionError('signed feedback returned no valid issueId')
    if not isinstance(issue_code,str) or not issue_code.strip():raise AssertionError('signed feedback returned no issueCode')
    # Persist only the returned identifier; no signatures, request payload or code.
    return {'issue_id':str(issue_id)}


def validate_signing(signing):
    if (not isinstance(signing,dict) or set(signing)!={'key_id','audience','secret','principal'}
            or any(not isinstance(signing.get(key),str) or not 1<=len(signing[key])<=4096
                   for key in ('key_id','audience','secret'))
            or not isinstance(signing.get('principal'),dict)):
        raise ValueError('invalid in-memory fixture signing material')
    principal=signing['principal']
    if type(principal.get('id')) is not int or principal['id']<=0 or len(json.dumps(principal))>2000:
        raise ValueError('invalid fixture principal')


def fresh_signature(signing,method,path,body):
    validate_signing(signing)
    encode=lambda value:base64.urlsafe_b64encode(value.encode()).decode().rstrip('=')
    principal=json.dumps(signing['principal'],ensure_ascii=True,separators=(',',':'))
    stamp=str(int(time.time()));nonce=secrets.token_urlsafe(24)
    digest='-' if method in ('GET','HEAD') else hashlib.sha256(body).hexdigest()
    canonical='\n'.join(['ISSUE-IDENTITY-V2',encode(signing['audience']),encode(signing['key_id']),stamp,
                         encode(nonce),method.upper(),encode(path),digest,encode(principal)])
    signature=base64.urlsafe_b64encode(hmac.new(signing['secret'].encode(),canonical.encode(),hashlib.sha256).digest()).decode().rstrip('=')
    return {'X-Issue-Identity-Version':'2','X-Issue-Key-Id':signing['key_id'],'X-Issue-Audience':signing['audience'],
            'X-Issue-Principal':principal,'X-Issue-Principal-Timestamp':stamp,'X-Issue-Principal-Nonce':nonce,
            'X-Issue-Content-SHA256':digest,'X-Issue-Principal-Signature':signature}


def fixture_root(output):
    output=Path(output).resolve()
    if '/Documents/tmp/artifacts/' not in str(output):raise ValueError('output must be inside Documents/tmp/artifacts')
    output.parent.mkdir(parents=True,exist_ok=True)
    root=output.parent/('platform-fixtures-'+uuid.uuid4().hex);root.mkdir(mode=0o700)
    return root


def wait_for_markers(folder, count, seconds=60):
    folder=Path(folder);folder.mkdir(exist_ok=True)
    deadline=time.monotonic()+seconds
    while len(list(folder.iterdir()))<count:
        if time.monotonic()>deadline:raise TimeoutError('not all isolated stations became ready')
        time.sleep(.01)


def epoch(value):
    if isinstance(value,str):
        try:
            parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
            return parsed.timestamp() if parsed.tzinfo is not None else None
        except (ValueError,OverflowError):return None
    return float(value) if type(value) in (int,float) and math.isfinite(value) and value>0 else None


def max_overlap(intervals):
    points=[]
    for start,end in intervals:
        if start is not None and end is not None and end>start:
            points.extend(((start,1),(end,-1)))
    if not points:return None
    active=peak=0
    for _at,delta in sorted(points):
        active+=delta;peak=max(peak,active)
    return peak


def operation_statistics(samples):
    report=summarize(samples)
    for name,summary in report.items():
        rows=[row for row in samples if row['operation']==name]
        summary['max_concurrent_requests']=max_overlap([(epoch(row.get('started_at')),epoch(row.get('completed_at'))) for row in rows])
        statuses={}
        for row in rows:
            if type(row.get('status')) is int:
                status=str(row['status']);statuses[status]=statuses.get(status,0)+1
        if statuses:summary['http_status_counts']=statuses
        summary['expected_conflicts']=sum(row.get('status')==409 and row['ok'] for row in rows)
    return report


def job_lifecycle_summary(stations,capacity=None):
    # RemoteAgentRun.id identifies one worker-owned lifecycle. Its internal
    # model/tool/diagnose/repair/verify stages never create extra jobs here.
    unique={};duplicates=0
    for station in stations:
        for job in station.get('jobs',[]):
            key=job['id']
            if key in unique:duplicates+=1
            else:unique[key]=job
    intervals=[];missing=[];exact_wait=[];observed_wait=[];queued=0;observed=0
    for key,job in unique.items():
        start=epoch(job.get('worker_started_at'));end=epoch(job.get('worker_completed_at'))
        if start is not None and end is not None and end>start:intervals.append((start,end))
        else:missing.append(key)
        queued_at=epoch(job.get('queued_at'))
        if start is not None and queued_at is not None and start>=queued_at:exact_wait.append(start-queued_at)
        observations=job.get('observations',[])
        if observations:
            observed+=1
            queue_times=[epoch(row.get('at')) for row in observations if row.get('status')=='queued']
            run_times=[epoch(row.get('at')) for row in observations if row.get('status')=='running']
            queue_times=[value for value in queue_times if value is not None]
            run_times=[value for value in run_times if value is not None]
            if queue_times:queued+=1
            if queue_times and run_times and min(run_times)>=min(queue_times):
                observed_wait.append(min(run_times)-min(queue_times))
    peak=max_overlap(intervals)
    result={'job_count':len(unique),'completed_jobs':sum(row.get('status')=='completed' for row in unique.values()),
            'counting_unit':'one RemoteAgentRun.id across its entire worker lifecycle; internal stages excluded',
            'worker_timed_jobs':len(intervals),'missing_worker_timing_job_ids':missing,'duplicate_job_records':duplicates,
            'max_concurrent_running':peak,'queued_jobs_observed':queued if observed else None,
            'expected_worker_concurrency':capacity,
            'capacity_exceeded':peak>capacity if peak is not None and capacity is not None else None,
            'capacity_peak_reached':peak==capacity if peak is not None and capacity is not None else None,
            'capacity_verified':bool(capacity is not None and unique and not missing and not duplicates and peak==capacity)}
    queues={row.get('worker_queue') for row in unique.values() if isinstance(row.get('worker_queue'),str)}
    if queues:result['observed_worker_queues']=sorted(queues)
    def waiting(values):return {'samples':len(values),'p50':percentile(values,.5),'p95':percentile(values,.95),'max':max(values)}
    if exact_wait:result['queue_wait_seconds']={**waiting(exact_wait),'source':'server queued_at to worker_started_at'}
    if observed_wait:result['observed_queue_to_running_seconds']={**waiting(observed_wait),'source':'client polling observations; approximate, includes observation delay'}
    return result


def terminal_probe_summary(stations):
    probes=[row['terminal_probe'] for row in stations if row.get('terminal_probe')]
    # Only count intervals after actual PTY marker verification and before
    # issuing close; HTTP session creation alone is not a working terminal.
    intervals=[(epoch(row.get('probe_start')),epoch(row.get('probe_end'))) for row in probes]
    complete=all(start is not None and end is not None and end>start for start,end in intervals)
    distinct_users=len({row.get('owner_user_id') for row in probes})
    distinct_sessions=len({row.get('session_id') for row in probes})
    distinct_identities=len({json.dumps(row.get('identity'),sort_keys=True) for row in probes})
    common_start=max((start for start,_ in intervals if start is not None),default=None)
    common_end=min((end for _,end in intervals if end is not None),default=None)
    overlap=common_end-common_start if common_start is not None and common_end is not None else None
    peak=max_overlap(intervals)
    count=len(stations)
    return {'requested_stations':count,'observed_probes':len(probes),'distinct_users':distinct_users,
            'distinct_sessions':distinct_sessions,'distinct_station_identities':distinct_identities,
            'max_concurrent_open':peak,
            'common_open_interval':{'started_at':common_start,'completed_at':common_end,'seconds':overlap},
            'interval_source':'client-observed real PTY marker verified through all-owner confirmation, before close',
            'verified':bool(count and len(probes)==count and complete and peak==count and overlap and overlap>0
                            and distinct_users==count and distinct_sessions==count and distinct_identities==count
                            and all(row.get('marker_verified') is True for row in probes))}


def mixed_overlap(stations):
    pairs=[];model_pairs=[]
    for left in stations:
        files=[row for row in left.get('phase_intervals',[]) if row['phase']=='files']
        for right in stations:
            if left['device_id']==right['device_id']:continue
            for file in files:
                for run in right.get('phase_intervals',[]):
                    if run['phase']!='agent_wait':continue
                    overlap=min(file['completed_at'],run['completed_at'])-max(file['started_at'],run['started_at'])
                    if overlap>0:
                        pairs.append({'files_station':left['device_id'],'agent_station':right['device_id'],
                                      'overlap_seconds':overlap})
            for transfer in left.get('file_http_intervals',[]):
                for run in right.get('run_observations',[]):
                    start=run.get('model_started_at');end=run.get('model_completed_at')
                    if isinstance(start,(int,float)) and isinstance(end,(int,float)):
                        duration=min(transfer['completed_at'],end)-max(transfer['started_at'],start)
                        if duration>0:model_pairs.append({'files_station':left['device_id'],'agent_station':right['device_id'],
                                                          'overlap_seconds':duration})
    return {'cross_station_files_agent_wait_overlap':bool(pairs),'phase_pairs':pairs,
            'cross_station_file_http_model_execution_overlap':bool(model_pairs),'model_execution_pairs':model_pairs,
            'evidence_boundary':'phase intervals include polling; model execution timing is reported separately'}


def station_job(job):
    manifest,station,root=job
    root=Path(root)/str(station['device_id']);root.mkdir(mode=0o700)
    os.environ.update(HOME=str(root),FIELD_REMOTE_TOKEN=station['token'])
    approved=root/'approved';approved.mkdir(mode=0o700)
    files=root/'files';files.mkdir(mode=0o700)
    config=approved/'config.json';config.write_text(json.dumps(station['initial_config']))
    payload=(str(station['device_id']).encode()+secrets.token_bytes(256*1024))
    (files/'seed.bin').write_bytes(payload);seed_digest=hashlib.sha256(payload).hexdigest()
    policy=Policy({'approved_root':str(approved),'allowed_commands':[['/usr/bin/printf']],
                   'editable_files':['config.json'],'file_browser_enabled':True})
    engine=Engine(policy,'127.0.0.1');samples=[];edge_errors=[];errors=[];phase_intervals=[]
    index=station.get('_index',0);shared=Path(root).parent
    user_map={user['id']:user for user in manifest['users']}
    def user(identifier):
        client=Http(manifest['base_url'],manifest['isolation_id'],user_map[identifier]['headers'],samples)
        client.fixture_user_id=identifier
        return client
    owner=user(station['owner_user_id'])
    edge=Http(manifest['base_url'],manifest['isolation_id'],{'Authorization':'Bearer '+station['token']},samples)
    operator=identity(policy)
    operator.update(hostname='stress-'+str(station['device_id']),boot_id=uuid.uuid4().hex)
    stopped=threading.Event();ready=threading.Event();command_counts={}

    def loop():
        try:
            while not stopped.is_set():
                engine.pump();outputs=engine.outputs[:100];results=engine.results[:100]
                response=edge.request('POST',BASE+'exchange/',{'identity':operator,'outputs':outputs,'results':results},operation='edge_exchange')
                commands=response.get('commands')
                if not isinstance(commands,list) or len(commands)>100:raise ValueError('invalid exchange commands')
                engine.acknowledge(len(outputs),len(results));engine.last_exchange=time.monotonic();ready.set()
                for command in commands:
                    kind=command.get('kind','unknown');command_counts[kind]=command_counts.get(kind,0)+1
                    if kind=='patch_file':(shared/('repair-active-'+str(index))).touch()
                    engine.accept(command)
                stopped.wait(.03)
        except Exception as exc:
            edge_errors.append({'operation':'exchange','error_class':type(exc).__name__,'detail':str(exc)[:100]})
            ready.set()
        finally:engine.close()

    file_jobs=[]
    def file(client,action,**kwargs):
        job=client.request('POST',BASE+'files/',{'device_id':station['device_id'],'target':'operator','action':action,**kwargs},expected=(201,),operation='file_'+action+'_submit')
        file_jobs.append((client.fixture_user_id,job['id']))
        completed=poll(lambda:client.request('GET',BASE+'files/'+job['id']+'/',operation='file_'+action+'_poll'),lambda value:value.get('status') in ('done','expired'))
        if completed.get('status')!='done' or completed.get('error'):raise AssertionError('file command did not finish successfully')
        return completed['result']

    def files_for_user(identifier):
        client=user(identifier)
        listing=file(client,'list',path='files')
        if not any(row['name']=='seed.bin' for row in listing['entries']):raise AssertionError('station home listing mismatch')
        prepared=file(client,'prepare',path='files/seed.bin');buffer=bytearray()
        while len(buffer)<prepared['size']:
            part=file(client,'chunk',ticket=prepared['ticket'],offset=len(buffer))
            chunk=base64.b64decode(part['data'])
            if not chunk:raise AssertionError('download truncated')
            buffer.extend(chunk)
            if (len(buffer)==len(chunk) and index%2==1 and manifest['model_mode']=='controlled_stub'
                    and len(manifest['stations'])>1):
                # Hold this real transfer open until a different cohort's actual
                # patch command reaches Engine, then continue HTTP traffic.
                deadline=time.monotonic()+90
                while not list(shared.glob('repair-active-*')):
                    # Keep real HTTP file traffic active while the other cohort
                    # leaves terminal mode and executes its repair gateway calls.
                    probe=file(client,'chunk',ticket=prepared['ticket'],offset=0)
                    if base64.b64decode(probe['data'])!=bytes(buffer):raise AssertionError('transfer retry integrity mismatch')
                    if time.monotonic()>deadline:raise TimeoutError('no actual cross-station repair reached Engine')
        if hashlib.sha256(buffer).hexdigest()!=seed_digest or prepared['sha256']!=seed_digest:
            raise AssertionError('crossstation file integrity mismatch')
        filename='user-'+hashlib.sha256(str(identifier).encode()).hexdigest()[:12]+'.bin'
        ticket=file(client,'upload_start',path='files',filename=filename,size=len(payload),sha256=seed_digest)['ticket']
        for offset in range(0,len(payload),96*1024):
            file(client,'upload_chunk',ticket=ticket,offset=offset,data=base64.b64encode(payload[offset:offset+96*1024]).decode())
        uploaded=file(client,'upload_finish',ticket=ticket)
        if uploaded['sha256']!=seed_digest or hashlib.sha256((files/filename).read_bytes()).hexdigest()!=seed_digest:
            raise AssertionError('upload integrity mismatch')
        return {'user_id':identifier,'download_sha_matches':True,'upload_sha_matches':True}

    thread=threading.Thread(target=loop,daemon=True)
    sid=None;terminal_probe=None
    run_results=[];file_results=[];new_diagnostics=[];new_feedback=[];diagnostics_before={};diagnostics_after={}
    try:
        # Read-only isolation handshake occurs before the station exchange thread.
        owner.request('GET',BASE,operation='isolation_handshake')
        thread.start()
        if not ready.wait(10) or edge_errors:raise AssertionError('edge registration exchange failed')
        barrier=shared/'ready';barrier.mkdir(exist_ok=True)
        (barrier/str(index)).write_text(str(os.getpid()))
        wait_for_markers(barrier,len(manifest['stations']))
        if manifest.get('terminal_concurrency_probe'):
            opened=owner.request('POST',BASE,{'action':'open','device_id':station['device_id'],'cols':100,'rows':30},
                                 expected=(201,),operation='terminal_probe_open')
            sid=opened['id'];terminal_path=BASE+'sessions/'+sid+'/'
            terminal_probe={'owner_user_id':station['owner_user_id'],'session_id':sid,'opened_at':time.time(),
                            'marker_verified':False,'identity':None}
            suffix=uuid.uuid4().hex;marker='ALL_STATIONS_PTY_'+suffix
            owner.request('POST',terminal_path,{'action':'input','data':base64.b64encode(
                ("printf 'ALL_STATIONS_PTY_%s\\n' '"+suffix+"'\n").encode()).decode()},operation='terminal_probe_input')
            cursor=0;probe_output=bytearray()
            def probe_read():
                nonlocal cursor
                result=owner.request('GET',terminal_path+'?after='+str(cursor),operation='terminal_probe_read')
                cursor=result['cursor'];terminal_probe['last_read_at']=time.time()
                for event in result['events']:probe_output.extend(base64.b64decode(event['data']))
                if result.get('status')=='closed':raise AssertionError('concurrency probe terminal closed prematurely')
                if result.get('identity'):terminal_probe['server_identity']=result['identity']
                for field in ('created_at','last_read_at','expires_at'):
                    if result.get(field) is not None:terminal_probe['server_'+field]=result[field]
                return marker.encode() in probe_output
            poll(probe_read,bool,20)
            terminal_probe['marker_verified']=True;terminal_probe['probe_start']=time.time()
            terminal_probe['identity']={'username':operator['username'],'hostname':operator['hostname'],'boot_id':operator['boot_id']}
            for identifier in station.get('allowed_user_ids',[]):
                if identifier!=station['owner_user_id']:
                    user(identifier).request('GET',terminal_path,expected=(403,404),operation='terminal_probe_crossowner_expected_deny')
            all_ready=shared/'terminal-all-ready';all_ready.mkdir(exist_ok=True)
            (all_ready/str(index)).write_text(sid)
            deadline=time.monotonic()+60
            while len(list(all_ready.iterdir()))<len(manifest['stations']):
                probe_read()
                if time.monotonic()>deadline:raise TimeoutError('not all real PTY markers became ready')
                time.sleep(.05)
            # A second barrier confirms every owner observed the all-open state.
            all_observed=shared/'terminal-all-observed';all_observed.mkdir(exist_ok=True)
            probe_read();(all_observed/str(index)).touch()
            deadline=time.monotonic()+60
            while len(list(all_observed.iterdir()))<len(manifest['stations']):
                probe_read()
                if time.monotonic()>deadline:raise TimeoutError('not all owners confirmed the all-open state')
                time.sleep(.05)
            terminal_probe['probe_end']=time.time()
            owner.request('POST',terminal_path,{'action':'close'},operation='terminal_probe_close')
            terminal_probe['closed_at']=time.time();sid=None
            # Keep the workload phase out of this distinct capacity probe.
            all_closed=shared/'terminal-all-closed';all_closed.mkdir(exist_ok=True)
            (all_closed/str(index)).touch();wait_for_markers(all_closed,len(manifest['stations']))
        for path in station.get('diagnostic_paths',[]):
            diagnostics_before[path]=hashlib.sha256(json.dumps(owner.request('GET',path,operation='original_diagnostic_before'),sort_keys=True).encode()).hexdigest()
        feedback=owner.request('GET',BASE+'feedback/?'+urllib.parse.urlencode({'device_id':station['device_id']}),operation='feedback_list')
        if not set(station['defect_ids']).issubset({item['id'] for item in feedback['results']}):raise AssertionError('station feedback missing or crossed')
        participants=station.get('allowed_user_ids') or [station['owner_user_id']]
        def file_phase():
            nonlocal file_results
            phase_started=time.time()
            (shared/('file-active-'+str(index))).touch()
            for path in station.get('diagnostic_create_paths',[]):
                try:new_diagnostics.append(submit_diagnostic(owner,path))
                except DiagnosticFailed as exc:
                    new_diagnostics.append(exc.result)
                    raise
            signed=station.get('signed_feedback_requests',[])
            with ThreadPoolExecutor(max_workers=len(participants)+len(signed)) as pool:
                file_futures=[pool.submit(files_for_user,identifier) for identifier in participants]
                feedback_futures=[pool.submit(submit_signed_feedback,
                    Http(manifest['base_url'],manifest['isolation_id'],request.get('headers',{}),samples),request)
                    for request in signed]
                file_results=[future.result() for future in file_futures]
                new_feedback.extend(future.result() for future in feedback_futures)
            if new_feedback:
                listed=owner.request('GET',BASE+'feedback/?'+urllib.parse.urlencode({'device_id':station['device_id'],'per_page':50}),operation='signed_feedback_station_binding_verify')
                present={row['id'] for row in listed['results']}
                if not {row['issue_id'] for row in new_feedback}.issubset(present):
                    raise AssertionError('signed feedback belongs to a different station or is missing')
            for identifier in participants:
                foreign=next((job for owner_id,job in file_jobs if owner_id!=identifier),None)
                if foreign:
                    user(identifier).request('GET',BASE+'files/'+foreign+'/',expected=(403,404),operation='file_crossowner_expected_deny')
            phase_intervals.append({'phase':'files','started_at':phase_started,'completed_at':time.time()})

        def agent_phase():
            nonlocal sid
            terminal=owner.request('POST',BASE,{'action':'open','device_id':station['device_id'],'cols':100,'rows':30},expected=(201,),operation='terminal_open')
            sid=terminal['id'];terminal_path=BASE+'sessions/'+sid+'/'
            suffix=uuid.uuid4().hex;marker='HTTP_PTY_'+suffix
            owner.request('POST',terminal_path,{'action':'input','data':base64.b64encode(("printf 'HTTP_PTY_%s\\n' '"+suffix+"'\n").encode()).decode()},operation='terminal_input')
            owner.request('POST',terminal_path,{'action':'resize','cols':111,'rows':33},operation='terminal_resize')
            cursor=0;output=bytearray()
            def terminal_read():
                nonlocal cursor
                state=owner.request('GET',terminal_path+'?after='+str(cursor),operation='terminal_poll')
                cursor=state['cursor']
                for event in state['events']:output.extend(base64.b64decode(event['data']))
                return marker.encode() in output
            poll(terminal_read,bool,20)
            for identifier in participants:
                if identifier!=station['owner_user_id']:
                    user(identifier).request('GET',terminal_path,expected=(403,404),operation='terminal_crossowner_expected_deny')
            # New contract: queued work may be submitted while human terminal is busy.
            modes=(('diagnose','repair') if manifest['model_mode']=='controlled_stub'
                   and not manifest.get('full_job_lifecycle') else ('repair',))
            for mode,defect in zip(modes,(station['defect_ids']*2)[:len(modes)]):
                submitted_at=time.time()
                run=owner.request('POST',BASE+'agent-runs/',{'device_id':station['device_id'],'defect_id':defect,'mode':mode,
                    'problem':'Isolated '+manifest['model_mode']+' mixed stress; inspect config.json and repair only when mode permits.'},expected=(201,),operation='agent_'+mode+'_submit')
                run_results.append({'id':run['id'],'mode':mode,'observations':[{'at':submitted_at,'status':run.get('status')}],
                                    'queued_at':run.get('queued_at') or run.get('created_at')})
            owner.request('POST',BASE,{'action':'open','device_id':station['device_id']},expected=(409,),operation='busy_terminal_expected_409')
            owner.request('POST',BASE+'files/',{'device_id':station['device_id'],'target':'operator','action':'upload_start','path':'files',
                'filename':'busy.bin','size':1,'sha256':hashlib.sha256(b'x').hexdigest()},expected=(409,),operation='busy_upload_expected_409')
            if index%2==0 and len(manifest['stations'])>1:
                poll(lambda:bool(list(shared.glob('file-active-*'))),bool,60)
            owner.request('POST',terminal_path,{'action':'close'},operation='terminal_close')
            sid=None
            wait_started=time.time()
            for run in run_results:
                observed=run['observations']
                def read_run():
                    value=owner.request('GET',BASE+'agent-runs/'+run['id']+'/',operation='agent_'+run['mode']+'_poll')
                    observed.append({'at':time.time(),'status':value.get('status')})
                    return value
                state=poll(read_run,lambda value:value.get('status') in ('completed','failed'),180)
                run['observations']=observed
                run.update(status=state['status'],result=state.get('result',{}))
                if state['status']!='completed':raise AssertionError('queued agent work failed')
                if manifest['model_mode']=='controlled_stub' and state.get('result',{}).get('model_provider')!='controlled_stub':
                    raise AssertionError('bulk controlled model evidence is not explicitly marked')
            phase_intervals.append({'phase':'agent_wait','started_at':wait_started,'completed_at':time.time()})

        if index%2==0:
            agent_phase();file_phase()
        else:
            file_phase();agent_phase()
        if json.loads(config.read_text())!=station['expected_repair_config']:raise AssertionError('actual Engine patch did not match expected config')
        backups=list(approved.glob('config.json.backup-*'))
        if not backups:raise AssertionError('actual repair produced no atomic backup')
        for path in station.get('diagnostic_paths',[]):
            diagnostics_after[path]=hashlib.sha256(json.dumps(owner.request('GET',path,operation='original_diagnostic_after'),sort_keys=True).encode()).hexdigest()
        if diagnostics_before!=diagnostics_after:raise AssertionError('original diagnostics changed during repair')
    except Exception as exc:
        errors.append({'error_class':type(exc).__name__,'detail':str(exc)[:160]})
    finally:
        if sid:
            try:owner.request('POST',BASE+'sessions/'+sid+'/',{'action':'close'},expected=(200,403,404,409),operation='terminal_finally_close')
            except Exception:errors.append({'error_class':'CleanupError','detail':'terminal close failed'})
        stopped.set()
        if thread.ident:thread.join(50)
        else:engine.close()
        if thread.is_alive():errors.append({'error_class':'ThreadLeak','detail':'edge exchange did not stop'})
    return {'device_id':station['device_id'],'simulated_uid':os.getuid(),'pid':os.getpid(),
            'ok':not errors and not edge_errors,'errors':errors+edge_errors,'samples':samples,'command_counts':command_counts,
            'users':file_results,'phase_intervals':phase_intervals,
            'terminal_probe':terminal_probe,
            'new_rules_diagnostics':new_diagnostics,
            'signed_feedback_count':len(new_feedback),'signed_feedback_issue_ids':[row['issue_id'] for row in new_feedback],
            'file_http_intervals':[{'started_at':sample['started_at'],'completed_at':sample['completed_at']}
                                   for sample in samples if sample['operation'].startswith('file_')],
            'run_observations':[{'id':row['id'],'mode':row['mode'],'observations':row.get('observations',[]),
                                 'model_started_at':row.get('result',{}).get('controlled_stub_started_at'),
                                 'model_completed_at':row.get('result',{}).get('controlled_stub_completed_at')} for row in run_results],
            'runs':[{'id':row['id'],'mode':row['mode'],'status':row.get('status')} for row in run_results],
            'jobs':[{'id':row['id'],'mode':row['mode'],'status':row.get('status'),'observations':row.get('observations',[]),
                     'worker_started_at':row.get('result',{}).get('worker_started_at'),
                     'worker_completed_at':row.get('result',{}).get('worker_completed_at'),
                     'worker_queue':row.get('result',{}).get('worker_queue'),
                     'queued_at':row.get('result',{}).get('queued_at') or row.get('queued_at')} for row in run_results],
            'config_sha256':hashlib.sha256(config.read_bytes()).hexdigest(),
            'original_diagnostics_unchanged':bool(diagnostics_before) and diagnostics_before==diagnostics_after}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',choices=['-'],required=True,help='credentials are accepted from stdin memory only')
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    raw=sys.stdin.buffer.read(1024*1024+1)
    if len(raw)>1024*1024:parser.error('fixture too large')
    manifest=validate_manifest(json.loads(raw))
    root=fixture_root(args.output);started=time.time()
    with ProcessPoolExecutor(max_workers=len(manifest['stations']),mp_context=multiprocessing.get_context('spawn')) as pool:
        results=list(pool.map(station_job,[(manifest,{**row,'_index':index},str(root)) for index,row in enumerate(manifest['stations'])]))
    samples=[sample for row in results for sample in row.pop('samples')]
    report={'scope':'isolated real central HTTP plus actual edge Engine','model_mode':manifest['model_mode'],
            'physical_multi_host':False,'distinct_uid_tested':False,'users_are_fixture_http_sessions':True,
            'started_at':started,'completed_at':time.time(),'station_count':len(results),'user_count':len(manifest['users']),
            'operation_count':len(samples),'operations':operation_statistics(samples),'stations':results,
            'p50_ms':percentile([row['elapsed_ms'] for row in samples],.5),'p95_ms':percentile([row['elapsed_ms'] for row in samples],.95),
            'ok':all(row['ok'] for row in results),'mixed_overlap':mixed_overlap(results)}
    report['distinct_station_pids']=len({row['pid'] for row in results})
    report['full_job_lifecycle']=manifest.get('full_job_lifecycle',False)
    report['job_lifecycle']=job_lifecycle_summary(results,manifest.get('expected_worker_concurrency'))
    if manifest.get('terminal_concurrency_probe'):
        report['terminal_probe']=terminal_probe_summary(results)
        if not report['terminal_probe']['verified']:report['ok']=False
    if manifest.get('expected_worker_concurrency') is not None and not report['job_lifecycle']['capacity_verified']:
        report['ok']=False
    if report['distinct_station_pids']!=len(results):report['ok']=False
    fd=os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream:json.dump(report,stream,indent=2);stream.flush();os.fsync(stream.fileno())
    print(json.dumps({'report':args.output,'ok':report['ok'],'stations':len(results),'operations':len(samples)}),flush=True)
    raise SystemExit(0 if report['ok'] else 1)


if __name__=='__main__':main()
