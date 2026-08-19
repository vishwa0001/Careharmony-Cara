#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import boto3
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Print only Cara/customer turns from the Connect automated-interaction recording."
    )
    p.add_argument("contact_id")
    p.add_argument(
        "--wait-seconds",
        type=int,
        default=120,
        help="How long to wait for the IVR recording to become available (default: 120)",
    )
    p.add_argument(
        "--language-code",
        default="en-US",
        help="Amazon Transcribe language code (default: en-US)",
    )
    return p.parse_args()


def load_outputs() -> dict[str, str]:
    path = ROOT / "deployment-state.json"
    if not path.is_file():
        raise RuntimeError("deployment-state.json not found. Run ./deploy.sh first.")
    out = json.loads(path.read_text(encoding="utf-8")).get("outputs", {})
    for key in ("Region", "InstanceId"):
        if not out.get(key):
            raise RuntimeError(f"deployment-state.json is missing output: {key}")
    return out


def timestamp_key(value: Any) -> dt.datetime:
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)
    if isinstance(value, (int, float)):
        value = float(value)
        if value > 10_000_000_000:
            value /= 1000.0
        return dt.datetime.fromtimestamp(value, tz=dt.timezone.utc)
    if isinstance(value, str):
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)
        except ValueError:
            pass
    return dt.datetime.min.replace(tzinfo=dt.timezone.utc)


def parse_s3_location(location: str) -> tuple[str, str]:
    """Accept the S3 location forms returned by Connect/Transcribe.

    Supported examples:
      s3://bucket/key
      bucket/key
      https://bucket.s3.us-east-1.amazonaws.com/key
      https://s3.us-east-1.amazonaws.com/bucket/key
    """
    location = (location or "").strip()
    if not location:
        raise RuntimeError("Recording S3 location is empty")

    if location.startswith("s3://"):
        parsed = urlparse(location)
        bucket = parsed.netloc
        key = unquote(parsed.path.lstrip("/"))
        if bucket and key:
            return bucket, key

    parsed = urlparse(location)
    host = parsed.netloc.lower()
    path = unquote(parsed.path.lstrip("/"))
    if parsed.scheme in {"http", "https"} and host and path:
        # Virtual-hosted style: https://bucket.s3.<region>.amazonaws.com/key
        # and https://bucket.s3.amazonaws.com/key
        marker = ".s3"
        if marker in host:
            bucket = host.split(marker, 1)[0]
            if bucket:
                return bucket, path
        # Path style: https://s3.<region>.amazonaws.com/bucket/key
        if host == "s3.amazonaws.com" or host.startswith("s3.") or host.startswith("s3-"):
            if "/" in path:
                bucket, key = path.split("/", 1)
                if bucket and key:
                    return bucket, key

    # Connect DescribeContact can return Location as bare "bucket/key".
    if "://" not in location and "/" in location:
        bucket, key = location.split("/", 1)
        if bucket and key:
            return bucket, key

    raise RuntimeError(f"Unsupported recording S3 location: {location}")


def contact_details(connect: Any, instance_id: str, contact_id: str) -> dict[str, Any]:
    return connect.describe_contact(InstanceId=instance_id, ContactId=contact_id)["Contact"]


