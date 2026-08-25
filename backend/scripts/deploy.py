#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cara_health_bot.config import load_config
from cara_health_bot.deployer import DeploymentError, CaraHealthBotDeployer, format_aws_error


def main() -> int:
    try:
        cfg = load_config()
        output = CaraHealthBotDeployer(cfg).deploy()
    except NoCredentialsError as error:
        print(f"AWS credentials error: {error}", file=sys.stderr)
        return 2
    except (ClientError, BotoCoreError) as error:
        print(f"AWS error: {format_aws_error(error)}", file=sys.stderr)
        return 3
    except (DeploymentError, ValueError, OSError, json.JSONDecodeError) as error:
        print(f"Deployment error: {error}", file=sys.stderr)
        return 4
    print()
    print(json.dumps(output, indent=2))
    print()
    print(f"{cfg.display_name} is deployed and verified.")
    print()
    print("Human agent:")
    print(f"  Username: {output['HumanAgentUsername']}")
    print(f"  Agent Workspace: {output['AgentWorkspaceUrl']}")
    print("  Sign in, then set the agent status to Available.")
    print()
    print("To place a consented US test call:")
    print('  python3 scripts/call.py "+1XXXXXXXXXX" --customer-name "John" --i-confirm-consent')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
