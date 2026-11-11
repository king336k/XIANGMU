"""Measure the same loopback configuration before and after starting its listener."""
import hashlib,json,os,socket,sys,threading,time
from pathlib import Path
from datetime import datetime,timezone
root=Path('/work');root.mkdir(exist_ok=True);os.environ['ENGRAM_DAQ_LOG_DIR']='/work/runtime-logs'
from backend.utils.logger import get_logger
log=get_logger('backend.evidence.operation');port=int(sys.argv[1]);sample=os.urandom(4096)
def listeners():
 return [int(row.split()[1].split(':')[-1],16) for row in Path('/proc/net/tcp').read_text().splitlines()[1:] if row.split()[3]=='0A']
proof={'recorded_at':datetime.now(timezone.utc).isoformat(),'scope':'isolated_software_repair','physical_robot':False,'target':{'host':'127.0.0.1','port':port},'listeners_before':listeners()}
try:
 with socket.create_connection(('127.0.0.1',port),timeout=2):pass
 raise AssertionError('Baseline unexpectedly reachable')
except ConnectionRefusedError as error:
 proof['before']={'exception_type':type(error).__name__,'errno':error.errno};log.exception('operation did not complete before service startup')
with socket.socket() as listener:
 listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);listener.bind(('127.0.0.1',port));listener.listen(1)
 proof['listeners_during']=listeners();log.info('endpoint listener ready',extra={'extra':{'port':port}})
 def serve():
  client,_=listener.accept()
  with client:client.sendall(b'ACK')
 thread=threading.Thread(target=serve);thread.start()
 with socket.create_connection(('127.0.0.1',port),timeout=2) as client:reply=client.recv(3)
 thread.join(2);assert reply==b'ACK' and not thread.is_alive()
 path=root/'sample.bin';path.write_bytes(sample);assert path.read_bytes()==sample
 proof['after']={'endpoint_connected':True,'reply':reply.decode(),'readback_bytes':len(sample),'sha256':hashlib.sha256(sample).hexdigest(),'operation_completed':True}
 log.info('endpoint request and sample readback completed',extra={'extra':proof['after']})
proof['listeners_after']=listeners();proof['completed_at']=datetime.now(timezone.utc).isoformat()
(root/'observations.json').write_text(json.dumps(proof,indent=2));print('EVIDENCE_CAPTURE_READY',flush=True);time.sleep(120)
