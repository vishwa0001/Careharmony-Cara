#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cara_health_bot.deployer import format_aws_error



def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Show Cara Health Bot Connect flow events for an exact ContactId.")
    p.add_argument("contact_id")
    p.add_argument("--hours", type=int, default=24, help="CloudWatch lookback window (default 24 hours)")
    return p.parse_args()


def load_outputs() -> dict[str, str]:
    path = ROOT / "deployment-state.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    out = data.get("outputs", {})
    for key in ("Region", "InstanceId", "ConnectLogGroup"):
        if not out.get(key):
            raise RuntimeError(f"deployment-state.json is missing {key}")
    return out


def main() -> int:
    args = parse_args()
    try:
        out = load_outputs()
        logs = boto3.client("logs", region_name=out["Region"])
        connect = boto3.client("connect", region_name=out["Region"])
        start_ms = int((dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=args.hours)).timestamp() * 1000)
        request = {
            "logGroupName": out["ConnectLogGroup"],
            "startTime": start_ms,
            "filterPattern": f'"{args.contact_id}"',
        }
        events: list[dict] = []
        previous = None
        while True:
            response = logs.filter_log_events(**request)
            events.extend(response.get("events", []))
            token = response.get("nextToken")
            if not token or token == previous:
                break
            previous = token
            request["nextToken"] = token
        print("=== Connect flow events ===")
        if not events:
            print("No matching flow-log events found in the selected time window.")
        for event in sorted(events, key=lambda x: x.get("timestamp", 0)):
            message = event.get("message", "")
            try:
                print(json.dumps(json.loads(message), indent=2, default=str))
            except json.JSONDecodeError:
                print(message)
        print("\n=== Contact record ===")
        record = connect.describe_contact(InstanceId=out["InstanceId"], ContactId=args.contact_id)["Contact"]
        fields = {k: record.get(k) for k in (
            "Id", "InitiationMethod", "InitiationTimestamp", "ConnectedToSystemTimestamp", "DisconnectTimestamp", "DisconnectDetails"
        )}
        print(json.dumps(fields, indent=2, default=str))
        print("\n=== Contact attributes ===")
        try:
            attrs = connect.get_contact_attributes(
                InstanceId=out["InstanceId"],
                InitialContactId=args.contact_id,
            ).get("Attributes", {})
            interesting = {k: attrs[k] for k in sorted(attrs) if k in {
                "customerName", "expectedPhone", "identityPolicyVersion",
                "identityConfirmed", "recipientType", "targetAvailableNow",
                "callbackDate", "callbackTime",
            }}
            print(json.dumps(interesting, indent=2, default=str))
        except ClientError as error:
            print(f"Could not read contact attributes: {format_aws_error(error)}")
        return 0
    except FileNotFoundError:
        print("deployment-state.json not found. Run ./deploy.sh first.", file=sys.stderr)
        return 2
    except RuntimeError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    except (ClientError, BotoCoreError) as error:
        print(f"AWS error: {format_aws_error(error)}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
