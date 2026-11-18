#!/usr/bin/env python3
"""Edge-only real PTY/file stress in isolated per-process station namespaces.

Requires Linux/Python 3 standard library and /usr/bin/{python3,printf,sleep}.
Run inside the project's Ubuntu 22.04 Docker image as the operator UID, network
none, with this directory read-only and Documents/tmp/artifacts writable:
  python3 /field/stress_harness.py --levels 4,8,16 --iterations 10 \
      --payload-bytes 1048576 --output /.../Documents/tmp/artifacts/.../report.json
The output must be new. Fixtures remain as auditable nonsecret artifacts.
This is neither a central HTTP/model test nor a physical multi-host/UID test.
"""

import argparse
import base64
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import hashlib
import io
import json
import math
import multiprocessing
import os
from pathlib import Path
import platform
import secrets
import statistics
import tarfile
import time
import uuid

from connector import Engine, Policy
from file_browser import CHUNK, local_request


def percentile(values, percent):
    values = sorted(values)
    return values[min(len(values) - 1, max(0, math.ceil(len(values) * percent)-1))] if values else None


def summarize(samples):
    groups = {}
    for sample in samples:
        groups.setdefault(sample['operation'], []).append(sample)
    return {name: {'count': len(rows), 'errors': sum(not row['ok'] for row in rows),
                   'p50_ms': round(statistics.median(row['elapsed_ms'] for row in rows), 3),
                   'p95_ms': round(percentile([row['elapsed_ms'] for row in rows], .95), 3)}
            for name, rows in sorted(groups.items())}


