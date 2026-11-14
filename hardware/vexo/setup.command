#!/bin/zsh
set -euo pipefail
cd -- "${0:A:h}"

sdk_commit=1e4291e2fa4896b1f603d3d4f0b009c483425da0
if ! command -v python3.12 >/dev/null; then
  print -u2 -- "需要 Python 3.12。安装后重新运行 ./setup.command。"
  exit 1
fi
if ! command -v git >/dev/null; then
  print -u2 -- "需要 Git。安装后重新运行 ./setup.command。"
  exit 1
fi

git submodule update --init --recursive -- vexo-open-kit
if [[ "$(git -C vexo-open-kit rev-parse HEAD)" != "$sdk_commit" ]]; then
  print -u2 -- "Vexo SDK 版本与此演示不一致；需要 $sdk_commit。"
  exit 1
fi

if [[ -e .venv && ! -x .venv/bin/python ]]; then
  print -u2 -- ".venv 不完整；请先移走该目录，再重新运行 ./setup.command。"
  exit 1
fi
if [[ -x .venv/bin/python ]] && ! .venv/bin/python -c 'import sys; sys.exit(sys.version_info[:2] != (3, 12))'; then
  print -u2 -- ".venv 不是 Python 3.12；请先移走该目录，再重新运行 ./setup.command。"
  exit 1
fi

python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install --no-deps ./vexo-open-kit/python

print -- "安装完成。下一步：cp .env.example .env.local"
print -- "编辑 .env.local，填写自己确认的 HEARTCAST_SOURCE_ID / WHOOP_SOURCE_ID。"
print -- "扫描设备：./start_heart_rate.command --scan 或 ./start_whoop_heart_rate.command --scan"
print -- "无硬件演示：./start_heart_rate.command --sim --temperature-demo --seconds 20"
