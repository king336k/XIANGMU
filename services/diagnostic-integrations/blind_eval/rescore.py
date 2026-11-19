#!/usr/bin/env python3
"""Reassess saved objective and model/tool receipts without replaying any tool."""
import argparse
import json
from pathlib import Path

import yaml

from harness import IsolatedCase, save


def rescore_case(root):
    objective=json.loads((root/'hidden-objective.json').read_text())
    before=json.loads((root/'inspect-before.json').read_text())
    after=json.loads((root/'inspect-after.json').read_text())
    result=json.loads((root/'model-report.json').read_text())
    class SavedService:
        def inspect(self,robot):return after
    case=object.__new__(IsolatedCase)
    case.root=root;case.oracle=objective;case.approved=objective['approved'];case.robot='dexforce'
    case.registry=json.loads((root/'pre-fault-snapshot.json').read_text())
    case.events=json.loads((root/'actual-tool-trajectory.json').read_text())
    case.project=root/'isolated-release/remote_control_robot';case.artifact=case.project/'robot_config'
    case.state=root/'isolated-device-state';case.relative=Path('robot/dexforce/robot_description.yaml')
    case.service=SavedService();case.yaml=yaml
    # Original corrupted bytes are verified against the recorded pre-run SHA;
    # they are not inferred from model text or used as a repair input.
    artifact_hash=next(row['sha256'] for row in before['files'] if row['role']=='artifact')
    import hashlib
    data=(case.artifact/case.relative).read_bytes()
    if hashlib.sha256(data).hexdigest()!=artifact_hash:
        raise ValueError('saved_artifact_changed_since_before_inspection')
    case.source_after_fault=data
    # The current score code only reads these saved objects and actual files.
    # Keep original score/report untouched for auditability.
    return case.score(result,model_called=True if case.events else None,persist=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run',type=Path)
    args=parser.parse_args()
    scores=[]
    for case in sorted(args.run.glob('case-*')):
        score=rescore_case(case)
        save(case/'score-reviewed.json',score);scores.append(score)
    save(args.run/'score-review-summary.json',{'rescored_without_model_or_tool_replay':True,
        'cases':scores,'passed':bool(scores) and all(score['passed'] for score in scores)})
    print(json.dumps({'cases':[{'case_id':row['case_id'],'model_called':row['model_called'],
        'workflow_completed':row['workflow_completed'],'progress':row['progress'],'passed':row['passed']} for row in scores]},ensure_ascii=False))


if __name__=='__main__':main()
