import csv
import datetime as dt
import json
import os
import sys
import time
import boto3

def main():
    profile = os.environ.get("AWS_PROFILE", "careharmony-main")
    session = boto3.Session(profile_name=profile, region_name="us-east-1")
    s3 = session.client("s3")
    dynamo = session.resource("dynamodb")
    batches_table = dynamo.Table("TalkingBotCallBatches-dev")

    campaign_id = f"test-meta-{int(time.time())}"
    bucket_name = "cara-health-bot-campaigns-176032258673-us-east-1"
    
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
        f"TEST-META-001,Kevin,Peterson,Male,{phone},Mercy Health,+18005550100,no\n"
    )

    print(f"Creating live meta-interruption test campaign: {campaign_id}")
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

    print(f"Uploaded CSV and config to s3://{bucket_name}/campaigns/{campaign_id}/")
    print("Intake Lambda will parse and schedule the call immediately.")

if __name__ == "__main__":
    main()
