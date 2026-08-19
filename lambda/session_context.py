from __future__ import annotations

import re
from typing import Any

import boto3

SESSION_ARN = re.compile(
    r"^arn:aws:wisdom:(?P<region>[^:]+):(?P<account>\d{12}):session/(?P<assistant>[a-f0-9-]{36})/(?P<session>[a-f0-9-]{36})$"
)


def _required(params: dict[str, Any], key: str) -> str:
    value = str(params.get(key) or "").strip()
    if not value:
        raise ValueError(f"Missing required Lambda invocation parameter: {key}")
    return value


def handler(event: dict[str, Any], context: Any) -> dict[str, str]:
    # Identity has already been deterministically confirmed by the dedicated
    # identity Lex bot before this Lambda is invoked. Do not log the incoming
    # event because it contains customer-specific data.
    details = event.get("Details") or {}
    params = details.get("Parameters") or {}
    if str(params.get("operation") or "initialize").strip() != "initialize":
        raise ValueError("Unsupported operation")

    assistant_id = _required(params, "assistantId")
    session_arn = _required(params, "sessionArn")
    customer_name = _required(params, "customerName")
    expected_phone = _required(params, "expectedPhone")

    match = SESSION_ARN.fullmatch(session_arn)
    if not match:
        raise ValueError("Unexpected Amazon Q session ARN")
    if match.group("assistant") != assistant_id:
        raise ValueError("Session ARN does not belong to the configured assistant")

    boto3.client("qconnect", region_name=match.group("region")).update_session_data(
        assistantId=assistant_id,
        sessionId=session_arn,
        namespace="Custom",
        data=[
            {"key": "customerName", "value": {"stringValue": customer_name}},
            {"key": "expectedPhone", "value": {"stringValue": expected_phone}},
            {"key": "identityPolicyVersion", "value": {"stringValue": "v6-cara-conversational"}},
            {"key": "identityConfirmed", "value": {"stringValue": "true"}},
            {"key": "conversationState", "value": {"stringValue": "PATIENT_CONFIRMED"}},
        ],
    )
    return {"contextStatus": "READY", "identityConfirmed": "true"}
