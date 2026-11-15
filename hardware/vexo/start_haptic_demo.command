#!/bin/zsh
set -euo pipefail
cd -- "${0:A:h}"

# Match the other launchers: CLI > environment > this checkout's .env.local.
whoop_source="${WHOOP_SOURCE_ID:-}"
whoop_serial="${WHOOP_SERIAL:-}"
heartcast_source="${HEARTCAST_SOURCE_ID:-}"
[[ ! -f .env.local ]] || source ./.env.local
whoop_source="${whoop_source:-${WHOOP_SOURCE_ID:-}}"
whoop_serial="${whoop_serial:-${WHOOP_SERIAL:-}}"
heartcast_source="${heartcast_source:-${HEARTCAST_SOURCE_ID:-}}"

typeset -a defaults=()
[[ -z "$whoop_source" ]] || defaults+=(--whoop-source "$whoop_source")
[[ -z "$whoop_serial" ]] || defaults+=(--whoop-serial "$whoop_serial")
[[ -z "$heartcast_source" ]] || defaults+=(--heartcast-source "$heartcast_source")
if [[ ! -x .venv/bin/python ]]; then
  print -u2 -- "开发环境尚未安装，请先运行 ./setup.command。"
  exit 1
fi
exec .venv/bin/python -u haptic_demo.py "${defaults[@]}" "$@"
