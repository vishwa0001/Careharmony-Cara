"""HTTP API Lambda for Cara Health Bot campaign management.

Transport/auth is deliberately separated from business logic. The campaign deployer
can expose this through an AWS_IAM-protected Lambda Function URL, while production
frontends can place API Gateway/Cognito or another authenticated edge in front.
"""
from __future__ import annotations

import base64
import csv
import datetime as dt
import io
import json
import os
import re
import uuid
from collections import Counter
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from cara_health_bot.phone_utils import normalize_phone_e164, validate_destination_prefix

CAMPAIGN_KEY = "CAMPAIGN"
ACTIVE_CANCEL_STATUSES = {"UPLOAD_PENDING", "PENDING"}
RESCHEDULABLE_STATUSES = {"CANCELLED"}
MAX_LIST_LIMIT = 100



def _json_default(value: Any):
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def _resolve_origin(event: dict | None = None) -> str:
    if isinstance(event, dict):
        headers = event.get("headers") or {}
        req_origin = headers.get("origin") or headers.get("Origin")
        if req_origin:
            return req_origin
    return os.environ.get("API_ALLOWED_ORIGIN", "*")


def _response(status: int, body: Any, event: dict | None = None) -> dict[str, Any]:
    origin = _resolve_origin(event)
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Headers": "content-type,authorization,accept",
            "Access-Control-Allow-Methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
            "Vary": "Origin",
        },
        "body": json.dumps(body, default=_json_default),
    }


def _csv_response(status: int, csv_body: str, filename: str, event: dict | None = None) -> dict[str, Any]:
    origin = _resolve_origin(event)
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "text/csv; charset=utf-8",
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Headers": "content-type,authorization,accept",
            "Access-Control-Expose-Headers": "Content-Disposition",
            "Access-Control-Allow-Methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
            "Vary": "Origin",
        },
        "body": csv_body,
    }


def _method(event: dict) -> str:
    return str(
        (event.get("requestContext") or {}).get("http", {}).get("method")
        or event.get("httpMethod")
        or ""
    ).upper()


def _path(event: dict) -> str:
    raw = event.get("rawPath") or event.get("path") or "/"
    return "/" + str(raw).strip("/")


def _body(event: dict) -> dict[str, Any]:
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    data = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(data, dict):
        raise ValueError("request body must be a JSON object")
    return data


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_campaign_id() -> str:
    return f"camp-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"


def _safe_filename(raw: str) -> str:
    name = (raw or "").strip()
    if not name or len(name) > 180:
        raise ValueError("fileName is required and must be <= 180 characters")
    if not name.lower().endswith(".csv"):
        raise ValueError("only CSV files are supported")
    if "/" in name or "\\" in name or name.startswith("."):
        raise ValueError("fileName must be a simple CSV filename")
    return name


def _normalize_local_schedule(scheduled_at: str, timezone_name: str) -> tuple[str, str]:
    raw = (scheduled_at or "").strip()
    tz_name = (timezone_name or "").strip()
    if not raw or not tz_name:
        raise ValueError("scheduledAt and timezone are required")
    try:
        zone = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("timezone must be a valid IANA timezone") from exc
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("scheduledAt must be an ISO date/time") from exc
    if parsed.tzinfo is None:
        local = parsed.replace(tzinfo=zone)
    else:
        local = parsed.astimezone(zone)
    utc = local.astimezone(dt.timezone.utc)
    if utc <= dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=1):
        raise ValueError("scheduledAt must be in the future")
    return local.isoformat(), utc.isoformat().replace("+00:00", "Z")


def _batches_table():
    return boto3.resource("dynamodb").Table(os.environ.get("BATCHES_TABLE_NAME", "TalkingBotCallBatches-dev"))


def _patients_table():
    return boto3.resource("dynamodb").Table(os.environ.get("PATIENTS_TABLE_NAME", "TalkingBotPatientRecords-dev"))


def _bucket() -> str:
    return os.environ["CAMPAIGN_BUCKET"]


def _scheduler_name(campaign_id: str) -> str:
    return f"cara-health-bot-campaign-{campaign_id}"[:64]


def _campaign(table, campaign_id: str) -> dict | None:
    return table.get_item(Key={"batchId": campaign_id}).get("Item")


