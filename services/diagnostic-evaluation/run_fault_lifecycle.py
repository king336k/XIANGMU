"""Repair, reviewed fresh-data closure, publication, then blinded repeat with real APIs."""
import bcrypt,hashlib,hmac,json,os,subprocess,sys,time,zipfile
from pathlib import Path
from uuid import uuid4
import requests
from run_real_faults import sql,native
ROOT=Path(sys.argv[1]);ROOT.mkdir(parents=True,exist_ok=True)
ORIGINAL=ROOT.parent;main=json.loads((ORIGINAL/'http-state.json').read_text());first=main['cases'][0];case=json.loads((ORIGINAL/'case-01/http-state.json').read_text())
AUTH='http://127.0.0.1:16335';PLATFORM='http://127.0.0.1:18880';SOURCE='latest-native-verification';PROJECT=1491109
base=f"/api/workspaces/{main['workspace']}/projects/{main['project_id']}/quality/";kb=base.replace('/quality/','/knowledge/')
statepath=ROOT/'state.json';state=json.loads(statepath.read_text()) if statepath.exists() else {'actors':{role:{'name':'fault149-'+role.lower()+'-'+uuid4().hex[:9]} for role in ['Manager','TeamLeader','Annotator']},'repeat_session':str(uuid4()),'repeat_package':'repeat149-'+uuid4().hex,'repeat_key':str(uuid4())}
events=[]
def checkpoint(phase):
 state['phase']=phase;statepath.write_text(json.dumps(state,ensure_ascii=False,indent=2));(ROOT/'http-events.json').write_text(json.dumps(events,ensure_ascii=False,indent=2));print(json.dumps({'phase':phase,'events':len(events)},ensure_ascii=False),flush=True)
env=dict(row.split('=',1) for row in json.loads(subprocess.check_output(['docker','inspect','project-bridge-verification-20261109']))[0]['Config']['Env'])
def password(name):return hmac.new(env['PLATFORM_BOOTSTRAP_TOKEN'].encode(),('acceptance:'+name).encode(),hashlib.sha256).hexdigest()
for role,actor in state['actors'].items():
 if 'uid' not in actor:
  exists=sql(f"SELECT id FROM users WHERE username='{actor['name']}';")
  if not exists:
   digest=bcrypt.hashpw(password(actor['name']).encode(),bcrypt.gensalt()).decode();sql(f"INSERT INTO users(username,email,password,role,status) VALUES('{actor['name']}','{actor['name']}@example.invalid','{digest}','{role}','Active');")
  actor['uid']=int(sql(f"SELECT id FROM users WHERE username='{actor['name']}';"))
 sql(f"INSERT IGNORE INTO project_users(project_id,user_id,role,created_by) VALUES({PROJECT},{actor['uid']},'Member',1);")
checkpoint('actors_upstream_ready')
setup='''import os,json,sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE','plane.settings.production')
import django;django.setup()
from plane.db.models import User,Project,ProjectMember,WorkspaceMember
from plane.quality.models import PlatformIdentity,BusinessRole,PlatformAccount
v=json.load(sys.stdin);p=Project.objects.get(pk=v['project']);out={}
for role,item in v['actors'].items():
 account=PlatformAccount.objects.filter(source_instance=v['source'],external_user_id=item['uid']).first()
 u=account.user if account else User.objects.get_or_create(email=item['name']+'@example.invalid',defaults={'username':item['name'],'first_name':role})[0]
 WorkspaceMember.objects.get_or_create(workspace=p.workspace,member=u,defaults={'role':15})
 ProjectMember.objects.get_or_create(project=p,member=u,defaults={'workspace':p.workspace,'role':20 if role=='Manager' else 15})
 BusinessRole.objects.get_or_create(project=p,user=u,defaults={'role':{'Manager':'PROJECT_MANAGER','TeamLeader':'TECHNICIAN','Annotator':'REGRESSION_TESTER'}[role]})
 PlatformIdentity.objects.get_or_create(project=p,source_instance=v['source'],external_user_id=item['uid'],defaults={'user':u})
 out[role]=str(u.id)
print(json.dumps(out))
'''
ids=native(setup,{'project':main['project_id'],'source':SOURCE,'actors':state['actors']});state['native_ids']=ids
clients={}
def call(role,method,path,body=None,expected=(200,)):
 response=clients[role].request(method,PLATFORM+path,json=body,timeout=45);events.append({'role':role,'method':method,'path':path,'status':response.status_code})
 assert response.status_code in expected,(role,method,path,response.status_code,response.text[:500]);return response.json()
