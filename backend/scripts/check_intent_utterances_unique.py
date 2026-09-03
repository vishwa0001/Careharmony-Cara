from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cara_health_bot.config import load_config
from cara_health_bot.builders import (
    identity_confirmed_intent_request,
    identity_named_confirmation_intent_request,
    identity_denied_intent_request,
    identity_ambiguous_intent_request,
    third_party_detected_intent_request,
    patient_unavailable_intent_request,
    wrong_number_intent_request,
    representative_detected_intent_request,
    deceased_intent_request,
    call_refusal_intent_request,
    safety_medical_intent_request,
    safety_behavioral_intent_request,
)

cfg = load_config()
bot_id = "test-bot"

# 1. Identity Bot Intents
identity_bot_builders = {
    "IdentityConfirmed": identity_confirmed_intent_request,
    "IdentityNamedConfirmation": lambda c, b: identity_named_confirmation_intent_request(c, b, with_slots=True),
    "IdentityDenied": identity_denied_intent_request,
    "IdentityAmbiguous": identity_ambiguous_intent_request,
    "ThirdPartyDetected": third_party_detected_intent_request,
    "PatientUnavailable": patient_unavailable_intent_request,
    "WrongNumber": wrong_number_intent_request,
    "RepresentativeDetected": representative_detected_intent_request,
    "Deceased": deceased_intent_request,
    "CallRefusal": call_refusal_intent_request,
    "SafetyMedical": safety_medical_intent_request,
    "SafetyBehavioral": safety_behavioral_intent_request,
}

# 2. Coaching Bot Intents
coaching_bot_builders = {
    "SafetyMedical": safety_medical_intent_request,
    "SafetyBehavioral": safety_behavioral_intent_request,
}

bots = {
    "Identity Bot (4M8I8HGPND)": identity_bot_builders,
    "Coaching Bot (4S3WG7D9ZQ)": coaching_bot_builders,
}

all_passed = True

for bot_name, builders in bots.items():
    print(f"\n==================== {bot_name} ====================")
    utterance_to_intents = {}
    for name, builder in builders.items():
        req = builder(cfg, bot_id)
        samples = [x["utterance"] for x in req.get("sampleUtterances", [])]
        print(f"Intent {name}: {len(samples)} utterances")
        if len(samples) > 1500:
            print(f"  WARNING: {name} exceeds Lex limit of 1500 ({len(samples)})")
        for u in samples:
            utterance_to_intents.setdefault(u.lower().strip(), []).append(name)

    duplicates = {u: intents for u, intents in utterance_to_intents.items() if len(intents) > 1}
    if duplicates:
        all_passed = False
        print(f"FOUND {len(duplicates)} DUPLICATE UTTERANCES ACROSS INTENTS IN {bot_name}:")
        for u, intents in duplicates.items():
            print(f"  '{u}' in: {intents}")
    else:
        print(f"ALL UTTERANCES ARE UNIQUE ACROSS ALL INTENTS IN {bot_name}! OK!")

if all_passed:
    print("\nOVERALL STATUS: ZERO INTENT COLLISIONS ACROSS ALL BOTS!")
else:
    print("\nOVERALL STATUS: COLLISIONS DETECTED")

