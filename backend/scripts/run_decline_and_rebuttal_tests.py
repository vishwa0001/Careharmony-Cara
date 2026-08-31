import csv
import datetime as dt
import json
import os
import sys
import time
import boto3

def run_targeted_test():
    session = boto3.Session(profile_name="careharmony", region_name="us-east-1")
    s3 = session.client("s3")
    dynamo = session.resource("dynamodb")
    batches_table = dynamo.Table("TalkingBotCallBatches-dev")
    patients_table = dynamo.Table("TalkingBotPatientRecords-dev")

    campaign_id = f"test-paired-{int(time.time())}"
    bucket_name = "cara-health-bot-campaigns-701348334422-us-east-1"
    
    now_dt = dt.datetime.now(dt.timezone.utc)
    scheduled_iso = (now_dt + dt.timedelta(seconds=10)).strftime("%Y-%m-%dT%H:%M:%SZ")

    config_data = {
        "campaignId": campaign_id,
        "batchId": campaign_id,
        "fileName": "patients.csv",
        "customerCount": 2,
        "patientCount": 2,
        "totalRows": 2,
        "scheduledAt": scheduled_iso,
        "timezone": "UTC",
        "callTime": scheduled_iso,
        "uploadedAt": now_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    phone = "+18148316822"

    # Row 1: Test Explicit Decline ("I'm not interested")
    # Row 2: Test Rebuttal + Dynamic Transfer Fetch
    csv_content = (
        "empi,first_name,last_name,gender,phone_number,practice_name,practice_callback_number,direct_agent\n"
        f"TEST-DECLINE-01,John,Doe,Male,{phone},Mercy Health,+18005550100,no\n"
        f"TEST-REBUTTAL-02,Jane,Smith,Female,{phone},Mercy Health,+18005550100,no\n"
    )

    print(f"Creating targeted campaign batch: {campaign_id}")
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

    s3.put_object(
        Bucket=bucket_name,
        Key=f"campaigns/{campaign_id}/config.json",
        Body=json.dumps(config_data).encode("utf-8"),
        ContentType="application/json",
    )

    s3.put_object(
        Bucket=bucket_name,
        Key=f"campaigns/{campaign_id}/patients.csv",
        Body=csv_content.encode("utf-8"),
        ContentType="text/csv",
    )
    print(f"Campaign {campaign_id} created and uploaded.")
    return campaign_id

if __name__ == "__main__":
    cid = run_targeted_test()
    print(f"Targeted Campaign ID: {cid}")
