import boto3
from boto3.dynamodb.conditions import Attr

session = boto3.Session(profile_name="careharmony", region_name="us-east-1")
table = session.resource("dynamodb").Table("TalkingBotPatientRecords-dev")

res = table.scan(FilterExpression=Attr("batchId").eq("test-real-1788185068"))
print(f"Total matching items: {len(res.get('Items', []))}")
for item in sorted(res.get("Items", []), key=lambda x: x.get("patientId", "")):
    print(f"patient: {item.get('customerName') or item.get('patientName') or item.get('patientId')}")
    print(f"direct_agent: {item.get('direct_agent')}")
    print(f"callMode: {item.get('callMode')}")
    print(f"status: {item.get('status')}")
    print(f"disposition: {item.get('disposition')}")
    print(f"contactId: {item.get('contactId')}")
    print("---")
