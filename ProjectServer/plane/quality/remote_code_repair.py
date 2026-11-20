# SPDX-License-Identifier: AGPL-3.0-only
"""Permission-scoped central bridge to the fixed isolated code repair service."""
import http.client
import json
import os
import re
import time
from urllib.parse import urlsplit

MAX_RESPONSE=256*1024
TTL=900


def _cache():
    from django.core.cache import cache
    return cache


def _provider(workspace_id):
    from plane.knowledge.assistant import provider_config
    return provider_config(workspace_id)


def _catalog(root,project_id):
    from .remote_source_snapshots import catalog
    return catalog(root,project_id)


def _scope(run):
    return {'run':str(run.pk),'owner':str(run.owner_id),'project':str(run.defect.project_id)}


def _configuration():
    token=os.environ.get('REMOTE_CODE_REPAIR_TOKEN','');url=os.environ.get('REMOTE_CODE_REPAIR_URL','')
    parts=urlsplit(url)
    if (len(token)<24 or parts.scheme not in {'http','https'} or not parts.hostname or parts.username or parts.password
            or parts.query or parts.fragment or parts.path not in {'','/'}):raise ValueError('code_worker_not_configured')
    return parts,token


def _request(method,path,payload=None,read_timeout=10):
    parts,token=_configuration()
    cls=http.client.HTTPSConnection if parts.scheme=='https' else http.client.HTTPConnection
    connection=cls(parts.hostname,parts.port,timeout=2)
    try:
        connection.connect();connection.sock.settimeout(min(10,max(.1,read_timeout)))
        connection.request(method,path,body=json.dumps(payload).encode() if payload is not None else None,
            headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
        response=connection.getresponse()
        if response.status==503:return {'error':'code_worker_busy','note':'代码工作区正忙，请稍后。'}
        if response.status not in {200,202}:return {'error':'code_worker_request_failed','http_status':response.status}
        raw=response.read(MAX_RESPONSE+1)
        if len(raw)>MAX_RESPONSE:return {'error':'code_worker_response_limit','result_incomplete':True,
            'code_verified':False,'note':'代码结果超过读取上限，未获得完整diff或验证结果；请从受控工件查看。'}
        value=json.loads(raw)
        return value if isinstance(value,dict) else {'error':'code_worker_response_invalid'}
    except Exception:return {'error':'code_worker_unavailable','note':'代码工作区未返回可用结果，未认定已修复。'}
    finally:connection.close()


def _clean(value,secrets=()):
    def text(raw):
        for secret in secrets:
            if secret:raw=raw.replace(secret,'[REDACTED]')
        try:
            from .diagnostic_redaction import redact
            return redact(raw)
        except (ImportError,ValueError):
            return re.sub(r'(?i)(api[_-]?key|password|token|authorization)(\s*[:=]\s*)([^\s,]+)',r'\1\2[REDACTED]',raw)
    if isinstance(value,str):return text(value)
    if isinstance(value,list):return [_clean(item,secrets) for item in value]
    if isinstance(value,dict):return {text(str(key)):('[REDACTED]' if re.fullmatch(r'(?i)(?:api[_-]?key|password|passwd|token|authorization|client[_-]?secret)',str(key)) else _clean(item,secrets)) for key,item in value.items()}
    return value


def start(run,source_id,problem):
    if str(run.defect.project_id)!=str(run.workstation.agent.project_id):return {'error':'code_source_not_authorized'}
    if run.mode!='repair':return {'error':'code_repair_mode_required','note':'本轮只允许取证；代码修复需要repair模式。'}
    if not isinstance(source_id,str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,59}',source_id):return {'error':'code_source_not_authorized'}
    if not isinstance(problem,str) or not 1<=len(problem.strip())<=20000:return {'error':'invalid_code_problem'}
    try:
        _,token=_configuration()
        root=os.environ.get('QUALITY_REMOTE_SOURCE_SNAPSHOTS_ROOT','')
        if not root:return {'error':'code_source_not_authorized'}
        selected=[row for row in _catalog(root,run.defect.project_id)['sources'] if row['id']==source_id]
        if len(selected)!=1:return {'error':'code_source_not_authorized'}
        commit=selected[0]['repository_commit'];scope=_scope(run);cache=_cache();prefix='remote-code:'+scope['run']
        if not cache.add(prefix+':submit',True,timeout=30):return {'error':'code_submission_in_progress'}
        try:
            count=cache.get(prefix+':count',0)
            if count>=2:return {'error':'code_job_budget_exhausted'}
            config=_provider(run.defect.project.workspace_id)
            if not config.get('configured'):return {'error':'code_model_not_configured'}
            cache.set(prefix+':count',count+1,timeout=TTL)
            result=_request('POST','/jobs',{'config':{key:config[key] for key in ('model','api_key','base_url')},
                'task':{'project_id':scope['project'],'source_id':source_id,'repository_commit':commit,'problem':problem}})
            if result.get('error')=='code_worker_busy':cache.set(prefix+':count',count,timeout=TTL)
            job_id=result.get('job_id')
            if not isinstance(job_id,str) or not re.fullmatch(r'[a-f0-9]{32}',job_id):
                return _clean(result,[token,config.get('api_key','')]) if result.get('error') else {'error':'code_worker_response_invalid'}
            cache.set('remote-code-job:'+job_id,{**scope,'source_id':source_id,'repository_commit':commit},timeout=TTL)
            return {'job_id':job_id,'status':'running','capability':'isolated_code_repair','source_id':source_id,
                'repository_commit':commit,'scope':'isolated_code_snapshot','business_verified':False,'production_deployed':False,
                'note':'仅启动隔离代码工作区；不会部署或认定现场业务恢复。'}
        finally:cache.delete(prefix+':submit')
    except Exception:return {'error':'code_worker_unavailable','note':'代码工作区当前不可用，未启动已确认的修复。'}


def status(run,job_id):
    if not isinstance(job_id,str) or not re.fullmatch(r'[a-f0-9]{32}',job_id):return {'error':'invalid_code_job_id'}
    try:
        binding=_cache().get('remote-code-job:'+job_id)
        if not isinstance(binding,dict) or any(binding.get(key)!=value for key,value in _scope(run).items()):return {'error':'code_job_not_owned'}
        _,token=_configuration()
        deadline=time.monotonic()+12
        result=_request('GET','/jobs/'+job_id)
        while result.get('status')=='running' and time.monotonic()<deadline-1:
            time.sleep(min(1,max(0,deadline-time.monotonic())))
            result=_request('GET','/jobs/'+job_id,read_timeout=min(2,max(.1,deadline-time.monotonic())))
        # Reload configured exact credentials in memory only, never cache or return them.
        config=_provider(run.defect.project.workspace_id)
        result=_clean(result,[token,config.get('api_key','')])
        if isinstance(result.get('result'),dict):
            receipt=result['result']
            matched=receipt.get('source_id')==binding['source_id'] and receipt.get('repository_commit')==binding['repository_commit']
            receipt['provenance_verified']=matched
            if not matched:
                receipt['code_verified']=False
                receipt['provenance_gap']='代码工作区结果未匹配批准源码及固定提交，不能认定该版本已修复。'
            result['result'].update(scope='isolated_code_snapshot',business_verified=False,production_deployed=False,repaired=False)
        result.update(job_id=job_id,source_id=binding['source_id'],repository_commit=binding['repository_commit'],
            scope='isolated_code_snapshot',business_verified=False,production_deployed=False)
        return result
    except Exception:return {'error':'code_worker_unavailable','note':'尚未取得完整代码工作区回执，不代表业务恢复。'}
