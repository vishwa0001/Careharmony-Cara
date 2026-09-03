"""Unit tests for Scheduled Direct Human Handoff campaign feature with campaign-level toggle."""
from __future__ import annotations

import io
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lambda"))

import campaign_api
import campaign_intake
import campaign_dialer
from cara_health_bot.phone_utils import normalize_phone_e164, validate_destination_prefix


class TestScheduledDirectHandoff(unittest.TestCase):
    def setUp(self):
        os.environ["BATCHES_TABLE_NAME"] = "TalkingBotCallBatches-dev"
        os.environ["PATIENTS_TABLE_NAME"] = "TalkingBotPatientRecords-dev"
        os.environ["CAMPAIGN_BUCKET"] = "test-bucket"
        os.environ["ALLOWED_DESTINATION_PREFIXES"] = "+1"
        os.environ["CONNECT_CONTACT_FLOW_ID"] = "flow-123"
        os.environ["CONNECT_INSTANCE_ID"] = "inst-123"
        os.environ["CONNECT_SOURCE_PHONE_NUMBER"] = "+18005550100"
        os.environ["FIXED_HUMAN_AGENT_PHONE_NUMBER"] = "+15822671755"

    def test_phone_utils(self):
        self.assertEqual(normalize_phone_e164("+18145551212"), "+18145551212")
        self.assertEqual(normalize_phone_e164("8145551212"), "+18145551212")
        self.assertEqual(normalize_phone_e164("18145551212"), "+18145551212")
        with self.assertRaises(ValueError):
            normalize_phone_e164("invalid")

        self.assertTrue(validate_destination_prefix("+18145551212", ["+1"]))
        self.assertFalse(validate_destination_prefix("+448145551212", ["+1"]))

    @patch("campaign_api.boto3")
    def test_campaign_api_create_upload_toggle_off(self, mock_boto3):
        mock_table = MagicMock()
        mock_s3 = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_boto3.client.return_value = mock_s3
        mock_s3.generate_presigned_url.return_value = "https://s3.amazonaws.com/upload"

        payload = {
            "fileName": "patients.csv",
            "scheduledAt": "2030-01-01T10:00:00",
            "timezone": "UTC",
            "customerCount": 5,
            "directAgentEnabled": False,
            "humanAgentPhoneNumber": "+18145551234",
        }
        res = campaign_api._create_upload(payload)
        self.assertIn("campaignId", res)
        put_item_call = mock_table.put_item.call_args[1]["Item"]
        self.assertFalse(put_item_call["directAgentEnabled"])
        self.assertEqual(put_item_call["humanAgentPhoneNumber"], "+18145551234")

    @patch("campaign_api.boto3")
    def test_campaign_api_create_upload_missing_phone_rejected(self, mock_boto3):
        mock_table = MagicMock()
        mock_s3 = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_boto3.client.return_value = mock_s3

        # Missing phone with toggle OFF
        with self.assertRaises(ValueError) as cm_off:
            campaign_api._create_upload({
                "fileName": "patients.csv",
                "scheduledAt": "2030-01-01T10:00:00",
                "timezone": "UTC",
                "customerCount": 5,
                "directAgentEnabled": False,
                "humanAgentPhoneNumber": "",
            })
        self.assertIn("humanAgentPhoneNumber", str(cm_off.exception))

        # Missing phone with toggle ON
        with self.assertRaises(ValueError) as cm_on:
            campaign_api._create_upload({
                "fileName": "patients.csv",
                "scheduledAt": "2030-01-01T10:00:00",
                "timezone": "UTC",
                "customerCount": 5,
                "directAgentEnabled": True,
                "humanAgentPhoneNumber": "",
            })
        self.assertIn("humanAgentPhoneNumber", str(cm_on.exception))

    @patch("campaign_api.boto3")
    def test_campaign_api_create_upload_toggle_on(self, mock_boto3):
        mock_table = MagicMock()
        mock_s3 = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_boto3.client.return_value = mock_s3
        mock_s3.generate_presigned_url.return_value = "https://s3.amazonaws.com/upload"

        payload = {
            "fileName": "patients.csv",
            "scheduledAt": "2030-01-01T10:00:00",
            "timezone": "UTC",
            "customerCount": 5,
            "directAgentEnabled": True,
            "humanAgentPhoneNumber": "+18145551234",
        }
        res = campaign_api._create_upload(payload)
        self.assertIn("campaignId", res)
        put_item_call = mock_table.put_item.call_args[1]["Item"]
        self.assertTrue(put_item_call["directAgentEnabled"])
        self.assertEqual(put_item_call["humanAgentPhoneNumber"], "+18145551234")

    @patch("campaign_api.boto3")
    def test_campaign_api_create_upload_toggle_on_invalid_phone(self, mock_boto3):
        mock_table = MagicMock()
        mock_s3 = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_boto3.client.return_value = mock_s3

        payload = {
            "fileName": "patients.csv",
            "scheduledAt": "2030-01-01T10:00:00",
            "timezone": "UTC",
            "customerCount": 5,
            "directAgentEnabled": True,
            "humanAgentPhoneNumber": "not-a-number",
        }
        with self.assertRaises(ValueError) as cm:
            campaign_api._create_upload(payload)
        self.assertIn("humanAgentPhoneNumber", str(cm.exception))

    @patch("campaign_intake._load_config")
    def test_intake_campaign_level_direct_agent_on(self, mock_load_cfg):
        mock_s3 = MagicMock()
        mock_load_cfg.return_value = {
            "directAgentEnabled": True,
            "humanAgentPhoneNumber": "+18145559999",
        }

        csv_text = (
            "empi,first_name,last_name,gender,phone_number,practice_name,practice_callback_number\n"
            "PT001,John,Doe,Male,18145551001,Practice A,5555550100\n"
            "PT002,Jane,Smith,Female,18145551002,Practice A,5555550100\n"
        )
        mock_s3.get_object.return_value = {"Body": io.BytesIO(csv_text.encode("utf-8"))}

        patients = campaign_intake._load_patients(mock_s3, "bucket", "camp-direct-on", config=mock_load_cfg.return_value)
        self.assertEqual(len(patients), 2)
        for p in patients:
            self.assertEqual(p["direct_agent"], "yes")
            self.assertEqual(p["callMode"], "DIRECT_HUMAN_HANDOFF")
            self.assertEqual(p["humanAgentPhoneNumber"], "+18145559999")

    @patch("campaign_intake._load_config")
    def test_intake_campaign_level_direct_agent_off(self, mock_load_cfg):
        mock_s3 = MagicMock()
        mock_load_cfg.return_value = {
            "directAgentEnabled": False,
            "humanAgentPhoneNumber": "+18145559999",
        }

        csv_text = (
            "empi,first_name,last_name,gender,phone_number,practice_name,practice_callback_number\n"
            "PT001,John,Doe,Male,18145551001,Practice A,5555550100\n"
        )
        mock_s3.get_object.return_value = {"Body": io.BytesIO(csv_text.encode("utf-8"))}

        patients = campaign_intake._load_patients(mock_s3, "bucket", "camp-direct-off", config=mock_load_cfg.return_value)
        self.assertEqual(len(patients), 1)
        self.assertEqual(patients[0]["direct_agent"], "no")
        self.assertEqual(patients[0]["callMode"], "NORMAL")
        self.assertEqual(patients[0]["humanAgentPhoneNumber"], "+18145559999")

    @patch("campaign_intake._load_config")
    def test_intake_ignores_csv_direct_agent_column(self, mock_load_cfg):
        mock_s3 = MagicMock()
        mock_load_cfg.return_value = {
            "directAgentEnabled": False,
            "humanAgentPhoneNumber": "+18145559999",
        }

        # CSV with legacy 'direct agent' column containing whatever values
        csv_text = (
            "empi,first_name,last_name,gender,phone_number,practice_name,practice_callback_number,direct agent\n"
            "PT001,John,Doe,Male,18145551001,Practice A,5555550100,random_text\n"
        )
        mock_s3.get_object.return_value = {"Body": io.BytesIO(csv_text.encode("utf-8"))}

        patients = campaign_intake._load_patients(mock_s3, "bucket", "camp-ignore-col", config=mock_load_cfg.return_value)
        self.assertEqual(len(patients), 1)
        # Column is ignored; campaign-level directAgentEnabled=False governs
        self.assertEqual(patients[0]["direct_agent"], "no")
        self.assertEqual(patients[0]["callMode"], "NORMAL")
        self.assertEqual(patients[0]["humanAgentPhoneNumber"], "+18145559999")

    @patch("campaign_dialer.boto3")
    def test_campaign_dialer_attributes_hygiene(self, mock_boto3):
        mock_table = MagicMock()
        mock_connect = MagicMock()

        patient_normal = {
            "patientId": "PT-100",
            "customerName": "John Doe",
            "phoneNumber": "+18145551111",
            "callMode": "NORMAL",
            "humanAgentPhoneNumber": "+18145551234",
            "practiceName": "Cedar Clinic",
        }
        campaign_dialer._place_call(mock_table, mock_connect, patient_normal, "camp-1")

        call_kwargs = mock_connect.start_outbound_voice_contact.call_args[1]
        attrs_normal = call_kwargs["Attributes"]
        self.assertIn("identityPrompt", attrs_normal)
        self.assertEqual(attrs_normal["humanAgentPhoneNumber"], "+18145551234")

        # Direct mode attributes hygiene test
        mock_connect.reset_mock()
        patient_direct = {
            "patientId": "PT-200",
            "customerName": "Jane Smith",
            "phoneNumber": "+18145552222",
            "callMode": "DIRECT_HUMAN_HANDOFF",
            "humanAgentPhoneNumber": "+15822671755",
            "practiceName": "Cedar Clinic",
        }
        campaign_dialer._place_call(mock_table, mock_connect, patient_direct, "camp-2")

        call_kwargs_direct = mock_connect.start_outbound_voice_contact.call_args[1]
        attrs_direct = call_kwargs_direct["Attributes"]

        # Must contain required direct handoff attributes set from config
        self.assertEqual(attrs_direct["customerName"], "Jane Smith")
        self.assertEqual(attrs_direct["expectedPhone"], "+18145552222")
        self.assertEqual(attrs_direct["humanAgentPhoneNumber"], "+15822671755")
        self.assertEqual(attrs_direct["callMode"], "DIRECT_HUMAN_HANDOFF")
        self.assertIn("identityPrompt", attrs_direct)
        self.assertIn("coachingGreeting", attrs_direct)

    @patch("urllib.request.urlopen")
    def test_session_context_ui_number_priority_overrides_mock_agent_phone(self, mock_urlopen):
        import session_context
        # Mock returns a phone number different from the UI-provided number
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "available": True,
            "agentPhone": "+15822671755",
            "agentId": "agent-002",
            "agentName": "Sarah Jenkins",
            "checkedAt": "2026-09-02T12:00:00Z",
        }).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        event = {
            "Details": {
                "Parameters": {
                    "operation": "checkAgentAvailability",
                    "patientId": "PT-300",
                    "empi": "EMPI-300",
                },
                "ContactData": {
                    "Attributes": {
                        "humanAgentPhoneNumber": "+18145559999",  # UI-provided number
                        "patientId": "PT-300",
                    }
                }
            }
        }

        result = session_context.handler(event, None)

        # UI-provided number MUST win over mock-returned number
        self.assertEqual(result["available"], "true")
        self.assertEqual(result["agentPhone"], "+18145559999")
        self.assertNotEqual(result["agentPhone"], "+15822671755")
        self.assertEqual(result["agentId"], "agent-002")
        self.assertEqual(result["agentName"], "Sarah Jenkins")

    @patch("urllib.request.urlopen")
    def test_session_context_mock_agent_phone_fallback_when_ui_number_missing(self, mock_urlopen):
        import session_context
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "available": True,
            "agentPhone": "+15822671755",
            "agentId": "agent-001",
            "agentName": "Sarah Jenkins",
            "checkedAt": "2026-09-02T12:00:00Z",
        }).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        event = {
            "Details": {
                "Parameters": {
                    "operation": "checkAgentAvailability",
                    "patientId": "PT-400",
                },
                "ContactData": {
                    "Attributes": {
                        "humanAgentPhoneNumber": "",  # No UI number
                        "patientId": "PT-400",
                    }
                }
            }
        }

        result = session_context.handler(event, None)

        # Falls back to mock API agentPhone
        self.assertEqual(result["available"], "true")
        self.assertEqual(result["agentPhone"], "+15822671755")
        self.assertEqual(result["agentId"], "agent-001")
        self.assertEqual(result["agentName"], "Sarah Jenkins")

    @patch("urllib.request.urlopen")
    def test_session_context_unavailable_branch(self, mock_urlopen):
        import session_context
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "available": False,
            "agentPhone": None,
            "agentId": None,
            "agentName": None,
            "checkedAt": "2026-09-02T12:00:00Z",
        }).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        event = {
            "Details": {
                "Parameters": {
                    "operation": "checkAgentAvailability",
                    "patientId": "PT-500",
                },
                "ContactData": {
                    "Attributes": {
                        "humanAgentPhoneNumber": "+18145559999",
                        "patientId": "PT-500",
                    }
                }
            }
        }

        result = session_context.handler(event, None)

        # Returns available="false"
        self.assertEqual(result["available"], "false")
        self.assertEqual(result["agentId"], "")
        self.assertEqual(result["agentName"], "")


if __name__ == "__main__":
    unittest.main()

