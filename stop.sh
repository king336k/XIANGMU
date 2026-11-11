#!/usr/bin/env bash
set -euo pipefail
project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [[ ${1:-} == --help ]]; then
  printf '%s\n' '用法：./stop.sh' '停止本项目服务，保留数据库、附件、配置和数据卷。'
  exit 0
fi
if [[ $# -ne 0 ]]; then printf '%s\n' '参数无效，请使用 ./stop.sh --help' >&2; exit 2; fi
cd "$project_root"
if [[ ! -f deploy/local/.env ]]; then
  printf '%s\n' '缺少本项目配置：deploy/local/.env；未停止任何服务。' >&2
  exit 1
fi
exec docker compose --env-file deploy/local/.env stop
