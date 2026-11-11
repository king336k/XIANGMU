#!/usr/bin/env python3
"""Check staged initial knowledge without DB; apply only to an explicit existing admin/project."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys


def main(argv=None):
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--seed-dir',default=str(Path(__file__).parent/'initial-knowledge'));p.add_argument('--check',action='store_true');p.add_argument('--apply',action='store_true');p.add_argument('--workspace');p.add_argument('--project');p.add_argument('--actor');args=p.parse_args(argv)
 try:
  if args.check and args.apply:raise ValueError('Choose check or apply')
  root=Path(__file__).resolve().parents[2]
  target=None;actor=None
  if args.apply and all([args.workspace,args.project,args.actor]):
   sys.path.insert(0,str(root/'ProjectServer') if (root/'ProjectServer').exists() else '/code');os.environ.setdefault('DJANGO_SETTINGS_MODULE','plane.settings.production');import django;django.setup()
   from plane.db.models import User,Project
   from plane.license.models import InstanceConfiguration
   from plane.knowledge.initial_seed import import_seed,INITIALIZED_KEY
   target=Project.objects.get(id=args.project,workspace__slug=args.workspace);actor=User.objects.get(id=args.actor,is_active=True)
   if InstanceConfiguration.objects.filter(key=INITIALIZED_KEY).exists():
    report=import_seed(None,target,actor)
    print(json.dumps(report,ensure_ascii=False));return 0
  source=root/'ProjectServer/plane/knowledge/initial_seed.py'
  if not source.is_file():source=Path('/code/plane/knowledge/initial_seed.py')
  spec=importlib.util.spec_from_file_location('initial_seed_validator',source);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);bundle,checked=module.check_seed_dir(args.seed_dir)
  if not args.apply or not all([args.workspace,args.project,args.actor]):
   print(json.dumps({**checked,'status':'checked' if not args.apply else 'staged_pending_admin','imported':0,'published':0,'requires_explicit_target':True},ensure_ascii=False));return 0
  report=import_seed(bundle,target,actor);print(json.dumps({**report,'imported':report['created'],'published':0},ensure_ascii=False));return 0
 except Exception as e:
  print(json.dumps({'status':'failed','error':str(e) if isinstance(e,ValueError) else 'Seed check/import failed; sensitive diagnostics suppressed','imported':0,'published':0}));return 1
if __name__=='__main__':raise SystemExit(main())
