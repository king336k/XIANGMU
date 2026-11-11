"""Concurrent duplicate requests against the real authenticated bridge, no new business records."""
import runpy
from pathlib import Path
import concurrent.futures
import json
import time

ctx=runpy.run_path(str(Path(__file__).with_name('verify_flow.py')))
bridge,base,payload,key,state,root=(ctx[name] for name in ['bridge','base','payload','key','state','ROOT'])
started=time.monotonic()
def retry(_):
    begin=time.monotonic()
    result=bridge('POST',base+'daq/reports/',payload,key=key)
    assert result['issueId']==state['defect_id'] and result['issueCode']==state['code']
    return time.monotonic()-begin
with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
    times=sorted(executor.map(retry,range(50)))
proof={'concurrent_clients':10,'duplicate_requests':50,'same_defect_id':state['defect_id'],'same_code':state['code'],
       'seconds':round(time.monotonic()-started,3),'p95_seconds':round(times[47],3),
       'scope':'one collector identity retrying concurrently; not 50 independent model jobs'}
(root/'retry-burst-proof.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2))
print(json.dumps(proof,ensure_ascii=False))
