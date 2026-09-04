#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

import boto3
import yaml
from botocore.validate import ParamValidator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cara_health_bot.builders import (
    identity_ambiguous_intent_request,
    identity_confirmed_intent_request,
    identity_denied_intent_request,
    identity_fallback_intent_request,
    identity_lex_alias_request,
    identity_lex_bot_create_request,
    identity_lex_bot_update_request,
    identity_lex_locale_request,
    identity_lex_runtime_permissions,
    third_party_detected_intent_request,
    patient_unavailable_intent_request,
    wrong_number_intent_request,
    representative_detected_intent_request,
    deceased_intent_request,
    call_refusal_intent_request,
    safety_medical_intent_request,
    safety_behavioral_intent_request,
    render_cara_prompt,
    availability_lex_bot_create_request,
    availability_lex_bot_update_request,
    availability_lex_locale_request,
    availability_now_intent_request,
    availability_unavailable_intent_request,
    availability_unknown_intent_request,
    availability_fallback_intent_request,
    availability_callback_date_slot_request,
    availability_callback_time_slot_request,
    availability_lex_alias_request,
    lex_alias_request,
    lex_bot_create_request,
    lex_bot_update_request,
    lex_fallback_intent_request,
    lex_locale_request,
    lex_qinconnect_intent_request,
    lex_runtime_permissions,
    q_agent_create_request,
    q_agent_configuration,
    q_agent_update_request,
    q_prompt_create_request,
    q_prompt_update_request,
    render_contact_flow,
    session_context_lambda_permissions,
)
from cara_health_bot.config import load_config


def client(name: str, region: str):
    return boto3.client(
        name,
        region_name=region,
        aws_access_key_id="test",
        aws_secret_access_key="test",
        aws_session_token="test",
    )


def validate_api(c, operation: str, request: dict) -> None:
    model = c.meta.service_model.operation_model(operation)
    report = ParamValidator().validate(request, model.input_shape)
    if report.has_errors():
        raise AssertionError(f"{operation} request validation failed:\n{report.generate_report()}")


