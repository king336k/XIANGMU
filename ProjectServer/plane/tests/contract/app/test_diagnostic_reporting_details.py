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
