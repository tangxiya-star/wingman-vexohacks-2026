#!/bin/zsh
set -euo pipefail
cd -- "${0:A:h}"
exec ./start_whoop_dashboard.command --band 77 --raise-hand --motion-mode accel-latch "$@"
