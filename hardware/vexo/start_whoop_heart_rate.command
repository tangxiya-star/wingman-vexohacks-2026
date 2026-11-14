#!/bin/zsh
set -euo pipefail
cd -- "${0:A:h}"

source_id="${WHOOP_SOURCE_ID:-}"
source_name="${WHOOP_NAME:-}"
[[ ! -f .env.local ]] || source ./.env.local
source_id="${source_id:-${WHOOP_SOURCE_ID:-}}"
source_name="${source_name:-${WHOOP_NAME:-WHOOP}}"

typeset -a defaults=(--label "$source_name")
needs_source=1
for argument in "$@"; do
  case "$argument" in
    --source|--source=*|--scan|-h|--help) needs_source=0 ;;
  esac
done
if (( needs_source )); then
  if [[ -z "$source_id" ]]; then
    print -u2 -- "请在 .env.local 设置 WHOOP_SOURCE_ID，或使用 --source 指定自己的设备。"
    print -u2 -- "先扫描：./start_whoop_heart_rate.command --scan"
    exit 2
  fi
  defaults+=(--source "$source_id")
fi
if [[ ! -x .venv/bin/python ]]; then
  print -u2 -- "开发环境尚未安装，请先运行 ./setup.command。"
  exit 1
fi
exec .venv/bin/python -u heart_rate_receiver.py "${defaults[@]}" "$@"
