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
import ipaddress
import json
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
    if value['model_mode']=='real_model_e2e' and len(stations)!=1:
        raise ValueError('real model evidence must be a separate single-station run')
    return value


class Http:
    def __init__(self,url,isolation,headers=None,samples=None):
        self.url=url.rstrip('/');self.isolation=isolation;self.headers=headers or {};self.samples=samples if samples is not None else []

    def request(self,method,path,payload=None,expected=(200,),operation=None):
        if not path.startswith('/api/') or path.startswith('//'):raise ValueError('relative local API path required')
        started=time.perf_counter();started_at=time.time();status=0;ok=False
        headers={**self.headers,'Content-Type':'application/json'}
        request=urllib.request.Request(self.url+path,data=None if payload is None else json.dumps(payload).encode(),
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
    sid=None
    run_results=[];file_results=[];new_diagnostics=[];diagnostics_before={};diagnostics_after={}
    try:
        # Read-only isolation handshake occurs before the station exchange thread.
        owner.request('GET',BASE,operation='isolation_handshake')
        thread.start()
        if not ready.wait(10) or edge_errors:raise AssertionError('edge registration exchange failed')
        barrier=shared/'ready';barrier.mkdir(exist_ok=True)
        (barrier/str(index)).write_text(str(os.getpid()))
        wait_for_markers(barrier,len(manifest['stations']))
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
            with ThreadPoolExecutor(max_workers=len(participants)) as pool:
                file_results=list(pool.map(files_for_user,participants))
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
            modes=('diagnose','repair') if manifest['model_mode']=='controlled_stub' else ('repair',)
            for mode,defect in zip(modes,(station['defect_ids']*2)[:len(modes)]):
                run=owner.request('POST',BASE+'agent-runs/',{'device_id':station['device_id'],'defect_id':defect,'mode':mode,
                    'problem':'Isolated '+manifest['model_mode']+' mixed stress; inspect config.json and repair only when mode permits.'},expected=(201,),operation='agent_'+mode+'_submit')
                run_results.append({'id':run['id'],'mode':mode})
            owner.request('POST',BASE,{'action':'open','device_id':station['device_id']},expected=(409,),operation='busy_terminal_expected_409')
            owner.request('POST',BASE+'files/',{'device_id':station['device_id'],'target':'operator','action':'upload_start','path':'files',
                'filename':'busy.bin','size':1,'sha256':hashlib.sha256(b'x').hexdigest()},expected=(409,),operation='busy_upload_expected_409')
            if index%2==0 and len(manifest['stations'])>1:
                poll(lambda:bool(list(shared.glob('file-active-*'))),bool,60)
            owner.request('POST',terminal_path,{'action':'close'},operation='terminal_close')
            sid=None
            wait_started=time.time()
            for run in run_results:
                observed=[]
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
            'new_rules_diagnostics':new_diagnostics,
            'file_http_intervals':[{'started_at':sample['started_at'],'completed_at':sample['completed_at']}
                                   for sample in samples if sample['operation'].startswith('file_')],
            'run_observations':[{'id':row['id'],'mode':row['mode'],'observations':row.get('observations',[]),
                                 'model_started_at':row.get('result',{}).get('controlled_stub_started_at'),
                                 'model_completed_at':row.get('result',{}).get('controlled_stub_completed_at')} for row in run_results],
            'runs':[{'id':row['id'],'mode':row['mode'],'status':row.get('status')} for row in run_results],
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
            'operation_count':len(samples),'operations':summarize(samples),'stations':results,
            'p50_ms':percentile([row['elapsed_ms'] for row in samples],.5),'p95_ms':percentile([row['elapsed_ms'] for row in samples],.95),
            'ok':all(row['ok'] for row in results),'mixed_overlap':mixed_overlap(results)}
    report['distinct_station_pids']=len({row['pid'] for row in results})
    if report['distinct_station_pids']!=len(results):report['ok']=False
    fd=os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream:json.dump(report,stream,indent=2);stream.flush();os.fsync(stream.fileno())
    print(json.dumps({'report':args.output,'ok':report['ok'],'stations':len(results),'operations':len(samples)}),flush=True)
    raise SystemExit(0 if report['ok'] else 1)


if __name__=='__main__':main()
