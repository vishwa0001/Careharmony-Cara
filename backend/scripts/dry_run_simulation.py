import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
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
from utils.agent_availability import check_agent_availability


def run_dry_run():
    print("================================================================")
    print("  CARA DIRECT AGENT & CALL FLOW — DRY RUN VERIFICATION")
    print("================================================================\n")

    # Step 1: Ingestion validation with 3 test rows
    print("[STEP 1] Ingesting test CSV with 3 test cases...")
    test_csv = (
        "empi,first_name,last_name,gender,phone_number,practice_name,practice_callback_number,direct_agent\n"
        "PT001,John,Doe,Male,+18145551001,Mercy Health,+18005550100,yes\n"
        "PT002,Jane,Smith,Female,+18145551002,Mercy Health,+18005550100,yes\n"
        "PT003,Alex,Taylor,Non-Binary,+18145551003,Mercy Health,+18005550100,no\n"
    )

    mock_s3 = MagicMock()
    mock_s3.get_object.return_value = {"Body": io.BytesIO(test_csv.encode("utf-8"))}

    patients = campaign_intake._load_patients(mock_s3, "test-bucket", "test-batch-001")
    print(f"  Successfully parsed {len(patients)} patient records from CSV:")
    for p in patients:
        print(f"    - {p['patientId']}: {p['customerName']} | direct_agent={p['direct_agent']} | initial callMode={p['callMode']}")

    print("\n[STEP 2] Simulating Call Placement for each test case...\n")
    mock_patients_table = MagicMock()
    mock_connect = MagicMock()
    mock_connect.start_outbound_voice_contact.return_value = {"ContactId": "mock-contact-id-12345"}

    # Case 1: direct_agent=yes, Agent Available
    print("  --- CASE 1: direct_agent='yes' AND Agent IS Available ---")
    with patch("campaign_dialer._check_agent_availability", return_value={"available": True, "agentPhone": "+15822671755", "checkedAt": "2026-08-31T14:00:00Z"}), \
         patch("campaign_dialer.check_agent_availability", return_value=True):
        contact_id = campaign_dialer._place_call(mock_patients_table, mock_connect, patients[0], "test-batch-001")
        call_args = mock_connect.start_outbound_voice_contact.call_args[1]
        attrs = call_args["Attributes"]
        print(f"    Placed ContactId: {contact_id}")
        print(f"    callMode: {attrs.get('callMode')}")
        print(f"    humanAgentPhoneNumber: {attrs.get('humanAgentPhoneNumber')}")
        print(f"    direct_agent: {attrs.get('direct_agent')}")
        assert attrs.get("callMode") == "DIRECT_HUMAN_HANDOFF", "Expected DIRECT_HUMAN_HANDOFF"
        assert attrs.get("humanAgentPhoneNumber") == "+15822671755"
        print("    --> PASS: Direct transfer initiated directly to human agent.")

    # Case 2: direct_agent=yes, Agent UNAVAILABLE (Fail-safe Fallback)
    print("\n  --- CASE 2: direct_agent='yes' AND Agent IS NOT Available (Fail-safe Fallback) ---")
    mock_connect.reset_mock()
    with patch("campaign_dialer._check_agent_availability", return_value={"available": False, "agentPhone": None, "checkedAt": "2026-08-31T14:00:00Z"}), \
         patch("campaign_dialer.check_agent_availability", return_value=False):
        contact_id = campaign_dialer._place_call(mock_patients_table, mock_connect, patients[1], "test-batch-001")
        call_args = mock_connect.start_outbound_voice_contact.call_args[1]
        attrs = call_args["Attributes"]
        print(f"    Placed ContactId: {contact_id}")
        print(f"    callMode: {attrs.get('callMode')}")
        print(f"    direct_agent: {attrs.get('direct_agent')}")
        print(f"    coachingGreeting: {attrs.get('coachingGreeting')}")
        assert attrs.get("callMode") == "NORMAL", "Expected fallback to NORMAL"
        assert "Please hold while I connect you now" in attrs.get("coachingGreeting")
        print("    --> PASS: Fail-safe activated! Fell back to Normal Cara Flow with fast-path greeting.")

    # Case 3: direct_agent=no, Normal Cara Flow
    print("\n  --- CASE 3: direct_agent='no' (Normal Cara Flow) ---")
    mock_connect.reset_mock()
    contact_id = campaign_dialer._place_call(mock_patients_table, mock_connect, patients[2], "test-batch-001")
    call_args = mock_connect.start_outbound_voice_contact.call_args[1]
    attrs = call_args["Attributes"]
    print(f"    Placed ContactId: {contact_id}")
    print(f"    callMode: {attrs.get('callMode')}")
    print(f"    direct_agent: {attrs.get('direct_agent')}")
    print(f"    coachingGreeting: {attrs.get('coachingGreeting')}")
    assert attrs.get("callMode") == "NORMAL"
    assert "Please hold while I connect you now" in attrs.get("coachingGreeting")
    print("    --> PASS: Normal Cara Flow initiated with fast-path greeting.")

    print("\n[STEP 3] Testing Disconnect & DynamoDB Status Finalizations...\n")

    # Finalization A: Successful Transfer -> COMPLETED
    print("  --- Finalization A: Successful Transfer ---")
    mock_table = MagicMock()
    patient = {"patientId": "PT001", "batchId": "test-batch-001", "contactId": "c-1"}
    contact = {"ContactId": "c-1", "Attributes": {"conversationState": "TRANSFER_COMPLETED"}}
    res = campaign_dialer._finalize_patient(mock_table, patient, contact)
    update_item = mock_table.update_item.call_args[1]
    print(f"    Status written: {update_item['ExpressionAttributeValues'][':completed']}")
    assert update_item['ExpressionAttributeValues'][':completed'] == "COMPLETED"
    print("    --> PASS: Status is COMPLETED")

    # Finalization B: Declined / Not Interested -> NOT_INTERESTED
    print("\n  --- Finalization B: Patient Declines / Refuses ---")
    mock_table = MagicMock()
    patient = {"patientId": "PT002", "batchId": "test-batch-001", "contactId": "c-2"}
    contact = {"ContactId": "c-2", "Attributes": {"caraEndReason": "refusal", "conversationState": "NOT_INTERESTED"}}
    res = campaign_dialer._finalize_patient(mock_table, patient, contact)
    update_item = mock_table.update_item.call_args[1]
    print(f"    Status written: {update_item['ExpressionAttributeValues'][':status']}")
    assert update_item['ExpressionAttributeValues'][':status'] == "NOT_INTERESTED"
    print("    --> PASS: Status is NOT_INTERESTED")

    # Finalization C: Callback with Unspecified Time -> CALLBACK_UNSPECIFIED
    print("\n  --- Finalization C: Agent Unavailable / Unspecified Callback ---")
    mock_table = MagicMock()
    patient = {"patientId": "PT003", "batchId": "test-batch-001", "contactId": "c-3"}
    plan = {"requestedBy": "PATIENT", "callbackWhen": "", "callbackReason": "Agent unavailable — unspecified callback."}
    res = campaign_dialer._finalize_callback_without_schedule(mock_table, patient, plan, {})
    update_item = mock_table.update_item.call_args[1]
    print(f"    Status written: {update_item['ExpressionAttributeValues'][':status']}")
    assert update_item['ExpressionAttributeValues'][':status'] == "CALLBACK_UNSPECIFIED"
    print("    --> PASS: Status is CALLBACK_UNSPECIFIED")

    # Finalization D: Setup Error -> FAILED
    print("\n  --- Finalization D: Call Setup Error ---")
    mock_table = MagicMock()
    patient = {"patientId": "PT004", "batchId": "test-batch-001"}
    campaign_dialer._mark_setup_failed(mock_table, patient, reason="Connect rate exceeded")
    update_item = mock_table.update_item.call_args[1]
    print(f"    Status written: {update_item['ExpressionAttributeValues'][':failed']}")
    print(f"    Failure reason: {update_item['ExpressionAttributeValues'][':reason']}")
    assert update_item['ExpressionAttributeValues'][':failed'] == "FAILED"
    print("    --> PASS: Status is FAILED")

    print("\n================================================================")
    print("  ALL DRY RUN CHECKS PASSED SUCCESSFULLY!")
    print("================================================================\n")


if __name__ == "__main__":
    run_dry_run()
