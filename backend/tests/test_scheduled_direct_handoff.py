"""Unit tests for Scheduled Direct Human Handoff campaign feature with per-row CSV toggle."""
from __future__ import annotations

import io
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
    def test_campaign_api_create_upload(self, mock_boto3):
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
        }
        res = campaign_api._create_upload(payload)
        self.assertIn("campaignId", res)
        put_item_call = mock_table.put_item.call_args[1]["Item"]
        self.assertNotIn("callMode", put_item_call)
        self.assertNotIn("humanAgentPhoneNumber", put_item_call)

    @patch("campaign_intake.boto3")
    def test_intake_direct_agent_values(self, mock_boto3):
        mock_s3 = MagicMock()

        # 1. Test CSV with mixed direct agent values (yes, YES, no, NO, empty)
        csv_text = (
            "empi,first_name,last_name,gender,phone_number,practice_name,practice_callback_number,direct agent\n"
            "PT001,John,Doe,Male,18145551001,Practice A,5555550100,yes\n"
            "PT002,Jane,Smith,Female,18145551002,Practice A,5555550100,NO\n"
            "PT003,Alex,Sei,Male,18145551003,Practice A,5555550100,YES\n"
            "PT004,Mary,Johnson,Female,18145551004,Practice A,5555550100,\n"
        )
        mock_s3.get_object.return_value = {"Body": io.BytesIO(csv_text.encode("utf-8"))}

        patients = campaign_intake._load_patients(mock_s3, "bucket", "camp-1")
        self.assertEqual(len(patients), 4)

        # PT001: direct agent = yes
        self.assertEqual(patients[0]["callMode"], "DIRECT_HUMAN_HANDOFF")
        self.assertEqual(patients[0]["humanAgentPhoneNumber"], "+15822671755")

        # PT002: direct agent = NO
        self.assertEqual(patients[1]["callMode"], "NORMAL")
        self.assertNotIn("humanAgentPhoneNumber", patients[1])

        # PT003: direct agent = YES
        self.assertEqual(patients[2]["callMode"], "DIRECT_HUMAN_HANDOFF")
        self.assertEqual(patients[2]["humanAgentPhoneNumber"], "+15822671755")

        # PT004: direct agent = empty
        self.assertEqual(patients[3]["callMode"], "NORMAL")
        self.assertNotIn("humanAgentPhoneNumber", patients[3])

    @patch("campaign_intake.boto3")
    def test_intake_legacy_csv_missing_direct_agent_column(self, mock_boto3):
        mock_s3 = MagicMock()

        # Legacy CSV with no direct agent column
        csv_text = (
            "empi,first_name,last_name,gender,phone_number,practice_name,practice_callback_number\n"
            "PT001,John,Doe,Male,18145551001,Practice A,5555550100\n"
        )
        mock_s3.get_object.return_value = {"Body": io.BytesIO(csv_text.encode("utf-8"))}

        patients = campaign_intake._load_patients(mock_s3, "bucket", "camp-legacy")
        self.assertEqual(patients[0]["callMode"], "NORMAL")
        self.assertNotIn("humanAgentPhoneNumber", patients[0])

    @patch("campaign_intake.boto3")
    def test_intake_invalid_direct_agent_values_rejected(self, mock_boto3):
        mock_s3 = MagicMock()

        for invalid_val in ["maybe", "true", "false", "random", "123"]:
            csv_text = (
                f"empi,first_name,last_name,gender,phone_number,practice_name,practice_callback_number,direct agent\n"
                f"PT001,John,Doe,Male,18145551001,Practice A,5555550100,{invalid_val}\n"
            )
            mock_s3.get_object.return_value = {"Body": io.BytesIO(csv_text.encode("utf-8"))}

            with self.assertRaises(ValueError) as cm:
                campaign_intake._load_patients(mock_s3, "bucket", "camp-invalid")
            self.assertIn("invalid direct agent value", str(cm.exception))

    @patch("campaign_dialer._check_agent_availability", return_value={"available": True, "agentPhone": "+15822671755", "checkedAt": "2026-08-31T00:00:00Z"})
    @patch("campaign_dialer.boto3")
    def test_campaign_dialer_attributes_hygiene(self, mock_boto3, mock_avail):
        mock_table = MagicMock()
        mock_connect = MagicMock()

        patient_normal = {
            "patientId": "PT-100",
            "customerName": "John Doe",
            "phoneNumber": "+18145551111",
            "callMode": "NORMAL",
        }
        campaign_dialer._place_call(mock_table, mock_connect, patient_normal, "camp-1")

        call_kwargs = mock_connect.start_outbound_voice_contact.call_args[1]
        attrs_normal = call_kwargs["Attributes"]
        self.assertIn("identityPrompt", attrs_normal)
        self.assertNotIn("humanAgentPhoneNumber", attrs_normal)

        # Direct mode attributes hygiene test
        mock_connect.reset_mock()
        patient_direct = {
            "patientId": "PT-200",
            "customerName": "Jane Smith",
            "phoneNumber": "+18145552222",
            "callMode": "DIRECT_HUMAN_HANDOFF",
            "humanAgentPhoneNumber": "+15822671755",
        }
        campaign_dialer._place_call(mock_table, mock_connect, patient_direct, "camp-2")

        call_kwargs_direct = mock_connect.start_outbound_voice_contact.call_args[1]
        attrs_direct = call_kwargs_direct["Attributes"]
        
        # Must contain required direct handoff attributes
        self.assertEqual(attrs_direct["customerName"], "Jane Smith")
        self.assertEqual(attrs_direct["expectedPhone"], "+18145552222")
        self.assertEqual(attrs_direct["humanAgentPhoneNumber"], "+15822671755")
        self.assertEqual(attrs_direct["callMode"], "DIRECT_HUMAN_HANDOFF")
        self.assertEqual(attrs_direct["agentAvailabilityCheckedAt"], "2026-08-31T00:00:00Z")
        self.assertNotIn("identityPrompt", attrs_direct)
        self.assertNotIn("coachingGreeting", attrs_direct)

    @patch("campaign_dialer.check_agent_availability", return_value=False)
    @patch("campaign_dialer._check_agent_availability", return_value={"available": False, "agentPhone": None, "checkedAt": "2026-08-31T00:00:00Z"})
    def test_direct_handoff_agent_unavailable_falls_back_to_normal(self, mock_avail, mock_check_avail):
        mock_table = MagicMock()
        mock_connect = MagicMock()
        mock_connect.start_outbound_voice_contact.return_value = {"ContactId": "contact-fallback-1"}
        patient_direct = {
            "batchId": "camp-unavail",
            "patientId": "PT-UNAVAIL",
            "customerName": "Jane Smith",
            "phoneNumber": "+18145552222",
            "direct_agent": "yes",
            "callMode": "DIRECT_HUMAN_HANDOFF",
        }
        contact_id = campaign_dialer._place_call(mock_table, mock_connect, patient_direct, "camp-unavail")
        self.assertEqual(contact_id, "contact-fallback-1")
        mock_connect.start_outbound_voice_contact.assert_called_once()
        call_kwargs = mock_connect.start_outbound_voice_contact.call_args[1]
        attrs = call_kwargs["Attributes"]
        self.assertEqual(attrs["callMode"], "NORMAL")
        self.assertEqual(attrs["direct_agent"], "yes")
        self.assertIn("coachingGreeting", attrs)

    @patch("campaign_dialer._check_agent_availability", return_value={"available": True, "agentPhone": "+15822671755", "checkedAt": "2026-08-31T00:00:00Z"})
    @patch("campaign_dialer.boto3")
    def test_campaign_dialer_mixed_patient_execution(self, mock_boto3, mock_avail):
        mock_table = MagicMock()
        mock_connect = MagicMock()

        patient_direct = {
            "patientId": "PT-A",
            "customerName": "Patient A",
            "phoneNumber": "+18145551111",
            "callMode": "DIRECT_HUMAN_HANDOFF",
            "humanAgentPhoneNumber": "+15822671755",
        }
        patient_normal = {
            "patientId": "PT-B",
            "customerName": "Patient B",
            "phoneNumber": "+18145552222",
            "callMode": "NORMAL",
        }

        # Place direct call
        campaign_dialer._place_call(mock_table, mock_connect, patient_direct, "camp-mixed")
        attrs_direct = mock_connect.start_outbound_voice_contact.call_args[1]["Attributes"]
        self.assertEqual(attrs_direct["callMode"], "DIRECT_HUMAN_HANDOFF")
        self.assertEqual(attrs_direct["humanAgentPhoneNumber"], "+15822671755")

        # Place normal call
        mock_connect.reset_mock()
        campaign_dialer._place_call(mock_table, mock_connect, patient_normal, "camp-mixed")
        attrs_normal = mock_connect.start_outbound_voice_contact.call_args[1]["Attributes"]
        self.assertNotIn("humanAgentPhoneNumber", attrs_normal)
        self.assertIn("identityPrompt", attrs_normal)


if __name__ == "__main__":
    unittest.main()
