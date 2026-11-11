#!/usr/bin/env bash
set -euo pipefail
project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
if [[ ${1:-} == --help ]]; then
  printf '%s\n' '用法：./deploy/build.sh' '按锁文件安装依赖、编译前端与协作服务，再构建本项目API、前端、协作镜像；不启动服务。'
  exit 0
fi
if [[ $# -ne 0 ]]; then printf '%s\n' '参数无效，请使用 ./deploy/build.sh --help' >&2; exit 2; fi
cd "$project_root"
pnpm install --frozen-lockfile
pnpm build:platform
for service in api web live diagnostic-worker; do
  docker build -t "engramproject/${service}:local" -f "deploy/local/Dockerfile.${service}" .
done
