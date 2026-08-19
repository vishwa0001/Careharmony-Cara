#!/usr/bin/env python3
"""Best-effort cleanup for resources named/recorded by Cara Health Bot.

The Connect instance is deleted last. This is intentionally opt-in via cleanup.sh.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cara_health_bot.config import load_config
from cara_health_bot.deployer import format_aws_error



def ignore_not_found(call, *args, **kwargs):
    try:
        return call(*args, **kwargs)
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") in {"ResourceNotFoundException", "NoSuchEntity"}:
            return None
        print("Warning:", format_aws_error(error), file=sys.stderr)
        return None


def main() -> int:
    cfg = load_config()
    path = ROOT / "deployment-state.json"
    if not path.is_file():
        print("No deployment-state.json; nothing to clean.")
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    r = data.get("resources", {})
    region = data.get("outputs", {}).get("Region", cfg.region)
    q = boto3.client("qconnect", region_name=region)
    lex = boto3.client("lexv2-models", region_name=region)
    iam = boto3.client("iam", region_name=region)
    connect = boto3.client("connect", region_name=region)
    lambda_client = boto3.client("lambda", region_name=region)
    logs = boto3.client("logs", region_name=region)
    s3 = boto3.client("s3", region_name=region)

    if r.get("sessionContextLambdaArn") and r.get("connectInstanceId"):
        ignore_not_found(
            connect.disassociate_lambda_function,
            InstanceId=r["connectInstanceId"],
            FunctionArn=r["sessionContextLambdaArn"],
            ClientToken=str(__import__("uuid").uuid4()),
        )
    if r.get("sessionContextLambdaName"):
        ignore_not_found(
            lambda_client.delete_function, FunctionName=r["sessionContextLambdaName"]
        )
        print("Requested session-context Lambda deletion")
    if r.get("sessionContextLambdaRoleName"):
        ignore_not_found(
            iam.delete_role_policy,
            RoleName=r["sessionContextLambdaRoleName"],
            PolicyName=cfg.session_context_lambda_policy_name,
        )
        ignore_not_found(iam.delete_role, RoleName=r["sessionContextLambdaRoleName"])
        print("Requested session-context Lambda role deletion")

    if r.get("availabilityBotId"):
        ignore_not_found(lex.delete_bot, botId=r["availabilityBotId"], skipResourceInUseCheck=True)
        print("Requested availability Lex bot deletion")
    if r.get("identityBotId"):
        ignore_not_found(lex.delete_bot, botId=r["identityBotId"], skipResourceInUseCheck=True)
        print("Requested identity Lex bot deletion")
    if r.get("identityLexRuntimeRoleName"):
        ignore_not_found(
            iam.delete_role_policy,
            RoleName=r["identityLexRuntimeRoleName"],
            PolicyName=cfg.identity_lex_runtime_policy_name,
        )
        ignore_not_found(iam.delete_role, RoleName=r["identityLexRuntimeRoleName"])
        print("Requested identity Lex role deletion")
    if r.get("botId"):
        ignore_not_found(lex.delete_bot, botId=r["botId"], skipResourceInUseCheck=True)
        print("Requested coaching Lex bot deletion")
    if r.get("lexRuntimeRoleName"):
        ignore_not_found(iam.delete_role_policy, RoleName=r["lexRuntimeRoleName"], PolicyName=cfg.lex_runtime_policy_name)
        ignore_not_found(iam.delete_role, RoleName=r["lexRuntimeRoleName"])
        print("Requested Lex role deletion")
    if r.get("lexConversationLogGroup"):
        ignore_not_found(logs.delete_log_group, logGroupName=r["lexConversationLogGroup"])
        print("Requested Lex conversation log-group deletion")
    if r.get("assistantId") and r.get("aiAgentId"):
        ignore_not_found(
            q.remove_assistant_ai_agent,
            assistantId=r["assistantId"],
            aiAgentType="ORCHESTRATION",
            orchestratorUseCase="Connect.SelfService",
        )
        print("Requested Q self-service orchestrator unbinding")

    if r.get("assistantIntegrationId") and r.get("connectInstanceId"):
        ignore_not_found(
            connect.delete_integration_association,
            InstanceId=r["connectInstanceId"],
            IntegrationAssociationId=r["assistantIntegrationId"],
        )
        print("Requested Connect/Q assistant integration deletion")

    if r.get("assistantId") and r.get("aiAgentId"):
        ignore_not_found(q.delete_ai_agent, assistantId=r["assistantId"], aiAgentId=r["aiAgentId"])
        print("Requested Q AI agent deletion")
    if r.get("assistantId") and r.get("aiPromptId"):
        ignore_not_found(q.delete_ai_prompt, assistantId=r["assistantId"], aiPromptId=r["aiPromptId"])
        print("Requested Q prompt deletion")
    if r.get("phoneNumberId"):
        ignore_not_found(connect.release_phone_number, PhoneNumberId=r["phoneNumberId"])
        print("Requested phone-number release")
    if r.get("connectInstanceId"):
        ignore_not_found(connect.delete_instance, InstanceId=r["connectInstanceId"], ClientToken=str(__import__('uuid').uuid4()))
        print("Requested Connect instance deletion")
    if r.get("assistantId"):
        ignore_not_found(q.delete_assistant, assistantId=r["assistantId"])
        print("Requested dedicated Q assistant deletion")

    bucket = r.get("recordingBucket")
    if bucket:
        try:
            while True:
                response = s3.list_object_versions(Bucket=bucket, MaxKeys=1000)
                objects = [
                    {"Key": item["Key"], "VersionId": item["VersionId"]}
                    for item in response.get("Versions", []) + response.get("DeleteMarkers", [])
                ]
                if not objects:
                    break
                s3.delete_objects(Bucket=bucket, Delete={"Objects": objects, "Quiet": True})
            while True:
                response = s3.list_objects_v2(Bucket=bucket, MaxKeys=1000)
                objects = [{"Key": item["Key"]} for item in response.get("Contents", [])]
                if not objects:
                    break
                s3.delete_objects(Bucket=bucket, Delete={"Objects": objects, "Quiet": True})
            s3.delete_bucket(Bucket=bucket)
            print(f"Deleted recording bucket s3://{bucket}")
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") not in {"NoSuchBucket", "404"}:
                print("Warning:", format_aws_error(error), file=sys.stderr)
    try:
        path.unlink()
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
