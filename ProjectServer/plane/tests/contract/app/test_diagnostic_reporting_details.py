"""Optional report details retain evidence validation and legacy compatibility."""
import json
from types import SimpleNamespace

import pytest

from plane.quality.diagnostic_model import DiagnosticAnswer, analyze_diagnostic

pytestmark=[pytest.mark.contract]


def output():
    return {'answer':'**问题**：历史复位失败，当前配置已复查。\n**原因**：历史日志记录目标超限。\n**处理**：按真实回执说明处理。\n**验证**：业务仍待获授权后验收。',
        'suggested_actions':['由获授权人员执行原失败的复位操作。'],
        'verification_steps':['复位完成且不再出现同类错误，才确认该业务恢复。'],'citations':['DESCRIPTION'],
        'evidence_details':'配置来源、真实位置和前后变化见本轮执行回执。'}


def test_optional_details_and_four_sections_survive_server_validation(mocker,monkeypatch):
    monkeypatch.setenv('DIAGNOSTIC_AGENT_PYTHON','fixture-python')
    value=output()
    mocker.patch('plane.quality.diagnostic_model.subprocess.run',return_value=SimpleNamespace(stdout=json.dumps(value)))
    result=analyze_diagnostic({'api_key':'synthetic','base_url':'https://synthetic.invalid','model':'offline',
        'require_actionable_report':True},'原事件材料',[],[])
    assert result['answer']==value['answer']
    assert result['evidence_details']==value['evidence_details']
    assert len(result['verification_steps'])==1


def test_details_have_a_bound_and_legacy_missing_details_is_valid():
    legacy=output();legacy.pop('evidence_details')
    parsed=DiagnosticAnswer(data=legacy)
    assert parsed.is_valid(),parsed.errors
    assert parsed.validated_data['evidence_details']==''
    too_long=DiagnosticAnswer(data={**legacy,'evidence_details':'x'*10001})
    assert not too_long.is_valid()
    assert 'evidence_details' in too_long.errors


def test_details_cannot_smuggle_uncited_foreign_knowledge(mocker,monkeypatch):
    monkeypatch.setenv('DIAGNOSTIC_AGENT_PYTHON','fixture-python')
    value=output();value['evidence_details']='机制依据 KN-foreign-private'
    mocker.patch('plane.quality.diagnostic_model.subprocess.run',return_value=SimpleNamespace(stdout=json.dumps(value)))
    with pytest.raises(ValueError,match='INVALID_DIAGNOSTIC_CITATION'):
        analyze_diagnostic({'api_key':'synthetic','base_url':'https://synthetic.invalid','model':'offline'},'原材料',[],[])


def test_official_fallback_receives_trusted_verified_subset_scope(mocker,monkeypatch):
    monkeypatch.delenv('DIAGNOSTIC_AGENT_PYTHON',raising=False)
    client=mocker.patch('plane.quality.diagnostic_model.OpenAI').return_value.__enter__.return_value
    value=output();value['answer']='故障：已读日志支持目标超限；未读部分不参与结论。'
    client.chat.completions.create.return_value=SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(value)))],usage=None)
    result=analyze_diagnostic({'api_key':'synthetic','base_url':'https://synthetic.invalid','model':'offline',
        'analysis_scope':'verified_read_subset','require_actionable_report':True},'原材料片段',[],[])
    system=next(message['content'] for message in client.chat.completions.create.call_args.kwargs['messages'] if message['role']=='system')
    assert '只陈述已读取事实' in system
    assert '不能声称全面排除' in system
    assert result['answer']==value['answer']


def test_official_fallback_does_not_add_partial_scope_to_full_scan(mocker,monkeypatch):
    monkeypatch.delenv('DIAGNOSTIC_AGENT_PYTHON',raising=False)
    client=mocker.patch('plane.quality.diagnostic_model.OpenAI').return_value.__enter__.return_value
    client.chat.completions.create.return_value=SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(output())))],usage=None)
    analyze_diagnostic({'api_key':'synthetic','base_url':'https://synthetic.invalid','model':'offline'},'原材料',[],[])
    system=next(message['content'] for message in client.chat.completions.create.call_args.kwargs['messages'] if message['role']=='system')
    assert '本轮范围是已通过完整性校验且实际读取的材料片段' not in system


def test_unread_zip_notice_is_not_an_original_source_and_partial_reads_stay_truncated(mocker,monkeypatch):
    monkeypatch.setenv('DIAGNOSTIC_AGENT_PYTHON','fixture-python')
    read_ref='FILE-source:read.log';unread_ref='FILE-source:unread.log'
    value=output();value['citations']=[read_ref]
    child=mocker.patch('plane.quality.diagnostic_model.subprocess.run',return_value=SimpleNamespace(stdout=json.dumps(value)))
    sources=[{'file_id':'source','name':'diagnostic.zip','archive_entry':'read.log','read_bytes':12,
        'scanned_bytes':12,'file_bytes':1000,'excerpt':'ERROR actual','scan_incomplete':True,'truncated':True,
        'integrity_verified':True,'semantic_scan_complete':False,'selection_scope':'stream_prefix'},
        {'file_id':'source','name':'diagnostic.zip','archive_entry':'unread.log','read_bytes':0,
        'scanned_bytes':0,'file_bytes':1000,'excerpt':'扫描预算耗尽，未读取条目','scan_incomplete':True,
        'integrity_verified':True,'semantic_scan_complete':False}]
    analyze_diagnostic({'api_key':'synthetic','model':'offline','base_url':'https://synthetic.invalid'},
        '已读取片段',sources,[],{})
    sent=json.loads(child.call_args.kwargs['input'])
    assert unread_ref not in sent['materials']
    assert unread_ref not in {row['reference'] for row in sent['evidence']}
    assert sent['materials'][read_ref]['content']=='ERROR actual'
    assert sent['materials'][read_ref]['truncated'] is True
    row=next(row for row in sent['evidence'] if row['reference']==read_ref)
    assert row['scan_incomplete'] and row['integrity_verified']
    assert row['semantic_scan_complete'] is False and row['selection_scope']=='stream_prefix'
