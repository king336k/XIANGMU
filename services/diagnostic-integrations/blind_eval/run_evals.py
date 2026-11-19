#!/usr/bin/env python3
"""Pydantic Evals dataset exercising the real runner and isolated DAQ adapters."""
import argparse
import asyncio
from datetime import datetime
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

from harness import IsolatedCase, evaluate_case, load_module, save, selfcheck


class ActualReceiptChecks(Evaluator):
    def evaluate(self,ctx):
        """Deterministic scoring uses actual hidden-objective comparisons only."""
        return ctx.output['checks']


async def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selfcheck',action='store_true',help='SDK/adapter plumbing only; does not invoke model')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--fault',choices=['limit','type','dimension'])
    args=parser.parse_args()
    if version('pydantic-evals')!='2.66.0' or version('pydantic-ai-slim')!='2.66.0':
        raise ValueError('evaluation_and_model_sdk_versions_must_match_2_66_0')
    args.output.mkdir(parents=True,exist_ok=False)
    daq=Path(os.environ['DAQ_REPO']).resolve()
    fixtures={}
    for approved in (True,False):
        identifier='case-'+uuid.uuid4().hex[:8]
        fixtures[identifier]=IsolatedCase(args.output/identifier,daq,approved,args.fault)
    config=None;runner=None
    if not args.selfcheck:
        raw=json.loads(sys.stdin.buffer.read(1024*1024+1))
        config=raw.get('config',raw)
        if not all(isinstance(config.get(key),str) and config[key] for key in ('api_key','base_url','model')):
            raise ValueError('model_configuration_required')
        runner=load_module('actual_remote_runner',Path(os.environ['ROOT_AGENT_RUNNER']))
    async def task(inputs):
        case=fixtures[inputs['case_id']]
        if args.selfcheck:
            result=selfcheck(case)
            return {'checks':{'real_adapter_selfcheck':result['adapter_selfcheck_passed']},
                    'scope':'adapter_only_real_model_not_called'}
        return await evaluate_case(case,runner,config)
    # Only opaque IDs are Dataset inputs. The task creates the model prompt
    # independently; oracles never enter model inputs, knowledge or history.
    dataset=Dataset(name='isolated-daq-blind-evaluation',
        cases=[Case(name=identifier,inputs={'case_id':identifier}) for identifier in fixtures],
        evaluators=[ActualReceiptChecks()])
    report=await dataset.evaluate(task,max_concurrency=1,progress=False,task_timeout=305)
    encoded=EvaluationReportAdapter.dump_python(report,mode='json')
    save(args.output/'pydantic-evals-report.json',encoded)
    checks=[evaluation.value for case in report.cases for evaluation in case.assertions.values()]
    summary={'framework':'pydantic-evals','framework_version':version('pydantic-evals'),
        'model_framework':'pydantic-ai-slim','model_framework_version':version('pydantic-ai-slim'),
        'workflow_framework':'langgraph','workflow_framework_version':version('langgraph'),
        'case_count':len(report.cases),'failure_count':len(report.failures),
        'failure_count_semantics':'dataset_task_exceptions_only; workflow failures appear in assertions',
        'confirmed_model_case_count':sum(case.output.get('model_called') is True for case in report.cases)
            if not args.selfcheck else 0,
        'completed_workflow_case_count':sum(case.output.get('workflow_completed') is True for case in report.cases)
            if not args.selfcheck else 0,
        'passed':bool(checks) and all(checks) and not report.failures,'selfcheck_only':args.selfcheck,
        'real_model_called':not args.selfcheck,'robot_reset_executed':False,
        'scope':'isolated_real_model_blind_evaluation' if not args.selfcheck else 'sdk_and_adapter_selfcheck'}
    save(args.output/'evaluation-summary.json',summary)
    print(json.dumps({'output':str(args.output),'summary':summary},ensure_ascii=False))


if __name__=='__main__':
    try:asyncio.run(main())
    except Exception as error:
        print(json.dumps({'error':type(error).__name__,'scope':'evaluation_incomplete'}),file=sys.stderr)
        sys.exit(1)
