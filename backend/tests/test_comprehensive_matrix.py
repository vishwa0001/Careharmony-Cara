import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lambda"))

os.environ.setdefault("CONNECT_CONTACT_FLOW_ID", "flow-123")
os.environ.setdefault("CONNECT_INSTANCE_ID", "inst-123")
os.environ.setdefault("CONNECT_SOURCE_PHONE_NUMBER", "+18005550100")
os.environ.setdefault("AWS_LAMBDA_FUNCTION_NAME", "cara-health-bot-campaign-dialer")
os.environ.setdefault("BATCHES_TABLE_NAME", "TalkingBotCallBatches-dev")
os.environ.setdefault("PATIENTS_TABLE_NAME", "TalkingBotPatientRecords-dev")

import campaign_intake
import campaign_dialer
import session_context
from utils.agent_availability import check_agent_availability


class ComprehensiveMatrixTests(unittest.TestCase):

    # -------------------------------------------------------------
    # 1. INTAKE PARSING & HEADER PERMUTATIONS
    # -------------------------------------------------------------
    def test_intake_header_and_value_variations(self):
        cases = [
            ("direct_agent", "yes", "yes", "DIRECT_HUMAN_HANDOFF"),
            ("direct_agent", "YES", "yes", "DIRECT_HUMAN_HANDOFF"),
            ("direct_agent", "Yes ", "yes", "DIRECT_HUMAN_HANDOFF"),
            ("direct_agent", "no", "no", "NORMAL"),
            ("direct_agent", "NO", "no", "NORMAL"),
            ("direct_agent", "", "no", "NORMAL"),
            ("directAgent", "yes", "yes", "DIRECT_HUMAN_HANDOFF"),
            ("direct agent", "yes", "yes", "DIRECT_HUMAN_HANDOFF"),
        ]
        for header, val, exp_direct, exp_mode in cases:
            with self.subTest(header=header, value=val):
                csv = (
                    f"empi,first_name,last_name,gender,phone_number,practice_name,practice_callback_number,{header}\n"
                    f"P1,Jane,Doe,Female,+18145551001,Practice X,+18005550100,{val}\n"
                )
                mock_s3 = MagicMock()
                mock_s3.get_object.return_value = {"Body": io.BytesIO(csv.encode("utf-8"))}
                res = campaign_intake._load_patients(mock_s3, "b", "c")
                self.assertEqual(res[0]["direct_agent"], exp_direct)
                self.assertEqual(res[0]["callMode"], exp_mode)

    def test_intake_invalid_values_fail_safely(self):
        invalid_vals = ["maybe", "true", "1", "AGENT", "unknown"]
        for val in invalid_vals:
            with self.subTest(value=val):
                csv = (
                    f"empi,first_name,last_name,gender,phone_number,practice_name,practice_callback_number,direct_agent\n"
                    f"P1,Jane,Doe,Female,+18145551001,Practice X,+18005550100,{val}\n"
                )
                mock_s3 = MagicMock()
                mock_s3.get_object.return_value = {"Body": io.BytesIO(csv.encode("utf-8"))}
                with self.assertRaises(ValueError):
                    campaign_intake._load_patients(mock_s3, "b", "c")

    # -------------------------------------------------------------
    # 2. AGENT AVAILABILITY API PERMUTATIONS
    # -------------------------------------------------------------
    @patch("requests.get")
    def test_agent_availability_api_responses(self, mock_get):
        # Case A: Available True
        mock_get.return_value.raise_for_status = MagicMock()
        mock_get.return_value.json.return_value = {"available": True, "agentPhone": "+15822671755"}
        self.assertTrue(check_agent_availability({"patientId": "p1"}))

        # Case B: Available False
        mock_get.return_value.json.return_value = {"available": False}
        self.assertFalse(check_agent_availability({"patientId": "p2"}))

        # Case C: HTTP 500
        mock_get.side_effect = Exception("HTTP 500 Server Error")
        self.assertFalse(check_agent_availability({"patientId": "p3"}))

        # Case D: Network Timeout
        mock_get.side_effect = Exception("Connection Timeout after 5000ms")
        self.assertFalse(check_agent_availability({"patientId": "p4"}))

    # -------------------------------------------------------------
    # 3. CALL PLACEMENT ROUTING MATRIX
    # -------------------------------------------------------------
    def test_call_placement_matrix(self):
        mock_table = MagicMock()
        mock_connect = MagicMock()
        mock_connect.start_outbound_voice_contact.return_value = {"ContactId": "c-123"}

        test_matrix = [
            # direct_agent, initial callMode, agent_avail, exp_call_mode, exp_has_agent_phone, exp_coaching_greeting
            ("yes", "DIRECT_HUMAN_HANDOFF", True,  "DIRECT_HUMAN_HANDOFF", True,  False),
            ("yes", "DIRECT_HUMAN_HANDOFF", False, "NORMAL",               False, True),
            ("yes", "NORMAL",               True,  "DIRECT_HUMAN_HANDOFF", True,  False),
            ("yes", "NORMAL",               False, "NORMAL",               False, True),
            ("no",  "NORMAL",               True,  "NORMAL",               False, True),
            ("no",  "NORMAL",               False, "NORMAL",               False, True),
        ]

        for direct_val, init_mode, avail, exp_mode, exp_agent_phone, exp_greeting in test_matrix:
            with self.subTest(direct_agent=direct_val, init_mode=init_mode, avail=avail):
                mock_connect.reset_mock()
                patient = {
                    "patientId": "P-TEST",
                    "firstName": "Alice",
                    "lastName": "Walker",
                    "customerName": "Alice Walker",
                    "phoneNumber": "+18145559999",
                    "practiceName": "Health Center",
                    "direct_agent": direct_val,
                    "callMode": init_mode,
                }
                with patch("campaign_dialer.check_agent_availability", return_value=avail), \
                     patch("campaign_dialer._check_agent_availability", return_value={"available": avail, "agentPhone": "+15822671755" if avail else None}):
                    contact_id = campaign_dialer._place_call(mock_table, mock_connect, patient, "camp-1")
                    attrs = mock_connect.start_outbound_voice_contact.call_args[1]["Attributes"]
                    
                    self.assertEqual(attrs["callMode"], exp_mode)
                    self.assertEqual(attrs["direct_agent"], direct_val)
                    if exp_agent_phone:
                        self.assertIn("humanAgentPhoneNumber", attrs)
                        self.assertEqual(attrs["humanAgentPhoneNumber"], "+15822671755")
                    else:
                        self.assertNotIn("humanAgentPhoneNumber", attrs)
                    if exp_greeting:
                        self.assertIn("coachingGreeting", attrs)
                        self.assertIn("Please hold while I connect you now", attrs["coachingGreeting"])

    # -------------------------------------------------------------
    # 4. SESSION CONTEXT ATTRIBUTE FORWARDING
    # -------------------------------------------------------------
    @patch("session_context.boto3")
    def test_session_context_attributes(self, mock_boto3):
        mock_q = MagicMock()
        mock_boto3.client.return_value = mock_q
        asst_id = "11111111-1111-4111-8111-111111111111"
        sess_id = "22222222-2222-4222-8222-222222222222"
        event = {
            "Details": {
                "Parameters": {
                    "operation": "initialize",
                    "assistantId": asst_id,
                    "sessionArn": f"arn:aws:wisdom:us-east-1:123456789012:session/{asst_id}/{sess_id}",
                    "customerName": "Robert Frost",
                    "expectedPhone": "+18145550000",
                    "direct_agent": "yes",
                    "practiceName": "Cedar Clinic",
                    "firstName": "Robert",
                }
            }
        }
        res = session_context.handler(event, None)
        self.assertEqual(res["contextStatus"], "READY")
        update_call = mock_q.update_session_data.call_args[1]
        data_keys = {item["key"]: item["value"]["stringValue"] for item in update_call["data"]}
        self.assertEqual(data_keys["direct_agent"], "yes")
        self.assertEqual(data_keys["practiceName"], "Cedar Clinic")
        self.assertEqual(data_keys["firstName"], "Robert")
        self.assertEqual(data_keys["identityConfirmed"], "true")

    # -------------------------------------------------------------
    # 5. DYNAMODB STATUS MATRIX (ALL CALL OUTCOMES)
    # -------------------------------------------------------------
    def test_status_transition_matrix(self):
        outcomes = [
            # Reason, State, Disp, Expected Status
            ({"caraEndReason": "refusal"}, "IN_PROGRESS", "Identity Confirmed", "NOT_INTERESTED"),
            ({"caraEndReason": "do_not_call"}, "IN_PROGRESS", "Identity Confirmed", "NOT_INTERESTED"),
            ({"caraEndReason": "not_interested"}, "IN_PROGRESS", "Identity Confirmed", "NOT_INTERESTED"),
            ({}, "NOT_INTERESTED", "Identity Confirmed", "NOT_INTERESTED"),
            ({}, "IN_PROGRESS", "Call Refused", "NOT_INTERESTED"),
            ({}, "IN_PROGRESS", "Identity Denied - Refusal", "NOT_INTERESTED"),
            ({}, "IN_PROGRESS", "Refusal", "NOT_INTERESTED"),
            ({}, "TRANSFER_COMPLETED", "Identity Confirmed", "COMPLETED"),
            ({}, "IN_PROGRESS", "Identity Confirmed", "COMPLETED"),
        ]

        for attrs, state, disp, exp_status in outcomes:
            with self.subTest(attrs=attrs, state=state, disp=disp):
                mock_table = MagicMock()
                patient = {"patientId": "P-STAT", "batchId": "B-STAT", "contactId": "c-stat"}
                contact = {
                    "ContactId": "c-stat",
                    "Attributes": {**attrs, "conversationState": state},
                }
                with patch("campaign_dialer._classify_contact", return_value=("Confirmed" if "Confirmed" in disp else "Denied", disp)):
                    campaign_dialer._finalize_patient(mock_table, patient, contact)
                    update_kwargs = mock_table.update_item.call_args[1]
                    vals = update_kwargs["ExpressionAttributeValues"]
                    status_val = vals.get(":status") or vals.get(":completed")
                    self.assertEqual(status_val, exp_status)
                    # Verify condition expression is always present
                    self.assertEqual(update_kwargs["ConditionExpression"], "#s=:inprogress")

    def test_callback_status_unspecified_vs_scheduled(self):
        import datetime as dt
        # Unspecified Callback -> CALLBACK_UNSPECIFIED
        mock_table = MagicMock()
        patient = {"patientId": "P-CB1", "batchId": "B-CB1", "contactId": "c-cb1"}
        plan_unspec = {"requestedBy": "PATIENT", "callbackWhen": "", "callbackReason": "unspecified"}
        campaign_dialer._finalize_callback_without_schedule(mock_table, patient, plan_unspec, {})
        update_unspec = mock_table.update_item.call_args[1]
        self.assertEqual(update_unspec["ExpressionAttributeValues"][":status"], "CALLBACK_UNSPECIFIED")
        self.assertEqual(update_unspec["ConditionExpression"], "#s=:inprogress")

        # Scheduled Callback -> CALLBACK_SCHEDULED
        with patch("campaign_dialer._create_callback_schedule", return_value=("sched-1", "2026-09-01T15:00:00Z")):
            mock_table.reset_mock()
            cb_time = dt.datetime(2026, 9, 1, 15, 0, 0, tzinfo=dt.timezone.utc)
            plan_sched = {
                "requestedBy": "PATIENT",
                "callbackAt": cb_time,
                "callbackWhen": "tomorrow at 11am",
                "disposition": "Callback Requested - Time Specified",
                "identityResult": "Confirmed",
            }
            campaign_dialer._schedule_callback(mock_table, patient, plan_sched, {})
            update_sched = mock_table.update_item.call_args[1]
            self.assertEqual(update_sched["ExpressionAttributeValues"][":scheduled"], "CALLBACK_SCHEDULED")
            self.assertEqual(update_sched["ConditionExpression"], "#s=:inprogress")

    def test_setup_failed_status(self):
        mock_table = MagicMock()
        patient = {"patientId": "P-FAIL", "batchId": "B-FAIL"}
        campaign_dialer._mark_setup_failed(mock_table, patient, reason="Connect rate limit reached")
        update_fail = mock_table.update_item.call_args[1]
        self.assertEqual(update_fail["ExpressionAttributeValues"][":failed"], "FAILED")
        self.assertEqual(update_fail["ExpressionAttributeValues"][":reason"], "Connect rate limit reached")
        self.assertEqual(update_fail["ConditionExpression"], "#s=:inprogress")


if __name__ == "__main__":
    unittest.main()
