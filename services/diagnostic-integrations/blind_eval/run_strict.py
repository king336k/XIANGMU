#!/usr/bin/env python3
"""Strict raw-evidence evaluation; credentials enter through stdin only."""
import argparse
import asyncio
from importlib.metadata import version
import json
import os
from pathlib import Path
import sys
import uuid

os.environ.setdefault('OTEL_SDK_DISABLED','true')
os.environ.setdefault('LOGFIRE_SEND_TO_LOGFIRE','false')
os.environ.setdefault('PYDANTIC_AI_NO_BANNER','1')

from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator
from pydantic_evals.reporting import EvaluationReportAdapter

from harness import load_module, save
from strict_harness import StrictCase, evaluate_strict


class StrictReceiptChecks(Evaluator):
    def evaluate(self,ctx):return ctx.output['checks']


async def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--case',choices=['approved','candidate','both'],default='approved')
    parser.add_argument('--fault',choices=['limit','type','dimension'])
    parser.add_argument('--selfcheck',action='store_true')
    args=parser.parse_args()
    if version('pydantic-evals')!='2.66.0' or version('pydantic-ai-slim')!='2.66.0':
        raise ValueError('evaluation_and_model_sdk_versions_must_match')
    args.output.mkdir(parents=True,exist_ok=False)
    selected=[True,False] if args.case=='both' else [args.case=='approved']
    fixtures={}
    for approved in selected:
        identifier='case-'+uuid.uuid4().hex[:8]
        fixtures[identifier]=StrictCase(args.output/identifier,Path(os.environ['DAQ_REPO']),approved,args.fault)
    config=None;runner=None
    if not args.selfcheck:
        raw=json.loads(sys.stdin.buffer.read(1024*1024+1));config=raw.get('config',raw)
        if not all(isinstance(config.get(key),str) and config[key] for key in ('api_key','base_url','model')):
            raise ValueError('model_configuration_required')
        runner=load_module('actual_remote_runner',Path(os.environ['ROOT_AGENT_RUNNER']))
    async def task(inputs):
        case=fixtures[inputs['case_id']]
        if args.selfcheck:
            catalog=case.raw_inspect()
            response=case.read_raw(case.current_alias)
            if case.approved:
                # SDK plumbing test only: no model claim; a test candidate is
                # submitted through the identical content-controlled patch API.
                proposal=case.yaml.safe_dump(case.good,sort_keys=False)
                receipt=case.patch_model_content(case.current_alias,response['sha256'],proposal)
                passed=receipt.get('state')=='applied'
            else:
                receipt=case.patch_model_content(case.current_alias,response['sha256'],case.yaml.safe_dump(case.good))
                passed=receipt.get('error')=='baseline_not_approved_for_device'
            return {'checks':{'raw_inspect_without_findings':not any(key in catalog.get('configuration',{})
                for key in ('findings','suggested_changes','artifact_findings')),'actual_patch_adapter':passed},
                'model_called':False,'workflow_completed':False,'scope':'strict_adapter_selfcheck_only'}
        return await evaluate_strict(case,runner,config)
    dataset=Dataset(name='strict-raw-daq-model-authored-patch',
        cases=[Case(name=identifier,inputs={'case_id':identifier}) for identifier in fixtures],
        evaluators=[StrictReceiptChecks()])
    report=await dataset.evaluate(task,max_concurrency=1,progress=False,task_timeout=305)
    save(args.output/'pydantic-evals-report.json',EvaluationReportAdapter.dump_python(report,mode='json'))
    assertions=[evaluation.value for case in report.cases for evaluation in case.assertions.values()]
    summary={'scope':'strict_raw_evidence_model_authored_patch','framework':'pydantic-evals',
        'framework_version':version('pydantic-evals'),'case_count':len(report.cases),
        'failure_count':len(report.failures),'selfcheck_only':args.selfcheck,
        'confirmed_model_case_count':sum(case.output.get('model_called') is True for case in report.cases),
        'completed_workflow_case_count':sum(case.output.get('workflow_completed') is True for case in report.cases),
        'passed':bool(assertions) and all(assertions) and not report.failures,'robot_reset_executed':False,
        'model_runtime_timeout_seconds':295,'task_timeout_seconds':305}
    save(args.output/'evaluation-summary.json',summary)
    print(json.dumps({'output':str(args.output),'summary':summary},ensure_ascii=False))


if __name__=='__main__':
    try:asyncio.run(main())
    except Exception as error:
        print(json.dumps({'error':type(error).__name__,'scope':'strict_evaluation_incomplete'}),file=sys.stderr)
        sys.exit(1)
