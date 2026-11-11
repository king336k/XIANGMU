"""Deterministic evidence checks plus explicit reviewer judgments after blinded model run."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

JUDGMENTS={
1:('准确识别直接原因','ConnectionRefusedError（Errno 111）','operation前后监听为空；连接目标127.0.0.1闭端口','模型区分服务未启动/端口错/命名空间等待验证项，没有把可能原因说成硬件损坏。'),
2:('准确识别直接原因','输出挂载点容量耗尽','8MiB独立tmpfs可用空间降为0，errno28，输出仅8MiB','模型正确区分父级32MiB与子挂载8MiB，未误判宿主盘满或OOM。'),
3:('准确识别直接原因','目录访问权限与运行身份不匹配','UID/GID65534访问root拥有0500目录触发errno13','模型没有建议全目录777或直接root运行；ACL/安全策略只列为未验证项。'),
4:('准确识别直接原因','local_ip 缺失','原DAQ validate_ros1_config实际抛PreflightError，ROS1配置未含local_ip','正确停留在配置预检原因，没有跳到机器人连接坏。'),
5:('正常对照未过度诊断','未见采集操作异常','4096B写回SHA一致、loopback ACK成功、operation_completed=true','模型不把networknone/临时listener关闭当故障，且不外推真实机器人链路正常。')}

def review(root):
    truth=json.loads((root/'ground_truth.json').read_text());state=json.loads((root/'http-state.json').read_text());rows=[];total={'requests':0,'input_tokens':0,'output_tokens':0}
    for oracle in truth['cases']:
        number=oracle['case_id'];folder=root/f'case-{number:02}';job=json.loads((folder/'model-output.json').read_text());result=job['result'];http=json.loads((folder/'http-state.json').read_text());answer=result['answer']
        with zipfile.ZipFile(folder/'material.zip') as bundle:
            names=bundle.namelist();assert set(names)=={'system.log','environment.json','capture_manifest.json','runtime.json'}
            assert 'ground_truth.json' not in names and 'observations.json' not in names
            assert hashlib.sha256((folder/'material.zip').read_bytes()).hexdigest()==oracle['bundle_sha256']==http['sha256']
        assert result['model_status']=='completed' and result['model_usage']['requests']==1
        sources=result['sources'];assert len(sources)==4 and all(not source.get('scan_incomplete') and source['scanned_bytes']==source['file_bytes'] for source in sources)
        allowed={f"FILE-{row['file_id']}:{row['archive_entry']}" for row in sources};citations={row['reference'] for row in result['citations']};assert citations<=allowed and len(citations)==4
        verdict,quote,facts,note=JUDGMENTS[number];assert quote in answer
        for key in total:total[key]+=result['model_usage'][key]
        rows.append({'case_id':number,'code':http['code'],'job_id':job['id'],'expected_root_cause':oracle['cause'],'observed_exception':oracle['observed'].get('exception_type'),
            'verdict':verdict,'model_quote':quote,'evidence':facts,'review_note':note,'unsupported_hardware_assertion':False,'citation_valid':True,
            'incorrect_or_unconfirmed_detail':'runtime exit_code=0 was supplied while container was running; not valid final-exit evidence',
            'model_usage':result['model_usage'],'model_duration_ms':result['duration_ms'],'elapsed_seconds':http['elapsed_seconds'],
            'artifact':str(folder/'model-output.json')})
    report={'scope':'5个隔离真实软件操作；无物理机器人，不代表现场准确率','project_id':state['project_id'],'identifier':state['identifier'],
        'case_count':5,'abnormal_direct_causes_identified':4,'normal_control_not_overdiagnosed':1,'model_requests':5,'usage':total,
        'blindness':{'oracle_not_uploaded':True,'neutral_titles_and_description':True,'runner_does_not_read_ground_truth':True,'new_collectors_tasks_sessions':True,'project_secret':True},
        'limits':['每类仅1例，故障栈明确，不能外推混合/间歇故障或现场准确率。','容器取证时仍running，runtime.exit_code=0是Docker缺省值，不是最终退出码；5个输入/输出保留原样并记录此局限。','API结果未持久化模型名称；另保存本轮配置快照，不能仅由job输出反推模型。','未上传原始录制；存储只使用容器tmpfs，没有填充宿主盘。'],
        'observed_incorrect_facts':['五项回答中沿用了输入runtime.exit_code=0：容器仍运行，该值不能支持最终正常退出。源于取证输入歧义，未修改原包或重跑。'],
        'missing_evidence':['每类仅一次；缺混合与间歇故障样本。','无物理机器人、实际ROS端到端采集、持续性和恢复后再验证证据。','无provider实付费用；模型名称仅事后配置快照，任务自身未冻结。'],
        'recommendations':['正式取证明确区分container_status、exit_code_if_exited与operation_completed。','诊断结果应冻结模型名称/供应商/提示版本，便于回归对账。','增加多原因、缺日志、间歇网络和真实设备脱敏样本；在盲测集扩大前不宣传准确率百分比。'],
        'cases':rows}
    return report

def main():
    parser=argparse.ArgumentParser();parser.add_argument('artifact',type=Path);args=parser.parse_args();report=review(args.artifact)
    (args.artifact/'review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    lines=['# 真实受控软件故障盲测','',report['scope'],'','四种故障直接原因均识别，正常对照未过度诊断。仅这5个case，不能写成现场诊断准确率。','','|样本|实际证据|模型原文摘录|复核|','|---|---|---|---|']
    for row in report['cases']:lines.append(f"|{row['code']}|{row['evidence']}|{row['model_quote']}|{row['verdict']}|")
    lines+=['','请求及token：'+json.dumps(report['usage'],ensure_ascii=False)+'。provider未提供本轮计费金额，不将token换算成实付。','']
    lines+=['- '+value for value in report['limits']]+['','不准确或不能确证的细节：']+['- '+value for value in report['observed_incorrect_facts']]+['','仍缺证据：']+['- '+value for value in report['missing_evidence']]+['','后续建议：']+['- '+value for value in report['recommendations']]
    (args.artifact/'review.md').write_text('\n'.join(lines)+'\n');print(json.dumps({'cases':5,'requests':5,'usage':report['usage'],'review':str(args.artifact/'review.md')},ensure_ascii=False))
if __name__=='__main__':main()
