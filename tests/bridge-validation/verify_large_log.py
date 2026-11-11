"""Real bridge upload, complete download, scan and model check for a 90 MiB diagnostic log."""
import runpy
from pathlib import Path
import sys
import json
import hashlib
import time
import zipfile

ctx = runpy.run_path(str(Path(__file__).with_name('verify_flow.py')))
globals().update({key:ctx[key] for key in ['ROOT','state','base','bridge','clients','PLATFORM','events']})
archive = ROOT / 'large-log.zip'
size = 90 * 1024 * 1024
if not archive.exists():
    line = b'INFO stable sampling ' + b'x' * 1000 + b'\n'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as bundle:
        with bundle.open('logs/large.log','w') as out:
            written = 0
            for segment, marker in [(size//3,b'ERROR connection refused E-NET-730 target=127.0.0.1:65123\n'),(size//3,b'ERROR recorder halted E-DISK-912 disk_full=true\n'),(size//3,b'INFO end\n')]:
                count = segment//len(line)
                for _ in range(count): out.write(line)
                out.write(marker)
raw=archive.read_bytes()
with zipfile.ZipFile(archive) as bundle: original_size=bundle.getinfo('logs/large.log').file_size
started=time.monotonic()
package=bridge('POST',base+'packages/',{'name':'90MiB日志压力验收','defect_id':state['defect_id'],'source_system':'ENGRAM_DAQ',
    'external_id':'large-'+state['request_key'],'files':[{'path':archive.name,'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}]},expected=[200,201])
file=bridge('POST',base+f"packages/{package['id']}/files/",files={'file':(archive.name,raw,'application/zip')},expected=[200,201])
response=clients['Manager'].get(PLATFORM+base+f"files/{file['id']}/download/",timeout=30)
assert response.status_code==200 and hashlib.sha256(response.content).digest()==hashlib.sha256(raw).digest()
while time.monotonic()-started<210:
    detail=bridge('GET',base+f"daq/issues/{state['defect_id']}/")
    if detail['diagnostics'][0]['status'] not in {'queued','running'}:break
    time.sleep(2)
job=detail['diagnostics'][0]
source=next(row for row in job['result'].get('sources',[]) if row.get('archive_entry')=='logs/large.log')
proof={'code':state['code'],'zip_bytes':len(raw),'expanded_log_bytes':original_size,'scanned_bytes':source.get('scanned_bytes'),
    'source_retains_both_errors':all(marker in source['excerpt'] for marker in ['E-NET-730','E-DISK-912']),
    'download_sha256_verified':True,'model_status':job['result'].get('model_status'),'model_ms':job['result'].get('duration_ms'),
    'engine':job['result'].get('engine'),'elapsed_seconds':round(time.monotonic()-started,3),'checks':len(events)}
(ROOT/'large-log-proof.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2))
print(json.dumps(proof,ensure_ascii=False))
assert proof['scanned_bytes']==proof['expanded_log_bytes'] and proof['source_retains_both_errors']
assert proof['model_status']=='completed'
