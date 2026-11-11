"""Run inside the target Django environment. Default action is dry-run."""
import argparse
import json
from pathlib import Path
import os
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'ProjectServer'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE','plane.settings.production')
import django
django.setup()
from django.db import transaction
from plane.db.models import User
from plane.quality.legacy_migration import build_plan,apply_plan,rollback,validate_targets,preview_plan

parser=argparse.ArgumentParser()
parser.add_argument('action',choices=['dry-run','apply','rollback'])
parser.add_argument('--source',type=Path);parser.add_argument('--mapping',type=Path)
parser.add_argument('--actor',required=True);parser.add_argument('--run-id');parser.add_argument('--output',required=True,type=Path)
args=parser.parse_args()
try:
    actor=User.objects.get(pk=args.actor,is_active=True)
    if args.action=='rollback':
        if not args.run_id:raise ValueError('--run-id required')
        result=rollback(args.run_id,actor)
    else:
        if not args.source or not args.mapping:raise ValueError('--source and --mapping required')
        plan=build_plan(json.loads(args.source.read_text()),json.loads(args.mapping.read_text()))
        if args.action=='apply':result=apply_plan(plan,actor)
        else:
            if not plan['conflicts']:
                try:plan['target_preview']=preview_plan(plan,actor)
                except ValueError as error:plan['conflicts'].append({'code':'target_conflict','reason':str(error)})
            result={key:value for key,value in plan.items() if key not in {'rows','attachments','mapping'}}
            result['mapping_preview']=[{'table':row['table'],'source_id':row['key'],'target_id':row['id'],'disposition':row['disposition'],'source_hash':row['source_hash']} for row in plan['rows']]
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');args.output.chmod(0o600)
    print(json.dumps({'action':args.action,'conflicts':len(result.get('conflicts',[])),'output':str(args.output)},ensure_ascii=False))
    if result.get('conflicts'):raise SystemExit(2)
except (ValueError,OSError) as error:
    print(str(error),file=sys.stderr);raise SystemExit(2)