def _patients(patients_tbl, campaign_id: str) -> list[dict]:
    items: list[dict] = []
    kwargs: dict[str, Any] = {
        "IndexName": "StatusSlotIndex",
        "KeyConditionExpression": Key("batchId").eq(campaign_id),
        "ScanIndexForward": True,
    }
    try:
        while True:
            response = patients_tbl.query(**kwargs)
            items.extend(response.get("Items", []))
            if not response.get("LastEvaluatedKey"):
                return items
            kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
    except ClientError:
        # Fallback if GSI querying on batchId isn't enabled or during scan fallback
        kwargs = {
            "FilterExpression": Attr("batchId").eq(campaign_id),
        }
        while True:
            response = patients_tbl.scan(**kwargs)
            items.extend(response.get("Items", []))
            if not response.get("LastEvaluatedKey"):
                return items
            kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]


def _summary(items: list[dict]) -> dict[str, Any]:
    statuses = Counter(str(item.get("status") or "UNKNOWN") for item in items)
    dispositions = Counter(str(item.get("disposition") or "") for item in items if item.get("disposition"))
    return {
        "total": len(items),
        "pending": statuses.get("PENDING", 0),
        "inProgress": statuses.get("IN_PROGRESS", 0),
        "callbackScheduled": statuses.get("CALLBACK_SCHEDULED", 0),
        "completed": statuses.get("COMPLETED", 0),
        "callSetupFailed": statuses.get("CALL_SETUP_FAILED", 0),
        "dispositions": dict(dispositions),
    }


def _decorate_campaign(batches_tbl, patients_tbl, item: dict, include_summary: bool = True) -> dict:
    result = dict(item)
    result["campaignId"] = result.get("batchId")
    result["customerCount"] = int(result.get("totalRows") or result.get("customerCount") or result.get("patientCount") or 0)
    if include_summary and result.get("batchId"):
        result["summary"] = _summary(_patients(patients_tbl, result["batchId"]))
    return result


def _create_upload(payload: dict) -> dict:
    batches_tbl = _batches_table()
    endpoint_url = os.environ.get("S3_ENDPOINT_URL")
    s3 = boto3.client("s3", endpoint_url=endpoint_url) if endpoint_url else boto3.client("s3")
    campaign_id = _new_campaign_id()
    filename = _safe_filename(str(payload.get("fileName") or ""))
    local_iso, utc_iso = _normalize_local_schedule(
        str(payload.get("scheduledAt") or ""), str(payload.get("timezone") or "")
    )
    customer_count = int(payload.get("customerCount") or 0)
    if customer_count <= 0:
        raise ValueError("customerCount must be greater than zero")
    file_size = int(payload.get("fileSize") or 0)
    if file_size < 0 or file_size > 10 * 1024 * 1024:
        raise ValueError("fileSize exceeds the 10 MB limit")
    original_id = (payload.get("originalRecordId") or "").strip() or None

    # Campaign-level configuration (Direct Agent toggle + Human Agent Phone Number)
    direct_agent_enabled = bool(payload.get("directAgentEnabled") in {True, "true", "True", 1})
    human_agent_phone = str(payload.get("humanAgentPhoneNumber") or "").strip()

    if not human_agent_phone:
        raise ValueError("humanAgentPhoneNumber is required for campaign creation")
    try:
        human_agent_phone = normalize_phone_e164(human_agent_phone)
    except Exception as err:
        raise ValueError(f"humanAgentPhoneNumber must be a valid E.164 phone number: {err}") from err

    now = _now()
    config = {
        "campaignId": campaign_id,
        "batchId": campaign_id,
        "fileName": filename,
        "fileSize": file_size,
        "customerCount": customer_count,
        "scheduledAt": local_iso,
        "timezone": payload.get("timezone"),
        "callTime": utc_iso,
        "uploadedAt": now,
        "originalRecordId": original_id,
        "directAgentEnabled": direct_agent_enabled,
        "humanAgentPhoneNumber": human_agent_phone,
    }
    key = f"campaigns/{campaign_id}/patients.csv"
    batches_tbl.put_item(
        Item={
            "batchId": campaign_id,
            "campaignId": campaign_id,
            "status": "UPLOAD_PENDING",
            "fileName": filename,
            "fileSize": file_size,
            "totalRows": customer_count,
            "customerCount": customer_count,
            "patientCount": customer_count,
            "scheduledAt": local_iso,
            "scheduledFor": utc_iso,
            "timezone": str(payload.get("timezone")),
            "s3Bucket": _bucket(),
            "s3Key": key,
            "uploadedAt": now,
            "createdAt": now,
            "updatedAt": now,
            "directAgentEnabled": direct_agent_enabled,
            "humanAgentPhoneNumber": human_agent_phone,
            **({"originalRecordId": original_id} if original_id else {}),
        },
        ConditionExpression=Attr("batchId").not_exists(),
    )
    if original_id:
        try:
            batches_tbl.update_item(
                Key={"batchId": original_id},
                UpdateExpression="SET replacedById=:newId, updatedAt=:now",
                ConditionExpression="attribute_exists(batchId)",
                ExpressionAttributeValues={":newId": campaign_id, ":now": now},
            )
        except ClientError:
            pass
    s3.put_object(
        Bucket=_bucket(),
        Key=f"campaigns/{campaign_id}/config.json",
        Body=json.dumps(config).encode("utf-8"),
        ContentType="application/json",
        ServerSideEncryption="AES256",
    )
    key = f"campaigns/{campaign_id}/patients.csv"
    upload_url = s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": _bucket(), "Key": key, "ContentType": "text/csv"},
        ExpiresIn=900,
    )
    return {
        "batchId": campaign_id,
        "campaignId": campaign_id,
        "uploadUrl": upload_url,
        "uploadHeaders": {"Content-Type": "text/csv"},
        "expiresInSeconds": 900,
    }


