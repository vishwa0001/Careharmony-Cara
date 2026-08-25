from __future__ import annotations

import json
from typing import Any

from .config import ProjectConfig


def initial_lex_trust_policy(account_id: str) -> dict[str, Any]:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "LexV2ServiceTrust",
                "Effect": "Allow",
                "Principal": {"Service": "lexv2.amazonaws.com"},
                "Action": "sts:AssumeRole",
                "Condition": {"StringEquals": {"aws:SourceAccount": account_id}},
            },
            {
                "Sid": "LexV2InternalTemporaryTrust",
                "Effect": "Allow",
                "Principal": {"Service": "lexv2.aws.internal"},
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {"aws:SourceAccount": account_id},
                    "ArnLike": {"aws:SourceArn": f"arn:aws:lex:*:{account_id}:bot-alias/*/*"},
                },
            },
        ],
    }


def final_lex_trust_policy(account_id: str, bot_id: str) -> dict[str, Any]:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "LexV2ServiceTrust",
                "Effect": "Allow",
                "Principal": {"Service": "lexv2.amazonaws.com"},
                "Action": "sts:AssumeRole",
                "Condition": {"StringEquals": {"aws:SourceAccount": account_id}},
            },
            {
                "Sid": "LexV2InternalTrustPolicy",
                "Effect": "Allow",
                "Principal": {"Service": "lexv2.aws.internal"},
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {"aws:SourceAccount": account_id},
                    "ArnLike": {
                        "aws:SourceArn": f"arn:aws:lex:*:{account_id}:bot-alias/{bot_id}/*"
                    },
                },
            },
        ],
    }


def lex_runtime_permissions(region: str, account_id: str, assistant_id: str, assistant_arn: str, conversation_log_group: str | None = None) -> dict[str, Any]:
    # These are the exact custom-role permissions AWS documents for AMAZON.QInConnectIntent.
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "LexSpeechAndSentiment",
                "Effect": "Allow",
                "Action": ["polly:SynthesizeSpeech", "comprehend:DetectSentiment"],
                "Resource": "*",
            },
            {
                "Sid": "QInConnectAssistantPolicy",
                "Effect": "Allow",
                "Action": ["wisdom:CreateSession", "wisdom:GetAssistant"],
                "Resource": [assistant_arn, f"{assistant_arn}/*"],
            },
            {
                "Sid": "QInConnectSessionsPolicy",
                "Effect": "Allow",
                "Action": ["wisdom:SendMessage", "wisdom:GetNextMessage"],
                "Resource": [f"arn:aws:wisdom:{region}:{account_id}:session/{assistant_id}/*"],
            },
            *([
                {
                    "Sid": "LexConversationTextLogs",
                    "Effect": "Allow",
                    "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
                    "Resource": [
                        f"arn:aws:logs:{region}:{account_id}:log-group:{conversation_log_group}:*"
                    ],
                }
            ] if conversation_log_group else []),
        ],
    }




def standard_lex_trust_policy(account_id: str) -> dict[str, Any]:
    """Trust policy for the small deterministic identity bot."""
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "LexV2ServiceTrust",
                "Effect": "Allow",
                "Principal": {"Service": "lexv2.amazonaws.com"},
                "Action": "sts:AssumeRole",
                "Condition": {"StringEquals": {"aws:SourceAccount": account_id}},
            }
        ],
    }


def identity_lex_runtime_permissions(
    region: str, account_id: str, conversation_log_group: str | None = None
) -> dict[str, Any]:
    statements: list[dict[str, Any]] = [
        {
            "Sid": "IdentityBotSpeech",
            "Effect": "Allow",
            "Action": ["polly:SynthesizeSpeech"],
            "Resource": "*",
        }
    ]
    if conversation_log_group:
        statements.append(
            {
                "Sid": "IdentityBotConversationTextLogs",
                "Effect": "Allow",
                "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
                "Resource": [
                    f"arn:aws:logs:{region}:{account_id}:log-group:{conversation_log_group}:*"
                ],
            }
        )
    return {"Version": "2012-10-17", "Statement": statements}


def identity_lex_bot_create_request(cfg: ProjectConfig, role_arn: str) -> dict[str, Any]:
    return {
        "botName": cfg.identity_bot_name,
        "description": "Deterministic expected-customer identity gate for Cara Health Bot",
        "roleArn": role_arn,
        "dataPrivacy": {"childDirected": False},
        "idleSessionTTLInSeconds": 300,
        "botTags": {"AmazonConnectEnabled": "True", "Project": cfg.project_name},
        "testBotAliasTags": {"AmazonConnectEnabled": "True", "Project": cfg.project_name},
    }


def identity_lex_bot_update_request(
    cfg: ProjectConfig, bot_id: str, role_arn: str
) -> dict[str, Any]:
    create = identity_lex_bot_create_request(cfg, role_arn)
    return {
        "botId": bot_id,
        "botName": create["botName"],
        "description": create["description"],
        "roleArn": role_arn,
        "dataPrivacy": create["dataPrivacy"],
        "idleSessionTTLInSeconds": create["idleSessionTTLInSeconds"],
    }


def identity_lex_locale_request(cfg: ProjectConfig, bot_id: str) -> dict[str, Any]:
    return {
        "botId": bot_id,
        "botVersion": "DRAFT",
        "localeId": cfg.locale,
        "description": "US English identity confirmation gate",
        "nluIntentConfidenceThreshold": cfg.identity_nlu_confidence_threshold,
    }


def _identity_end_conversation() -> dict[str, Any]:
    return {
        "active": False,
        "nextStep": {"dialogAction": {"type": "EndConversation"}},
    }


