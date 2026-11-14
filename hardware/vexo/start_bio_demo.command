#!/bin/zsh
set -euo pipefail
cd -- "${0:A:h}"
exec ./start_heart_rate.command --temperature-demo --raise-hand "$@"
