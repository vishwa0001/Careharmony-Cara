#!/usr/bin/env python3
"""CLI script to initiate a Direct Human Handoff call for CareHarmony-CARA."""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cara_health_bot.config import load_config
from cara_health_bot.deployer import format_aws_error
from cara_health_bot.phone_utils import normalize_phone_e164 as normalize_phone

E164_PATTERN = re.compile(r"^\+[1-9]\d{7,14}$")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Place a Direct Human Handoff outbound call connecting a customer to a human agent."
    )
    p.add_argument(
        "customer_phone",
        help="Destination customer phone number in E.164 or 10/11-digit US format (e.g. +18145551212 or 8145551212)",
    )
    p.add_argument(
        "--customer-name",
        required=True,
        help="Expected customer name to confirm before transfer",
    )
    p.add_argument(
        "--human-agent-phone",
        required=True,
        help="Human agent phone number in E.164 or 10/11-digit US format (e.g. +18145559999 or 8145559999)",
    )
    p.add_argument(
        "--i-confirm-consent",
        action="store_true",
        help="Required acknowledgment that the recipient expects and consents to the automated call",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the validated Connect API request without placing a call",
    )
    return p.parse_args()


def load_outputs() -> dict[str, str]:
    path = ROOT / "deployment-state.json"
    if not path.is_file():
        raise RuntimeError("deployment-state.json not found. Run ./deploy.sh first.")
    data = json.loads(path.read_text(encoding="utf-8"))
    out = data.get("outputs", {})
    for key in ("InstanceId", "SourcePhoneNumber", "ContactFlowId", "Region"):
        if not out.get(key):
            raise RuntimeError(f"deployment-state.json is missing output: {key}")
    return out


def normalize_phone(raw: str) -> str:
    value = (raw or "").strip()
    if E164_PATTERN.fullmatch(value):
        return value
    digits = re.sub(r"\D", "", value)
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    raise ValueError("phone number must be E.164 format or a 10/11 digit US number")


def validate_customer_name(name: str) -> str:
    value = " ".join(name.strip().split())
    if not (1 <= len(value) <= 80):
        raise ValueError("customer name must be between 1 and 80 characters")
    if any(not (ch.isalpha() or ch in " .\'-") for ch in value):
        raise ValueError("customer name may contain letters, spaces, period, apostrophe, and hyphen only")
    return value


def redact(phone: str) -> str:
    if len(phone) <= 6:
        return phone
    return phone[:-4] + "XXXX"


def main() -> int:
    args = parse_args()

    try:
        customer_phone = normalize_phone(args.customer_phone)
    except ValueError as error:
        print(f"Error: customer phone: {error}", file=sys.stderr)
        return 2

    try:
        human_agent_phone = normalize_phone(args.human_agent_phone)
    except ValueError as error:
        print(f"Error: human agent phone: {error}", file=sys.stderr)
        return 2

    try:
        customer_name = validate_customer_name(args.customer_name)
    except ValueError as error:
        print(f"Error: customer name: {error}", file=sys.stderr)
        return 2

    try:
        cfg = load_config()
    except Exception as error:
        print(f"Error loading configuration: {error}", file=sys.stderr)
        return 4

    if not any(customer_phone.startswith(prefix) for prefix in cfg.allowed_destination_prefixes):
        print(
            f"Error: customer destination phone must match one of allowed prefixes {cfg.allowed_destination_prefixes}",
            file=sys.stderr,
        )
        return 2

    if not any(human_agent_phone.startswith(prefix) for prefix in cfg.allowed_destination_prefixes):
        print(
            f"Error: human agent destination phone must match one of allowed prefixes {cfg.allowed_destination_prefixes}",
            file=sys.stderr,
        )
        return 2

    if not args.i_confirm_consent:
        print(
            "Error: pass --i-confirm-consent only when the recipient expects and consents to this call.",
            file=sys.stderr,
        )
        return 2

    try:
        out = load_outputs()
        request = {
            "DestinationPhoneNumber": customer_phone,
            "ContactFlowId": out["ContactFlowId"],
            "InstanceId": out["InstanceId"],
            "SourcePhoneNumber": out["SourcePhoneNumber"],
            "ClientToken": str(uuid.uuid4()),
            "Name": f"{cfg.display_name} direct human handoff call",
            "Description": f"Consented direct human handoff call for {customer_name}",
            "TrafficType": "GENERAL",
            "Attributes": {
                "customerName": customer_name,
                "expectedPhone": customer_phone,
                "humanAgentPhoneNumber": human_agent_phone,
                "callMode": "DIRECT_HUMAN_HANDOFF",
            },
        }

        if args.dry_run:
            print("Direct Human Handoff Request: VALID\n")
            print("Customer:")
            print(f"  Name: {customer_name}")
            print(f"  Phone: {redact(customer_phone)}")
            print("\nHuman Agent:")
            print(f"  Phone: {redact(human_agent_phone)}")
            print("\nAmazon Connect:")
            print(f"  Instance: {out['InstanceId']}")
            print(f"  Contact Flow: {out['ContactFlowId']}")
            print(f"  Source Phone: {redact(out['SourcePhoneNumber'])}")
            print("\nStatus: DRY RUN")
            print("AWS Call: NOT EXECUTED")

            shown = dict(request)
            shown["DestinationPhoneNumber"] = redact(shown["DestinationPhoneNumber"])
            shown["SourcePhoneNumber"] = redact(shown["SourcePhoneNumber"])
            shown["Attributes"] = dict(shown["Attributes"])
            shown["Attributes"]["expectedPhone"] = redact(shown["Attributes"]["expectedPhone"])
            shown["Attributes"]["humanAgentPhoneNumber"] = redact(shown["Attributes"]["humanAgentPhoneNumber"])
            print("\nPayload:")
            print(json.dumps(shown, indent=2))
            return 0

        connect = boto3.client("connect", region_name=out["Region"])
        response = connect.start_outbound_voice_contact(**request)
        print("Direct Human Handoff call started.")
        print("ContactId:", response["ContactId"])
        return 0

    except NoCredentialsError as error:
        print(f"AWS credentials error: {error}", file=sys.stderr)
        return 3
    except (ClientError, BotoCoreError) as error:
        print(f"AWS error: {format_aws_error(error)}", file=sys.stderr)
        return 3
    except (RuntimeError, ValueError, OSError, json.JSONDecodeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
