"""One real diagnostic over the unchanged repeat evidence; missing confidence is not success."""
import json,sys,time,subprocess
from pathlib import Path
from uuid import uuid4
prefix=Path(__file__).with_name('run_fault_lifecycle.py').read_text().split("if 'solution' not in state:")[0]
exec(compile(prefix,str(Path(__file__).with_name('run_fault_lifecycle.py')),'exec'))
output=Path('/home/engram/Documents/tmp/artifacts/confidence-coverage/model');output.mkdir(parents=True,exist_ok=True)
expected='817edae817f5f06a9c44df6602cf26e965f60f3ce9eed74357d3471ab6f566b6'
for container in ['plane-local-20261106-api-1','plane-local-20261106-diagnostic-worker-1']:
 actual=subprocess.check_output(['docker','exec',container,'sha256sum','/code/plane/quality/diagnostic_model.py'],text=True).split()[0]
 assert actual==expected,'Confidence boundary not deployed'
agent_hash=subprocess.check_output(['docker','exec','plane-local-20261106-diagnostic-worker-1','sha256sum','/opt/diagnostic-agent/runner.py'],text=True).split()[0]
assert agent_hash=='1fd387c0d55f8a0a2cacbb78a2b0d3437ca78c9865e193f1689b0ab339d52181','Typed agent not deployed'
state.setdefault('confidence_request_id',str(uuid4()));checkpoint('confidence_key_saved')
created=call('Manager','POST',base+f"defects/{state['repeat_defect_id']}/diagnostics/",{'request_id':state['confidence_request_id'],'mode':'llm'},expected=(200,201));state['confidence_job_id']=created['id'];checkpoint('confidence_job_queued')
start=time.monotonic()
while time.monotonic()-start<200:
 job=call('Manager','GET',base+f"diagnostics/{created['id']}/")
 (output/'actual-model-output.json').write_text(json.dumps(job,ensure_ascii=False,indent=2))
 if job['status'] not in {'queued','running'}:break
 time.sleep(2)
result=job.get('result',{});value=result.get('model_confidence');present=type(value) in {int,float} and 0<=value<=1
refs=[row['reference'] for row in result.get('confidence_references',[])];citations=[row['reference'] for row in result.get('citations',[])]
proof={'job_id':job['id'],'defect_id':job['defect_id'],'model_status':result.get('model_status'),'model_confidence':value,'evidence_assessment':result.get('evidence_assessment'),'confidence_basis':result.get('confidence_basis'),'confidence_references':refs,'model_info':result.get('model_info'),'model_usage':result.get('model_usage'),'duration_ms':result.get('duration_ms'),'score_is_model_self_assessment_not_correctness_probability':True,'field_acceptance_passed':bool(job['status']=='completed' and result.get('model_status')=='completed' and present and result.get('confidence_basis') and result.get('evidence_assessment') in {'supported','partial','insufficient'} and refs and set(refs)<=set(citations))}
(output/'actual-confidence-proof.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2));print(json.dumps(proof,ensure_ascii=False),flush=True)
