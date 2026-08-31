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


def _fetch_agent_availability(patient_id: str, empi: str) -> dict[str, str]:
    import os
    import json
    import urllib.request
    import urllib.parse
    import datetime as dt

    now_iso = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    url = os.environ.get("AGENT_AVAILABILITY_URL", "https://uqyt6tgmp3dktodmkrkxqmn3f40wndqq.lambda-url.us-east-1.on.aws/")
    fixed_phone = os.environ.get("FIXED_AGENT_PHONE", "+15822671755")

    try:
        target_url = url
        params = {}
        if patient_id:
            params["patientId"] = patient_id
        if empi:
            params["empi"] = empi
        if params:
            query = urllib.parse.urlencode(params)
            target_url = f"{url}?{query}" if "?" not in url else f"{url}&{query}"
        with urllib.request.urlopen(target_url, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            available = bool(data.get("available"))
            agent_phone = str(data.get("agentPhone") or fixed_phone)
            checked_at = str(data.get("checkedAt") or now_iso)
            return {
                "available": "true" if available else "false",
                "agentPhone": agent_phone,
                "agentCheckedAt": checked_at,
            }
    except Exception as e:
        print(f"[WARN] _fetch_agent_availability failed: {e}")
        return {
            "available": "false",
            "agentPhone": fixed_phone,
            "agentCheckedAt": now_iso,
        }


def handler(event: dict[str, Any], context: Any) -> dict[str, str]:
    # Do not log the incoming event because it contains customer-specific data.
    details = event.get("Details") or {}
    params = details.get("Parameters") or {}
    operation = str(params.get("operation") or "initialize").strip()

    if operation == "checkAgentAvailability":
        patient_id = _optional(params, "patientId")
        empi = _optional(params, "empi")
        return _fetch_agent_availability(patient_id, empi)

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
    direct_agent = _optional(params, "direct_agent") or _optional(params, "directAgent") or "no"
    practice_name = _optional(params, "practiceName")
    first_name = _optional(params, "firstName")

    match = SESSION_ARN.fullmatch(session_arn)
    if not match:
        raise ValueError("Unexpected Amazon Q session ARN")
    if match.group("assistant") != assistant_id:
        raise ValueError("Session ARN does not belong to the configured assistant")

    session_data = [
        {"key": "customerName", "value": {"stringValue": customer_name}},
        {"key": "expectedPhone", "value": {"stringValue": expected_phone}},
        {"key": "identityPolicyVersion", "value": {"stringValue": "v7-full-name-validated"}},
        {"key": "identityConfirmed", "value": {"stringValue": "true"}},
        {"key": "conversationState", "value": {"stringValue": "PATIENT_CONFIRMED"}},
        {"key": "direct_agent", "value": {"stringValue": direct_agent or "no"}},
    ]
    if practice_name:
        session_data.append({"key": "practiceName", "value": {"stringValue": practice_name}})
    if first_name:
        session_data.append({"key": "firstName", "value": {"stringValue": first_name}})

    boto3.client("qconnect", region_name=match.group("region")).update_session_data(
        assistantId=assistant_id,
        sessionId=session_arn,
        namespace="Custom",
        data=session_data,
    )
    return {"contextStatus": "READY", "identityConfirmed": "true"}