def identity_confirmed_intent_request(cfg: ProjectConfig, bot_id: str) -> dict[str, Any]:
    # Bare yes/yeah are intentionally *not* here: they are ambiguous in V1.
    samples = [
        "yes this is me",
        "yes I am",
        "yes that's me",
        "yes that is me",
        "this is me",
        "that's me",
        "that is me",
        "speaking",
        "yes speaking",
        "this is John",
        "yes this is John",
        "this is Sarah",
        "yes this is Sarah",
        "you are speaking with me",
        "yeah this is me",
        "yeah that's me", 
        "yes this is him",
        "yes this is her",
        "it's me",
        "yes it's me",
        "yeah it's me",
        "correct this is me",
        "yes you have the right person",
        "this is the right person",
        "yes that's correct",
    ]
    return {
        "intentName": "IdentityConfirmed",
        "description": "Caller clearly confirms they are the expected customer",
        "sampleUtterances": [{"utterance": x} for x in samples],
        "intentClosingSetting": _identity_end_conversation(),
        "botId": bot_id,
        "botVersion": "DRAFT",
        "localeId": cfg.locale,
    }


def identity_named_confirmation_intent_request(
    cfg: ProjectConfig, bot_id: str, *, with_slots: bool = False
) -> dict[str, Any]:
    """Capture an explicitly spoken first + last name for deterministic validation.

    The concrete examples let the intent exist before its built-in name slots are
    created.  The slot-bearing forms are added only after those slots exist.
    """
    if with_slots:
        # Final published intent must use only slot-bearing utterances.
        # Literal full-name examples can win intent matching without filling
        # firstName/lastName, which makes deterministic validation ambiguous.
        samples = [
            "yes this is {firstName} {lastName}",
            "yes I am {firstName} {lastName}",
            "this is {firstName} {lastName}",
            "I am {firstName} {lastName}",
            "{firstName} {lastName} speaking",
            "yes {firstName} {lastName} speaking",
            "you are speaking with {firstName} {lastName}",
        ]
    else:
        # Bootstrap examples used only before the slots have been created.
        samples = [
            "yes this is John Doe",
            "yes I am John Doe",
            "this is John Doe",
            "John Doe speaking",
            "yes this is Sarah Miller",
            "I am Sarah Miller",
            "Sarah Miller speaking",
        ]
    return {
        "intentName": "IdentityNamedConfirmation",
        "description": (
            "Caller states a first and last name. The Connect flow validates the "
            "captured name against expectedCustomerName before confirming identity."
        ),
        "sampleUtterances": [{"utterance": x} for x in samples],
        "intentClosingSetting": _identity_end_conversation(),
        "botId": bot_id,
        "botVersion": "DRAFT",
        "localeId": cfg.locale,
    }


def identity_first_name_slot_request(
    cfg: ProjectConfig, bot_id: str, intent_id: str
) -> dict[str, Any]:
    return {
        "slotName": "firstName",
        "description": "First name spoken by the caller during identity confirmation",
        "slotTypeId": "AMAZON.FirstName",
        "valueElicitationSetting": {"slotConstraint": "Optional"},
        "botId": bot_id,
        "botVersion": "DRAFT",
        "localeId": cfg.locale,
        "intentId": intent_id,
    }


def identity_last_name_slot_request(
    cfg: ProjectConfig, bot_id: str, intent_id: str
) -> dict[str, Any]:
    return {
        "slotName": "lastName",
        "description": "Last name spoken by the caller during identity confirmation",
        "slotTypeId": "AMAZON.LastName",
        "valueElicitationSetting": {"slotConstraint": "Optional"},
        "botId": bot_id,
        "botVersion": "DRAFT",
        "localeId": cfg.locale,
        "intentId": intent_id,
    }


def identity_denied_intent_request(cfg: ProjectConfig, bot_id: str) -> dict[str, Any]:
    samples = [
        "no",
        "no I am not",
        "no this is not me",
        "not me",
        "I am not that person",
        "I am someone else",
        "I am not John",
        "I'm not John",
        "no I am not John",
        "no I'm not John",
        "no this is not John",
        "this is not John",
        "you have the wrong person",
    ]
    return {
        "intentName": "IdentityDenied",
        "description": "Caller says they are not the expected customer without asserting a wrong number",
        "sampleUtterances": [{"utterance": x} for x in samples],
        "intentClosingSetting": _identity_end_conversation(),
        "botId": bot_id,
        "botVersion": "DRAFT",
        "localeId": cfg.locale,
    }


def identity_ambiguous_intent_request(cfg: ProjectConfig, bot_id: str) -> dict[str, Any]:
    samples = [
        "yes",
        "yeah",
        "yep",
        "sure",
        "hello",
        "who is this",
        "who is calling",
        "may I know who I am talking with",
        "may I know whom I am talking with",
        "may I know who I'm talking with",
        "who am I speaking with",
        "can I know who this is",
        "who are you looking for",
        "who are you trying to reach",
        "who did you ask for",
        "why are you calling",
        "what is this about",
        "what do you want",
        "maybe",
        "I don't know",
    ]
    return {
        "intentName": "IdentityAmbiguous",
        "description": "Response does not clearly establish expected-customer identity",
        "sampleUtterances": [{"utterance": x} for x in samples],
        "intentClosingSetting": _identity_end_conversation(),
        "botId": bot_id,
        "botVersion": "DRAFT",
        "localeId": cfg.locale,
    }