def _list_campaigns(event: dict) -> dict:
    batches_tbl = _batches_table()
    patients_tbl = _patients_table()
    limit = 50
    qs = event.get("queryStringParameters") or {}
    try:
        limit = max(1, min(MAX_LIST_LIMIT, int(qs.get("limit") or 50)))
    except ValueError:
        pass
    items: list[dict] = []
    kwargs: dict[str, Any] = {
        "Limit": min(500, limit * 5),
    }
    for _ in range(10):
        resp = batches_tbl.scan(**kwargs)
        items.extend(resp.get("Items", []))
        if len(items) >= limit or not resp.get("LastEvaluatedKey"):
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    items.sort(key=lambda x: x.get("createdAt") or "", reverse=True)
    return {"items": [_decorate_campaign(batches_tbl, patients_tbl, item, include_summary=False) for item in items[:limit]]}


def _detail(campaign_id: str) -> dict | None:
    batches_tbl = _batches_table()
    patients_tbl = _patients_table()
    item = _campaign(batches_tbl, campaign_id)
    return _decorate_campaign(batches_tbl, patients_tbl, item, include_summary=True) if item else None



def _patient_list(campaign_id: str) -> dict:
    batches_tbl = _batches_table()
    patients_tbl = _patients_table()
    if not _campaign(batches_tbl, campaign_id):
        raise KeyError(campaign_id)
    patient_items = _patients(patients_tbl, campaign_id)
    result = []
    for item in patient_items:
        phone = str(item.get("phoneNumber") or "")
        result.append({
            "patientId": item.get("patientId"),
            "empi": item.get("empi") or item.get("patientId"),
            "contactId": item.get("contactId"),
            "customerName": item.get("customerName"),
            "phoneLast4": phone[-4:] if len(phone) >= 4 else "",
            "status": item.get("status"),
            "identityResult": item.get("identityResult"),
            "disposition": item.get("disposition"),
            "attemptCount": int(item.get("attemptCount") or 0),
            "callbackCount": int(item.get("callbackCount") or 0),
            "callbackAt": item.get("callbackAt"),
            "callbackFor": item.get("callbackFor"),
            "callbackWhen": item.get("callbackWhen"),
            "callbackRequestedBy": item.get("callbackRequestedBy"),
            "completedAt": item.get("completedAt"),
            "callMode": item.get("callMode"),
        })
    return {"items": result, "summary": _summary(patient_items)}


