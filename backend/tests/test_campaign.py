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
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lambda"))


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
            "BATCHES_TABLE_NAME": "TalkingBotCallBatches-dev",
            "PATIENTS_TABLE_NAME": "TalkingBotPatientRecords-dev",
            "CONNECT_INSTANCE_ID": "instance-1",
            "CONNECT_CONTACT_FLOW_ID": "flow-1",
            "CONNECT_SOURCE_PHONE_NUMBER": "+18775550100",
            "AWS_LAMBDA_FUNCTION_NAME": "cara-health-bot-campaign-dialer",
            "AWS_DEFAULT_REGION": "us-east-1",
        }, clear=False)
        self.env.start()
    def tearDown(self): self.env.stop()

    def test_valid_campaign_csv(self):
        csv_data = b"empi,first_name,last_name,gender,phone_number,practice_name,practice_callback_number\nP1,John,Doe,M,+18148316822,North Clinic,+18145550100\n"
        patients = intake._load_patients(FakeS3({"campaigns/c1/patients.csv": csv_data}), "bucket", "c1")
        self.assertEqual(patients[0]["patientId"], "P1")
        self.assertEqual(patients[0]["customerName"], "John Doe")
        self.assertEqual(patients[0]["practiceName"], "North Clinic")
        self.assertEqual(patients[0]["providerName"], "")

    def test_valid_campaign_csv_with_provider(self):
        csv_data = b"empi,first_name,last_name,gender,phone_number,practice_name,practice_callback_number,provider_name\nP1,John,Doe,M,+18148316822,North Clinic,+18145550100,Dr. Gregory House\n"
        patients = intake._load_patients(FakeS3({"campaigns/c1/patients.csv": csv_data}), "bucket", "c1")
        self.assertEqual(patients[0]["patientId"], "P1")
        self.assertEqual(patients[0]["customerName"], "John Doe")
        self.assertEqual(patients[0]["practiceName"], "North Clinic")
        self.assertEqual(patients[0]["providerName"], "Dr. Gregory House")

    def test_empty_campaign_rejected(self):
        csv_data = b"empi,first_name,last_name,gender,phone_number,practice_name,practice_callback_number\n"
        with self.assertRaisesRegex(ValueError, "no data rows"):
            intake._load_patients(FakeS3({"campaigns/c1/patients.csv": csv_data}), "bucket", "c1")

    def test_campaign_start_schedule_requires_timezone(self):
        with self.assertRaises(ValueError): intake._schedule_expression_utc("2026-08-20T10:00:00")
        self.assertEqual(intake._schedule_expression_utc("2026-08-20T10:00:00-04:00"), "at(2026-08-20T14:00:00)")

    def test_atomic_patient_claim(self):
        patient={"batchId":"c1","patientId":"p1"}
        self.assertTrue(dialer._claim_patient(ConditionalTable(), patient))
        self.assertFalse(dialer._claim_patient(ConditionalTable(fail=True), patient))

    def test_successful_start_outbound_voice_contact(self):
        class Connect:
            def __init__(self): self.kw=None
            def start_outbound_voice_contact(self, **kwargs): self.kw=kwargs; return {"ContactId":"contact-1"}
        c=Connect(); patient={"patientId":"p1","empi":"p1","phoneNumber":"+18148316822","customerName":"John Doe","firstName":"John","lastName":"Doe","practiceName":"North Clinic","practiceCallbackNumber":"+18145550100"}
        self.assertEqual(dialer._place_call(None, c, patient, "c1"), "contact-1")
        self.assertEqual(c.kw["ContactFlowId"], "flow-1")
        self.assertEqual(c.kw["Attributes"]["campaignId"], "c1")
        self.assertEqual(c.kw["Attributes"]["patientId"], "p1")
        self.assertEqual(c.kw["Attributes"]["identityPrompt"], "Hi, this is Cara — I'm a virtual assistant calling from North Clinic. Am I able to speak with John Doe?")
        self.assertEqual(c.kw["Attributes"]["identityClarification"], "Hi, this is Cara — I'm a virtual assistant calling from North Clinic. Am I able to speak with John Doe?")

    def test_dialer_opening_line_with_provider(self):
        class Connect:
            def __init__(self): self.kw=None
            def start_outbound_voice_contact(self, **kwargs): self.kw=kwargs; return {"ContactId":"contact-1"}
        c=Connect(); patient={"patientId":"p1","empi":"p1","phoneNumber":"+18148316822","customerName":"John Doe","firstName":"John","lastName":"Doe","practiceName":"North Clinic","providerName":"Dr. Smith","practiceCallbackNumber":"+18145550100"}
        self.assertEqual(dialer._place_call(None, c, patient, "c1"), "contact-1")
        self.assertEqual(c.kw["Attributes"]["providerName"], "Dr. Smith")
        self.assertEqual(c.kw["Attributes"]["identityPrompt"], "Hi, this is Cara — I'm a virtual assistant calling on behalf of Dr. Smith from North Clinic. Am I able to speak with John Doe?")
        self.assertEqual(c.kw["Attributes"]["identityClarification"], "Hi, this is Cara — I'm a virtual assistant calling on behalf of Dr. Smith from North Clinic. Am I able to speak with John Doe?")

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
            dialer._start_next_call(table, table, connect, "c1")
        place.assert_not_called()

    def test_cancelled_campaign_ignores_late_scheduler_event(self):
        with mock.patch.object(dialer, "_set_campaign_running", return_value=False), \
             mock.patch.object(dialer, "_query_patients") as query, \
             mock.patch.object(dialer, "_place_call") as place:
            dialer._start_next_call(object(), object(), object(), "c1")
        query.assert_not_called()
        place.assert_not_called()

    def test_duplicate_disconnected_event_is_idempotent(self):
        patient={"batchId":"c1","patientId":"p1","contactId":"contact-1"}
        table=ConditionalTable(fail=True)
        self.assertFalse(dialer._finalize_patient(table, patient, {"Attributes":{"identityResult":"Confirmed"}}))

    def test_start_outbound_failure_marks_failed_and_advances(self):
        patient={"batchId":"c1","patientId":"p1","phoneNumber":"+18148316822","customerName":"John"}
        with mock.patch.object(dialer, "_set_campaign_running", return_value=True), \
             mock.patch.object(dialer, "_query_patients", side_effect=[[], [patient], []]), \
             mock.patch.object(dialer, "_claim_patient", return_value=True), \
             mock.patch.object(dialer, "_place_call", side_effect=ClientError({"Error":{"Code":"InvalidParameterException","Message":"bad"}}, "StartOutboundVoiceContact")), \
             mock.patch.object(dialer, "_mark_setup_failed") as failed, \
             mock.patch.object(dialer, "_mark_campaign_completed_if_done"):
            dialer._start_next_call(object(), object(), object(), "c1")
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
            self.assertTrue(dialer._mark_campaign_completed_if_done(table, table, "c1"))
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
            "TalkingBotCallBatches-dev",
            "TalkingBotPatientRecords-dev",
            "StatusSlotIndex",
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
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {
            "BATCHES_TABLE_NAME": "TalkingBotCallBatches-dev",
            "PATIENTS_TABLE_NAME": "TalkingBotPatientRecords-dev",
            "CONNECT_INSTANCE_ID": "instance-1",
            "CONNECT_CONTACT_FLOW_ID": "flow-1",
            "CONNECT_SOURCE_PHONE_NUMBER": "+18775550100",
            "AWS_LAMBDA_FUNCTION_NAME": "cara-health-bot-campaign-dialer",
            "AWS_DEFAULT_REGION": "us-east-1",
            "AWS_REGION": "us-east-1",
        }, clear=False)
        self.env.start()

    def tearDown(self):
        self.env.stop()

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
            self.assertFalse(dialer._mark_campaign_completed_if_done(table, table, 'c1'))
        self.assertEqual(table.calls, [])

    def test_start_callback_call_places_outbound_contact_successfully(self):
        class Connect:
            def __init__(self): self.kw = None
            def start_outbound_voice_contact(self, **kwargs):
                self.kw = kwargs
                return {"ContactId": "cb-contact-123"}

        class FakePatientsTable:
            def __init__(self, item):
                self.item = item
                self.calls = []
            def get_item(self, Key):
                return {"Item": self.item}
            def update_item(self, **kwargs):
                self.calls.append(kwargs)
                return {}

        class FakeBatchesTable:
            def get_item(self, Key):
                return {"Item": {"batchId": "camp-1", "status": "RUNNING", "timezone": "America/New_York"}}
            def update_item(self, **kwargs):
                return {}

        patient = {
            "patientId": "p1",
            "batchId": "camp-1",
            "phoneNumber": "+18148316822",
            "customerName": "Kevin Peterson",
            "firstName": "Kevin",
            "lastName": "Peterson",
            "status": "CALLBACK_SCHEDULED",
            "practiceName": "Sample Practice",
            "practiceCallbackNumber": "+15555550100",
        }
        patients_table = FakePatientsTable(patient)
        batches_table = FakeBatchesTable()
        connect = Connect()

        with mock.patch.object(dialer, "_query_patients", return_value=[]):
            dialer._start_callback_call(batches_table, patients_table, connect, "camp-1", "p1")

        self.assertIsNotNone(connect.kw)
        self.assertEqual(connect.kw["DestinationPhoneNumber"], "+18148316822")
        self.assertEqual(connect.kw["Attributes"]["campaignId"], "camp-1")
        self.assertEqual(connect.kw["Attributes"]["patientId"], "p1")
        self.assertEqual(connect.kw["Attributes"]["customerName"], "Kevin Peterson")

    def test_handler_patient_callback_event(self):
        class Connect:
            def __init__(self): self.kw = None
            def start_outbound_voice_contact(self, **kwargs):
                self.kw = kwargs
                return {"ContactId": "cb-contact-456"}

        patient = {
            "patientId": "p1",
            "batchId": "camp-1",
            "phoneNumber": "+18148316822",
            "customerName": "Kevin Peterson",
            "firstName": "Kevin",
            "lastName": "Peterson",
            "status": "CALLBACK_SCHEDULED",
            "practiceName": "Sample Practice",
            "practiceCallbackNumber": "+15555550100",
        }
        mock_patients_table = mock.MagicMock()
        mock_patients_table.get_item.return_value = {"Item": patient}
        mock_batches_table = mock.MagicMock()
        mock_batches_table.get_item.return_value = {"Item": {"batchId": "camp-1", "status": "RUNNING"}}

        connect = Connect()

        with mock.patch.object(dialer, "_batches_table", return_value=mock_batches_table), \
             mock.patch.object(dialer, "_patients_table", return_value=mock_patients_table), \
             mock.patch.object(dialer, "_query_patients", return_value=[]), \
             mock.patch("boto3.client", return_value=connect):
            resp = dialer.handler({"trigger": "patient-callback", "campaignId": "camp-1", "recordKey": "p1"}, None)

        self.assertEqual(resp, {"handled": "patient-callback", "campaignId": "camp-1", "recordKey": "p1"})
        self.assertIsNotNone(connect.kw)
        self.assertEqual(connect.kw["DestinationPhoneNumber"], "+18148316822")

    def test_export_campaign_csv_all_records(self):
        campaign = {"campaignId": "camp-1", "fileName": "customers_2026_08_29.csv"}
        patients = [
            {
                "campaignId": "camp-1",
                "patientId": "TESTPT-0001",
                "empi": "TESTPT-0001",
                "contactId": "call-123",
                "status": "COMPLETED",
                "disposition": "Identity Confirmed",
                "callStartDateTime": "2026-08-29T15:00:00Z",
                "callEndDateTime": "2026-08-29T15:05:30Z",
                "outboundCallPhoneNumber": "+18775230000",
                "callSummary": "Patient confirmed identity",
            },
            {
                "campaignId": "camp-1",
                "patientId": "TESTPT-0002",
                "empi": "TESTPT-0002",
                "contactId": "call-456",
                "status": "COMPLETED",
                "disposition": "Wrong Person",
                "callStartDateTime": "2026-08-29T15:10:00Z",
                "callEndDateTime": "2026-08-29T15:14:10Z",
                "outboundCallPhoneNumber": "+18775230000",
                "callSummary": "Wrong person answered",
            },
        ]
        with mock.patch.object(api, "_campaign", return_value=campaign), \
             mock.patch.object(api, "_patients", return_value=patients):
            event = {
                "rawPath": "/campaigns/camp-1/export",
                "httpMethod": "GET",
            }
            resp = api.handler(event, None)
            self.assertEqual(resp["statusCode"], 200)
            self.assertEqual(resp["headers"]["Content-Type"], "text/csv; charset=utf-8")
            self.assertIn('filename="customers_2026_08_29_export.csv"', resp["headers"]["Content-Disposition"])
            lines = resp["body"].strip().split("\n")
            self.assertEqual(len(lines), 3) # Header + 2 rows
            self.assertEqual(lines[0], "empi,call_id,call_start_datetime,call_end_datetime,disposition,call_summary,requested_callback_date_time,outbound_call_phone_number,call_type")
            self.assertIn("TESTPT-0001,call-123", lines[1])
            self.assertIn("TESTPT-0002,call-456", lines[2])

    def test_export_campaign_csv_multiple_call_attempts(self):
        campaign = {"campaignId": "camp-1", "fileName": "batch_multi.csv"}
        patient = {
            "campaignId": "camp-1",
            "patientId": "TESTPT-0001",
            "empi": "TESTPT-0001",
            "callAttempts": [
                {
                    "callId": "call-attempt-1",
                    "contactId": "call-attempt-1",
                    "callStartDateTime": "2026-08-29T10:00:00Z",
                    "callEndDateTime": "2026-08-29T10:02:00Z",
                    "disposition": "No Answer",
                    "outboundCallPhoneNumber": "+18775230000",
                },
                {
                    "callId": "call-attempt-2",
                    "contactId": "call-attempt-2",
                    "callStartDateTime": "2026-08-29T14:00:00Z",
                    "callEndDateTime": "2026-08-29T14:05:00Z",
                    "disposition": "Identity Confirmed",
                    "outboundCallPhoneNumber": "+18775230000",
                },
            ],
        }
        with mock.patch.object(api, "_campaign", return_value=campaign), \
             mock.patch.object(api, "_patients", return_value=[patient]):
            event = {
                "rawPath": "/campaigns/camp-1/export",
                "httpMethod": "GET",
            }
            resp = api.handler(event, None)
            self.assertEqual(resp["statusCode"], 200)
            lines = resp["body"].strip().split("\n")
            self.assertEqual(len(lines), 3) # Header + 2 attempts
            self.assertIn("call-attempt-1", lines[1])
            self.assertIn("call-attempt-2", lines[2])

    def test_export_campaign_csv_empty(self):
        campaign = {"campaignId": "camp-empty", "fileName": "empty_batch.csv"}
        with mock.patch.object(api, "_campaign", return_value=campaign), \
             mock.patch.object(api, "_patients", return_value=[]):
            event = {
                "rawPath": "/campaigns/camp-empty/export",
                "httpMethod": "GET",
            }
            resp = api.handler(event, None)
            self.assertEqual(resp["statusCode"], 200)
            lines = resp["body"].strip().split("\n")
            self.assertEqual(len(lines), 1)
            self.assertEqual(lines[0], "empi,call_id,call_start_datetime,call_end_datetime,disposition,call_summary,requested_callback_date_time,outbound_call_phone_number,call_type")

    def test_export_campaign_csv_not_found(self):
        with mock.patch.object(api, "_campaign", return_value=None):
            event = {
                "rawPath": "/campaigns/camp-999/export",
                "httpMethod": "GET",
            }
            resp = api.handler(event, None)
            self.assertEqual(resp["statusCode"], 404)

    def test_finalize_patient_not_interested(self):
        table = ConditionalTable()
        patient = {"patientId": "p-1", "batchId": "b-1", "contactId": "c-1"}
        contact = {
            "ContactId": "c-1",
            "Attributes": {"caraEndReason": "refusal", "conversationState": "NOT_INTERESTED"},
        }
        res = dialer._finalize_patient(table, patient, contact)
        self.assertTrue(res)
        self.assertEqual(len(table.calls), 1)
        update = table.calls[0]
        self.assertEqual(update["ExpressionAttributeValues"][":status"], "NOT_INTERESTED")

    def test_finalize_callback_unspecified(self):
        table = ConditionalTable()
        patient = {"patientId": "p-2", "batchId": "b-1", "contactId": "c-2"}
        plan = {"requestedBy": "PATIENT", "callbackWhen": "", "callbackReason": "Agent unavailable"}
        res = dialer._finalize_callback_without_schedule(table, patient, plan, {})
        self.assertTrue(res)
        self.assertEqual(len(table.calls), 1)
        update = table.calls[0]
        self.assertEqual(update["ExpressionAttributeValues"][":status"], "CALLBACK_UNSPECIFIED")

    def test_handle_disconnect_auto_reschedules_unspecified_callback_24h(self):
        import datetime as dt
        from zoneinfo import ZoneInfo
        batches_table = ConditionalTable()
        patients_table = ConditionalTable()
        patient = {
            "patientId": "p-unspec-1",
            "batchId": "camp-1",
            "contactId": "c-unspec-1",
            "status": "IN_PROGRESS",
            "callbackCount": 0,
        }
        patients_table.items = [patient]

        call_start = dt.datetime(2026, 8, 24, 14, 0, 0, tzinfo=dt.timezone.utc)
        contact = {
            "ContactId": "c-unspec-1",
            "InitiationTimestamp": call_start,
            "Attributes": {
                "identityResult": "Confirmed",
                "identityConfirmed": "true",
                "conversationState": "CALLBACK",
                "callbackWhen": "",
                "callbackReason": "",
            }
        }
        class Connect:
            def describe_contact(self, **kwargs):
                return {"Contact": contact}

        with mock.patch.object(dialer, "_lookup_by_contact", return_value=patient):
            with mock.patch.object(dialer, "_campaign", return_value={"batchId": "camp-1", "timezone": "America/New_York", "status": "RUNNING"}):
                with mock.patch.object(dialer, "_create_callback_schedule", return_value=("sched-auto-24h", "2026-08-25T14:00:00Z")) as mock_sched:
                    with mock.patch.object(dialer, "_start_next_call"):
                        dialer._handle_disconnect(batches_table, patients_table, Connect(), "c-unspec-1", "inst-1")

                        mock_sched.assert_called_once()
                        args = mock_sched.call_args[0]
                        self.assertEqual(args[0], "camp-1")
                        self.assertEqual(args[1], "p-unspec-1")
                        expected_cb = call_start.astimezone(ZoneInfo("America/New_York")) + dt.timedelta(hours=24)
                        self.assertEqual(args[2], expected_cb)

                        self.assertEqual(len(patients_table.calls), 1)
                        update = patients_table.calls[0]
                        vals = update["ExpressionAttributeValues"]
                        self.assertEqual(vals[":scheduled"], "CALLBACK_SCHEDULED")
                        self.assertEqual(vals[":disposition"], "Callback Requested - Auto-Rescheduled (24h)")
                        self.assertEqual(vals[":callbackAt"], expected_cb.isoformat())
                        self.assertEqual(vals[":callbackFor"], "2026-08-25T14:00:00Z")
                        self.assertEqual(vals[":scheduleName"], "sched-auto-24h")

    def test_mark_setup_failed(self):
        table = ConditionalTable()
        patient = {"patientId": "p-3", "batchId": "b-1"}
        dialer._mark_setup_failed(table, patient, reason="Connect API timeout")
        self.assertEqual(len(table.calls), 1)
        update = table.calls[0]
        self.assertEqual(update["ExpressionAttributeValues"][":failed"], "FAILED")
        self.assertEqual(update["ExpressionAttributeValues"][":reason"], "Connect API timeout")

    def test_agent_availability_utility_failsafe(self):
        from backend.utils.agent_availability import check_agent_availability
        with mock.patch("requests.get", side_effect=Exception("network down")):
            self.assertFalse(check_agent_availability())


