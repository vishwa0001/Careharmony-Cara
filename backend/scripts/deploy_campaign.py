import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cara_health_bot.campaign_deployer import CampaignDeployer, CampaignDeploymentError


def main() -> int:
    parser = argparse.ArgumentParser(description="Deploy or validate Cara Health Bot campaign infrastructure")
    parser.add_argument("--dry-run", action="store_true", help="Validate pipeline without placing real calls or modifying AWS")
    args = parser.parse_args()

    try:
        output = CampaignDeployer(ROOT, dry_run=args.dry_run).deploy()
    except Exception as error:
        print(f"Campaign deployment error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(output, indent=2))
    if args.dry_run:
        print("\nCara Health Bot campaign workaround dry-run validation complete.")
    else:
        print("\nCara Health Bot campaign workaround is deployed and verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