def third_party_detected_intent_request(cfg: ProjectConfig, bot_id: str) -> dict[str, Any]:
    samples = [
        "this is his wife",
        "this is her husband",
        "I am his wife",
        "I am her husband",
        "I am his husband",
        "I am her wife",
        "I am his brother",
        "I am her brother",
        "I am his sister",
        "I am her sister",
        "I am his mother",
        "I am her mother",
        "I am his father",
        "I am her father",
        "I am a relative",
        "I am his relative",
        "I am her relative",
        "I am a family member",
        "I am his son",
        "I am her son",
        "I am his daughter",
        "I am her daughter",
        "I am answering for him",
        "I am answering for her",
    ]
    return {
        "intentName": "ThirdPartyDetected",
        "description": "A relative or other third party answered instead of the expected customer",
        "sampleUtterances": [{"utterance": x} for x in samples],
        "intentClosingSetting": _identity_end_conversation(),
        "botId": bot_id,
        "botVersion": "DRAFT",
        "localeId": cfg.locale,
    }


def patient_unavailable_intent_request(cfg: ProjectConfig, bot_id: str) -> dict[str, Any]:
    """The expected person is explicitly unavailable, so skip the redundant availability question."""
    samples = [
        "he is not available",
        "she is not available",
        "they are not available",
        "he's not available",
        "she's not available",
        "he is not here",
        "she is not here",
        "they are not here",
        "he's not here",
        "she's not here",
        "he is away right now",
        "she is away right now",
        "he is at work",
        "she is at work",
        "he is busy right now",
        "she is busy right now",
        "he cannot come to the phone",
        "she cannot come to the phone",
    ]
    return {
        "intentName": "PatientUnavailable",
        "description": (
            "The expected customer is explicitly unavailable. Skip asking whether they are available "
            "again and move directly to the bounded callback-availability conversation."
        ),
        "sampleUtterances": [{"utterance": x} for x in samples],
        "intentClosingSetting": _identity_end_conversation(),
        "botId": bot_id,
        "botVersion": "DRAFT",
        "localeId": cfg.locale,
    }


def wrong_number_intent_request(cfg: ProjectConfig, bot_id: str) -> dict[str, Any]:
    samples = [
        "wrong number",
        "no wrong number",
        "no this is the wrong number",
        "this is the wrong number",
        "it is the wrong number",
        "it's the wrong number",
        "you have the wrong number",
        "you called the wrong number",
        "you reached the wrong number",
        "I am not that person and this is the wrong number",
        "I'm not that person and this is the wrong number",
        "I am not John and this is the wrong number",
        "I'm not John and this is the wrong number",
        "no I am not John this is the wrong number",
        "no I'm not John this is the wrong number",
        "there is no John here",
        "there is nobody here by that name",
        "no one here has that name",
        "you have the wrong person and number",
    ]
    return {
        "intentName": "WrongNumber",
        "description": "Caller clearly indicates the destination or intended person is wrong",
        "sampleUtterances": [{"utterance": x} for x in samples],
        "intentClosingSetting": _identity_end_conversation(),
        "botId": bot_id,
        "botVersion": "DRAFT",
        "localeId": cfg.locale,
    }


def representative_detected_intent_request(cfg: ProjectConfig, bot_id: str) -> dict[str, Any]:
    samples = [
        "I am his caregiver",
        "I am her caregiver",
        "I am the caregiver",
        "I am his representative",
        "I am her representative",
        "I am the representative",
        "I am his authorized representative",
        "I am her authorized representative",
        "I have power of attorney",
        "I am his power of attorney",
        "I am her power of attorney",
    ]
    return {
        "intentName": "RepresentativeDetected",
        "description": "A caregiver or representative answered instead of the expected customer",
        "sampleUtterances": [{"utterance": x} for x in samples],
        "intentClosingSetting": _identity_end_conversation(),
        "botId": bot_id,
        "botVersion": "DRAFT",
        "localeId": cfg.locale,
    }


def call_refusal_intent_request(cfg: ProjectConfig, bot_id: str) -> dict[str, Any]:
    samples = [
        "no thanks",
        "I am not interested",
        "I don't want this",
        "I do not want this",
        "please stop",
        "stop calling me",
        "do not call me",
        "don't call me again",
        "take me off your list",
        "I don't want any calls",
    ]
    return {
        "intentName": "CallRefusal",
        "description": "Caller clearly refuses the call or asks not to be called",
        "sampleUtterances": [{"utterance": x} for x in samples],
        "intentClosingSetting": _identity_end_conversation(),
        "botId": bot_id,
        "botVersion": "DRAFT",
        "localeId": cfg.locale,
    }


def deceased_intent_request(cfg: ProjectConfig, bot_id: str) -> dict[str, Any]:
    samples = [
        "he passed away",
        "she passed away",
        "John passed away",
        "he died",
        "she died",
        "John died",
        "he is deceased",
        "she is deceased",
        "John is deceased",
        "he is no longer with us",
        "she is no longer with us",
    ]
    return {
        "intentName": "Deceased",
        "description": "Caller reports that the expected customer is deceased",
        "sampleUtterances": [{"utterance": x} for x in samples],
        "intentClosingSetting": _identity_end_conversation(),
        "botId": bot_id,
        "botVersion": "DRAFT",
        "localeId": cfg.locale,
    }



