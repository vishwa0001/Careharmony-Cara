#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
if [[ "${I_UNDERSTAND_CARA_HEALTH_BOT_CLEANUP:-}" != "YES" ]]; then
  echo "Cleanup can release the project's claimed phone number and delete project resources."
  echo "Run: I_UNDERSTAND_CARA_HEALTH_BOT_CLEANUP=YES ./cleanup.sh"
  exit 2
fi
source .venv/bin/activate 2>/dev/null || true
python scripts/cleanup.py
