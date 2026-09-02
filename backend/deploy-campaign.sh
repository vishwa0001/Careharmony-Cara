#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

export AWS_PAGER=""
REGION="$(python3 -c 'import json; print(json.load(open("config.json"))["region"])')"
export AWS_REGION="$REGION"
export AWS_DEFAULT_REGION="$REGION"

if [[ ! -f deployment-state.json ]]; then
  echo "deployment-state.json not found. Deploy the base Cara Health Bot first with ./deploy.sh" >&2
  exit 1
fi

if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/validate.py
python -m unittest discover -s tests -v
aws sts get-caller-identity --output json
python scripts/deploy_campaign.py