def safety_medical_intent_request(cfg: ProjectConfig, bot_id: str) -> dict[str, Any]:
    """Semantic urgent-medical safety intent used anywhere before the Q conversation."""
    samples = [
        "I am having severe trouble breathing",
        "I can barely breathe",
        "I cannot catch my breath",
        "I am having crushing chest pain",
        "I have severe chest pain",
        "the bleeding will not stop",
        "I am bleeding badly",
        "there is uncontrolled bleeding",
        "I passed out and feel very unwell",
        "he is unconscious",
        "she lost consciousness",
        "I am having a severe allergic reaction",
        "my throat is swelling and I cannot breathe well",
        "I suddenly feel weak on one side",
        "I suddenly have numbness on one side",
        "I am suddenly very confused",
        "he is suddenly confused and weak",
        "I have a serious injury",
        "I am in unbearable pain",
        "the pain is severe and unbearable",
        "my blood pressure is dangerously high",
        "my blood pressure is dangerously low and I feel faint",
        "my blood sugar is dangerously low",
        "my blood sugar is extremely high and I feel very sick",
        "I think I overdosed",
        "someone here may have overdosed",
        "I am having a seizure emergency",
        "I am not interested because I have crushing chest pain",
        "I do not want this and I cannot breathe",
        "no thanks I am bleeding badly",
        "I am busy but I am having trouble breathing",
        "call me later my blood sugar is dangerously low",
        "stop calling me I am having severe chest pain",
        "wrong number but someone here is unconscious",
        "he is not available because he is having severe chest pain",
        "she cannot come to the phone because she is having trouble breathing",
        "he is not here because he had a serious injury",
    ]
    return {
        "intentName": "SafetyMedical",
        "description": (
            "Possible urgent physical or medical safety situation. This intent overrides ordinary identity, "
            "availability, objection, refusal, callback, and transfer meanings."
        ),
        "sampleUtterances": [{"utterance": x} for x in samples],
        "intentClosingSetting": _identity_end_conversation(),
        "botId": bot_id,
        "botVersion": "DRAFT",
        "localeId": cfg.locale,
    }


def safety_behavioral_intent_request(cfg: ProjectConfig, bot_id: str) -> dict[str, Any]:
    """Semantic behavioral/personal-safety crisis intent used before the Q conversation."""
    samples = [
        "I am thinking about suicide",
        "I have been thinking about killing myself",
        "I want to die",
        "I do not want to live anymore",
        "I want to hurt myself",
        "I might hurt myself",
        "I am afraid I will hurt myself",
        "I want to hurt someone",
        "I am afraid I might hurt someone",
        "I do not feel safe right now",
        "I am in immediate danger",
        "someone is threatening me",
        "someone is hurting me",
        "I am being abused",
        "I do not feel safe at home",
        "my partner is threatening me",
        "I am having a mental health crisis",
        "I am in a behavioral health crisis",
        "I am having a substance use crisis",
        "I feel completely unsafe",
        "he is talking about killing himself",
        "she says she wants to die",
        "he may hurt himself",
        "she may hurt someone",
        "they are in immediate danger",
        "I am not interested because I have been thinking about killing myself",
        "I do not want this I want to die",
        "no thanks I might hurt myself",
        "I am busy but I do not feel safe",
        "call me later I am in immediate danger",
        "stop calling me someone is hurting me",
        "wrong number but I am in immediate danger",
        "he is not available because he is having a mental health crisis",
        "she cannot come to the phone because she says she wants to die",
    ]
    return {
        "intentName": "SafetyBehavioral",
        "description": (
            "Possible suicidal, self-harm, harm-to-others, abuse, mental-health, substance-use, or immediate "
            "personal-safety crisis. This intent overrides ordinary identity, availability, objection, refusal, "
            "callback, and transfer meanings."
        ),
        "sampleUtterances": [{"utterance": x} for x in samples],
        "intentClosingSetting": _identity_end_conversation(),
        "botId": bot_id,
        "botVersion": "DRAFT",
        "localeId": cfg.locale,
    }


def availability_lex_bot_create_request(cfg: ProjectConfig, role_arn: str) -> dict[str, Any]:
    return {
        "botName": cfg.availability_bot_name,
        "description": "Privacy-minimal third-party availability bot for Cara Health Bot",
        "roleArn": role_arn,
        "dataPrivacy": {"childDirected": False},
        "idleSessionTTLInSeconds": 300,
        "botTags": {"AmazonConnectEnabled": "True", "Project": cfg.project_name},
        "testBotAliasTags": {"AmazonConnectEnabled": "True", "Project": cfg.project_name},
    }


def availability_lex_bot_update_request(
    cfg: ProjectConfig, bot_id: str, role_arn: str
) -> dict[str, Any]:
    create = availability_lex_bot_create_request(cfg, role_arn)
    return {
        "botId": bot_id,
        "botName": create["botName"],
        "description": create["description"],
        "roleArn": role_arn,
        "dataPrivacy": create["dataPrivacy"],
        "idleSessionTTLInSeconds": create["idleSessionTTLInSeconds"],
    }


def availability_lex_locale_request(cfg: ProjectConfig, bot_id: str) -> dict[str, Any]:
    return {
        "botId": bot_id,
        "botVersion": "DRAFT",
        "localeId": cfg.locale,
        "description": "US English third-party availability conversation",
        "nluIntentConfidenceThreshold": 0.50,
    }


def availability_now_intent_request(cfg: ProjectConfig, bot_id: str) -> dict[str, Any]:
    samples = [
        "yes",
        "yes he is here",
        "yes she is here",
        "yes they are here",
        "he is here",
        "she is here",
        "they are here",
        "he's here",
        "she's here",
        "one moment",
        "hold on",
        "I can get him",
        "I can get her",
        "I can pass the phone",
        "let me get him",
        "let me get her",
        "I will put him on",
        "I will put her on",
    ]
    return {
        "intentName": "TargetAvailableNow",
        "description": "The expected customer is available to come to the phone now",
        "sampleUtterances": [{"utterance": x} for x in samples],
        "intentClosingSetting": _identity_end_conversation(),
        "botId": bot_id,
        "botVersion": "DRAFT",
        "localeId": cfg.locale,
    }