def _export_patient_csv(campaign_id: str, patient_id: str, event: dict) -> dict:
    batches_tbl = _batches_table()
    patients_tbl = _patients_table()
    campaign = _campaign(batches_tbl, campaign_id)
    if not campaign:
        return _response(404, {"error": "Campaign not found"})

    patients = _patients(patients_tbl, campaign_id)
    target_patient = next((p for p in patients if str(p.get("patientId")) == patient_id or str(p.get("empi")) == patient_id), None)
    if not target_patient:
        return _response(404, {"error": "Patient not found"})

    call_attempts = target_patient.get("callAttempts") or []
    target_attempt = call_attempts[-1] if isinstance(call_attempts, list) and len(call_attempts) > 0 else {}

    empi = str(target_patient.get("empi") or target_patient.get("patientId") or "n/a")
    call_id = str(target_attempt.get("callId") or target_attempt.get("contactId") or target_patient.get("contactId") or "n/a")
    call_start_datetime = str(target_attempt.get("callStartDateTime") or target_patient.get("callStartDateTime") or target_patient.get("createdAt") or "n/a")
    call_end_datetime = str(target_attempt.get("callEndDateTime") or target_patient.get("callEndDateTime") or target_patient.get("completedAt") or "n/a")
    disposition = str(target_attempt.get("disposition") or target_patient.get("disposition") or target_patient.get("status") or "n/a")

    callback_for = target_patient.get("callbackFor") or target_patient.get("callbackAt") or target_patient.get("callbackWhen")
    requested_callback_date_time = str(callback_for) if callback_for else "n/a"

    call_mode = target_patient.get("callMode") or "NORMAL"
    call_type = "DIRECT_AGENT" if call_mode == "DIRECT_HUMAN_HANDOFF" else "NORMAL"
    if target_patient.get("callSummary"):
        call_summary = str(target_patient["callSummary"])
    elif target_patient.get("callbackReason"):
        call_summary = f"Callback requested: {target_patient['callbackReason']}"
    elif call_mode == "DIRECT_HUMAN_HANDOFF":
        call_summary = f"Direct Human Handoff call - {disposition}"
    elif disposition != "n/a":
        call_summary = f"Cara outreach - {disposition}"
    else:
        call_summary = "n/a"

    outbound_call_phone_number = str(target_attempt.get("outboundCallPhoneNumber") or target_patient.get("outboundCallPhoneNumber") or os.environ.get("CONNECT_SOURCE_PHONE_NUMBER", "+1877523XXXX"))

    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow([
        "empi",
        "call_id",
        "call_start_datetime",
        "call_end_datetime",
        "disposition",
        "call_summary",
        "requested_callback_date_time",
        "outbound_call_phone_number",
        "call_type",
    ])
    writer.writerow([
        empi,
        call_id,
        call_start_datetime,
        call_end_datetime,
        disposition,
        call_summary,
        requested_callback_date_time,
        outbound_call_phone_number,
        call_type,
    ])

    filename = f"{empi}_{call_id}.csv"
    return _csv_response(200, output.getvalue(), filename, event)


