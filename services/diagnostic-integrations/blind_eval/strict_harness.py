"""Raw-only model evidence and model-authored configuration patch evaluation."""
import asyncio
import copy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import secrets
import threading
import time
import uuid

from harness import IsolatedCase, digest, load_module, save, utc


class StrictCase(IsolatedCase):
    def __init__(self,root,daq,approved=True,fault_kind=None):
        super().__init__(root,daq,approved,fault_kind)
        # The raw scenario describes the failure stage, never a YAML key,
        # group or index. The model must discover all configuration facts.
        self.log=[f'{utc()} [INFO] reset requested',f'{utc()} [ERROR] reset goal validation failed',
                  f'{utc()} [ERROR] RESET_ERROR type=planning_failed reset_aborted']
        (self.root/'fixture-node.log').write_text('\n'.join(self.log)+'\n')
        self.daq=daq
        self.module=load_module('strict_config_'+uuid.uuid4().hex,
            daq/'src/engram_Teleop_DAQ_web/backend/app/launcher/robot/configuration_diagnostics.py')
        self.current_alias='current/'+str(self.relative)
        self.current_path=self.state/'robot_config_effective'/self.relative
        self.reads={};self.patch_receipts=[]
        self.allowed_reads={self.current_alias:self.current_path,
            'baseline/'+str(self.relative):self.baseline/self.relative,
            'baseline/manifest.json':self.baseline/'manifest.json',
            'device/pre-fault-snapshot.json':self.root/'pre-fault-snapshot.json'}
        remote=daq/'src/remote_control_robot'
        paths=['deploy/src/unified_ik/include/unified_ik/reset_home_config.h',
               'deploy/src/unified_ik/src/unified_ik_node.cpp',
               'deploy/src/core/src/pinocchio_kinematics/reset_trajectory_planner.cpp']
        self.sources={path:remote/path for path in paths if (remote/path).is_file()}
        try:
            import subprocess
            self.source_revision=subprocess.check_output(['git','-c','safe.directory='+str(remote),'-C',str(remote),'rev-parse','HEAD'],text=True,
                stderr=subprocess.DEVNULL).strip()
        except Exception:self.source_revision=None

    def raw_inspect(self):
        # Values, semantic findings, changed fields and repair proposals are
        # deliberately absent. Raw documents are available only after reads.
        return {'action':'inspect','scope':'configuration_validation','mode':'raw_evidence',
            'checks':[{'name':'evidence_catalog','state':'pass'}],
            'configuration':{'state':'not_evaluated','repair_allowed':self.approved,
                'repair_authority':'device_approved_snapshot' if self.approved else 'release_candidate'},
            'read_only_roots':['current/','baseline/','device/'],
            'file_index':[{'path':alias,'bytes':path.stat().st_size} for alias,path in self.allowed_reads.items()],
            'editable_files':[self.current_alias],
            'source_catalog':[{'id':'teleop-source','kind':'approved_local_git_snapshot',
                               'repository_commit':self.source_revision}],
            'node_observations':[{'name':'unified_ik','running':True,'source_path':str(self.root/'fixture-node.log'),
                                  'lines':self.log}],
            'business_not_evaluated':['robot_reset','motion','collection'],'verified':False,'exit_code':0}

    def read_raw(self,path):
        if path not in self.allowed_reads:return {'error':'raw_file_not_allowlisted'}
        raw=self.allowed_reads[path].read_bytes()
        self.reads[path]=digest(raw)
        return {'path':path,'resolved_path':str(self.allowed_reads[path]),'content':raw.decode(),
            'sha256':digest(raw),'line':1,'ok':True}

    def patch_model_content(self,path,sha,content):
        def denied(reason):return {'ok':False,'exit_code':1,'error':reason}
        if path!=self.current_alias:return denied('patch_target_not_allowlisted')
        if not isinstance(content,str) or len(content.encode())>65536:return denied('bounded_yaml_content_required')
        before_bytes=self.current_path.read_bytes()
        if self.reads.get(path)!=sha or digest(before_bytes)!=sha:return denied('current_file_sha_conflict')
        observed=self.service.inspect(self.robot)
        if observed.get('snapshot_sha256')!=self.before['snapshot_sha256']:return denied('configuration_snapshot_changed')
        try:
            candidate=self.module._document(content.encode())
            old=self.module._document(before_bytes)
        except Exception:return denied('candidate_yaml_invalid')
        if self.module.validate_description(candidate):return denied('candidate_semantics_invalid')
        if not isinstance(candidate,dict) or set(candidate)!=set(old):return denied('unapproved_document_change')
        if any(candidate[key]!=old[key] for key in old if key!='initial_joint_states'):
            return denied('only_initial_joint_states_may_change')
        try:trusted,manifest_sha=self.service._trusted(self.robot)
        except Exception:return denied('baseline_integrity_failed')
        changes=[]
        for group,before in old['initial_joint_states'].items():
            after=candidate['initial_joint_states'].get(group)
            limits=old['joint_limits'][group]
            if not isinstance(before,list) or len(before)!=len(old['joints_name'][group]):
                if after!=trusted['initial_joint_states'][group]:return denied('unsupported_candidate_value')
                changes.append({'key':'initial_joint_states.'+group,'before':before,'after':after})
                continue
            for index,(previous,proposed) in enumerate(zip(before,after)):
                valid=self.module._number(previous) and limits[index][0]<=previous<=limits[index][1]
                equal=(previous==proposed and (valid or type(previous) is type(proposed)))
                if equal:continue
                if valid:return denied('valid_operator_value_must_be_preserved')
                if proposed!=trusted['initial_joint_states'][group][index]:return denied('unsupported_candidate_value')
                changes.append({'key':f'initial_joint_states.{group}[{index}]',
                                'before':previous if self.module._number(previous) else None,'after':proposed})
        if not changes:return denied('empty_patch')
        if not self.approved:return denied('baseline_not_approved_for_device')
        authority=self.service._authority(self.robot,manifest_sha,observed['snapshot_sha256'],[row['key'] for row in changes])
        if authority!='explicit_repair_plan':return denied('independent_plan_not_valid')
        approval_sha=digest(self.service.approval_file.read_bytes())
        override=self.service.overrides/self.robot/'initial_joint_states.yaml'
        override.parent.mkdir(parents=True,exist_ok=True)
        if override.resolve()!=override.absolute():return denied('override_symlink_rejected')
        backup=override.with_name(override.name+'.backup-'+uuid.uuid4().hex)
        temporary=override.with_name('.model-patch-'+uuid.uuid4().hex)
        written=False
        # Written values come solely from the model's candidate document. The
        # trusted original is used to reject unauthorized changes, never write.
        import fcntl,os
        with (self.state/'.strict-model-patch.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            if digest(self.current_path.read_bytes())!=sha or self.service.inspect(self.robot)['snapshot_sha256']!=observed['snapshot_sha256']:
                return denied('configuration_changed_during_patch')
            if digest(self.service.approval_file.read_bytes())!=approval_sha:return denied('approval_changed')
            if self.service._authority(self.robot,manifest_sha,observed['snapshot_sha256'],[row['key'] for row in changes])!=authority:
                return denied('approval_expired_or_changed')
            try:
                if self.service._trusted(self.robot)[1]!=manifest_sha:return denied('baseline_changed')
            except Exception:return denied('baseline_integrity_failed')
            self.module._exclusive_write(backup,override.read_bytes() if override.exists() else b'',0o600)
            data=self.yaml.safe_dump({'initial_joint_states':candidate['initial_joint_states']},sort_keys=False).encode()
            receipt={'ok':False,'exit_code':1,'state':'written_runtime_unverified','actual_write':False,
                'changes':changes,'backup':str(backup),'resolved_path':str(override),
                'submitted_content_sha256':digest(content.encode()),'source_of_written_values':'model_submitted_content'}
            try:
                self.module._exclusive_write(temporary,data,0o644)
                os.replace(temporary,override);written=True;receipt['actual_write']=True
                for row in changes:row.update(path=str(override),backup=str(backup),target_kind='collector',line=1)
                self.refresh()
                after=self.service.inspect(self.robot)
                if after['state']=='pass':receipt.update(ok=True,exit_code=0,state='applied',sha256=digest(data))
            except Exception as error:receipt['verification_error']=type(error).__name__
            finally:temporary.unlink(missing_ok=True)
            self.patch_receipts.append(receipt)
            return receipt

    def strict_rpc(self,body):
        op=body.get('operation')
        if op=='run' and body.get('argv')==['daq-local-diagnostics-v1','inspect']:
            value=self.raw_inspect();response={'ok':True,'exit_code':0,'stdout':json.dumps(value,ensure_ascii=False),'stderr':''}
        elif op=='run' and body.get('argv')==['daq-local-diagnostics-v1','verify']:
            observed=self.service.inspect(self.robot);passed=observed['state']=='pass'
            value={'scope':'configuration_validation','verified':passed,'exit_code':0 if passed else 1,
                'checks':[{'name':'configuration_semantics','state':'pass' if passed else 'fail'}],
                'business_not_evaluated':['robot_reset','motion','collection']}
            response={'ok':True,'exit_code':value['exit_code'],'stdout':json.dumps(value),'stderr':''}
        elif op=='read_file':response=self.read_raw(body.get('path'))
        elif op=='patch_file':response=self.patch_model_content(body.get('path'),body.get('expected_sha256'),body.get('content'))
        elif op=='knowledge':response={'source':'isolated_empty_knowledge','results':[],'case_history':[]}
        elif op=='catalog':response={'sources':[{'id':'teleop-source','kind':'local_git_snapshot','repository_commit':self.source_revision}]}
        elif op in {'list_source_paths','read_source','search_source'} and body.get('source_id')=='teleop-source':
            response=self.source_rpc(body)
        else:response={'error':'fixed_raw_tool_contract_only'}
        self.events.append({'at':utc(),'request':body,'response':response})
        return response

    def source_rpc(self,body):
        op=body['operation'];offset=body.get('offset',0)
        if type(offset) is not int or offset<0:return {'error':'invalid_offset'}
        if op=='list_source_paths':
            prefix=body.get('path','')
            return {'source_id':'teleop-source','repository_commit':self.source_revision,
                'paths':[{'path':path,'bytes':file.stat().st_size} for path,file in self.sources.items() if path.startswith(prefix)][offset:offset+50],
                'next_offset':None}
        if op=='read_source' and body.get('path') in self.sources:
            file=self.sources[body['path']];raw=file.read_bytes();chunk=raw[offset:offset+12000]
            return {'source_id':'teleop-source','path':body['path'],'repository_commit':self.source_revision,
                'content':chunk.decode(errors='replace'),'line':raw[:offset].count(b'\n')+1,
                'next_offset':offset+len(chunk) if offset+len(chunk)<len(raw) else None,'sha256':digest(raw)}
        if op=='search_source' and isinstance(body.get('query'),str) and 0<len(body['query'])<=100:
            query=body['query'];matches=[]
            for path,file in self.sources.items():
                for index,line in enumerate(file.read_text(errors='replace').splitlines(),1):
                    if query in line:matches.append({'path':path,'line':index,'content':line[:1000]})
            return {'source_id':'teleop-source','repository_commit':self.source_revision,'matches':matches[:20]}
        return {'error':'source_path_not_allowlisted'}

    def strict_score(self,result,model_called):
        # Reuse hidden objective scoring only; mark raw-mode independent patch
        # receipts as successful mutation evidence without generating changes.
        base=super().score(result,model_called=model_called)
        submitted=[event for event in self.events if event['request'].get('operation')=='patch_file']
        successful=any(receipt.get('state')=='applied' and receipt.get('actual_write') for receipt in self.patch_receipts)
        if self.approved:base['checks']['actual_repair_executed']=successful
        base['checks']['inspect_contains_no_semantic_answer']=all(
            not any(key in json.loads(event['response']['stdout']).get('configuration',{})
                for key in ('findings','artifact_findings','suggested_changes'))
            for event in self.events if event['request'].get('argv')==['daq-local-diagnostics-v1','inspect'])
        base['checks']['model_submitted_content_used']=bool(submitted) and successful if self.approved else not successful
        base['progress']['actual_configuration_write']=successful
        base['progress']['model_patch_submission_count']=len(submitted)
        base['evaluation_scope']='strict_raw_evidence_model_authored_patch_no_robot_reset'
        base['passed']=all(base['checks'].values())
        return base


async def evaluate_strict(case,runner,config):
    token=secrets.token_hex(24)
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.headers.get('Authorization')!='Bearer '+token:self.send_error(403);return
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=262144:raise ValueError('request_size')
                body=json.loads(self.rfile.read(size))
                with case.lock:response=case.strict_rpc(body)
                raw=json.dumps(response,ensure_ascii=False).encode()
                self.send_response(200);self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
            except Exception:self.send_error(409,'fixed_strict_fixture_request_failed')
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    payload={'config':config,'gateway_url':f'http://127.0.0.1:{server.server_port}/rpc','tool_token':token,
        'research_url':f'http://127.0.0.1:{server.server_port}/research',
        'problem':'设备复位失败，请排查并完成能够确认的修复及验证。',
        'context':{'inspect_argv':['daq-local-diagnostics-v1','inspect'],
            'verify_argv':['daq-local-diagnostics-v1','verify'],'verification_scope':'configuration_validation',
            'repair_allowed':True,'operation_mode':'repair','require_knowledge_search':True,
            'editable_files':[case.current_alias],
            'repair_scope':'仅允许对列出的当前配置文件提交完整YAML；先读取实际文件及独立设备认可来源，修改需满足服务端授权，不能放宽安全限制。',
            'feedback_materials':{'sources':[{'source':'isolated_node_log','excerpt':'\n'.join(case.log)}]}}}
    runtime={};started=time.monotonic()
    try:
        try:result=await asyncio.wait_for(runner.analyze(payload,runtime),timeout=295)
        except Exception as error:result=runner.failed_analysis(payload,runtime,error)
        gateway=runtime.get('gateway')
        redact=lambda value:runner.redact(value,[config['api_key'],token])
        save(case.root/'model-report.json',redact(result))
        save(case.root/'actual-tool-trajectory.json',redact(case.events))
        save(case.root/'model-patch-receipts.json',case.patch_receipts)
        save(case.root/'runner-receipts.json',redact({'gateway_evidence':gateway.evidence if gateway else [],
            'executions':gateway.executions if gateway else [],
            'validation_journal':getattr(gateway,'validation_journal',[]) if gateway else [],
            'elapsed_seconds':round(time.monotonic()-started,3),'model_name':config['model']}))
        score=case.strict_score(result,True if case.events else None);save(case.root/'score.json',score)
        return score
    finally:server.shutdown();server.server_close();thread.join(timeout=2)
