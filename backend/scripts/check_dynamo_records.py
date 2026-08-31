import boto3

session = boto3.Session(profile_name="careharmony", region_name="us-east-1")
table = session.resource("dynamodb").Table("TalkingBotPatientRecords-dev")
res = table.scan()
print(f"Total patient records: {len(res.get('Items', []))}")
for item in res.get("Items", []):
    print("patient:", item.get("patientName") or item.get("customerName") or item.get("patientId"))
    print("direct_agent:", item.get("direct_agent"))
    print("callMode:", item.get("callMode"))
    print("status:", item.get("status"))
    print("disposition:", item.get("disposition"))
    print("---")