def station(job):
    root, station_number, iterations, payload_bytes = job
    root = Path(root)
    home = root / f'station-{station_number:03}'
    home.mkdir(mode=0o700)
    approved, files, spool = home / 'approved', home / 'files', home / '.cache' / 'transfers'
    approved.mkdir(mode=0o700); files.mkdir(mode=0o700)
    # Credentials are distinct in memory, unused by this edge-only transport
    # harness, never written or returned. All processes retain the real UID.
    os.environ.update(HOME=str(home), FIELD_REMOTE_TOKEN='rw_' + secrets.token_urlsafe(30))
    tag = f'station_{station_number:03}_{uuid.uuid4().hex}'
    policy = Policy({'approved_root': str(approved), 'editable_files': ['config.json'],
                     'allowed_commands': [['/usr/bin/printf'], ['/usr/bin/sleep']]})
    engine = Engine(policy, '127.0.0.1')
    # Every worker holds one station until all distinct processes are ready.
    # This prevents short jobs from being serially reused by fewer processes.
    barrier = root/'ready'
    barrier.mkdir(exist_ok=True)
    (barrier/str(station_number)).write_text(str(os.getpid()))
    expected_workers=int(root.name.split('-')[-1])
    deadline=time.monotonic()+20
    while len(list(barrier.iterdir())) < expected_workers:
        if time.monotonic()>deadline:
            engine.close()
            return {'station':station_number,'pid':os.getpid(),'uid':os.getuid(),'home':str(home),'samples':[],
                    'unexpected':[{'operation':'barrier','error_class':'Timeout','detail':'not all station processes became ready'}],
                    'counters':{},'ok':False}
        time.sleep(.005)
    samples, unexpected, counters = [], [], {'sha_checks': 0, 'crossstation_rejections': 0,
                                             'terminal_bytes': 0, 'uploads': 0, 'downloads': 0}
    groups_to_reap = []

    def measured(name, function):
        started = time.perf_counter()
        try:
            value = function()
            samples.append({'operation': name, 'ok': True, 'elapsed_ms': (time.perf_counter()-started)*1000})
            return value
        except Exception as exc:
            samples.append({'operation': name, 'ok': False, 'elapsed_ms': (time.perf_counter()-started)*1000})
            unexpected.append({'operation': name, 'error_class': type(exc).__name__, 'detail': str(exc)[:160]})
            raise

    def command(kind, **kwargs):
        return {'id': uuid.uuid4().hex, 'expires_at': time.time()+45, 'kind': kind, **kwargs}

    def accept(row, expect=True):
        engine.accept(row)
        deadline = time.monotonic()+12
        while not any(item['id'] == row['id'] for item in engine.results):
            engine.pump()
            if time.monotonic() > deadline: raise AssertionError('command result deadline exceeded')
            time.sleep(.005)
        result = next(item for item in engine.results if item['id'] == row['id'])
        if result['ok'] is not expect: raise AssertionError('unexpected command status: '+row['kind'])
        return result

    def drain():
        engine.pump()
        raw = b''.join(base64.b64decode(item['data']) for item in engine.outputs if item['kind']=='data')
        counters['terminal_bytes'] += len(raw)
        engine.acknowledge(len(engine.outputs), len(engine.results))
        return raw

    def file_call(action, **kwargs):
        return local_request(files, spool, {'action': action, **kwargs})

    def transfer(iteration):
        payload = tag.encode()+b'\x00\xff'+secrets.token_bytes(payload_bytes)
        digest = hashlib.sha256(payload).hexdigest()
        filename = f'payload-{iteration}.bin'
        ticket = measured('upload_start', lambda: file_call('upload_start', path='', filename=filename,
                                                           size=len(payload), sha256=digest))['ticket']
        for offset in range(0, len(payload), CHUNK):
            data = base64.b64encode(payload[offset:offset+CHUNK]).decode()
            result = measured('upload_chunk', lambda: file_call('upload_chunk', ticket=ticket, offset=offset, data=data))
            if result['next_offset'] != min(offset+CHUNK, len(payload)): raise AssertionError('upload offset mismatch')
            if offset == 0:
                measured('upload_retry_dedup', lambda: file_call('upload_chunk', ticket=ticket, offset=offset, data=data))
        result = measured('upload_finish', lambda: file_call('upload_finish', ticket=ticket))
        if result['sha256'] != digest or hashlib.sha256((files/filename).read_bytes()).hexdigest()!=digest:
            raise AssertionError('upload crossstation integrity mismatch')
        counters['sha_checks'] += 1; counters['uploads'] += 1
        prepared = measured('download_prepare', lambda: file_call('prepare', path=filename))
        received = bytearray()
        while len(received) < prepared['size']:
            part = measured('download_chunk', lambda: file_call('chunk', ticket=prepared['ticket'], offset=len(received)))
            chunk = base64.b64decode(part['data'])
            if not chunk: raise AssertionError('empty download chunk before EOF')
            received.extend(chunk)
        if hashlib.sha256(received).hexdigest()!=digest or prepared['sha256']!=digest or not received.startswith(tag.encode()):
            raise AssertionError('download crossstation integrity mismatch')
        counters['sha_checks'] += 1; counters['downloads'] += 1
        # A distinct station's cache cannot resolve this station's raw ticket.
        other = home/'other-station-cache'
        try: local_request(files, other, {'action':'chunk','ticket':prepared['ticket'],'offset':0})
        except FileNotFoundError: counters['crossstation_rejections'] += 1
        else: raise AssertionError('crossstation download ticket leaked')
        measured('upload_finish_retry', lambda: file_call('upload_finish', ticket=ticket))
        return digest

    try:
        with ThreadPoolExecutor(max_workers=1) as file_worker:
            for iteration in range(iterations):
                engine.last_exchange=time.monotonic()
                sid=f'{tag}_{iteration}'
                measured('terminal_open', lambda: accept(command('terminal_open',session_id=sid,cols=100,rows=30)))
                groups_to_reap.append(engine.terminals[sid].pid)
                future=file_worker.submit(transfer,iteration)
                human=(b'test -z "$FIELD_REMOTE_TOKEN" && printf "'+tag.encode()+
                       b'" > pty-check.txt && printf "'+tag.encode()+b'\\n"\n')
                measured('terminal_input',lambda:accept(command('terminal_input',session_id=sid,data=base64.b64encode(human).decode())))
                measured('terminal_resize',lambda:accept(command('terminal_resize',session_id=sid,cols=110,rows=33)))
                run=command('run',argv=['/usr/bin/printf',tag],cwd='',timeout=3)
                result=measured('fixed_command',lambda:accept(run))
                if result['stdout']!=tag:raise AssertionError('tool result crossstation mismatch')
                measured('command_dedup',lambda:accept(run))
                current=json.dumps({'station':tag,'iteration':iteration,'fixed':False})
                updated=json.dumps({'station':tag,'iteration':iteration,'fixed':True})
                (approved/'config.json').write_text(current)
                patch=command('patch_file',path='config.json',expected_sha256=hashlib.sha256(current.encode()).hexdigest(),content=updated)
                patched=measured('patch_atomic_backup',lambda:accept(patch))
                if (approved/patched['backup']).read_text()!=current or (approved/'config.json').read_text()!=updated:
                    raise AssertionError('patch backup mismatch')
                measured('patch_dedup',lambda:accept(patch))
                expired=command('patch_file',path='config.json',expected_sha256=patched['sha256'],content='expired-mutation')
                expired['expires_at']=time.time()-1
                measured('expiry_rejection',lambda:accept(expired,expect=False))
                if (approved/'config.json').read_text()!=updated:raise AssertionError('expired command executed')
                deadline=time.monotonic()+12
                terminal_seen=bytearray()
                while (not future.done() or tag.encode() not in terminal_seen
                       or not (approved/'pty-check.txt').exists()):
                    terminal_seen.extend(drain())
                    if time.monotonic()>deadline:raise AssertionError('concurrent PTY/file deadline exceeded')
                    time.sleep(.005)
                future.result()
                if (approved/'pty-check.txt').read_text()!=tag:raise AssertionError('PTY shell did not execute with isolated credentials')
                (approved/'pty-check.txt').unlink()
                measured('terminal_close',lambda:accept(command('terminal_close',session_id=sid)))
                drain()
                cancelled=f'{sid}_offline'
                measured('terminal_open_for_offline',lambda:accept(command('terminal_open',session_id=cancelled,cols=80,rows=24)))
                groups_to_reap.append(engine.terminals[cancelled].pid)
                def offline():
                    engine.last_exchange=time.monotonic()-31;engine.pump()
                    if cancelled in engine.terminals:raise AssertionError('offline terminal remained open')
                measured('offline_cancel',offline)
                drain();engine.last_exchange=time.monotonic()
            archive=measured('directory_archive_prepare',lambda:file_call('prepare',path=''))
            blob=bytearray()
            while len(blob)<archive['size']:
                item=measured('directory_archive_chunk',lambda:file_call('chunk',ticket=archive['ticket'],offset=len(blob)))
                blob.extend(base64.b64decode(item['data']))
            if hashlib.sha256(blob).hexdigest()!=archive['sha256']:raise AssertionError('archive SHA mismatch')
            with tarfile.open(fileobj=io.BytesIO(blob),mode='r:gz') as stream:
                if len(stream.getmembers())!=iterations:raise AssertionError('archive member count mismatch')
                for member in stream:
                    if not stream.extractfile(member).read().startswith(tag.encode()):raise AssertionError('archive crossstation data')
            counters['sha_checks'] += 1
    except Exception as exc:
        unexpected.append({'operation':'station_validation','error_class':type(exc).__name__,'detail':str(exc)[:160]})
    finally:
        engine.close()
        for group in groups_to_reap:
            try:os.killpg(group,0)
            except ProcessLookupError:continue
            unexpected.append({'operation':'cleanup','error_class':'ProcessLeak','detail':'PTY process group survived'})
    return {'station':station_number,'pid':os.getpid(),'uid':os.getuid(),'home':str(home),
            'samples':samples,'unexpected':unexpected,'counters':counters,'ok':not unexpected}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    parser.add_argument('--levels',default='4,8,16')
    parser.add_argument('--iterations',type=int,default=3)
    parser.add_argument('--payload-bytes',type=int,default=256*1024)
    args=parser.parse_args()
    levels=[int(value) for value in args.levels.split(',')]
    if any(not 1<=value<=16 for value in levels) or not 1<=args.iterations<=10 or not 1<=args.payload_bytes<=2*1024*1024:
        parser.error('bounded load: 1..16 workers, 1..10 iterations, <=2MiB per file')
    output=Path(args.output).resolve()
    if '/Documents/tmp/artifacts/' not in str(output):parser.error('output must be in Documents/tmp/artifacts')
    output.parent.mkdir(parents=True,exist_ok=True)
    fixtures=output.parent/('fixtures-'+uuid.uuid4().hex)
    fixtures.mkdir(mode=0o700)
    def source_digests():
        folder=Path(__file__).resolve().parent
        return {name:hashlib.sha256((folder/name).read_bytes()).hexdigest()
                for name in ('connector.py','file_browser.py','stress_harness.py')}
    report={'scope':'edge-only concurrent component stress','physical_multi_host':False,'central_http_tested':False,
            'feedback_diagnosis_repair_workflow_tested':False,'model_tested':False,'controlled_model_tested':False,
            'multi_uid_tested':False,'station_isolation':'separate processes and HOME/approvedroot/token, same real UID',
            'python':platform.python_version(),'os':platform.platform(),'network':'none (container runtime supplied)',
            'hostname':__import__('socket').gethostname(),'levels':[],'started_at':time.time(),
            'container_image':'teleop-daq-feedback-verify:20261111','device_profile':'CPU-only isolated tests','gpu_flags':[]}
    report['source_sha256_start']=source_digests()
    report['os_release']=Path('/etc/os-release').read_text()
    for level in levels:
        folder=fixtures/f'load-{level}';folder.mkdir()
        started=time.perf_counter()
        with ProcessPoolExecutor(max_workers=level,mp_context=multiprocessing.get_context('spawn')) as pool:
            stations=list(pool.map(station,[(str(folder),number,args.iterations,args.payload_bytes) for number in range(level)]))
        samples=[sample for item in stations for sample in item.pop('samples')]
        unexpected=[error for item in stations for error in item['unexpected']]
        result={'workers':level,'elapsed_seconds':round(time.perf_counter()-started,3),'iterations_per_station':args.iterations,
                'payload_bytes':args.payload_bytes,'operation_count':len(samples),'operations':summarize(samples),
                'p50_ms':round(statistics.median(sample['elapsed_ms'] for sample in samples),3) if samples else None,
                'p95_ms':round(percentile([sample['elapsed_ms'] for sample in samples],.95),3) if samples else None,
                'unexpected_count':len(unexpected),'errors':unexpected,'stations':stations,
                'crossstation_integrity_ok':not unexpected,'ok':all(item['ok'] for item in stations)}
        result['distinct_worker_pids']=len({item['pid'] for item in stations})
        result['total_sha_checks']=sum(item['counters'].get('sha_checks',0) for item in stations)
        result['total_crossstation_rejections']=sum(item['counters'].get('crossstation_rejections',0) for item in stations)
        if result['distinct_worker_pids'] != level:
            result['ok']=False
            result['errors'].append({'operation':'worker_count','error_class':'InsufficientConcurrency'})
        report['levels'].append(result)
        print(json.dumps({key:result[key] for key in ('workers','elapsed_seconds','operation_count','unexpected_count','ok')}),flush=True)
    report.update(completed_at=time.time(),ok=all(level['ok'] for level in report['levels']))
    report['source_sha256_end']=source_digests()
    report['source_unchanged_during_run']=report['source_sha256_start']==report['source_sha256_end']
    report['ok'] &= report['source_unchanged_during_run']
    fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream:json.dump(report,stream,indent=2);stream.flush();os.fsync(stream.fileno())
    print(json.dumps({'report':str(output),'ok':report['ok']}),flush=True)
    raise SystemExit(0 if report['ok'] else 1)


if __name__=='__main__':main()
