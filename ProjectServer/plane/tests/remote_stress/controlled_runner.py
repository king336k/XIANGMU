"""Deterministic model replacement for load tests; still uses real tool HTTP/Engine."""
import json
import sys
import time
import urllib.request


def main():
    payload=json.load(sys.stdin)
    context=payload['context']
    started=time.time()
    def tool(operation, **values):
        data=json.dumps({'operation':operation,**values}).encode()
        request=urllib.request.Request(payload['gateway_url'],data=data,method='POST',headers={
            'Content-Type':'application/json','Authorization':'Bearer '+payload['tool_token']})
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=45) as response:
            result=json.load(response)
        if result.get('ok') is not True or result.get('exit_code',0)!=0:
            raise ValueError('controlled tool failed')
        return result
    before=tool('read_file',path='config.json')
    actual=json.loads(before['content'])
    repaired=False
    if context['operation_mode']=='repair':
        actual['fixed']=True
        tool('patch_file',path='config.json',content=json.dumps(actual),expected_sha256=before['sha256'])
        repaired=True
    after=tool('read_file',path='config.json')
    verified=json.loads(after['content'])==actual
    print(json.dumps({'summary':'受控模型混合压测：真实执行端已读取并校验配置。',
        'root_cause':'受控故障，仅用于测试调度与数据隔离。','actions':['读取配置']+(['修改配置'] if repaired else []),
        'verification':['实际文件读回一致'] if verified else [],'verification_passed':verified,
        'repaired':repaired and verified,'model_provider':'controlled_stub',
        'controlled_stub_started_at':started,'controlled_stub_completed_at':time.time()}))


if __name__=='__main__':
    main()
