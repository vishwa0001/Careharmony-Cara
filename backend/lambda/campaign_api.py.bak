"""HTTP API Lambda for Cara Health Bot campaign management.

Transport/auth is deliberately separated from business logic. The campaign deployer
can expose this through an AWS_IAM-protected Lambda Function URL, while production
frontends can place API Gateway/Cognito or another authenticated edge in front.
"""
from __future__ import annotations

import base64
import datetime as dt
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

CAMPAIGN_KEY = "CAMPAIGN"
ACTIVE_CANCEL_STATUSES = {"UPLOAD_PENDING", "PENDING"}
RESCHEDULABLE_STATUSES = {"CANCELLED"}
MAX_LIST_LIMIT = 100


def _json_default(value: Any):
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def _response(status: int, body: Any) -> dict[str, Any]:
    origin = os.environ.get("API_ALLOWED_ORIGIN", "http://localhost:5173")
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Headers": "content-type,authorization",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
            "Vary": "Origin",
        },
        "body": json.dumps(body, default=_json_default),
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


def _table():
    return boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])


def _bucket() -> str:
    return os.environ["CAMPAIGN_BUCKET"]


def _scheduler_name(campaign_id: str) -> str:
    return f"cara-health-bot-campaign-{campaign_id}"[:64]


def _campaign(table, campaign_id: str) -> dict | None:
    return table.get_item(Key={"campaignId": campaign_id, "recordKey": CAMPAIGN_KEY}).get("Item")


def _patients(table, campaign_id: str) -> list[dict]:
    items: list[dict] = []
    kwargs: dict[str, Any] = {
        "KeyConditionExpression": Key("campaignId").eq(campaign_id) & Key("recordKey").begins_with("PATIENT#"),
        "ScanIndexForward": True,
    }
    while True:
        response = table.query(**kwargs)
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


def _decorate_campaign(table, item: dict, include_summary: bool = True) -> dict:
    result = dict(item)
    result["batchId"] = result.get("campaignId")
    result["customerCount"] = int(result.get("patientCount") or result.get("customerCount") or 0)
    if include_summary and result.get("campaignId"):
        result["summary"] = _summary(_patients(table, result["campaignId"]))
    return result