def _recording_candidates(contact: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [
        r
        for r in (contact.get("Recordings") or [])
        if r.get("StorageType") == "S3"
        and r.get("MediaStreamType") == "AUDIO"
        and r.get("Status") == "AVAILABLE"
        and r.get("Location")
    ]
    candidates.sort(key=lambda r: timestamp_key(r.get("StartTimestamp")))
    return candidates


def wait_for_ivr_recording(
    connect: Any, instance_id: str, contact_id: str, wait_seconds: int
) -> dict[str, Any] | None:
    deadline = time.time() + max(0, wait_seconds)
    while True:
        contact = contact_details(connect, instance_id, contact_id)
        recordings = _recording_candidates(contact)
        if recordings:
            # Bot-only calls have one recording. Once human transfer is added there
            # can be a second agent-interaction recording; the automated/IVR one is
            # the recording that starts first.
            return recordings[0]
        if time.time() >= deadline:
            return None
        time.sleep(5)


def _normalize_recording_for_transcribe(
    s3: Any,
    input_bucket: str,
    input_key: str,
    output_bucket: str,
    contact_id: str,
    media_format: str,
) -> str:
    """Copy Connect's recording to an SSE-S3 object Transcribe can consume.

    Connect recordings may use Connect/KMS object encryption. Rewriting the object
    into the project bucket with SSE-S3 avoids asking Transcribe to decrypt the
    original Connect object directly.
    """
    target_key = f"transcribe-input/{contact_id}.{media_format}"
    try:
        s3.head_object(Bucket=output_bucket, Key=target_key)
        return f"s3://{output_bucket}/{target_key}"
    except ClientError as error:
        code = str(error.response.get("Error", {}).get("Code", ""))
        status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code not in {"404", "NoSuchKey", "NotFound"} and status != 404:
            raise

    try:
        s3.copy_object(
            Bucket=output_bucket,
            Key=target_key,
            CopySource={"Bucket": input_bucket, "Key": input_key},
            ServerSideEncryption="AES256",
        )
    except ClientError:
        # Fallback for environments where CopyObject has stricter KMS behavior.
        source = s3.get_object(Bucket=input_bucket, Key=input_key)
        body = source["Body"].read()
        s3.put_object(
            Bucket=output_bucket,
            Key=target_key,
            Body=body,
            ServerSideEncryption="AES256",
            ContentType=source.get("ContentType", "audio/wav"),
        )
    return f"s3://{output_bucket}/{target_key}"


def _job_name(contact_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]", "-", contact_id)[:160]
    # v2 prevents a failed job created by older transcript.py versions from
    # poisoning retries forever for the same ContactId.
    return f"cara-health-bot-stereo-v2-{safe}"


def _get_job_or_none(transcribe: Any, job_name: str) -> dict[str, Any] | None:
    try:
        return transcribe.get_transcription_job(TranscriptionJobName=job_name)["TranscriptionJob"]
    except ClientError as error:
        code = str(error.response.get("Error", {}).get("Code", ""))
        if code not in {"BadRequestException", "NotFoundException", "ResourceNotFoundException"}:
            raise
        return None


def _wait_for_job(transcribe: Any, job_name: str, timeout_seconds: int = 300) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        job = transcribe.get_transcription_job(TranscriptionJobName=job_name)["TranscriptionJob"]
        status = job.get("TranscriptionJobStatus")
        if status == "COMPLETED":
            return job
        if status == "FAILED":
            raise RuntimeError(f"Amazon Transcribe failed: {job.get('FailureReason', 'unknown reason')}")
        time.sleep(5)
    raise RuntimeError("Timed out waiting for Amazon Transcribe")


def _channel_turns(
    channel: dict[str, Any], speaker: str, base: dt.datetime, silence_gap_seconds: float = 1.3
) -> list[tuple[dt.datetime, str, str]]:
    turns: list[tuple[dt.datetime, str, str]] = []
    words: list[str] = []
    start_sec: float | None = None
    previous_end: float | None = None

    def flush() -> None:
        nonlocal words, start_sec, previous_end
        text = " ".join(words).strip()
        text = re.sub(r"\s+([,.!?;:])", r"\1", text)
        if text and start_sec is not None:
            turns.append((base + dt.timedelta(seconds=start_sec), speaker, text))
        words, start_sec, previous_end = [], None, None

    for item in channel.get("items") or []:
        alternatives = item.get("alternatives") or []
        if not alternatives:
            continue
        content = str(alternatives[0].get("content") or "").strip()
        if not content:
            continue
        item_type = str(item.get("type") or "")
        if item_type == "punctuation":
            if words:
                words.append(content)
                if content in {".", "?", "!"}:
                    flush()
            continue

        try:
            item_start = float(item.get("start_time", previous_end if previous_end is not None else 0.0))
            item_end = float(item.get("end_time", item_start))
        except (TypeError, ValueError):
            item_start = previous_end if previous_end is not None else 0.0
            item_end = item_start
        if previous_end is not None and item_start - previous_end >= silence_gap_seconds:
            flush()
        if start_sec is None:
            start_sec = item_start
        words.append(content)
        previous_end = item_end
    flush()
    return turns


def turns_from_transcribe_document(
    document: dict[str, Any], recording_start: Any
) -> list[tuple[dt.datetime, str, str]]:
    """Convert a channel-identified Transcribe document to Cara/Customer turns."""
    channels = ((document.get("results") or {}).get("channel_labels") or {}).get("channels") or []
    if not channels:
        raise RuntimeError("Amazon Transcribe returned no channel-identification data")

    by_label = {str(c.get("channel_label")): c for c in channels}
    if "ch_0" not in by_label or "ch_1" not in by_label:
        raise RuntimeError(
            "Expected a two-channel Connect automated-interaction recording, "
            f"but Transcribe returned channels: {sorted(by_label)}"
        )

    # AWS Connect automated/IVR stereo layout: left = system prompts, right =
    # customer. Transcribe labels the first/second channels ch_0/ch_1.
    base = timestamp_key(recording_start)
    turns = _channel_turns(by_label["ch_0"], "Cara", base)
    turns.extend(_channel_turns(by_label["ch_1"], "Customer", base))
    turns.sort(key=lambda x: x[0])
    return turns


def transcribe_recording(
    transcribe: Any,
    s3: Any,
    recording: dict[str, Any],
    contact_id: str,
    output_bucket: str,
    output_prefix: str,
    language_code: str,
) -> list[tuple[dt.datetime, str, str]]:
    input_bucket, input_key = parse_s3_location(str(recording["Location"]))
    media_format = Path(input_key).suffix.lower().lstrip(".") or "wav"
    if media_format not in {"wav", "mp3", "mp4", "flac", "ogg", "amr", "webm", "m4a"}:
        media_format = "wav"

    media_uri = _normalize_recording_for_transcribe(
        s3, input_bucket, input_key, output_bucket, contact_id, media_format
    )
    job_name = _job_name(contact_id)
    output_key = f"{output_prefix.rstrip('/')}/{contact_id}-stereo-v2.json"

    job = _get_job_or_none(transcribe, job_name)
    if job and job.get("TranscriptionJobStatus") == "FAILED":
        # A failed name cannot be reused until deleted.
        transcribe.delete_transcription_job(TranscriptionJobName=job_name)
        job = None

    if job is None:
        transcribe.start_transcription_job(
            TranscriptionJobName=job_name,
            LanguageCode=language_code,
            MediaFormat=media_format,
            Media={"MediaFileUri": media_uri},
            OutputBucketName=output_bucket,
            OutputKey=output_key,
            Settings={"ChannelIdentification": True},
        )

    _wait_for_job(transcribe, job_name)

    # We control OutputBucketName/OutputKey, so read that exact object. This avoids
    # differences in TranscriptFileUri URL formatting across SDK/service versions.
    try:
        obj = s3.get_object(Bucket=output_bucket, Key=output_key)
    except ClientError as error:
        raise RuntimeError(
            f"Transcribe completed but output s3://{output_bucket}/{output_key} was not readable: "
            f"{error.response.get('Error', {}).get('Message', str(error))}"
        ) from error
    document = json.loads(obj["Body"].read())
    return turns_from_transcribe_document(document, recording.get("StartTimestamp"))


def main() -> int:
    args = parse_args()
    try:
        if args.wait_seconds < 0:
            raise ValueError("--wait-seconds must be >= 0")
        if not re.fullmatch(r"[a-z]{2}-[A-Z]{2}", args.language_code):
            raise ValueError("--language-code must look like en-US")

        out = load_outputs()
        region = out["Region"]
        connect = boto3.client("connect", region_name=region)
        s3 = boto3.client("s3", region_name=region)
        transcribe = boto3.client("transcribe", region_name=region)

        recording = wait_for_ivr_recording(
            connect, out["InstanceId"], args.contact_id, args.wait_seconds
        )
        if recording is None:
            raise RuntimeError(
                "The automated-interaction recording is not available yet. "
                "Wait a little after hangup and run this command again."
            )

        output_bucket = out.get("RecordingBucket")
        if not output_bucket:
            output_bucket, _ = parse_s3_location(str(recording["Location"]))

        turns = transcribe_recording(
            transcribe,
            s3,
            recording,
            args.contact_id,
            output_bucket,
            out.get("TranscriptPrefix", "transcribe-output"),
            args.language_code,
        )
        if not turns:
            raise RuntimeError("The recording was transcribed but contained no spoken turns.")
        for _, speaker, text in turns:
            print(f"{speaker}: {text}")
        return 0
    except NoCredentialsError as error:
        print(f"AWS credentials error: {error}", file=sys.stderr)
        return 3
    except (ClientError, BotoCoreError) as error:
        print(f"AWS error: {error}", file=sys.stderr)
        return 3
    except (RuntimeError, ValueError, OSError, json.JSONDecodeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
