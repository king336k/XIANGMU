"""Generate measured evidence inside a disposable DAQ container; no diagnosis oracle here."""
import hashlib
import json
import os
from pathlib import Path
import platform
import socket
import sys
import threading
import time
from datetime import datetime,timezone

case=int(sys.argv[1]);root=Path('/work');root.mkdir(exist_ok=True)
if case==3:
    restricted=root/'private';restricted.mkdir();(restricted/'record.bin').write_bytes(b'controlled-record')
    restricted.chmod(0o500);os.setgid(65534);os.setuid(65534)
os.environ['ENGRAM_DAQ_LOG_DIR']='/work/runtime-logs'
from backend.utils.logger import get_logger
logger=get_logger('backend.evidence.operation')
def dump(name,value):(root/name).write_text(json.dumps(value,ensure_ascii=False,indent=2))
def fs(path):
    stat=os.statvfs(path)
    return {'path':str(path),'total_bytes':stat.f_blocks*stat.f_frsize,'available_to_user_bytes':stat.f_bavail*stat.f_frsize,'free_inodes':stat.f_favail,'flags':stat.f_flag}
def listeners():
    result=[]
    for name in ['tcp','tcp6']:
        for line in Path('/proc/net/'+name).read_text().splitlines()[1:]:
            columns=line.split()
            if columns[3]=='0A':result.append({'family':name,'address_hex':columns[1],'port':int(columns[1].split(':')[-1],16)})
    return result
configuration={'ros_mode':'ros1' if case==4 else 'isolated','ros1':{'master_uri':'http://127.0.0.1:11311'} if case==4 else {},'capture_root':'/work/payload'}
environment={'recorded_at':datetime.now(timezone.utc).isoformat(),'scope':'isolated_daq_container','physical_robot_connected':False,
    'python':platform.python_version(),'platform':platform.platform(),'uid':os.getuid(),'gid':os.getgid(),
    'filesystem_before':fs('/work/payload'),'listeners_before':listeners(),'configuration':configuration,'network_namespace':os.readlink('/proc/self/ns/net')}
logger.info('environment inspection completed',extra={'extra':{'uid':os.getuid(),'scope':'isolated_daq_container'}})
for number in range(15):logger.info('runtime observation',extra={'extra':{'sample':number,'monotonic_ns':time.monotonic_ns()}})
started=time.monotonic();observed={'operation_completed':False}
try:
    logger.info('operation started')
    if case==1:
        with socket.socket() as reserved:
            reserved.bind(('127.0.0.1',0));port=reserved.getsockname()[1]
        environment['operation_target']={'host':'127.0.0.1','port':port}
        logger.info('opening configured endpoint',extra={'extra':environment['operation_target']})
        with socket.create_connection(('127.0.0.1',port),timeout=2):pass
    elif case==2:
        with (root/'payload'/'record.bin').open('wb',buffering=0) as output:
            for _ in range(20):output.write(b'x'*(1024*1024))
    elif case==3:
        mode=(root/'private').stat();environment['path_state']={'path':'/work/private','mode':oct(mode.st_mode&0o777),'uid':mode.st_uid,'gid':mode.st_gid}
        with (root/'private'/'record.bin').open('rb') as source:source.read()
    elif case==4:
        from backend.utils.runtime_preflight import validate_ros1_config
        validate_ros1_config(configuration['ros1'])
    elif case==5:
        raw=os.urandom(4096);path=root/'payload'/'record.bin';path.write_bytes(raw)
        readback=path.read_bytes();assert readback==raw
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));listener.listen(1);port=listener.getsockname()[1]
            environment['operation_target']={'host':'127.0.0.1','port':port};environment['listeners_during']=listeners()
            def serve():
                connection,_=listener.accept()
                with connection:connection.sendall(b'ACK')
            thread=threading.Thread(target=serve);thread.start()
            with socket.create_connection(('127.0.0.1',port),timeout=2) as connection:assert connection.recv(3)==b'ACK'
            thread.join(timeout=2);assert not thread.is_alive()
        observed.update(readback_sha256=hashlib.sha256(readback).hexdigest(),readback_bytes=len(readback),endpoint_connected=True)
        logger.info('file write and readback completed',extra={'extra':{'bytes':len(readback),'sha256':hashlib.sha256(readback).hexdigest()}})
        logger.info('endpoint request completed',extra={'extra':{'host':'127.0.0.1','port':port,'reply':'ACK'}})
    else:raise ValueError('unknown operation')
    observed['operation_completed']=True;logger.info('operation completed')
except Exception as error:
    observed.update(exception_type=type(error).__name__,errno=getattr(error,'errno',None),code=getattr(error,'code',None),message=str(error))
    logger.exception('operation did not complete')
finally:
    environment.update(filesystem_after=fs('/work/payload'),listeners_after=listeners(),elapsed_seconds=round(time.monotonic()-started,6))
    files=[]
    for path in (root/'payload').iterdir():
        if path.is_file():files.append({'path':path.name,'size_bytes':path.stat().st_size})
    logger.info('output inventory completed',extra={'extra':{'files':files}})
    for number in range(8):logger.info('post-operation observation',extra={'extra':{'sample':number,'monotonic_ns':time.monotonic_ns()}})
    dump('environment.json',environment);dump('observations.json',observed)
    dump('capture_manifest.json',{'observed_outputs':files,'operation_completed':observed['operation_completed'],'recorded_at':datetime.now(timezone.utc).isoformat()})

print('EVIDENCE_CAPTURE_READY',flush=True)
time.sleep(120)