def _create_upload(payload: dict) -> dict:
    table = _table()
    s3 = boto3.client("s3")
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
    now = _now()
    config = {
        "campaignId": campaign_id,
        "fileName": filename,
        "fileSize": file_size,
        "customerCount": customer_count,
        "scheduledAt": local_iso,
        "timezone": payload.get("timezone"),
        "callTime": utc_iso,
        "uploadedAt": now,
        "originalRecordId": original_id,
    }
    table.put_item(
        Item={
            "campaignId": campaign_id,
            "recordKey": CAMPAIGN_KEY,
            "entityType": "CAMPAIGN",
            "status": "UPLOAD_PENDING",
            "fileName": filename,
            "fileSize": file_size,
            "customerCount": customer_count,
            "patientCount": customer_count,
            "scheduledAt": local_iso,
            "scheduledFor": utc_iso,
            "timezone": str(payload.get("timezone")),
            "uploadedAt": now,
            "createdAt": now,
            "updatedAt": now,
            **({"originalRecordId": original_id} if original_id else {}),
        },
        ConditionExpression=Attr("campaignId").not_exists(),
    )
    if original_id:
        try:
            table.update_item(
                Key={"campaignId": original_id, "recordKey": CAMPAIGN_KEY},
                UpdateExpression="SET replacedById=:newId, updatedAt=:now",
                ConditionExpression="attribute_exists(campaignId) AND attribute_exists(recordKey)",
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
    table = _table()
    limit = 50
    qs = event.get("queryStringParameters") or {}
    try:
        limit = max(1, min(MAX_LIST_LIMIT, int(qs.get("limit") or 50)))
    except ValueError:
        pass
    items: list[dict] = []
    kwargs: dict[str, Any] = {
        "FilterExpression": Attr("recordKey").eq(CAMPAIGN_KEY),
        "Limit": min(500, limit * 5),
    }
    for _ in range(10):
        resp = table.scan(**kwargs)
        items.extend(resp.get("Items", []))
        if len(items) >= limit or not resp.get("LastEvaluatedKey"):
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    items.sort(key=lambda x: x.get("createdAt") or "", reverse=True)
    return {"items": [_decorate_campaign(table, item, include_summary=False) for item in items[:limit]]}


def _detail(campaign_id: str) -> dict | None:
    table = _table()
    item = _campaign(table, campaign_id)
    return _decorate_campaign(table, item, include_summary=True) if item else None


def _patient_list(campaign_id: str) -> dict:
    table = _table()
    if not _campaign(table, campaign_id):
        raise KeyError(campaign_id)
    patient_items = _patients(table, campaign_id)
    result = []
    for item in patient_items:
        phone = str(item.get("phoneNumber") or "")
        result.append({
            "patientId": item.get("patientId"),
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
        })
    return {"items": result, "summary": _summary(patient_items)}


def _cancel(campaign_id: str, payload: dict) -> dict:
    table = _table()
    now = _now()
    reason = str(payload.get("reason") or "Cancelled by operator")[:250]
    try:
        response = table.update_item(
            Key={"campaignId": campaign_id, "recordKey": CAMPAIGN_KEY},
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
            current = _campaign(table, campaign_id)
            if not current:
                raise KeyError(campaign_id)
            raise RuntimeError(f"campaign cannot be cancelled from status {current.get('status')}") from exc
        raise
    try:
        boto3.client("scheduler").delete_schedule(Name=_scheduler_name(campaign_id), GroupName="default")
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
            raise
    return _decorate_campaign(table, response["Attributes"], include_summary=False)


def _reschedule(campaign_id: str, payload: dict) -> dict:
    table = _table()
    original = _campaign(table, campaign_id)
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
        "scheduledAt": local_iso,
        "timezone": payload.get("timezone") or original.get("timezone"),
        "callTime": utc_iso,
        "uploadedAt": _now(),
        "originalRecordId": campaign_id,
    })
    table.put_item(Item={
        "campaignId": new_id,
        "recordKey": CAMPAIGN_KEY,
        "entityType": "CAMPAIGN",
        "status": "UPLOAD_PENDING",
        "fileName": original.get("fileName", "patients.csv"),
        "fileSize": original.get("fileSize", 0),
        "customerCount": original.get("customerCount", original.get("patientCount", 0)),
        "patientCount": original.get("patientCount", 0),
        "scheduledAt": local_iso,
        "scheduledFor": utc_iso,
        "timezone": source_config["timezone"],
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
        Key=f"campaigns/{new_id}/patients.csv",
        ContentType="text/csv",
        MetadataDirective="REPLACE",
        ServerSideEncryption="AES256",
    )
    table.update_item(
        Key={"campaignId": campaign_id, "recordKey": CAMPAIGN_KEY},
        UpdateExpression="SET rescheduledToId=:newId, updatedAt=:now",
        ExpressionAttributeValues={":newId": new_id, ":now": _now()},
    )
    return {"campaignId": new_id, "batchId": new_id}


def handler(event: dict, context) -> dict:
    try:
        method = _method(event)
        path = _path(event)
        if method == "OPTIONS":
            return _response(204, {})
        if method == "POST" and path == "/uploads":
            return _response(201, _create_upload(_body(event)))
        if method == "GET" and path == "/campaigns":
            return _response(200, _list_campaigns(event))

        match = re.fullmatch(r"/campaigns/([A-Za-z0-9._-]{1,80})(?:/(patients|cancel|reschedule))?", path)
        if not match:
            return _response(404, {"error": "Not found"})
        campaign_id, action = match.groups()
        if method == "GET" and action is None:
            item = _detail(campaign_id)
            return _response(200, item) if item else _response(404, {"error": "Campaign not found"})
        if method == "GET" and action == "patients":
            try:
                return _response(200, _patient_list(campaign_id))
            except KeyError:
                return _response(404, {"error": "Campaign not found"})
        if method == "POST" and action == "cancel":
            try:
                return _response(200, _cancel(campaign_id, _body(event)))
            except KeyError:
                return _response(404, {"error": "Campaign not found"})
            except RuntimeError as exc:
                return _response(409, {"error": str(exc)})
        if method == "POST" and action == "reschedule":
            try:
                return _response(201, _reschedule(campaign_id, _body(event)))
            except KeyError:
                return _response(404, {"error": "Campaign not found"})
            except RuntimeError as exc:
                return _response(409, {"error": str(exc)})
        return _response(405, {"error": "Method not allowed"})
    except (ValueError, json.JSONDecodeError) as exc:
        return _response(400, {"error": str(exc)})
    except Exception as exc:
        print(f"[campaign_api] FAILED {type(exc).__name__}: {exc}")
        return _response(500, {"error": "Campaign API request failed"})
