"""Cara Health Bot event-driven sequential campaign dialer.

Besides the initial campaign schedule, this worker can now create one-time
patient callback schedules when either:
  * a confirmed patient asks Cara to call back at a specific time; or
  * a third party supplies the intended patient's callback date and time.

Callback schedules target this same Lambda and therefore preserve the existing
single-patient-at-a-time campaign sequencing and DISCONNECTED-event handling.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

try:
    from backend.utils.agent_availability import check_agent_availability
except ImportError:
    try:
        from utils.agent_availability import check_agent_availability
    except ImportError:
        try:
            from agent_availability import check_agent_availability
        except ImportError:
            def check_agent_availability(context: dict = {}) -> bool:
                return False

PATIENT_PENDING = "PENDING"
PATIENT_IN_PROGRESS = "IN_PROGRESS"
PATIENT_CALLBACK_SCHEDULED = "CALLBACK_SCHEDULED"
PATIENT_CALLBACK_UNSPECIFIED = "CALLBACK_UNSPECIFIED"
PATIENT_COMPLETED = "COMPLETED"
PATIENT_NOT_INTERESTED = "NOT_INTERESTED"
PATIENT_FAILED = "FAILED"
PATIENT_SETUP_FAILED = "CALL_SETUP_FAILED"
PATIENT_AGENT_UNAVAILABLE = "AGENT_UNAVAILABLE"
CAMPAIGN_PENDING = "PENDING"
CAMPAIGN_RUNNING = "RUNNING"
CAMPAIGN_COMPLETED = "COMPLETED"
CAMPAIGN_RECORD_KEY = "CAMPAIGN"
MAX_SETUP_FAILURES_PER_INVOCATION = 5
MAX_CALLBACKS_PER_PATIENT = 3
CALLBACK_DEFER_SECONDS = 60

DISPOSITIONS = {
    "Confirmed": "Identity Confirmed",
    "Denied": "Wrong Person / Identity Denied",
    "Ambiguous": "Identity Unclear",
    "Deceased": "Patient Deceased",
    None: "Unknown / Undetermined",
}
NOT_CONNECTED_REASONS = {
    "TELECOM_BUSY",
    "TELECOM_NUMBER_INVALID",
    "TELECOM_POTENTIAL_BLOCKING",
    "TELECOM_UNANSWERED",
    "TELECOM_TIMEOUT",
    "TELECOM_ORIGINATOR_CANCEL",
    "TELECOM_PROBLEM",
    "CUSTOMER_NEVER_ARRIVED",
    "OUTBOUND_DESTINATION_ENDPOINT_ERROR",
    "OUTBOUND_RESOURCE_ERROR",
    "OUTBOUND_ATTEMPT_FAILED",
    "EXPIRED",
}


def _now_dt() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _now() -> str:
    return _now_dt().strftime("%Y-%m-%dT%H:%M:%SZ")


def _batches_table():
    return boto3.resource("dynamodb").Table(os.environ.get("BATCHES_TABLE_NAME", "TalkingBotCallBatches-dev"))


def _patients_table():
    return boto3.resource("dynamodb").Table(os.environ.get("PATIENTS_TABLE_NAME", "TalkingBotPatientRecords-dev"))


def _campaign(batches_table, campaign_id: str) -> dict | None:
    if not hasattr(batches_table, "get_item"):
        return None
    try:
        return batches_table.get_item(Key={"batchId": campaign_id}).get("Item")
    except Exception:
        return None


def _query_patients(patients_table, campaign_id: str, status: str | None = None) -> list[dict]:
    items: list[dict] = []
    kwargs = {
        "FilterExpression": Attr("batchId").eq(campaign_id),
    }
    if status:
        kwargs["FilterExpression"] = kwargs["FilterExpression"] & Attr("status").eq(status)
    try:
        while True:
            response = patients_table.scan(**kwargs)
            items.extend(response.get("Items", []))
            last = response.get("LastEvaluatedKey")
            if not last:
                break
            kwargs["ExclusiveStartKey"] = last
        print(f"[DEBUG] _query_patients campaign={campaign_id} status={status} returned {len(items)} items")
        return items
    except ClientError as e:
        print(f"[ERROR] _query_patients failed: {e}")
        return []


def _set_campaign_running(batches_table, campaign_id: str) -> bool:
    now = _now()
    try:
        batches_table.update_item(
            Key={"batchId": campaign_id},
            UpdateExpression="SET #s=:running, startedAt=if_not_exists(startedAt,:now), updatedAt=:now",
            ConditionExpression="#s IN (:pending,:running)",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":running": CAMPAIGN_RUNNING, ":pending": CAMPAIGN_PENDING, ":now": now},
        )
        return True
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            print(f"[campaign_dialer] campaign={campaign_id} is not runnable; start/continue ignored")
            return False
        raise


def _claim_patient(patients_table, patient: dict) -> bool:
    try:
        patients_table.update_item(
            Key={"patientId": patient["patientId"], "batchId": patient["batchId"]},
            UpdateExpression="SET #s=:inprogress, attemptCount=if_not_exists(attemptCount,:zero)+:one, updatedAt=:now",
            ConditionExpression="#s=:pending",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":pending": PATIENT_PENDING,
                ":inprogress": PATIENT_IN_PROGRESS,
                ":zero": 0,
                ":one": 1,
                ":now": _now(),
            },
        )
        return True
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise


def _claim_callback_patient(patients_table, patient: dict) -> bool:
    try:
        patients_table.update_item(
            Key={"patientId": patient["patientId"], "batchId": patient["batchId"]},
            UpdateExpression=(
                "SET #s=:inprogress, attemptCount=if_not_exists(attemptCount,:zero)+:one, "
                "callbackStartedAt=:now, updatedAt=:now"
            ),
            ConditionExpression="#s=:scheduled",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":scheduled": PATIENT_CALLBACK_SCHEDULED,
                ":inprogress": PATIENT_IN_PROGRESS,
                ":zero": 0,
                ":one": 1,
                ":now": _now(),
            },
        )
        return True
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise


def _check_agent_availability(patient_id: str = "", empi: str = "") -> dict:
    url = os.environ.get("AGENT_AVAILABILITY_URL", "")
    if not url:
        print("AGENT_AVAILABILITY_URL not set — treating as unavailable")
        return {"available": False, "agentPhone": None, "checkedAt": None}
    try:
        import urllib.request
        import urllib.parse
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
            return json.loads(resp.read())
    except Exception as e:
        print(f"[WARN] Agent availability check failed: {e} — failing safe as unavailable")
        return {"available": False, "agentPhone": None, "checkedAt": None}


def _mark_agent_unavailable(patients_table, patient: dict, checked_at: str | None = None) -> None:
    now = _now()
    patients_table.update_item(
        Key={"patientId": patient["patientId"], "batchId": patient["batchId"]},
        UpdateExpression="SET #s=:unavail, disposition=:disp, agentCheckedAt=:checkedAt, completedAt=:now, updatedAt=:now",
        ConditionExpression="#s=:inprogress",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":inprogress": PATIENT_IN_PROGRESS,
            ":unavail": PATIENT_AGENT_UNAVAILABLE,
            ":disp": "AGENT_UNAVAILABLE",
            ":checkedAt": checked_at or now,
            ":now": now,
        },
    )


def _place_call(patients_table, connect, patient: dict, campaign_id: str, campaign: dict | None = None) -> str | None:
    customer_name = patient.get("customerName") or f"{patient.get('firstName', '')} {patient.get('lastName', '')}".strip()
    direct_agent = str(patient.get("direct_agent") or "no").strip().lower()
    call_mode = (patient.get("callMode") or "NORMAL").strip().upper()
    empi = str(patient.get("empi") or "")
    patient_id = str(patient.get("patientId") or empi)

    agent_phone = None
    agent_checked_at = None

    # Direct agent routing
    if direct_agent == "yes" or call_mode == "DIRECT_HUMAN_HANDOFF":
        # DISABLED FOR CLIENT TESTING — see 2026-09-01 campaign-level direct_agent migration
        # Pre-call mock availability check is disabled during client testing; the configured
        # humanAgentPhoneNumber is used directly for transfer without a pre-call check.
        #
        # availability = _check_agent_availability(patient_id=patient_id, empi=empi)
        # agent_available = availability.get("available", False)
        # if not agent_available:
        #     agent_available = check_agent_availability({"patientId": patient_id, "empi": empi})
        # if agent_available:
        #     call_mode = "DIRECT_HUMAN_HANDOFF"
        #     agent_phone = availability.get("agentPhone") or os.environ.get("FIXED_HUMAN_AGENT_PHONE_NUMBER", os.environ.get("FIXED_AGENT_PHONE", "+15822671755"))
        #     agent_checked_at = availability.get("checkedAt") or _now()
        # else:
        #     # Fail-safe: agent unavailable -> Normal Cara Flow
        #     call_mode = "NORMAL"

        call_mode = "DIRECT_HUMAN_HANDOFF"
        agent_checked_at = _now()

    # Always resolve the campaign-level human agent phone number
    agent_phone = str(
        patient.get("humanAgentPhoneNumber")
        or (campaign or {}).get("humanAgentPhoneNumber")
        or os.environ.get("FIXED_HUMAN_AGENT_PHONE_NUMBER", "+15822671755")
    )

    first_name = str(patient.get("firstName") or "")
    practice_name = str(patient.get("practiceName") or "")

    # Set opening greeting for Normal Cara Flow (permission asking)
    display_name = first_name or customer_name or "there"
    coaching_greeting = (
        f"Thanks, {display_name}. I'm Cara, an automated assistant. "
        f"I can connect you with a human specialist who can help. Is now a good time?"
    )

    if call_mode == "DIRECT_HUMAN_HANDOFF":
        attributes = {
            "customerName": customer_name,
            "expectedPhone": patient["phoneNumber"],
            "humanAgentPhoneNumber": agent_phone or "+15822671755",
            "agentAvailabilityCheckedAt": agent_checked_at or "",
            "callMode": "DIRECT_HUMAN_HANDOFF",
            "direct_agent": direct_agent,
            "firstName": first_name,
            "practiceName": practice_name,
        }
    else:
        attributes = {
            "campaignId": campaign_id,
            "patientId": patient["patientId"],
            "customerName": customer_name,
            "expectedPhone": patient["phoneNumber"],
            "humanAgentPhoneNumber": agent_phone or "+15822671755",
            "empi": str(patient.get("empi") or patient["patientId"]),
            "firstName": first_name,
            "lastName": str(patient.get("lastName") or ""),
            "gender": str(patient.get("gender") or ""),
            "practiceName": practice_name,
            "practiceCallbackNumber": str(patient.get("practiceCallbackNumber") or ""),
            "identityPolicyVersion": "v6-cara-conversational",
            "identityPrompt": f"Hi, may I speak with {customer_name}?",
            "identityClarification": f"I'm Cara, an automated assistant, and I'm trying to reach {customer_name}. I can explain more once I confirm I'm speaking with the right person. Are you {customer_name}?",
            "identityFailureMessage": f"Thanks. I need to speak directly with {customer_name}, so I'll end the call here. Have a good day.",
            "thirdPartyAvailabilityPrompt": f"Thanks. I need to speak directly with {customer_name}. Is {customer_name} available to come to the phone?",
            "patientUnavailablePrompt": f"No problem. If you know a better day and time to reach {customer_name}, I can note it.",
            "thirdPartyAvailabilityClarification": f"Just to clarify, is {customer_name} available to come to the phone now?",
            "representativeResponse": f"Thanks for letting me know. I can only continue directly with {customer_name}. Is {customer_name} available to come to the phone?",
            "wrongNumberResponse": "Thanks for letting me know. I apologize for the inconvenience. Have a good day.",
            "deceasedResponse": "I'm so sorry for your loss. Thank you for letting me know.",
            "refusalResponse": "Understood — thanks for your time today. Goodbye.",
            "passPhonePrompt": f"Thanks. Please pass the phone to {customer_name}.",
            "handoffIdentityPrompt": f"Hi. May I confirm I'm speaking with {customer_name}?",
            "coachingGreeting": coaching_greeting,
            "callMode": "NORMAL",
            "direct_agent": direct_agent,
        }

    connect_params = {
        "DestinationPhoneNumber": patient["phoneNumber"],
        "ContactFlowId": os.environ["CONNECT_CONTACT_FLOW_ID"],
        "InstanceId": os.environ["CONNECT_INSTANCE_ID"],
        "SourcePhoneNumber": os.environ["CONNECT_SOURCE_PHONE_NUMBER"],
        "ClientToken": str(uuid.uuid4()),
        "Name": "Cara Health Bot campaign call",
        "Description": "Automated patient outreach placed by Cara Health Bot campaign pipeline",
        "TrafficType": "GENERAL",
        "Attributes": attributes,
    }

    if os.environ.get("DRY_RUN", "").lower() in {"1", "true", "yes"}:
        print("  [DRY RUN] Would call start_outbound_voice_contact with params:")
        for k, v in connect_params.items():
            print(f"    {k}: {v}")
        return f"dry-run-contact-{uuid.uuid4()}"

    print(f"[DEBUG] start_outbound_voice_contact params: {json.dumps(connect_params, default=str)}")
    response = connect.start_outbound_voice_contact(**connect_params)
    contact_id = response["ContactId"]
    _save_contact_id(patients_table, patient, contact_id, call_mode=call_mode, campaign_id=campaign_id)
    return contact_id


def _save_contact_id(patients_table, patient: dict, contact_id: str, call_mode: str | None = None, campaign_id: str | None = None) -> None:
    if not patients_table:
        return
    batch_id = patient.get("batchId") or campaign_id
    if not batch_id or not patient.get("patientId"):
        return
    update_expr = "SET contactId=:contactId, updatedAt=:now"
    vals = {":inprogress": PATIENT_IN_PROGRESS, ":contactId": contact_id, ":now": _now()}
    if call_mode:
        update_expr += ", callMode=:callMode"
        vals[":callMode"] = call_mode
    patients_table.update_item(
        Key={"patientId": patient["patientId"], "batchId": batch_id},
        UpdateExpression=update_expr,
        ConditionExpression="#s=:inprogress",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues=vals,
    )


def _mark_setup_failed(patients_table, patient: dict, reason: str = "setup_error") -> None:
    now = _now()
    try:
        patients_table.update_item(
            Key={"patientId": patient["patientId"], "batchId": patient["batchId"]},
            UpdateExpression="SET #s=:failed, disposition=:disp, failureReason=:reason, completedAt=:now, updatedAt=:now",
            ConditionExpression="#s=:inprogress",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":inprogress": PATIENT_IN_PROGRESS,
                ":failed": PATIENT_FAILED,
                ":disp": "Call Setup Failed",
                ":reason": str(reason)[:500],
                ":now": now,
            },
        )
    except Exception as e:
        print(f"[ERROR] _mark_setup_failed: {e}")


def _async_continue(campaign_id: str) -> None:
    boto3.client("lambda").invoke(
        FunctionName=os.environ["AWS_LAMBDA_FUNCTION_NAME"],
        InvocationType="Event",
        Payload=json.dumps({"trigger": "campaign-continue", "campaignId": campaign_id}).encode("utf-8"),
    )


def _mark_campaign_completed_if_done(batches_table, patients_table, campaign_id: str) -> bool:
    active = _query_patients(patients_table, campaign_id)
    if any(item.get("status") in {PATIENT_PENDING, PATIENT_IN_PROGRESS, PATIENT_CALLBACK_SCHEDULED} for item in active):
        return False
    now = _now()
    try:
        batches_table.update_item(
            Key={"batchId": campaign_id},
            UpdateExpression="SET #s=:completed, completedAt=:now, updatedAt=:now",
            ConditionExpression="#s<>:completed",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":completed": CAMPAIGN_COMPLETED, ":now": now},
        )
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise
    print(f"[campaign_dialer] campaign={campaign_id} completed")
    return True


def _start_next_call(batches_table, patients_table, connect, campaign_id: str) -> None:
    if not _set_campaign_running(batches_table, campaign_id):
        return
    if _query_patients(patients_table, campaign_id, PATIENT_IN_PROGRESS):
        print(f"[campaign_dialer] campaign={campaign_id} already has an IN_PROGRESS patient; duplicate start ignored")
        return

    campaign = _campaign(batches_table, campaign_id)
    failures = 0
    while failures < MAX_SETUP_FAILURES_PER_INVOCATION:
        pending = _query_patients(patients_table, campaign_id, PATIENT_PENDING)
        if not pending:
            _mark_campaign_completed_if_done(batches_table, patients_table, campaign_id)
            return
        patient = pending[0]
        if not _claim_patient(patients_table, patient):
            print("[campaign_dialer] patient claim lost to another invocation")
            return
        try:
            contact_id = _place_call(
                patients_table=patients_table,
                connect=connect,
                patient=patient,
                campaign_id=campaign_id,
                campaign=campaign,
            )
            if contact_id:
                _save_contact_id(patients_table, patient, contact_id)
                print(f"[campaign_dialer] started campaign={campaign_id} patientId={patient['patientId']} contactId={contact_id}")
                return
            # If contact_id is None, agent was unavailable and patient was marked AGENT_UNAVAILABLE. Loop continues for next patient.
        except (ClientError, ValueError) as error:
            failures += 1
            code = error.response.get("Error", {}).get("Code", "ClientError") if isinstance(error, ClientError) else str(error)
            print(f"[campaign_dialer] call setup failed campaign={campaign_id} patientId={patient['patientId']} reason={code}")
            _mark_setup_failed(patients_table, patient, code)

    print(f"[campaign_dialer] campaign={campaign_id} hit bounded setup-failure limit; scheduling continuation")
    _async_continue(campaign_id)


def _extract_disconnect(event: dict) -> tuple[str, str] | None:
    if event.get("source") != "aws.connect":
        return None
    detail = event.get("detail") or {}
    if detail.get("eventType") != "DISCONNECTED":
        return None
    contact_id = detail.get("contactId")
    instance_arn = detail.get("instanceArn")
    if not contact_id or not instance_arn:
        return None
    expected = os.environ["CONNECT_INSTANCE_ID"]
    instance_id = instance_arn.rsplit("/", 1)[-1]
    if instance_id != expected:
        return None
    return contact_id, instance_id


def _lookup_by_contact(patients_table, contact_id: str) -> dict | None:
    try:
        response = patients_table.query(
            IndexName="contactId-index",
            KeyConditionExpression=Key("contactId").eq(contact_id),
            Limit=2,
        )
        items = response.get("Items", [])
        if len(items) == 1:
            return items[0]
    except ClientError:
        pass
    scan_kwargs = {
        "FilterExpression": Attr("contactId").eq(contact_id),
    }
    while True:
        response = patients_table.scan(**scan_kwargs)
        items = response.get("Items", [])
        if items:
            return items[0]
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        scan_kwargs["ExclusiveStartKey"] = last_key
    return None


def _disposition(identity_result: str | None) -> str:
    return DISPOSITIONS.get(identity_result, "Unknown / Undetermined")


def _classify_contact(contact: dict) -> tuple[str | None, str]:
    identity_result = (contact.get("Attributes") or {}).get("identityResult")
    if identity_result in {"Confirmed", "Denied", "Ambiguous", "Deceased"}:
        return identity_result, _disposition(identity_result)
    if contact.get("DisconnectReason") in NOT_CONNECTED_REASONS:
        return None, "No Answer / Not Connected"
    return None, _disposition(None)


def _normalize_timezone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(str(name or "UTC"))
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _parse_time(text: str) -> tuple[int, int] | None:
    value = (text or "").lower().strip()
    if not value:
        return None
    if re.search(r"\bnoon\b", value):
        return 12, 0
    if re.search(r"\bmidnight\b", value):
        return 0, 0
    match = re.search(r"\b(1[0-2]|0?[1-9])(?::([0-5]\d))?\s*(a\.?m\.?|p\.?m\.?)\b", value)
    if match:
        hour = int(match.group(1)) % 12
        minute = int(match.group(2) or 0)
        if match.group(3).startswith("p"):
            hour += 12
        return hour, minute

    # Amazon Q may verbalize tool arguments, for example:
    # "tomorrow at ten a.m." instead of "tomorrow at 10 AM".
    spoken_hours = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
        "eleven": 11,
        "twelve": 12,
    }

    hour_words = "|".join(spoken_hours)

    match = re.search(
        rf"\b({hour_words})\s*(a\.?m\.?|p\.?m\.?)\b",
        value,
    )
    if match:
        hour = spoken_hours[match.group(1)] % 12
        if match.group(2).startswith("p"):
            hour += 12
        return hour, 0

    # Also support "ten in the morning" / "two in the afternoon".
    match = re.search(
        rf"\b({hour_words})(?:\s+o'?clock)?\s+(?:in\s+the\s+)?"
        rf"(morning|afternoon|evening)\b",
        value,
    )
    if match:
        hour = spoken_hours[match.group(1)] % 12
        if match.group(2) in {"afternoon", "evening"}:
            hour += 12
        return hour, 0

    match = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", value)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None


_WEEKDAYS = {name.lower(): index for index, name in enumerate(
    ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
)}
_MONTHS = {
    name.lower(): index for index, name in enumerate(
        ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
        start=1,
    )
}
_MONTHS.update({name[:3]: value for name, value in list(_MONTHS.items())})


def _parse_date(text: str, today: dt.date) -> dt.date | None:
    value = (text or "").lower().strip()
    if not value:
        return None
    if "day after tomorrow" in value:
        return today + dt.timedelta(days=2)
    if re.search(r"\btomorrow\b", value):
        return today + dt.timedelta(days=1)
    if re.search(r"\btoday\b", value):
        return today

    match = re.search(r"\b(20\d{2})-(0[1-9]|1[0-2])-([0-2]\d|3[01])\b", value)
    if match:
        try:
            return dt.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None

    match = re.search(r"\b(0?[1-9]|1[0-2])/(0?[1-9]|[12]\d|3[01])(?:/(20\d{2}|\d{2}))?\b", value)
    if match:
        year = int(match.group(3)) if match.group(3) else today.year
        if year < 100:
            year += 2000
        try:
            candidate = dt.date(year, int(match.group(1)), int(match.group(2)))
            if not match.group(3) and candidate < today:
                candidate = candidate.replace(year=year + 1)
            return candidate
        except ValueError:
            return None

    month_pattern = "|".join(sorted((re.escape(x) for x in _MONTHS), key=len, reverse=True))
    match = re.search(rf"\b({month_pattern})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(20\d{{2}}))?\b", value)
    if match:
        month = _MONTHS[match.group(1)]
        year = int(match.group(3) or today.year)
        try:
            candidate = dt.date(year, month, int(match.group(2)))
            if not match.group(3) and candidate < today:
                candidate = candidate.replace(year=year + 1)
            return candidate
        except ValueError:
            return None

    match = re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({month_pattern})(?:\s+(20\d{{2}}))?\b", value)
    if match:
        month = _MONTHS[match.group(2)]
        year = int(match.group(3) or today.year)
        try:
            candidate = dt.date(year, month, int(match.group(1)))
            if not match.group(3) and candidate < today:
                candidate = candidate.replace(year=year + 1)
            return candidate
        except ValueError:
            return None

    for weekday, index in _WEEKDAYS.items():
        if re.search(rf"\b(?:next\s+)?{weekday}\b", value):
            delta = (index - today.weekday()) % 7
            if delta == 0 or re.search(rf"\bnext\s+{weekday}\b", value):
                delta = 7 if delta == 0 else delta
            return today + dt.timedelta(days=delta)
    return None


# Added because live test calls showed Cara acknowledging "call me back in 1
# hour" / "in 10 minutes" (her prompt already tells her to accept phrasing like
# this), but no callback ever actually happened -- this parser only understood
# clock times ("10 AM") and relative days ("tomorrow"), never durations. This
# fills that gap. Vague durations ("in a bit", "later today") still can't be
# scheduled precisely and fall through to the existing "time unspecified" path.
_DURATION_NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty-five": 45,
}




def _parse_relative_duration(text: str) -> dt.timedelta | None:
    value = (text or "").lower().strip()
    if not value or not re.search(r"\b(in|after)\b", value):
        return None
    if re.search(r"\bhalf\s+an?\s+hour\b", value):
        return dt.timedelta(minutes=30)


    number_pattern = r"(\d+|" + "|".join(_DURATION_NUMBER_WORDS) + r")"
    hours = 0
    minutes = 0
    hour_match = re.search(rf"\b{number_pattern}\s*hours?\b", value)
    if hour_match:
        token = hour_match.group(1)
        hours = int(token) if token.isdigit() else _DURATION_NUMBER_WORDS[token]
    minute_match = re.search(rf"\b{number_pattern}\s*min(?:ute)?s?\b", value)
    if minute_match:
        token = minute_match.group(1)
        minutes = int(token) if token.isdigit() else _DURATION_NUMBER_WORDS[token]
    if hours == 0 and minutes == 0:
        return None
    return dt.timedelta(hours=hours, minutes=minutes)

def _parse_callback_when(raw: str, timezone_name: str, now: dt.datetime | None = None) -> dt.datetime | None:
    """Parse the common exact callback forms Cara already accepts conversationally.

    This intentionally does not invent a time for phrases such as "tomorrow
    afternoon". If the caller does not provide an exact clock time, the request
    is persisted but not auto-scheduled.
    """
    zone = _normalize_timezone(timezone_name)
    current = (now or _now_dt()).astimezone(zone)
    duration = _parse_relative_duration(raw)
    if duration is not None:
        return current + duration

    time_value = _parse_time(raw)
    if not time_value:
        return None
    date_value = _parse_date(raw, current.date())
    if not date_value:
        candidate_today = dt.datetime.combine(current.date(), dt.time(*time_value), tzinfo=zone)
        date_value = current.date() if candidate_today > current + dt.timedelta(minutes=1) else current.date() + dt.timedelta(days=1)
    candidate = dt.datetime.combine(date_value, dt.time(*time_value), tzinfo=zone)
    if candidate <= current + dt.timedelta(minutes=1):
        return None
    return candidate


def _parse_lex_callback(callback_date: str, callback_time: str, timezone_name: str) -> dt.datetime | None:
    zone = _normalize_timezone(timezone_name)
    try:
        date_value = dt.date.fromisoformat(str(callback_date).strip())
    except ValueError:
        return None
    time_value = _parse_time(str(callback_time).strip())
    if not time_value:
        # AMAZON.Time commonly returns HH:MM; retain a strict fallback.
        match = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)(?::[0-5]\d)?", str(callback_time).strip())
        if not match:
            return None
        time_value = int(match.group(1)), int(match.group(2))
    candidate = dt.datetime.combine(date_value, dt.time(*time_value), tzinfo=zone)
    if candidate <= _now_dt().astimezone(zone) + dt.timedelta(minutes=1):
        return None
    return candidate


def _callback_schedule_name(campaign_id: str, record_key: str, callback_utc: dt.datetime) -> str:
    digest = hashlib.sha256(
        f"{campaign_id}|{record_key}|{callback_utc.isoformat()}".encode("utf-8")
    ).hexdigest()[:30]
    return f"cara-health-bot-callback-{digest}"


def _create_callback_schedule(campaign_id: str, record_key: str, callback_at: dt.datetime) -> tuple[str, str]:
    callback_utc = callback_at.astimezone(dt.timezone.utc).replace(microsecond=0)
    name = _callback_schedule_name(campaign_id, record_key, callback_utc)
    kwargs = {
        "GroupName": "default",
        "ScheduleExpression": f"at({callback_utc.strftime('%Y-%m-%dT%H:%M:%S')})",
        "ScheduleExpressionTimezone": "UTC",
        "FlexibleTimeWindow": {"Mode": "OFF"},
        "ActionAfterCompletion": "DELETE",
        "Target": {
            "Arn": os.environ["DIALER_LAMBDA_ARN"],
            "RoleArn": os.environ["SCHEDULER_ROLE_ARN"],
            "Input": json.dumps({
                "trigger": "patient-callback",
                "campaignId": campaign_id,
                "recordKey": record_key,
            }),
        },
    }
    scheduler = boto3.client("scheduler")
    try:
        scheduler.create_schedule(Name=name, **kwargs)
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") != "ConflictException":
            raise
        scheduler.update_schedule(Name=name, **kwargs)
    return name, callback_utc.isoformat().replace("+00:00", "Z")


def _delete_callback_schedule(name: str) -> None:
    try:
        boto3.client("scheduler").delete_schedule(Name=name, GroupName="default")
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
            raise


def _callback_plan(contact: dict, campaign: dict) -> dict | None:
    attrs = contact.get("Attributes") or {}
    if attrs.get("identityResult") == "Deceased":
        return None
    timezone_name = str(campaign.get("timezone") or "UTC")
    identity_confirmed = attrs.get("identityResult") == "Confirmed" or attrs.get("identityConfirmed") == "true"

    if identity_confirmed and attrs.get("conversationState") == "CALLBACK":
        raw = str(attrs.get("callbackWhen") or "").strip()
        return {
            "requestedBy": "PATIENT",
            "identityResult": "Confirmed",
            "disposition": "Callback Requested",
            "callbackWhen": raw,
            "callbackReason": str(attrs.get("callbackReason") or "").strip(),
            "callbackAt": _parse_callback_when(raw, timezone_name) if raw else None,
        }

    if attrs.get("recipientType") == "THIRD_PARTY" and attrs.get("targetAvailableNow") == "false":
        callback_date = str(attrs.get("callbackDate") or "").strip()
        callback_time = str(attrs.get("callbackTime") or "").strip()
        raw_when = str(attrs.get("callbackWhen") or "").strip()
        raw = raw_when or " ".join(x for x in (callback_date, callback_time) if x)
        if callback_date or callback_time or raw_when:
            parsed_dt = _parse_lex_callback(callback_date, callback_time, timezone_name) if (callback_date and callback_time) else None
            if not parsed_dt and raw:
                parsed_dt = _parse_callback_when(raw, timezone_name)
            return {
                "requestedBy": "THIRD_PARTY",
                "identityResult": attrs.get("identityResult") or "Denied",
                "disposition": "Third Party - Callback Requested",
                "callbackWhen": raw,
                "callbackReason": "Intended customer unavailable",
                "callbackAt": parsed_dt,
            }
    return None


def _extract_telephony_details(contact: dict) -> dict[str, str]:
    init_ts = contact.get("InitiationTimestamp")
    disc_ts = contact.get("DisconnectTimestamp")
    start_dt = (
        init_ts.isoformat().replace("+00:00", "Z")
        if isinstance(init_ts, dt.datetime)
        else str(init_ts or "")
    )
    end_dt = (
        disc_ts.isoformat().replace("+00:00", "Z")
        if isinstance(disc_ts, dt.datetime)
        else str(disc_ts or "")
    )
    sys_ep = contact.get("SystemEndpoint") or {}
    outbound_phone = str(sys_ep.get("Address") or os.environ.get("CONNECT_SOURCE_PHONE_NUMBER", ""))
    return {
        "callStartDateTime": start_dt,
        "callEndDateTime": end_dt,
        "outboundCallPhoneNumber": outbound_phone,
    }


def _persist_scheduled_callback(patients_table, patient: dict, plan: dict, schedule_name: str, callback_utc: str, contact: dict | None = None) -> bool:
    callback_at: dt.datetime = plan["callbackAt"]
    local_iso = callback_at.isoformat()
    now = _now()
    telephony = _extract_telephony_details(contact or {}) if contact else {}
    start_dt = telephony.get("callStartDateTime") or ""
    end_dt = telephony.get("callEndDateTime") or ""
    outbound_phone = telephony.get("outboundCallPhoneNumber") or os.environ.get("CONNECT_SOURCE_PHONE_NUMBER", "")

    new_attempt = {
        "callId": str(patient.get("contactId") or ""),
        "contactId": str(patient.get("contactId") or ""),
        "callStartDateTime": start_dt,
        "callEndDateTime": end_dt,
        "disposition": plan["disposition"],
        "identityResult": str(plan.get("identityResult") or "Missing"),
        "outboundCallPhoneNumber": outbound_phone,
        "completedAt": now,
    }

    try:
        patients_table.update_item(
            Key={"patientId": patient["patientId"], "batchId": patient["batchId"]},
            UpdateExpression=(
                "SET #s=:scheduled, identityResult=:identity, disposition=:disposition, "
                "callbackRequestedBy=:requestedBy, callbackWhen=:callbackWhen, callbackReason=:callbackReason, "
                "callbackAt=:callbackAt, callbackFor=:callbackFor, callbackScheduleName=:scheduleName, "
                "callbackCount=if_not_exists(callbackCount,:zero)+:one, callbackRequestedAt=:now, updatedAt=:now, "
                "callStartDateTime=:startDt, callEndDateTime=:endDt, outboundCallPhoneNumber=:outboundPhone, "
                "callAttempts=list_append(if_not_exists(callAttempts, :emptyList), :newAttempt) "
                "REMOVE completedAt"
            ),
            ConditionExpression="#s=:inprogress",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":inprogress": PATIENT_IN_PROGRESS,
                ":scheduled": PATIENT_CALLBACK_SCHEDULED,
                ":identity": str(plan.get("identityResult") or "Missing"),
                ":disposition": plan["disposition"],
                ":requestedBy": plan["requestedBy"],
                ":callbackWhen": str(plan.get("callbackWhen") or ""),
                ":callbackReason": str(plan.get("callbackReason") or ""),
                ":callbackAt": local_iso,
                ":callbackFor": callback_utc,
                ":scheduleName": schedule_name,
                ":zero": 0,
                ":one": 1,
                ":now": now,
                ":startDt": start_dt,
                ":endDt": end_dt,
                ":outboundPhone": outbound_phone,
                ":newAttempt": [new_attempt],
                ":emptyList": [],
            },
        )
        print(
            f"[campaign_dialer] callback scheduled batchId={patient['batchId']} "
            f"patientId={patient['patientId']} requestedBy={plan['requestedBy']} callbackFor={callback_utc}"
        )
        return True
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            _delete_callback_schedule(schedule_name)
            return False
        raise


def _schedule_callback(patients_table, patient: dict, plan: dict, contact: dict | None = None) -> bool:
    if int(patient.get("callbackCount") or 0) >= MAX_CALLBACKS_PER_PATIENT:
        print(f"[campaign_dialer] callback limit reached batchId={patient['batchId']} patientId={patient['patientId']}")
        return False
    schedule_name, callback_utc = _create_callback_schedule(
        patient["batchId"], patient.get("patientId", ""), plan["callbackAt"]
    )
    return _persist_scheduled_callback(patients_table, patient, plan, schedule_name, callback_utc, contact)


def _finalize_callback_without_schedule(patients_table, patient: dict, plan: dict, contact: dict | None = None) -> bool:
    now = _now()
    disposition = (
        "Callback Requested - Time Unspecified"
        if plan.get("requestedBy") == "PATIENT"
        else "Third Party - Callback Time Unclear"
    )
    telephony = _extract_telephony_details(contact or {}) if contact else {}
    start_dt = telephony.get("callStartDateTime") or ""
    end_dt = telephony.get("callEndDateTime") or ""
    outbound_phone = telephony.get("outboundCallPhoneNumber") or os.environ.get("CONNECT_SOURCE_PHONE_NUMBER", "")

    new_attempt = {
        "callId": str(patient.get("contactId") or ""),
        "contactId": str(patient.get("contactId") or ""),
        "callStartDateTime": start_dt,
        "callEndDateTime": end_dt,
        "disposition": disposition,
        "identityResult": str(plan.get("identityResult") or "Missing"),
        "outboundCallPhoneNumber": outbound_phone,
        "completedAt": now,
    }

    try:
        patients_table.update_item(
            Key={"patientId": patient["patientId"], "batchId": patient["batchId"]},
            UpdateExpression=(
                "SET #s=:status, identityResult=:identity, disposition=:disposition, "
                "callbackRequestedBy=:requestedBy, callbackWhen=:callbackWhen, callbackReason=:callbackReason, "
                "completedAt=:now, updatedAt=:now, "
                "callStartDateTime=:startDt, callEndDateTime=:endDt, outboundCallPhoneNumber=:outboundPhone, "
                "callAttempts=list_append(if_not_exists(callAttempts, :emptyList), :newAttempt)"
            ),
            ConditionExpression="#s=:inprogress",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":inprogress": PATIENT_IN_PROGRESS,
                ":status": PATIENT_CALLBACK_UNSPECIFIED,
                ":identity": str(plan.get("identityResult") or "Missing"),
                ":disposition": disposition,
                ":requestedBy": plan.get("requestedBy") or "UNKNOWN",
                ":callbackWhen": str(plan.get("callbackWhen") or ""),
                ":callbackReason": str(plan.get("callbackReason") or ""),
                ":now": now,
                ":startDt": start_dt,
                ":endDt": end_dt,
                ":outboundPhone": outbound_phone,
                ":newAttempt": [new_attempt],
                ":emptyList": [],
            },
        )
        print(
            f"[campaign_dialer] callback request persisted without schedule batchId={patient['batchId']} "
            f"patientId={patient['patientId']} disposition={disposition} status={PATIENT_CALLBACK_UNSPECIFIED}"
        )
        return True
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise


def _finalize_patient(patients_table, patient: dict, contact: dict) -> bool:
    identity_result, disposition = _classify_contact(contact)
    now = _now()
    telephony = _extract_telephony_details(contact)
    start_dt = telephony["callStartDateTime"]
    end_dt = telephony["callEndDateTime"]
    outbound_phone = telephony["outboundCallPhoneNumber"]

    new_attempt = {
        "callId": str(patient.get("contactId") or ""),
        "contactId": str(patient.get("contactId") or ""),
        "callStartDateTime": start_dt,
        "callEndDateTime": end_dt,
        "disposition": disposition,
        "identityResult": identity_result or "Missing",
        "outboundCallPhoneNumber": outbound_phone,
        "completedAt": now,
    }

    # Check if patient declined / refused
    attrs = contact.get("Attributes") or {}
    refusal_dispositions = {"Call Refused", "Identity Denied - Refusal", "Refusal"}
    cara_end_reason = str(attrs.get("caraEndReason") or contact.get("caraEndReason") or "").lower()
    conversation_state = str(attrs.get("conversationState") or contact.get("conversationState") or "").upper()

    is_not_interested = (
        cara_end_reason in {"refusal", "do_not_call", "not_interested"}
        or conversation_state == "NOT_INTERESTED"
        or disposition in refusal_dispositions
        or identity_result == "Denied"
    )

    if is_not_interested:
        try:
            patients_table.update_item(
                Key={"patientId": patient["patientId"], "batchId": patient["batchId"]},
                UpdateExpression=(
                    "SET #s=:status, disposition=:disposition, identityResult=:identity, completedAt=:completedAt, updatedAt=:updatedAt, "
                    "callStartDateTime=:startDt, callEndDateTime=:endDt, outboundCallPhoneNumber=:outboundPhone, "
                    "callAttempts=list_append(if_not_exists(callAttempts, :emptyList), :newAttempt)"
                ),
                ConditionExpression="#s=:inprogress",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":status": PATIENT_NOT_INTERESTED,
                    ":inprogress": PATIENT_IN_PROGRESS,
                    ":identity": identity_result or "Denied",
                    ":disposition": disposition if disposition != "Unknown / Undetermined" else "Refusal",
                    ":completedAt": now,
                    ":updatedAt": now,
                    ":startDt": start_dt,
                    ":endDt": end_dt,
                    ":outboundPhone": outbound_phone,
                    ":newAttempt": [new_attempt],
                    ":emptyList": [],
                },
            )
            print(f"[campaign_dialer] finalized NOT_INTERESTED batchId={patient['batchId']} patientId={patient['patientId']}")
            return True
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return False
            raise

    values = {
        ":inprogress": PATIENT_IN_PROGRESS,
        ":completed": PATIENT_COMPLETED,
        ":identity": identity_result or "Missing",
        ":disposition": disposition,
        ":completedAt": now,
        ":updatedAt": now,
        ":startDt": start_dt,
        ":endDt": end_dt,
        ":outboundPhone": outbound_phone,
        ":newAttempt": [new_attempt],
        ":emptyList": [],
    }
    try:
        patients_table.update_item(
            Key={"patientId": patient["patientId"], "batchId": patient["batchId"]},
            UpdateExpression=(
                "SET #s=:completed, identityResult=:identity, disposition=:disposition, completedAt=:completedAt, updatedAt=:updatedAt, "
                "callStartDateTime=:startDt, callEndDateTime=:endDt, outboundCallPhoneNumber=:outboundPhone, "
                "callAttempts=list_append(if_not_exists(callAttempts, :emptyList), :newAttempt)"
            ),
            ConditionExpression="#s=:inprogress",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues=values,
        )
        print(f"[campaign_dialer] finalized batchId={patient['batchId']} patientId={patient['patientId']} identityResult={values[':identity']} disposition={disposition}")
        return True
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            print(f"[campaign_dialer] duplicate DISCONNECTED for contactId={patient.get('contactId')} ignored")
            return False
        raise


def _handle_disconnect(batches_table, patients_table, connect, contact_id: str, instance_id: str) -> None:
    patient = _lookup_by_contact(patients_table, contact_id)
    if not patient:
        print(f"[campaign_dialer] unrelated/unknown contactId={contact_id} ignored")
        return
    if patient.get("status") != PATIENT_IN_PROGRESS:
        print(f"[campaign_dialer] already-finalized contactId={contact_id} ignored")
        return
    contact = connect.describe_contact(InstanceId=instance_id, ContactId=contact_id).get("Contact", {})
    campaign = _campaign(batches_table, patient["batchId"]) or {}
    plan = _callback_plan(contact, campaign)
    if plan:
        callback_at = plan.get("callbackAt")
        handled = _schedule_callback(patients_table, patient, plan, contact) if callback_at else _finalize_callback_without_schedule(patients_table, patient, plan, contact)
        if handled:
            _start_next_call(batches_table, patients_table, connect, patient["batchId"])
            return
    if not _finalize_patient(patients_table, patient, contact):
        return
    _start_next_call(batches_table, patients_table, connect, patient["batchId"])


def _defer_callback(patients_table, patient: dict) -> None:
    deferred_at = _now_dt() + dt.timedelta(seconds=CALLBACK_DEFER_SECONDS)
    schedule_name, callback_utc = _create_callback_schedule(patient["batchId"], patient.get("patientId", ""), deferred_at)
    try:
        patients_table.update_item(
            Key={"patientId": patient["patientId"], "batchId": patient["batchId"]},
            UpdateExpression="SET callbackFor=:callbackFor, callbackScheduleName=:scheduleName, updatedAt=:now",
            ConditionExpression="#s=:scheduled",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":scheduled": PATIENT_CALLBACK_SCHEDULED,
                ":callbackFor": callback_utc,
                ":scheduleName": schedule_name,
                ":now": _now(),
            },
        )
        print(f"[campaign_dialer] callback deferred batchId={patient['batchId']} patientId={patient['patientId']} callbackFor={callback_utc}")
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            _delete_callback_schedule(schedule_name)
            return
        raise


def _start_callback_call(batches_table, patients_table, connect, campaign_id: str, record_key: str) -> None:
    campaign = _campaign(batches_table, campaign_id)
    if not campaign or campaign.get("status") not in {CAMPAIGN_PENDING, CAMPAIGN_RUNNING}:
        print(f"[campaign_dialer] callback campaign={campaign_id} is not runnable")
        return
    # Supports both patientId and old record_key
    patient_id = record_key if "#" in record_key and not record_key.startswith("PATIENT#") else f"{campaign_id}#{record_key}"
    patient = patients_table.get_item(Key={"patientId": patient_id, "batchId": campaign_id}).get("Item")
    if not patient:
        patient = patients_table.get_item(Key={"patientId": record_key, "batchId": campaign_id}).get("Item")
    if not patient or patient.get("status") != PATIENT_CALLBACK_SCHEDULED:
        print(f"[campaign_dialer] callback patient no longer scheduled campaign={campaign_id} patientId={patient_id}")
        return
    if _query_patients(patients_table, campaign_id, PATIENT_IN_PROGRESS):
        _defer_callback(patients_table, patient)
        return
    if not _set_campaign_running(batches_table, campaign_id):
        return
    if not _claim_callback_patient(patients_table, patient):
        return
    try:
        contact_id = _place_call(
            patients_table=patients_table,
            connect=connect,
            patient=patient,
            campaign_id=campaign_id,
            campaign=campaign,
        )
        if contact_id:
            _save_contact_id(patients_table, patient, contact_id)
            print(
                f"[campaign_dialer] callback started campaign={campaign_id} "
                f"patientId={patient['patientId']} contactId={contact_id}"
            )
    except (ClientError, ValueError) as error:
        code = error.response.get("Error", {}).get("Code", "ClientError") if isinstance(error, ClientError) else str(error)
        print(f"[campaign_dialer] callback call setup failed campaign={campaign_id} patientId={patient['patientId']} reason={code}")
        _mark_setup_failed(patients_table, patient, code)
        _start_next_call(batches_table, patients_table, connect, campaign_id)


def handler(event: dict, context) -> dict:
    try:
        batches_table = _batches_table()
        patients_table = _patients_table()
        connect = boto3.client("connect")
        trigger = event.get("trigger")
        if trigger in {"campaign-start", "campaign-continue"}:
            campaign_id = event.get("campaignId")
            if not campaign_id:
                raise ValueError("campaign event missing campaignId")
            _start_next_call(batches_table, patients_table, connect, campaign_id)
            return {"handled": trigger, "campaignId": campaign_id}

        if trigger == "patient-callback":
            campaign_id = event.get("campaignId")
            record_key = event.get("recordKey") or event.get("patientId")
            if not campaign_id or not record_key:
                raise ValueError("patient callback event missing campaignId or recordKey")
            _start_callback_call(batches_table, patients_table, connect, campaign_id, record_key)
            return {"handled": trigger, "campaignId": campaign_id, "recordKey": record_key}

        disconnected = _extract_disconnect(event)
        if disconnected:
            contact_id, instance_id = disconnected
            _handle_disconnect(batches_table, patients_table, connect, contact_id, instance_id)
            return {"handled": "DISCONNECTED", "contactId": contact_id}

        print("[campaign_dialer] ignored unrelated event")
        return {"handled": "ignored"}
    except Exception as error:
        print(f"[campaign_dialer] FAILED: {type(error).__name__}: {error}")
        raise
