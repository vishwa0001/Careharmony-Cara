#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cara_health_bot.campaign_deployer import CampaignDeployer, CampaignDeploymentError


def main() -> int:
    try:
        output = CampaignDeployer(ROOT).deploy()
    except Exception as error:
        print(f"Campaign deployment error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(output, indent=2))
    print("\nCara Health Bot campaign workaround is deployed and verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
