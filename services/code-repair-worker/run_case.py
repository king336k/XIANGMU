#!/usr/bin/env python3
"""Run a real model against an isolated unknown-to-model code fault; config only on stdin."""
import argparse
import hashlib
import json
import logging
import os
from pathlib import Path
import sys
import uuid

import worker


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-id',required=True)
    parser.add_argument('--output-root',required=True)
    args=parser.parse_args()
    logging.disable(logging.CRITICAL)
    config=json.loads(sys.stdin.buffer.read(128*1024));config=config.get('config',config)
    root=Path(args.output_root).absolute();root.mkdir(parents=True,exist_ok=True)
    runroot=root/('real-model-'+uuid.uuid4().hex);runroot.mkdir()
    snapshot=runroot/'sources'/'code-repair-fixture';files=snapshot/'files';files.mkdir(parents=True)
    content={'calculator.py':'def add(a, b):\n    return a - b\n',
        'test_calculator.py':'from calculator import add\n\ndef test_add():\n    assert add(2, 3) == 5\n    assert add(-1, 2) == 1\n'}
    commit=hashlib.sha1(json.dumps(content,sort_keys=True).encode()).hexdigest()
    manifest={'schema':'remote-source-snapshot-v1','source_id':'code-repair-fixture','project_ids':[args.project_id],
        'repository_commit':commit,'source_repository':'local-fixture://isolated-calculator','files':{}}
    for name,text in content.items():
        target=files/name;target.write_text(text);target.chmod(0o444)
        manifest['files'][name]={'size':len(text.encode()),'sha256':hashlib.sha256(text.encode()).hexdigest()}
    (snapshot/'manifest.json').write_text(json.dumps(manifest));(snapshot/'manifest.json').chmod(0o444)
    files.chmod(0o555);snapshot.chmod(0o555)
    os.environ['QUALITY_REMOTE_SOURCE_SNAPSHOTS_ROOT']=str(runroot/'sources')
    os.environ['CODE_REPAIR_WORK_ROOT']=str(runroot/'runs')
    os.environ.setdefault('CODE_REPAIR_DEPENDENCIES',str(Path(__import__('pydantic').__file__).parent.parent))
    payload={'config':config,'task':{'project_id':args.project_id,'source_id':'code-repair-fixture',
        'repository_commit':commit,'problem':'The existing calculator unit tests fail. Diagnose the cause from the files and test output, make the smallest source fix, and verify the existing tests without weakening them.'},
        'test_command':'python -m pytest -q'}
    # The fixture has no Git history: make this explicit rather than implying a deployment commit.
    try:result=worker.run(payload)
    except Exception as error:result={'engine':'openhands-sdk','code_verified':False,'business_verified':False,'error_class':type(error).__name__}
    result['fixture_only']=True;result['repository_commit_semantics']='deterministic_fixture_identity_not_deployment_commit'
    (runroot/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps({'artifact_root':str(runroot),**result},ensure_ascii=False))


if __name__=='__main__':main()
