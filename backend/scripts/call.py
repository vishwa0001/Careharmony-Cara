#!/usr/bin/env python3
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

E164 = re.compile(r"^\+[1-9]\d{7,14}$")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Place one expected and consented Cara Health Bot outbound call.")
    p.add_argument("phone_number", help="Destination in E.164 format, e.g. +18145551212")
    p.add_argument("--customer-name", required=True, help="Expected customer name Cara must confirm before continuing")
    p.add_argument("--practice-name", required=True, help="Referring practice name for this call (required)")
    p.add_argument("--first-name", default=None, help="Patient first name (defaults to first token of customer-name)")
    p.add_argument("--i-confirm-consent", action="store_true", help="Required acknowledgment that the recipient expects and consents to the automated call")
    p.add_argument("--dry-run", action="store_true", help="Print the Connect API request without placing a call")
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


def render_behavior_text(
    template: str,
    *,
    customer_name: str,
    cfg,
    first_name: str | None = None,
    practice_name: str | None = None,
) -> str:
    resolved_first_name = (
        (first_name or "").strip()
        or (customer_name.strip().split()[0] if customer_name.strip() else "")
        or "the patient"
    )
    resolved_practice_name = (practice_name or "").strip()
    return template.format(
        customer_name=customer_name,
        customerName=customer_name,
        first_name=resolved_first_name,
        firstName=resolved_first_name,
        practice_name=resolved_practice_name,
        practiceName=resolved_practice_name,
        agent_name=str(cfg.cara_behavior.get("agentName") or "Cara"),
    )


def main() -> int:
    args = parse_args()
    cfg = load_config()
    if not E164.fullmatch(args.phone_number):
        print("Error: phone_number must be E.164 format, e.g. +18145551212", file=sys.stderr)
        return 2
    if not any(args.phone_number.startswith(prefix) for prefix in cfg.allowed_destination_prefixes):
        print(f"Error: destination must match one of {cfg.allowed_destination_prefixes}", file=sys.stderr)
        return 2
    if not args.i_confirm_consent:
        print("Error: pass --i-confirm-consent only when the recipient expects and consents to this automated call.", file=sys.stderr)
        return 2
    try:
        customer_name = validate_customer_name(args.customer_name)
        practice_name = (args.practice_name or "").strip()
        if not practice_name:
            print("Error: --practice-name is required and must be non-empty", file=sys.stderr)
            return 2
        resolved_first_name = (
            (args.first_name or "").strip()
            or (customer_name.strip().split()[0] if customer_name.strip() else "")
            or "the patient"
        )
        out = load_outputs()
        request = {
            "DestinationPhoneNumber": args.phone_number,
            "ContactFlowId": out["ContactFlowId"],
            "InstanceId": out["InstanceId"],
            "SourcePhoneNumber": out["SourcePhoneNumber"],
            "ClientToken": str(uuid.uuid4()),
            "Name": f"{cfg.display_name} identity-gated conversation",
            "Description": f"Consented outbound {cfg.display_name} call with expected-customer identity confirmation",
            "TrafficType": "GENERAL",
            "Attributes": {
                "customerName": customer_name,
                "firstName": resolved_first_name,
                "practiceName": practice_name,
                "expectedPhone": args.phone_number,
                "identityPolicyVersion": "v6-cara-conversational",
                "identityPrompt": f"Hi, may I speak with {customer_name}?",
                "identityClarification": render_behavior_text(
                    cfg.cara_behavior["preIdentityQuestionResponse"],
                    customer_name=customer_name,
                    first_name=resolved_first_name,
                    practice_name=practice_name,
                    cfg=cfg,
                ),
                "identityFailureMessage": f"Thanks. I need to speak directly with {customer_name}, so I'll end the call here. Have a good day.",
                "thirdPartyAvailabilityPrompt": render_behavior_text(
                    cfg.cara_behavior["otherPersonResponse"],
                    customer_name=customer_name,
                    first_name=resolved_first_name,
                    practice_name=practice_name,
                    cfg=cfg,
                ),
                "patientUnavailablePrompt": render_behavior_text(
                    cfg.cara_behavior["patientUnavailableResponse"],
                    customer_name=customer_name,
                    first_name=resolved_first_name,
                    practice_name=practice_name,
                    cfg=cfg,
                ),
                "agentUnavailablePrompt": render_behavior_text(
                    cfg.cara_behavior.get("agentUnavailableResponse", "Is there a specific time that works best for you?"),
                    customer_name=customer_name,
                    first_name=resolved_first_name,
                    practice_name=practice_name,
                    cfg=cfg,
                ),
                "thirdPartyAvailabilityClarification": f"Just to clarify, is {customer_name} available to come to the phone now?",
                "representativeResponse": render_behavior_text(
                    cfg.cara_behavior["representativeResponse"],
                    customer_name=customer_name,
                    first_name=resolved_first_name,
                    practice_name=practice_name,
                    cfg=cfg,
                ),
                "representativeTransferMessage": render_behavior_text(
                    cfg.cara_behavior.get(
                        "representativeTransferMessage",
                        "Hi, {practice_name} has some important information to share regarding {first_name}'s care. Please hold while I connect you now.",
                    ),
                    customer_name=customer_name,
                    first_name=resolved_first_name,
                    practice_name=practice_name,
                    cfg=cfg,
                ),
                "wrongNumberResponse": render_behavior_text(
                    cfg.cara_behavior["wrongNumberResponse"],
                    customer_name=customer_name,
                    first_name=resolved_first_name,
                    practice_name=practice_name,
                    cfg=cfg,
                ),
                "deceasedResponse": render_behavior_text(
                    cfg.cara_behavior["deceasedResponse"],
                    customer_name=customer_name,
                    first_name=resolved_first_name,
                    practice_name=practice_name,
                    cfg=cfg,
                ),
                "refusalResponse": render_behavior_text(
                    cfg.cara_behavior["refusalResponse"],
                    customer_name=customer_name,
                    first_name=resolved_first_name,
                    practice_name=practice_name,
                    cfg=cfg,
                ),
                "passPhonePrompt": f"Thanks. Please pass the phone to {customer_name}.",
                "handoffIdentityPrompt": f"Hi. May I confirm I'm speaking with {customer_name}?",
                "coachingGreeting": render_behavior_text(
                    cfg.cara_behavior["openingMessage"],
                    customer_name=customer_name,
                    first_name=resolved_first_name,
                    practice_name=practice_name,
                    cfg=cfg,
                ),
            },
        }
        if args.dry_run:
            shown = dict(request)
            shown["DestinationPhoneNumber"] = redact(shown["DestinationPhoneNumber"])
            shown["Attributes"] = dict(shown["Attributes"])
            shown["Attributes"]["expectedPhone"] = redact(shown["Attributes"]["expectedPhone"])
            print(json.dumps(shown, indent=2))
            return 0
        connect = boto3.client("connect", region_name=out["Region"])
        response = connect.start_outbound_voice_contact(**request)
        print("Call started.")
        print("ContactId:", response["ContactId"])
        print("The Connect flow now owns the call. If it disconnects unexpectedly, run:")
        print(f"  python3 scripts/logs.py {response['ContactId']}")
        print("To print only the Cara/customer conversation, run:")
        print(f"  python3 scripts/transcript.py {response['ContactId']}")
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
