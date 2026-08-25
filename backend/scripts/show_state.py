#!/usr/bin/env python3
from pathlib import Path
import json

path = Path(__file__).resolve().parents[1] / "deployment-state.json"
if not path.is_file():
    raise SystemExit("deployment-state.json not found. Run ./deploy.sh first.")
print(json.dumps(json.loads(path.read_text(encoding="utf-8")), indent=2))
