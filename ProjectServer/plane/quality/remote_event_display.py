"""Readable event projections from scoped server records; stored history is unchanged."""
import re
import shlex

from .diagnostic_materials import redact
from .remote_models import RemoteAgentRun, RemoteCommand

UUID = re.compile(r'\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b')
SECRET_FLAG = re.compile(r'^(?:--?(?:password|passwd|token|secret|api[-_]?key|authorization|cookie)|-p)$', re.I)
SECRET_ASSIGN = re.compile(r'(?i)\b(password|passwd|pwd|token|secret|api[_-]?key|authorization|cookie|sshpass)=\S+')


def safe_argv(values):
    if not isinstance(values,list):return []
    result=[];hide=False
    for value in values[:40]:
        if not isinstance(value,str):continue
        if hide:
            result.append('[已隐藏]');hide=False;continue
        if SECRET_FLAG.fullmatch(value):
            result.append(value);hide=True;continue
        value=SECRET_ASSIGN.sub(lambda match:match[1]+'=[已隐藏]',value)
        result.append(redact(value)[:2000])
    return result


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
    task=f'{run.defect.code} 第{round_no}轮{mode}'
    target={'label':'采集电脑','username':'','host':''}
    value={'summary':task,'stage':'queued','defect_code':run.defect.code,'round':round_no,
        'target':target,'run_id':str(run.id),'command_id':None,'details':'','task':task}
    row=next((commands[item]for item in ids if item in commands and commands[item].run_id==run.id),None)
    if row:
        argv=row.payload.get('argv');kind=row.payload.get('kind');context_policy=station.capabilities.get('agent_context',{})
        label='检查现场状态';stage='inspect';path=row.result.get('resolved_path') or row.payload.get('path')
        if kind=='read_file':label='读取配置'+('：'+str(path)if path else '')
        elif kind=='patch_file':label='修改配置'+('：'+str(path)if path else '');stage='repair'
        elif argv and argv==context_policy.get('verify_argv'):label='联合复测控制回执、遥测与采集文件';stage='verify'
        elif context_policy.get('repair_argv') and isinstance(argv,list) and argv[:len(context_policy['repair_argv'])]==context_policy['repair_argv']:
            label='修复已登记的机器人配置';stage='repair'
        elif isinstance(argv,list) and len(argv)>=2 and argv[-2] in {'rosa','rai'}:
            label=argv[-2].upper()+('健康检查'if argv[-1]=='health'else'只读检查')
        elif argv and argv==context_policy.get('inspect_argv'):label='检查采集电脑与机器人当前配置和连接'
        success=row.result.get('ok')is True and row.result.get('exit_code',0)==0
        # Only actual per-command receipt identity can override the station snapshot.
        if row.result.get('target_kind') in {'collector','robot'}:
            target={'label':'机器人'if row.result['target_kind']=='robot'else'采集电脑',
                'username':row.result.get('target_username',''),'host':row.result.get('target_ip','')}
        value.update(summary=f'{task} · {label}：'+('完成'if success else'失败'),stage=stage,target=target,
            command={'argv':safe_argv(argv),'path':redact(str(path))if path else None,'exit_code':row.result.get('exit_code')},command_id=str(row.id))
        value['details']=('实际命令：'+shlex.join(safe_argv(argv)))if argv else ('文件操作：'+str(kind))
    elif '进入队列' in note:
        value['summary']=task+'：已排队'
    elif '处理结束' in note:
        value.update(summary=task+'：'+('已修复并复测通过'if'已修复并通过复测'in note else'复测通过，未修改现场'if'验证通过'in note else'未确认解决，查看现场处理结果'),stage='completed')
    return value
