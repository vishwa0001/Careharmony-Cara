import csv
import datetime as dt
import json
import os
import sys
import time
import boto3

def run_decline_test():
    session = boto3.Session(profile_name="careharmony", region_name="us-east-1")
    s3 = session.client("s3")
    dynamo = session.resource("dynamodb")
    batches_table = dynamo.Table("TalkingBotCallBatches-dev")

    campaign_id = f"test-decline-{int(time.time())}"
    bucket_name = "cara-health-bot-campaigns-701348334422-us-east-1"
    
    now_dt = dt.datetime.now(dt.timezone.utc)
    scheduled_iso = (now_dt + dt.timedelta(seconds=5)).strftime("%Y-%m-%dT%H:%M:%SZ")

    config_data = {
        "campaignId": campaign_id,
        "batchId": campaign_id,
        "fileName": "patients.csv",
        "customerCount": 1,
        "patientCount": 1,
        "totalRows": 1,
        "scheduledAt": scheduled_iso,
        "timezone": "UTC",
        "callTime": scheduled_iso,
        "uploadedAt": now_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    phone = "+18148316822"

    csv_content = (
        "empi,first_name,last_name,gender,phone_number,practice_name,practice_callback_number,direct_agent\n"
        f"TEST-DECLINE-EMPI,Sarah,Connor,Female,{phone},Mercy Health,+18005550100,no\n"
    )

    print(f"Creating decline test campaign: {campaign_id}")
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
    print(f"Campaign {campaign_id} uploaded.")
    return campaign_id

if __name__ == "__main__":
    cid = run_decline_test()
    print(f"Campaign ID: {cid}")
