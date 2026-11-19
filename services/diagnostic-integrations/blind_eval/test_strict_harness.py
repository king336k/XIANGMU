import copy
import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).parent))
from strict_harness import StrictCase


def fixture(tmp_path,approved=True,fault='limit'):
    return StrictCase(tmp_path/'case',Path(os.environ['DAQ_REPO']),approved,fault)


def test_inspect_has_no_validator_or_hidden_answers_and_knowledge_empty(tmp_path):
    case=fixture(tmp_path)
    response=case.strict_rpc({'operation':'run','argv':['daq-local-diagnostics-v1','inspect']})
    text=response['stdout'];value=json.loads(text)
    assert value['read_only_roots']==['current/','baseline/','device/']
    assert all(word not in text for word in ('suggested_changes','joint_limit_violation','artifact_findings','"after"','"field"'))
    assert case.oracle['field'] not in text
    assert 'initial_joint_states' not in '\n'.join(case.log)
    assert case.strict_rpc({'operation':'knowledge','query':'old fixes'})['case_history']==[]
    assert case.strict_rpc({'operation':'read_file','path':'hidden-objective.json'})['error']


@pytest.mark.parametrize('fault',['limit','type','dimension'])
def test_patch_writes_only_actual_model_candidate_and_real_overlay(tmp_path,fault):
    case=fixture(tmp_path,fault=fault)
    before=case.read_raw(case.current_alias)
    submitted=case.yaml.safe_dump(case.good,sort_keys=False)
    receipt=case.patch_model_content(case.current_alias,before['sha256'],submitted)
    assert receipt['state']=='applied' and receipt['actual_write'] is True
    assert receipt['source_of_written_values']=='model_submitted_content'
    actual=case.yaml.safe_load(case.current_path.read_text())
    assert actual['initial_joint_states']==case.good['initial_joint_states']
    assert (case.artifact/case.relative).read_bytes()==case.source_after_fault


def test_model_patch_cannot_expand_limits_or_change_other_legal_calibration(tmp_path):
    case=fixture(tmp_path);before=case.read_raw(case.current_alias)
    candidate=copy.deepcopy(case.good);candidate['joint_limits'][case.oracle['group']][case.oracle['index']][1]+=1
    assert case.patch_model_content(case.current_alias,before['sha256'],case.yaml.safe_dump(candidate))['error']=='only_initial_joint_states_may_change'
    candidate=copy.deepcopy(case.good)
    other=next(key for key in candidate['initial_joint_states'] if key!=case.oracle['group'])
    candidate['initial_joint_states'][other][0]+=0.01
    assert case.patch_model_content(case.current_alias,before['sha256'],case.yaml.safe_dump(candidate))['error']=='valid_operator_value_must_be_preserved'
    assert not (case.state/'robot_config_overrides').exists()


def test_wrong_model_content_is_rejected_instead_of_automatically_replaced_by_baseline(tmp_path):
    case=fixture(tmp_path);before=case.read_raw(case.current_alias)
    submitted=copy.deepcopy(case.good)
    group,index=case.oracle['group'],case.oracle['index']
    lo,hi=submitted['joint_limits'][group][index]
    submitted['initial_joint_states'][group][index]=(lo+hi)/2
    if submitted['initial_joint_states'][group][index]==case.good['initial_joint_states'][group][index]:
        submitted['initial_joint_states'][group][index]+=0.01
    result=case.patch_model_content(case.current_alias,before['sha256'],case.yaml.safe_dump(submitted))
    assert result['error']=='unsupported_candidate_value'
    assert not (case.state/'robot_config_overrides').exists()


def test_candidate_baseline_does_not_authorize_patch_and_sha_is_enforced(tmp_path):
    case=fixture(tmp_path,approved=False);before=case.read_raw(case.current_alias)
    submitted=case.yaml.safe_dump(case.good)
    assert case.patch_model_content(case.current_alias,'0'*64,submitted)['error']=='current_file_sha_conflict'
    assert case.patch_model_content(case.current_alias,before['sha256'],submitted)['error']=='baseline_not_approved_for_device'
    assert not (case.state/'robot_config_overrides').exists()


def test_source_catalog_lists_and_reads_real_repository_files(tmp_path):
    case=fixture(tmp_path)
    paths=case.source_rpc({'operation':'list_source_paths'})['paths']
    assert paths
    path=paths[0]['path']
    source=case.source_rpc({'operation':'read_source','path':path})
    assert source['content'] and source['path']==path
    assert source['sha256']
