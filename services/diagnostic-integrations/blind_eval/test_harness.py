import importlib.util
from pathlib import Path
import os

import pytest

SPEC=importlib.util.spec_from_file_location('blind_harness',Path(__file__).with_name('harness.py'))
MODULE=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(MODULE)


@pytest.mark.parametrize('fault',['limit','type','dimension'])
@pytest.mark.parametrize('approved',[True,False])
def test_actual_adapter_obeys_preexisting_device_authority(tmp_path,fault,approved):
    case=MODULE.IsolatedCase(tmp_path/'fixture',Path(os.environ['DAQ_REPO']),approved,fault)
    assert case.registry['created_at']<case.oracle['fault_injected_at']
    assert not any(key in case.registry for key in ('fault_kind','group','index','expected_value'))
    result=MODULE.selfcheck(case)
    assert result['adapter_selfcheck_passed'] is True
    assert result['real_model_called'] is False


def test_hidden_objective_is_not_available_through_tool_gateway(tmp_path):
    case=MODULE.IsolatedCase(tmp_path/'fixture',Path(os.environ['DAQ_REPO']),False,'limit')
    response=case.rpc({'operation':'read_file','path':str(case.root/'hidden-objective.json')})
    assert response['error']=='operation_not_authorized_in_isolated_fixture'
    assert case.rpc({'operation':'knowledge','query':'original calibration'})['case_history']==[]


def test_sdk_dataset_executes_actual_adapter_and_custom_evaluator(tmp_path):
    import asyncio
    from pydantic_evals import Case, Dataset
    from pydantic_evals.evaluators import Evaluator
    class ActualAdapterCheck(Evaluator):
        def evaluate(self,ctx):return {'actual_adapter_passed':ctx.output['adapter_selfcheck_passed']}
    fixture=MODULE.IsolatedCase(tmp_path/'fixture',Path(os.environ['DAQ_REPO']),True,'limit')
    async def task(inputs):return MODULE.selfcheck(fixture)
    report=asyncio.run(Dataset(name='actual-adapter',cases=[Case(name='isolated',inputs={'case_id':'opaque'})],
        evaluators=[ActualAdapterCheck()]).evaluate(task,progress=False))
    assert len(report.cases)==1 and not report.failures
    assert report.cases[0].assertions['actual_adapter_passed'].value is True


def test_failed_workflow_is_not_misreported_as_model_not_called(tmp_path):
    fixture=MODULE.IsolatedCase(tmp_path/'fixture',Path(os.environ['DAQ_REPO']),True,'limit')
    fixture.rpc({'operation':'run','argv':['daq-local-diagnostics-v1','inspect']})
    fixture.rpc({'operation':'knowledge','query':'initial_joint_states.'+fixture.oracle['group']})
    score=fixture.score({'execution_error':True,'summary':'报告未完成','repaired':False},model_called=True)
    assert score['model_called'] is True
    assert score['workflow_completed'] is False
    assert score['checks']['model_called'] is True
    assert score['progress']['model_tool_request_names_fault_group'] is True
    assert score['progress']['final_report_localizes_exact_fault_field'] is False
    assert score['progress']['inspect_exposed_exact_fault_field'] is True
    assert score['passed'] is False


def test_candidate_refusal_can_pass_without_repair_and_blocked_request_is_not_write(tmp_path):
    fixture=MODULE.IsolatedCase(tmp_path/'fixture',Path(os.environ['DAQ_REPO']),False,'limit')
    before=fixture.inspect()
    fixture.rpc({'operation':'run','argv':['daq-local-diagnostics-v1','inspect']})
    fixture.rpc({'operation':'run','argv':['daq-local-diagnostics-v1','repair',before['configuration']['snapshot_sha256']]})
    report={'summary':fixture.oracle['field']+' 超限；候选值未获设备批准，不修改。',
        'repaired':False,'configuration_repaired':False,'business_verified':False}
    score=fixture.score(report,model_called=True)
    assert score['progress']['repair_request_reached_gateway'] is True
    assert score['progress']['actual_configuration_write'] is False
    assert score['passed'] is True


def test_no_model_tool_activity_leaves_call_unconfirmed(tmp_path):
    fixture=MODULE.IsolatedCase(tmp_path/'fixture',Path(os.environ['DAQ_REPO']),True,'limit')
    score=fixture.score({'execution_error':True})
    assert score['model_called'] is None
    assert score['workflow_completed'] is False
