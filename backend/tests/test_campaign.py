from __future__ import annotations

import importlib.util
import io
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "lambda" / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


intake = _load("cara_campaign_intake_test", "campaign_intake.py")
dialer = _load("cara_campaign_dialer_test", "campaign_dialer.py")
api = _load("cara_campaign_api_test", "campaign_api.py")


class Body:
    def __init__(self, data: bytes): self.data = data
    def read(self): return self.data


class FakeS3:
    def __init__(self, objects): self.objects = objects
    def get_object(self, Bucket, Key): return {"Body": Body(self.objects[Key])}


class ConditionalTable:
    def __init__(self, fail=False): self.fail = fail; self.calls=[]
    def update_item(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException", "Message": "race"}}, "UpdateItem")
        return {}


class CampaignTests(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {
            "TABLE_NAME": "cara-health-bot-campaign-state",
            "CONNECT_INSTANCE_ID": "instance-1",
            "CONNECT_CONTACT_FLOW_ID": "flow-1",
            "CONNECT_SOURCE_PHONE_NUMBER": "+18775550100",
            "AWS_LAMBDA_FUNCTION_NAME": "cara-health-bot-campaign-dialer",
        }, clear=False)
        self.env.start()
    def tearDown(self): self.env.stop()

    def test_valid_campaign_csv(self):
        csv_data = b"empi,first_name,last_name,gender,phone_number,practice_name,practice_callback_number\nP1,John,Doe,M,+18148316822,North Clinic,+18145550100\n"
        patients = intake._load_patients(FakeS3({"campaigns/c1/patients.csv": csv_data}), "bucket", "c1")
        self.assertEqual(patients[0]["patientId"], "P1")
        self.assertEqual(patients[0]["customerName"], "John Doe")
        self.assertEqual(patients[0]["practiceName"], "North Clinic")

    def test_empty_campaign_rejected(self):
        csv_data = b"empi,first_name,last_name,gender,phone_number,practice_name,practice_callback_number\n"
        with self.assertRaisesRegex(ValueError, "no data rows"):
            intake._load_patients(FakeS3({"campaigns/c1/patients.csv": csv_data}), "bucket", "c1")

    def test_campaign_start_schedule_requires_timezone(self):
        with self.assertRaises(ValueError): intake._schedule_expression_utc("2026-08-20T10:00:00")
        self.assertEqual(intake._schedule_expression_utc("2026-08-20T10:00:00-04:00"), "at(2026-08-20T14:00:00)")

    def test_atomic_patient_claim(self):
        patient={"campaignId":"c1","recordKey":"PATIENT#00000001#p1"}
        self.assertTrue(dialer._claim_patient(ConditionalTable(), patient))
        self.assertFalse(dialer._claim_patient(ConditionalTable(fail=True), patient))

    def test_successful_start_outbound_voice_contact(self):
        class Connect:
            def __init__(self): self.kw=None
            def start_outbound_voice_contact(self, **kwargs): self.kw=kwargs; return {"ContactId":"contact-1"}
        c=Connect(); patient={"patientId":"p1","empi":"p1","phoneNumber":"+18148316822","customerName":"John","firstName":"John","lastName":"Doe","practiceName":"North Clinic","practiceCallbackNumber":"+18145550100"}
        self.assertEqual(dialer._place_call(c, patient, "c1"), "contact-1")
        self.assertEqual(c.kw["ContactFlowId"], "flow-1")
        self.assertEqual(c.kw["Attributes"]["campaignId"], "c1")
        self.assertEqual(c.kw["Attributes"]["patientId"], "p1")

    def test_disposition_mapping_confirmed_denied_ambiguous_missing(self):
        self.assertEqual(dialer._disposition("Confirmed"), "Identity Confirmed")
        self.assertEqual(dialer._disposition("Denied"), "Wrong Person / Identity Denied")
        self.assertEqual(dialer._disposition("Ambiguous"), "Identity Unclear")
        self.assertEqual(dialer._disposition(None), "Unknown / Undetermined")

    def test_missing_identity_is_not_ambiguous(self):
        self.assertNotEqual(dialer._disposition(None), dialer._disposition("Ambiguous"))

    def test_no_answer_not_connected_is_separate_from_ambiguous(self):
        identity, disposition = dialer._classify_contact({"Attributes": {}, "DisconnectReason": "TELECOM_UNANSWERED"})
        self.assertIsNone(identity)
        self.assertEqual(disposition, "No Answer / Not Connected")
        self.assertNotEqual(disposition, dialer._disposition("Ambiguous"))

    def test_duplicate_scheduler_event_does_not_dial_second_patient(self):
        table=object(); connect=object()
        with mock.patch.object(dialer, "_set_campaign_running", return_value=True), \
             mock.patch.object(dialer, "_query_patients", return_value=[{"status":"IN_PROGRESS"}]), \
             mock.patch.object(dialer, "_place_call") as place:
            dialer._start_next_call(table, connect, "c1")
        place.assert_not_called()

    def test_cancelled_campaign_ignores_late_scheduler_event(self):
        with mock.patch.object(dialer, "_set_campaign_running", return_value=False), \
             mock.patch.object(dialer, "_query_patients") as query, \
             mock.patch.object(dialer, "_place_call") as place:
            dialer._start_next_call(object(), object(), "c1")
        query.assert_not_called()
        place.assert_not_called()

    def test_duplicate_disconnected_event_is_idempotent(self):
        patient={"campaignId":"c1","recordKey":"PATIENT#1#p1","patientId":"p1","contactId":"contact-1"}
        table=ConditionalTable(fail=True)
        self.assertFalse(dialer._finalize_patient(table, patient, {"Attributes":{"identityResult":"Confirmed"}}))

    def test_start_outbound_failure_marks_failed_and_advances(self):
        patient={"campaignId":"c1","recordKey":"PATIENT#1#p1","patientId":"p1","phoneNumber":"+18148316822","customerName":"John"}
        with mock.patch.object(dialer, "_set_campaign_running", return_value=True), \
             mock.patch.object(dialer, "_query_patients", side_effect=[[], [patient], []]), \
             mock.patch.object(dialer, "_claim_patient", return_value=True), \
             mock.patch.object(dialer, "_place_call", side_effect=ClientError({"Error":{"Code":"InvalidParameterException","Message":"bad"}}, "StartOutboundVoiceContact")), \
             mock.patch.object(dialer, "_mark_setup_failed") as failed, \
             mock.patch.object(dialer, "_mark_campaign_completed_if_done"):
            dialer._start_next_call(object(), object(), "c1")
        failed.assert_called_once()

    def test_contact_lookup_uses_gsi_not_scan(self):
        class Table:
            def __init__(self): self.kw=None
            def query(self, **kwargs): self.kw=kwargs; return {"Items":[{"patientId":"p1"}]}
        t=Table(); result=dialer._lookup_by_contact(t,"contact-1")
        self.assertEqual(result["patientId"], "p1")
        self.assertEqual(t.kw["IndexName"], "contactId-index")

    def test_campaign_completion_when_no_pending_or_in_progress(self):
        table=ConditionalTable()
        with mock.patch.object(dialer, "_query_patients", return_value=[{"status":"COMPLETED"},{"status":"CALL_SETUP_FAILED"}]):
            self.assertTrue(dialer._mark_campaign_completed_if_done(table,"c1"))
        self.assertEqual(table.calls[0]["ExpressionAttributeValues"][":completed"], "COMPLETED")

    def test_disconnect_event_ignores_other_instance(self):
        event={"source":"aws.connect","detail":{"eventType":"DISCONNECTED","contactId":"c","instanceArn":"arn:aws:connect:us-east-1:1:instance/other"}}
        self.assertIsNone(dialer._extract_disconnect(event))

    def test_frontend_local_time_is_converted_using_iana_timezone(self):
        local, utc = api._normalize_local_schedule("2030-08-25T10:00:00", "America/New_York")
        self.assertIn("-04:00", local)
        self.assertTrue(utc.endswith("Z"))
        self.assertIn("14:00:00", utc)

    def test_api_route_contract_is_present(self):
        text = (ROOT / "lambda" / "campaign_api.py").read_text(encoding="utf-8")
        for route in ("/uploads", "/campaigns", "cancel", "reschedule", "patients"):
            self.assertIn(route, text)


if __name__ == "__main__": unittest.main()


class CampaignBoto3DeploymentTests(unittest.TestCase):
    def test_campaign_deployer_replaces_cdk(self):
        text = (ROOT / "cara_health_bot" / "campaign_deployer.py").read_text(encoding="utf-8")
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        deploy_script = (ROOT / "deploy-campaign.sh").read_text(encoding="utf-8")
        self.assertNotIn("aws_cdk", text)
        self.assertNotIn("aws-cdk-lib", requirements)
        self.assertNotIn("cdk deploy", deploy_script)
        self.assertIn("python scripts/deploy_campaign.py", deploy_script)

    def test_campaign_deployer_has_required_resources_and_triggers(self):
        text = (ROOT / "cara_health_bot" / "campaign_deployer.py").read_text(encoding="utf-8")
        for required in (
            "cara-health-bot-campaign-state",
            "contactId-index",
            "cara-health-bot-campaign-intake",
            "cara-health-bot-campaign-dialer",
            "cara-health-bot-campaign-api",
            "put_bucket_notification_configuration",
            "patients.csv",
            "AWS_IAM",
            "put_rule",
            "put_targets",
            "DISCONNECTED",
            "Connect Customer Contact Event",
        ):
            self.assertIn(required, text)

    def test_start_outbound_voice_contact_policy_is_unscoped_as_required_by_aws(self):
        text = (ROOT / "cara_health_bot" / "campaign_deployer.py").read_text(encoding="utf-8")
        self.assertIn('"connect:StartOutboundVoiceContact"], "Resource": "*"', text)
        self.assertNotIn('"connect:InstanceId"', text)

    def test_campaign_deployer_reuses_base_state(self):
        text = (ROOT / "cara_health_bot" / "campaign_deployer.py").read_text(encoding="utf-8")
        for key in ("InstanceId", "InstanceArn", "ContactFlowId", "SourcePhoneNumber"):
            self.assertIn(key, text)
        self.assertIn("deployment-state.json", text)
        self.assertIn("current credentials", text)

class CampaignCallbackSchedulingTests(unittest.TestCase):
    def test_patient_callback_parser_handles_tomorrow_at_10(self):
        now = __import__('datetime').datetime(2026, 8, 24, 12, 39, tzinfo=__import__('datetime').timezone(__import__('datetime').timedelta(hours=-4)))
        parsed = dialer._parse_callback_when('call me tomorrow at 10 AM', 'America/New_York', now)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.isoformat(), '2026-08-25T10:00:00-04:00')

    def test_patient_callback_parser_handles_spoken_ten_am(self):
        now = __import__('datetime').datetime(
            2026, 8, 24, 13, 24,
            tzinfo=__import__('datetime').timezone(
                __import__('datetime').timedelta(hours=-4)
            )
        )
        parsed = dialer._parse_callback_when(
            "tomorrow at ten a.m.",
            "America/New_York",
            now,
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(
            parsed.isoformat(),
            "2026-08-25T10:00:00-04:00",
        )

    def test_patient_callback_parser_does_not_invent_daypart_time(self):
        now = __import__('datetime').datetime(2026, 8, 24, 12, 39, tzinfo=__import__('datetime').timezone(__import__('datetime').timedelta(hours=-4)))
        self.assertIsNone(dialer._parse_callback_when('tomorrow afternoon', 'America/New_York', now))

    def test_confirmed_patient_callback_plan(self):
        contact = {'Attributes': {
            'identityResult': 'Confirmed',
            'identityConfirmed': 'true',
            'conversationState': 'CALLBACK',
            'callbackWhen': 'tomorrow at 10 AM',
            'callbackReason': 'busy',
        }}
        with mock.patch.object(dialer, '_now_dt', return_value=__import__('datetime').datetime(2026, 8, 24, 16, 39, tzinfo=__import__('datetime').timezone.utc)):
            plan = dialer._callback_plan(contact, {'timezone': 'America/New_York'})
        self.assertEqual(plan['requestedBy'], 'PATIENT')
        self.assertEqual(plan['disposition'], 'Callback Requested')
        self.assertEqual(plan['callbackAt'].isoformat(), '2026-08-25T10:00:00-04:00')

    def test_third_party_callback_plan_uses_lex_slots(self):
        contact = {'Attributes': {
            'identityResult': 'Denied',
            'recipientType': 'THIRD_PARTY',
            'targetAvailableNow': 'false',
            'callbackDate': '2026-08-25',
            'callbackTime': '10:00',
        }}
        with mock.patch.object(dialer, '_now_dt', return_value=__import__('datetime').datetime(2026, 8, 24, 16, 39, tzinfo=__import__('datetime').timezone.utc)):
            plan = dialer._callback_plan(contact, {'timezone': 'America/New_York'})
        self.assertEqual(plan['requestedBy'], 'THIRD_PARTY')
        self.assertEqual(plan['disposition'], 'Third Party - Callback Requested')
        self.assertEqual(plan['callbackAt'].isoformat(), '2026-08-25T10:00:00-04:00')

    def test_callback_scheduled_patient_keeps_campaign_open(self):
        table = ConditionalTable()
        with mock.patch.object(dialer, '_query_patients', return_value=[{'status': 'CALLBACK_SCHEDULED'}]):
            self.assertFalse(dialer._mark_campaign_completed_if_done(table, 'c1'))
        self.assertEqual(table.calls, [])
