"""Readable event projections from scoped server records; stored history is unchanged."""
import re
import json
import shlex

from .diagnostic_materials import redact
from .remote_models import RemoteAgentRun, RemoteCommand

UUID = re.compile(r'\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b')
SECRET_FLAG = re.compile(r'^(?:--?(?:password|passwd|token|secret|api[-_]?key|authorization|cookie)|-p)$', re.I)
SECRET_ASSIGN = re.compile(r'(?i)\b(password|passwd|pwd|token|secret|api[_-]?key|authorization|cookie|sshpass)=\S+')


def sensitive_name(value):
    normalized=re.sub(r'[^a-z0-9]','',str(value).lower())
    return any(word in normalized for word in ['password','passwd','sshpass','token','secret','apikey','authorization','cookie']) or normalized in {'pwd','key'}


def safe_argv(values):
    if not isinstance(values,list):return []
    result=[];hide=False;shell_body=False
    executable=str(values[0]).rsplit('/',1)[-1] if values else ''
    for index,value in enumerate(values[:40]):
        if not isinstance(value,str):continue
        if hide or shell_body:
            result.append('[已隐藏]');hide=False;shell_body=False;continue
        if executable in {'bash','sh','zsh','dash','ksh'} and index>0 and re.fullmatch(r'-[a-zA-Z]*c[a-zA-Z]*',value):
            result.append(value);shell_body=True;continue
        if value=='-p':result.append(value);hide=True;continue
        if value.startswith('-p') and len(value)>2:
            result.append('-p[已隐藏]');continue
        option=value.split('=',1)[0]
        if option.startswith('-') and sensitive_name(option):
            if '=' in value:result.append(option+'=[已隐藏]')
            else:result.append(option);hide=True
            continue
        value=SECRET_ASSIGN.sub(lambda match:match[1]+'=[已隐藏]',value)
        result.append(redact(value)[:2000])
    return result


def safe_change_value(value,depth=0):
    if depth>16:return '[结构超过解析深度]'
    if isinstance(value,dict):
        return {key:'[已隐藏]' if sensitive_name(key) else safe_change_value(item,depth+1) for key,item in value.items()}
    if isinstance(value,list):return [safe_change_value(item,depth+1) for item in value]
    if isinstance(value,str):return redact(value)
    return value


def readable_assignment(note):
    """Names already in the historical note remain; opaque IDs move to details."""
    if not isinstance(note,str):return note
    if not note.startswith(('初步分派','诊断自动指派','人工改派','诊断待分诊原因')):return note
    return re.sub(r'\s*\([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\)','',note)


