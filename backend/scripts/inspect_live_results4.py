import json
import os
import sys
import boto3

profile = os.environ.get("AWS_PROFILE", "careharmony-main")
session = boto3.Session(profile_name=profile, region_name="us-east-1")
dynamo = session.resource("dynamodb")
batches_table = dynamo.Table("TalkingBotCallBatches-dev")
patients_table = dynamo.Table("TalkingBotPatientRecords-dev")

campaign_id = "test-real-1788191485"
batch = batches_table.get_item(Key={"batchId": campaign_id}).get("Item")
print("=== BATCH STATUS ===")
print(json.dumps(batch, indent=2, default=str))

print("\n=== PATIENTS ===")
response = patients_table.scan(
    FilterExpression="batchId = :bid",
    ExpressionAttributeValues={":bid": campaign_id}
)
items = response.get("Items", [])
for item in items:
    print(f"\nPatient ID: {item.get('patientId')}")
    print(f"  Name: {item.get('firstName')} {item.get('lastName')}")
    print(f"  Status: {item.get('status')}")
    print(f"  Call Mode: {item.get('callMode')}")
    print(f"  Contact ID: {item.get('contactId')}")
    print(f"  Disposition: {item.get('disposition')}")
    print(f"  Identity Result: {item.get('identityResult')}")
    print(f"  Attempts: {item.get('callAttempts')}")
