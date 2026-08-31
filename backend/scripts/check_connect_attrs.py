import boto3

session = boto3.Session(profile_name="careharmony", region_name="us-east-1")
client = session.client("connect")

for attr_type in [
    "INBOUND_CALLS",
    "OUTBOUND_CALLS",
    "CONTACTFLOW_LOGS",
    "CONTACT_LENS",
    "AUTO_RESOLVE_BEST_VOICES",
    "USE_CUSTOM_TTS_VOICES",
    "ENHANCED_CONTACT_MONITORING",
    "ENHANCED_CHAT_MONITORING",
    "HIGH_VOLUME_OUTBOUND",
]:
    try:
        r = client.describe_instance_attribute(
            InstanceId="c3fad8b2-0d5c-4a2c-9532-4a684dbe4764",
            AttributeType=attr_type,
        )
        print(f"{attr_type}: {r['Attribute']['Value']}")
    except Exception as e:
        print(f"{attr_type}: ERROR - {e}")