def availability_unavailable_intent_request(
    cfg: ProjectConfig, bot_id: str, *, slot_priorities: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    samples = [
        "no",
        "not right now",
        "not available",
        "he is not available",
        "she is not available",
        "they are not available",
        "he is not here",
        "she is not here",
        "they are not here",
        "he's at work",
        "she's at work",
        "he is at work",
        "she is at work",
        "he will be back later",
        "she will be back later",
        "try again later",
        "call back later",
        "he is busy",
        "she is busy",
    ]
    # Slot-bearing samples are added only after the slots exist in DRAFT.
    if slot_priorities is not None:
        samples += [
            "{callbackDate}",
            "{callbackTime}",
            "{callbackDate} {callbackTime}",
            "try {callbackDate}",
            "call back {callbackDate}",
            "try at {callbackTime}",
            "call back at {callbackTime}",
            "try {callbackDate} at {callbackTime}",
            "call back {callbackDate} at {callbackTime}",
            "he will be available {callbackDate}",
            "she will be available {callbackDate}",
            "they will be available {callbackDate}",
            "he will be available {callbackDate} at {callbackTime}",
            "she will be available {callbackDate} at {callbackTime}",
            "they will be available {callbackDate} at {callbackTime}",
            "he will be available at {callbackTime}",
            "she will be available at {callbackTime}",
            "they will be available at {callbackTime}",
        ]
    request: dict[str, Any] = {
        "intentName": "TargetUnavailable",
        "description": "The expected customer is unavailable; collect a better callback day and time",
        "sampleUtterances": [{"utterance": x} for x in samples],
        "intentClosingSetting": _identity_end_conversation(),
        "botId": bot_id,
        "botVersion": "DRAFT",
        "localeId": cfg.locale,
    }
    if slot_priorities is not None:
        request["slotPriorities"] = slot_priorities
    return request


def availability_unknown_intent_request(cfg: ProjectConfig, bot_id: str) -> dict[str, Any]:
    samples = [
        "I don't know",
        "I am not sure",
        "not sure",
        "maybe",
        "I don't know when",
        "I cannot say",
        "no idea",
        "I don't know their schedule",
    ]
    return {
        "intentName": "AvailabilityUnknown",
        "description": "The third party cannot provide useful availability information",
        "sampleUtterances": [{"utterance": x} for x in samples],
        "intentClosingSetting": _identity_end_conversation(),
        "botId": bot_id,
        "botVersion": "DRAFT",
        "localeId": cfg.locale,
    }


def availability_fallback_intent_request(cfg: ProjectConfig, bot_id: str) -> dict[str, Any]:
    return {
        "intentName": "FallbackIntent",
        "description": "Unknown availability response",
        "parentIntentSignature": "AMAZON.FallbackIntent",
        "botId": bot_id,
        "botVersion": "DRAFT",
        "localeId": cfg.locale,
    }


def availability_callback_date_slot_request(
    cfg: ProjectConfig, bot_id: str, intent_id: str
) -> dict[str, Any]:
    return {
        "slotName": "callbackDate",
        "description": "Better date to reach the expected customer",
        "slotTypeId": "AMAZON.Date",
        "valueElicitationSetting": {
            "slotConstraint": "Required",
            "promptSpecification": {
                "messageGroups": [{
                    "message": {"plainTextMessage": {"value": "What day would be better to reach them?"}}
                }],
                "maxRetries": 2,
                "allowInterrupt": True,
            },
        },
        "botId": bot_id,
        "botVersion": "DRAFT",
        "localeId": cfg.locale,
        "intentId": intent_id,
    }


def availability_callback_time_slot_request(
    cfg: ProjectConfig, bot_id: str, intent_id: str
) -> dict[str, Any]:
    return {
        "slotName": "callbackTime",
        "description": "Better time to reach the expected customer",
        "slotTypeId": "AMAZON.Time",
        "valueElicitationSetting": {
            "slotConstraint": "Required",
            "promptSpecification": {
                "messageGroups": [{
                    "message": {"plainTextMessage": {"value": "What time would be better to reach them? For example, 10 AM or 2 PM."}}
                }],
                "maxRetries": 2,
                "allowInterrupt": True,
            },
        },
        "botId": bot_id,
        "botVersion": "DRAFT",
        "localeId": cfg.locale,
        "intentId": intent_id,
    }


def availability_lex_alias_request(
    cfg: ProjectConfig,
    bot_id: str,
    bot_version: str,
    conversation_log_group_arn: str | None = None,
) -> dict[str, Any]:
    request: dict[str, Any] = {
        "botAliasName": cfg.availability_bot_alias_name,
        "description": "Published third-party availability bot used by Amazon Connect",
        "botVersion": bot_version,
        "botAliasLocaleSettings": {cfg.locale: {"enabled": True}},
        "sentimentAnalysisSettings": {"detectSentiment": False},
        "botId": bot_id,
    }
    if conversation_log_group_arn:
        request["conversationLogSettings"] = {
            "textLogSettings": [
                {
                    "enabled": True,
                    "destination": {
                        "cloudWatch": {
                            "cloudWatchLogGroupArn": conversation_log_group_arn,
                            "logPrefix": "cara-health-bot-availability",
                        }
                    },
                }
            ]
        }
    return request

def identity_fallback_intent_request(cfg: ProjectConfig, bot_id: str) -> dict[str, Any]:
    return {
        "intentName": "FallbackIntent",
        "description": "Unknown identity response",
        "parentIntentSignature": "AMAZON.FallbackIntent",
        "botId": bot_id,
        "botVersion": "DRAFT",
        "localeId": cfg.locale,
    }


def identity_lex_alias_request(
    cfg: ProjectConfig,
    bot_id: str,
    bot_version: str,
    conversation_log_group_arn: str | None = None,
) -> dict[str, Any]:
    request: dict[str, Any] = {
        "botAliasName": cfg.identity_bot_alias_name,
        "description": "Published deterministic identity gate used by Amazon Connect",
        "botVersion": bot_version,
        "botAliasLocaleSettings": {cfg.locale: {"enabled": True}},
        "sentimentAnalysisSettings": {"detectSentiment": False},
        "botId": bot_id,
    }
    if conversation_log_group_arn:
        request["conversationLogSettings"] = {
            "textLogSettings": [
                {
                    "enabled": True,
                    "selectiveLoggingEnabled": False,
                    "destination": {
                        "cloudWatch": {
                            "cloudWatchLogGroupArn": conversation_log_group_arn,
                            "logPrefix": "cara-health-bot-identity",
                        }
                    },
                }
            ]
        }
    return request


def lambda_trust_policy() -> dict[str, Any]:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "LambdaServiceTrust",
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }


