#!/usr/bin/env python3
"""Create private local configuration without replacing an existing file."""
from pathlib import Path
import os
import secrets

root = Path(__file__).resolve().parent.parent
path = root / 'deploy/local/.env'
content = (path.parent / '.env.example').read_text()
secret_keys = {'POSTGRES_PASSWORD', 'RABBITMQ_PASSWORD', 'AWS_SECRET_ACCESS_KEY', 'SECRET_KEY', 'LIVE_SERVER_SECRET_KEY'}
lines = []
for line in content.splitlines():
    key, separator, value = line.partition('=')
    if separator and key in secret_keys:
        line = key + '=' + secrets.token_hex(32)
    lines.append(line)
try:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    raise SystemExit('配置已存在，保留现有文件：' + str(path))
with os.fdopen(descriptor, 'w') as stream:
    stream.write('\n'.join(lines) + '\n')
print('本地配置已创建：' + str(path))
