#!/usr/bin/env bash
# Card 959 / F-precheck: cheap checks before a Pass ask.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec python3 "$ROOT/tools/precheck.py" "$@"