def session_context_lambda_permissions(
    region: str, account_id: str, assistant_id: str, function_name: str
) -> dict[str, Any]:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "CreateLambdaLogGroup",
                "Effect": "Allow",
                "Action": ["logs:CreateLogGroup"],
                "Resource": "*",
            },
            {
                "Sid": "WriteLambdaLogs",
                "Effect": "Allow",
                "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
                "Resource": [
                    f"arn:aws:logs:{region}:{account_id}:log-group:/aws/lambda/{function_name}:*"
                ],
            },
            {
                "Sid": "WriteCaraHealthBotSessionContext",
                "Effect": "Allow",
                "Action": ["wisdom:UpdateSessionData"],
                "Resource": [
                    f"arn:aws:wisdom:{region}:{account_id}:session/{assistant_id}/*"
                ],
            },
        ],
    }


def render_cara_prompt(cfg: ProjectConfig, template: str) -> str:
    """Inject conversation-only configuration into the existing Q prompt template."""
    behavior_json = json.dumps(
        cfg.cara_behavior,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    rendered = template.replace("${CaraBehaviorConfig}", behavior_json)
    if "${CaraBehaviorConfig}" in rendered:
        raise ValueError("unresolved Cara behavior configuration placeholder")
    return rendered


def cara_return_to_control_tools() -> list[dict[str, Any]]:
    """Conversation outcomes; the existing Connect flow performs the actual actions."""
    return [
        {
            "toolName": "EscalateToHuman",
            "toolType": "RETURN_TO_CONTROL",
            "description": "Return control when the confirmed customer is ready for a human specialist.",
            "instruction": {
                "instruction": (
                    "Use only when the confirmed customer agrees to, asks for, or is clearly ready for "
                    "a human specialist and there is no safety concern. If Cara just offered a specialist "
                    "or asked whether now is a good time and the caller answers affirmatively, invoke this "
                    "tool immediately in that same turn. Saying that you will connect the caller without "
                    "invoking this tool does not perform the transfer. Safety always overrides transfer. "
                    "Do not invoke after a clear refusal or callback request."
                ),
                "examples": [
                    "Cara: Is now a good time? Caller: Yes, it is a good time to connect. -> invoke EscalateToHuman",
                    "Cara: Would you like me to connect you with a specialist? Caller: Yes, please. -> invoke EscalateToHuman",
                    "Caller: Please connect me to a human specialist. -> invoke EscalateToHuman",
                ],
            },
            "inputSchema": {
                "type": "object",
                "properties": {
                    "conversationSummary": {
                        "type": "string",
                        "description": "Brief neutral summary for the human specialist; do not invent facts.",
                        "maxLength": 500,
                    },
                    "customerIntent": {
                        "type": "string",
                        "description": "Brief phrase describing what the customer wants or asked about.",
                        "maxLength": 120,
                    },
                },
            },
        },
        {
            "toolName": "RequestCallback",
            "toolType": "RETURN_TO_CONTROL",
            "description": "Return control when the confirmed customer wants to be called later.",
            "instruction": {
                "instruction": (
                    "Use when the customer says they are busy, says now is not a good time, asks to be called later, "
                    "or gives a preferred callback time and there is no safety concern. If Cara just asked whether now "
                    "is a good time, a negative answer means unavailable now, not refusal. If the same turn contains a "
                    "request to call later or future timing, invoke RequestCallback immediately in that same turn. "
                    "For example, 'No, it is not a good time right now. Can you call me tomorrow at 10 AM?' MUST invoke "
                    "RequestCallback with callbackWhen='tomorrow at 10 AM'. Do not use EndConversation or endReason=other "
                    "for a busy/not-good-time/call-later response. Safety and an explicit do-not-call request override "
                    "callback. Never invent a date or time. Before invoking, verbally acknowledge any specific time the "
                    "customer actually provided."
                ),
                "examples": [
                    "Cara: Is now a good time? Caller: No, call me tomorrow at 10 AM. -> invoke RequestCallback with callbackWhen tomorrow at 10 AM",
                    "Cara: Is now a good time? Caller: Not right now, call me later. -> invoke RequestCallback",
                    "Caller: I'm busy, try me tomorrow morning. -> invoke RequestCallback",
                ],
            },
            "inputSchema": {
                "type": "object",
                "properties": {
                    "callbackWhen": {
                        "type": "string",
                        "description": "Customer's requested callback timing in their own meaning; empty if none was provided.",
                        "maxLength": 160,
                    },
                    "callbackReason": {
                        "type": "string",
                        "description": "Short neutral reason such as busy or not a good time.",
                        "maxLength": 120,
                    },
                },
                "required": ["callbackWhen", "callbackReason"],
            },
        },
        {
            "toolName": "EndConversation",
            "toolType": "RETURN_TO_CONTROL",
            "description": "Return control when the call should end without transfer.",
            "instruction": {
                "instruction": (
                    "Use after a clear refusal, do-not-call request, safety situation, or when continuing would be "
                    "inappropriate. Do NOT use EndConversation for busy, not-right-now, not-a-good-time, call-later, "
                    "or another callback request. A sentence can begin with 'no' and still be a callback request when "
                    "the 'no' answers whether now is a good time. Never use endReason other as a substitute for "
                    "RequestCallback. Safety has the highest priority over every other intent. For urgent physical/medical "
                    "safety use endReason safety_medical. For suicidal, self-harm, harm-to-others, abuse, mental-health, "
                    "behavioral/substance-use, or immediate personal-safety crisis use safety_behavioral."
                )
            },
            "inputSchema": {
                "type": "object",
                "properties": {
                    "endReason": {
                        "type": "string",
                        "enum": ["refusal", "do_not_call", "safety_medical", "safety_behavioral", "unknown_question", "other"],
                        "description": "Why the conversation is ending.",
                    }
                },
                "required": ["endReason"],
            },
        },
    ]


def q_prompt_create_request(cfg: ProjectConfig, assistant_id: str, content: str) -> dict[str, Any]:
    content = render_cara_prompt(cfg, content)
    return {
        "assistantId": assistant_id,
        "name": cfg.prompt_name,
        "type": "ORCHESTRATION",
        "description": "Orchestration prompt for the Cara Health Bot life coach",
        "templateType": "TEXT",
        "templateConfiguration": {"textFullAIPromptEditTemplateConfiguration": {"text": content}},
        "modelId": cfg.orchestration_model_id,
        "apiFormat": "MESSAGES",
        "visibilityStatus": "PUBLISHED",
        "tags": {"Project": cfg.project_name, "Purpose": "LifeCoachVoiceDemo"},
    }


def q_prompt_update_request(cfg: ProjectConfig, assistant_id: str, prompt_id: str, content: str) -> dict[str, Any]:
    create = q_prompt_create_request(cfg, assistant_id, content)
    return {
        "assistantId": assistant_id,
        "aiPromptId": prompt_id,
        "description": create["description"],
        "templateConfiguration": create["templateConfiguration"],
        "modelId": create["modelId"],
        "visibilityStatus": create["visibilityStatus"],
    }


def q_agent_configuration(cfg: ProjectConfig, connect_instance_arn: str, prompt_version_id: str) -> dict[str, Any]:
    # The existing Q/Nova conversation layer provides semantic Cara behavior.
    # Return-to-Control tools only signal the three already-supported outcomes:
    # transfer, callback, or end. They do not provision or replace infrastructure.
    return {
        "orchestrationAIAgentConfiguration": {
            "orchestrationAIPromptId": prompt_version_id,
            "connectInstanceArn": connect_instance_arn,
            "locale": cfg.locale,
            "toolConfigurations": cara_return_to_control_tools(),
        }
    }


def q_agent_create_request(cfg: ProjectConfig, assistant_id: str, connect_instance_arn: str, prompt_version_id: str) -> dict[str, Any]:
    return {
        "assistantId": assistant_id,
        "name": cfg.agent_name,
        "type": "ORCHESTRATION",
        "description": "Continuous conversational life-coach orchestrator for Cara Health Bot",
        "configuration": q_agent_configuration(cfg, connect_instance_arn, prompt_version_id),
        "visibilityStatus": "PUBLISHED",
        "tags": {"Project": cfg.project_name, "Purpose": "LifeCoachVoiceDemo"},
    }


def q_agent_update_request(cfg: ProjectConfig, assistant_id: str, connect_instance_arn: str, agent_id: str, prompt_version_id: str) -> dict[str, Any]:
    create = q_agent_create_request(cfg, assistant_id, connect_instance_arn, prompt_version_id)
    return {
        "assistantId": assistant_id,
        "aiAgentId": agent_id,
        "description": create["description"],
        "configuration": create["configuration"],
        "visibilityStatus": create["visibilityStatus"],
    }


def lex_bot_create_request(cfg: ProjectConfig, role_arn: str) -> dict[str, Any]:
    return {
        "botName": cfg.bot_name,
        "description": "Cara Health Bot realtime voice bot using Amazon Nova 2 Sonic and Amazon Q in Connect",
        "roleArn": role_arn,
        "dataPrivacy": {"childDirected": False},
        "idleSessionTTLInSeconds": 86400,
        "botTags": {"AmazonConnectEnabled": "True", "Project": cfg.project_name},
        "testBotAliasTags": {"AmazonConnectEnabled": "True", "Project": cfg.project_name},
    }


def lex_bot_update_request(cfg: ProjectConfig, bot_id: str, role_arn: str) -> dict[str, Any]:
    create = lex_bot_create_request(cfg, role_arn)
    return {
        "botId": bot_id,
        "botName": create["botName"],
        "description": create["description"],
        "roleArn": role_arn,
        "dataPrivacy": create["dataPrivacy"],
        "idleSessionTTLInSeconds": create["idleSessionTTLInSeconds"],
    }


def lex_locale_request(cfg: ProjectConfig, bot_id: str) -> dict[str, Any]:
    return {
        "botId": bot_id,
        "botVersion": "DRAFT",
        "localeId": cfg.locale,
        "description": "US English realtime Cara Health Bot conversation",
        "nluIntentConfidenceThreshold": 0.40,
        "unifiedSpeechSettings": {
            "speechFoundationModel": {
                "modelArn": f"arn:aws:bedrock:{cfg.region}::foundation-model/{cfg.speech_model_id}"
            }
        },
    }


def lex_qinconnect_intent_request(cfg: ProjectConfig, bot_id: str, assistant_arn: str) -> dict[str, Any]:
    return {
        "intentName": "AmazonQinConnect",
        "description": "Routes free-form voice conversation to the Cara Health Bot Q assistant",
        "parentIntentSignature": "AMAZON.QInConnectIntent",
        "fulfillmentCodeHook": {
            "enabled": False,
            "active": True,
            "postFulfillmentStatusSpecification": {
                "successResponse": {
                    "messageGroups": [
                        {
                            "message": {
                                "plainTextMessage": {"value": "((x-amz-lex:q-in-connect-response))"}
                            }
                        }
                    ],
                    "allowInterrupt": True,
                },
                "successNextStep": {"dialogAction": {"type": "EndConversation"}},
                "failureNextStep": {"dialogAction": {"type": "EndConversation"}},
                "timeoutNextStep": {"dialogAction": {"type": "EndConversation"}},
            },
        },
        "botId": bot_id,
        "botVersion": "DRAFT",
        "localeId": cfg.locale,
        "qInConnectIntentConfiguration": {
            "qInConnectAssistantConfiguration": {"assistantArn": assistant_arn}
        },
    }


def lex_fallback_intent_request(cfg: ProjectConfig, bot_id: str) -> dict[str, Any]:
    return {
        "intentName": "FallbackIntent",
        "description": "Default fallback intent",
        "parentIntentSignature": "AMAZON.FallbackIntent",
        "botId": bot_id,
        "botVersion": "DRAFT",
        "localeId": cfg.locale,
    }


def lex_alias_request(
    cfg: ProjectConfig,
    bot_id: str,
    bot_version: str,
    conversation_log_group_arn: str | None = None,
) -> dict[str, Any]:
    request: dict[str, Any] = {
        "botAliasName": cfg.bot_alias_name,
        "description": "Published Cara Health Bot alias used by Amazon Connect",
        "botVersion": bot_version,
        "botAliasLocaleSettings": {cfg.locale: {"enabled": True}},
        "sentimentAnalysisSettings": {"detectSentiment": False},
        "botId": bot_id,
    }
    if conversation_log_group_arn:
        request["conversationLogSettings"] = {
            "textLogSettings": [
                {
                    "enabled": True,
                    "selectiveLoggingEnabled": False,
                    "destination": {
                        "cloudWatch": {
                            "cloudWatchLogGroupArn": conversation_log_group_arn,
                            "logPrefix": "cara-health-bot",
                        }
                    },
                }
            ]
        }
    return request


def lex_alias_resource_policy(account_id: str, connect_instance_arn: str, alias_arn: str) -> dict[str, Any]:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowCaraHealthBotConnectInvoke",
                "Effect": "Allow",
                "Principal": {"Service": "connect.amazonaws.com"},
                "Action": ["lex:RecognizeText", "lex:RecognizeUtterance", "lex:StartConversation"],
                "Resource": alias_arn,
                "Condition": {
                    "StringEquals": {"AWS:SourceAccount": account_id},
                    "ArnEquals": {"AWS:SourceArn": connect_instance_arn},
                },
            }
        ],
    }