for role,actor in state['actors'].items():
 session=requests.Session();csrf=session.get(PLATFORM+'/auth/get-csrf-token/',timeout=20).json()['csrf_token'];session.headers.update({'X-CSRFToken':csrf,'Origin':PLATFORM,'Referer':PLATFORM+'/'});clients[role]=session
 call(role,'POST','/api/quality-auth/data-login/',{'source_instance':SOURCE,'username':actor['name'],'password':password(actor['name'])});session.headers['X-CSRFToken']=session.cookies.get('csrftoken') or csrf
 context=call(role,'GET',base+'context/')
 ids[role]=context['user_id']
 state['native_ids']=ids
def defect():return call('Manager','GET',base+f"defects/{case['defect_id']}/")
def patch(role,**values):return call(role,'PATCH',base+f"defects/{case['defect_id']}/",{'expected_version':defect()['edit_version'],**values})
if 'solution' not in state:
 repair=call('Manager','POST',base.split('/quality/')[0]+'/issues/',{'name':'隔离连接服务启动与回归'},expected=(201,));state['repair_issue_id']=repair['id']
 patch('Manager',assignee_id=ids['TeamLeader'],repair_issue_id=repair['id']);patch('TeamLeader',status='in_progress',resolution='核对运行日志、同一网络命名空间监听及配置目标')
 port=json.loads((ORIGINAL/'case-01/environment.json').read_text())['operation_target']['port'];state['repair_port']=port
 solution=call('TeamLeader','POST',base+'solutions/',{'defect_id':case['defect_id'],'title':'恢复隔离回环端点监听','root_cause':f'原日志ConnectionRefusedError errno111，目标127.0.0.1:{port}在同一网络命名空间无监听。不能据此判为机器人硬件损坏。',
 'steps':f'保持DAQ同一目标127.0.0.1:{port}，先启动隔离TCP监听服务，确认监听就绪再连接；接收ACK；写入4096字节样本并回读比对SHA256。',
 'verification':'修复送测之后创建新Session，保留原目标连接失败及启动监听后的ACK成功日志、样本SHA256；由测试员回读权威平台新包READY，再由经理关闭时再次复读。',
 'risk':'仅隔离软件场景，无物理机器人','rollback':'停止隔离监听服务，删除测试容器'},expected=(201,))
 solution=call('TeamLeader','POST',base+f"solutions/{solution['id']}/submit/",{'expected_version':solution['edit_version'],'reviewer_ids':[ids['Manager']],'required_count':1})
 rev=max(solution['revisions'],key=lambda row:row['version']);solution=call('Manager','POST',base+f"solutions/{solution['id']}/review/",{'revision_id':rev['id'],'decision':'approve','comment':'按同一目标及真实ACK和新数据SHA回读验证，不以状态修改替代修复。'})
 state['solution']=solution;checkpoint('reviewed_solution')
if 'plan' not in state:
 patch('TeamLeader',status='resolved',fixed_build='faultlab-listener-v1',resolution='按审核方案启动受控监听；送测新Session及实际样本验证')
 row=call('TeamLeader','POST',base+f"defects/{case['defect_id']}/data-regressions/",{'solution_id':state['solution']['id'],'environment':'networknone隔离DAQ，真实TCP监听与样本回读'},expected=(201,));plan=row['plan']
 plan=call('Manager','POST',base+f"plans/{plan['id']}/workflow/",{'action':'assign','expected_version':plan['workflow_version'],'assignee_id':ids['Annotator']})
 plan=call('Annotator','POST',base+f"plans/{plan['id']}/workflow/",{'action':'claim','expected_version':plan['workflow_version']});state['plan']=plan;checkpoint('fresh_regression_created')
