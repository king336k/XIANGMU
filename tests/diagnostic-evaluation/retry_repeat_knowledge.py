"""One new diagnostic attempt over the exact unchanged repeat report/materials after retrieval fix."""
import json,time,hashlib,subprocess
from pathlib import Path
from uuid import uuid4
# Initialize only the same isolated role sessions; never rerun the repair or second report.
prefix=Path(__file__).with_name('run_fault_lifecycle.py').read_text().split("if 'solution' not in state:")[0]
exec(compile(prefix,str(Path(__file__).with_name('run_fault_lifecycle.py')),'exec'))
expected='96387234ff46929cb0c16d6aca308e4329fe8959cc9c012df1ece60f9b33731c'
for container in ['plane-local-20261106-api-1','plane-local-20261106-diagnostic-worker-1']:
 value=subprocess.check_output(['docker','exec',container,'sha256sum','/code/plane/quality/diagnostic_materials.py'],text=True).split()[0]
 assert value==expected,'Runtime retrieval fix not deployed'
state.setdefault('repeat_retry_request_id',str(uuid4()));checkpoint('retry_request_key_saved')
original=ROOT/'repeat-model-output.json';before=hashlib.sha256(original.read_bytes()).hexdigest()
created=call('Manager','POST',base+f"defects/{state['repeat_defect_id']}/diagnostics/",{'request_id':state['repeat_retry_request_id'],'mode':'llm'},expected=(200,201))
state['repeat_retry_job_id']=created['id'];checkpoint('repeat_retry_queued')
start=time.monotonic()
while time.monotonic()-start<200:
 job=call('Manager','GET',base+f"diagnostics/{created['id']}/")
 (ROOT/'repeat-retry-model-output.json').write_text(json.dumps(job,ensure_ascii=False,indent=2))
 if job['status'] not in {'queued','running'}:break
 time.sleep(2)
assert job['status']=='completed' and job['result']['model_status']=='completed',job.get('error_code')
rows=call('Manager','GET',kb+'search/?q=ConnectionRefusedError')['results'];current=next(row for row in rows if row['article_id']==state['published']['id'])
kn=[row for row in job['result']['citations'] if row['reference'].startswith('KN-')]
assert hashlib.sha256(original.read_bytes()).hexdigest()==before
state['retry_validation']={'old_output_preserved':True,'same_repeat_defect':job['defect_id']==state['repeat_defect_id'],'expected_reference':current['reference'],'knowledge_citations':[row['reference'] for row in kn],'cited_current_same_project_knowledge':any(row['reference']==current['reference'] for row in kn),'model_usage':job['result'].get('model_usage'),'duration_ms':job['result'].get('duration_ms')}
(ROOT/'repeat-knowledge-validation.json').write_text(json.dumps(state['retry_validation'],ensure_ascii=False,indent=2));checkpoint('repeat_current_knowledge_cited' if state['retry_validation']['cited_current_same_project_knowledge'] else 'repeat_current_knowledge_still_not_cited')
print(json.dumps(state['retry_validation'],ensure_ascii=False),flush=True)
