import boto3
import json

session = boto3.Session(profile_name="careharmony-main", region_name="us-east-1")
lex = session.client("lexv2-models")

bot_id = "4M8I8HGPND"
alias_id = "KJZH9WFPLC"

alias = lex.describe_bot_alias(botId=bot_id, botAliasId=alias_id)
bot_version = alias["botVersion"]
print(f"Live Identity Bot Version on Alias KJZH9WFPLC: {bot_version}")

intents = lex.list_intents(botId=bot_id, botVersion=bot_version, localeId="en_US").get("intentSummaries", [])
print(f"Intents ({len(intents)}):")
for i in intents:
    intent_id = i["intentId"]
    intent_name = i["intentName"]
    desc = lex.describe_intent(botId=bot_id, botVersion=bot_version, localeId="en_US", intentId=intent_id)
    utterances = [u["utterance"] for u in desc.get("sampleUtterances", [])]
    print(f"\n--- Intent: {intent_name} (ID: {intent_id}, Utterances: {len(utterances)}) ---")
    print(f"Sample (first 5): {utterances[:5]}")

