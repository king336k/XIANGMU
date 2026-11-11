"""Run five isolated real operations. Ground truth stays outside evidence bundles."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time
import zipfile
from datetime import datetime,timezone

TRUTH={1:{'cause':'loopback endpoint has no listener','type':'ConnectionRefusedError','errno':111,'required':['connection refused','监听']},2:{'cause':'8MiB container tmpfs capacity exhausted','type':'OSError','errno':28,'required':['空间','tmpfs']},3:{'cause':'nonroot process cannot traverse root-owned0500 directory','type':'PermissionError','errno':13,'required':['权限','uid']},4:{'cause':'DAQ ROS1 configuration missing local_ip','type':'PreflightError','code':'LOCAL_IP_MISSING','required':['local_ip','配置']},5:{'cause':'normal control: file write/readback and loopback connection succeed','type':None,'required':[]}}
def main():
    parser=argparse.ArgumentParser();parser.add_argument('artifact',type=Path);parser.add_argument('--case',type=int,choices=range(1,6));args=parser.parse_args();root=args.artifact;root.mkdir(parents=True,exist_ok=True)
    script=Path(__file__).with_name('controlled_faults.py').resolve();image='engram-daq-backend:latest';image_id=subprocess.check_output(['docker','image','inspect',image,'--format','{{.Id}}'],text=True).strip()
    truth={'provenance':'controlled_real_software_operations','physical_robot':False,'cases':[]}
    for number in ([args.case] if args.case else range(1,6)):
        case=root/f'case-{number:02}';case.mkdir(exist_ok=True);name='diagnostic-blind-'+root.name[-8:]+'-'+str(number)
        command=['docker','create','--name',name,'--network','none','--memory','512m','--cpus','1','--pids-limit','128','--tmpfs','/work:rw,size=32m,mode=1777','--tmpfs','/work/payload:rw,size=8m,mode=1777','-v',str(script)+':/harness/operation.py:ro','--entrypoint','python3',image,'/harness/operation.py',str(number)]
        created=subprocess.run(command,capture_output=True,text=True)
        if created.returncode:raise RuntimeError('Cannot create isolated evidence container')
        try:
            subprocess.run(['docker','start',name],capture_output=True,check=True)
            for attempt in range(60):
                output=subprocess.check_output(['docker','logs',name],stderr=subprocess.STDOUT)
                if b'EVIDENCE_CAPTURE_READY' in output:break
                time.sleep(.2)
            else:raise RuntimeError('Evidence generator did not complete: '+output.decode()[-1500:])
            (case/'environment.json').write_bytes(subprocess.check_output(['docker','exec',name,'cat','/work/environment.json']))
            (case/'capture_manifest.json').write_bytes(subprocess.check_output(['docker','exec',name,'cat','/work/capture_manifest.json']))
            (case/'observations.json').write_bytes(subprocess.check_output(['docker','exec',name,'cat','/work/observations.json']))
            logs=subprocess.check_output(['docker','logs','--timestamps',name],stderr=subprocess.STDOUT);(case/'system.log').write_bytes(logs)
            state=json.loads(subprocess.check_output(['docker','inspect',name]))[0]
            runtime={'image_id':image_id,'network_mode':state['HostConfig']['NetworkMode'],'tmpfs':state['HostConfig']['Tmpfs'],'container_status':state['State']['Status'],'exit_code_if_exited':state['State']['ExitCode'] if state['State']['Status']=='exited' else None,'oom_killed':state['State']['OOMKilled'],'recorded_at':datetime.now(timezone.utc).isoformat()}
            (case/'runtime.json').write_text(json.dumps(runtime,indent=2))
        finally:subprocess.run(['docker','rm','-f',name],capture_output=True)
        observed=json.loads((case/'observations.json').read_text());expected=TRUTH[number]
        if number<5:
            assert observed['exception_type']==expected['type'],(number,observed)
            if 'errno' in expected:assert observed['errno']==expected['errno']
            if 'code' in expected:assert observed['code']==expected['code'],observed
        else:assert observed['operation_completed'] and observed['endpoint_connected'] and observed['readback_bytes']==4096
        archive=case/'material.zip'
        with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as bundle:
            for filename in ['system.log','environment.json','capture_manifest.json','runtime.json']:
                bundle.write(case/filename,filename)
        truth['cases'].append({'case_id':number,**expected,'observed':observed,'bundle_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'bundle_bytes':archive.stat().st_size})
        (root/'ground_truth.json').write_text(json.dumps(truth,ensure_ascii=False,indent=2));print(json.dumps({'case':number,'bytes':archive.stat().st_size,'actual_exception':observed.get('exception_type'),'complete':True}),flush=True)
if __name__=='__main__':main()
