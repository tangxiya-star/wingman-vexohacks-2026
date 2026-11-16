#!/bin/zsh
set -eu
cd -- "$(dirname -- "$0")"
exec node server/scripts/start-local.mjs
