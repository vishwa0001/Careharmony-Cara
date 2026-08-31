import boto3
from boto3.dynamodb.conditions import Attr

session = boto3.Session(profile_name="careharmony", region_name="us-east-1")
table = session.resource("dynamodb").Table("TalkingBotPatientRecords-dev")

res = table.scan(FilterExpression=Attr("batchId").eq("live-test-1788186554"))
items = sorted(res.get("Items", []), key=lambda x: x.get("patientId", ""))

print(f"Total matching items: {len(items)}")
for i, item in enumerate(items, 1):
    print(f"--- ROW {i} ---")
    print(f"patientId: {item.get('patientId')}")
    print(f"empi: {item.get('empi')}")
    print(f"contactId: {item.get('contactId')}")
    print(f"direct_agent: {item.get('direct_agent')}")
    print(f"callMode: {item.get('callMode')}")
    print(f"status: {item.get('status')}")
    print(f"disposition: {item.get('disposition')}")
    print(f"identityResult: {item.get('identityResult')}")
    print(f"rawItem: {item}")
