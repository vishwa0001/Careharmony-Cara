import json
import os
import sys
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cara_health_bot.config import load_config
from cara_health_bot.builders import render_contact_flow
from cara_health_bot.deployer import CaraHealthBotDeployer

def main():
    profile = os.environ.get("AWS_PROFILE", "careharmony-main")
    cfg = load_config()
    session = boto3.Session(profile_name=profile, region_name=cfg.region)
    sts = session.client("sts")
    identity = sts.get_caller_identity()
    print(f"Deploying with profile={profile}, account={identity['Account']}, region={cfg.region}")
    assert identity["Account"] == "176032258673", f"Expected account 176032258673, got {identity['Account']}"

    state_file = ROOT / "deployment-state.json"
    state = json.loads(state_file.read_text(encoding="utf-8"))
    res = state.get("resources") or state

    instance_id = res["connectInstanceId"]
    assistant_id = res["assistantId"]
    assistant_arn = res["assistantArn"]
    alias_arn = res["botAliasArn"]
    identity_alias_arn = res["identityBotAliasArn"]
    availability_alias_arn = res["availabilityBotAliasArn"]
    session_context_lambda_arn = res["sessionContextLambdaArn"]
    human_transfer_queue_arn = res["humanTransferQueueArn"]
    flow_id = res["contactFlowId"]

    print(f"Rendering contact flow content...")
    rendered_flow = render_contact_flow(
        cfg,
        assistant_id,
        assistant_arn,
        alias_arn,
        identity_alias_arn,
        availability_alias_arn,
        session_context_lambda_arn,
        human_transfer_queue_arn,
    )

    connect = session.client("connect")
    print(f"Updating contact flow content for instance {instance_id}, flow {flow_id}...")
    connect.update_contact_flow_content(
        InstanceId=instance_id,
        ContactFlowId=flow_id,
        Content=rendered_flow,
    )
    print("Contact flow content updated successfully.")

    # Verification via describe_contact_flow
    print("Verifying published contact flow...")
    described = connect.describe_contact_flow(
        InstanceId=instance_id,
        ContactFlowId=flow_id,
    )["ContactFlow"]
    print(f"Flow Name: {described.get('Name')}")
    print(f"Flow Status: {described.get('Status')}")
    print(f"Flow State: {described.get('State')}")
    assert described.get("Status") == "PUBLISHED", "Flow is not published!"

    flow_content = json.loads(described.get("Content", "{}"))
    actions = {a["Identifier"]: a for a in flow_content.get("Actions", [])}

    # Verify action e0000000-0000-4000-8000-000000000008 exists
    assert "e0000000-0000-4000-8000-000000000008" in actions, "Action 0008 not found in published flow!"
    act_0008 = actions["e0000000-0000-4000-8000-000000000008"]
    print("\n--- ACTION e0000000-0000-4000-8000-000000000008 ---")
    print(json.dumps(act_0008, indent=2))

    # Verify action e0000000-0000-4000-8000-000000000005 transitions to 0008
    act_0005 = actions["e0000000-0000-4000-8000-000000000005"]
    print("\n--- ACTION e0000000-0000-4000-8000-000000000005 TRANSITIONS ---")
    print(json.dumps(act_0005.get("Transitions"), indent=2))
    assert act_0005["Transitions"]["NextAction"] == "e0000000-0000-4000-8000-000000000008"

    # Also run the full deployer published flow verification
    deployer = CaraHealthBotDeployer(cfg, verbose=True)
    deployer.session = session
    deployer.account_id = identity["Account"]
    deployer.resources = res
    deployer.connect = connect
    deployer.sts = sts
    deployer.lex = session.client("lexv2-models")
    deployer.qconnect = session.client("qconnect")
    deployer.lambda_client = session.client("lambda")
    deployer.logs = session.client("logs")
    deployer.iam = session.client("iam")
    deployer.s3 = session.client("s3")
    deployer.verify()
    print("\nAll deployer published flow route assertions PASSED!")

if __name__ == "__main__":
    main()
