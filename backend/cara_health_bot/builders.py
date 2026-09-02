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
    samples = [
        # Direct affirmations with name
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
        # Expanded affirmations - simple
        "yes it is me",
        "yes it's me",
        "yep it's me",
        "yep that's me",
        "yep this is me",
        "correct that is me",
        "correct this is me",
        "that would be me",
        "this would be me",
        "yes I am the one",
        "yes that is correct",
        "yes that's correct",
        "affirmative",
        "yes sir that is me",
        "yes ma'am that is me",
        "you got me",
        "you've reached me",
        "you have reached me",
        "I am here",
        "present",
        "yes I am here",
        "this is the right person",
        "you have the right person",
        "you reached the right person",
        "I am the right person",
        "yes you have the right person",
        "that's definitely me",
        "that is definitely me",
        "yes definitely me",
        "yes absolutely that's me",
        "absolutely this is me",
        "certainly this is me",
        "of course this is me",
        "of course that's me",
        # With first name variants
        "this is John speaking",
        "this is Sarah speaking",
        "yes this is John speaking",
        "yes this is Sarah speaking",
        "John here",
        "Sarah here",
        "yes John speaking",
        "yes Sarah speaking",
        "it's John",
        "it is John",
        "it's Sarah",
        "it is Sarah",
        "yes it's John",
        "yes it is John",
        "yes it's Sarah",
        "yes it is Sarah",
        "John speaking",
        "Sarah speaking",
        "you are speaking with John",
        "you are speaking with Sarah",
        "you have reached John",
        "you have reached Sarah",
        "you've reached John",
        "you've reached Sarah",
        "you got John",
        "you got Sarah",
        # Informal / colloquial
        "yeah that's me",
        "yeah this is me",
        "yeah it's me",
        "yeah speaking",
        "yeah you got me",
        "yeah I am",
        "yep speaking",
        "yep that is me",
        "uh huh this is me",
        "uh huh that's me",
        "mm hmm this is me",
        "mm hmm speaking",
        "sure thing this is me",
        "sure that's me",
        "right this is me",
        "right that is me",
        "correct I am",
        "exactly this is me",
        "exactly that is me",
        "indeed this is me",
        "indeed speaking",
        # Contextual confirmations
        "hi yes this is me",
        "hello yes this is me",
        "hello this is me",
        "hi this is me",
        "hi this is John",
        "hello this is John",
        "hi this is Sarah",
        "hello this is Sarah",
        "hey yes that's me",
        "hey this is me",
        "good morning this is me",
        "good afternoon this is me",
        "yes I am the person you are looking for",
        "yes I am who you are calling",
        "yes I am who you are looking for",
        "yes I am the one you called",
        "yes that is my name",
        "yes that's my name",
        "yes that is my name you called",
        "yes I go by that name",
        # Slight hesitation but still confirming
        "I think that's me",
        "I believe that's me",
        "I believe this is me",
        "I believe so yes",
        "I think so yes",
        "I think that is me yes",
        "as far as I know that is me",
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
    if with_slots:
        samples = [
            "yes this is {firstName} {lastName}",
            "yes I am {firstName} {lastName}",
            "this is {firstName} {lastName}",
            "I am {firstName} {lastName}",
            "{firstName} {lastName} speaking",
            "yes {firstName} {lastName} speaking",
            "you are speaking with {firstName} {lastName}",
            # Expanded slot-bearing
            "yes it is {firstName} {lastName}",
            "it is {firstName} {lastName}",
            "it's {firstName} {lastName}",
            "yes it's {firstName} {lastName}",
            "hi this is {firstName} {lastName}",
            "hello this is {firstName} {lastName}",
            "hi yes this is {firstName} {lastName}",
            "hello yes this is {firstName} {lastName}",
            "yep this is {firstName} {lastName}",
            "yep {firstName} {lastName} speaking",
            "yeah this is {firstName} {lastName}",
            "yeah {firstName} {lastName}",
            "correct this is {firstName} {lastName}",
            "that is correct I am {firstName} {lastName}",
            "my name is {firstName} {lastName}",
            "yes my name is {firstName} {lastName}",
            "you have reached {firstName} {lastName}",
            "you are speaking to {firstName} {lastName}",
            "this is {firstName} {lastName} speaking",
            "yes this is {firstName} {lastName} speaking",
            "{firstName} {lastName} here",
            "yes {firstName} {lastName} here",
            "speaking this is {firstName} {lastName}",
        ]
    else:
        samples = [
            "yes this is John Doe",
            "yes I am John Doe",
            "this is John Doe",
            "John Doe speaking",
            "yes this is Sarah Miller",
            "I am Sarah Miller",
            "Sarah Miller speaking",
            # Expanded bootstrap examples
            "yes this is Michael Smith",
            "this is Emily Johnson",
            "yes I am Robert Brown",
            "David Wilson speaking",
            "yes this is Jennifer Davis",
            "it is John Doe",
            "it's John Doe",
            "yes it is John Doe",
            "yes it's John Doe",
            "hi this is John Doe",
            "hello this is John Doe",
            "hi yes this is Sarah Miller",
            "hello yes this is Sarah Miller",
            "yep this is John Doe",
            "yeah this is John Doe",
            "correct this is John Doe",
            "my name is John Doe",
            "yes my name is John Doe",
            "you have reached John Doe",
            "you are speaking with John Doe",
            "you are speaking to John Doe",
            "this is John Doe speaking",
            "yes this is John Doe speaking",
            "John Doe here",
            "yes John Doe here",
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
        # Original
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
        # Expanded - simple negations
        "nope",
        "nope not me",
        "nope this is not me",
        "no that is not me",
        "no that's not me",
        "that is not me",
        "that's not me",
        "this is not me",
        "this isn't me",
        "no this isn't me",
        "no that isn't me",
        "not the right person",
        "I am not the right person",
        "I'm not the right person",
        "this is not the right person",
        "this isn't the right person",
        "no not the right person",
        "no this is not the right person",
        "you called the wrong person",
        "you reached the wrong person",
        "I am not who you are looking for",
        "I'm not who you are looking for",
        "no I am not who you are looking for",
        "no I'm not who you are looking for",
        "I am not the person you are looking for",
        "I'm not the person you are looking for",
        "no I am not the person you are looking for",
        "no I'm not the person you are looking for",
        "I am not the one you called",
        "I'm not the one you called",
        "no I am not the one",
        "no I'm not the one",
        "that is not my name",
        "that's not my name",
        "no that is not my name",
        "no that's not my name",
        "you have the wrong individual",
        "you reached the wrong individual",
        # General non-target assertions
        "no not him",
        "no not her",
        "not him",
        "not her",
        "no I'm not him",
        "no I'm not her",
        "no I am not him",
        "no I am not her",
        "no this is not him",
        "no this is not her",
        "no this isn't him",
        "no this isn't her",
        "this is not him",
        "this is not her",
        "this isn't him",
        "this isn't her",
        "no this is someone else",
        "no I am someone else",
        "no I'm someone else",
        "this is someone else",
        "I am someone else",
        "I'm someone else",
        "no you have someone else",
        "you have someone else",
        # Denying with a different name reference
        "I am not Sarah",
        "I'm not Sarah",
        "no I am not Sarah",
        "no I'm not Sarah",
        "this is not Sarah",
        "no this is not Sarah",
        "I am not Michael",
        "I'm not Michael",
        "no I am not Michael",
        "I am not Robert",
        "I am not David",
        "I am not Jennifer",
        "I am not Emily",
        # More emphatic denials
        "definitely not me",
        "absolutely not me",
        "no definitely not",
        "no absolutely not",
        "I am certainly not that person",
        "I'm certainly not that person",
        "that is definitely not me",
        "that's definitely not me",
        "no that is definitely not me",
        "no that's definitely not me",
        # Confused / uncertain denial
        "I don't think that's me",
        "I don't think that is me",
        "I don't believe that is me",
        "I'm not sure but I don't think that's me",
        "that doesn't sound like me",
        "that does not sound like me",
        "no that doesn't sound right",
        "no I don't think that's me",
        # Polite denials
        "I'm sorry that's not me",
        "I'm sorry this is not me",
        "sorry that's not me",
        "sorry this is not me",
        "I'm afraid that's not me",
        "I'm afraid this is not me",
        "I'm afraid you have the wrong person",
        "sorry you have the wrong person",
        "I'm sorry you have the wrong person",
        "I believe you have the wrong person",
        "I think you have the wrong person",
    ]
    # Remove duplicates preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for s in samples:
        if s not in seen:
            seen.add(s)
            deduped.append(s)
    return {
        "intentName": "IdentityDenied",
        "description": "Caller says they are not the expected customer without asserting a wrong number",
        "sampleUtterances": [{"utterance": x} for x in deduped],
        "intentClosingSetting": _identity_end_conversation(),
        "botId": bot_id,
        "botVersion": "DRAFT",
        "localeId": cfg.locale,
    }


def identity_ambiguous_intent_request(cfg: ProjectConfig, bot_id: str) -> dict[str, Any]:
    samples = [
        # Original
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
        # Expanded - evasive / unclear
        "um",
        "uh",
        "hmm",
        "I'm not sure",
        "I am not sure",
        "not sure",
        "I guess",
        "possibly",
        "it depends",
        "pardon",
        "excuse me",
        "what",
        "huh",
        "come again",
        "can you repeat that",
        "I didn't catch that",
        "I don't understand",
        "what do you mean",
        "what are you asking",
        # Asking for clarification about identity
        "what name did you say",
        "whose name did you say",
        "what name are you looking for",
        "which John",
        "which Sarah",
        "which one",
        "can you tell me more",
        "what is this call about",
        "who gave you this number",
        "what company are you from",
        "who are you",
        "what organization is this",
        "is this a sales call",
        "is this a robocall",
        "why do you need to know",
        "what do you need",
        "can you explain",
        "what exactly do you want",
        # Partial affirmations that are still ambiguous
        "I might be",
        "could be",
        "that might be me",
        "that could be me",
        "perhaps",
        "possibly that's me",
        "I suppose",
        "I guess that could be me",
        "that sounds about right maybe",
        "I'm not entirely sure",
        "I am not entirely sure",
        "I am not completely sure",
        # Deflections
        "it's complicated",
        "it is complicated",
        "that's a long story",
        "that depends",
        "why do you ask",
        "before I answer who is this",
        "can I ask who is calling first",
        "can I ask what this is regarding",
        "what is this regarding",
        "what is the nature of this call",
        "just a moment",
        "hold on a second",
        "give me a second",
        "one second",
        "wait",
        "hang on",
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
    relationships = [
        "father", "mother", "dad", "mom", "parent",
        "brother", "sister", "sibling",
        "wife", "husband", "spouse", "partner", "girlfriend", "boyfriend",
        "son", "daughter", "child", "kid",
        "roommate", "housemate",
        "coworker", "colleague",
        "friend", "neighbor",
        "guardian",
        "assistant",
        "uncle", "aunt", "cousin", "nephew", "niece",
        "grandfather", "grandmother", "grandpa", "grandma", "grandchild",
        "stepson", "stepdaughter", "stepfather", "stepmother", "stepbrother", "stepsister",
        "in-law", "emergency contact", "family member", "relative",
    ]

    samples: list[str] = []
    for r in relationships:
        samples.extend([
            f"I am his {r}",
            f"I am her {r}",
            f"I'm his {r}",
            f"I'm her {r}",
            f"this is his {r}",
            f"this is her {r}",
            f"no I am his {r}",
            f"no I am her {r}",
            f"no I'm his {r}",
            f"no I'm her {r}",
            f"no this is his {r}",
            f"no this is her {r}",
            f"no you're speaking with his {r}",
            f"no you're speaking with her {r}",
            f"no you're talking to his {r}",
            f"no you're talking to her {r}",
            f"you're speaking with his {r}",
            f"you're speaking with her {r}",
            f"his {r}",
            f"her {r}",
            f"his {r} speaking",
            f"her {r} speaking",
            f"no his {r}",
            f"no her {r}",
            f"I'm a {r}",
            f"no I'm a {r}",
        ])

    samples.extend([
        # Answering / picking up on behalf
        "I answered the phone for him",
        "I answered the phone for her",
        "I picked up for him",
        "I picked up for her",
        "I am picking up for him",
        "I am picking up for her",
        "I'm picking up for him",
        "I'm picking up for her",
        "no I picked up for him",
        "no I picked up for her",
        "no I'm picking up for him",
        "no I'm picking up for her",
        "I am answering for him",
        "I am answering for her",
        "I'm answering for him",
        "I'm answering for her",
        "no I am answering for him",
        "no I am answering for her",
        "no I'm answering for him",
        "no I'm answering for her",
        "I am taking the call for him",
        "I am taking the call for her",
        "I'm taking the call for him",
        "I'm taking the call for her",
        "I am calling on his behalf",
        "I am calling on her behalf",
        "I'm calling on his behalf",
        "I'm calling on her behalf",
        "I am speaking on his behalf",
        "I am speaking on her behalf",
        "I'm speaking on his behalf",
        "I'm speaking on her behalf",
        "I live with him",
        "I live with her",
        "we live together",
        "we share this phone",
        "this is a shared phone",
        "I found this phone",
        "I am holding his phone",
        "I am holding her phone",
        "I'm holding his phone",
        "I'm holding her phone",
        "I have his phone",
        "I have her phone",
        "no I have his phone",
        "no I have her phone",
    ])

    seen_tp: set[str] = set()
    deduped_tp: list[str] = []
    for s in samples:
        if s not in seen_tp:
            seen_tp.add(s)
            deduped_tp.append(s)

    return {
        "intentName": "ThirdPartyDetected",
        "description": "A relative or other third party answered instead of the expected customer",
        "sampleUtterances": [{"utterance": x} for x in deduped_tp],
        "intentClosingSetting": _identity_end_conversation(),
        "botId": bot_id,
        "botVersion": "DRAFT",
        "localeId": cfg.locale,
    }


def patient_unavailable_intent_request(cfg: ProjectConfig, bot_id: str) -> dict[str, Any]:
    samples = [
        # Original
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
        # Expanded - not available / not home
        "they're not here",
        "they're not available",
        "he isn't available",
        "she isn't available",
        "they aren't available",
        "he isn't here",
        "she isn't here",
        "they aren't here",
        "he is not home",
        "she is not home",
        "they are not home",
        "he's not home",
        "she's not home",
        "they're not home",
        "he isn't home",
        "she isn't home",
        "they aren't home",
        "he is out",
        "she is out",
        "they are out",
        "he's out",
        "she's out",
        "they're out",
        "he stepped out",
        "she stepped out",
        "they stepped out",
        "he is not in right now",
        "she is not in right now",
        "they are not in right now",
        "he is not around",
        "she is not around",
        "they are not around",
        "he's not around",
        "she's not around",
        # At work / out of reach
        "he's at work",
        "she's at work",
        "they're at work",
        "he is at the office",
        "she is at the office",
        "they are at the office",
        "he is working right now",
        "she is working right now",
        "he is on a shift",
        "she is on a shift",
        "he is at his job",
        "she is at her job",
        # Cannot come to the phone
        "he can't come to the phone",
        "she can't come to the phone",
        "they can't come to the phone",
        "he cannot get to the phone",
        "she cannot get to the phone",
        "they cannot get to the phone",
        "he is unable to come to the phone",
        "she is unable to come to the phone",
        "he is not able to come to the phone right now",
        "she is not able to come to the phone right now",
        "he can't talk right now",
        "she can't talk right now",
        "they can't talk right now",
        "he cannot talk right now",
        "she cannot talk right now",
        "he is not able to talk right now",
        "she is not able to talk right now",
        # Sleeping / resting
        "he is sleeping",
        "she is sleeping",
        "they are sleeping",
        "he's sleeping",
        "she's sleeping",
        "he is asleep",
        "she is asleep",
        "they are asleep",
        "he is resting",
        "she is resting",
        "they are resting",
        "he's resting",
        "she's resting",
        "he is taking a nap",
        "she is taking a nap",
        "he is in the shower",
        "she is in the shower",
        "he is in the bathroom",
        "she is in the bathroom",
        # Away / traveling
        "he is away",
        "she is away",
        "they are away",
        "he's away",
        "she's away",
        "he is traveling",
        "she is traveling",
        "they are traveling",
        "he is out of town",
        "she is out of town",
        "they are out of town",
        "he is on vacation",
        "she is on vacation",
        "they are on vacation",
        "he is at a doctor's appointment",
        "she is at a doctor's appointment",
        "he is at an appointment",
        "she is at an appointment",
        "he is at the hospital",
        "she is at the hospital",
        "he is in the hospital",
        "she is in the hospital",
        "he is running errands",
        "she is running errands",
        "he is in a meeting",
        "she is in a meeting",
        # Busy
        "he is busy",
        "she is busy",
        "they are busy",
        "he's busy",
        "she's busy",
        "he is occupied right now",
        "she is occupied right now",
        "he is tied up right now",
        "she is tied up right now",
        "he is preoccupied",
        "she is preoccupied",
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
        # Original
        "wrong number",
        "no wrong number",
        "no this is the wrong number",
        "this is the wrong number",
        "no this is a wrong number",
        "this is a wrong number",
        "it is the wrong number",
        "it's the wrong number",
        "no it's the wrong number",
        "it is a wrong number",
        "it's a wrong number",
        "no it's a wrong number",
        "no it is a wrong number",
        "no it is the wrong number",
        "it's wrong number",
        "no it's wrong number",
        "it is wrong number",
        "no it is wrong number",
        "you have the wrong number",
        "no you have the wrong number",
        "you called the wrong number",
        "no you called the wrong number",
        "you reached the wrong number",
        "no you reached the wrong number",
        "you got the wrong number",
        "no you got the wrong number",
        "you've got the wrong number",
        "no you've got the wrong number",
        "oh you got the wrong number",
        "oh no you got the wrong number",
        "oh hey you got the wrong number",
        "wrong phone number",
        "no wrong phone number",
        "this is the wrong phone number",
        "no this is the wrong phone number",
        "you have the wrong phone number",
        "no you have the wrong phone number",
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
        # Expanded - wrong number variants
        "you dialed the wrong number",
        "no you dialed the wrong number",
        "you've dialed the wrong number",
        "no you've dialed the wrong number",
        "you have dialed the wrong number",
        "no you have dialed the wrong number",
        "this is not the number you want",
        "this is not the right number",
        "you have an incorrect number",
        "this number is incorrect",
        "you may have misdialed",
        "I think you misdialed",
        "I think you have the wrong number",
        "I believe you have the wrong number",
        "I'm pretty sure this is the wrong number",
        "I'm sure you have the wrong number",
        "sorry wrong number",
        "sorry you have the wrong number",
        "I'm afraid you have the wrong number",
        "I'm afraid this is the wrong number",
        # Acoustic ASR misrecognition variants
        "no this is the phone number",
        "this is the phone number",
        # No one by that name here
        "there is no Sarah here",
        "there is no Michael here",
        "there is no David here",
        "there is no Robert here",
        "there is no one here with this name",
        "there is nobody here with this name",
        "there's no one here with this name",
        "there's nobody here with this name",
        "there is no one here with that name",
        "there is nobody here with that name",
        "there's no one here with that name",
        "there's nobody here with that name",
        "no one here with this name",
        "nobody here with this name",
        "no one here with that name",
        "nobody here with that name",
        "no one here by this name",
        "nobody here by this name",
        "no one with this name",
        "nobody with this name",
        "no one with that name",
        "nobody with that name",
        "no one here by that name",
        "nobody here by that name",
        "no one lives here by that name",
        "no one at this number by that name",
        "no one at this number with this name",
        "no one at this number with that name",
        "there is no one at this number with this name",
        "there is nobody at this number with this name",
        "we don't have anyone by that name here",
        "there is nobody at this number by that name",
        "that name doesn't ring a bell",
        "that name does not ring a bell",
        "I don't know anyone by that name",
        "I do not know anyone by that name",
        "I don't recognize that name",
        "I do not recognize that name",
        "I've never heard of that person",
        "I have never heard of that person",
        "I don't know who that is",
        "I do not know who that is",
        # ASR-clipped fragments (turn-start truncation resilient)
        "here with this name",
        "here with that name",
        "here by that name",
        "here by this name",
        "at this number with this name",
        "at this number with that name",
        "one here with this name",
        "one here with that name",
        "one here by that name",
        "one here by this name",
        "body here with this name",
        "body here by that name",
        "lives here with this name",
        "lives here by that name",
        # Number changed / reassigned
        "this number has changed",
        "this is a new number",
        "I recently got this number",
        "I just got this number",
        "this number was reassigned",
        "I am a new owner of this number",
        "this is my new number but I am not that person",
        "this used to be someone else's number",
        "the previous owner of this number was someone else",
        # Combined assertions
        "you have the wrong number and the wrong person",
        "wrong person wrong number",
        "neither the person nor the number is right",
        "you have reached the wrong number entirely",
        "completely wrong number",
        "totally wrong number",
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
        # Original
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
        # Expanded - caregiver variants
        "I am their caregiver",
        "I'm his caregiver",
        "I'm her caregiver",
        "I'm their caregiver",
        "I am the primary caregiver",
        "I am his primary caregiver",
        "I am her primary caregiver",
        "I am a professional caregiver",
        "I am his professional caregiver",
        "I am her professional caregiver",
        "I am his home health aide",
        "I am her home health aide",
        "I am the home health aide",
        "I am his nurse",
        "I am her nurse",
        "I am the nurse",
        "I am his healthcare proxy",
        "I am her healthcare proxy",
        "I am the healthcare proxy",
        "I am his health advocate",
        "I am her health advocate",
        # Representative variants
        "I'm his representative",
        "I'm her representative",
        "I'm their representative",
        "I am their representative",
        "I'm his authorized representative",
        "I'm her authorized representative",
        "I'm their authorized representative",
        "I am their authorized representative",
        "I am acting as his representative",
        "I am acting as her representative",
        "I am acting on his behalf",
        "I am acting on her behalf",
        "I am authorized to speak on his behalf",
        "I am authorized to speak on her behalf",
        "I am authorized to handle his affairs",
        "I am authorized to handle her affairs",
        "I am legally authorized to speak for him",
        "I am legally authorized to speak for her",
        # Power of attorney variants
        "I'm his power of attorney",
        "I'm her power of attorney",
        "I'm their power of attorney",
        "I have his power of attorney",
        "I have her power of attorney",
        "I hold power of attorney",
        "I hold his power of attorney",
        "I hold her power of attorney",
        "I have power of attorney for him",
        "I have power of attorney for her",
        "I have durable power of attorney",
        "I am the durable power of attorney",
        "I have medical power of attorney",
        "I am the medical power of attorney",
        "I have healthcare power of attorney",
        "I am the legal guardian",
        "I am his legal guardian",
        "I am her legal guardian",
        "I am their legal guardian",
        "I am the conservator",
        "I am his conservator",
        "I am her conservator",
        # Social worker / professional
        "I am his social worker",
        "I am her social worker",
        "I am the social worker",
        "I am his case manager",
        "I am her case manager",
        "I am the case manager",
        "I am his care coordinator",
        "I am her care coordinator",
        "I am the care coordinator",
        "I am his doctor",
        "I am her doctor",
        "I am calling from his doctor's office",
        "I am calling from her doctor's office",
        # Expanded - family member/guardian explicitly offering to proceed on
        # the patient's behalf. Added so any such offer (family or
        # professional) routes straight to a human agent instead of ending
        # the call -- the identity gate no longer tries to judge whether the
        # caller is telling the truth; a human verifies that live.
        "no I am his brother you can talk to me",
        "no I am her sister you can talk to me",
        "this is his brother you can talk to me",
        "this is her sister you can talk to me",
        "I am his father you can speak to me",
        "I am her mother you can speak to me",
        "I am his son I can talk on his behalf",
        "I am her daughter I can talk on her behalf",
        "I am his guardian you can talk to me",
        "I am her guardian you can talk to me",
        "I am his family member you can talk to me",
        "I am her family member you can talk to me",
        "you can talk to me",
        "you can speak to me",
        "you can talk with me",
        "you can discuss it with me",
        "I can talk on his behalf",
        "I can talk on her behalf",
        "I can speak on his behalf",
        "I can speak on her behalf",
        "I can speak for him",
        "I can speak for her",
        "I can answer for him",
        "I can answer for her",
        "I can talk for him",
        "I can talk for her",
        "I'll speak for him",
        "I'll speak for her",
    ]
    return {
        "intentName": "RepresentativeDetected",
        "description": (
            "A caregiver, representative, or family member/guardian answered instead of the "
            "expected customer and offers to speak or proceed on their behalf"
        ),
        "sampleUtterances": [{"utterance": x} for x in samples],
        "intentClosingSetting": _identity_end_conversation(),
        "botId": bot_id,
        "botVersion": "DRAFT",
        "localeId": cfg.locale,
    }


def call_refusal_intent_request(cfg: ProjectConfig, bot_id: str) -> dict[str, Any]:
    samples = [
        # Original
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
        # Expanded - direct refusals
        "no thank you",
        "no thank you I am not interested",
        "no I'm not interested",
        "no I am not interested",
        "not interested",
        "not interested thank you",
        "not interested thanks",
        "I'm not interested",
        "I am not interested at all",
        "I'm really not interested",
        "I have no interest in this",
        "I have absolutely no interest",
        "this does not interest me",
        "this doesn't interest me",
        "I don't need this",
        "I do not need this",
        "I don't want it",
        "I do not want it",
        "I don't want to be called",
        "I do not want to be called",
        "I don't want any more calls",
        "I do not want any more calls",
        # Stop calling requests
        "please stop calling",
        "stop calling",
        "please do not call me again",
        "please don't call me again",
        "do not call this number again",
        "don't call this number again",
        "do not call me anymore",
        "don't call me anymore",
        "never call me again",
        "please never call me again",
        "I want you to stop calling me",
        "I need you to stop calling me",
        "I would like you to stop calling me",
        "please refrain from calling me",
        "cease calling me",
        "cease and desist calling me",
        # Do not call list requests
        "remove me from your list",
        "take me off your call list",
        "remove me from your call list",
        "put me on your do not call list",
        "add me to your do not call list",
        "I want to be on your do not call list",
        "place me on the do not call list",
        "I want to be removed from your list",
        "please remove my number",
        "remove my number from your system",
        "delete my number",
        "I want my number removed",
        "unsubscribe me",
        "please unsubscribe me from calls",
        # Irritated / emphatic
        "stop bothering me",
        "please stop bothering me",
        "leave me alone",
        "please leave me alone",
        "I don't want to be contacted",
        "do not contact me",
        "don't contact me again",
        "I am asking you not to call",
        "I am requesting you stop calling",
        "I formally request you stop calling",
        "I said no",
        "I already said no",
        "I've already said no",
        "I told you before I'm not interested",
        "I've told you before not to call",
        "this is harassment",
        "stop harassing me",
        "you keep calling me",
        "you've been calling too much",
        "you call too often",
        "I do not appreciate these calls",
        "I don't appreciate these calls",
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
        # Original
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
        # Live evidence - is no more & is dead disclosures
        "Kevin is no more",
        "Kevin Peterson is no more",
        "he is no more",
        "she is no more",
        "they are no more",
        "he's no more",
        "she's no more",
        "they're no more",
        "Kevin Peterson is no more right now",
        "Kevin is no more right now",
        "is no more",
        "is no more right now",
        "no more right now",
        "Kevin Peterson is dead",
        "Kevin is dead",
        "he is dead",
        "he's dead",
        "she is dead",
        "she's dead",
        "they are dead",
        "they're dead",
        "Kevin passed",
        "Kevin Peterson passed",
        "Kevin Peterson passed away",
        "Kevin Peterson has passed",
        "he passed",
        "she passed",
        "they passed",
        # Expanded - passed away / passed on
        "they passed away",
        "he has passed away",
        "she has passed away",
        "they have passed away",
        "he passed on",
        "she passed on",
        "they passed on",
        "he has passed on",
        "she has passed on",
        "they have passed on",
        "he passed last year",
        "she passed last year",
        "he passed recently",
        "she passed recently",
        "he passed a few months ago",
        "she passed a few months ago",
        "he passed away last month",
        "she passed away last month",
        "he passed away last year",
        "she passed away last year",
        "he passed away a few weeks ago",
        "she passed away a few weeks ago",
        # Died
        "they died",
        "he has died",
        "she has died",
        "they have died",
        "he died last year",
        "she died last year",
        "he died recently",
        "she died recently",
        "he died a few months ago",
        "she died a few months ago",
        "Sarah died",
        "Michael died",
        "Robert died",
        "David died",
        # Deceased
        "they are deceased",
        "he has been deceased",
        "she has been deceased",
        "he is now deceased",
        "she is now deceased",
        "he was pronounced deceased",
        "she was pronounced deceased",
        # No longer with us
        "they are no longer with us",
        "he has passed and is no longer with us",
        "she has passed and is no longer with us",
        "he is gone",
        "she is gone",
        "they are gone",
        "he's gone",
        "she's gone",
        "he has left us",
        "she has left us",
        "they have left us",
        "he is no longer alive",
        "she is no longer alive",
        "they are no longer alive",
        "he is no longer living",
        "she is no longer living",
        "they are no longer living",
        # Euphemisms
        "he passed to the other side",
        "she passed to the other side",
        "he is resting in peace",
        "she is resting in peace",
        "he is in a better place",
        "she is in a better place",
        "he is with God now",
        "she is with God now",
        "God rest his soul he has passed",
        "God rest her soul she has passed",
        "may he rest in peace he passed away",
        "may she rest in peace she passed away",
        # Context provided by third party
        "he was my father and he passed away",
        "she was my mother and she passed away",
        "he was my husband and he passed",
        "she was my wife and she passed",
        "I'm calling to let you know he passed away",
        "I'm calling to let you know she passed away",
        "I wanted to inform you he has passed",
        "I wanted to inform you she has passed",
        "I am calling because he passed away recently",
        "I am calling because she passed away recently",
    ]
    seen: set[str] = set()
    deduped: list[str] = []
    for s in samples:
        if s not in seen:
            seen.add(s)
            deduped.append(s)

    return {
        "intentName": "Deceased",
        "description": "Caller reports that the expected customer is deceased",
        "sampleUtterances": [{"utterance": x} for x in deduped],
        "intentClosingSetting": _identity_end_conversation(),
        "botId": bot_id,
        "botVersion": "DRAFT",
        "localeId": cfg.locale,
    }


def safety_medical_intent_request(cfg: ProjectConfig, bot_id: str) -> dict[str, Any]:
    samples = [
        # Original
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
        # Expanded - breathing / respiratory
        "I can't breathe",
        "I cannot breathe",
        "I am struggling to breathe",
        "I have difficulty breathing",
        "I am short of breath",
        "I am very short of breath",
        "I am extremely short of breath",
        "my breathing is very labored",
        "I am wheezing badly",
        "I feel like I am suffocating",
        "I feel like something is blocking my airway",
        "I am choking",
        "someone is choking",
        "he is choking",
        "she is choking",
        "I cannot get enough air",
        "I feel like I am drowning",
        "my lungs feel like they are shutting down",
        # Chest pain / cardiac
        "I am having a heart attack",
        "I'm having a heart attack",
        "I have a heart attack",
        "my chest feels like it is exploding",
        "my chest feels like it's exploding",
        "my chest is exploding",
        "I am having chest pain",
        "I have chest pain",
        "my chest hurts badly",
        "my chest is hurting severely",
        "I have pressure in my chest",
        "I feel pressure on my chest",
        "there is tightness in my chest",
        "I have tightness in my chest",
        "my chest feels very tight",
        "I think I am having a heart attack",
        "I may be having a heart attack",
        "I feel like I am having a heart attack",
        "he is having a heart attack",
        "she is having a heart attack",
        "they are having a heart attack",
        "my heart is racing and I feel very sick",
        "my heart is pounding and I cannot breathe",
        "I have an irregular heartbeat and feel faint",
        "I am having palpitations and feel very unwell",
        # Bleeding / injury
        "I am bleeding a lot",
        "there is a lot of blood",
        "the wound is bleeding severely",
        "I cannot stop the bleeding",
        "he is bleeding heavily",
        "she is bleeding heavily",
        "they are bleeding heavily",
        "there is severe bleeding here",
        "someone is bleeding severely",
        "I have a severe laceration",
        "I have a deep cut that won't stop bleeding",
        "I had a bad fall and I am bleeding",
        "I was in an accident and I am injured",
        "I have a serious head injury",
        "he has a serious injury",
        "she has a serious injury",
        # Loss of consciousness / passing out
        "I feel like I am going to faint",
        "I feel like I am going to pass out",
        "I nearly fainted",
        "I almost passed out",
        "he fainted",
        "she fainted",
        "they fainted",
        "he passed out",
        "she passed out",
        "they passed out",
        "he is unresponsive",
        "she is unresponsive",
        "they are unresponsive",
        "he won't wake up",
        "she won't wake up",
        "they won't wake up",
        "I cannot wake him up",
        "I cannot wake her up",
        "he is not breathing",
        "she is not breathing",
        "they are not breathing",
        # Stroke symptoms
        "I think I am having a stroke",
        "he is having a stroke",
        "she is having a stroke",
        "he suddenly cannot speak",
        "she suddenly cannot speak",
        "his face is drooping",
        "her face is drooping",
        "he cannot move his arm",
        "she cannot move her arm",
        "I have sudden severe headache",
        "I have the worst headache of my life",
        "he has sudden vision loss",
        "she has sudden vision loss",
        # Allergic reaction
        "I am having an allergic reaction",
        "I am having a bad allergic reaction",
        "I am having anaphylaxis",
        "I think I am having anaphylaxis",
        "my throat is closing",
        "my throat is swelling shut",
        "I used my epi-pen but still feel very sick",
        "I am swelling all over",
        "I have hives and my throat is closing",
        # Blood sugar / diabetic emergency
        "my blood sugar is very low",
        "my blood sugar is critically low",
        "I am hypoglycemic and feel very bad",
        "he is having a diabetic emergency",
        "she is having a diabetic emergency",
        "his blood sugar crashed",
        "her blood sugar crashed",
        "my blood sugar is extremely high and I feel sick",
        "I am in diabetic ketoacidosis",
        "I think I am in DKA",
        # Blood pressure
        "my blood pressure is very high",
        "my blood pressure is extremely high",
        "I am having a hypertensive crisis",
        "my blood pressure is critically low",
        "I feel faint because my blood pressure is low",
        # Overdose / poisoning
        "I took too many pills",
        "I may have taken too many medications",
        "someone took too many pills",
        "he overdosed",
        "she overdosed",
        "they overdosed",
        "I think someone overdosed here",
        "he may have overdosed",
        "she may have overdosed",
        "I ingested something harmful",
        "I was poisoned",
        "someone was poisoned",
        "he swallowed something dangerous",
        "she swallowed something dangerous",
        # Seizure
        "I am having a seizure",
        "he is having a seizure",
        "she is having a seizure",
        "they are having a seizure",
        "he just had a seizure",
        "she just had a seizure",
        "the seizure is not stopping",
        "he is convulsing",
        "she is convulsing",
        # Embedded in other responses
        "I'm not interested but I am having trouble breathing",
        "no thanks but I cannot breathe well",
        "stop calling me but there is someone unconscious here",
        "wrong number but someone here is not breathing",
        "she is not available she is in the hospital with chest pain",
        "he cannot come to the phone he is having a heart attack",
        "call me later I am having a severe allergic reaction",
        "I am busy but there is a medical emergency",
        "not a good time there is a medical emergency here",
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
    samples = [
        # Original
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
        # Expanded - suicidal ideation
        "I am thinking of ending my life",
        "I have thoughts of ending my life",
        "I have been thinking about ending my life",
        "I have suicidal thoughts",
        "I am having suicidal thoughts",
        "I am suicidal",
        "I feel suicidal",
        "I want to end it all",
        "I want to end my life",
        "I am planning to end my life",
        "I have a plan to end my life",
        "I don't want to be here anymore",
        "I don't want to exist anymore",
        "life is not worth living",
        "I feel like life is not worth living",
        "I feel like there is no point in living",
        "there is no reason to go on",
        "I have no reason to live",
        "I see no reason to keep going",
        "I am going to kill myself",
        "I was thinking of killing myself",
        "I nearly killed myself",
        "I almost killed myself",
        "he is thinking about suicide",
        "she is thinking about suicide",
        "they are thinking about suicide",
        "he said he wants to kill himself",
        "she said she wants to kill herself",
        "he mentioned ending his life",
        "she mentioned ending her life",
        # Self-harm
        "I have been hurting myself",
        "I hurt myself recently",
        "I am cutting myself",
        "I have been cutting myself",
        "I am harming myself",
        "I have been harming myself",
        "I feel the urge to hurt myself",
        "I feel like hurting myself",
        "I am scared I will hurt myself",
        "I am worried I might hurt myself",
        "he has been hurting himself",
        "she has been hurting herself",
        "he is cutting himself",
        "she is cutting herself",
        # Harm to others
        "I am thinking about hurting someone",
        "I am having thoughts of hurting someone",
        "I feel like hurting someone",
        "I might do something dangerous",
        "I am scared I might hurt someone",
        "I am afraid of what I might do",
        "I have been thinking of hurting my family",
        "he is threatening to hurt someone",
        "she is threatening to hurt someone",
        "they are threatening to harm others",
        "he has a weapon and is making threats",
        "she has a weapon and is threatening people",
        # Abuse / domestic violence / danger
        "I am not safe",
        "I am not safe right now",
        "I am in danger",
        "I am in danger right now",
        "I feel like I am in danger",
        "I am being hurt",
        "I am being hurt right now",
        "someone is hurting me right now",
        "someone is attacking me",
        "I am being attacked",
        "I am being physically abused",
        "I am experiencing domestic violence",
        "my partner is hurting me",
        "my partner hit me",
        "my partner has been hitting me",
        "I am afraid of my partner",
        "I am afraid of my spouse",
        "my husband is threatening me",
        "my wife is threatening me",
        "my boyfriend is threatening me",
        "my girlfriend is threatening me",
        "there is violence in my home",
        "there is an abusive situation here",
        "I am trapped",
        "I cannot leave safely",
        "I am afraid to go home",
        "I do not feel safe where I am",
        "I do not feel safe at home right now",
        "there is a dangerous person here",
        "someone broke into my home",
        "someone is in my home right now",
        "I am being stalked",
        "someone is following me",
        "I am being threatened",
        "I am receiving threats",
        # Mental health crisis
        "I am in crisis",
        "I am having a crisis",
        "I am having a mental health emergency",
        "I am experiencing a mental health emergency",
        "I am spiraling",
        "I am in a very dark place",
        "I am in a really bad place right now",
        "I am not okay",
        "I am really not okay right now",
        "I cannot cope anymore",
        "I can't cope with this anymore",
        "I am overwhelmed and I don't know what to do",
        "I am in a breakdown",
        "I am having a breakdown",
        "I am having a panic attack",
        "I am having a severe panic attack",
        "I am psychotic right now",
        "I am hearing voices telling me to hurt myself",
        "I am hearing voices and I am scared",
        # Substance use crisis
        "I am having a substance abuse crisis",
        "I am in a substance use emergency",
        "I have been using drugs and I feel unsafe",
        "I have relapsed and I feel like hurting myself",
        "I overdosed on drugs and I want to die",
        "I have been drinking heavily and feel suicidal",
        "I am in withdrawal and I feel like I might do something dangerous",
        # Embedded in other responses
        "I'm not interested but I don't feel safe right now",
        "no thanks but I am in danger",
        "stop calling me I am being hurt right now",
        "wrong number but someone here is suicidal",
        "he is not available he is in a mental health crisis",
        "she cannot come to the phone she said she wants to die",
        "call me later I am not safe right now",
        "I am busy but I am having thoughts of hurting myself",
        "not a good time I am in crisis",
        "I'm not interested I want to die",
        "I do not want this call and I am suicidal",
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
        # Original
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
        # Expanded - affirmations of availability
        "yes they're here",
        "he is available",
        "she is available",
        "they are available",
        "he's available",
        "she's available",
        "they're available",
        "he is home",
        "she is home",
        "they are home",
        "he's home",
        "she's home",
        "they're home",
        "he is right here",
        "she is right here",
        "they are right here",
        "he's right here",
        "she's right here",
        "yes he is available",
        "yes she is available",
        "yes they are available",
        "yes he is home",
        "yes she is home",
        "yes he is here with me",
        "yes she is here with me",
        "yes they are here with me",
        # Offering to fetch / transfer
        "hold on please",
        "just a moment please",
        "just a second",
        "one second please",
        "give me a moment",
        "give me one second",
        "wait one moment",
        "please hold",
        "please hold on",
        "please wait",
        "just a moment",
        "please give me a moment",
        "I'll get him",
        "I'll get her",
        "I'll get them",
        "I can get them",
        "let me get them",
        "I will get him",
        "I will get her",
        "I will get them",
        "I'll go get him",
        "I'll go get her",
        "I'll go get them",
        "let me go get him",
        "let me go get her",
        "let me go get them",
        "I'll bring him to the phone",
        "I'll bring her to the phone",
        "I will bring him to the phone",
        "I will bring her to the phone",
        "I'll put him on the phone",
        "I'll put her on the phone",
        "I'll put them on the phone",
        "I will put them on the phone",
        "I can put him on",
        "I can put her on",
        "I can put them on",
        "let me put him on",
        "let me put her on",
        "let me transfer you to him",
        "let me hand him the phone",
        "let me hand her the phone",
        "I will hand him the phone",
        "I will hand her the phone",
        "I'll pass the phone to him",
        "I'll pass the phone to her",
        "I will pass the phone to him",
        "I will pass the phone to her",
        "I can pass you to him",
        "I can pass you to her",
        "I can transfer you to him",
        "I can transfer you to her",
        # Affirmative with transitional phrases
        "sure let me get him",
        "sure let me get her",
        "of course let me get him",
        "of course let me get her",
        "absolutely let me get him",
        "absolutely let me get her",
        "yes sure one moment",
        "yes of course one moment",
        "yes one moment please",
        "yes hold on please",
        "yes please hold on",
        "yes just a moment",
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
        # Original
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
        # Expanded - unavailable now
        "no not right now",
        "not at this time",
        "not at the moment",
        "not currently",
        "he's not available",
        "she's not available",
        "they're not available",
        "he is unavailable",
        "she is unavailable",
        "they are unavailable",
        "he's unavailable",
        "she's unavailable",
        "they're unavailable",
        "he's not here",
        "she's not here",
        "they're not here",
        "he is not home",
        "she is not home",
        "they are not home",
        "he's not home",
        "she's not home",
        "they're not home",
        "he is out right now",
        "she is out right now",
        "they are out right now",
        "he's out right now",
        "she's out right now",
        "they're out right now",
        "he is not in",
        "she is not in",
        "they are not in",
        "he stepped out",
        "she stepped out",
        "they stepped out",
        "he is away right now",
        "she is away right now",
        "they are away right now",
        # At work / occupied
        "they're at work",
        "he is working right now",
        "she is working right now",
        "they are working right now",
        "he is on a shift",
        "she is on a shift",
        "he is at the office",
        "she is at the office",
        "they are at the office",
        "he is in a meeting",
        "she is in a meeting",
        "they are in a meeting",
        "he is busy right now",
        "she is busy right now",
        "they are busy right now",
        "he's busy right now",
        "she's busy right now",
        "they're busy right now",
        "he is occupied right now",
        "she is occupied right now",
        "he is tied up",
        "she is tied up",
        "he is unavailable at the moment",
        "she is unavailable at the moment",
        # Call back / try again
        "please call back later",
        "please try again later",
        "try calling later",
        "try calling back later",
        "call again later",
        "try again at a later time",
        "call us back later",
        "please try later",
        "he will be available later",
        "she will be available later",
        "they will be available later",
        "he should be free later",
        "she should be free later",
        "they should be free later",
        "try tomorrow",
        "try calling tomorrow",
        "call back tomorrow",
        "try again tomorrow",
        "maybe try the afternoon",
        "try in the afternoon",
        "try calling this evening",
        "try this evening",
        "try later today",
        "try in a few hours",
        "call back in a few hours",
        "try again in a little while",
        "maybe try next week",
        "try next week",
        "call next week",
        "he will be available next week",
        "she will be available next week",
        # Specific time / date suggestions (non-slot)
        "he will be back around noon",
        "she will be back around noon",
        "he gets off work at five",
        "she gets off work at five",
        "he will be home by six",
        "she will be home by six",
        "he will be free after three",
        "she will be free after three",
        "try calling Monday",
        "call on Monday",
        "he will be available Monday morning",
        "she will be available Monday morning",
        "try in the morning",
        "call in the morning",
        "try this weekend",
        "call this weekend",
    ]
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
            "call back on {callbackDate}",
            "try again on {callbackDate}",
            "try again at {callbackTime}",
            "try {callbackDate} around {callbackTime}",
            "call back on {callbackDate} around {callbackTime}",
            "he will be free {callbackDate}",
            "she will be free {callbackDate}",
            "they will be free {callbackDate}",
            "he will be free at {callbackTime}",
            "she will be free at {callbackTime}",
            "they will be free at {callbackTime}",
            "he should be available {callbackDate} at {callbackTime}",
            "she should be available {callbackDate} at {callbackTime}",
            "they should be available {callbackDate} at {callbackTime}",
            # Compound date + time utterances
            "tomorrow morning 10 am",
            "tomorrow morning 10:00 am",
            "tomorrow morning 10:00 a.m.",
            "tomorrow morning at 10 am",
            "tomorrow morning at 10:00 am",
            "tomorrow morning at 10:00 a.m.",
            "tomorrow morning around 10",
            "tomorrow morning around 10 am",
            "tomorrow morning around 10:00 am",
            "tomorrow morning around 10:00 a.m.",
            "tomorrow morning",
            "tomorrow afternoon",
            "tomorrow evening",
            "tomorrow night",
            "tomorrow at {callbackTime}",
            "tomorrow around {callbackTime}",
            "in the morning",
            "in the afternoon",
            "in the evening",
            "in an hour",
            "in 1 hour",
            "in a couple hours",
            "in 2 hours",
            "in 30 minutes",
            "in half an hour",
            "next week",
            "Monday morning",
            "Monday afternoon",
            "Monday at 10 am",
            "Monday at 10:00 am",
            "Monday at 10:00 a.m.",
            "Tuesday morning",
            "Wednesday morning",
            "Thursday morning",
            "Friday morning",
            "this morning",
            "this afternoon",
            "this evening",
            "later today",
            "later this morning",
            "later this afternoon",
            "around {callbackTime}",
            "around {callbackTime} {callbackDate}",
            "{callbackDate} in the morning",
            "{callbackDate} in the afternoon",
            "{callbackDate} in the evening",
            "{callbackDate} around {callbackTime}",
            "{callbackDate} at {callbackTime}",
            "{callbackDate} morning {callbackTime}",
            "{callbackDate} morning at {callbackTime}",
            "{callbackDate} morning around {callbackTime}",
            "{callbackDate} afternoon at {callbackTime}",
            "{callbackDate} afternoon around {callbackTime}",
            # Connect / reach / call prefix utterances
            "you can connect with him {callbackDate} at {callbackTime}",
            "you can connect with her {callbackDate} at {callbackTime}",
            "you can connect with them {callbackDate} at {callbackTime}",
            "you can connect with him {callbackDate} {callbackTime}",
            "you can connect with her {callbackDate} {callbackTime}",
            "you can connect with them {callbackDate} {callbackTime}",
            "you can connect with him {callbackDate}",
            "you can connect with him at {callbackTime}",
            "you can reach him {callbackDate} at {callbackTime}",
            "you can reach her {callbackDate} at {callbackTime}",
            "you can reach them {callbackDate} at {callbackTime}",
            "you can reach him {callbackDate} {callbackTime}",
            "you can reach her {callbackDate} {callbackTime}",
            "you can reach them {callbackDate} {callbackTime}",
            "you can reach him {callbackDate}",
            "you can reach him at {callbackTime}",
            "you can call him {callbackDate} at {callbackTime}",
            "you can call her {callbackDate} at {callbackTime}",
            "you can call them {callbackDate} at {callbackTime}",
            "you can call him {callbackDate} {callbackTime}",
            "you can call her {callbackDate} {callbackTime}",
            "you can call them {callbackDate} {callbackTime}",
            "you can call him {callbackDate}",
            "you can call him at {callbackTime}",
            "connect with him {callbackDate} at {callbackTime}",
            "connect with her {callbackDate} at {callbackTime}",
            "connect with them {callbackDate} at {callbackTime}",
            "reach him {callbackDate} at {callbackTime}",
            "reach her {callbackDate} at {callbackTime}",
            "reach them {callbackDate} at {callbackTime}",
            "call him {callbackDate} at {callbackTime}",
            "call her {callbackDate} at {callbackTime}",
            "call them {callbackDate} at {callbackTime}",
            "you can connect with him tomorrow morning at 10 am",
            "you can connect with him tomorrow morning at 10:00 am",
            "you can connect with him tomorrow morning at 10:00 a.m.",
            "you can reach him tomorrow morning at 10 am",
            "you can reach him tomorrow morning at 10:00 am",
            "you can reach him tomorrow morning at 10:00 a.m.",
            "you can call him tomorrow morning at 10 am",
            "you can call him tomorrow morning at 10:00 am",
            "you can call him tomorrow morning at 10:00 a.m.",
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
        # Original
        "I don't know",
        "I am not sure",
        "not sure",
        "maybe",
        "I don't know when",
        "I cannot say",
        "no idea",
        "I don't know their schedule",
        # Expanded
        "I have no idea",
        "I am not certain",
        "I'm not certain",
        "I'm not sure",
        "I am unsure",
        "I'm unsure",
        "I really don't know",
        "I really am not sure",
        "I honestly don't know",
        "I have no clue",
        "I couldn't tell you",
        "I can't tell you",
        "I cannot tell you",
        "I don't have that information",
        "I do not have that information",
        "I'm not aware of their schedule",
        "I am not aware of their schedule",
        "I don't know his schedule",
        "I don't know her schedule",
        "I am not familiar with his schedule",
        "I am not familiar with her schedule",
        "I couldn't say",
        "I can't say for sure",
        "I cannot say for sure",
        "it's hard to say",
        "it is hard to say",
        "I'm not sure when he will be available",
        "I'm not sure when she will be available",
        "I'm not sure when they will be available",
        "I don't know when he will be back",
        "I don't know when she will be back",
        "I don't know when they will be back",
        "I have no way of knowing",
        "there is no way for me to know",
        "I just don't know",
        "I really just don't know",
        "your guess is as good as mine",
        "it varies",
        "it depends",
        "I'm not really sure",
        "I am not really sure",
        "I wish I knew",
        "if I knew I would tell you",
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


# Added because a third party who already said "no" to availability would
# sometimes offer to speak for the patient instead ("I can talk on his
# behalf") and the bot had no idea what to do with that -- it fell through to
# AvailabilityUnknown/FallbackIntent and just ended the call. This intent
# catches that offer here too, not just on the very first identity question.
def availability_representative_willing_intent_request(cfg: ProjectConfig, bot_id: str) -> dict[str, Any]:
    samples = [
        "I can talk on his behalf",
        "I can talk on her behalf",
        "I can speak on his behalf",
        "I can speak on her behalf",
        "I can speak for him",
        "I can speak for her",
        "I can answer for him",
        "I can answer for her",
        "I can talk for him",
        "I can talk for her",
        "I'll speak for him",
        "I'll speak for her",
        "you can talk to me",
        "you can speak to me",
        "you can talk with me",
        "you can discuss it with me",
        "you can tell me instead",
        "talk to me instead",
        "I can help with that",
        "I can handle this for him",
        "I can handle this for her",
        "I'll handle it",
    ]
    return {
        "intentName": "RepresentativeWillingToProceed",
        "description": (
            "The third party offers to speak or proceed on the intended customer's behalf "
            "instead of getting them to the phone"
        ),
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
            "slotConstraint": "Optional",
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
            "slotConstraint": "Optional",
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
                    "Use ONLY when the confirmed customer explicitly agrees to, asks for, or provides a clear "
                    "affirmative answer to speak with a human specialist (e.g., 'yes', 'sure', 'okay', 'go ahead', "
                    "'you can connect now', 'please connect me', 'yes please'). "
                    "NEVER invoke this tool when the customer asks a question or raises an objection, even after "
                    "answering it — you MUST ask for consent and wait for their explicit affirmative reply. "
                    "If the customer stays silent or says something neutral, re-prompt for consent and DO NOT transfer. "
                    "Saying that you will connect the caller without invoking this tool does not perform the transfer. "
                    "Safety always overrides transfer. Do not invoke after a clear refusal or callback request."
                ),
                "examples": [
                    "Cara: Is now a good time? Caller: Yes, please connect me. -> invoke EscalateToHuman",
                    "Cara: Would you like me to connect you with the care team? Caller: Sure, go ahead. -> invoke EscalateToHuman",
                    "Cara: Would you like me to connect you? Caller: Yes, you can connect now. -> invoke EscalateToHuman",
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
                    "inappropriate. Do NOT produce any spoken text in <message> tags when calling EndConversation; "
                    "the Connect flow handles all closing and safety messages after control returns. "
                    "Do NOT use EndConversation for busy, not-right-now, not-a-good-time, call-later, "
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