"""Real 16335 bridge: unique actor, >20MiB incompressible ZIP, retry, bounded SHA readback and automatic diagnosis.

Uses existing isolated source/project only. No ordinary account login or session replacement.
Run: python verify_chunked_evidence.py ARTIFACT_DIR EXISTING_FLOW_STATE_JSON
"""
import base64
import bcrypt
import hashlib
import hmac
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import textwrap
from uuid import uuid4
import zipfile
import requests

ROOT = Path(sys.argv[1]); ROOT.mkdir(parents=True, exist_ok=True)
state = json.loads(Path(sys.argv[2]).read_text())
AUTH = 'http://127.0.0.1:16335'
checkpoint_path=ROOT/'chunked-transfer-state.json'
checkpoint=json.loads(checkpoint_path.read_text()) if checkpoint_path.exists() else {}
NAME = checkpoint.get('actor') or 'native146-evidence-' + uuid4().hex[:10]
def checkpoint_save(**values):
    checkpoint.update(values);checkpoint_path.write_text(json.dumps(checkpoint,indent=2))
source = 'latest-native-verification'
upstream_project = 1401109
started = time.monotonic()
env = dict(row.split('=', 1) for row in json.loads(subprocess.check_output(
    ['docker', 'inspect', 'project-bridge-verification-20261109']))[0]['Config']['Env'])
password = hmac.new(env['PLATFORM_BOOTSTRAP_TOKEN'].encode(), ('acceptance:' + NAME).encode(), hashlib.sha256).hexdigest()
hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
query = f"""INSERT INTO users(username,email,password,role,status) VALUES('{NAME}','{NAME}@example.invalid','{hashed}','Collector','Active');
INSERT INTO project_users(project_id,user_id,role,created_by) SELECT {upstream_project},id,'Member',1 FROM users WHERE username='{NAME}';
SELECT id FROM users WHERE username='{NAME}';"""
if 'uid' not in checkpoint:
    result = subprocess.run(['docker','exec','-i','account-interop-20261107-iam-db-1','sh','-c',
        'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --default-character-set=utf8mb4 -uroot -N account_acceptance'],
        input=query, capture_output=True, text=True, check=True)
    uid = int(result.stdout.strip().splitlines()[-1])
    setup = '''
    import os,json,sys
    os.environ.setdefault('DJANGO_SETTINGS_MODULE','plane.settings.production')
    import django;django.setup()
    from plane.db.models import User,Project,ProjectMember,WorkspaceMember
    from plane.quality.models import PlatformIdentity,BusinessRole
    value=json.load(sys.stdin);project=Project.objects.get(pk=value['project'])
    user=User.objects.create(username=value['name'],email=value['name']+'@example.invalid',first_name='Evidence',last_name='146')
    WorkspaceMember.objects.create(workspace=project.workspace,member=user,role=15)
    ProjectMember.objects.create(project=project,workspace=project.workspace,member=user,role=15)
    BusinessRole.objects.create(project=project,user=user,role='REPORTER')
    PlatformIdentity.objects.create(project=project,source_instance=value['source'],external_user_id=value['uid'],user=user)
    print(str(user.pk))
    '''
    setup_result = subprocess.run(['docker','exec','-i','plane-local-20261106-api-1','python','-c',textwrap.dedent(setup)],
        input=json.dumps({'project':state['project_id'],'name':NAME,'source':source,'uid':uid}),capture_output=True,text=True)
    if setup_result.returncode: raise RuntimeError(setup_result.stderr[-2000:])
    checkpoint_save(actor=NAME,uid=uid)
else:
    uid=checkpoint['uid']
login = requests.post(AUTH+'/api/daq/auth/login',json={'username':NAME,'password':password},timeout=30)
assert login.status_code == 200 and login.json().get('code') == 1, 'DAQ login failed'
headers = {'Authorization':'Bearer '+login.json()['data']['accessToken']}
events=[]
def bridge(method,path,body=None,files=None,expected=(200,),stream=False):
    response=requests.request(method,AUTH+'/issue-api'+path,headers=headers,json=body if files is None else None,
                              files=files,timeout=90,stream=stream)
    events.append({'method':method,'path':path,'status':response.status_code})
    assert response.status_code in expected,(method,path,response.status_code,response.text[:350])
    return response if stream else response.json()
base=f"/api/workspaces/{state['workspace']}/projects/{state['project_id']}/quality/"
# Existing report source remains authoritative; new package appends complete evidence to its history.
archive=ROOT/'incompressible-diagnostic.zip'
log_size=32*1024*1024
if not archive.exists():
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_STORED) as bundle:
        with bundle.open('logs/system.log','w') as output:
            remaining=log_size
            while remaining:
                data=base64.b85encode(os.urandom(min(32*1024,remaining)))+b'\n';data=data[:remaining]
                output.write(data);remaining-=len(data)
            output.write(b'\n2026-11-09T05:06:07Z ERROR E-FULL-TAIL target=127.0.0.1:65123 connection refused\n')
        bundle.writestr('environment.json',json.dumps({'scope':'local_simulation','recorded_at':'2026-11-09T05:06:07Z','disk':{'available_to_user_bytes':123456},'network':{'port':65123,'tcp_connect':'failed'}}))
        bundle.writestr('capture_manifest.json','{"all_complete":false,"outputs":{"expected":10,"actual":8}}')
        bundle.writestr('schema.json','{"version":2,"fields":["joints","camera"]}')
        bundle.writestr('auto_qc.json','{"passed":false,"failures":[{"code":"FRAME_DROP","missing":2}]}')