def _export_campaign_csv(campaign_id: str, event: dict) -> dict:
    batches_tbl = _batches_table()
    patients_tbl = _patients_table()
    campaign = _campaign(batches_tbl, campaign_id)
    if not campaign:
        return _response(404, {"error": "Campaign not found"})

    patients = _patients(patients_tbl, campaign_id)

    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow([
        "empi",
        "call_id",
        "call_start_datetime",
        "call_end_datetime",
        "disposition",
        "call_summary",
        "requested_callback_date_time",
        "outbound_call_phone_number",
        "call_type",
    ])

    default_source_phone = os.environ.get("CONNECT_SOURCE_PHONE_NUMBER", "+1877523XXXX")

    for target_patient in patients:
        empi = str(target_patient.get("empi") or target_patient.get("patientId") or "n/a")
        call_mode = target_patient.get("callMode") or campaign.get("callMode") or "NORMAL"
        call_type = "DIRECT_AGENT" if call_mode == "DIRECT_HUMAN_HANDOFF" else "NORMAL"
        
        callback_for = target_patient.get("callbackFor") or target_patient.get("callbackAt") or target_patient.get("callbackWhen")
        default_requested_callback = str(callback_for) if callback_for else "n/a"

        def _get_call_summary(disp: str) -> str:
            if target_patient.get("callSummary"):
                return str(target_patient["callSummary"])
            elif target_patient.get("callbackReason"):
                return f"Callback requested: {target_patient['callbackReason']}"
            elif call_mode == "DIRECT_HUMAN_HANDOFF":
                return f"Direct Human Handoff call - {disp}"
            elif disp and disp != "n/a":
                return f"Cara outreach - {disp}"
            return "n/a"

        call_attempts = target_patient.get("callAttempts") or []
        if isinstance(call_attempts, list) and len(call_attempts) > 0:
            for attempt in call_attempts:
                if not isinstance(attempt, dict):
                    continue
                call_id = str(attempt.get("callId") or attempt.get("contactId") or "n/a")
                call_start = str(attempt.get("callStartDateTime") or "n/a")
                call_end = str(attempt.get("callEndDateTime") or "n/a")
                disp = str(attempt.get("disposition") or "n/a")
                summary = str(attempt.get("callSummary") or _get_call_summary(disp))
                req_cb = str(attempt.get("requestedCallbackDateTime") or default_requested_callback)
                phone_num = str(attempt.get("outboundCallPhoneNumber") or target_patient.get("outboundCallPhoneNumber") or default_source_phone)

                writer.writerow([
                    empi,
                    call_id,
                    call_start,
                    call_end,
                    disp,
                    summary,
                    req_cb,
                    phone_num,
                    call_type,
                ])
        elif target_patient.get("contactId") or target_patient.get("disposition") or target_patient.get("status") in {"COMPLETED", "FAILED", "CALL_SETUP_FAILED", "CALLBACK_SCHEDULED", "AGENT_UNAVAILABLE"}:
            call_id = str(target_patient.get("contactId") or "n/a")
            call_start = str(target_patient.get("callStartDateTime") or target_patient.get("createdAt") or "n/a")
            call_end = str(target_patient.get("callEndDateTime") or target_patient.get("completedAt") or "n/a")
            disp = str(target_patient.get("disposition") or ("AGENT_UNAVAILABLE" if target_patient.get("status") == "AGENT_UNAVAILABLE" else target_patient.get("status") or "n/a"))
            summary = _get_call_summary(disp)
            phone_num = str(target_patient.get("outboundCallPhoneNumber") or default_source_phone)

            writer.writerow([
                empi,
                call_id,
                call_start,
                call_end,
                disp,
                summary,
                default_requested_callback,
                phone_num,
                call_type,
            ])

    raw_file_name = str(campaign.get("fileName") or "export.csv")
    stem = raw_file_name.rsplit(".", 1)[0] if "." in raw_file_name else raw_file_name
    export_filename = f"{stem}_export.csv"

    return _csv_response(200, output.getvalue(), export_filename, event)


def _cancel(campaign_id: str, payload: dict) -> dict:
    batches_tbl = _batches_table()
    patients_tbl = _patients_table()
    now = _now()
    reason = str(payload.get("reason") or "Cancelled by operator")[:250]
    try:
        response = batches_tbl.update_item(
            Key={"batchId": campaign_id},
            UpdateExpression="SET #s=:cancelled, cancellationReason=:reason, cancelledAt=:now, updatedAt=:now",
            ConditionExpression="#s IN (:upload,:pending)",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":upload": "UPLOAD_PENDING", ":pending": "PENDING", ":cancelled": "CANCELLED",
                ":reason": reason, ":now": now,
            },
            ReturnValues="ALL_NEW",
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            current = _campaign(batches_tbl, campaign_id)
            if not current:
                raise KeyError(campaign_id)
            raise RuntimeError(f"campaign cannot be cancelled from status {current.get('status')}") from exc
        raise
    try:
        boto3.client("scheduler").delete_schedule(Name=_scheduler_name(campaign_id), GroupName="default")
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
            raise
    return _decorate_campaign(batches_tbl, patients_tbl, response["Attributes"], include_summary=False)


