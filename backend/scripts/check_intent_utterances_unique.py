import sys
sys.path.insert(0, "backend")

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

builders = {
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

intent_samples = {}
utterance_to_intents = {}

for name, builder in builders.items():
    req = builder(cfg, bot_id)
    samples = [x["utterance"] for x in req.get("sampleUtterances", [])]
    intent_samples[name] = samples
    print(f"Intent {name}: {len(samples)} utterances")
    if len(samples) > 1500:
        print(f"  WARNING: {name} exceeds Lex limit of 1500 ({len(samples)})")
    for u in samples:
        utterance_to_intents.setdefault(u.lower(), []).append(name)

duplicates = {u: intents for u, intents in utterance_to_intents.items() if len(intents) > 1}
if duplicates:
    print(f"\nFOUND {len(duplicates)} DUPLICATE UTTERANCES ACROSS INTENTS:")
    for u, intents in duplicates.items():
        print(f"  '{u}' in: {intents}")
else:
    print("\nALL UTTERANCES ARE UNIQUE ACROSS ALL INTENTS! OK!")
