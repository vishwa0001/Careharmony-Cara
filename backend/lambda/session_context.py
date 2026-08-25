from __future__ import annotations

import re
import unicodedata
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


def _optional(params: dict[str, Any], key: str) -> str:
    return str(params.get(key) or "").strip()


def _name_token(value: str) -> str:
    # Normalize case, accents, punctuation, apostrophes and hyphens without
    # introducing fuzzy/nickname matching. Identity must remain conservative.
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(ch for ch in decomposed if ch.isalnum() and not unicodedata.combining(ch))


def _expected_name_parts(value: str) -> list[str]:
    return [_name_token(part) for part in re.findall(r"[^\s]+", value) if _name_token(part)]


def _verify_identity_name(expected: str, first: str, last: str) -> str:
    expected_parts = _expected_name_parts(expected)
    first_norm = _name_token(first)
    last_norm = _name_token(last)

    if not expected_parts or not first_norm:
        return "ambiguous"

    # Existing single-name callers remain supported.
    if len(expected_parts) == 1:
        if last_norm:
            return "false"
        return "true" if first_norm == expected_parts[0] else "false"

    # For a configured full name, require both first and last name. Ignore
    # middle names in the configured value, but do not accept a first-name-only
    # match as full identity confirmation.
    if not last_norm:
        return "ambiguous"
    return (
        "true"
        if first_norm == expected_parts[0] and last_norm == expected_parts[-1]
        else "false"
    )


def handler(event: dict[str, Any], context: Any) -> dict[str, str]:
    # Do not log the incoming event because it contains customer-specific data.
    details = event.get("Details") or {}
    params = details.get("Parameters") or {}
    operation = str(params.get("operation") or "initialize").strip()

    if operation == "verifyIdentityName":
        expected = _required(params, "expectedCustomerName")
        result = _verify_identity_name(
            expected,
            _optional(params, "spokenFirstName"),
            _optional(params, "spokenLastName"),
        )
        return {"identityMatch": result}

    if operation != "initialize":
        raise ValueError("Unsupported operation")

    # At this point identity has already been deterministically confirmed by
    # either a contextual confirmation (for example, "speaking") or the
    # full-name validator above.
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
            {"key": "identityPolicyVersion", "value": {"stringValue": "v7-full-name-validated"}},
            {"key": "identityConfirmed", "value": {"stringValue": "true"}},
            {"key": "conversationState", "value": {"stringValue": "PATIENT_CONFIRMED"}},
        ],
    )
    return {"contextStatus": "READY", "identityConfirmed": "true"}