if 'repair_proof' not in state:
 time.sleep(1.1);name='fault149-repair-'+uuid4().hex[:8];script=Path(__file__).with_name('repair_operation.py').resolve()
 command=['docker','create','--name',name,'--network','none','--memory','512m','--cpus','1','--tmpfs','/work:rw,size=16m,mode=1777','-v',str(script)+':/harness/operation.py:ro','--entrypoint','python3','engram-daq-backend:latest','/harness/operation.py',str(state['repair_port'])]
 subprocess.run(command,check=True,capture_output=True)
 try:
  subprocess.run(['docker','start',name],check=True,capture_output=True)
  for attempt in range(60):
   logs=subprocess.check_output(['docker','logs',name],stderr=subprocess.STDOUT)
   if b'EVIDENCE_CAPTURE_READY' in logs:break
   time.sleep(.2)
  else:raise RuntimeError('repair evidence incomplete')
  (ROOT/'repair-system.log').write_bytes(logs)
  proof=json.loads(subprocess.check_output(['docker','exec',name,'cat','/work/observations.json']));(ROOT/'repair-observations.json').write_text(json.dumps(proof,indent=2))
  sample=subprocess.check_output(['docker','exec',name,'cat','/work/sample.bin']);(ROOT/'sample.bin').write_bytes(sample)
  assert proof['before']['errno']==111 and proof['after']['endpoint_connected'] and proof['after']['reply']=='ACK' and hashlib.sha256(sample).hexdigest()==proof['after']['sha256']
  state['repair_proof']=proof
 finally:subprocess.run(['docker','rm','-f',name],capture_output=True)
 state['new_session']=str(uuid4());state['new_package']='repair149-'+uuid4().hex;checkpoint('actual_listener_repair_and_new_sample')
plan=state['plan'];evidence=base+f"plans/{plan['id']}/data-evidence/"
if 'regression_completed' not in state:
 sql(f"SET time_zone='+08:00'; INSERT IGNORE INTO data_packages(id,task_id,user_id,name,source_session_id,status,recorded_at,uploaded_at,created_at,updated_at) VALUES('{state['new_package']}',{first['task']},{first['uid']},'隔离服务修复实际新样本','{state['new_session']}','Transferring',NOW(),NOW(),NOW(),NOW());")
 call('Annotator','POST',evidence,{'source_session_id':first['session']},expected=(400,));call('Annotator','POST',evidence,{'source_session_id':state['new_session']},expected=(400,))
 sql(f"UPDATE data_packages SET status='PendingAnnotation' WHERE id='{state['new_package']}';")
 linked=call('Annotator','POST',evidence,{'source_session_id':state['new_session']},expected=(201,));assert linked['package_id']==state['new_package'];state['data_evidence']=linked
 execution=call('Annotator','POST',base+f"items/{plan['items'][0]['id']}/executions/",{'request_id':str(uuid4()),'result':'passed','actual_result':f"同一目标127.0.0.1:{state['repair_port']}恢复监听后TCP ACK成功，4096字节实际样本回读SHA256={state['repair_proof']['after']['sha256']}；新Session及平台就绪状态已回读。",'evidence':'实际隔离DAQ日志和repair-observations.json；原Session和未就绪新包均被拒绝'},expected=(201,));state['execution']=execution
 plan=call('Annotator','POST',base+f"plans/{plan['id']}/workflow/",{'action':'submit','expected_version':plan['workflow_version']});state['plan']=plan
 call('Annotator','POST',base+f"plans/{plan['id']}/workflow/",{'action':'approve','expected_version':plan['workflow_version']},expected=(403,))
 sql(f"UPDATE data_packages SET status='ConvertFailed' WHERE id='{state['new_package']}';")
 call('Manager','POST',base+f"plans/{plan['id']}/workflow/",{'action':'approve','expected_version':plan['workflow_version']},expected=(400,));assert defect()['status']=='resolved'
 sql(f"UPDATE data_packages SET status='PendingAnnotation' WHERE id='{state['new_package']}';")
 plan=call('Manager','POST',base+f"plans/{plan['id']}/workflow/",{'action':'approve','expected_version':plan['workflow_version']});assert plan['status']=='completed' and defect()['status']=='closed'
 state['plan']=plan;state['regression_completed']=True;checkpoint('actual_repair_new_session_readback_and_closed')
if 'published' not in state:
 rows=call('Manager','GET',kb+'articles/?status=draft')['results'];article=next(row for row in rows if row.get('source_defect_id')==case['defect_id'])
 (ROOT/'knowledge-draft.json').write_text(json.dumps(article,ensure_ascii=False,indent=2))
 assert article['source_regression_id'] and 'ConnectionRefusedError' in article['content'] and 'ACK' in article['content'] and state['new_session'] in article['content']
 wf=kb+f"articles/{article['id']}/workflow/";scanned=call('Manager','POST',wf,{'action':'scan','expected_version':article['edit_version']});assert not scanned['scan_findings']
 published=call('Manager','POST',wf,{'action':'publish','expected_version':scanned['edit_version']});assert published['publication_active'] and published['status']=='published'
 state['published']=published;(ROOT/'knowledge-published.json').write_text(json.dumps(published,ensure_ascii=False,indent=2));checkpoint('knowledge_scanned_and_published')
