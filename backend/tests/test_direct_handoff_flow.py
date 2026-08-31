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

        # Verify DIRECT_HUMAN_HANDOFF condition
        conditions = callmode_block["Transitions"]["Conditions"]
        handoff_cond = next((c for c in conditions if c["Condition"]["Operands"] == ["DIRECT_HUMAN_HANDOFF"]), None)
        self.assertIsNotNone(handoff_cond)
        self.assertEqual(handoff_cond["NextAction"], "e1000000-0000-4000-8000-000000000002")

        # Verify Default / Missing transition points to original Identity Lex Bot
        self.assertEqual(callmode_block["Transitions"]["NextAction"], "10000000-0000-4000-8000-000000000001")

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
