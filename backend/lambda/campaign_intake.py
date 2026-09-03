"""Cara Health Bot campaign intake Lambda.

Triggered by campaigns/<campaignId>/patients.csv. The API writes config.json first,
then returns a presigned PUT URL for patients.csv. Intake validates the server-side
CSV, persists ordered patient state, transitions the campaign to PENDING, and creates
one EventBridge Scheduler entry for the campaign start.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import os
import re
from urllib.parse import unquote_plus
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import boto3
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

from cara_health_bot.phone_utils import normalize_phone_e164, validate_destination_prefix

STATUS_CAMPAIGN_UPLOAD_PENDING = "UPLOAD_PENDING"
STATUS_CAMPAIGN_PENDING = "PENDING"
STATUS_CAMPAIGN_VALIDATION_FAILED = "VALIDATION_FAILED"
STATUS_PATIENT_PENDING = "PENDING"
CAMPAIGN_RECORD_KEY = "CAMPAIGN"
REQUIRED_FRONTEND_FIELDS = [
    "empi", "first_name", "last_name", "gender", "phone_number",
    "practice_name", "practice_callback_number",
]


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _campaign_id_from_key(key: str) -> str:
    parts = key.split("/")
    if len(parts) != 3 or parts[0] != "campaigns" or parts[2] != "patients.csv":
        raise ValueError("expected S3 key campaigns/<campaignId>/patients.csv")
    campaign_id = parts[1].strip()
    if not campaign_id or not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", campaign_id):
        raise ValueError("invalid campaignId in S3 path")
    return campaign_id


def _clean_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").replace("\ufeff", "").strip().lower())


def _field_map(fieldnames: list[str]) -> dict[str, str]:
    available = {_clean_key(name): name for name in fieldnames}
    mapping: dict[str, str] = {}
    for required in REQUIRED_FRONTEND_FIELDS:
        match = available.get(_clean_key(required))
        if not match:
            raise ValueError(f"patients.csv missing required column: {required}")
        mapping[required] = match
    return mapping


def _normalize_phone_e164(raw: str) -> str:
    value = (raw or "").strip()
    if re.fullmatch(r"\+[1-9]\d{7,14}", value):
        return value
    digits = re.sub(r"\D", "", value)
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    raise ValueError("phone_number must be E.164 or a 10/11 digit US number")


def _normalize_callback(raw: str) -> str:
    return _normalize_phone_e164(raw)


def _resolve_call_time(config: dict) -> tuple[str, str]:
    call_time = (config.get("callTime") or "").strip()
    if call_time:
        parsed = dt.datetime.fromisoformat(call_time.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("callTime must include a timezone offset")
        utc = parsed.astimezone(dt.timezone.utc)
        return config.get("scheduledAt") or utc.isoformat(), utc.isoformat().replace("+00:00", "Z")
    raw = (config.get("scheduledAt") or "").strip()
    tz_name = (config.get("timezone") or "").strip()
    if not raw or not tz_name:
        raise ValueError("config.json requires callTime or scheduledAt+timezone")
    try:
        zone = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("invalid IANA timezone") from exc
    parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    local = parsed.replace(tzinfo=zone) if parsed.tzinfo is None else parsed.astimezone(zone)
    return local.isoformat(), local.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _schedule_expression_utc(call_time: str) -> str:
    parsed = dt.datetime.fromisoformat(call_time.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("callTime must include a timezone offset")
    utc = parsed.astimezone(dt.timezone.utc)
    return f"at({utc.strftime('%Y-%m-%dT%H:%M:%S')})"


def _load_config(s3, bucket: str, campaign_id: str) -> dict:
    response = s3.get_object(Bucket=bucket, Key=f"campaigns/{campaign_id}/config.json")
    data = json.loads(response["Body"].read())
    if not isinstance(data, dict):
        raise ValueError("config.json must contain a JSON object")
    if data.get("campaignId") and data["campaignId"] != campaign_id:
        raise ValueError("config.json campaignId does not match S3 path")
    return data


FIXED_HUMAN_AGENT_PHONE_NUMBER = "+15822671755"


def _load_patients(s3, bucket: str, campaign_id: str, config: dict | None = None) -> list[dict]:
    response = s3.get_object(Bucket=bucket, Key=f"campaigns/{campaign_id}/patients.csv")
    text = response["Body"].read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    fields = reader.fieldnames or []
    mapping = _field_map(fields)

    # Campaign-level Direct Agent configuration (Client Testing)
    cfg = config or {}
    direct_agent_enabled = bool(
        cfg.get("directAgentEnabled") in {True, "true", "True", 1}
        or str(cfg.get("direct_agent") or "").strip().lower() == "yes"
    )
    campaign_agent_phone = str(
        cfg.get("humanAgentPhoneNumber")
        or os.environ.get("FIXED_HUMAN_AGENT_PHONE_NUMBER", FIXED_HUMAN_AGENT_PHONE_NUMBER)
    ).strip()

    # Check for legacy 'direct agent' column header in CSV if present (ignored for client testing)
    direct_agent_header = None
    for field in fields:
        clean = _clean_key(field)
        if clean == "directagent":
            direct_agent_header = field
            print(f"[campaign_intake] [INFO] CSV contains '{field}' column; ignoring per-row direct_agent in favor of campaign-level setting (directAgentEnabled={direct_agent_enabled})")
            break

    rows: list[dict] = []
    seen_empi: set[str] = set()
    seen_phone: set[str] = set()
    for line, row in enumerate(reader, start=2):
        get = lambda key: str(row.get(mapping[key]) or "").strip()
        empi = get("empi")
        first = get("first_name")
        last = get("last_name")
        gender = get("gender")
        practice = get("practice_name")
        if not practice:
            raise ValueError(f"row {line}: practice_name is required and must be non-empty")
        seen_empi.add(empi)
        phone = _normalize_phone_e164(get("phone_number"))
        seen_phone.add(phone)
        callback = _normalize_callback(get("practice_callback_number"))

        # DISABLED FOR CLIENT TESTING — see 2026-09-01 campaign-level direct_agent migration
        # raw_direct = str(row.get(direct_agent_header) or "").strip().lower() if direct_agent_header else ""

        patient_dict = {
            "patientId": empi,
            "empi": empi,
            "firstName": first,
            "lastName": last,
            "customerName": f"{first} {last}".strip(),
            "gender": gender,
            "phoneNumber": phone,
            "practiceName": practice,
            "practiceCallbackNumber": callback,
        }

        # Apply campaign-level Direct Agent configuration
        patient_dict["humanAgentPhoneNumber"] = campaign_agent_phone
        if direct_agent_enabled:
            patient_dict["direct_agent"] = "yes"
            patient_dict["callMode"] = "DIRECT_HUMAN_HANDOFF"
        else:
            patient_dict["direct_agent"] = "no"
            patient_dict["callMode"] = "NORMAL"

        # DISABLED FOR CLIENT TESTING — see 2026-09-01
        # if raw_direct == "yes":
        #     patient_dict["direct_agent"] = "yes"
        #     patient_dict["callMode"] = "DIRECT_HUMAN_HANDOFF"
        #     patient_dict["humanAgentPhoneNumber"] = fixed_agent_phone
        # elif raw_direct in {"no", ""} or direct_agent_header is None:
        #     patient_dict["direct_agent"] = "no"
        #     patient_dict["callMode"] = "NORMAL"
        # else:
        #     raise ValueError(f"row {line}: invalid direct agent value '{row.get(direct_agent_header)}'. Expected 'yes' or 'no'")

        rows.append(patient_dict)
    if not rows:
        raise ValueError("patients.csv has no data rows")
    return rows


def _batches_table():
    return boto3.resource("dynamodb").Table(os.environ.get("BATCHES_TABLE_NAME", "TalkingBotCallBatches-dev"))


def _patients_table():
    return boto3.resource("dynamodb").Table(os.environ.get("PATIENTS_TABLE_NAME", "TalkingBotPatientRecords-dev"))


def _set_validation_failed(batches_table, campaign_id: str, reason: str) -> None:
    try:
        batches_table.update_item(
            Key={"batchId": campaign_id},
            UpdateExpression="SET #s=:failed, failureReason=:reason, updatedAt=:now",
            ConditionExpression="#s <> :cancelled",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":failed": STATUS_CAMPAIGN_VALIDATION_FAILED, ":cancelled": "CANCELLED",
                ":reason": reason[:500], ":now": _now(),
            },
        )
    except Exception:
        pass


def _write_state(batches_table, patients_table, campaign_id: str, patients: list[dict], local_time: str, call_time: str, config: dict) -> None:
    now = _now()

    existing = batches_table.get_item(Key={"batchId": campaign_id}).get("Item")
    if existing and existing.get("status") not in {STATUS_CAMPAIGN_UPLOAD_PENDING, STATUS_CAMPAIGN_PENDING}:
        raise ValueError(f"campaign {campaign_id} already exists with status {existing.get('status')}")
    
    update_expr = (
        "SET #s=:pending, totalRows=:count, validRows=:count, invalidRows=:zero, patientCount=:count, customerCount=:count, scheduledAt=:local, "
        "scheduledFor=:utc, #tz=:tz, updatedAt=:now REMOVE failureReason"
    )
    expr_vals = {
        ":pending": STATUS_CAMPAIGN_PENDING, ":count": len(patients), ":zero": 0, ":local": local_time,
        ":utc": call_time, ":tz": str(config.get("timezone") or "UTC"), ":now": now,
    }

    if existing:
        batches_table.update_item(
            Key={"batchId": campaign_id},
            UpdateExpression=update_expr,
            ExpressionAttributeNames={"#s": "status", "#tz": "timezone"},
            ExpressionAttributeValues=expr_vals,
        )
    else:
        item = {
            "batchId": campaign_id, "campaignId": campaign_id,
            "status": STATUS_CAMPAIGN_PENDING, "totalRows": len(patients), "validRows": len(patients), "invalidRows": 0,
            "patientCount": len(patients), "customerCount": len(patients),
            "createdAt": now, "uploadedAt": now, "scheduledAt": local_time, "scheduledFor": call_time,
            "timezone": str(config.get("timezone") or "UTC"), "updatedAt": now,
            "fileName": config.get("fileName", "patients.csv"), "fileSize": int(config.get("fileSize") or 0),
            "s3Bucket": config.get("s3Bucket", ""), "s3Key": f"campaigns/{campaign_id}/patients.csv",
            **({"originalRecordId": config["originalRecordId"]} if config.get("originalRecordId") else {}),
        }
        batches_table.put_item(Item=item)

    for sequence, patient in enumerate(patients, start=1):
        patient_id = f"{campaign_id}#row-{sequence}"
        item = {
            "patientId": patient_id,
            "batchId": campaign_id,
            "rowNumber": sequence,
            "status": STATUS_PATIENT_PENDING,
            "callSlotStart": call_time,
            "attemptCount": 0,
            "createdAt": now,
            "updatedAt": now,
            **patient,
        }
        item["patientId"] = patient_id
        try:
            patients_table.put_item(Item=item, ConditionExpression=Attr("patientId").not_exists())
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
        print(f"[campaign_intake] patient row={sequence} patientId={patient_id} status=PENDING callMode={patient.get('callMode')}")


def _create_schedule(scheduler, campaign_id: str, schedule_expression: str) -> None:
    name = f"cara-health-bot-campaign-{campaign_id}"[:64]
    kwargs = {
        "GroupName": "default",
        "ScheduleExpression": schedule_expression,
        "ScheduleExpressionTimezone": "UTC",
        "FlexibleTimeWindow": {"Mode": "OFF"},
        "ActionAfterCompletion": "DELETE",
        "Target": {
            "Arn": os.environ["DIALER_LAMBDA_ARN"], "RoleArn": os.environ["SCHEDULER_ROLE_ARN"],
            "Input": json.dumps({"trigger": "campaign-start", "campaignId": campaign_id}),
        },
    }
    try:
        scheduler.create_schedule(Name=name, **kwargs)
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") != "ConflictException":
            raise
        scheduler.update_schedule(Name=name, **kwargs)


def handler(event: dict, context) -> dict:
    records = event.get("Records") or []
    if len(records) != 1:
        raise ValueError("campaign intake expects exactly one S3 object event")
    record = records[0]
    bucket = record["s3"]["bucket"]["name"]
    key = unquote_plus(record["s3"]["object"]["key"])
    campaign_id = _campaign_id_from_key(key)
    batches_table = _batches_table()
    patients_table = _patients_table()
    try:
        print(f"[campaign_intake] processing campaign={campaign_id}")
        s3 = boto3.client("s3")
        config = _load_config(s3, bucket, campaign_id)
        config["s3Bucket"] = bucket
        local_time, call_time = _resolve_call_time(config)
        patients = _load_patients(s3, bucket, campaign_id, config)
        _write_state(batches_table, patients_table, campaign_id, patients, local_time, call_time, config)
        schedule_expression = _schedule_expression_utc(call_time)
        _create_schedule(boto3.client("scheduler"), campaign_id, schedule_expression)
        return {"campaignId": campaign_id, "patientCount": len(patients), "scheduleExpression": schedule_expression}
    except Exception as error:
        _set_validation_failed(batches_table, campaign_id, str(error))
        print(f"[campaign_intake] FAILED campaign={campaign_id}: {type(error).__name__}: {error}")
        raise