def _reschedule(campaign_id: str, payload: dict) -> dict:
    batches_tbl = _batches_table()
    patients_tbl = _patients_table()
    original = _campaign(batches_tbl, campaign_id)
    if not original:
        raise KeyError(campaign_id)
    if original.get("status") not in RESCHEDULABLE_STATUSES:
        raise RuntimeError(f"campaign cannot be rescheduled from status {original.get('status')}")
    local_iso, utc_iso = _normalize_local_schedule(
        str(payload.get("scheduledAt") or ""), str(payload.get("timezone") or original.get("timezone") or "")
    )
    new_id = _new_campaign_id()
    s3 = boto3.client("s3")
    source_config = json.loads(
        s3.get_object(Bucket=_bucket(), Key=f"campaigns/{campaign_id}/config.json")["Body"].read()
    )
    source_config.update({
        "campaignId": new_id,
        "batchId": new_id,
        "scheduledAt": local_iso,
        "timezone": payload.get("timezone") or original.get("timezone"),
        "callTime": utc_iso,
        "uploadedAt": _now(),
        "originalRecordId": campaign_id,
    })
    key = f"campaigns/{new_id}/patients.csv"
    batches_tbl.put_item(Item={
        "batchId": new_id,
        "campaignId": new_id,
        "status": "UPLOAD_PENDING",
        "fileName": original.get("fileName", "patients.csv"),
        "fileSize": original.get("fileSize", 0),
        "totalRows": original.get("totalRows", original.get("customerCount", original.get("patientCount", 0))),
        "customerCount": original.get("customerCount", original.get("patientCount", 0)),
        "patientCount": original.get("patientCount", 0),
        "scheduledAt": local_iso,
        "scheduledFor": utc_iso,
        "timezone": source_config["timezone"],
        "s3Bucket": _bucket(),
        "s3Key": key,
        "uploadedAt": source_config["uploadedAt"],
        "createdAt": source_config["uploadedAt"],
        "updatedAt": source_config["uploadedAt"],
        "originalRecordId": campaign_id,
    })
    s3.put_object(
        Bucket=_bucket(), Key=f"campaigns/{new_id}/config.json",
        Body=json.dumps(source_config).encode("utf-8"), ContentType="application/json", ServerSideEncryption="AES256",
    )
    s3.copy_object(
        Bucket=_bucket(),
        CopySource={"Bucket": _bucket(), "Key": f"campaigns/{campaign_id}/patients.csv"},
        Key=key,
        ContentType="text/csv",
        MetadataDirective="REPLACE",
        ServerSideEncryption="AES256",
    )
    batches_tbl.update_item(
        Key={"batchId": campaign_id},
        UpdateExpression="SET rescheduledToId=:newId, updatedAt=:now",
        ExpressionAttributeValues={":newId": new_id, ":now": _now()},
    )
    return {"campaignId": new_id, "batchId": new_id}


def handler(event: dict, context) -> dict:
    try:
        method = _method(event)
        path = _path(event)
        if method == "OPTIONS":
            return _response(204, {}, event)
        if method == "POST" and path == "/uploads":
            return _response(201, _create_upload(_body(event)), event)
        if method == "GET" and path == "/campaigns":
            return _response(200, _list_campaigns(event), event)

        campaign_export_match = re.fullmatch(r"/campaigns/([A-Za-z0-9._-]{1,80})/export", path)
        if campaign_export_match:
            if method == "GET":
                campaign_id = campaign_export_match.group(1)
                return _export_campaign_csv(campaign_id, event)
            return _response(405, {"error": "Method not allowed"}, event)

        export_match = re.fullmatch(r"/campaigns/([A-Za-z0-9._-]{1,80})/patients/([A-Za-z0-9._-]{1,80})/export", path)
        if export_match:
            if method == "GET":
                campaign_id, patient_id = export_match.groups()
                return _export_patient_csv(campaign_id, patient_id, event)
            return _response(405, {"error": "Method not allowed"}, event)

        match = re.fullmatch(r"/campaigns/([A-Za-z0-9._-]{1,80})(?:/(patients|cancel|reschedule|export))?", path)
        if not match:
            return _response(404, {"error": "Not found"}, event)
        campaign_id, action = match.groups()
        if method == "GET" and action == "export":
            return _export_campaign_csv(campaign_id, event)
        if method == "GET" and action is None:
            item = _detail(campaign_id)
            return _response(200, item, event) if item else _response(404, {"error": "Campaign not found"}, event)
        if method == "GET" and action == "patients":
            try:
                return _response(200, _patient_list(campaign_id), event)
            except KeyError:
                return _response(404, {"error": "Campaign not found"}, event)
        if method == "POST" and action == "cancel":
            try:
                return _response(200, _cancel(campaign_id, _body(event)), event)
            except KeyError:
                return _response(404, {"error": "Campaign not found"}, event)
            except RuntimeError as exc:
                return _response(409, {"error": str(exc)}, event)
        if method == "POST" and action == "reschedule":
            try:
                return _response(201, _reschedule(campaign_id, _body(event)), event)
            except KeyError:
                return _response(404, {"error": "Campaign not found"}, event)
            except RuntimeError as exc:
                return _response(409, {"error": str(exc)}, event)
        return _response(405, {"error": "Method not allowed"}, event)
    except (ValueError, json.JSONDecodeError) as exc:
        return _response(400, {"error": str(exc)}, event)
    except Exception as exc:
        print(f"[campaign_api] FAILED {type(exc).__name__}: {exc}")
        return _response(500, {"error": "Campaign API request failed"}, event)