def main() -> int:
    cfg = load_config()
    for py in ROOT.rglob("*.py"):
        if ".venv" not in py.parts:
            ast.parse(py.read_text(encoding="utf-8"), filename=str(py))

    raw_prompt = cfg.prompt_path.read_text(encoding="utf-8")
    parsed_prompt = yaml.safe_load(raw_prompt)
    assert isinstance(parsed_prompt, dict)
    assert isinstance(parsed_prompt.get("system"), str)
    assert isinstance(parsed_prompt.get("messages"), list)
    for token in (
        "<message>", "</message>", "{{$.conversationHistory}}", "{{$.locale}}",
        "{{$.Custom.customerName}}", "{{$.Custom.expectedPhone}}", "Cara",
    ):
        assert token in raw_prompt, f"prompt missing {token}"
    assert "${CaraBehaviorConfig}" in raw_prompt
    rendered_prompt = render_cara_prompt(cfg, raw_prompt)
    assert "${CaraBehaviorConfig}" not in rendered_prompt
    for behavior_token in (
        "LIGHTWEIGHT CONVERSATIONAL STATE", "QUESTIONS", "OBJECTIONS", "CLEAR REFUSAL",
        "CALLBACK", "SAFETY — HIGHEST PRIORITY", "INTENT PRIORITY", "TRANSFER-FIRST GOAL",
        "EscalateToHuman", "RequestCallback", "EndConversation",
    ):
        assert behavior_token in raw_prompt, f"Cara prompt missing {behavior_token}"
    assert "Never ask the caller to confirm their identity again" in raw_prompt
    assert "SAFETY ALWAYS OVERRIDES EVERY OTHER CONVERSATIONAL INTENT OR STATE" in raw_prompt
    assert "resume_state" in raw_prompt
    assert "safety_medical" in raw_prompt and "safety_behavioral" in raw_prompt
    variables = re.findall(r"\{\{\$\.[^{}]+\}\}", raw_prompt)
    assert len(variables) == len(set(variables)), "Q prompt variables must be unique"

    flow = json.loads(cfg.flow_path.read_text(encoding="utf-8"))
    actions = flow["Actions"]
    logging = next(a for a in actions if a["Type"] == "UpdateFlowLoggingBehavior")
    assert "Errors" not in logging["Transitions"]
    lex_actions = [a for a in actions if a["Type"] == "ConnectParticipantWithLexBot"]
    assert len(lex_actions) == 9
    identity_actions = [a for a in lex_actions if a["Parameters"]["LexV2Bot"]["AliasArn"] == "${IdentityLexBotAliasArn}"]
    availability_actions = [a for a in lex_actions if a["Parameters"]["LexV2Bot"]["AliasArn"] == "${AvailabilityLexBotAliasArn}"]
    coaching_actions = [a for a in lex_actions if a["Parameters"]["LexV2Bot"]["AliasArn"] == "${LexBotAliasArn}"]
    assert len(identity_actions) == 5 and len(availability_actions) == 3 and len(coaching_actions) == 1
    assert {a["Parameters"]["LexSessionAttributes"]["caraHealthBotPhase"] for a in identity_actions} == {"identity-1", "identity-2", "identity-3", "handoff-identity-1", "handoff-identity-2"}
    assert all(
        a["Parameters"]["LexSessionAttributes"].get("expectedCustomerName") == "$.Attributes.customerName"
        for a in identity_actions
    )
    assert cfg.identity_nlu_confidence_threshold >= 0.90
    assert {a["Parameters"]["LexSessionAttributes"]["caraHealthBotPhase"] for a in availability_actions} == {"third-party-availability-1", "third-party-availability-2", "patient-unavailable-callback"}
    assert coaching_actions[0]["Parameters"]["LexSessionAttributes"]["caraHealthBotPhase"] == "coaching"
    coaching_errors = {
        e["ErrorType"]: e["NextAction"]
        for e in coaching_actions[0]["Transitions"].get("Errors", [])
    }
    assert coaching_errors.get("NoMatchingCondition") == "b0000000-0000-4000-8000-000000000001", (
        "QinConnect NoMatchingCondition must route to the Return-to-Control Tool router"
    )
    compares = [a for a in actions if a["Type"] == "Compare"]
    assert len(compares) == 10
    compare_values = [a["Parameters"]["ComparisonValue"] for a in compares]
    assert compare_values.count("$.Lex.SessionAttributes.Tool") == 1
    assert compare_values.count("$.Lex.SessionAttributes.endReason") == 1
    assert compare_values.count("$.External.identityMatch") == 4
    assert compare_values.count("$.External.available") == 2
    assert compare_values.count("$.Attributes.callMode") == 1
    assert compare_values.count("$.Attributes.humanAgentPhoneNumber") == 1

    identifiers = [a["Identifier"] for a in actions]
    assert len(identifiers) == len(set(identifiers)), "contact-flow action identifiers must be unique"
    action_ids = set(identifiers)
    for action in actions:
        transitions = action.get("Transitions", {})
        targets = []
        if transitions.get("NextAction"):
            targets.append(transitions["NextAction"])
        targets += [x.get("NextAction") for x in transitions.get("Conditions", [])]
        targets += [x.get("NextAction") for x in transitions.get("Errors", [])]
        for target in targets:
            assert target in action_ids, f"flow action {action['Identifier']} points to missing action {target}"

    actions_by_id = {a["Identifier"]: a for a in actions}
    identity_1 = actions_by_id["10000000-0000-4000-8000-000000000001"]
    identity_2 = actions_by_id["10000000-0000-4000-8000-000000000003"]
    first_routes = {
        c["Condition"]["Operands"][0]: c["NextAction"]
        for c in identity_1["Transitions"].get("Conditions", [])
    }
    second_routes = {
        c["Condition"]["Operands"][0]: c["NextAction"]
        for c in identity_2["Transitions"].get("Conditions", [])
    }
    assert first_routes["SafetyMedical"] == "d0000000-0000-4000-8000-000000000001"
    assert first_routes["SafetyBehavioral"] == "d0000000-0000-4000-8000-000000000002"
    assert first_routes["IdentityConfirmed"] == "90000000-0000-4000-8000-000000000004"
    assert first_routes["IdentityDenied"] == "e0000000-0000-4000-8000-000000000003"
    assert first_routes["PatientUnavailable"] == "e0000000-0000-4000-8000-000000000004"
    assert first_routes["ThirdPartyDetected"] == "e0000000-0000-4000-8000-000000000003"
    assert first_routes["RepresentativeDetected"] == "e0000000-0000-4000-8000-000000000005"
    assert first_routes["WrongNumber"] == "e0000000-0000-4000-8000-000000000001"
    assert first_routes["Deceased"] == "c0000000-0000-4000-8000-000000000003"
    assert first_routes["CallRefusal"] == "c0000000-0000-4000-8000-000000000004"
    assert first_routes["IdentityAmbiguous"] == "10000000-0000-4000-8000-000000000003"
    assert first_routes["FallbackIntent"] == "10000000-0000-4000-8000-000000000003"
    assert second_routes["SafetyMedical"] == "d0000000-0000-4000-8000-000000000001"
    assert second_routes["SafetyBehavioral"] == "d0000000-0000-4000-8000-000000000002"
    assert second_routes["IdentityConfirmed"] == "90000000-0000-4000-8000-000000000004"
    assert second_routes["PatientUnavailable"] == "e0000000-0000-4000-8000-000000000004"
    assert second_routes["ThirdPartyDetected"] == "e0000000-0000-4000-8000-000000000003"
    assert second_routes["IdentityDenied"] == "e0000000-0000-4000-8000-000000000003"
    assert second_routes["IdentityAmbiguous"] == "10000000-0000-4000-8000-000000000007"
    assert second_routes["FallbackIntent"] == "10000000-0000-4000-8000-000000000007"
    assert identity_2["Transitions"]["NextAction"] == "10000000-0000-4000-8000-000000000007"

    identity_3 = actions_by_id["10000000-0000-4000-8000-000000000007"]
    third_routes = {
        c["Condition"]["Operands"][0]: c["NextAction"]
        for c in identity_3["Transitions"].get("Conditions", [])
    }
    assert third_routes["IdentityConfirmed"] == "90000000-0000-4000-8000-000000000004"
    assert third_routes["IdentityAmbiguous"] == "e0000000-0000-4000-8000-000000000006"
    assert third_routes["FallbackIntent"] == "e0000000-0000-4000-8000-000000000006"
    assert identity_3["Transitions"]["NextAction"] == "e0000000-0000-4000-8000-000000000006"

    assert actions_by_id["90000000-0000-4000-8000-000000000004"]["Parameters"]["Attributes"]["identityResult"] == "Confirmed"
    assert actions_by_id["90000000-0000-4000-8000-000000000005"]["Parameters"]["Attributes"]["identityResult"] == "Confirmed"
    assert actions_by_id["e0000000-0000-4000-8000-000000000001"]["Parameters"]["Attributes"]["identityResult"] == "Denied"
    assert actions_by_id["e0000000-0000-4000-8000-000000000002"]["Parameters"]["Attributes"]["identityResult"] == "Ambiguous"
    assert actions_by_id["e0000000-0000-4000-8000-000000000006"]["Parameters"]["Attributes"]["identityResult"] == "Ambiguous"
    assert actions_by_id["e0000000-0000-4000-8000-000000000006"]["Transitions"]["NextAction"] == "10000000-0000-4000-8000-000000000005"
    timeout_route = next(e for e in identity_2["Transitions"]["Errors"] if e["ErrorType"] == "InputTimeLimitExceeded")
    assert timeout_route["NextAction"] == "e0000000-0000-4000-8000-000000000002"

    availability_1 = actions_by_id["a0000000-0000-4000-8000-000000000001"]
    availability_routes = {
        c["Condition"]["Operands"][0]: c["NextAction"]
        for c in availability_1["Transitions"].get("Conditions", [])
    }
    assert availability_routes["SafetyMedical"] == "d0000000-0000-4000-8000-000000000001"
    assert availability_routes["SafetyBehavioral"] == "d0000000-0000-4000-8000-000000000002"
    assert availability_routes["TargetAvailableNow"] == "a0000000-0000-4000-8000-000000000006"
    assert availability_routes["TargetUnavailable"] == "a0000000-0000-4000-8000-000000000011"
    patient_unavailable = actions_by_id["a0000000-0000-4000-8000-000000000011"]
    assert patient_unavailable["Parameters"]["Text"] == "$.Attributes.patientUnavailablePrompt"
    patient_routes = {
        c["Condition"]["Operands"][0]: c["NextAction"]
        for c in patient_unavailable["Transitions"].get("Conditions", [])
    }
    assert patient_routes["SafetyMedical"] == "d0000000-0000-4000-8000-000000000001"
    assert patient_routes["SafetyBehavioral"] == "d0000000-0000-4000-8000-000000000002"
    assert patient_routes["TargetUnavailable"] == "a0000000-0000-4000-8000-000000000007"
    callback = actions_by_id["a0000000-0000-4000-8000-000000000007"]
    assert callback["Parameters"]["Attributes"]["callbackDate"] == "$.Lex.Slots.callbackDate"
    assert callback["Parameters"]["Attributes"]["callbackTime"] == "$.Lex.Slots.callbackTime"

    transfer_prompt = actions_by_id["90000000-0000-4000-8000-000000000003"]
    set_queue = actions_by_id["90000000-0000-4000-8000-000000000001"]
    transfer_queue = actions_by_id["90000000-0000-4000-8000-000000000002"]
    assert transfer_prompt["Type"] == "MessageParticipant"
    assert transfer_prompt["Transitions"]["NextAction"] == "90000000-0000-4000-8000-000000000001"
    assert set_queue["Type"] == "UpdateContactTargetQueue"
    assert set_queue["Parameters"]["QueueId"] == "${HumanTransferQueueArn}"
    assert set_queue["Transitions"]["NextAction"] == "90000000-0000-4000-8000-000000000002"
    assert transfer_queue["Type"] == "TransferContactToQueue"
    assert actions_by_id["90000000-0000-4000-8000-000000000004"]["Transitions"]["NextAction"] == "33333333-3333-4333-8333-333333333333"
    coaching = actions_by_id["55555555-5555-4555-8555-555555555555"]
    coaching_routes = {
        c["Condition"]["Operands"][0]: c["NextAction"]
        for c in coaching["Transitions"].get("Conditions", [])
    }
    assert coaching_routes["SafetyMedical"] == "d0000000-0000-4000-8000-000000000001"
    assert coaching_routes["SafetyBehavioral"] == "d0000000-0000-4000-8000-000000000002"
    outcome_router = actions_by_id["b0000000-0000-4000-8000-000000000001"]
    outcome_routes = {
        c["Condition"]["Operands"][0]: c["NextAction"]
        for c in outcome_router["Transitions"]["Conditions"]
    }
    assert set(outcome_routes) == {"EscalateToHuman", "RequestCallback", "EndConversation"}
    end_reason_router = actions_by_id["b0000000-0000-4000-8000-000000000008"]
    assert end_reason_router["Parameters"]["ComparisonValue"] == "$.Lex.SessionAttributes.endReason"
    end_reason_routes = {
        c["Condition"]["Operands"][0]: c["NextAction"]
        for c in end_reason_router["Transitions"]["Conditions"]
    }
    assert end_reason_routes == {
        "safety_medical": "d0000000-0000-4000-8000-000000000001",
        "safety_behavioral": "d0000000-0000-4000-8000-000000000002",
    }
    assert actions_by_id["d0000000-0000-4000-8000-000000000003"]["Parameters"]["Text"] == "${CaraSafetyMedicalResponse}"
    assert actions_by_id["d0000000-0000-4000-8000-000000000004"]["Parameters"]["Text"] == "${CaraSafetyBehavioralResponse}"
    callback_outcome = actions_by_id["b0000000-0000-4000-8000-000000000002"]["Parameters"]["Attributes"]
    assert callback_outcome["callbackWhen"] == "$.Lex.SessionAttributes.callbackWhen"
    assert callback_outcome["callbackReason"] == "$.Lex.SessionAttributes.callbackReason"

    invokes = [a for a in actions if a["Type"] == "InvokeLambdaFunction"]
    operations = [a["Parameters"]["LambdaInvocationAttributes"]["operation"] for a in invokes]
    assert operations.count("initialize") == 1
    assert operations.count("verifyIdentityName") == 4
    assert "confirmIdentity" not in json.dumps(flow)
    assert "$.Lex.SessionAttributes.Tool" in json.dumps(flow)
    recordings = [a for a in actions if a["Type"] == "UpdateContactRecordingBehavior"]
    assert len(recordings) == 1
    assert recordings[0]["Parameters"]["RecordingBehavior"]["IVRRecordingBehavior"] == "Enabled"
    assert recordings[0]["Parameters"]["RecordingBehavior"]["RecordedParticipants"] == ["Agent", "Customer"]

    account = "123456789012"
    assistant_id = "11111111-2222-3333-4444-555555555555"
    assistant_arn = f"arn:aws:wisdom:{cfg.region}:{account}:assistant/{assistant_id}"
    instance_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    instance_arn = f"arn:aws:connect:{cfg.region}:{account}:instance/{instance_id}"
    bot_id = "ABCDEFGHIJ"
    identity_bot_id = "ZYXWVUTSRQ"
    availability_bot_id = "QWERTYUIOP"
    role_arn = f"arn:aws:iam::{account}:role/{cfg.lex_runtime_role_name}"
    identity_role_arn = f"arn:aws:iam::{account}:role/{cfg.identity_lex_runtime_role_name}"
    prompt_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    agent_id = "ffffffff-1111-2222-3333-444444444444"
    prompt_version_id = f"{prompt_id}:1"
    alias_arn = f"arn:aws:lex:{cfg.region}:{account}:bot-alias/{bot_id}/KLMNOPQRST"
    identity_alias_arn = f"arn:aws:lex:{cfg.region}:{account}:bot-alias/{identity_bot_id}/TSRQPONMLK"
    availability_alias_arn = f"arn:aws:lex:{cfg.region}:{account}:bot-alias/{availability_bot_id}/ASDFGHJKLZ"
    lambda_arn = f"arn:aws:lambda:{cfg.region}:{account}:function:{cfg.session_context_lambda_name}"
    lambda_role_arn = f"arn:aws:iam::{account}:role/{cfg.session_context_lambda_role_name}"
    lex_log_group = cfg.lex_conversation_log_group(account)
    lex_log_arn = f"arn:aws:logs:{cfg.region}:{account}:log-group:{lex_log_group}"

    q = client("qconnect", cfg.region)
    lex = client("lexv2-models", cfg.region)
    connect = client("connect", cfg.region)
    lambda_client = client("lambda", cfg.region)
    iam_client = client("iam", cfg.region)
    logs_client = client("logs", cfg.region)
    transcribe_client = client("transcribe", cfg.region)

    # Fresh-account creation request shapes. Cara Health Bot owns these resources
    # and never needs IDs from a legacy Talking Bot deployment.
    validate_api(connect, "CreateInstance", {
        "IdentityManagementType": "CONNECT_MANAGED",
        "InstanceAlias": cfg.instance_alias(account),
        "InboundCallsEnabled": True,
        "OutboundCallsEnabled": True,
        "Tags": {"Project": cfg.project_name},
        "ClientToken": "00000000-0000-4000-8000-000000000000",
    })
    validate_api(q, "CreateAssistant", {
        "name": cfg.assistant_name,
        "type": "AGENT",
        "description": "Dedicated Amazon Q in Connect assistant for Cara Health Bot",
        "tags": {"Project": cfg.project_name, "AmazonConnectEnabled": "True"},
        "clientToken": "00000000-0000-4000-8000-000000000000",
    })
    validate_api(connect, "CreateIntegrationAssociation", {
        "InstanceId": instance_id,
        "IntegrationType": "WISDOM_ASSISTANT",
        "IntegrationArn": assistant_arn,
        "Tags": {"Project": cfg.project_name},
    })
    validate_api(q, "RemoveAssistantAIAgent", {
        "assistantId": assistant_id,
        "aiAgentType": "ORCHESTRATION",
        "orchestratorUseCase": "Connect.SelfService",
    })
    validate_api(connect, "DeleteIntegrationAssociation", {
        "InstanceId": instance_id,
        "IntegrationAssociationId": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    })
    validate_api(connect, "SearchAvailablePhoneNumbers", {
        "InstanceId": instance_id,
        "PhoneNumberCountryCode": cfg.phone_country_code,
        "PhoneNumberType": cfg.phone_number_type,
        "MaxResults": 5,
    })
    validate_api(connect, "ClaimPhoneNumber", {
        "InstanceId": instance_id,
        "PhoneNumber": "+18775550123",
        "PhoneNumberDescription": "Cara Health Bot outbound source number",
        "Tags": {"Project": cfg.project_name},
        "ClientToken": "00000000-0000-4000-8000-000000000000",
    })
    validate_api(connect, "AssociateInstanceStorageConfig", {
        "InstanceId": instance_id,
        "ResourceType": "CALL_RECORDINGS",
        "StorageConfig": {"StorageType": "S3", "S3Config": {
            "BucketName": cfg.recording_bucket(account),
            "BucketPrefix": cfg.recording_prefix,
        }},
        "ClientToken": "00000000-0000-4000-8000-000000000000",
    })
    validate_api(connect, "UpdateInstanceStorageConfig", {
        "InstanceId": instance_id,
        "AssociationId": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "ResourceType": "CALL_RECORDINGS",
        "StorageConfig": {"StorageType": "S3", "S3Config": {
            "BucketName": cfg.recording_bucket(account),
            "BucketPrefix": cfg.recording_prefix,
        }},
    })
    validate_api(transcribe_client, "StartTranscriptionJob", {
        "TranscriptionJobName": "cara-health-bot-test-contact",
        "LanguageCode": "en-US",
        "MediaFormat": "wav",
        "Media": {"MediaFileUri": f"s3://{cfg.recording_bucket(account)}/transcribe-input/contact.wav"},
        "OutputBucketName": cfg.recording_bucket(account),
        "OutputKey": f"{cfg.transcript_prefix}/contact.json",
        "Settings": {"ChannelIdentification": True},
    })
    validate_api(transcribe_client, "DeleteTranscriptionJob", {
        "TranscriptionJobName": "cara-health-bot-test-contact",
    })

    validate_api(q, "CreateAIPrompt", q_prompt_create_request(cfg, assistant_id, raw_prompt))
    validate_api(q, "UpdateAIPrompt", q_prompt_update_request(cfg, assistant_id, prompt_id, raw_prompt))
    agent_cfg = q_agent_configuration(cfg, instance_arn, prompt_version_id)
    tool_names = {x["toolName"] for x in agent_cfg["orchestrationAIAgentConfiguration"]["toolConfigurations"]}
    assert tool_names == {"EscalateToHuman", "RequestCallback", "EndConversation"}
    validate_api(q, "CreateAIAgent", q_agent_create_request(cfg, assistant_id, instance_arn, prompt_version_id))
    validate_api(q, "UpdateAIAgent", q_agent_update_request(cfg, assistant_id, instance_arn, agent_id, prompt_version_id))

    validate_api(lex, "CreateBot", lex_bot_create_request(cfg, role_arn))
    validate_api(lex, "UpdateBot", lex_bot_update_request(cfg, bot_id, role_arn))
    validate_api(lex, "CreateBotLocale", lex_locale_request(cfg, bot_id))
    validate_api(lex, "CreateIntent", lex_qinconnect_intent_request(cfg, bot_id, assistant_arn))
    validate_api(lex, "CreateIntent", safety_medical_intent_request(cfg, bot_id))
    validate_api(lex, "CreateIntent", safety_behavioral_intent_request(cfg, bot_id))
    validate_api(lex, "CreateIntent", lex_fallback_intent_request(cfg, bot_id))
    alias_req = lex_alias_request(cfg, bot_id, "1", lex_log_arn)
    validate_api(lex, "CreateBotAlias", alias_req)
    validate_api(lex, "UpdateBotAlias", {"botAliasId": "KLMNOPQRST", **alias_req})

    validate_api(lex, "CreateBot", identity_lex_bot_create_request(cfg, identity_role_arn))
    validate_api(lex, "UpdateBot", identity_lex_bot_update_request(cfg, identity_bot_id, identity_role_arn))
    validate_api(lex, "CreateBotLocale", identity_lex_locale_request(cfg, identity_bot_id))
    for builder in (
        identity_confirmed_intent_request,
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
        identity_fallback_intent_request,
    ):
        validate_api(lex, "CreateIntent", builder(cfg, identity_bot_id))
    identity_alias_req = identity_lex_alias_request(cfg, identity_bot_id, "1", lex_log_arn)
    validate_api(lex, "CreateBotAlias", identity_alias_req)
    validate_api(lex, "UpdateBotAlias", {"botAliasId": "TSRQPONMLK", **identity_alias_req})

    validate_api(lex, "CreateBot", availability_lex_bot_create_request(cfg, identity_role_arn))
    validate_api(lex, "UpdateBot", availability_lex_bot_update_request(cfg, availability_bot_id, identity_role_arn))
    validate_api(lex, "CreateBotLocale", availability_lex_locale_request(cfg, availability_bot_id))
    validate_api(lex, "CreateIntent", availability_now_intent_request(cfg, availability_bot_id))
    unavailable_req = availability_unavailable_intent_request(cfg, availability_bot_id)
    validate_api(lex, "CreateIntent", unavailable_req)
    validate_api(lex, "CreateIntent", availability_unknown_intent_request(cfg, availability_bot_id))
    validate_api(lex, "CreateIntent", safety_medical_intent_request(cfg, availability_bot_id))
    validate_api(lex, "CreateIntent", safety_behavioral_intent_request(cfg, availability_bot_id))
    validate_api(lex, "CreateIntent", availability_fallback_intent_request(cfg, availability_bot_id))
    date_slot_req = availability_callback_date_slot_request(cfg, availability_bot_id, "MNBVCXZLKJ")
    time_slot_req = availability_callback_time_slot_request(cfg, availability_bot_id, "MNBVCXZLKJ")
    validate_api(lex, "CreateSlot", date_slot_req)
    validate_api(lex, "CreateSlot", time_slot_req)
    validate_api(lex, "UpdateSlot", {"slotId": "POIUYTREWA", **date_slot_req})
    validate_api(lex, "UpdateSlot", {"slotId": "LKJHGFDSAZ", **time_slot_req})
    final_unavailable = availability_unavailable_intent_request(cfg, availability_bot_id, slot_priorities=[
        {"priority": 1, "slotId": "POIUYTREWA"},
        {"priority": 2, "slotId": "LKJHGFDSAZ"},
    ])
    validate_api(lex, "UpdateIntent", {"intentId": "MNBVCXZLKJ", **final_unavailable})
    availability_alias_req = availability_lex_alias_request(cfg, availability_bot_id, "1", lex_log_arn)
    validate_api(lex, "CreateBotAlias", availability_alias_req)
    validate_api(lex, "UpdateBotAlias", {"botAliasId": "ASDFGHJKLZ", **availability_alias_req})

    validate_api(connect, "AssociateBot", {"InstanceId": instance_id, "LexV2Bot": {"AliasArn": alias_arn}, "ClientToken": "00000000-0000-4000-8000-000000000000"})
    validate_api(connect, "AssociateBot", {"InstanceId": instance_id, "LexV2Bot": {"AliasArn": identity_alias_arn}, "ClientToken": "00000000-0000-4000-8000-000000000000"})
    validate_api(connect, "AssociateBot", {"InstanceId": instance_id, "LexV2Bot": {"AliasArn": availability_alias_arn}, "ClientToken": "00000000-0000-4000-8000-000000000000"})

    routing_profile_id = "11111111-2222-3333-4444-555555555555"
    queue_id = "22222222-3333-4444-5555-666666666666"
    hours_id = "55555555-6666-7777-8888-999999999999"
    security_profile_id = "33333333-4444-5555-6666-777777777777"
    validate_api(connect, "CreateHoursOfOperation", {
        "InstanceId": instance_id,
        "Name": "CaraHealthBotHours",
        "Description": "24x7 hours for Cara Health Bot human transfer testing",
        "TimeZone": "UTC",
        "Config": [
            {
                "Day": day,
                "StartTime": {"Hours": 0, "Minutes": 0},
                "EndTime": {"Hours": 23, "Minutes": 59},
            }
            for day in ("SUNDAY", "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY")
        ],
        "Tags": {"Project": cfg.project_name},
    })
    validate_api(connect, "CreateQueue", {
        "InstanceId": instance_id,
        "Name": cfg.human_transfer_queue_name,
        "Description": "Cara Health Bot human specialist transfer queue",
        "HoursOfOperationId": hours_id,
        "Tags": {"Project": cfg.project_name, "Purpose": "HumanTransfer"},
    })
    validate_api(connect, "UpdateQueueStatus", {
        "InstanceId": instance_id, "QueueId": queue_id, "Status": "ENABLED",
    })
    validate_api(connect, "CreateRoutingProfile", {
        "InstanceId": instance_id,
        "Name": cfg.human_agent_routing_profile_name,
        "Description": "Cara Health Bot human specialist routing profile",
        "DefaultOutboundQueueId": queue_id,
        "QueueConfigs": [{
            "QueueReference": {"QueueId": queue_id, "Channel": "VOICE"},
            "Priority": 1, "Delay": 0,
        }],
        "MediaConcurrencies": [{"Channel": "VOICE", "Concurrency": 1}],
        "Tags": {"Project": cfg.project_name, "Purpose": "HumanTransfer"},
    })
    validate_api(connect, "CreateSecurityProfile", {
        "InstanceId": instance_id,
        "SecurityProfileName": cfg.human_agent_security_profile_name,
        "Description": "Cara Health Bot human specialist security profile",
        "Permissions": ["BasicAgentAccess"],
        "Tags": {"Project": cfg.project_name, "Purpose": "HumanTransfer"},
    })
    validate_api(connect, "UpdateSecurityProfile", {
        "InstanceId": instance_id,
        "SecurityProfileId": security_profile_id,
        "Description": "Cara Health Bot human specialist security profile",
        "Permissions": ["BasicAgentAccess"],
    })
    user_id = "44444444-5555-6666-7777-888888888888"
    queue_cfg = {
        "QueueReference": {"QueueId": queue_id, "Channel": "VOICE"},
        "Priority": 1,
        "Delay": 0,
    }
    validate_api(connect, "AssociateRoutingProfileQueues", {
        "InstanceId": instance_id,
        "RoutingProfileId": routing_profile_id,
        "QueueConfigs": [queue_cfg],
    })
    validate_api(connect, "UpdateRoutingProfileQueues", {
        "InstanceId": instance_id,
        "RoutingProfileId": routing_profile_id,
        "QueueConfigs": [queue_cfg],
    })
    validate_api(connect, "CreateUser", {
        "InstanceId": instance_id,
        "Username": cfg.human_agent_username,
        "Password": "ValidAgent1!",
        "IdentityInfo": {"FirstName": cfg.human_agent_first_name, "LastName": cfg.human_agent_last_name},
        "PhoneConfig": {"PhoneType": "SOFT_PHONE", "AutoAccept": False, "AfterContactWorkTimeLimit": cfg.human_agent_after_contact_work_seconds},
        "RoutingProfileId": routing_profile_id,
        "SecurityProfileIds": [security_profile_id],
        "Tags": {"Project": cfg.project_name, "Purpose": "HumanTransferAgent"},
    })
    validate_api(connect, "UpdateUserRoutingProfile", {
        "InstanceId": instance_id, "UserId": user_id, "RoutingProfileId": routing_profile_id,
    })
    validate_api(connect, "UpdateUserSecurityProfiles", {
        "InstanceId": instance_id, "UserId": user_id, "SecurityProfileIds": [security_profile_id],
    })
    validate_api(connect, "UpdateUserIdentityInfo", {
        "InstanceId": instance_id, "UserId": user_id,
        "IdentityInfo": {"FirstName": cfg.human_agent_first_name, "LastName": cfg.human_agent_last_name},
    })
    validate_api(connect, "UpdateUserPhoneConfig", {
        "InstanceId": instance_id, "UserId": user_id,
        "PhoneConfig": {"PhoneType": "SOFT_PHONE", "AutoAccept": False, "AfterContactWorkTimeLimit": cfg.human_agent_after_contact_work_seconds},
    })

    validate_api(connect, "StartOutboundVoiceContact", {
        "DestinationPhoneNumber": "+14155550123", "ContactFlowId": instance_id,
        "InstanceId": instance_id, "SourcePhoneNumber": "+18665551212",
        "ClientToken": "00000000-0000-4000-8000-000000000000",
        "Name": "Cara Health Bot identity-gated conversation", "Description": "Consented outbound Cara Health Bot call",
        "TrafficType": "GENERAL",
        "Attributes": {
            "customerName": "Anish", "expectedPhone": "+14155550123",
            "identityPolicyVersion": "v6-cara-conversational",
            "identityPrompt": "Hi, may I speak with Anish?",
            "identityClarification": "I'm Cara, an automated assistant. I can explain more once I confirm I'm speaking with Anish. Am I speaking with Anish?",
            "identityFailureMessage": "Thanks. I need to speak directly with Anish, so I'll end the call here. Have a good day.",
            "thirdPartyAvailabilityPrompt": "Thanks. I need to speak directly with Anish. Is Anish available to come to the phone?",
            "thirdPartyAvailabilityClarification": "Just to clarify, is Anish available to come to the phone now?",
            "representativeResponse": "Thanks for letting me know. I can only continue directly with Anish. Is Anish available to come to the phone?",
            "wrongNumberResponse": "Thanks for letting me know. I apologize for the inconvenience. Have a good day.",
            "deceasedResponse": "I'm so sorry for your loss. Thank you for letting me know.",
            "refusalResponse": "Understood. I won't continue this call. Thank you for your time.",
            "passPhonePrompt": "Thanks. Please pass the phone to Anish.",
            "handoffIdentityPrompt": "Hi. May I confirm I'm speaking with Anish?",
            "coachingGreeting": "Thanks, Anish. I'm Cara, an automated assistant. I can connect you with a human specialist who can help further. Is now a good time for a quick handoff?",
        },
    })
    validate_api(lambda_client, "CreateFunction", {
        "FunctionName": cfg.session_context_lambda_name, "Runtime": "python3.12", "Role": lambda_role_arn,
        "Handler": "session_context.handler", "Code": {"ZipFile": b"PK-test"}, "Description": "Cara Health Bot identity context",
        "Timeout": 8, "MemorySize": 128, "Publish": False, "Tags": {"Project": cfg.project_name},
    })

    assert "wisdom:UpdateSessionData" in json.dumps(session_context_lambda_permissions(cfg.region, account, assistant_id, cfg.session_context_lambda_name))
    assert "logs:PutLogEvents" in json.dumps(lex_runtime_permissions(cfg.region, account, assistant_id, assistant_arn, lex_log_group))
    assert "logs:PutLogEvents" in json.dumps(identity_lex_runtime_permissions(cfg.region, account, lex_log_group))

    rendered = render_contact_flow(cfg, assistant_id, assistant_arn, alias_arn, identity_alias_arn, availability_alias_arn, lambda_arn, f"arn:aws:connect:{cfg.region}:{account}:instance/{instance_id}/queue/ffffffff-1111-2222-3333-444444444444")
    text = json.dumps(json.loads(rendered))
    assert assistant_arn in text and alias_arn in text and identity_alias_arn in text and availability_alias_arn in text and lambda_arn in text
    assert "ffffffff-1111-2222-3333-444444444444" in text
    assert cfg.cara_behavior["transferMessage"] in text
    assert cfg.cara_behavior["callbackResponses"]["endMessage"] in text
    assert cfg.cara_behavior["safetyMedicalResponse"] in text
    assert cfg.cara_behavior["safetyBehavioralResponse"] in text
    assert all(name in text for name in (
        "IdentityConfirmed", "IdentityDenied", "IdentityAmbiguous", "ThirdPartyDetected",
        "PatientUnavailable", "WrongNumber", "RepresentativeDetected", "Deceased", "CallRefusal",
        "SafetyMedical", "SafetyBehavioral",
    ))
    assert "TargetAvailableNow" in text and "TargetUnavailable" in text
    assert '"Type": "Compare"' in text
    assert "$.Lex.SessionAttributes.Tool" in text
    assert text.find(identity_alias_arn) < text.find(assistant_arn)
    assert "x-amz-lex:q-in-connect:ai-agent-arn" not in text

    campaign_files = [
        cfg.root / "lambda" / "campaign_intake.py",
        cfg.root / "lambda" / "campaign_dialer.py",
        cfg.root / "cara_health_bot" / "campaign_deployer.py",
        cfg.root / "scripts" / "deploy_campaign.py",
        cfg.root / "deploy-campaign.sh",
    ]
    assert all(path.is_file() for path in campaign_files)
    assert not (cfg.root / "campaign").exists(), "campaign deployment must not depend on CDK"
    campaign_text = "\n".join(path.read_text(encoding="utf-8") for path in campaign_files if path.suffix == ".py")
    for required in (
        "contactId-index", "StartOutboundVoiceContact", "DescribeContact",
        "CALL_SETUP_FAILED", "ConditionalCheckFailedException",
        "scheduler:CreateSchedule", "put_bucket_notification_configuration",
        "Connect Customer Contact Event", "DISCONNECTED",
    ):
        assert required in campaign_text
    assert "aws_cdk" not in campaign_text
    assert "connect:InstanceId" not in campaign_text, "StartOutboundVoiceContact must not use unsupported IAM condition scoping"

    print("Validation passed:")
    print("- Python syntax and stateful Cara conversational prompt")
    print("- semantic identity recipient handling plus privacy-minimal third-party availability flow")
    print("- safety-first semantic handling across identity, third-party availability, and Cara conversation")
    print("- dedicated configured medical and behavioral safety exits override transfer/callback/refusal")
    print("- Cara Return-to-Control outcomes: transfer, callback, and respectful end")
    print("- human Connect agent create/reuse, queue/routing/security, and soft-phone request shapes")
    print("- separate identity, availability, and Nova 2 Sonic Lex request shapes")
    print("- callback AMAZON.Date / AMAZON.Time slot request shapes")
    print("- all three Live aliases have Lex text conversation logs")
    print("- Q/Connect/Lex/Lambda/S3-storage/Transcribe start/delete request shapes")
    print("- automated/IVR recording is enabled before the identity gate")
    print("- transcript source is one stereo Connect recording: ch_0 Cara, ch_1 Customer")
    print("- outbound campaign S3/DynamoDB/Scheduler/dialer workaround and identityResult persistence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
