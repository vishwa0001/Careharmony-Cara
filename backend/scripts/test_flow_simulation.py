import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class FlowExecutionSimulationTests(unittest.TestCase):
    def setUp(self):
        flow_path = ROOT / "contact-flows" / "cara-health-bot-flow.json"
        self.flow = json.loads(flow_path.read_text(encoding="utf-8"))
        self.actions = {a["Identifier"]: a for a in self.flow["Actions"]}

    def simulate_flow(self, initial_attributes, mock_lambda_results, mock_lex_intents=None):
        """Simulates step-by-step execution through the Connect Contact Flow JSON."""
        curr_id = self.flow["StartAction"]
        attributes = dict(initial_attributes)
        trace = []
        prompts_spoken = []
        mock_lex = list(mock_lex_intents or [])

        while curr_id and curr_id != "77777777-7777-4777-8777-777777777777":
            action = self.actions[curr_id]
            act_type = action["Type"]
            trace.append((curr_id, act_type))

            if act_type == "UpdateContactAttributes":
                for k, v in action["Parameters"].get("Attributes", {}).items():
                    # Resolve $.External.* or $.Attributes.* or $.SystemEndpoint.*
                    if v.startswith("$.External."):
                        ext_key = v.split("$.External.")[1]
                        attributes[k] = mock_lambda_results.get(ext_key, "")
                    elif v.startswith("$.Attributes."):
                        attr_key = v.split("$.Attributes.")[1]
                        attributes[k] = attributes.get(attr_key, "")
                    else:
                        attributes[k] = v
                curr_id = action["Transitions"].get("NextAction")

            elif act_type == "Compare":
                comp_param = action["Parameters"]["ComparisonValue"]
                val = ""
                if comp_param.startswith("$.Attributes."):
                    val = attributes.get(comp_param.split("$.Attributes.")[1], "")
                elif comp_param.startswith("$.External."):
                    val = mock_lambda_results.get(comp_param.split("$.External.")[1], "")
                
                matched_next = None
                for cond in action["Transitions"].get("Conditions", []):
                    op = cond["Condition"]["Operator"]
                    operands = cond["Condition"]["Operands"]
                    if op == "Equals" and val == operands[0]:
                        matched_next = cond["NextAction"]
                        break
                    elif op == "TextStartsWith" and val.startswith(operands[0]):
                        matched_next = cond["NextAction"]
                        break
                
                if matched_next:
                    curr_id = matched_next
                else:
                    curr_id = action["Transitions"].get("NextAction")

            elif act_type == "InvokeLambdaFunction":
                op = action["Parameters"]["LambdaInvocationAttributes"]["operation"]
                if op == "checkAgentAvailability":
                    # Simulated result already in mock_lambda_results
                    pass
                curr_id = action["Transitions"].get("NextAction")

            elif act_type == "MessageParticipant":
                txt = action["Parameters"].get("Text", "")
                if txt.startswith("$.Attributes."):
                    attr_key = txt.split("$.Attributes.")[1]
                    txt = attributes.get(attr_key, txt)
                prompts_spoken.append(txt)
                curr_id = action["Transitions"].get("NextAction")

            elif act_type in ("ConnectParticipantWithLexBot", "GetUserInput"):
                lex_prompt = action["Parameters"].get("Text", "")
                if lex_prompt.startswith("$.Attributes."):
                    attr_key = lex_prompt.split("$.Attributes.")[1]
                    lex_prompt = attributes.get(attr_key, lex_prompt)
                prompts_spoken.append(lex_prompt)

                if mock_lex:
                    intent = mock_lex.pop(0)
                    matched_next = None
                    for cond in action["Transitions"].get("Conditions", []):
                        op = cond["Condition"]["Operator"]
                        operands = cond["Condition"]["Operands"]
                        if op == "Equals" and intent == operands[0]:
                            matched_next = cond["NextAction"]
                            break
                    if matched_next:
                        curr_id = matched_next
                    else:
                        curr_id = action["Transitions"].get("NextAction")
                else:
                    break
            elif act_type == "TransferParticipantToThirdParty":
                break
            else:
                curr_id = action["Transitions"].get("NextAction")

        return trace, attributes, prompts_spoken, curr_id

    def test_direct_handoff_available_true(self):
        initial_attrs = {
            "callMode": "DIRECT_HUMAN_HANDOFF",
            "customerName": "Jane Smith",
            "identityPrompt": "Hi, may I speak with Jane Smith?",
        }
        mock_lambda = {
            "available": "true",
            "agentPhone": "+15822671755",
            "agentId": "agent-001",
            "agentName": "Sarah Jenkins",
        }
        trace, final_attrs, prompts, end_node_id = self.simulate_flow(initial_attrs, mock_lambda)
        
        # Verify transfer node is reached
        self.assertEqual(end_node_id, "e1000000-0000-4000-8000-000000000004")
        self.assertEqual(self.actions[end_node_id]["Type"], "TransferParticipantToThirdParty")
        self.assertIn("Please hold while I connect your call to a human representative.", prompts)
        self.assertEqual(final_attrs["humanAgentPhoneNumber"], "+15822671755")
        self.assertEqual(final_attrs["agentName"], "Sarah Jenkins")

    def test_direct_handoff_available_false_falls_back_to_normal(self):
        initial_attrs = {
            "callMode": "DIRECT_HUMAN_HANDOFF",
            "customerName": "Jane Smith",
            "identityPrompt": "Hi, may I speak with Jane Smith?",
        }
        mock_lambda = {
            "available": "false",
            "agentPhone": None,
            "agentId": None,
            "agentName": None,
        }
        trace, final_attrs, prompts, end_node_id = self.simulate_flow(initial_attrs, mock_lambda)
        
        # Verify transfer is NOT reached; instead normal Cara Lex Bot opening is reached
        self.assertEqual(end_node_id, "10000000-0000-4000-8000-000000000001")
        self.assertEqual(self.actions[end_node_id]["Type"], "ConnectParticipantWithLexBot")
        self.assertEqual(final_attrs["callMode"], "NORMAL")
        self.assertEqual(prompts, ["Hi, may I speak with Jane Smith?"])

    def test_turn1_ambiguous_turn2_mumbled_turn3_double_check_confirmed(self):
        initial_attrs = {
            "callMode": "NORMAL",
            "customerName": "Angela Ha",
            "firstName": "Angela",
            "identityPrompt": "Hi, may I speak with Angela Ha?",
            "identityClarification": "I'm Cara, an automated assistant, and I'm trying to reach Angela Ha. I can explain more once I confirm I'm speaking with the right person. Are you Angela Ha?",
            "identityDoubleCheckPrompt": "Just to double check, is this Angela?",
            "identityFailureMessage": "Thanks. I need to speak directly with Angela Ha, so I'll end the call here. Have a good day.",
        }
        # Turn 1: "Sorry, who is this?" (IdentityAmbiguous)
        # Turn 2: "Um." (IdentityAmbiguous)
        # Turn 3: "Yes." (IdentityConfirmed)
        trace, final_attrs, prompts, end_node_id = self.simulate_flow(
            initial_attrs,
            mock_lambda_results={},
            mock_lex_intents=["IdentityAmbiguous", "IdentityAmbiguous", "IdentityConfirmed"],
        )
        
        # Verify 3 identity prompts spoken in exact sequence
        self.assertEqual(prompts[:3], [
            "Hi, may I speak with Angela Ha?",
            "I'm Cara, an automated assistant, and I'm trying to reach Angela Ha. I can explain more once I confirm I'm speaking with the right person. Are you Angela Ha?",
            "Just to double check, is this Angela?",
        ])
        
        # Must confirm identity and proceed toward transfer
        self.assertEqual(final_attrs["identityResult"], "Confirmed")
        self.assertEqual(final_attrs["identityConfirmed"], "true")

    def test_turn1_ambiguous_turn2_mumbled_turn3_still_ambiguous_disconnects(self):
        initial_attrs = {
            "callMode": "NORMAL",
            "customerName": "Angela Ha",
            "firstName": "Angela",
            "identityPrompt": "Hi, may I speak with Angela Ha?",
            "identityClarification": "I'm Cara, an automated assistant, and I'm trying to reach Angela Ha. I can explain more once I confirm I'm speaking with the right person. Are you Angela Ha?",
            "identityDoubleCheckPrompt": "Just to double check, is this Angela?",
            "identityFailureMessage": "Thanks. I need to speak directly with Angela Ha, so I'll end the call here. Have a good day.",
        }
        # Turn 1: "Sorry, who is this?" (IdentityAmbiguous)
        # Turn 2: "Um." (IdentityAmbiguous)
        # Turn 3: "Um." (IdentityAmbiguous)
        trace, final_attrs, prompts, end_node_id = self.simulate_flow(
            initial_attrs,
            mock_lambda_results={},
            mock_lex_intents=["IdentityAmbiguous", "IdentityAmbiguous", "IdentityAmbiguous"],
        )
        
        # Verify 3 prompts spoken + terminal failure message
        self.assertEqual(prompts[0], "Hi, may I speak with Angela Ha?")
        self.assertEqual(prompts[1], "I'm Cara, an automated assistant, and I'm trying to reach Angela Ha. I can explain more once I confirm I'm speaking with the right person. Are you Angela Ha?")
        self.assertEqual(prompts[2], "Just to double check, is this Angela?")
        self.assertIn("Thanks. I need to speak directly with Angela Ha, so I'll end the call here. Have a good day.", prompts)
        
        # Must record Ambiguous identityResult and reach disconnect
        self.assertEqual(final_attrs["identityResult"], "Ambiguous")
        node_ids = [t[0] for t in trace]
        self.assertIn("10000000-0000-4000-8000-000000000007", node_ids)
        self.assertIn("e0000000-0000-4000-8000-000000000006", node_ids)
        self.assertIn("10000000-0000-4000-8000-000000000005", node_ids)

if __name__ == "__main__":
    unittest.main()
