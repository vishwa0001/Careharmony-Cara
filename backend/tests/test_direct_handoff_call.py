from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.direct_handoff_call import (
    load_outputs,
    main,
    normalize_phone,
    redact,
    validate_customer_name,
)


class DirectHandoffCallTests(unittest.TestCase):
    def test_normalize_phone_valid_formats(self):
        self.assertEqual(normalize_phone("8145551212"), "+18145551212")
        self.assertEqual(normalize_phone("18145551212"), "+18145551212")
        self.assertEqual(normalize_phone("+18145551212"), "+18145551212")
        self.assertEqual(normalize_phone("  +18145559999  "), "+18145559999")

    def test_normalize_phone_invalid_formats(self):
        with self.assertRaises(ValueError):
            normalize_phone("123")
        with self.assertRaises(ValueError):
            normalize_phone("invalid")
        with self.assertRaises(ValueError):
            normalize_phone("")

    def test_validate_customer_name(self):
        self.assertEqual(validate_customer_name("  John   Doe  "), "John Doe")
        self.assertEqual(validate_customer_name("Mary-Jane O'Connor"), "Mary-Jane O'Connor")
        with self.assertRaises(ValueError):
            validate_customer_name("")
        with self.assertRaises(ValueError):
            validate_customer_name("a" * 81)
        with self.assertRaises(ValueError):
            validate_customer_name("John123")
        with self.assertRaises(ValueError):
            validate_customer_name("Jane @ Work")

    def test_redact(self):
        self.assertEqual(redact("+18145551212"), "+1814555XXXX")
        self.assertEqual(redact("123456"), "123456")
        self.assertEqual(redact("123"), "123")

    @mock.patch("sys.argv", ["direct_handoff_call.py", "8145551212", "--customer-name", "John Doe", "--human-agent-phone", "8145559999"])
    def test_main_missing_consent(self):
        with mock.patch("scripts.direct_handoff_call.load_config"):
            ret = main()
            self.assertEqual(ret, 2)

    @mock.patch("sys.argv", ["direct_handoff_call.py", "invalid_phone", "--customer-name", "John Doe", "--human-agent-phone", "8145559999", "--i-confirm-consent"])
    def test_main_invalid_customer_phone(self):
        ret = main()
        self.assertEqual(ret, 2)

    @mock.patch("sys.argv", ["direct_handoff_call.py", "8145551212", "--customer-name", "John Doe", "--human-agent-phone", "invalid_phone", "--i-confirm-consent"])
    def test_main_invalid_human_agent_phone(self):
        ret = main()
        self.assertEqual(ret, 2)

    @mock.patch("sys.argv", ["direct_handoff_call.py", "+448145551212", "--customer-name", "John Doe", "--human-agent-phone", "8145559999", "--i-confirm-consent"])
    def test_main_disallowed_prefix_customer_phone(self):
        mock_cfg = mock.MagicMock()
        mock_cfg.allowed_destination_prefixes = ("+1",)
        with mock.patch("scripts.direct_handoff_call.load_config", return_value=mock_cfg):
            ret = main()
            self.assertEqual(ret, 2)

    @mock.patch("sys.argv", ["direct_handoff_call.py", "8145551212", "--customer-name", "John Doe", "--human-agent-phone", "+448145559999", "--i-confirm-consent"])
    def test_main_disallowed_prefix_human_agent_phone(self):
        mock_cfg = mock.MagicMock()
        mock_cfg.allowed_destination_prefixes = ("+1",)
        with mock.patch("scripts.direct_handoff_call.load_config", return_value=mock_cfg):
            ret = main()
            self.assertEqual(ret, 2)

    @mock.patch("sys.argv", ["direct_handoff_call.py", "8145551212", "--customer-name", "John Doe", "--human-agent-phone", "8145559999", "--i-confirm-consent", "--dry-run"])
    def test_main_dry_run_success(self):
        fake_outputs = {
            "InstanceId": "test-instance",
            "ContactFlowId": "test-flow",
            "SourcePhoneNumber": "+18005550000",
            "Region": "us-east-1",
        }
        with mock.patch("scripts.direct_handoff_call.load_outputs", return_value=fake_outputs), \
             mock.patch("boto3.client") as mock_boto:
            ret = main()
            self.assertEqual(ret, 0)
            mock_boto.assert_not_called()

    @mock.patch("sys.argv", ["direct_handoff_call.py", "8145551212", "--customer-name", "John Doe", "--human-agent-phone", "8145559999", "--i-confirm-consent"])
    def test_main_live_call_success(self):
        fake_outputs = {
            "InstanceId": "test-instance",
            "ContactFlowId": "test-flow",
            "SourcePhoneNumber": "+18005550000",
            "Region": "us-east-1",
        }
        mock_connect = mock.MagicMock()
        mock_connect.start_outbound_voice_contact.return_value = {"ContactId": "test-contact-123"}

        with mock.patch("scripts.direct_handoff_call.load_outputs", return_value=fake_outputs), \
             mock.patch("boto3.client", return_value=mock_connect) as mock_boto:
            ret = main()
            self.assertEqual(ret, 0)
            mock_boto.assert_called_once_with("connect", region_name="us-east-1")
            mock_connect.start_outbound_voice_contact.assert_called_once()
            kwargs = mock_connect.start_outbound_voice_contact.call_args.kwargs
            self.assertEqual(kwargs["DestinationPhoneNumber"], "+18145551212")
            self.assertEqual(kwargs["Attributes"]["customerName"], "John Doe")
            self.assertEqual(kwargs["Attributes"]["humanAgentPhoneNumber"], "+18145559999")
            self.assertEqual(kwargs["Attributes"]["callMode"], "DIRECT_HUMAN_HANDOFF")


if __name__ == "__main__":
    unittest.main()
