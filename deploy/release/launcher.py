#!/usr/bin/env python3
"""Operate the exact persisted release, shared configuration and complete helper profile."""
import argparse
import importlib.util
import json
from pathlib import Path
import re

_spec = importlib.util.spec_from_file_location('engram_release_runtime', Path(__file__).with_name('install.py'))
runtime = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runtime)


def execute(root, release, record, action, since):
    rows = runtime.owned_containers(record, release)
    if action == 'logs':
        runtime.export_logs(root, record, rows, since)
    elif action == 'start':
        manifest = runtime.load_manifest((release/'deploy/release/runtime-manifest.json').read_bytes())
        runtime.verify_images(manifest)
        model_manifest = json.loads((release/'services/embedding-service/model-manifest.json').read_text())
        runtime.verify_models(root, model_manifest)
        runtime.compose_run(root, release, record, ['up', '-d', '--no-build', '--pull', 'never', *runtime.BASE, *runtime.APPS])
    elif action == 'stop':
        runtime.export_logs(root, record, rows, since)
        runtime.compose_run(root, release, record, ['stop'])
    else:
        safe = [{'service':row['Config']['Labels'].get('com.docker.compose.service'), 'status':row['State']['Status'], 'health':row['State'].get('Health',{}).get('Status')} for row in rows]
        print(json.dumps({'services':safe}, ensure_ascii=False))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deploy-root', required=True)
    parser.add_argument('action', choices=['start', 'stop', 'logs', 'status'])
    parser.add_argument('--since', default='24h')
    args = parser.parse_args(argv)
    try:
        if not re.fullmatch(r'[1-9][0-9]{0,5}[smh]', args.since): raise ValueError('invalid bounded log window')
        root = runtime.safe_root(args.deploy_root)
        release = runtime.current_release(root)
        if release is None: raise ValueError('no healthy current release')
        record = runtime.deployment_options(root)
        env = root/'shared/.env'; runtime.safe_root(str(env))
        if not env.is_file() or env.stat().st_mode & 0o077: raise ValueError('private shared environment required')
        values = runtime.read_env(env)
        if not values.get('BUILTIN_EMBEDDING_KEY') or not values.get('DOCUMENT_OCR_KEY'): raise ValueError('helper configuration missing')
        execute(root, release, record, args.action, args.since)
        print(json.dumps({'action':args.action, 'release_id':release.name, 'completed':True}, ensure_ascii=False))
        return 0
    except (ValueError, OSError, KeyError, TypeError):
        print(json.dumps({'completed':False, 'error':'Launch refused; verify current pointer, ownership and private shared configuration.'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