def event_process(event,context):
    note=event.note or ''
    if not note.startswith('Agent '):return None
    ids=UUID.findall(note)
    if not ids:return None
    cache=context if context is not None else {}
    key=('remote_event_display',str(event.defect_id))
    if key not in cache:
        runs=list(RemoteAgentRun.objects.filter(defect_id=event.defect_id,defect__project_id=event.project_id)
            .select_related('workstation__agent__project','defect__project').order_by('created_at','id'))
        mapping={str(run.id):(run,index+1)for index,run in enumerate(runs)}
        commands={str(row.id):row for row in RemoteCommand.objects.filter(run_id__in=[run.id for run in runs]).select_related('run','workstation')}
        cache[key]=(mapping,commands)
    runs,commands=cache[key]
    pair=next((runs[value]for value in ids if value in runs),None)
    if pair is None:return None
    run,round_no=pair;station=run.workstation
    mode={'repair':'诊断修复','diagnose':'只读诊断','verify':'只读复测'}.get(run.mode,'现场处理')
    code_key=('remote_event_defect_code',str(event.defect_id))
    if code_key not in cache:cache[code_key]=run.defect.code
    defect_code=cache[code_key]
    task=f'{defect_code} 第{round_no}轮{mode}'
    snapshot=run.result.get('target_snapshot',{}) if isinstance(run.result,dict) else {}
    collector=snapshot.get('collector',{}) if isinstance(snapshot,dict) else {}
    frozen=bool(collector.get('username') and collector.get('host'))
    target={'label':'采集电脑' if frozen else '采集电脑（当前登记信息）',
        'username':collector.get('username') or station.username,
        'host':collector.get('host') or station.capabilities.get('network',{}).get('ip_address',''),
        'identity_source':'execution_snapshot' if frozen else 'current_registration'}
    value={'summary':task,'stage':'queued','defect_code':defect_code,'round':round_no,
        'target':target,'run_id':str(run.id),'command_id':None,'details':'','task':task}
    row=next((commands[item]for item in ids if item in commands and commands[item].run_id==run.id),None)
    if row:
        argv=row.payload.get('argv');kind=row.payload.get('kind');context_policy=station.capabilities.get('agent_context',{})
        label='检查现场状态';stage='inspect';path=row.result.get('resolved_path') or row.payload.get('path')
        if kind=='read_file':label='读取配置'+('：'+str(path)if path else '')
        elif kind=='patch_file':label='修改配置'+('：'+str(path)if path else '');stage='repair'
        elif argv and argv==context_policy.get('verify_argv'):
            label='只读复核连接与服务状态' if context_policy.get('verification_scope')=='read_only_connectivity' else '执行本轮固定复测'
            stage='verify'
        elif context_policy.get('repair_argv') and isinstance(argv,list) and argv[:len(context_policy['repair_argv'])]==context_policy['repair_argv']:
            label='修复已登记的机器人配置';stage='repair'
        elif isinstance(argv,list) and len(argv)>=2 and argv[-2] in {'rosa','rai'}:
            label=argv[-2].upper()+('健康检查'if argv[-1]=='health'else'只读检查')
        elif argv and argv==context_policy.get('inspect_argv'):label='检查采集电脑与机器人当前配置和连接'
        success=row.result.get('ok')is True and row.result.get('exit_code',0)==0
        receipt=row.result
        # Only the registered fixed repair command returns this structured robot receipt.
        if kind=='run' and stage=='repair' and success:
            stdout=row.result.get('stdout','')
            if isinstance(stdout,str) and len(stdout)<=65536:
                try:
                    parsed=json.loads(stdout)
                    if isinstance(parsed,dict) and parsed.get('simulation') is True:
                        receipt=parsed
                except (ValueError,TypeError):pass
        # Only actual per-command receipt identity can override the station snapshot.
        if row.result.get('target_kind') in {'collector','robot'}:
            target={'label':'机器人'if row.result['target_kind']=='robot'else'采集电脑',
                'username':row.result.get('target_username',''),'host':row.result.get('target_ip','')}
        raw_changes=receipt.get('changes',[])
        raw_changes=raw_changes[:20] if isinstance(raw_changes,list) else []
        robot_targets={(change.get('target_username'),change.get('target_ip')) for change in raw_changes
            if isinstance(change,dict) and change.get('target_kind')=='robot'
            and isinstance(change.get('target_username'),str) and isinstance(change.get('target_ip'),str)}
        if len(robot_targets)==1:
            username,host=next(iter(robot_targets))
            target={'label':'机器人','username':redact(username),'host':redact(host),'identity_source':'execution_receipt'}
        changes=[]
        for change in raw_changes:
            if not isinstance(change,dict):continue
            safe={}
            for field in ['key','before','after','before_exists','after_exists','line','before_line','after_line','path','backup','before_sha256','after_sha256']:
                if field not in change:continue
                value_part=change[field]
                if field in {'before','after'} and sensitive_name(change.get('key','')):
                    safe[field]='[已隐藏]'
                elif field in {'before','after'}:
                    # String redaction and key-based JSON sanitizing protect credentials.
                    try:
                        cleaned=json.loads(redact(json.dumps({str(change.get('key','value')):safe_change_value(value_part)},ensure_ascii=False)))
                        safe[field]=next(iter(cleaned.values())) if isinstance(cleaned,dict) else '[已隐藏]'
                    except (ValueError,TypeError):
                        safe[field]='[已隐藏]'
                elif isinstance(value_part,str):safe[field]=redact(value_part)[:2000]
                elif value_part is None or type(value_part) in {bool,int}:safe[field]=value_part
            if safe:changes.append(safe)
        command={'argv':safe_argv(argv),'path':redact(str(path))if path else None,'exit_code':row.result.get('exit_code'),
            'kind':kind,'changes':changes,'backup':redact(str(receipt.get('backup',''))),
            'expected_sha256':row.payload.get('expected_sha256'),'sha256':row.result.get('sha256')}
        value.update(summary=f'{task} · {label}：'+('完成'if success else'失败'),stage=stage,target=target,
            command=command,command_id=str(row.id))
        operation={'read_file':'读取配置文件','patch_file':'修改配置文件','run':'执行现场命令'}.get(kind,'执行现场操作')
        value['details']=('实际命令：'+shlex.join(safe_argv(argv)))if argv else operation
    elif '进入队列' in note:
        value['summary']=task+'：已排队'
    elif '处理结束' in note:
        value.update(summary=task+'：'+('已修复并复测通过'if'已修复并通过复测'in note else'复测通过，未修改现场'if'验证通过'in note else'未确认解决，查看现场处理结果'),stage='completed')
    return value
