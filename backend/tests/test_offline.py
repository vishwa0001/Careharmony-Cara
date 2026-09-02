from __future__ import annotations

import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from botocore.exceptions import ClientError

from cara_health_bot.builders import (
    identity_ambiguous_intent_request,
    identity_confirmed_intent_request,
    identity_named_confirmation_intent_request,
    identity_first_name_slot_request,
    identity_last_name_slot_request,
    identity_denied_intent_request,
    third_party_detected_intent_request,
    patient_unavailable_intent_request,
    wrong_number_intent_request,
    representative_detected_intent_request,
    deceased_intent_request,
    call_refusal_intent_request,
    safety_medical_intent_request,
    safety_behavioral_intent_request,
    render_cara_prompt,
    availability_now_intent_request,
    availability_unavailable_intent_request,
    availability_unknown_intent_request,
    availability_callback_date_slot_request,
    availability_callback_time_slot_request,
    identity_lex_alias_request,
    identity_lex_runtime_permissions,
    lex_alias_request,
    lex_qinconnect_intent_request,
    lex_runtime_permissions,
    q_agent_configuration,
    render_contact_flow,
    session_context_lambda_permissions,
)
from cara_health_bot.config import load_config
from cara_health_bot.deployer import CaraHealthBotDeployer


class CaraHealthBotOfflineTests(unittest.TestCase):
    def test_display_name_is_cara_health_bot(self):
        self.assertEqual(self.cfg.display_name, "Cara Health Bot")


    def test_full_internal_rename_uses_cara_health_bot_resources(self):
        self.assertEqual(self.cfg.project_name, "CaraHealthBot")
        self.assertEqual(self.cfg.connect_instance_alias_base, "cara-health-bot")
        self.assertEqual(self.cfg.bot_name, "cara-health-bot-nova-2-sonic")
        self.assertEqual(self.cfg.identity_bot_name, "cara-health-bot-identity-v341")
        self.assertEqual(self.cfg.availability_bot_name, "cara-health-bot-availability")
        self.assertEqual(self.cfg.flow_name, "CaraHealthBotNova2Sonic")
        self.assertEqual(self.cfg.session_context_lambda_name, "cara-health-bot-session-context")
        self.assertEqual(self.cfg.human_agent_username, "caraagent")
        self.assertEqual(self.cfg.recording_bucket(self.account), f"cara-health-bot-recordings-{self.account}-us-east-1")

    def test_standalone_deployment_never_borrows_another_q_assistant(self):
        source = (self.cfg.root / "cara_health_bot" / "deployer.py").read_text(encoding="utf-8")
        config_raw = (self.cfg.root / "config.json").read_text(encoding="utf-8")
        self.assertNotIn("assistantReuseCandidates", config_raw)
        self.assertNotIn("TALKING_BOT_REUSE_ASSISTANT_ID", source)
        self.assertNotIn("shared-existing", source)
        self.assertIn("will not reuse another project's assistant", source)

    def test_deploy_has_no_legacy_talking_bot_dependency(self):
        root = self.cfg.root
        deploy = (root / "deploy.sh").read_text(encoding="utf-8")
        self.assertNotIn("REPLACE_TALKING_BOT_WITH_CARA_HEALTH_BOT", deploy)
        self.assertNotIn("LEGACY_TALKING_BOT_STATE", deploy)
        self.assertNotIn("cleanup_legacy_talking_bot.py", deploy)
        self.assertFalse((root / "scripts" / "cleanup_legacy_talking_bot.py").exists())
        self.assertIn("standalone stack", deploy)

    def test_same_name_external_resources_are_not_silently_reused(self):
        source = (self.cfg.root / "cara_health_bot" / "deployer.py").read_text(encoding="utf-8")
        self.assertIn("Refusing to reuse another deployment's instance", source)
        self.assertIn("Refusing to reuse another deployment's assistant", source)
        self.assertIn('tags.get("Project") != self.cfg.project_name', source)

    def test_cleanup_unbinds_q_resources_before_deletion(self):
        cleanup = (self.cfg.root / "scripts" / "cleanup.py").read_text(encoding="utf-8")
        self.assertIn("remove_assistant_ai_agent", cleanup)
        self.assertIn("delete_integration_association", cleanup)
        self.assertLess(cleanup.index("remove_assistant_ai_agent"), cleanup.index("delete_ai_agent"))
        self.assertLess(cleanup.index("delete_integration_association"), cleanup.index("delete_assistant"))

    @classmethod
    def setUpClass(cls):
        cls.cfg = load_config()
        cls.account = "123456789012"
        cls.assistant_id = "11111111-2222-3333-4444-555555555555"
        cls.assistant_arn = f"arn:aws:wisdom:us-east-1:{cls.account}:assistant/{cls.assistant_id}"
        cls.instance_arn = f"arn:aws:connect:us-east-1:{cls.account}:instance/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        cls.alias_arn = f"arn:aws:lex:us-east-1:{cls.account}:bot-alias/ABCDEFGHIJ/KLMNOPQRST"
        cls.identity_alias_arn = f"arn:aws:lex:us-east-1:{cls.account}:bot-alias/ZYXWVUTSRQ/TSRQPONMLK"
        cls.availability_alias_arn = f"arn:aws:lex:us-east-1:{cls.account}:bot-alias/QWERTYUIOP/ASDFGHJKLZ"
        cls.lambda_arn = f"arn:aws:lambda:us-east-1:{cls.account}:function:{cls.cfg.session_context_lambda_name}"

    def _flow(self):
        return json.loads(self.cfg.flow_path.read_text(encoding="utf-8"))

    def test_prompt_implements_cara_conversation_behavior(self):
        raw = self.cfg.prompt_path.read_text(encoding="utf-8")
        self.assertIn("You are Cara", raw)
        self.assertIn("LIGHTWEIGHT CONVERSATIONAL STATE", raw)
        self.assertIn("OBJECTIONS", raw)
        self.assertIn("CLEAR REFUSAL", raw)
        self.assertIn("CALLBACK", raw)
        self.assertIn("SAFETY — HIGHEST PRIORITY", raw)
        self.assertIn("SAFETY ALWAYS OVERRIDES EVERY OTHER CONVERSATIONAL INTENT OR STATE", raw)
        self.assertIn("resume_state", raw)
        self.assertIn("I don't have time", raw)
        self.assertIn("No, it is not a good time right now. Can you call me tomorrow at 10 AM?", raw)
        self.assertIn("One clear affirmative answer is enough", raw)
        self.assertIn("speak transferMessage exactly once", raw)
        self.assertIn("Is now a good time to connect?", raw)
        self.assertIn("Connect flow handles speaking any required closing or safety response", raw)
        self.assertIn("TRANSFER-FIRST GOAL", raw)
        self.assertIn("EscalateToHuman", raw)
        self.assertIn("RequestCallback", raw)
        self.assertIn("EndConversation", raw)
        self.assertIn("${CaraBehaviorConfig}", raw)
        rendered = render_cara_prompt(self.cfg, raw)
        self.assertNotIn("${CaraBehaviorConfig}", rendered)
        self.assertIn('"questionResponses"', rendered)
        self.assertIn("Never ask the caller to confirm their identity again", rendered)

    def test_prompt_variables_are_unique(self):
        raw = self.cfg.prompt_path.read_text(encoding="utf-8")
        variables = re.findall(r"\{\{\$\.[^{}]+\}\}", raw)
        self.assertEqual(len(variables), len(set(variables)))
        for required in (
            "{{$.Custom.customerName}}",
            "{{$.Custom.expectedPhone}}",
            "{{$.conversationHistory}}",
            "{{$.locale}}",
        ):
            self.assertEqual(raw.count(required), 1)

    def test_q_agent_has_only_conversation_outcome_tools(self):
        cfg = q_agent_configuration(self.cfg, self.instance_arn, "prompt-id:1")
        orchestrator = cfg["orchestrationAIAgentConfiguration"]
        tools = orchestrator["toolConfigurations"]
        self.assertEqual(
            {tool["toolName"] for tool in tools},
            {"EscalateToHuman", "RequestCallback", "EndConversation"},
        )
        escalate = next(tool for tool in tools if tool["toolName"] == "EscalateToHuman")
        self.assertGreaterEqual(len(escalate["instruction"].get("examples", [])), 3)
        self.assertTrue(any("connect" in x.lower() for x in escalate["instruction"]["examples"]))
        self.assertNotIn("confirmIdentity", json.dumps(tools))
        callback_tool = next(tool for tool in tools if tool["toolName"] == "RequestCallback")
        self.assertTrue(
            any("tomorrow at 10 AM" in x for x in callback_tool["instruction"].get("examples", []))
        )
        self.assertIn("Do not use EndConversation", callback_tool["instruction"]["instruction"])
        end_tool = next(tool for tool in tools if tool["toolName"] == "EndConversation")
        self.assertIn("callback request", end_tool["instruction"]["instruction"])
        reasons = set(end_tool["inputSchema"]["properties"]["endReason"]["enum"])
        self.assertIn("safety_medical", reasons)
        self.assertIn("safety_behavioral", reasons)

    def test_identity_confirmed_includes_bare_yes(self):
        req = identity_confirmed_intent_request(self.cfg, "ABCDEFGHIJ")
        samples = {x["utterance"] for x in req["sampleUtterances"]}
        self.assertIn("yes this is me", samples)
        self.assertIn("speaking", samples)
        self.assertIn("yes", samples)
        self.assertIn("yeah", samples)

    def test_identity_named_confirmation_uses_first_and_last_name_slots(self):
        base = identity_named_confirmation_intent_request(self.cfg, "ABCDEFGHIJ")
        base_samples = {x["utterance"] for x in base["sampleUtterances"]}
        self.assertIn("yes this is John Doe", base_samples)
        self.assertNotIn("yes this is {firstName} {lastName}", base_samples)

        slotted = identity_named_confirmation_intent_request(
            self.cfg, "ABCDEFGHIJ", with_slots=True
        )
        slotted_samples = {x["utterance"] for x in slotted["sampleUtterances"]}
        self.assertIn("yes this is {firstName} {lastName}", slotted_samples)
        self.assertIn("{firstName} {lastName} speaking", slotted_samples)

        first = identity_first_name_slot_request(self.cfg, "ABCDEFGHIJ", "KLMNOPQRST")
        last = identity_last_name_slot_request(self.cfg, "ABCDEFGHIJ", "KLMNOPQRST")
        self.assertEqual(first["slotTypeId"], "AMAZON.FirstName")
        self.assertEqual(last["slotTypeId"], "AMAZON.LastName")
        self.assertEqual(first["valueElicitationSetting"]["slotConstraint"], "Optional")
        self.assertEqual(last["valueElicitationSetting"]["slotConstraint"], "Optional")

    def test_identity_confirmed_contains_bare_yes_and_ambiguous_contains_questions(self):
        confirmed_req = identity_confirmed_intent_request(self.cfg, "ABCDEFGHIJ")
        confirmed_samples = {x["utterance"] for x in confirmed_req["sampleUtterances"]}
        self.assertIn("yes", confirmed_samples)
        self.assertIn("yeah", confirmed_samples)

        ambiguous_req = identity_ambiguous_intent_request(self.cfg, "ABCDEFGHIJ")
        ambiguous_samples = {x["utterance"] for x in ambiguous_req["sampleUtterances"]}
        self.assertNotIn("yes", ambiguous_samples)
        self.assertNotIn("yeah", ambiguous_samples)
        self.assertIn("who is this", ambiguous_samples)
        self.assertIn("may I know whom I am talking with", ambiguous_samples)
        self.assertIn("may I know who I'm talking with", ambiguous_samples)
        self.assertIn("who are you looking for", ambiguous_samples)

    def test_identity_recipient_semantics_are_separated(self):
        denied = {x["utterance"] for x in identity_denied_intent_request(self.cfg, "ABCDEFGHIJ")["sampleUtterances"]}
        unavailable = {x["utterance"] for x in patient_unavailable_intent_request(self.cfg, "ABCDEFGHIJ")["sampleUtterances"]}
        wrong = {x["utterance"] for x in wrong_number_intent_request(self.cfg, "ABCDEFGHIJ")["sampleUtterances"]}
        rep = {x["utterance"] for x in representative_detected_intent_request(self.cfg, "ABCDEFGHIJ")["sampleUtterances"]}
        deceased = {x["utterance"] for x in deceased_intent_request(self.cfg, "ABCDEFGHIJ")["sampleUtterances"]}
        refusal = {x["utterance"] for x in call_refusal_intent_request(self.cfg, "ABCDEFGHIJ")["sampleUtterances"]}
        self.assertIn("no I am not", denied)
        self.assertIn("no I'm not John", denied)
        self.assertIn("I'm not John", denied)
        self.assertNotIn("wrong number", denied)
        self.assertIn("he is not available", unavailable)
        self.assertIn("she is not here", unavailable)
        self.assertNotIn("he is not available", {x["utterance"] for x in third_party_detected_intent_request(self.cfg, "ABCDEFGHIJ")["sampleUtterances"]})
        self.assertIn("wrong number", wrong)
        self.assertIn("no wrong number", wrong)
        self.assertIn("no it's wrong number", wrong)
        self.assertIn("I am not John and this is the wrong number", wrong)
        self.assertIn("there is no one here with this name", wrong)
        self.assertIn("here with this name", wrong)
        self.assertIn("I am his caregiver", rep)
        self.assertIn("he passed away", deceased)
        self.assertIn("stop calling me", refusal)

    def test_third_party_intent_contains_relative_phrases(self):
        req = third_party_detected_intent_request(self.cfg, "ABCDEFGHIJ")
        samples = {x["utterance"] for x in req["sampleUtterances"]}
        self.assertIn("this is his wife", samples)
        self.assertIn("I am his brother", samples)
        self.assertNotIn("he is not available", samples)
        self.assertNotIn("she is not here", samples)

    def test_identity_questions_and_unavailable_scenarios_do_not_repeat(self):
        ambiguous = {x["utterance"] for x in identity_ambiguous_intent_request(self.cfg, "ABCDEFGHIJ")["sampleUtterances"]}
        unavailable = {x["utterance"] for x in patient_unavailable_intent_request(self.cfg, "ABCDEFGHIJ")["sampleUtterances"]}
        self.assertIn("who are you looking for", ambiguous)
        self.assertIn("she is not here", unavailable)
        self.assertIn("he is not available", unavailable)

        actions = {a["Identifier"]: a for a in self._flow()["Actions"]}
        direct_callback = actions["a0000000-0000-4000-8000-000000000011"]
        self.assertEqual(direct_callback["Parameters"]["Text"], "$.Attributes.patientUnavailablePrompt")
        self.assertNotEqual(direct_callback["Parameters"]["Text"], "$.Attributes.thirdPartyAvailabilityPrompt")
        for identity_id in (
            "10000000-0000-4000-8000-000000000001",
            "10000000-0000-4000-8000-000000000003",
            "a0000000-0000-4000-8000-000000000003",
            "a0000000-0000-4000-8000-000000000004",
        ):
            routes = {
                c["Condition"]["Operands"][0]: c["NextAction"]
                for c in actions[identity_id]["Transitions"].get("Conditions", [])
            }
            expected = "e0000000-0000-4000-8000-000000000004" if identity_id.startswith("10000000") else "a0000000-0000-4000-8000-000000000011"
            self.assertEqual(routes["PatientUnavailable"], expected)

    def test_safety_intents_are_semantic_and_encode_priority_conflicts(self):
        medical = {x["utterance"] for x in safety_medical_intent_request(self.cfg, "ABCDEFGHIJ")["sampleUtterances"]}
        behavioral = {x["utterance"] for x in safety_behavioral_intent_request(self.cfg, "ABCDEFGHIJ")["sampleUtterances"]}
        self.assertIn("I am not interested because I have crushing chest pain", medical)
        self.assertIn("I am busy but I am having trouble breathing", medical)
        self.assertIn("call me later my blood sugar is dangerously low", medical)
        self.assertIn("I do not want this I want to die", behavioral)
        self.assertIn("I am busy but I do not feel safe", behavioral)
        self.assertIn("stop calling me someone is hurting me", behavioral)
        self.assertGreaterEqual(len(medical), 25)
        self.assertGreaterEqual(len(behavioral), 25)

    def test_safety_is_first_route_in_all_pre_q_conversational_lex_actions(self):
        actions = [a for a in self._flow()["Actions"] if a["Type"] == "ConnectParticipantWithLexBot"]
        pre_q = [a for a in actions if a["Parameters"]["LexV2Bot"]["AliasArn"] in {"${IdentityLexBotAliasArn}", "${AvailabilityLexBotAliasArn}"}]
        self.assertEqual(len(pre_q), 7)
        for action in pre_q:
            operands = [c["Condition"]["Operands"][0] for c in action["Transitions"].get("Conditions", [])]
            self.assertGreaterEqual(len(operands), 2)
            self.assertEqual(operands[:2], ["SafetyMedical", "SafetyBehavioral"])

    def test_safety_exit_uses_configured_response_then_disconnects(self):
        actions = {a["Identifier"]: a for a in self._flow()["Actions"]}
        medical_state = actions["d0000000-0000-4000-8000-000000000001"]
        behavioral_state = actions["d0000000-0000-4000-8000-000000000002"]
        self.assertEqual(medical_state["Parameters"]["Attributes"]["conversationState"], "SAFETY")
        self.assertEqual(behavioral_state["Parameters"]["Attributes"]["conversationState"], "SAFETY")
        medical_message = actions["d0000000-0000-4000-8000-000000000003"]
        behavioral_message = actions["d0000000-0000-4000-8000-000000000004"]
        self.assertEqual(medical_message["Parameters"]["Text"], "${CaraSafetyMedicalResponse}")
        self.assertEqual(behavioral_message["Parameters"]["Text"], "${CaraSafetyBehavioralResponse}")
        self.assertEqual(medical_message["Transitions"]["NextAction"], "77777777-7777-4777-8777-777777777777")
        self.assertEqual(behavioral_message["Transitions"]["NextAction"], "77777777-7777-4777-8777-777777777777")

    def test_identity_nlu_threshold_is_hardened(self):
        from cara_health_bot.builders import identity_lex_locale_request
        req = identity_lex_locale_request(self.cfg, "ABCDEFGHIJ")
        self.assertGreaterEqual(req["nluIntentConfidenceThreshold"], 0.90)

    def test_human_agent_config_is_explicit_and_password_is_not_stored(self):
        self.assertEqual(self.cfg.human_agent_username, "caraagent")
        self.assertEqual(self.cfg.human_agent_routing_profile_name, "CaraHealthBotRoutingProfile")
        self.assertEqual(self.cfg.human_agent_security_profile_name, "CaraHealthBotHumanAgent")
        self.assertEqual(self.cfg.human_transfer_queue_name, "CaraHealthBotQueue")
        raw = self.cfg.root.joinpath("config.json").read_text(encoding="utf-8")
        self.assertNotIn("humanAgentPassword", raw)

    def test_flow_has_identity_availability_and_handoff_gates(self):
        flow = self._flow()
        actions = flow["Actions"]
        lex = [a for a in actions if a["Type"] == "ConnectParticipantWithLexBot"]
        identity = [a for a in lex if a["Parameters"]["LexV2Bot"]["AliasArn"] == "${IdentityLexBotAliasArn}"]
        availability = [a for a in lex if a["Parameters"]["LexV2Bot"]["AliasArn"] == "${AvailabilityLexBotAliasArn}"]
        coaching = [a for a in lex if a["Parameters"]["LexV2Bot"]["AliasArn"] == "${LexBotAliasArn}"]
        self.assertEqual(len(identity), 4)
        self.assertEqual(len(availability), 3)
        self.assertEqual(len(coaching), 1)
        phases = {a["Parameters"]["LexSessionAttributes"]["caraHealthBotPhase"] for a in lex}
        self.assertTrue({"identity-1", "identity-2", "third-party-availability-1", "third-party-availability-2", "patient-unavailable-callback", "handoff-identity-1", "handoff-identity-2", "coaching"} <= phases)
        for action in identity:
            self.assertEqual(
                action["Parameters"]["LexSessionAttributes"]["expectedCustomerName"],
                "$.Attributes.customerName",
            )

    def test_flow_uses_semantic_identity_then_q_outcome_tools(self):
        flow = self._flow()
        actions = {a["Identifier"]: a for a in flow["Actions"]}
        first = actions["10000000-0000-4000-8000-000000000001"]
        routes = {c["Condition"]["Operands"][0]: c["NextAction"] for c in first["Transitions"]["Conditions"]}
        self.assertEqual(routes["SafetyMedical"], "d0000000-0000-4000-8000-000000000001")
        self.assertEqual(routes["SafetyBehavioral"], "d0000000-0000-4000-8000-000000000002")
        self.assertEqual(routes["IdentityConfirmed"], "90000000-0000-4000-8000-000000000004")
        self.assertEqual(routes["IdentityNamedConfirmation"], "f1000000-0000-4000-8000-000000000001")
        self.assertEqual(routes["IdentityDenied"], "e0000000-0000-4000-8000-000000000003")
        self.assertEqual(routes["RepresentativeDetected"], "e0000000-0000-4000-8000-000000000005")
        self.assertEqual(routes["WrongNumber"], "e0000000-0000-4000-8000-000000000001")
        self.assertEqual(routes["Deceased"], "c0000000-0000-4000-8000-000000000003")
        self.assertEqual(routes["CallRefusal"], "c0000000-0000-4000-8000-000000000004")
        second = actions["10000000-0000-4000-8000-000000000003"]
        second_routes = {c["Condition"]["Operands"][0]: c["NextAction"] for c in second["Transitions"]["Conditions"]}
        self.assertEqual(second_routes["IdentityNamedConfirmation"], "f1000000-0000-4000-8000-000000000003")
        self.assertEqual(second_routes["IdentityAmbiguous"], "e0000000-0000-4000-8000-000000000006")
        self.assertEqual(second_routes["FallbackIntent"], "e0000000-0000-4000-8000-000000000006")
        self.assertEqual(second["Transitions"]["NextAction"], "e0000000-0000-4000-8000-000000000006")
        compare = actions["b0000000-0000-4000-8000-000000000001"]
        self.assertEqual(compare["Type"], "Compare")
        self.assertEqual(compare["Parameters"]["ComparisonValue"], "$.Lex.SessionAttributes.Tool")
        tool_routes = {c["Condition"]["Operands"][0]: c["NextAction"] for c in compare["Transitions"]["Conditions"]}
        self.assertEqual(set(tool_routes), {"EscalateToHuman", "RequestCallback", "EndConversation"})


    def test_confirmed_customer_enters_cara_before_transfer(self):
        actions = {a["Identifier"]: a for a in self._flow()["Actions"]}
        mark = actions["90000000-0000-4000-8000-000000000004"]
        self.assertEqual(mark["Parameters"]["Attributes"]["identityConfirmed"], "true")
        self.assertEqual(mark["Transitions"]["NextAction"], "33333333-3333-4333-8333-333333333333")
        q = actions["55555555-5555-4555-8555-555555555555"]
        self.assertEqual(q["Transitions"]["NextAction"], "b0000000-0000-4000-8000-000000000001")
        coaching_routes = {
            c["Condition"]["Operands"][0]: c["NextAction"]
            for c in q["Transitions"].get("Conditions", [])
        }
        self.assertEqual(coaching_routes["SafetyMedical"], "d0000000-0000-4000-8000-000000000001")
        self.assertEqual(coaching_routes["SafetyBehavioral"], "d0000000-0000-4000-8000-000000000002")
        q_errors = {e["ErrorType"]: e["NextAction"] for e in q["Transitions"]["Errors"]}
        # AMAZON.QinConnectIntent returns a fulfilled intent even for a Return-to-Control
        # tool. For standard utterances not matching explicit safety intents, Connect uses NoMatchingCondition;
        # that branch must inspect $.Lex.SessionAttributes.Tool instead of falling back.
        self.assertEqual(q_errors["NoMatchingCondition"], "b0000000-0000-4000-8000-000000000001")
        transfer_context = actions["b0000000-0000-4000-8000-000000000005"]
        self.assertEqual(transfer_context["Parameters"]["Attributes"]["conversationState"], "TRANSFER_READY")
        self.assertEqual(transfer_context["Transitions"]["NextAction"], "b0000000-0000-4000-8000-000000000010")
        self.assertEqual(actions["b0000000-0000-4000-8000-000000000010"]["Type"], "InvokeLambdaFunction")

    def test_cara_callback_and_end_outcomes_are_persisted(self):
        actions = {a["Identifier"]: a for a in self._flow()["Actions"]}
        callback = actions["b0000000-0000-4000-8000-000000000002"]
        self.assertEqual(callback["Parameters"]["Attributes"]["callbackWhen"], "$.Lex.SessionAttributes.callbackWhen")
        self.assertEqual(callback["Parameters"]["Attributes"]["callbackReason"], "$.Lex.SessionAttributes.callbackReason")
        ending = actions["b0000000-0000-4000-8000-000000000004"]
        self.assertEqual(ending["Parameters"]["Attributes"]["caraEndReason"], "$.Lex.SessionAttributes.endReason")
        self.assertEqual(ending["Transitions"]["NextAction"], "b0000000-0000-4000-8000-000000000008")
        safety_router = actions["b0000000-0000-4000-8000-000000000008"]
        self.assertEqual(safety_router["Parameters"]["ComparisonValue"], "$.Lex.SessionAttributes.endReason")
        safety_routes = {c["Condition"]["Operands"][0]: c["NextAction"] for c in safety_router["Transitions"]["Conditions"]}
        self.assertEqual(safety_routes["safety_medical"], "d0000000-0000-4000-8000-000000000001")
        self.assertEqual(safety_routes["safety_behavioral"], "d0000000-0000-4000-8000-000000000002")

    def test_third_party_availability_flow_is_bounded_and_persists_callback(self):
        actions = {a["Identifier"]: a for a in self._flow()["Actions"]}
        availability = actions["a0000000-0000-4000-8000-000000000001"]
        routes = {c["Condition"]["Operands"][0]: c["NextAction"] for c in availability["Transitions"]["Conditions"]}
        self.assertEqual(routes["SafetyMedical"], "d0000000-0000-4000-8000-000000000001")
        self.assertEqual(routes["SafetyBehavioral"], "d0000000-0000-4000-8000-000000000002")
        self.assertEqual(routes["WrongNumber"], "e0000000-0000-4000-8000-000000000001")
        self.assertEqual(routes["TargetAvailableNow"], "a0000000-0000-4000-8000-000000000006")
        self.assertEqual(routes["TargetUnavailable"], "a0000000-0000-4000-8000-000000000011")
        availability_2 = actions["a0000000-0000-4000-8000-000000000005"]
        routes_2 = {c["Condition"]["Operands"][0]: c["NextAction"] for c in availability_2["Transitions"]["Conditions"]}
        self.assertEqual(routes_2["WrongNumber"], "e0000000-0000-4000-8000-000000000001")
        callback = actions["a0000000-0000-4000-8000-000000000007"]
        attrs = callback["Parameters"]["Attributes"]
        self.assertEqual(attrs["callbackDate"], "$.Lex.Slots.callbackDate")
        self.assertEqual(attrs["callbackTime"], "$.Lex.Slots.callbackTime")
        self.assertEqual(attrs["identityConfirmed"], "false")
        pass_phone = actions["a0000000-0000-4000-8000-000000000002"]
        self.assertEqual(pass_phone["Parameters"]["Text"], "$.Attributes.passPhonePrompt")
        handoff = actions["a0000000-0000-4000-8000-000000000003"]
        handoff_routes = {c["Condition"]["Operands"][0]: c["NextAction"] for c in handoff["Transitions"]["Conditions"]}
        self.assertEqual(handoff_routes["IdentityConfirmed"], "90000000-0000-4000-8000-000000000005")

    def test_availability_intents_and_slots_are_deterministic(self):
        available = {x["utterance"] for x in availability_now_intent_request(self.cfg, "ABCDEFGHIJ")["sampleUtterances"]}
        unavailable = availability_unavailable_intent_request(self.cfg, "ABCDEFGHIJ", slot_priorities=[])
        unknown = {x["utterance"] for x in availability_unknown_intent_request(self.cfg, "ABCDEFGHIJ")["sampleUtterances"]}
        self.assertIn("yes he is here", available)
        self.assertIn("call back {callbackDate} at {callbackTime}", {x["utterance"] for x in unavailable["sampleUtterances"]})
        self.assertIn("I don't know", unknown)
        date_slot = availability_callback_date_slot_request(self.cfg, "ABCDEFGHIJ", "KLMNOPQRST")
        time_slot = availability_callback_time_slot_request(self.cfg, "ABCDEFGHIJ", "KLMNOPQRST")
        self.assertEqual(date_slot["slotTypeId"], "AMAZON.Date")
        self.assertEqual(time_slot["slotTypeId"], "AMAZON.Time")
        self.assertEqual(date_slot["valueElicitationSetting"]["slotConstraint"], "Optional")
        self.assertEqual(time_slot["valueElicitationSetting"]["slotConstraint"], "Optional")

    def test_flow_uses_session_context_lambda_for_init_and_full_name_validation(self):
        invokes = [a for a in self._flow()["Actions"] if a["Type"] == "InvokeLambdaFunction"]
        operations = [a["Parameters"]["LambdaInvocationAttributes"]["operation"] for a in invokes]
        self.assertEqual(operations.count("initialize"), 1)
        self.assertEqual(operations.count("verifyIdentityName"), 4)
        for action in invokes:
            attrs = action["Parameters"]["LambdaInvocationAttributes"]
            if attrs["operation"] == "verifyIdentityName":
                self.assertEqual(attrs["expectedCustomerName"], "$.Attributes.customerName")
                self.assertEqual(attrs["spokenFirstName"], "$.Lex.Slots.firstName")
                self.assertEqual(attrs["spokenLastName"], "$.Lex.Slots.lastName")

    def test_flow_identity_alias_occurs_before_q_assistant(self):
        rendered = render_contact_flow(
            self.cfg,
            self.assistant_id,
            self.assistant_arn,
            self.alias_arn,
            self.identity_alias_arn,
            self.availability_alias_arn,
            self.lambda_arn,
            "arn:aws:connect:us-east-1:123456789012:instance/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/queue/ffffffff-1111-2222-3333-444444444444",
        )
        self.assertLess(rendered.find(self.identity_alias_arn), rendered.find(self.assistant_arn))
        self.assertIn(self.alias_arn, rendered)
        self.assertIn(self.availability_alias_arn, rendered)
        self.assertIn(self.lambda_arn, rendered)

    def test_lambda_marks_identity_already_confirmed(self):
        spec = importlib.util.spec_from_file_location(
            "session_context_test", self.cfg.root / "lambda" / "session_context.py"
        )
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        calls = []
        class FakeQ:
            def update_session_data(self, **kwargs):
                calls.append(kwargs)
                return {}
        session_arn = f"arn:aws:wisdom:us-east-1:{self.account}:session/{self.assistant_id}/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        event = {"Details": {"Parameters": {
            "operation": "initialize",
            "assistantId": self.assistant_id,
            "sessionArn": session_arn,
            "customerName": "Anish",
            "expectedPhone": "+14155550123",
        }}}
        with mock.patch.object(module.boto3, "client", return_value=FakeQ()):
            result = module.handler(event, None)
        data = {x["key"]: x["value"]["stringValue"] for x in calls[0]["data"]}
        self.assertEqual(data["identityConfirmed"], "true")
        self.assertEqual(data["identityPolicyVersion"], "v7-full-name-validated")
        self.assertEqual(data["conversationState"], "PATIENT_CONFIRMED")
        self.assertEqual(result["identityConfirmed"], "true")

    def test_lambda_full_name_validation_is_exact_and_conservative(self):
        spec = importlib.util.spec_from_file_location(
            "session_context_name_test", self.cfg.root / "lambda" / "session_context.py"
        )
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)

        def verify(expected, first, last):
            event = {"Details": {"Parameters": {
                "operation": "verifyIdentityName",
                "expectedCustomerName": expected,
                "spokenFirstName": first,
                "spokenLastName": last,
            }}}
            return module.handler(event, None)["identityMatch"]

        self.assertEqual(verify("John Doe", "John", "Doe"), "true")
        self.assertEqual(verify("John Michael Doe", "John", "Doe"), "true")
        self.assertEqual(verify("John Doe", "Michael", "Smith"), "false")
        self.assertEqual(verify("John Doe", "John", "Smith"), "false")
        self.assertEqual(verify("John Doe", "John", ""), "ambiguous")
        self.assertEqual(verify("José O'Neil", "Jose", "ONeil"), "true")

    def test_call_passes_dynamic_identity_prompts(self):
        text = (self.cfg.root / "scripts" / "call.py").read_text(encoding="utf-8")
        self.assertIn('"identityPolicyVersion": "v6-cara-conversational"', text)
        self.assertIn('"identityPrompt": f"Hi, may I speak with {customer_name}?"', text)
        self.assertIn('cfg.cara_behavior["preIdentityQuestionResponse"]', text)
        self.assertIn('cfg.cara_behavior["otherPersonResponse"]', text)
        self.assertIn('"passPhonePrompt": f"Thanks. Please pass the phone to {customer_name}."', text)
        self.assertIn('"handoffIdentityPrompt": f"Hi. May I confirm I\'m speaking with {customer_name}?"', text)
        self.assertIn('cfg.cara_behavior["openingMessage"]', text)
        self.assertNotIn("RingTimeoutInSeconds", text)

    def test_both_lex_aliases_enable_text_logs(self):
        log_arn = f"arn:aws:logs:us-east-1:{self.account}:log-group:/aws/lex/test"
        main = lex_alias_request(self.cfg, "ABCDEFGHIJ", "1", log_arn)
        identity = identity_lex_alias_request(self.cfg, "ZYXWVUTSRQ", "1", log_arn)
        for req in (main, identity):
            self.assertTrue(req["botAliasLocaleSettings"]["en_US"]["enabled"])
            self.assertTrue(req["conversationLogSettings"]["textLogSettings"][0]["enabled"])

    def test_roles_are_least_privilege(self):
        q_policy = lex_runtime_permissions(
            "us-east-1", self.account, self.assistant_id, self.assistant_arn, "/aws/lex/test"
        )
        identity_policy = identity_lex_runtime_permissions(
            "us-east-1", self.account, "/aws/lex/test"
        )
        q_text = json.dumps(q_policy)
        identity_text = json.dumps(identity_policy)
        self.assertIn("wisdom:SendMessage", q_text)
        self.assertNotIn('"wisdom:*"', q_text)
        self.assertNotIn("wisdom:", identity_text)
        self.assertIn("logs:PutLogEvents", identity_text)

    def test_lambda_role_is_scoped_to_current_assistant_sessions(self):
        policy = session_context_lambda_permissions(
            "us-east-1", self.account, self.assistant_id, self.cfg.session_context_lambda_name
        )
        text = json.dumps(policy)
        self.assertIn("wisdom:UpdateSessionData", text)
        self.assertIn(f"session/{self.assistant_id}/*", text)
        self.assertNotIn('"wisdom:*"', text)

    def test_qinconnect_request_still_binds_exact_assistant(self):
        request = lex_qinconnect_intent_request(self.cfg, "ABCDEFGHIJ", self.assistant_arn)
        self.assertEqual(
            request["qInConnectIntentConfiguration"]["qInConnectAssistantConfiguration"]["assistantArn"],
            self.assistant_arn,
        )

    def test_existing_human_agent_is_reused_without_password(self):
        deployer = object.__new__(CaraHealthBotDeployer)
        deployer.cfg = self.cfg
        deployer.verbose = False

        class FakeState:
            def __init__(self): self.resources = {}
            def update(self, **kwargs): self.resources.update(kwargs)

        class FakeConnect:
            def __init__(self): self.calls = []
            def update_security_profile(self, **kwargs): self.calls.append(("security-profile", kwargs))
            def update_user_routing_profile(self, **kwargs): self.calls.append(("routing", kwargs))
            def update_user_security_profiles(self, **kwargs): self.calls.append(("security", kwargs))
            def update_user_identity_info(self, **kwargs): self.calls.append(("identity", kwargs))
            def update_user_phone_config(self, **kwargs): self.calls.append(("phone", kwargs))
            def describe_instance(self, **kwargs):
                return {"Instance": {"IdentityManagementType": "CONNECT_MANAGED", "InstanceAccessUrl": "https://example.my.connect.aws"}}

        deployer.state = FakeState()
        deployer.connect = FakeConnect()
        data = {
            "list_routing_profiles": [{"Name": "CaraHealthBotRoutingProfile", "Id": "rp-1"}],
            "list_routing_profile_queues": [{"QueueId": "q-1", "QueueName": "CaraHealthBotQueue", "Channel": "VOICE", "Priority": 1, "Delay": 0}],
            "list_security_profiles": [{"Name": "CaraHealthBotHumanAgent", "Id": "sp-1"}],
            "list_users": [{"Username": "caraagent", "Id": "u-1", "Arn": "arn:user/u-1"}],
        }
        deployer._paginate = lambda client, operation, key, **kwargs: iter(data[operation])
        with mock.patch.dict("os.environ", {}, clear=True):
            user_id, user_arn, workspace = deployer.ensure_human_agent("i-1", "q-1")
        self.assertEqual(user_id, "u-1")
        self.assertEqual(user_arn, "arn:user/u-1")
        self.assertEqual(workspace, "https://example.my.connect.aws/agent-app-v2/")
        self.assertEqual(
            {name for name, _ in deployer.connect.calls},
            {"security-profile", "routing", "security", "identity", "phone"},
        )
        self.assertEqual(deployer.state.resources["humanAgentUsername"], "caraagent")

    def test_lex_version_creation_retries_fresh_bot_resource_not_found(self):
        deployer = object.__new__(CaraHealthBotDeployer)
        deployer.cfg = self.cfg
        deployer.verbose = False
        deployer._numeric_version_summaries = lambda bot_id: []
        deployer._recover_new_version_after_create_error = lambda bot_id, baseline_versions, assistant_arn: None
        class FakeLex:
            def __init__(self): self.calls = 0
            def create_bot_version(self, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    raise ClientError({"Error": {"Code": "ResourceNotFoundException", "Message": "not ready"}}, "CreateBotVersion")
                return {"botVersion": "1"}
        deployer.lex = FakeLex()
        with mock.patch("cara_health_bot.deployer.time.sleep", return_value=None):
            version = deployer._create_bot_version_resilient("ABCDEFGHIJ", self.assistant_arn)
        self.assertEqual(version, "1")
        self.assertEqual(deployer.lex.calls, 2)


    def test_flow_enables_ivr_recording_before_identity(self):
        flow = self._flow()
        actions = flow["Actions"]
        recording = next(a for a in actions if a["Type"] == "UpdateContactRecordingBehavior")
        self.assertEqual(recording["Parameters"]["RecordingBehavior"]["IVRRecordingBehavior"], "Enabled")
        self.assertEqual(
            recording["Parameters"]["RecordingBehavior"]["RecordedParticipants"],
            ["Agent", "Customer"],
        )
        voice = next(a for a in actions if a["Identifier"] == "22222222-2222-4222-8222-222222222222")
        self.assertEqual(voice["Transitions"]["NextAction"], recording["Identifier"])
        callmode_block = next(a for a in actions if a["Identifier"] == recording["Transitions"]["NextAction"])
        self.assertEqual(callmode_block["Type"], "Compare")
        identity_msg = next(a for a in actions if a["Identifier"] == callmode_block["Transitions"]["NextAction"])
        self.assertEqual(identity_msg["Type"], "ConnectParticipantWithLexBot")
        self.assertEqual(identity_msg["Parameters"]["LexSessionAttributes"]["caraHealthBotPhase"], "identity-1")

    def test_cara_business_wording_is_configurable(self):
        cara = self.cfg.cara_behavior
        self.assertEqual(cara["agentName"], "Cara")
        self.assertIn("questionResponses", cara)
        self.assertIn("objectionResponses", cara)
        self.assertIn("callbackResponses", cara)
        self.assertIn("wrongNumberResponse", cara)
        self.assertIn("deceasedResponse", cara)
        self.assertIn("safetyMedicalResponse", cara)
        self.assertIn("safetyBehavioralResponse", cara)
        self.assertTrue(cara["questionResponses"]["cost"]["short"].startswith("<CONFIGURE_"))

    def test_config_has_recording_storage_names(self):
        self.assertEqual(self.cfg.recording_bucket(self.account), f"cara-health-bot-recordings-{self.account}-us-east-1")
        self.assertEqual(self.cfg.recording_prefix, "connect-recordings")
        self.assertEqual(self.cfg.transcript_prefix, "transcribe-output")

    def test_transcript_accepts_connect_bare_bucket_key_location(self):
        import importlib.util

        script = self.cfg.root / "scripts" / "transcript.py"
        spec = importlib.util.spec_from_file_location("cara_health_bot_transcript_test", script)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)

        location = (
            "cara-health-bot-recordings-701348334422-us-east-1/"
            "connect-recordings/ivr/2026/08/13/"
            "6f2846ee-29e3-45c5-8933-27f24891571f_20260813T07:35_UTC.wav"
        )
        bucket, key = module.parse_s3_location(location)
        self.assertEqual(bucket, "cara-health-bot-recordings-701348334422-us-east-1")
        self.assertEqual(
            key,
            "connect-recordings/ivr/2026/08/13/"
            "6f2846ee-29e3-45c5-8933-27f24891571f_20260813T07:35_UTC.wav",
        )

    def _transcript_module(self):
        script = self.cfg.root / "scripts" / "transcript.py"
        spec = importlib.util.spec_from_file_location("cara_health_bot_transcript_test", script)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        return module

    def test_transcript_uses_single_stereo_recording_for_both_speakers(self):
        text = (self.cfg.root / "scripts" / "transcript.py").read_text(encoding="utf-8")
        self.assertIn("Recordings", text)
        self.assertIn("start_transcription_job", text)
        self.assertIn('ChannelIdentification": True', text)
        self.assertIn('by_label["ch_0"]', text)
        self.assertIn('by_label["ch_1"]', text)
        self.assertNotIn("qconnect", text.lower())
        self.assertNotIn("filter_log_events", text)

    def test_transcript_parses_both_channels_in_timestamp_order(self):
        module = self._transcript_module()
        document = {
            "results": {"channel_labels": {"channels": [
                {"channel_label": "ch_0", "items": [
                    {"start_time": "0.00", "end_time": "0.20", "type": "pronunciation", "alternatives": [{"content": "Hi"}]},
                    {"start_time": "0.21", "end_time": "0.40", "type": "pronunciation", "alternatives": [{"content": "Anish"}]},
                    {"type": "punctuation", "alternatives": [{"content": "?"}]},
                    {"start_time": "4.00", "end_time": "4.20", "type": "pronunciation", "alternatives": [{"content": "Thanks"}]},
                    {"type": "punctuation", "alternatives": [{"content": "."}]},
                ]},
                {"channel_label": "ch_1", "items": [
                    {"start_time": "2.00", "end_time": "2.20", "type": "pronunciation", "alternatives": [{"content": "Yes"}]},
                    {"start_time": "2.21", "end_time": "2.40", "type": "pronunciation", "alternatives": [{"content": "speaking"}]},
                    {"type": "punctuation", "alternatives": [{"content": "."}]},
                ]},
            ]}}
        }
        turns = module.turns_from_transcribe_document(document, "2026-08-13T07:35:00Z")
        self.assertEqual([(speaker, text) for _, speaker, text in turns], [
            ("Cara", "Hi Anish?"),
            ("Customer", "Yes speaking."),
            ("Cara", "Thanks."),
        ])

    def test_transcript_accepts_multiple_s3_location_forms(self):
        module = self._transcript_module()
        expected = ("example-bucket", "path/to/file.wav")
        values = [
            "s3://example-bucket/path/to/file.wav",
            "example-bucket/path/to/file.wav",
            "https://example-bucket.s3.us-east-1.amazonaws.com/path/to/file.wav",
            "https://s3.us-east-1.amazonaws.com/example-bucket/path/to/file.wav",
        ]
        for value in values:
            with self.subTest(value=value):
                self.assertEqual(module.parse_s3_location(value), expected)

    def test_transcript_failed_job_is_deleted_and_restarted(self):
        module = self._transcript_module()
        class FakeBody:
            def read(self):
                return json.dumps({"results": {"channel_labels": {"channels": [
                    {"channel_label": "ch_0", "items": [{"start_time": "0", "end_time": "0.2", "type": "pronunciation", "alternatives": [{"content": "Hello"}]}]},
                    {"channel_label": "ch_1", "items": [{"start_time": "1", "end_time": "1.2", "type": "pronunciation", "alternatives": [{"content": "Hi"}]}]},
                ]}}}).encode()
        class FakeS3:
            def get_object(self, **kwargs): return {"Body": FakeBody()}
        class FakeTranscribe:
            def __init__(self): self.deleted = 0; self.started = 0; self.calls = 0
            def get_transcription_job(self, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    return {"TranscriptionJob": {"TranscriptionJobStatus": "FAILED", "FailureReason": "old failure"}}
                return {"TranscriptionJob": {"TranscriptionJobStatus": "COMPLETED"}}
            def delete_transcription_job(self, **kwargs): self.deleted += 1
            def start_transcription_job(self, **kwargs): self.started += 1
        fake_t = FakeTranscribe()
        recording = {"Location": "example-bucket/path/file.wav", "StartTimestamp": "2026-08-13T07:35:00Z"}
        with mock.patch.object(module, "_normalize_recording_for_transcribe", return_value="s3://example-bucket/transcribe-input/contact.wav"):
            turns = module.transcribe_recording(fake_t, FakeS3(), recording, "contact", "example-bucket", "out", "en-US")
        self.assertEqual(fake_t.deleted, 1)
        self.assertEqual(fake_t.started, 1)
        self.assertEqual([(s, t) for _, s, t in turns], [("Cara", "Hello"), ("Customer", "Hi")])

    def test_transcript_copy_falls_back_to_get_put(self):
        module = self._transcript_module()
        class Body:
            def read(self): return b"audio-bytes"
        class FakeS3:
            def __init__(self): self.puts = []
            def head_object(self, **kwargs):
                raise ClientError({"Error": {"Code": "404", "Message": "not found"}, "ResponseMetadata": {"HTTPStatusCode": 404}}, "HeadObject")
            def copy_object(self, **kwargs):
                raise ClientError({"Error": {"Code": "AccessDenied", "Message": "kms copy denied"}}, "CopyObject")
            def get_object(self, **kwargs): return {"Body": Body(), "ContentType": "audio/wav"}
            def put_object(self, **kwargs): self.puts.append(kwargs)
        fake = FakeS3()
        uri = module._normalize_recording_for_transcribe(fake, "source", "path/call.wav", "dest", "abc", "wav")
        self.assertEqual(uri, "s3://dest/transcribe-input/abc.wav")
        self.assertEqual(len(fake.puts), 1)
        self.assertEqual(fake.puts[0]["ServerSideEncryption"], "AES256")
        self.assertEqual(fake.puts[0]["Body"], b"audio-bytes")

    def test_transcript_requires_two_channels(self):
        module = self._transcript_module()
        document = {"results": {"channel_labels": {"channels": [{"channel_label": "ch_0", "items": []}]}}}
        with self.assertRaisesRegex(RuntimeError, "two-channel"):
            module.turns_from_transcribe_document(document, "2026-08-13T07:35:00Z")


if __name__ == "__main__":
    unittest.main()

class CaraCampaignFlowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = load_config()
        cls.flow = json.loads(cls.cfg.flow_path.read_text(encoding="utf-8"))
        cls.actions = {a["Identifier"]: a for a in cls.flow["Actions"]}

    def test_confirmed_identity_is_persisted_as_connect_attribute(self):
        for ident in ("90000000-0000-4000-8000-000000000004", "90000000-0000-4000-8000-000000000005"):
            self.assertEqual(self.actions[ident]["Parameters"]["Attributes"]["identityResult"], "Confirmed")

    def test_denied_and_ambiguous_identity_attributes_exist(self):
        denied = self.actions["e0000000-0000-4000-8000-000000000001"]
        ambiguous = self.actions["e0000000-0000-4000-8000-000000000002"]
        self.assertEqual(denied["Type"], "UpdateContactAttributes")
        self.assertEqual(denied["Parameters"]["Attributes"]["identityResult"], "Denied")
        self.assertEqual(ambiguous["Parameters"]["Attributes"]["identityResult"], "Ambiguous")

    def test_wrong_number_routes_through_denied_attribute(self):
        first = self.actions["10000000-0000-4000-8000-000000000001"]
        routes = {c["Condition"]["Operands"][0]: c["NextAction"] for c in first["Transitions"]["Conditions"]}
        self.assertEqual(routes["WrongNumber"], "e0000000-0000-4000-8000-000000000001")

    def test_full_name_identity_routes_through_validator(self):
        first = self.actions["10000000-0000-4000-8000-000000000001"]
        second = self.actions["10000000-0000-4000-8000-000000000003"]
        first_routes = {c["Condition"]["Operands"][0]: c["NextAction"] for c in first["Transitions"]["Conditions"]}
        second_routes = {c["Condition"]["Operands"][0]: c["NextAction"] for c in second["Transitions"]["Conditions"]}
        self.assertEqual(first_routes["IdentityNamedConfirmation"], "f1000000-0000-4000-8000-000000000001")
        self.assertEqual(second_routes["IdentityNamedConfirmation"], "f1000000-0000-4000-8000-000000000003")
        compare = self.actions["f1000000-0000-4000-8000-000000000002"]
        self.assertEqual(compare["Parameters"]["ComparisonValue"], "$.External.identityMatch")
        routes = {c["Condition"]["Operands"][0]: c["NextAction"] for c in compare["Transitions"]["Conditions"]}
        self.assertEqual(routes["true"], "90000000-0000-4000-8000-000000000004")
        self.assertEqual(routes["false"], "e0000000-0000-4000-8000-000000000003")

    def test_exhausted_identity_timeout_routes_through_ambiguous_attribute(self):
        second = self.actions["10000000-0000-4000-8000-000000000003"]
        timeout = next(e for e in second["Transitions"]["Errors"] if e["ErrorType"] == "InputTimeLimitExceeded")
        self.assertEqual(timeout["NextAction"], "e0000000-0000-4000-8000-000000000002")


    def test_second_attempt_unresolved_identity_persists_ambiguous_and_ends(self):
        second = self.actions["10000000-0000-4000-8000-000000000003"]
        routes = {c["Condition"]["Operands"][0]: c["NextAction"] for c in second["Transitions"]["Conditions"]}
        self.assertEqual(routes["IdentityAmbiguous"], "e0000000-0000-4000-8000-000000000006")
        self.assertEqual(routes["FallbackIntent"], "e0000000-0000-4000-8000-000000000006")
        self.assertEqual(second["Transitions"]["NextAction"], "e0000000-0000-4000-8000-000000000006")
        ambiguous = self.actions["e0000000-0000-4000-8000-000000000006"]
        self.assertEqual(ambiguous["Parameters"]["Attributes"]["identityResult"], "Ambiguous")
        self.assertEqual(ambiguous["Transitions"]["NextAction"], "10000000-0000-4000-8000-000000000005")
