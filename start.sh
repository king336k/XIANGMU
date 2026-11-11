#!/usr/bin/env bash
set -euo pipefail
project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [[ ${1:-} == --help ]]; then
  printf '%s\n' '用法：./start.sh' '启动已构建的本机平台，不编译代码、不构建或拉取镜像。' '首次使用：python3 scripts/init_local_config.py，然后 ./deploy/build.sh'
  exit 0
fi
if [[ $# -ne 0 ]]; then printf '%s\n' '参数无效，请使用 ./start.sh --help' >&2; exit 2; fi
cd "$project_root"
if [[ ! -f deploy/local/.env ]]; then
  printf '%s\n' '尚未初始化配置，请先运行：python3 scripts/init_local_config.py' >&2
  exit 1
fi
if [[ -e deploy/local/builtin-embedding.json || -L deploy/local/builtin-embedding.json ]]; then
  exec python3 services/embedding-service/setup_platform.py --apply --resume --start-platform --project-root "$project_root"
fi
exec docker compose --env-file deploy/local/.env up -d --no-build --pull never
