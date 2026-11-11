#!/usr/bin/env bash
set -euo pipefail
project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$project_root"
python3 - <<'PY'
from pathlib import Path
import os
import secrets

existing_keys = set()
for folder in [Path('ProjectServer'), Path('services/collaboration')]:
    config = folder / '.env'
    if config.exists():
        for line in config.read_text().splitlines():
            if line.startswith('LIVE_SERVER_SECRET_KEY='):
                value = line.partition('=')[2].strip().strip('"').strip("'")
                if value:
                    existing_keys.add(value)
if len(existing_keys) > 1:
    raise SystemExit('已有后端与协作服务配置不一致，请先核对；未改动配置。')
shared_key = next(iter(existing_keys), None) or secrets.token_hex(32)
for folder in [Path('.'), Path('ProjectFront'), Path('ProjectServer'), Path('services/admin'), Path('services/space'), Path('services/collaboration')]:
    template, target = folder / '.env.example', folder / '.env'
    if target.exists():
        print('保留已有配置：' + str(target))
        continue
    content = template.read_text()
    if folder == Path('ProjectServer'):
        content += '\nSECRET_KEY=' + secrets.token_hex(32) + '\n'
    if folder in [Path('ProjectServer'), Path('services/collaboration')]:
        lines = [line for line in content.splitlines() if not line.startswith('LIVE_SERVER_SECRET_KEY=')]
        content = '\n'.join(lines) + '\nLIVE_SERVER_SECRET_KEY=' + shared_key + '\n'
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        stream.write(content)
    print('已创建开发配置：' + str(target))
PY
