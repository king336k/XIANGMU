"""Five blinded controlled-real cases through IAM/HMAC bridge; never reads ground_truth."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import bcrypt
import hashlib
import hmac
import json
from pathlib import Path
import subprocess
import time
from uuid import uuid4
import requests

AUTH='http://127.0.0.1:16335';SOURCE='latest-native-verification';UPSTREAM_PROJECT=1491109

def sql(query):
    result=subprocess.run(['docker','exec','-i','account-interop-20261107-iam-db-1','sh','-c','MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --default-character-set=utf8mb4 -uroot -N account_acceptance'],input=query,capture_output=True,text=True)
    if result.returncode:raise RuntimeError('Isolated fixture SQL failed')
    return result.stdout.strip()

def native(script,value):
    result=subprocess.run(['docker','exec','-i','plane-local-20261106-api-1','python','-c',script],input=json.dumps(value),capture_output=True,text=True)
    if result.returncode:raise RuntimeError('Native fixture failed: '+result.stderr[-500:])
    return json.loads(result.stdout.strip().splitlines()[-1])

SETUP='''import os,json,sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE','plane.settings.production')
import django;django.setup()
from plane.db.models import Workspace,Project,ProjectMember,WorkspaceMember,User,Issue,State
from plane.db.models.state import DEFAULT_STATES
from plane.quality.models import ProjectRolePolicy,PlatformProject,PlatformIdentity,BusinessRole,DaqBinding
from plane.license.models import InstanceAdmin
value=json.load(sys.stdin);ws=Workspace.objects.get(slug='chinese-demo');owner=InstanceAdmin.objects.filter(role=20,user__is_active=True).first().user
project,created=Project.objects.get_or_create(workspace=ws,identifier='FAULTLAB149',defaults={'name':'受控软件盲测实验室','network':0,'created_by':owner})
if created:State.objects.bulk_create([State(project=project,workspace=ws,**row) for row in DEFAULT_STATES])
ProjectMember.objects.get_or_create(project=project,member=owner,defaults={'workspace':ws,'role':20})
ProjectRolePolicy.objects.update_or_create(project=project,defaults={'enabled':True})
PlatformProject.objects.get_or_create(project=project,source_instance=value['source'],external_project_id=value['upstream'],defaults={'active':True,'created_by':owner})
for item in value['cases']:
 user,_=User.objects.get_or_create(email=item['name']+'@example.invalid',defaults={'username':item['name'],'first_name':'隔离验证'})
 WorkspaceMember.objects.get_or_create(workspace=ws,member=user,defaults={'role':15})
 ProjectMember.objects.get_or_create(project=project,member=user,defaults={'workspace':ws,'role':15})
 PlatformIdentity.objects.get_or_create(project=project,source_instance=value['source'],external_user_id=item['uid'],defaults={'user':user})
 BusinessRole.objects.get_or_create(project=project,user=user,defaults={'role':'REPORTER'})
 issue,_=Issue.objects.get_or_create(project=project,name='隔离采集作业 '+str(item['number']),defaults={'workspace':ws,'created_by':owner})
 DaqBinding.objects.get_or_create(project=project,source_instance=value['source'],platform_task_id=item['task'],source_record_id=item['session'],defaults={'external_project_id':value['upstream'],'issue':issue,'package_id':item['package'],'created_by':owner})
print(json.dumps({'project_id':str(project.id),'workspace':ws.slug,'identifier':project.identifier}))
'''

def main():
    parser=argparse.ArgumentParser();parser.add_argument('artifact',type=Path);args=parser.parse_args();root=args.artifact;root.mkdir(parents=True,exist_ok=True)
    path=root/'http-state.json';state=json.loads(path.read_text()) if path.exists() else {'cases':[{'number':n,'name':'fault149-'+uuid4().hex[:12],'task':149110900+n,'session':str(uuid4()),'package':'fault149-'+uuid4().hex,'request_key':str(uuid4())} for n in range(1,6)]}
    def save():path.write_text(json.dumps(state,ensure_ascii=False,indent=2))
    save()
    env=dict(row.split('=',1) for row in json.loads(subprocess.check_output(['docker','inspect','project-bridge-verification-20261109']))[0]['Config']['Env'])
    def password(name):return hmac.new(env['PLATFORM_BOOTSTRAP_TOKEN'].encode(),('acceptance:'+name).encode(),hashlib.sha256).hexdigest()
    sql(f"INSERT IGNORE INTO projects(id,name,description,status,start_date,end_date,created_by) VALUES({UPSTREAM_PROJECT},'受控软件盲测实验室','隔离容器实验，无物理机器人','InProgress',CURDATE(),DATE_ADD(CURDATE(),INTERVAL 1 MONTH),1);")
    for case in state['cases']:
        if 'uid' not in case:
            exists=sql(f"SELECT id FROM users WHERE username='{case['name']}';")
            if not exists:
                hashed=bcrypt.hashpw(password(case['name']).encode(),bcrypt.gensalt()).decode()
                sql(f"INSERT INTO users(username,email,password,role,status) VALUES('{case['name']}','{case['name']}@example.invalid','{hashed}','Collector','Active');")
            case['uid']=int(sql(f"SELECT id FROM users WHERE username='{case['name']}';"));save()
        sql(f"SET time_zone='+08:00'; INSERT IGNORE INTO project_users(project_id,user_id,role,created_by) VALUES({UPSTREAM_PROJECT},{case['uid']},'Member',1); INSERT IGNORE INTO tasks(id,project_id,name,status,created_at,updated_at) VALUES({case['task']},{UPSTREAM_PROJECT},'隔离采集作业 {case['number']}','InProgress',NOW(),NOW()); INSERT IGNORE INTO data_packages(id,task_id,user_id,name,source_session_id,status,recorded_at,uploaded_at,created_at,updated_at) VALUES('{case['package']}',{case['task']},{case['uid']},'隔离采集记录 {case['number']}','{case['session']}','PendingAnnotation',NOW(),NOW(),NOW(),NOW());")
    state.update(native(SETUP,{'source':SOURCE,'upstream':UPSTREAM_PROJECT,'cases':state['cases']}));save()
    base=f"/api/workspaces/{state['workspace']}/projects/{state['project_id']}/quality/"
    def run(case):
        folder=root/f"case-{case['number']:02}";check=folder/'http-state.json'
        local=json.loads(check.read_text()) if check.exists() else {};events=[]
        def checkpoint():check.write_text(json.dumps(local,ensure_ascii=False,indent=2))
        response=requests.post(AUTH+'/api/daq/auth/login',json={'username':case['name'],'password':password(case['name'])},timeout=30)
        assert response.status_code==200 and response.json().get('code')==1,'DAQ login failed'
        headers={'Authorization':'Bearer '+response.json()['data']['accessToken']}
        def bridge(method,url,data=None,files=None,expected=(200,)):
            response=requests.request(method,AUTH+'/issue-api'+url,headers={**headers,'Idempotency-Key':case['request_key']},json=data if files is None else None,files=files,timeout=60)
            events.append({'method':method,'path':url,'status':response.status_code})
            assert response.status_code in expected,(method,url,response.status_code,response.text[:300])
            return response.json()
        started=time.monotonic()
        payload={'sourceRecordId':case['session'],'platformTaskId':case['task'],'category':'Other','title':f"隔离采集异常验证编号{case['number']:02}",
            'description':'隔离采集运行检查已完成，请依据附带完整日志及环境观测判断是否存在异常、证据范围和下一步验证。无物理机器人连接。'}
        receipt=bridge('POST',base+'daq/reports/',payload,expected=(200,201));local.update(defect_id=receipt['issueId'],code=receipt['issueCode']);checkpoint()
        archive=folder/'material.zip';raw=archive.read_bytes();digest=hashlib.sha256(raw).hexdigest()
        package=bridge('POST',base+'packages/',{'name':'隔离运行观测材料','defect_id':local['defect_id'],'source_system':'ENGRAM_DAQ','external_id':'blind-'+case['request_key'],'files':[{'path':'material.zip','size':len(raw),'sha256':digest}]},expected=(200,201))
        uploaded=bridge('POST',base+f"packages/{package['id']}/files/",files={'file':('material.zip',raw,'application/zip')},expected=(200,201))
        local.update(package_id=package['id'],file_id=uploaded['id'],sha256=digest);checkpoint()
        job=None
        while time.monotonic()-started<240:
            detail=bridge('GET',base+f"daq/issues/{local['defect_id']}/")
            (folder/'model-http-detail.json').write_text(json.dumps(detail,ensure_ascii=False,indent=2))
            candidates=[row for row in detail['diagnostics'] if any(source.get('file_id')==uploaded['id'] for source in row.get('result',{}).get('sources',[]))]
            job=candidates[0] if candidates else None
            if job and job['status'] not in {'running','queued'}:break
            time.sleep(2)
        assert job is not None,'No completed diagnostic'
        local.update(job_id=job['id'],status=job['status'],model_status=job.get('result',{}).get('model_status'),elapsed_seconds=round(time.monotonic()-started,3),events=events)
        checkpoint();(folder/'model-output.json').write_text(json.dumps(job,ensure_ascii=False,indent=2))
        print(json.dumps({'case':case['number'],'code':local['code'],'model_status':local['model_status'],'elapsed_seconds':local['elapsed_seconds']},ensure_ascii=False),flush=True)
        return local
    results=[]
    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in as_completed([pool.submit(run,case) for case in state['cases']]):results.append(future.result())
    (root/'http-results.json').write_text(json.dumps({'scope':'five controlled real software operations, no physical robot','model_input_blinded':True,'concurrency':2,'results':results},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