check=hashlib.sha256()
with archive.open('rb') as handle:
    for chunk in iter(lambda:handle.read(1024*1024),b''): check.update(chunk)
digest=check.hexdigest()
baseline=bridge('GET',base+f"daq/issues/{state['defect_id']}/")
baseline_jobs=set(checkpoint.get('baseline_jobs',[row['id'] for row in baseline.get('diagnostics',[])]))
checkpoint_save(baseline_jobs=sorted(baseline_jobs))
if 'package' not in checkpoint:
    package=bridge('POST',base+'packages/',{'name':'完整不可压缩诊断材料','defect_id':state['defect_id'],
        'source_system':'ENGRAM_DAQ','external_id':NAME,'files':[{'path':archive.name,'size':archive.stat().st_size,'sha256':digest}]},expected=(200,201))
    checkpoint_save(package=package)
else:
    package=checkpoint['package']
chunk_bytes=4*1024*1024;count=(archive.stat().st_size+chunk_bytes-1)//chunk_bytes
with archive.open('rb') as handle:
    for index in range(count):
        raw=handle.read(chunk_bytes)
        fields={'file':('chunk.bin',raw,'application/octet-stream'),'manifest_path':(None,archive.name),
                'chunk_index':(None,str(index)),'chunk_count':(None,str(count))}
        uploaded=bridge('POST',base+f"packages/{package['id']}/files/",files=fields,expected=(200,201) if index==count-1 else (200,202))
        if index==0:
            bridge('POST',base+f"packages/{package['id']}/files/",files=fields,expected=(200,202))
        if index < count-1 and uploaded.get('uploading'):
            listing=bridge('GET',base+f"packages/{package['id']}/files/")
            assert listing==[], 'Partial file became visible'
            partial=bridge('GET',base+f"daq/issues/{state['defect_id']}/")
            assert {row['id'] for row in partial.get('diagnostics',[])}==baseline_jobs, 'Partial upload started diagnosis'
checkpoint_save(file=uploaded)
endpoint=base+f"files/{uploaded['id']}/download/"
metadata=bridge('GET',endpoint+'?metadata=1')
assert metadata['size']==archive.stat().st_size and metadata['sha256']==digest
returned=hashlib.sha256();downloaded=0;read_sizes=[]
for offset in range(0,metadata['size'],chunk_bytes):
    length=min(chunk_bytes,metadata['size']-offset)
    readback=bridge('GET',endpoint+f'?offset={offset}&length={length}',expected=(206,),stream=True)
    block_size=0
    for block in readback.iter_content(1024*1024):
        returned.update(block);downloaded+=len(block);block_size+=len(block)
    read_sizes.append(block_size)
    assert block_size==length and block_size<=chunk_bytes
assert returned.hexdigest()==digest and downloaded==archive.stat().st_size
job=None
for attempt in range(100):
    detail=bridge('GET',base+f"daq/issues/{state['defect_id']}/")
    job=next((row for row in detail.get('diagnostics',[]) if row['id'] not in baseline_jobs and any(source.get('file_id')==uploaded['id'] for source in row.get('result',{}).get('sources',[]))),None)
    if job and job['status'] not in {'queued','running'}:break
    time.sleep(2)
assert job and job.get('result',{}).get('model_status')=='completed', 'Automatic model diagnosis did not complete'
sources=[row for row in job['result'].get('sources',[]) if row.get('file_id')==uploaded['id']]
entries={row.get('archive_entry') for row in sources}
assert {'logs/system.log','environment.json','capture_manifest.json','schema.json','auto_qc.json'}<=entries
log=next(row for row in sources if row.get('archive_entry')=='logs/system.log')
assert log['scanned_bytes']==log['file_bytes'] and not log['scan_incomplete'] and 'E-FULL-TAIL' in log['excerpt']
assert all(not row.get('scan_incomplete') for row in sources)
diagnostic={'job_id':job['id'],'status':job['status'],'model_status':job['result'].get('model_status'),
    'duration_ms':job['result'].get('duration_ms'),'engine':job['result'].get('engine'),
    'sources':[dict((key,row.get(key)) for key in ['archive_entry','scanned_bytes','file_bytes','scan_incomplete']) for row in sources],
    'tail_error_found':True,'raw_mcap_video_uploaded':False}
(ROOT/'chunked-diagnostic-proof.json').write_text(json.dumps(diagnostic,ensure_ascii=False,indent=2))
proof={'actor':NAME,'upstream_user_id':uid,'project_id':state['project_id'],'defect_id':state['defect_id'],
       'package_id':package['id'],'file_id':uploaded['id'],'archive_bytes':downloaded,'sha256':digest,
       'readback_sha256':returned.hexdigest(),'chunk_bytes':chunk_bytes,'chunk_count':count,
       'retry_verified':True,'partial_file_not_visible':True,'partial_diagnosis_not_started':True,
       'download_max_response_bytes':max(read_sizes),'download_responses':len(read_sizes),'diagnostic':diagnostic,'elapsed_seconds':round(time.monotonic()-started,3),'events':events}
(ROOT/'chunked-http-proof.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2))
print(json.dumps({key:value for key,value in proof.items() if key!='events'},ensure_ascii=False))