# The second report is a genuinely new closed-port operation, not a rewritten first report.
if 'repeat_result' not in state:
 repeat=ROOT/'repeat';repeat.mkdir(exist_ok=True)
 if not (repeat/'case-01/material.zip').exists():
  subprocess.run([sys.executable,str(Path(__file__).with_name('generate_controlled_faults.py')),str(repeat),'--case','1'],check=True)
 # Only oracle outside material.zip records expected cause; no oracle file is opened by the upload/model path.
 sql(f"SET time_zone='+08:00'; INSERT IGNORE INTO data_packages(id,task_id,user_id,name,source_session_id,status,recorded_at,uploaded_at,created_at,updated_at) VALUES('{state['repeat_package']}',{first['task']},{first['uid']},'隔离运行复查记录','{state['repeat_session']}','PendingAnnotation',NOW(),NOW(),NOW(),NOW());")
 login=requests.post(AUTH+'/api/daq/auth/login',json={'username':first['name'],'password':password(first['name'])},timeout=30);assert login.status_code==200 and login.json()['code']==1
 headers={'Authorization':'Bearer '+login.json()['data']['accessToken'],'Idempotency-Key':state['repeat_key']}
 def bridge(method,path,data=None,files=None,expected=(200,)):
  response=requests.request(method,AUTH+'/issue-api'+path,headers=headers,json=data if files is None else None,files=files,timeout=45);events.append({'role':'repeat-collector','method':method,'path':path,'status':response.status_code});assert response.status_code in expected,(path,response.status_code,response.text[:400]);return response.json()
 # Resolve a new real source Session against the existing authoritative task binding.
 payload={'sourceRecordId':state['repeat_session'],'platformTaskId':first['task'],'category':'Other','title':'隔离采集异常复查编号06','description':'新的隔离运行记录，请依据本次完整日志、配置及环境观测判断异常、证据边界和后续验证。无物理机器人连接。'}
 receipt=bridge('POST',base+'daq/reports/',payload,expected=(200,201));assert receipt['issueId']!=case['defect_id'];state['repeat_defect_id']=receipt['issueId'];state['repeat_code']=receipt['issueCode'];checkpoint('new_repeat_report')
 raw=(repeat/'case-01/material.zip').read_bytes();digest=hashlib.sha256(raw).hexdigest()
 package=bridge('POST',base+'packages/',{'name':'新的隔离运行观测材料','defect_id':receipt['issueId'],'source_system':'ENGRAM_DAQ','external_id':'repeat-'+state['repeat_key'],'files':[{'path':'material.zip','size':len(raw),'sha256':digest}]},expected=(200,201))
 uploaded=bridge('POST',base+f"packages/{package['id']}/files/",files={'file':('material.zip',raw,'application/zip')},expected=(200,201));state['repeat_file_id']=uploaded['id'];checkpoint('repeat_complete_material_uploaded')
 deadline=time.monotonic()+200;job=None
 while time.monotonic()<deadline:
  detail=bridge('GET',base+f"daq/issues/{receipt['issueId']}/");(ROOT/'repeat-http-detail.json').write_text(json.dumps(detail,ensure_ascii=False,indent=2))
  candidates=[row for row in detail['diagnostics'] if any(s.get('file_id')==uploaded['id'] for s in row.get('result',{}).get('sources',[]))];job=candidates[0] if candidates else None
  if job and job['status'] not in {'queued','running'}:break
  time.sleep(2)
 assert job and job['result']['model_status']=='completed';state['repeat_result']=job;(ROOT/'repeat-model-output.json').write_text(json.dumps(job,ensure_ascii=False,indent=2));checkpoint('repeat_model_completed')
publications=call('Manager','GET',kb+'search/?q=ConnectionRefusedError')['results'];(ROOT/'knowledge-search-result.json').write_text(json.dumps(publications,ensure_ascii=False,indent=2))
article_id=state['published']['id'];current=next(row for row in publications if row['article_id']==article_id)
kn=[row for row in state['repeat_result']['result'].get('citations',[]) if row.get('reference','').startswith('KN-')]
state['knowledge_repeat_validation']={'expected_reference':current['reference'],'citations':[row['reference'] for row in kn],'same_project_current_publication':all(row['reference']==current['reference'] for row in kn),'cited_published_knowledge':any(row['reference']==current['reference'] for row in kn)}
checkpoint('repeat_knowledge_citation_verified' if state['knowledge_repeat_validation']['cited_published_knowledge'] else 'repeat_knowledge_not_cited')
