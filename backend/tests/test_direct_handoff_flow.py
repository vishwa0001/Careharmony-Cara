from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cara_health_bot.builders import render_contact_flow
from cara_health_bot.config import load_config


class DirectHandoffFlowTests(unittest.TestCase):
    def setUp(self):
        self.flow_path = ROOT / "contact-flows" / "cara-health-bot-flow.json"
        self.cfg = load_config()

    def test_raw_flow_json_is_valid(self):
        content = self.flow_path.read_text(encoding="utf-8")
        data = json.loads(content)
        self.assertIn("Version", data)
        self.assertIn("StartAction", data)
        self.assertIn("Actions", data)

    def test_render_contact_flow_renders_without_unresolved_placeholders(self):
        rendered_json = render_contact_flow(
            cfg=self.cfg,
            assistant_id="test-assistant-id",
            assistant_arn="arn:aws:wisdom:us-east-1:123456789012:assistant/test",
            lex_alias_arn="arn:aws:lex:us-east-1:123456789012:bot-alias/test/alias",
            identity_lex_alias_arn="arn:aws:lex:us-east-1:123456789012:bot-alias/identity/alias",
            availability_lex_alias_arn="arn:aws:lex:us-east-1:123456789012:bot-alias/availability/alias",
            session_context_lambda_arn="arn:aws:lambda:us-east-1:123456789012:function:context",
            human_transfer_queue_arn="arn:aws:connect:us-east-1:123456789012:instance/inst/queue/queue",
        )
        parsed = json.loads(rendered_json)
        self.assertIsInstance(parsed, dict)

    def test_recording_block_transitions_to_callmode_compare(self):
        data = json.loads(self.flow_path.read_text(encoding="utf-8"))
        actions = {a["Identifier"]: a for a in data["Actions"]}

        rec_block = actions.get("20000000-0000-4000-8000-000000000001")
        self.assertIsNotNone(rec_block)
        self.assertEqual(rec_block["Type"], "UpdateContactRecordingBehavior")
        self.assertEqual(rec_block["Transitions"]["NextAction"], "e1000000-0000-4000-8000-000000000001")

    def test_callmode_compare_block_routing(self):
        data = json.loads(self.flow_path.read_text(encoding="utf-8"))
        actions = {a["Identifier"]: a for a in data["Actions"]}

        callmode_block = actions.get("e1000000-0000-4000-8000-000000000001")
        self.assertIsNotNone(callmode_block)
        self.assertEqual(callmode_block["Type"], "Compare")
        self.assertEqual(callmode_block["Parameters"]["ComparisonValue"], "$.Attributes.callMode")

        # Verify DIRECT_HUMAN_HANDOFF condition routes to in-flow availability check
        conditions = callmode_block["Transitions"]["Conditions"]
        handoff_cond = next((c for c in conditions if c["Condition"]["Operands"] == ["DIRECT_HUMAN_HANDOFF"]), None)
        self.assertIsNotNone(handoff_cond)
        self.assertEqual(handoff_cond["NextAction"], "e1000000-0000-4000-8000-000000000010")

        # Verify Default / Missing transition points to original Identity Lex Bot
        self.assertEqual(callmode_block["Transitions"]["NextAction"], "10000000-0000-4000-8000-000000000001")

    def test_direct_call_availability_check_and_fallback_routing(self):
        data = json.loads(self.flow_path.read_text(encoding="utf-8"))
        actions = {a["Identifier"]: a for a in data["Actions"]}

        # 1. Availability check Lambda invocation node
        lambda_node = actions.get("e1000000-0000-4000-8000-000000000010")
        self.assertIsNotNone(lambda_node)
        self.assertEqual(lambda_node["Type"], "InvokeLambdaFunction")
        self.assertEqual(lambda_node["Parameters"]["LambdaInvocationAttributes"]["operation"], "checkAgentAvailability")
        self.assertEqual(lambda_node["Transitions"]["NextAction"], "e1000000-0000-4000-8000-000000000011")
        error_trans = next((e for e in lambda_node["Transitions"]["Errors"] if e["ErrorType"] == "NoMatchingError"), None)
        self.assertIsNotNone(error_trans)
        self.assertEqual(error_trans["NextAction"], "e1000000-0000-4000-8000-000000000020")

        # 2. Availability Compare node
        compare_node = actions.get("e1000000-0000-4000-8000-000000000011")
        self.assertIsNotNone(compare_node)
        self.assertEqual(compare_node["Type"], "Compare")
        self.assertEqual(compare_node["Parameters"]["ComparisonValue"], "$.External.available")
        true_cond = next((c for c in compare_node["Transitions"]["Conditions"] if c["Condition"]["Operands"] == ["true"]), None)
        self.assertIsNotNone(true_cond)
        self.assertEqual(true_cond["NextAction"], "e1000000-0000-4000-8000-000000000012")
        self.assertEqual(compare_node["Transitions"]["NextAction"], "e1000000-0000-4000-8000-000000000020")

        # 3. Available=true Attribute Update node (routes to phone check & transfer)
        avail_update = actions.get("e1000000-0000-4000-8000-000000000012")
        self.assertIsNotNone(avail_update)
        self.assertEqual(avail_update["Type"], "UpdateContactAttributes")
        self.assertEqual(avail_update["Parameters"]["Attributes"]["humanAgentPhoneNumber"], "$.External.agentPhone")
        self.assertEqual(avail_update["Transitions"]["NextAction"], "e1000000-0000-4000-8000-000000000002")

        # 4. Available=false Fallback node (resets callMode to NORMAL and routes to Normal Cara Lex Bot)
        fallback_update = actions.get("e1000000-0000-4000-8000-000000000020")
        self.assertIsNotNone(fallback_update)
        self.assertEqual(fallback_update["Type"], "UpdateContactAttributes")
        self.assertEqual(fallback_update["Parameters"]["Attributes"]["callMode"], "NORMAL")
        self.assertEqual(fallback_update["Transitions"]["NextAction"], "10000000-0000-4000-8000-000000000001")

    def test_mid_call_escalate_path_remains_isolated_and_untouched(self):
        data = json.loads(self.flow_path.read_text(encoding="utf-8"))
        actions = {a["Identifier"]: a for a in data["Actions"]}

        # Mid-call checkAgentAvailability node
        mid_lambda = actions.get("b0000000-0000-4000-8000-000000000010")
        self.assertIsNotNone(mid_lambda)
        self.assertEqual(mid_lambda["Transitions"]["NextAction"], "b0000000-0000-4000-8000-000000000011")

        # Mid-call Compare node
        mid_compare = actions.get("b0000000-0000-4000-8000-000000000011")
        self.assertIsNotNone(mid_compare)
        # Mid-call false branch still routes to callback announcement and scheduling
        self.assertEqual(mid_compare["Transitions"]["NextAction"], "b0000000-0000-4000-8000-000000000013")
        mid_prompt = actions.get("b0000000-0000-4000-8000-000000000013")
        self.assertIsNotNone(mid_prompt)
        self.assertEqual(mid_prompt["Transitions"]["NextAction"], "b0000000-0000-4000-8000-000000000014")
        mid_attr = actions.get("b0000000-0000-4000-8000-000000000014")
        self.assertIsNotNone(mid_attr)
        self.assertEqual(mid_attr["Transitions"]["NextAction"], "a0000000-0000-4000-8000-000000000011")

    def test_agent_phone_safeguard_compare_block(self):
        data = json.loads(self.flow_path.read_text(encoding="utf-8"))
        actions = {a["Identifier"]: a for a in data["Actions"]}

        agent_check_block = actions.get("e1000000-0000-4000-8000-000000000002")
        self.assertIsNotNone(agent_check_block)
        self.assertEqual(agent_check_block["Type"], "Compare")
        self.assertEqual(agent_check_block["Parameters"]["ComparisonValue"], "$.Attributes.humanAgentPhoneNumber")

        # TextStartsWith (+) condition routes to courtesy prompt
        conditions = agent_check_block["Transitions"]["Conditions"]
        plus_cond = next((c for c in conditions if c["Condition"]["Operator"] == "TextStartsWith" and c["Condition"]["Operands"] == ["+"]), None)
        self.assertIsNotNone(plus_cond)
        self.assertEqual(plus_cond["NextAction"], "e1000000-0000-4000-8000-000000000003")

        # Missing or invalid phone number routes to failure prompt via error transition and default fallback
        errors = agent_check_block["Transitions"]["Errors"]
        no_match = next((e for e in errors if e["ErrorType"] == "NoMatchingCondition"), None)
        self.assertIsNotNone(no_match)
        self.assertEqual(no_match["NextAction"], "e1000000-0000-4000-8000-000000000005")
        self.assertEqual(agent_check_block["Transitions"]["NextAction"], "e1000000-0000-4000-8000-000000000005")

    def test_transfer_to_phone_number_block_parameters(self):
        data = json.loads(self.flow_path.read_text(encoding="utf-8"))
        actions = {a["Identifier"]: a for a in data["Actions"]}

        transfer_block = actions.get("e1000000-0000-4000-8000-000000000004")
        self.assertIsNotNone(transfer_block)
        self.assertEqual(transfer_block["Type"], "TransferParticipantToThirdParty")
        self.assertEqual(transfer_block["Parameters"]["ThirdPartyPhoneNumber"], "$.Attributes.humanAgentPhoneNumber")
        self.assertEqual(transfer_block["Parameters"]["ThirdPartyConnectionTimeLimitSeconds"], "60")
        self.assertEqual(transfer_block["Parameters"]["ContinueFlowExecution"], "False")

        caller_id_block = actions.get("e1000000-0000-4000-8000-000000000006")
        self.assertIsNotNone(caller_id_block)
        self.assertEqual(caller_id_block["Type"], "UpdateContactAttributes")
        self.assertEqual(caller_id_block["Parameters"]["Attributes"]["CallerIdNumber"], "$.SystemEndpoint.Address")

        # Error transition points to failure prompt block
        errors = transfer_block["Transitions"]["Errors"]
        error_trans = next((e for e in errors if e["ErrorType"] == "NoMatchingError"), None)
        self.assertIsNotNone(error_trans)
        self.assertEqual(error_trans["NextAction"], "e1000000-0000-4000-8000-000000000005")


if __name__ == "__main__":
    unittest.main()
