#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

from botocore.exceptions import BotoCoreError, ClientError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cara_health_bot.config import load_config
from cara_health_bot.deployer import DeploymentError, CaraHealthBotDeployer, format_aws_error


def main() -> int:
    try:
        cfg = load_config()
        d = CaraHealthBotDeployer(cfg)
        d.account_id = d.sts.get_caller_identity()["Account"]
        output = d.verify()
        print(json.dumps(output, indent=2))
        return 0
    except (DeploymentError, ValueError, OSError, json.JSONDecodeError) as error:
        print(f"Check failed: {error}", file=sys.stderr)
        return 2
    except (ClientError, BotoCoreError) as error:
        print(f"AWS error: {format_aws_error(error)}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
