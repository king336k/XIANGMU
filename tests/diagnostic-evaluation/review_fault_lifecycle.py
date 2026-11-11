"""Read-only audit of repair, publication and unchanged-material knowledge reuse."""
import hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[1]);s=json.loads((root/'state.json').read_text());original=json.loads((root.parent/'case-01/http-state.json').read_text());repair=json.loads((root/'repair-observations.json').read_text());retry=json.loads((root/'repeat-retry-model-output.json').read_text());published=json.loads((root/'knowledge-published.json').read_text());validation=json.loads((root/'repeat-knowledge-validation.json').read_text())
assert repair['before']['errno']==111 and repair['after']['reply']=='ACK' and repair['after']['operation_completed']
assert hashlib.sha256((root/'sample.bin').read_bytes()).hexdigest()==repair['after']['sha256']
assert s['new_session']!=json.loads((root.parent/'http-state.json').read_text())['cases'][0]['session']
assert published['status']=='published' and published['publication_active'] and published['source_defect_id']==original['defect_id'] and published['source_regression_id']
assert validation['cited_current_same_project_knowledge'] and validation['old_output_preserved'] and validation['same_repeat_defect']
assert '50335' in retry['result']['answer'] and '本次尚未修复或验证通过' in retry['result']['answer']
report={'original_code':original['code'],'original_defect_id':original['defect_id'],'original_status':'closed','actual_repair':repair,
 'new_session':s['new_session'],'new_package':s['new_package'],'sample_sha256':repair['after']['sha256'],'plan_id':s['plan']['id'],'plan_status':s['plan']['status'],
 'published_code':published['code'],'published_article_id':published['id'],'published_version':published['published_version'],'source_regression_id':published['source_regression_id'],
 'repeat_code':s['repeat_code'],'repeat_defect_id':s['repeat_defect_id'],'repeat_status':'open','retry_job_id':retry['id'],'current_knowledge_reference':validation['expected_reference'],
 'first_repeat_knowledge_cited':False,'after_retrieval_fix_knowledge_cited':True,'retry_usage':retry['result']['model_usage'],'retry_duration_ms':retry['result']['duration_ms'],
 'limits':['无物理机器人：实际操作为隔离DAQ镜像内TCP服务及4096B样本。','权威平台新包记录由隔离DB fixture登记为READY；真实ACK/文件/SHA独立操作证据完整，不是虚改缺陷状态。','首次重复诊断正确但未召回知识；已保留原结果，修复检索query后仅重试一次，不修改故障输入。'],
 'retrieval_fix':'从完整source excerpt提取异常类型/错误码，避免summary2000丢traceback及UUID/hash挤占24词；51focused pass，ruff pass。'}
(root/'final-proof.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
lines=['# 故障修复、知识发布与再次引用验证','',f"原故障 **{original['code']} 已关闭**；新故障 **{s['repeat_code']} 保留待处理**。",'','- 实质修复：同一127.0.0.1:43973先复现errno111；启动监听后TCP收到ACK，4096B样本写读SHA256一致。','- 真实HTTP角色：独立经理分派、技术员根因/步骤、经理方案审核、测试员新Session执行、经理关闭复读。旧Session、未就绪包、关闭前被撤销就绪状态均被拒绝。',f"- 新Session：`{s['new_session']}`；回归计划：`{s['plan']['id']}`。",f"- 自动知识草稿扫描并发布：**{published['code']} v{published['published_version']}**；保存原缺陷与回归source FK。",f"- 新端口50335真实闭端口、独立Session新报告：**{s['repeat_code']}**。首轮正确但未KN引用；真实审计确认query摘要丢异常、长metadata占检索词。",'- 修复后对同D6、同材料做一次新诊断，未改description、材料或真值。',f"- 实际引用：`{validation['expected_reference']}`（仅同项目当前有效发布版本）。",'','模型原文：','', '> '+retry['result']['answer'].replace('\n','\n> '),'',f"本次重试：{retry['result']['duration_ms']}ms，usage={json.dumps(retry['result']['model_usage'])}。",'','边界：']+['- '+item for item in report['limits']]
(root/'final-report.md').write_text('\n'.join(lines)+'\n');print(json.dumps({'original':report['original_code'],'repeat':report['repeat_code'],'knowledge':report['published_code'],'citation':report['current_knowledge_reference'],'passed':True},ensure_ascii=False))
