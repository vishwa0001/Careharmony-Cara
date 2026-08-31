import csv
import datetime as dt
import json
import os
import sys
import time
import boto3

def run_real_campaign():
    session = boto3.Session(profile_name="careharmony", region_name="us-east-1")
    s3 = session.client("s3")
    dynamo = session.resource("dynamodb")
    batches_table = dynamo.Table("TalkingBotCallBatches-dev")
    patients_table = dynamo.Table("TalkingBotPatientRecords-dev")

    campaign_id = f"test-real-{int(time.time())}"
    bucket_name = "cara-health-bot-campaigns-701348334422-us-east-1"
    
    # Schedule for 1 minute from now in UTC
    now_dt = dt.datetime.now(dt.timezone.utc)
    scheduled_dt = now_dt + dt.timedelta(minutes=1)
    scheduled_iso = scheduled_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    config_data = {
        "campaignId": campaign_id,
        "batchId": campaign_id,
        "fileName": "patients.csv",
        "customerCount": 3,
        "patientCount": 3,
        "totalRows": 3,
        "scheduledAt": scheduled_iso,
        "timezone": "UTC",
        "callTime": scheduled_iso,
        "uploadedAt": now_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    phone = "+18148316822"

    # 3-row test CSV
    csv_content = (
        "empi,first_name,last_name,gender,phone_number,practice_name,practice_callback_number,direct_agent\n"
        f"TEST-ROW-1,John,Doe,Male,{phone},Mercy Health,+18005550100,yes\n"
        f"TEST-ROW-2-UNAVAIL,Jane,Smith,Female,{phone},Mercy Health,+18005550100,yes\n"
        f"TEST-ROW-3-NORMAL,Alex,Taylor,Non-Binary,{phone},Mercy Health,+18005550100,no\n"
    )

    print(f"Creating campaign batch record: {campaign_id}")
    batches_table.put_item(
        Item={
            **config_data,
            "status": "UPLOAD_PENDING",
            "s3Bucket": bucket_name,
            "s3Key": f"campaigns/{campaign_id}/patients.csv",
            "createdAt": now_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "updatedAt": now_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    )

    print(f"1. Uploading config.json to s3://{bucket_name}/campaigns/{campaign_id}/config.json")
    s3.put_object(
        Bucket=bucket_name,
        Key=f"campaigns/{campaign_id}/config.json",
        Body=json.dumps(config_data).encode("utf-8"),
        ContentType="application/json",
    )

    print(f"2. Uploading patients.csv to s3://{bucket_name}/campaigns/{campaign_id}/patients.csv")
    s3.put_object(
        Bucket=bucket_name,
        Key=f"campaigns/{campaign_id}/patients.csv",
        Body=csv_content.encode("utf-8"),
        ContentType="text/csv",
    )
    print("Upload complete. S3 event will trigger campaign_intake and dialer Lambda.")
    return campaign_id

if __name__ == "__main__":
    campaign_id = run_real_campaign()
    print(f"Campaign ID: {campaign_id}")
