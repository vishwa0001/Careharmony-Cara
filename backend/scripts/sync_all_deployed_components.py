#!/usr/bin/env python3
import io
import json
import os
import sys
import zipfile
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cara_health_bot.config import load_config
from cara_health_bot.builders import render_contact_flow, q_prompt_update_request, q_agent_update_request, q_agent_configuration

def main():
    cfg = load_config()
    session = boto3.Session(profile_name=os.environ.get("AWS_PROFILE", "careharmony"), region_name=cfg.region)
    lambda_client = session.client("lambda")
    connect_client = session.client("connect")
    qconnect_client = session.client("qconnect")
    sts_client = session.client("sts")

    account_id = sts_client.get_caller_identity()["Account"]
    print(f"Deploying to account {account_id}, region {cfg.region}...")

    # 1. Update session-context Lambda
    print("\n1. Updating cara-health-bot-session-context Lambda...")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        code_path = ROOT / "lambda" / "session_context.py"
        zf.write(code_path, arcname="session_context.py")
    buf.seek(0)
    lambda_client.update_function_code(
        FunctionName="cara-health-bot-session-context",
        ZipFile=buf.read(),
        Publish=True
    )
    print("   -> cara-health-bot-session-context code updated successfully.")

    # 2. Retrieve deployed resource IDs
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
    connect_instance_arn = res["connectInstanceArn"]

    # 3. Update Contact Flow Content
    print("\n2. Updating Amazon Connect contact flow...")
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
    connect_client.update_contact_flow_content(
        InstanceId=instance_id,
        ContactFlowId=flow_id,
        Content=rendered_flow
    )
    print(f"   -> Contact flow {flow_id} updated and published.")

    # 4. Update Q in Connect Prompt and AI Agent
    print("\n3. Updating Q in Connect prompt & agent...")
    prompt_id = res["aiPromptId"]
    prompt_content = cfg.prompt_path.read_text(encoding="utf-8")
    prompt_req = q_prompt_update_request(cfg, assistant_id, prompt_id, prompt_content)
    update_res = qconnect_client.update_ai_prompt(**prompt_req)
    version_res = qconnect_client.create_ai_prompt_version(
        assistantId=assistant_id,
        aiPromptId=prompt_id
    )
    prompt_version = version_res.get("versionNumber", 1)
    print(f"   -> AI Prompt updated. New version: {prompt_version}")

    agent_id = res["aiAgentId"]
    # Update AI Agent with new prompt version
    agent_req = q_agent_update_request(cfg, assistant_id, connect_instance_arn, agent_id, f"{prompt_id}:{prompt_version}")
    qconnect_client.update_ai_agent(**agent_req)
    agent_ver_res = qconnect_client.create_ai_agent_version(
        assistantId=assistant_id,
        aiAgentId=agent_id
    )
    agent_version = agent_ver_res.get("versionNumber", 1)
    print(f"   -> AI Agent updated with new prompt version. Agent version: {agent_version}")

    # Point assistant's Connect.SelfService orchestrator to the new agent version
    qconnect_client.update_assistant_ai_agent(
        assistantId=assistant_id,
        aiAgentType="ORCHESTRATION",
        orchestratorUseCase="Connect.SelfService",
        configuration={"aiAgentId": f"{agent_id}:{agent_version}"},
    )
    print(f"   -> Assistant Connect.SelfService orchestrator updated to agent version {agent_version}")

    print("\nAll components successfully synced to AWS!")

if __name__ == "__main__":
    main()