def render_contact_flow(
    cfg: ProjectConfig,
    assistant_id: str,
    assistant_arn: str,
    lex_alias_arn: str,
    identity_lex_alias_arn: str,
    availability_lex_alias_arn: str,
    session_context_lambda_arn: str,
    human_transfer_queue_arn: str,
) -> str:
    text = cfg.flow_path.read_text(encoding="utf-8")
    replacements = {
        "${VoiceId}": cfg.voice_id,
        "${WisdomAssistantId}": assistant_id,
        "${WisdomAssistantArn}": assistant_arn,
        "${LexBotAliasArn}": lex_alias_arn,
        "${IdentityLexBotAliasArn}": identity_lex_alias_arn,
        "${AvailabilityLexBotAliasArn}": availability_lex_alias_arn,
        "${SessionContextLambdaArn}": session_context_lambda_arn,
        "${FallbackMessage}": cfg.cara_behavior["fallbackMessage"],
        "${HumanTransferQueueArn}": human_transfer_queue_arn,
        "${IdentitySuccessTransferMessage}": cfg.cara_behavior["transferMessage"],
        "${CaraCallbackEndMessage}": cfg.cara_behavior["callbackResponses"]["endMessage"],
        "${CaraRespectfulClosingMessage}": cfg.cara_behavior["respectfulClosingMessage"],
        "${CaraSafetyMedicalResponse}": cfg.cara_behavior["safetyMedicalResponse"],
        "${CaraSafetyBehavioralResponse}": cfg.cara_behavior["safetyBehavioralResponse"],
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    unresolved = [key for key in replacements if key in text]
    if unresolved:
        raise ValueError(f"unresolved contact-flow placeholders: {unresolved}")
    parsed = json.loads(text)
    return json.dumps(parsed, separators=(",", ":"))
