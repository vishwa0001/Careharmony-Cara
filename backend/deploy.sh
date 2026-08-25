#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

export AWS_PAGER=""
REGION="$(python3 -c 'import json; print(json.load(open("config.json"))["region"])')"
DISPLAY_NAME="$(python3 -c 'import json; print(json.load(open("config.json"))["displayName"])')"
export AWS_REGION="$REGION"
export AWS_DEFAULT_REGION="$REGION"

printf 'AWS CLI: '
aws --version
printf 'Python:  '
python3 --version
printf 'Identity:\n'
aws sts get-caller-identity --output json

echo "Creating isolated Python environment..."
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo "Running offline validation and tests..."
python scripts/validate.py
python -m unittest discover -s tests -v

echo "Deploying ${DISPLAY_NAME} as a standalone stack in ${AWS_REGION}..."
python scripts/deploy.py
