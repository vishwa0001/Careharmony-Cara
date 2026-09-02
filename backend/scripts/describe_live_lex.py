import boto3
import json

session = boto3.Session(profile_name="careharmony-main", region_name="us-east-1")
lex = session.client("lexv2-models")

bot_id = "TZ7RVZJ2VG"
alias_id = "YS2ECNTEXL"

alias = lex.describe_bot_alias(botId=bot_id, botAliasId=alias_id)
bot_version = alias["botVersion"]
print(f"Live Bot Version on Alias YS2ECNTEXL: {bot_version}")

intents = lex.list_intents(botId=bot_id, botVersion=bot_version, localeId="en_US").get("intentSummaries", [])
target_unavail = next((i for i in intents if i["intentName"] == "TargetUnavailable"), None)
unavail_desc = lex.describe_intent(botId=bot_id, botVersion=bot_version, localeId="en_US", intentId=target_unavail["intentId"])
print("TargetUnavailable Utterance Count:", len(unavail_desc.get("sampleUtterances", [])))
print("TargetUnavailable Sample Utterances:", json.dumps([x["utterance"] for x in unavail_desc.get("sampleUtterances", [])], indent=2))

slots = lex.list_slots(botId=bot_id, botVersion=bot_version, localeId="en_US", intentId=target_unavail["intentId"]).get("slotSummaries", [])
for s in slots:
    slot_desc = lex.describe_slot(botId=bot_id, botVersion=bot_version, localeId="en_US", intentId=target_unavail["intentId"], slotId=s["slotId"])
    print(f"Slot {s['slotName']}: slotTypeId={slot_desc.get('slotTypeId')}, slotConstraint={slot_desc.get('valueElicitationSetting', {}).get('slotConstraint')}")
