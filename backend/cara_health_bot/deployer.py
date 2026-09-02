from __future__ import annotations

import io
import json
import os
import re
import tempfile
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any, Callable, Iterable

import boto3
import yaml
from botocore.exceptions import BotoCoreError, ClientError

from .builders import (
    final_lex_trust_policy,
    initial_lex_trust_policy,
    standard_lex_trust_policy,
    lambda_trust_policy,
    lex_alias_request,
    lex_alias_resource_policy,
    lex_bot_create_request,
    lex_bot_update_request,
    lex_fallback_intent_request,
    lex_locale_request,
    lex_qinconnect_intent_request,
    lex_runtime_permissions,
    identity_lex_runtime_permissions,
    identity_lex_bot_create_request,
    identity_lex_bot_update_request,
    identity_lex_locale_request,
    identity_confirmed_intent_request,
    identity_named_confirmation_intent_request,
    identity_first_name_slot_request,
    identity_last_name_slot_request,
    identity_denied_intent_request,
    identity_ambiguous_intent_request,
    identity_fallback_intent_request,
    identity_lex_alias_request,
    third_party_detected_intent_request,
    patient_unavailable_intent_request,
    wrong_number_intent_request,
    representative_detected_intent_request,
    deceased_intent_request,
    call_refusal_intent_request,
    safety_medical_intent_request,
    safety_behavioral_intent_request,
    availability_lex_bot_create_request,
    availability_lex_bot_update_request,
    availability_lex_locale_request,
    availability_now_intent_request,
    availability_unavailable_intent_request,
    availability_unknown_intent_request,
    availability_representative_willing_intent_request,
    availability_fallback_intent_request,
    availability_callback_date_slot_request,
    availability_callback_time_slot_request,
    availability_lex_alias_request,
    q_agent_create_request,
    q_agent_update_request,
    q_prompt_create_request,
    q_prompt_update_request,
    render_contact_flow,
    session_context_lambda_permissions,
)
from .config import ProjectConfig


class DeploymentError(RuntimeError):
    pass


class StateStore:
    def __init__(self, path: Path, project_name: str) -> None:
        self.path = path
        if path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))
        else:
            self.data = {"projectName": project_name, "resources": {}, "outputs": {}}

    @property
    def resources(self) -> dict[str, Any]:
        return self.data.setdefault("resources", {})

    def update(self, **values: Any) -> None:
        self.resources.update({k: v for k, v in values.items() if v is not None})
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=self.path.name, dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self.data, handle, indent=2, default=str)
                handle.write("\n")
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


class CaraHealthBotDeployer:
    def __init__(self, cfg: ProjectConfig, *, verbose: bool = True) -> None:
        self.cfg = cfg
        self.verbose = verbose
        self.session = boto3.Session(region_name=cfg.region)
        self.sts = self.session.client("sts")
        self.connect = self.session.client("connect")
        self.qconnect = self.session.client("qconnect")
        self.lex = self.session.client("lexv2-models")
        self.iam = self.session.client("iam")
        self.logs = self.session.client("logs")
        self.lambda_client = self.session.client("lambda")
        self.s3 = self.session.client("s3")
        self.state = StateStore(cfg.state_path, cfg.project_name)
        self.account_id = ""

    def log(self, message: str) -> None:
        if self.verbose:
            print(message, flush=True)

    @staticmethod
    def _error_code(error: Exception) -> str:
        if isinstance(error, ClientError):
            return error.response.get("Error", {}).get("Code", "")
        return ""

    @classmethod
    def _is_error(cls, error: Exception, *codes: str) -> bool:
        return cls._error_code(error) in codes

    def _paginate(self, client: Any, operation: str, key: str, **kwargs: Any) -> Iterable[Any]:
        if client.can_paginate(operation):
            paginator = client.get_paginator(operation)
            for page in paginator.paginate(**kwargs):
                yield from page.get(key, [])
            return
        method = getattr(client, operation)
        request = dict(kwargs)
        while True:
            page = method(**request)
            yield from page.get(key, [])
            token = page.get("nextToken") or page.get("NextToken")
            if not token:
                return
            request["nextToken" if "nextToken" in page else "NextToken"] = token

    def _wait(
        self,
        description: str,
        reader: Callable[[], tuple[str, Any]],
        desired: set[str],
        failed: set[str],
        *,
        timeout_seconds: int = 900,
        interval_seconds: int = 5,
    ) -> Any:
        deadline = time.time() + timeout_seconds
        last_status = ""
        last_value: Any = None
        while time.time() < deadline:
            status, value = reader()
            last_value = value
            if status != last_status:
                self.log(f"    {description}: {status}")
                last_status = status
            if status in desired:
                return value
            if status in failed:
                raise DeploymentError(f"{description} failed with status {status}: {value}")
            time.sleep(interval_seconds)
        raise DeploymentError(
            f"Timed out waiting for {description}; last status was {last_status}; last response={last_value}"
        )

    def _retry(self, description: str, call: Callable[[], Any], *, attempts: int = 10) -> Any:
        last: Exception | None = None
        retry_codes = {
            "ConflictException",
            "ThrottlingException",
            "TooManyRequestsException",
            "ResourceNotFoundException",
            "InternalServerException",
            "InternalServiceException",
            "ServiceUnavailableException",
        }
        for attempt in range(attempts):
            try:
                return call()
            except ClientError as error:
                if self._error_code(error) not in retry_codes:
                    raise
                last = error
                time.sleep(min(3 * (attempt + 1), 20))
        raise DeploymentError(f"{description} failed after retries: {format_aws_error(last)}")

    def preflight(self) -> str:
        self.log("0/12  AWS identity and local prompt validation")
        identity = self.sts.get_caller_identity()
        self.account_id = identity["Account"]
        self.log(f"    AWS account: {self.account_id}")
        self.log(f"    AWS region:  {self.cfg.region}")
        if len(self.account_id) != 12 or not self.account_id.isdigit():
            raise DeploymentError(f"Unexpected AWS account id: {self.account_id!r}")

        # Parse the prompt now so a malformed heredoc/YAML can never reach AWS.
        raw = self.cfg.prompt_path.read_text(encoding="utf-8")
        try:
            prompt = yaml.safe_load(raw)
        except yaml.YAMLError as error:
            raise DeploymentError(f"Prompt YAML is invalid: {error}") from error
        if not isinstance(prompt, dict) or not isinstance(prompt.get("system"), str):
            raise DeploymentError("Prompt YAML must contain a top-level string field named 'system'")
        if not isinstance(prompt.get("messages"), list):
            raise DeploymentError("Prompt YAML must contain a top-level list field named 'messages'")
        for required in (
            "<message>",
            "</message>",
            "{{$.conversationHistory}}",
            "{{$.locale}}",
            "{{$.Custom.customerName}}",
        ):
            if required not in raw:
                raise DeploymentError(f"Prompt is missing required token: {required}")
        self.log("    Prompt YAML: valid")
        return self.account_id

    # ---------- Amazon Connect instance / telephony ----------

    def ensure_connect_instance(self) -> tuple[str, str, str]:
        self.log("1/12  Isolated Amazon Connect instance")
        alias = self.cfg.instance_alias(self.account_id)
        instances = list(self._paginate(self.connect, "list_instances", "InstanceSummaryList"))
        found = next((x for x in instances if x.get("InstanceAlias") == alias), None)
        if found:
            instance_id = found["Id"]
            existing_instance = self.connect.describe_instance(InstanceId=instance_id)["Instance"]
            existing_arn = existing_instance.get("Arn")
            tags = (
                self.connect.list_tags_for_resource(resourceArn=existing_arn).get("tags", {})
                if existing_arn
                else {}
            )
            if tags.get("Project") != self.cfg.project_name:
                raise DeploymentError(
                    f"Amazon Connect instance alias {alias!r} already exists but is not owned by "
                    f"{self.cfg.project_name}. Refusing to reuse another deployment's instance."
                )
            self.log(f"    Reusing Cara Health Bot instance {alias} ({instance_id})")
        else:
            response = self.connect.create_instance(
                IdentityManagementType="CONNECT_MANAGED",
                InstanceAlias=alias,
                InboundCallsEnabled=True,
                OutboundCallsEnabled=True,
                Tags={"Project": self.cfg.project_name},
                ClientToken=str(uuid.uuid4()),
            )
            instance_id = response["Id"]
            self.log(f"    Created {alias} ({instance_id})")

        instance = self._wait(
            "Connect instance",
            lambda: (
                (r := self.connect.describe_instance(InstanceId=instance_id))["Instance"].get("InstanceStatus", ""),
                r["Instance"],
            ),
            {"ACTIVE"},
            {"CREATION_FAILED"},
            timeout_seconds=1200,
            interval_seconds=10,
        )
        if not instance.get("OutboundCallsEnabled"):
            self.connect.update_instance_attribute(
                InstanceId=instance_id, AttributeType="OUTBOUND_CALLS", Value="true"
            )
        instance_arn = instance["Arn"]
        self.state.update(
            connectInstanceId=instance_id,
            connectInstanceArn=instance_arn,
            connectInstanceAlias=alias,
            connectLogGroup=self.cfg.log_group(self.account_id),
        )
        return instance_id, instance_arn, alias

    def ensure_logging(self, instance_id: str, alias: str) -> str:
        self.log("2/12  Connect flow logging / CloudWatch")
        self.connect.update_instance_attribute(
            InstanceId=instance_id,
            AttributeType="CONTACTFLOW_LOGS",
            Value="true",
        )
        log_group = f"/aws/connect/{alias}"
        # AWS normally creates this automatically. Creating it ourselves if it is
        # not visible yet makes scripts/logs.py useful from the first test call.
        try:
            self.logs.create_log_group(logGroupName=log_group, tags={"Project": self.cfg.project_name})
            self.log(f"    Created log group {log_group}")
        except ClientError as error:
            if not self._is_error(error, "ResourceAlreadyExistsException"):
                raise
            self.log(f"    Log group ready: {log_group}")
        lex_log_group = self.cfg.lex_conversation_log_group(self.account_id)
        try:
            self.logs.create_log_group(
                logGroupName=lex_log_group,
                tags={"Project": self.cfg.project_name, "Purpose": "LexConversationText"},
            )
            self.log(f"    Created Lex conversation log group {lex_log_group}")
        except ClientError as error:
            if not self._is_error(error, "ResourceAlreadyExistsException"):
                raise
            self.log(f"    Lex conversation log group ready: {lex_log_group}")
        self.state.update(connectLogGroup=log_group, lexConversationLogGroup=lex_log_group)
        return log_group

    def ensure_recording_storage(self, instance_id: str) -> tuple[str, str, str]:
        """Create/reuse S3 storage for Connect IVR recordings.

        This is intentionally independent of the console-only Bot Analytics /
        Automated Interaction Logs switches. The recording itself is enough for
        scripts/transcript.py to recover customer speech deterministically.
        """
        self.log("3/12  Automated-interaction recording storage")
        bucket = self.cfg.recording_bucket(self.account_id)
        prefix = self.cfg.recording_prefix

        try:
            self.s3.head_bucket(Bucket=bucket)
            self.log(f"    Reusing S3 bucket {bucket}")
        except ClientError as error:
            code = self._error_code(error)
            if code not in {"404", "NoSuchBucket", "NotFound"}:
                # HeadBucket commonly returns a numeric 404 code through botocore.
                status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
                if status != 404:
                    raise
            request: dict[str, Any] = {"Bucket": bucket}
            if self.cfg.region != "us-east-1":
                request["CreateBucketConfiguration"] = {"LocationConstraint": self.cfg.region}
            self.s3.create_bucket(**request)
            self.log(f"    Created S3 bucket {bucket}")

        self.s3.put_public_access_block(
            Bucket=bucket,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True,
            },
        )
        self.s3.put_bucket_encryption(
            Bucket=bucket,
            ServerSideEncryptionConfiguration={
                "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
            },
        )

        configs = list(
            self._paginate(
                self.connect,
                "list_instance_storage_configs",
                "StorageConfigs",
                InstanceId=instance_id,
                ResourceType="CALL_RECORDINGS",
            )
        )
        desired = {
            "StorageType": "S3",
            "S3Config": {"BucketName": bucket, "BucketPrefix": prefix},
        }
        if configs:
            current = configs[0]
            association_id = current["AssociationId"]
            current_s3 = current.get("S3Config") or {}
            if current.get("StorageType") != "S3" or current_s3.get("BucketName") != bucket or current_s3.get("BucketPrefix") != prefix:
                self.connect.update_instance_storage_config(
                    InstanceId=instance_id,
                    AssociationId=association_id,
                    ResourceType="CALL_RECORDINGS",
                    StorageConfig=desired,
                )
                self.log(f"    Updated Connect CALL_RECORDINGS storage -> s3://{bucket}/{prefix}/")
            else:
                self.log(f"    Connect CALL_RECORDINGS storage ready: s3://{bucket}/{prefix}/")
        else:
            response = self.connect.associate_instance_storage_config(
                InstanceId=instance_id,
                ResourceType="CALL_RECORDINGS",
                StorageConfig=desired,
                ClientToken=str(uuid.uuid4()),
            )
            association_id = response["AssociationId"]
            self.log(f"    Associated Connect CALL_RECORDINGS -> s3://{bucket}/{prefix}/")

        self.state.update(
            recordingBucket=bucket,
            recordingPrefix=prefix,
            recordingStorageAssociationId=association_id,
            transcriptPrefix=self.cfg.transcript_prefix,
        )
        return bucket, prefix, association_id

    def ensure_phone_number(self, instance_id: str) -> tuple[str, str]:
        self.log("4/12  Source phone number")
        phones = list(
            self._paginate(
                self.connect,
                "list_phone_numbers_v2",
                "ListPhoneNumbersSummaryList",
                InstanceId=instance_id,
            )
        )
        preferred = next(
            (x for x in phones if x.get("PhoneNumberType") == self.cfg.phone_number_type),
            None,
        )
        if preferred:
            number = preferred["PhoneNumber"]
            phone_id = preferred["PhoneNumberId"]
            self.log(f"    Reusing {number}")
        else:
            search = self.connect.search_available_phone_numbers(
                InstanceId=instance_id,
                PhoneNumberCountryCode=self.cfg.phone_country_code,
                PhoneNumberType=self.cfg.phone_number_type,
                MaxResults=5,
            )
            available = search.get("AvailableNumbersList", [])
            if not available:
                raise DeploymentError(
                    f"No available {self.cfg.phone_country_code} {self.cfg.phone_number_type} phone numbers were returned. "
                    "This can be caused by account telephony eligibility or quota restrictions."
                )
            number = available[0]["PhoneNumber"]
            claimed = self.connect.claim_phone_number(
                InstanceId=instance_id,
                PhoneNumber=number,
                PhoneNumberDescription="Cara Health Bot outbound source number",
                Tags={"Project": self.cfg.project_name},
                ClientToken=str(uuid.uuid4()),
            )
            phone_id = claimed["PhoneNumberId"]
            self.log(f"    Claimed {number} ({phone_id})")

            def phone_reader() -> tuple[str, Any]:
                r = self.connect.describe_phone_number(PhoneNumberId=phone_id)["ClaimedPhoneNumberSummary"]
                status = (r.get("PhoneNumberStatus") or {}).get("Status") or "CLAIMED"
                return status, r

            self._wait(
                "phone-number claim",
                phone_reader,
                {"CLAIMED"},
                {"FAILED"},
                timeout_seconds=600,
                interval_seconds=5,
            )
        self.state.update(sourcePhoneNumber=number, phoneNumberId=phone_id)
        return number, phone_id

    # ---------- Amazon Q in Connect ----------

    def ensure_assistant(self, instance_id: str) -> tuple[str, str]:
        """Create/reuse only the Cara Health Bot-owned Amazon Q assistant.

        A clean-room deployment must never borrow an assistant from another
        application. Reruns may reuse the same-name Cara assistant created by
        this project, but assistant quota exhaustion is a hard deployment error.
        """
        self.log("5/12  Dedicated Amazon Q in Connect assistant and integration")
        assistants = list(self._paginate(self.qconnect, "list_assistants", "assistantSummaries"))
        found = next(
            (
                x
                for x in assistants
                if x.get("name") == self.cfg.assistant_name
                and x.get("status") not in {"DELETED", "DELETE_IN_PROGRESS", "DELETE_FAILED"}
            ),
            None,
        )

        if found:
            assistant_id = found["assistantId"]
            existing_assistant = self.qconnect.get_assistant(assistantId=assistant_id)["assistant"]
            existing_arn = existing_assistant["assistantArn"]
            tags = self.qconnect.list_tags_for_resource(resourceArn=existing_arn).get("tags", {})
            if tags.get("Project") != self.cfg.project_name:
                raise DeploymentError(
                    f"Amazon Q in Connect assistant {self.cfg.assistant_name!r} already exists but is "
                    f"not tagged Project={self.cfg.project_name}. Refusing to reuse another deployment's assistant."
                )
            self.log(f"    Reusing Cara Health Bot assistant {self.cfg.assistant_name} ({assistant_id})")
        else:
            try:
                response = self.qconnect.create_assistant(
                    name=self.cfg.assistant_name,
                    type="AGENT",
                    description="Dedicated Amazon Q in Connect assistant for Cara Health Bot",
                    tags={"Project": self.cfg.project_name, "AmazonConnectEnabled": "True"},
                    clientToken=str(uuid.uuid4()),
                )
            except ClientError as error:
                if self._is_error(error, "ServiceQuotaExceededException"):
                    existing = ", ".join(
                        sorted(
                            f"{x.get('name')} [{x.get('status')}]"
                            for x in assistants
                            if x.get("name")
                        )
                    ) or "none"
                    raise DeploymentError(
                        "Amazon Q in Connect assistant quota is full. Cara Health Bot is configured "
                        "for a standalone deployment and will not reuse another project's assistant. "
                        f"Existing assistants: {existing}. Remove an unused assistant or obtain "
                        "capacity before rerunning deploy.sh."
                    ) from error
                raise
            assistant_id = response["assistant"]["assistantId"]
            self.log(f"    Created dedicated assistant {self.cfg.assistant_name} ({assistant_id})")

        assistant = self._wait(
            "Q assistant",
            lambda: (
                (r := self.qconnect.get_assistant(assistantId=assistant_id))["assistant"].get("status", ""),
                r["assistant"],
            ),
            {"ACTIVE"},
            {"FAILED", "CREATE_FAILED", "DELETE_FAILED", "DELETED"},
            timeout_seconds=600,
            interval_seconds=5,
        )
        assistant_arn = assistant["assistantArn"]
        self.qconnect.tag_resource(
            resourceArn=assistant_arn,
            tags={"Project": self.cfg.project_name, "AmazonConnectEnabled": "True"},
        )

        integrations = list(
            self._paginate(
                self.connect,
                "list_integration_associations",
                "IntegrationAssociationSummaryList",
                InstanceId=instance_id,
                IntegrationType="WISDOM_ASSISTANT",
            )
        )
        stale_removed = False
        for item in integrations:
            if item.get("IntegrationArn") != assistant_arn:
                self.connect.delete_integration_association(
                    InstanceId=instance_id,
                    IntegrationAssociationId=item["IntegrationAssociationId"],
                )
                stale_removed = True
                self.log(f"    Removed stale assistant integration {item.get('IntegrationArn')}")
        if stale_removed:
            deadline = time.time() + 180
            while time.time() < deadline:
                remaining = list(
                    self._paginate(
                        self.connect,
                        "list_integration_associations",
                        "IntegrationAssociationSummaryList",
                        InstanceId=instance_id,
                        IntegrationType="WISDOM_ASSISTANT",
                    )
                )
                if not any(x.get("IntegrationArn") != assistant_arn for x in remaining):
                    break
                time.sleep(3)
            else:
                raise DeploymentError("Timed out removing a stale Connect Q assistant integration")

        integrations = list(
            self._paginate(
                self.connect,
                "list_integration_associations",
                "IntegrationAssociationSummaryList",
                InstanceId=instance_id,
                IntegrationType="WISDOM_ASSISTANT",
            )
        )
        matching = next((x for x in integrations if x.get("IntegrationArn") == assistant_arn), None)
        if not matching:
            response = self._retry(
                "attach Q assistant to Connect",
                lambda: self.connect.create_integration_association(
                    InstanceId=instance_id,
                    IntegrationType="WISDOM_ASSISTANT",
                    IntegrationArn=assistant_arn,
                    Tags={"Project": self.cfg.project_name},
                ),
                attempts=12,
            )
            integration_id = response["IntegrationAssociationId"]
            self.log(f"    Attached assistant to Connect ({integration_id})")
        else:
            integration_id = matching["IntegrationAssociationId"]
            self.log("    Assistant integration already correct")

        self.state.update(
            assistantId=assistant_id,
            assistantArn=assistant_arn,
            assistantName=assistant.get("name"),
            assistantOwnership="cara-health-bot",
            assistantIntegrationId=integration_id,
        )
        return assistant_id, assistant_arn

    def ensure_security_profile(self, instance_id: str) -> tuple[str, str]:
        profiles = list(
            self._paginate(
                self.connect,
                "list_security_profiles",
                "SecurityProfileSummaryList",
                InstanceId=instance_id,
            )
        )
        found = next((x for x in profiles if x.get("Name") == self.cfg.security_profile_name), None)
        permissions = ["BasicAgentAccess", "Wisdom.View"]
        if found:
            profile_id, profile_arn = found["Id"], found["Arn"]
            self.connect.update_security_profile(
                InstanceId=instance_id,
                SecurityProfileId=profile_id,
                Description="Security profile for the Cara Health Bot orchestration agent",
                Permissions=permissions,
            )
        else:
            response = self.connect.create_security_profile(
                InstanceId=instance_id,
                SecurityProfileName=self.cfg.security_profile_name,
                Description="Security profile for the Cara Health Bot orchestration agent",
                Permissions=permissions,
                Tags={"Project": self.cfg.project_name},
            )
            profile_id, profile_arn = response["SecurityProfileId"], response["SecurityProfileArn"]
        self.state.update(securityProfileId=profile_id, securityProfileArn=profile_arn)
        return profile_id, profile_arn

    def _session_context_zip(self) -> bytes:
        source = (self.cfg.root / "lambda" / "session_context.py").read_bytes()
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("session_context.py", source)
        return buffer.getvalue()

    def _wait_lambda_ready(self, function_name: str, timeout_seconds: int = 300) -> dict[str, Any]:
        deadline = time.time() + timeout_seconds
        last: dict[str, Any] = {}
        while time.time() < deadline:
            last = self.lambda_client.get_function_configuration(FunctionName=function_name)
            state = last.get("State")
            update = last.get("LastUpdateStatus")
            if state == "Active" and update in {None, "Successful"}:
                return last
            if state == "Failed" or update == "Failed":
                raise DeploymentError(
                    f"Session-context Lambda failed to become ready: state={state}, "
                    f"update={update}, reason={last.get('StateReason') or last.get('LastUpdateStatusReason')}"
                )
            time.sleep(3)
        raise DeploymentError(f"Timed out waiting for Lambda {function_name} to become ready: {last}")

    def ensure_session_context_lambda(
        self, instance_id: str, instance_arn: str, assistant_id: str
    ) -> tuple[str, str]:
        self.log("6/12  Per-call customer identity context Lambda")
        role_name = self.cfg.session_context_lambda_role_name
        try:
            role = self.iam.get_role(RoleName=role_name)["Role"]
            self.iam.update_assume_role_policy(
                RoleName=role_name,
                PolicyDocument=json.dumps(lambda_trust_policy()),
            )
        except ClientError as error:
            if not self._is_error(error, "NoSuchEntity"):
                raise
            role = self.iam.create_role(
                RoleName=role_name,
                Description="Cara Health Bot Lambda role for copying per-call identity context into Q sessions",
                AssumeRolePolicyDocument=json.dumps(lambda_trust_policy()),
                Tags=[{"Key": "Project", "Value": self.cfg.project_name}],
            )["Role"]

        self.iam.put_role_policy(
            RoleName=role_name,
            PolicyName=self.cfg.session_context_lambda_policy_name,
            PolicyDocument=json.dumps(
                session_context_lambda_permissions(
                    self.cfg.region,
                    self.account_id,
                    assistant_id,
                    self.cfg.session_context_lambda_name,
                )
            ),
        )
        role_arn = role["Arn"]
        function_name = self.cfg.session_context_lambda_name
        code = {"ZipFile": self._session_context_zip()}

        try:
            current = self.lambda_client.get_function(FunctionName=function_name)["Configuration"]
            self._wait_lambda_ready(function_name)
            self.lambda_client.update_function_code(FunctionName=function_name, **code)
            self._wait_lambda_ready(function_name)
            self.lambda_client.update_function_configuration(
                FunctionName=function_name,
                Role=role_arn,
                Runtime="python3.12",
                Handler="session_context.handler",
                Timeout=8,
                MemorySize=128,
                Description="Copies expected customer identity into the current Amazon Q in Connect session",
            )
            function = self._wait_lambda_ready(function_name)
            self.log(f"    Updated Lambda {function_name}")
        except ClientError as error:
            if not self._is_error(error, "ResourceNotFoundException"):
                raise
            self.log("    Waiting for Lambda IAM role propagation")
            time.sleep(12)
            response = self.lambda_client.create_function(
                FunctionName=function_name,
                Runtime="python3.12",
                Role=role_arn,
                Handler="session_context.handler",
                Code=code,
                Description="Copies expected customer identity into the current Amazon Q in Connect session",
                Timeout=8,
                MemorySize=128,
                Publish=False,
                Tags={"Project": self.cfg.project_name, "Purpose": "IdentityContext"},
            )
            function = self._wait_lambda_ready(function_name)
            self.log(f"    Created Lambda {function_name}")

        function_arn = function.get("FunctionArn")
        if not function_arn:
            function_arn = self.lambda_client.get_function_configuration(
                FunctionName=function_name
            )["FunctionArn"]

        statement_id = "CaraHealthBotConnectInvoke"
        try:
            self.lambda_client.remove_permission(
                FunctionName=function_name, StatementId=statement_id
            )
        except ClientError as error:
            if not self._is_error(error, "ResourceNotFoundException"):
                raise
        self.lambda_client.add_permission(
            FunctionName=function_name,
            StatementId=statement_id,
            Action="lambda:InvokeFunction",
            Principal="connect.amazonaws.com",
            SourceAccount=self.account_id,
            SourceArn=instance_arn,
        )

        associated = self.connect.list_lambda_functions(InstanceId=instance_id).get(
            "LambdaFunctions", []
        )
        if function_arn not in associated:
            self.connect.associate_lambda_function(
                InstanceId=instance_id,
                FunctionArn=function_arn,
                ClientToken=str(uuid.uuid4()),
            )
            self.log("    Associated Lambda with the Connect instance")
        else:
            self.log("    Lambda already associated with the Connect instance")

        self.state.update(
            sessionContextLambdaName=function_name,
            sessionContextLambdaArn=function_arn,
            sessionContextLambdaRoleName=role_name,
            sessionContextLambdaRoleArn=role_arn,
        )
        return function_name, function_arn

    def ensure_prompt_and_agent(
        self,
        instance_id: str,
        instance_arn: str,
        assistant_id: str,
        security_profile_id: str,
    ) -> tuple[str, str, str]:
        self.log("7/12  Cara prompt and self-service orchestration agent")
        content = self.cfg.prompt_path.read_text(encoding="utf-8")
        prompts = list(
            self._paginate(
                self.qconnect,
                "list_ai_prompts",
                "aiPromptSummaries",
                assistantId=assistant_id,
            )
        )
        prompt = next((x for x in prompts if x.get("name") == self.cfg.prompt_name), None)
        if prompt:
            prompt_id = prompt["aiPromptId"]
            self.qconnect.update_ai_prompt(
                **q_prompt_update_request(self.cfg, assistant_id, prompt_id, content)
            )
            self.log(f"    Updated prompt {self.cfg.prompt_name} ({prompt_id})")
        else:
            response = self.qconnect.create_ai_prompt(
                **q_prompt_create_request(self.cfg, assistant_id, content)
            )
            prompt_id = response["aiPrompt"]["aiPromptId"]
            self.log(f"    Created prompt {self.cfg.prompt_name} ({prompt_id})")

        prompt_version_response = self._retry(
            "publish prompt version",
            lambda: self.qconnect.create_ai_prompt_version(
                assistantId=assistant_id, aiPromptId=prompt_id, clientToken=str(uuid.uuid4())
            ),
        )
        prompt_version = str(prompt_version_response["versionNumber"])
        prompt_version_id = f"{prompt_id}:{prompt_version}"
        self.log(f"    Published prompt version {prompt_version}")

        agents = list(
            self._paginate(
                self.qconnect,
                "list_ai_agents",
                "aiAgentSummaries",
                assistantId=assistant_id,
            )
        )
        agent = next((x for x in agents if x.get("name") == self.cfg.agent_name), None)
        if agent:
            agent_id = agent["aiAgentId"]
            self.qconnect.update_ai_agent(
                **q_agent_update_request(
                    self.cfg, assistant_id, instance_arn, agent_id, prompt_version_id
                )
            )
            self.log(f"    Updated agent {self.cfg.agent_name} ({agent_id})")
        else:
            response = self.qconnect.create_ai_agent(
                **q_agent_create_request(self.cfg, assistant_id, instance_arn, prompt_version_id)
            )
            agent_id = response["aiAgent"]["aiAgentId"]
            self.log(f"    Created agent {self.cfg.agent_name} ({agent_id})")

        agent_version_response = self._retry(
            "publish agent version",
            lambda: self.qconnect.create_ai_agent_version(
                assistantId=assistant_id, aiAgentId=agent_id, clientToken=str(uuid.uuid4())
            ),
        )
        agent_version = str(agent_version_response["versionNumber"])
        base_agent_arn = f"arn:aws:wisdom:{self.cfg.region}:{self.account_id}:ai-agent/{assistant_id}/{agent_id}"
        agent_version_arn = f"{base_agent_arn}:{agent_version}"
        self.log(f"    Published agent version {agent_version}")

        # Connect AI agent permissions are attached to the mutable and numbered forms.
        for target_arn in (f"{base_agent_arn}:$SAVED", f"{base_agent_arn}:$LATEST", agent_version_arn):
            try:
                self._retry(
                    f"associate security profile with {target_arn}",
                    lambda target=target_arn: self.connect.associate_security_profiles(
                        InstanceId=instance_id,
                        EntityType="AI_AGENT",
                        EntityArn=target,
                        SecurityProfiles=[{"Id": security_profile_id}],
                    ),
                    attempts=6,
                )
            except ClientError as error:
                if not self._is_error(error, "ResourceInUseException", "DuplicateResourceException"):
                    raise

        # Critical fix learned from the failed deployment: the custom orchestrator
        # must be the assistant's Connect.SelfService orchestrator. Do not rely on
        # a Lex session-attribute override in the contact flow.
        self._retry(
            "set self-service orchestrator",
            lambda: self.qconnect.update_assistant_ai_agent(
                assistantId=assistant_id,
                aiAgentType="ORCHESTRATION",
                orchestratorUseCase="Connect.SelfService",
                configuration={"aiAgentId": f"{agent_id}:{agent_version}"},
            ),
        )
        assistant = self.qconnect.get_assistant(assistantId=assistant_id)["assistant"]
        orchestrators = assistant.get("orchestratorConfigurationList", [])
        expected = {"aiAgentId": f"{agent_id}:{agent_version}", "orchestratorUseCase": "Connect.SelfService"}
        if expected not in orchestrators:
            raise DeploymentError(
                "Q assistant did not retain the Cara Health Bot Connect.SelfService orchestrator configuration"
            )

        self.state.update(
            aiPromptId=prompt_id,
            aiPromptVersion=prompt_version,
            aiAgentId=agent_id,
            aiAgentVersion=agent_version,
            aiAgentVersionArn=agent_version_arn,
        )
        return agent_id, agent_version, agent_version_arn

    # ---------- IAM / Lex / Nova 2 Sonic ----------

    def ensure_lex_role(self, assistant_id: str, assistant_arn: str) -> tuple[str, str]:
        self.log("8/12  Least-privilege Lex runtime role")
        role_name = self.cfg.lex_runtime_role_name
        try:
            role = self.iam.get_role(RoleName=role_name)["Role"]
            self.iam.update_assume_role_policy(
                RoleName=role_name,
                PolicyDocument=json.dumps(initial_lex_trust_policy(self.account_id)),
            )
        except ClientError as error:
            if not self._is_error(error, "NoSuchEntity"):
                raise
            role = self.iam.create_role(
                RoleName=role_name,
                Description="Custom runtime role for Cara Health Bot Lex and Amazon Q in Connect",
                AssumeRolePolicyDocument=json.dumps(initial_lex_trust_policy(self.account_id)),
                Tags=[{"Key": "Project", "Value": self.cfg.project_name}],
            )["Role"]
        self.iam.put_role_policy(
            RoleName=role_name,
            PolicyName=self.cfg.lex_runtime_policy_name,
            PolicyDocument=json.dumps(
                lex_runtime_permissions(
                    self.cfg.region,
                    self.account_id,
                    assistant_id,
                    assistant_arn,
                    self.state.resources.get("lexConversationLogGroup"),
                )
            ),
        )
        role_arn = role["Arn"]
        self.state.update(lexRuntimeRoleName=role_name, lexRuntimeRoleArn=role_arn)
        self.log("    Waiting for IAM role propagation")
        time.sleep(15)
        return role_name, role_arn

    def ensure_identity_lex_role(self) -> tuple[str, str]:
        self.log("8b/12 Identity Lex runtime role")
        role_name = self.cfg.identity_lex_runtime_role_name
        trust = json.dumps(standard_lex_trust_policy(self.account_id))
        try:
            role = self.iam.get_role(RoleName=role_name)["Role"]
            self.iam.update_assume_role_policy(
                RoleName=role_name,
                PolicyDocument=trust,
            )
        except ClientError as error:
            if not self._is_error(error, "NoSuchEntity"):
                raise
            role = self.iam.create_role(
                RoleName=role_name,
                Description="Runtime role for Cara Health Bot deterministic identity Lex bot",
                AssumeRolePolicyDocument=trust,
                Tags=[{"Key": "Project", "Value": self.cfg.project_name}],
            )["Role"]
        self.iam.put_role_policy(
            RoleName=role_name,
            PolicyName=self.cfg.identity_lex_runtime_policy_name,
            PolicyDocument=json.dumps(
                identity_lex_runtime_permissions(
                    self.cfg.region,
                    self.account_id,
                    self.state.resources.get("lexConversationLogGroup"),
                )
            ),
        )
        role_arn = role["Arn"]
        self.state.update(
            identityLexRuntimeRoleName=role_name,
            identityLexRuntimeRoleArn=role_arn,
        )
        self.log("    Waiting for identity Lex IAM role propagation")
        time.sleep(12)
        return role_name, role_arn

    def _find_bot_by_name(self, bot_name: str) -> dict[str, Any] | None:
        return next(
            (
                x
                for x in self._paginate(self.lex, "list_bots", "botSummaries", maxResults=100)
                if x.get("botName") == bot_name
            ),
            None,
        )

    def _identity_version_is_correct(self, bot_id: str, version: str) -> bool:
        if not version or version == "DRAFT":
            return False
        try:
            meta = self.lex.describe_bot_version(botId=bot_id, botVersion=str(version))
            if meta.get("botStatus") != "Available":
                return False
            locale = self.lex.describe_bot_locale(
                botId=bot_id, botVersion=str(version), localeId=self.cfg.locale
            )
            if locale.get("botLocaleStatus") != "Built":
                return False
            intents = list(
                self._paginate(
                    self.lex,
                    "list_intents",
                    "intentSummaries",
                    botId=bot_id,
                    botVersion=str(version),
                    localeId=self.cfg.locale,
                    maxResults=100,
                )
            )
            by_name = {x.get("intentName"): x.get("intentId") for x in intents}
            expected_builders = {
                "IdentityConfirmed": identity_confirmed_intent_request,
                "IdentityNamedConfirmation": lambda cfg, bid: identity_named_confirmation_intent_request(
                    cfg, bid, with_slots=True
                ),
                "IdentityDenied": identity_denied_intent_request,
                "IdentityAmbiguous": identity_ambiguous_intent_request,
                "ThirdPartyDetected": third_party_detected_intent_request,
                "PatientUnavailable": patient_unavailable_intent_request,
                "WrongNumber": wrong_number_intent_request,
                "RepresentativeDetected": representative_detected_intent_request,
                "Deceased": deceased_intent_request,
                "CallRefusal": call_refusal_intent_request,
                "SafetyMedical": safety_medical_intent_request,
                "SafetyBehavioral": safety_behavioral_intent_request,
            }
            for name, builder in expected_builders.items():
                intent_id = by_name.get(name)
                if not intent_id:
                    return False
                actual = self.lex.describe_intent(
                    botId=bot_id,
                    botVersion=str(version),
                    localeId=self.cfg.locale,
                    intentId=intent_id,
                )
                expected = builder(self.cfg, bot_id)
                actual_samples = {
                    x.get("utterance") for x in actual.get("sampleUtterances", [])
                }
                expected_samples = {
                    x.get("utterance") for x in expected.get("sampleUtterances", [])
                }
                if actual_samples != expected_samples:
                    return False

            named_id = by_name.get("IdentityNamedConfirmation")
            if not named_id:
                return False
            named_slots = list(
                self._paginate(
                    self.lex,
                    "list_slots",
                    "slotSummaries",
                    botId=bot_id,
                    botVersion=str(version),
                    localeId=self.cfg.locale,
                    intentId=named_id,
                    maxResults=100,
                )
            )
            slots_by_name = {x.get("slotName"): x.get("slotId") for x in named_slots}
            for slot_name, slot_type in {
                "firstName": "AMAZON.FirstName",
                "lastName": "AMAZON.LastName",
            }.items():
                slot_id = slots_by_name.get(slot_name)
                if not slot_id:
                    return False
                actual_slot = self.lex.describe_slot(
                    botId=bot_id,
                    botVersion=str(version),
                    localeId=self.cfg.locale,
                    intentId=named_id,
                    slotId=slot_id,
                )
                if actual_slot.get("slotTypeId") != slot_type:
                    return False
                if actual_slot.get("valueElicitationSetting", {}).get("slotConstraint") != "Optional":
                    return False
            return "FallbackIntent" in by_name
        except ClientError:
            return False

    def ensure_identity_lex(
        self, role_arn: str, connect_instance_arn: str
    ) -> tuple[str, str, str, str]:
        self.log("9/12  Deterministic Lex identity gate")
        found = self._find_bot_by_name(self.cfg.identity_bot_name)
        if found:
            bot_id = found["botId"]
            current = self.lex.describe_bot(botId=bot_id)
            if current.get("botStatus") not in {"Available", "Failed"}:
                self._wait_bot(bot_id)
            self.lex.update_bot(
                **identity_lex_bot_update_request(self.cfg, bot_id, role_arn)
            )
            self.log(f"    Updating identity bot {self.cfg.identity_bot_name} ({bot_id})")
        else:
            response = self.lex.create_bot(
                **identity_lex_bot_create_request(self.cfg, role_arn)
            )
            bot_id = response["botId"]
            self.log(f"    Created identity bot {self.cfg.identity_bot_name} ({bot_id})")
        self._wait_bot(bot_id)
        bot_arn = f"arn:aws:lex:{self.cfg.region}:{self.account_id}:bot/{bot_id}"
        self.lex.tag_resource(
            resourceARN=bot_arn,
            tags={"AmazonConnectEnabled": "True", "Project": self.cfg.project_name},
        )

        alias = self._find_alias(bot_id)
        version = str(alias.get("botVersion")) if alias else ""
        if alias and self._identity_version_is_correct(bot_id, version):
            self.log(f"    Existing identity Live version {version} already matches V9 full-name-validated Cara identity gate")
        else:
            locale_request = identity_lex_locale_request(self.cfg, bot_id)
            if self._locale_exists(bot_id):
                current_locale = self.lex.describe_bot_locale(
                    botId=bot_id, botVersion="DRAFT", localeId=self.cfg.locale
                )
                if current_locale.get("botLocaleStatus") not in {
                    "NotBuilt", "Built", "ReadyExpressTesting", "Failed"
                }:
                    self._wait_draft_locale_stable(bot_id)
                if current_locale.get("botLocaleStatus") != "Failed":
                    self.lex.update_bot_locale(**locale_request)
            else:
                self.lex.create_bot_locale(**locale_request)
            self._wait_draft_locale_stable(bot_id)

            self._upsert_intent(
                bot_id, identity_confirmed_intent_request(self.cfg, bot_id)
            )
            named_intent_id = self._upsert_intent(
                bot_id, identity_named_confirmation_intent_request(self.cfg, bot_id)
            )
            first_name_slot_id = self._upsert_slot(
                bot_id,
                named_intent_id,
                identity_first_name_slot_request(self.cfg, bot_id, named_intent_id),
            )
            last_name_slot_id = self._upsert_slot(
                bot_id,
                named_intent_id,
                identity_last_name_slot_request(self.cfg, bot_id, named_intent_id),
            )
            named_request = identity_named_confirmation_intent_request(
                self.cfg, bot_id, with_slots=True
            )
            named_request["slotPriorities"] = [
                {"priority": 1, "slotId": first_name_slot_id},
                {"priority": 2, "slotId": last_name_slot_id},
            ]
            self._upsert_intent(bot_id, named_request)
            self._upsert_intent(
                bot_id, identity_denied_intent_request(self.cfg, bot_id)
            )
            self._upsert_intent(
                bot_id, identity_ambiguous_intent_request(self.cfg, bot_id)
            )
            self._upsert_intent(
                bot_id, third_party_detected_intent_request(self.cfg, bot_id)
            )
            self._upsert_intent(
                bot_id, patient_unavailable_intent_request(self.cfg, bot_id)
            )
            self._upsert_intent(
                bot_id, wrong_number_intent_request(self.cfg, bot_id)
            )
            self._upsert_intent(
                bot_id, representative_detected_intent_request(self.cfg, bot_id)
            )
            self._upsert_intent(
                bot_id, deceased_intent_request(self.cfg, bot_id)
            )
            self._upsert_intent(
                bot_id, call_refusal_intent_request(self.cfg, bot_id)
            )
            self._upsert_intent(
                bot_id, safety_medical_intent_request(self.cfg, bot_id)
            )
            self._upsert_intent(
                bot_id, safety_behavioral_intent_request(self.cfg, bot_id)
            )
            self._upsert_intent(
                bot_id, identity_fallback_intent_request(self.cfg, bot_id)
            )
            try:
                self.lex.build_bot_locale(
                    botId=bot_id, botVersion="DRAFT", localeId=self.cfg.locale
                )
                self.log("    Submitted identity locale build")
            except ClientError as error:
                if not self._is_error(error, "ConflictException"):
                    raise
            self._wait(
                "Identity Lex DRAFT locale build",
                lambda: (
                    (r := self.lex.describe_bot_locale(
                        botId=bot_id, botVersion="DRAFT", localeId=self.cfg.locale
                    )).get("botLocaleStatus", ""),
                    r,
                ),
                {"Built"},
                {"Failed"},
                timeout_seconds=900,
                interval_seconds=5,
            )

            baseline = {
                str(x.get("botVersion")) for x in self._numeric_version_summaries(bot_id)
            }
            last_error: ClientError | None = None
            for attempt in range(1, 7):
                try:
                    response = self.lex.create_bot_version(
                        botId=bot_id,
                        description="Cara Health Bot identity gate with safety-first conversational recipient handling",
                        botVersionLocaleSpecification={
                            self.cfg.locale: {"sourceBotVersion": "DRAFT"}
                        },
                    )
                    version = str(response["botVersion"])
                    self.log(f"    Creating identity Lex version {version}")
                    break
                except ClientError as error:
                    last_error = error
                    if self._error_code(error) not in {
                        "ResourceNotFoundException",
                        "ConflictException",
                        "PreconditionFailedException",
                        "InternalServerException",
                        "ServiceUnavailableException",
                        "ThrottlingException",
                    }:
                        raise
                    time.sleep(5)
                    fresh = [
                        str(x.get("botVersion"))
                        for x in self._numeric_version_summaries(bot_id)
                        if str(x.get("botVersion")) not in baseline
                    ]
                    if fresh:
                        version = fresh[0]
                        self.log(f"    Recovered identity Lex version {version}")
                        break
                    if attempt < 6:
                        time.sleep(min(5 * attempt, 20))
            else:
                raise DeploymentError(
                    "Identity Lex CreateBotVersion failed after retries: "
                    + format_aws_error(last_error)
                )
            self._wait(
                f"Identity Lex bot version {version}",
                lambda: self._read_numbered_version_status(bot_id, version),
                {"Available"},
                {"Failed"},
                timeout_seconds=900,
                interval_seconds=5,
            )
            self._wait(
                f"Identity Lex version {version} locale",
                lambda: self._read_numbered_locale_status(bot_id, version),
                {"Built"},
                {"Failed"},
                timeout_seconds=600,
                interval_seconds=5,
            )
            if not self._identity_version_is_correct(bot_id, version):
                raise DeploymentError(
                    "Published identity Lex version does not match the V9 full-name-validated Cara identity gate"
                )

        conversation_log_group = self.state.resources.get("lexConversationLogGroup")
        if not conversation_log_group:
            raise DeploymentError("Lex conversation log group is missing from deployment state")
        conversation_log_group_arn = (
            f"arn:aws:logs:{self.cfg.region}:{self.account_id}:log-group:{conversation_log_group}"
        )
        alias_request = identity_lex_alias_request(
            self.cfg, bot_id, version, conversation_log_group_arn
        )
        alias = self._find_alias(bot_id)
        if alias:
            alias_id = alias["botAliasId"]
            current = self.lex.describe_bot_alias(botId=bot_id, botAliasId=alias_id)
            if current.get("botAliasStatus") not in {"Available", "Failed"}:
                self._wait(
                    "Identity Lex Live alias",
                    lambda: (
                        (r := self.lex.describe_bot_alias(
                            botId=bot_id, botAliasId=alias_id
                        )).get("botAliasStatus", ""),
                        r,
                    ),
                    {"Available"},
                    {"Failed"},
                )
            self.lex.update_bot_alias(botAliasId=alias_id, **alias_request)
        else:
            response = self.lex.create_bot_alias(
                **alias_request,
                tags={"AmazonConnectEnabled": "True", "Project": self.cfg.project_name},
            )
            alias_id = response["botAliasId"]
        alias_data = self._wait(
            "Identity Lex Live alias",
            lambda: (
                (r := self.lex.describe_bot_alias(
                    botId=bot_id, botAliasId=alias_id
                )).get("botAliasStatus", ""),
                r,
            ),
            {"Available"},
            {"Failed"},
        )
        if (
            alias_data.get("botAliasLocaleSettings", {})
            .get(self.cfg.locale, {})
            .get("enabled")
            is not True
        ):
            raise DeploymentError("Identity Lex Live alias does not have en_US enabled")
        alias_arn = (
            f"arn:aws:lex:{self.cfg.region}:{self.account_id}:bot-alias/{bot_id}/{alias_id}"
        )
        policy = json.dumps(
            lex_alias_resource_policy(self.account_id, connect_instance_arn, alias_arn)
        )
        try:
            current_policy = self.lex.describe_resource_policy(resourceArn=alias_arn)
            self.lex.update_resource_policy(
                resourceArn=alias_arn,
                policy=policy,
                expectedRevisionId=current_policy["revisionId"],
            )
        except ClientError as error:
            if not self._is_error(error, "ResourceNotFoundException"):
                raise
            self.lex.create_resource_policy(resourceArn=alias_arn, policy=policy)
        self.state.update(
            identityBotId=bot_id,
            identityBotVersion=version,
            identityBotAliasId=alias_id,
            identityBotAliasArn=alias_arn,
        )
        return bot_id, version, alias_id, alias_arn

    def _availability_version_is_correct(self, bot_id: str, version: str) -> bool:
        if not version or version == "DRAFT":
            return False
        try:
            meta = self.lex.describe_bot_version(botId=bot_id, botVersion=str(version))
            if meta.get("botStatus") != "Available":
                return False
            locale = self.lex.describe_bot_locale(
                botId=bot_id, botVersion=str(version), localeId=self.cfg.locale
            )
            if locale.get("botLocaleStatus") != "Built":
                return False
            intents = list(
                self._paginate(
                    self.lex,
                    "list_intents",
                    "intentSummaries",
                    botId=bot_id,
                    botVersion=str(version),
                    localeId=self.cfg.locale,
                    maxResults=100,
                )
            )
            by_name = {x.get("intentName"): x.get("intentId") for x in intents}
            for name, builder in {
                "TargetAvailableNow": availability_now_intent_request,
                "AvailabilityUnknown": availability_unknown_intent_request,
                "RepresentativeWillingToProceed": availability_representative_willing_intent_request,
                "WrongNumber": wrong_number_intent_request,
                "Deceased": deceased_intent_request,
                "SafetyMedical": safety_medical_intent_request,
                "SafetyBehavioral": safety_behavioral_intent_request,
            }.items():
                intent_id = by_name.get(name)
                if not intent_id:
                    return False
                actual = self.lex.describe_intent(
                    botId=bot_id,
                    botVersion=str(version),
                    localeId=self.cfg.locale,
                    intentId=intent_id,
                )
                expected = builder(self.cfg, bot_id)
                if {x.get("utterance") for x in actual.get("sampleUtterances", [])} != {
                    x.get("utterance") for x in expected.get("sampleUtterances", [])
                }:
                    return False
            unavailable_id = by_name.get("TargetUnavailable")
            if not unavailable_id or "FallbackIntent" not in by_name:
                return False
            unavailable = self.lex.describe_intent(
                botId=bot_id,
                botVersion=str(version),
                localeId=self.cfg.locale,
                intentId=unavailable_id,
            )
            expected_unavailable = availability_unavailable_intent_request(
                self.cfg, bot_id, slot_priorities=[]
            )
            if {x.get("utterance") for x in unavailable.get("sampleUtterances", [])} != {
                x.get("utterance") for x in expected_unavailable.get("sampleUtterances", [])
            }:
                return False
            slots = list(
                self._paginate(
                    self.lex,
                    "list_slots",
                    "slotSummaries",
                    botId=bot_id,
                    botVersion=str(version),
                    localeId=self.cfg.locale,
                    intentId=unavailable_id,
                    maxResults=100,
                )
            )
            by_slot = {x.get("slotName"): x.get("slotId") for x in slots}
            expected_types = {"callbackDate": "AMAZON.Date", "callbackTime": "AMAZON.Time"}
            for slot_name, slot_type in expected_types.items():
                slot_id = by_slot.get(slot_name)
                if not slot_id:
                    return False
                actual_slot = self.lex.describe_slot(
                    botId=bot_id,
                    botVersion=str(version),
                    localeId=self.cfg.locale,
                    intentId=unavailable_id,
                    slotId=slot_id,
                )
                if actual_slot.get("slotTypeId") != slot_type:
                    return False
                if actual_slot.get("valueElicitationSetting", {}).get("slotConstraint") != "Optional":
                    return False
            return True
        except ClientError:
            return False

    def ensure_availability_lex(
        self, role_arn: str, connect_instance_arn: str
    ) -> tuple[str, str, str, str]:
        self.log("9b/12 Third-party availability Lex bot")
        found = self._find_bot_by_name(self.cfg.availability_bot_name)
        if found:
            bot_id = found["botId"]
            current = self.lex.describe_bot(botId=bot_id)
            if current.get("botStatus") not in {"Available", "Failed"}:
                self._wait_bot(bot_id)
            self.lex.update_bot(
                **availability_lex_bot_update_request(self.cfg, bot_id, role_arn)
            )
            self.log(f"    Updating availability bot {self.cfg.availability_bot_name} ({bot_id})")
        else:
            response = self.lex.create_bot(
                **availability_lex_bot_create_request(self.cfg, role_arn)
            )
            bot_id = response["botId"]
            self.log(f"    Created availability bot {self.cfg.availability_bot_name} ({bot_id})")
        self._wait_bot(bot_id)
        bot_arn = f"arn:aws:lex:{self.cfg.region}:{self.account_id}:bot/{bot_id}"
        self.lex.tag_resource(
            resourceARN=bot_arn,
            tags={"AmazonConnectEnabled": "True", "Project": self.cfg.project_name},
        )

        alias = next(
            (
                x
                for x in self._paginate(
                    self.lex, "list_bot_aliases", "botAliasSummaries", botId=bot_id, maxResults=100
                )
                if x.get("botAliasName") == self.cfg.availability_bot_alias_name
            ),
            None,
        )
        version = str(alias.get("botVersion")) if alias else ""
        if alias and self._availability_version_is_correct(bot_id, version):
            self.log(f"    Existing availability Live version {version} already matches V3 wrong-number-safe availability behavior")
        else:
            locale_request = availability_lex_locale_request(self.cfg, bot_id)
            if self._locale_exists(bot_id):
                current_locale = self.lex.describe_bot_locale(
                    botId=bot_id, botVersion="DRAFT", localeId=self.cfg.locale
                )
                if current_locale.get("botLocaleStatus") not in {
                    "NotBuilt", "Built", "ReadyExpressTesting", "Failed"
                }:
                    self._wait_draft_locale_stable(bot_id)
                self.lex.update_bot_locale(**locale_request)
            else:
                self.lex.create_bot_locale(**locale_request)
            self._wait_draft_locale_stable(bot_id)

            self._upsert_intent(bot_id, availability_now_intent_request(self.cfg, bot_id))
            unavailable_id = self._upsert_intent(
                bot_id, availability_unavailable_intent_request(self.cfg, bot_id)
            )
            self._upsert_intent(bot_id, availability_unknown_intent_request(self.cfg, bot_id))
            self._upsert_intent(
                bot_id, availability_representative_willing_intent_request(self.cfg, bot_id)
            )
            self._upsert_intent(bot_id, wrong_number_intent_request(self.cfg, bot_id))
            self._upsert_intent(bot_id, deceased_intent_request(self.cfg, bot_id))
            self._upsert_intent(bot_id, safety_medical_intent_request(self.cfg, bot_id))
            self._upsert_intent(bot_id, safety_behavioral_intent_request(self.cfg, bot_id))
            self._upsert_intent(bot_id, availability_fallback_intent_request(self.cfg, bot_id))

            date_slot_id = self._upsert_slot(
                bot_id,
                unavailable_id,
                availability_callback_date_slot_request(self.cfg, bot_id, unavailable_id),
            )
            time_slot_id = self._upsert_slot(
                bot_id,
                unavailable_id,
                availability_callback_time_slot_request(self.cfg, bot_id, unavailable_id),
            )
            final_unavailable = availability_unavailable_intent_request(
                self.cfg,
                bot_id,
                slot_priorities=[
                    {"priority": 1, "slotId": date_slot_id},
                    {"priority": 2, "slotId": time_slot_id},
                ],
            )
            self.lex.update_intent(intentId=unavailable_id, **final_unavailable)

            try:
                self.lex.build_bot_locale(
                    botId=bot_id, botVersion="DRAFT", localeId=self.cfg.locale
                )
                self.log("    Submitted availability locale build")
            except ClientError as error:
                if not self._is_error(error, "ConflictException"):
                    raise
            self._wait(
                "Availability Lex DRAFT locale build",
                lambda: (
                    (r := self.lex.describe_bot_locale(
                        botId=bot_id, botVersion="DRAFT", localeId=self.cfg.locale
                    )).get("botLocaleStatus", ""),
                    r,
                ),
                {"Built"},
                {"Failed"},
                timeout_seconds=900,
                interval_seconds=5,
            )

            baseline = {
                str(x.get("botVersion")) for x in self._numeric_version_summaries(bot_id)
            }
            last_error: ClientError | None = None
            for attempt in range(1, 7):
                try:
                    response = self.lex.create_bot_version(
                        botId=bot_id,
                        description="Cara Health Bot third-party availability conversation",
                        botVersionLocaleSpecification={
                            self.cfg.locale: {"sourceBotVersion": "DRAFT"}
                        },
                    )
                    version = str(response["botVersion"])
                    self.log(f"    Creating availability Lex version {version}")
                    break
                except ClientError as error:
                    last_error = error
                    if self._error_code(error) not in {
                        "ResourceNotFoundException",
                        "ConflictException",
                        "PreconditionFailedException",
                        "InternalServerException",
                        "ServiceUnavailableException",
                        "ThrottlingException",
                    }:
                        raise
                    time.sleep(5)
                    fresh = [
                        str(x.get("botVersion"))
                        for x in self._numeric_version_summaries(bot_id)
                        if str(x.get("botVersion")) not in baseline
                    ]
                    if fresh:
                        version = fresh[0]
                        self.log(f"    Recovered availability Lex version {version}")
                        break
                    if attempt < 6:
                        time.sleep(min(5 * attempt, 20))
            else:
                raise DeploymentError(
                    "Availability Lex CreateBotVersion failed after retries: "
                    + format_aws_error(last_error)
                )
            self._wait(
                f"Availability Lex bot version {version}",
                lambda: self._read_numbered_version_status(bot_id, version),
                {"Available"},
                {"Failed"},
                timeout_seconds=900,
                interval_seconds=5,
            )
            self._wait(
                f"Availability Lex version {version} locale",
                lambda: self._read_numbered_locale_status(bot_id, version),
                {"Built"},
                {"Failed"},
                timeout_seconds=600,
                interval_seconds=5,
            )
            if not self._availability_version_is_correct(bot_id, version):
                raise DeploymentError(
                    "Published availability Lex version does not match the expected availability bot"
                )

        conversation_log_group = self.state.resources.get("lexConversationLogGroup")
        if not conversation_log_group:
            raise DeploymentError("Lex conversation log group is missing from deployment state")
        conversation_log_group_arn = (
            f"arn:aws:logs:{self.cfg.region}:{self.account_id}:log-group:{conversation_log_group}"
        )
        alias_request = availability_lex_alias_request(
            self.cfg, bot_id, version, conversation_log_group_arn
        )
        alias = next(
            (
                x
                for x in self._paginate(
                    self.lex, "list_bot_aliases", "botAliasSummaries", botId=bot_id, maxResults=100
                )
                if x.get("botAliasName") == self.cfg.availability_bot_alias_name
            ),
            None,
        )
        if alias:
            alias_id = alias["botAliasId"]
            current = self.lex.describe_bot_alias(botId=bot_id, botAliasId=alias_id)
            if current.get("botAliasStatus") not in {"Available", "Failed"}:
                self._wait(
                    "Availability Lex Live alias",
                    lambda: (
                        (r := self.lex.describe_bot_alias(
                            botId=bot_id, botAliasId=alias_id
                        )).get("botAliasStatus", ""),
                        r,
                    ),
                    {"Available"},
                    {"Failed"},
                )
            self.lex.update_bot_alias(botAliasId=alias_id, **alias_request)
        else:
            response = self.lex.create_bot_alias(
                **alias_request,
                tags={"AmazonConnectEnabled": "True", "Project": self.cfg.project_name},
            )
            alias_id = response["botAliasId"]
        alias_data = self._wait(
            "Availability Lex Live alias",
            lambda: (
                (r := self.lex.describe_bot_alias(
                    botId=bot_id, botAliasId=alias_id
                )).get("botAliasStatus", ""),
                r,
            ),
            {"Available"},
            {"Failed"},
        )
        if (
            alias_data.get("botAliasLocaleSettings", {})
            .get(self.cfg.locale, {})
            .get("enabled")
            is not True
        ):
            raise DeploymentError("Availability Lex Live alias does not have en_US enabled")
        alias_arn = (
            f"arn:aws:lex:{self.cfg.region}:{self.account_id}:bot-alias/{bot_id}/{alias_id}"
        )
        policy = json.dumps(
            lex_alias_resource_policy(self.account_id, connect_instance_arn, alias_arn)
        )
        try:
            current_policy = self.lex.describe_resource_policy(resourceArn=alias_arn)
            self.lex.update_resource_policy(
                resourceArn=alias_arn,
                policy=policy,
                expectedRevisionId=current_policy["revisionId"],
            )
        except ClientError as error:
            if not self._is_error(error, "ResourceNotFoundException"):
                raise
            self.lex.create_resource_policy(resourceArn=alias_arn, policy=policy)
        self.state.update(
            availabilityBotId=bot_id,
            availabilityBotVersion=version,
            availabilityBotAliasId=alias_id,
            availabilityBotAliasArn=alias_arn,
        )
        return bot_id, version, alias_id, alias_arn

    def _find_bot(self) -> dict[str, Any] | None:
        return next(
            (
                x
                for x in self._paginate(self.lex, "list_bots", "botSummaries", maxResults=100)
                if x.get("botName") == self.cfg.bot_name
            ),
            None,
        )

    def ensure_bot(self, role_name: str, role_arn: str) -> str:
        found = self._find_bot()
        if found:
            bot_id = found["botId"]
            current = self.lex.describe_bot(botId=bot_id)
            if current.get("botStatus") not in {"Available", "Failed"}:
                self._wait_bot(bot_id)
            self.lex.update_bot(**lex_bot_update_request(self.cfg, bot_id, role_arn))
            self.log(f"    Updating existing Lex bot {self.cfg.bot_name} ({bot_id})")
        else:
            response = self.lex.create_bot(**lex_bot_create_request(self.cfg, role_arn))
            bot_id = response["botId"]
            self.log(f"    Created Lex bot {self.cfg.bot_name} ({bot_id})")
        self._wait_bot(bot_id)
        bot_arn = f"arn:aws:lex:{self.cfg.region}:{self.account_id}:bot/{bot_id}"
        self.lex.tag_resource(
            resourceARN=bot_arn,
            tags={"AmazonConnectEnabled": "True", "Project": self.cfg.project_name},
        )
        self.iam.update_assume_role_policy(
            RoleName=role_name,
            PolicyDocument=json.dumps(final_lex_trust_policy(self.account_id, bot_id)),
        )
        self.log("    Tightened Lex internal trust to this exact bot; waiting for IAM propagation")
        time.sleep(20)
        self.state.update(botId=bot_id)
        return bot_id

    def _wait_bot(self, bot_id: str) -> dict[str, Any]:
        return self._wait(
            "Lex bot",
            lambda: (
                (r := self.lex.describe_bot(botId=bot_id)).get("botStatus", ""),
                r,
            ),
            {"Available"},
            {"Failed"},
        )

    def _locale_exists(self, bot_id: str) -> bool:
        try:
            self.lex.describe_bot_locale(botId=bot_id, botVersion="DRAFT", localeId=self.cfg.locale)
            return True
        except ClientError as error:
            if self._is_error(error, "ResourceNotFoundException"):
                return False
            raise

    def _reset_failed_locale_if_needed(self, bot_id: str, locale_id: str = "en_US") -> None:
        """Delete a Failed DRAFT locale so it can be recreated cleanly."""
        try:
            resp = self.lex.describe_bot_locale(botId=bot_id, botVersion="DRAFT", localeId=locale_id)
            if resp.get("botLocaleStatus") == "Failed":
                self.log(f"    Bot locale {locale_id} for bot {bot_id} is in Failed state — deleting to allow fresh create")
                self.lex.delete_bot_locale(botId=bot_id, botVersion="DRAFT", localeId=locale_id)
                for _ in range(30):
                    try:
                        self.lex.describe_bot_locale(botId=bot_id, botVersion="DRAFT", localeId=locale_id)
                        time.sleep(2)
                    except self.lex.exceptions.ResourceNotFoundException:
                        break
                self.log(f"    Bot locale {locale_id} deleted — will recreate fresh")
        except self.lex.exceptions.ResourceNotFoundException:
            pass

    def _wait_draft_locale_stable(self, bot_id: str) -> dict[str, Any]:
        return self._wait(
            "Lex DRAFT locale",
            lambda: (
                (r := self.lex.describe_bot_locale(
                    botId=bot_id, botVersion="DRAFT", localeId=self.cfg.locale
                )).get("botLocaleStatus", ""),
                r,
            ),
            {"NotBuilt", "Built", "ReadyExpressTesting", "Failed"},
            {"Deleting"},
            timeout_seconds=900,
        )

    def _wait_draft_locale_after_build(self, bot_id: str) -> dict[str, Any]:
        # After BuildBotLocale returns, NotBuilt can briefly remain visible.  It is
        # not a publish-ready outcome, so wait until the build reaches either the
        # classic Built state or Nova 2 Sonic's ReadyExpressTesting state.
        return self._wait(
            "Lex DRAFT locale build",
            lambda: (
                (r := self.lex.describe_bot_locale(
                    botId=bot_id, botVersion="DRAFT", localeId=self.cfg.locale
                )).get("botLocaleStatus", ""),
                r,
            ),
            {"Built", "ReadyExpressTesting"},
            {"Failed"},
            timeout_seconds=900,
            interval_seconds=5,
        )

    def _upsert_intent(self, bot_id: str, request: dict[str, Any]) -> str:
        intents = list(
            self._paginate(
                self.lex,
                "list_intents",
                "intentSummaries",
                botId=bot_id,
                botVersion="DRAFT",
                localeId=self.cfg.locale,
                maxResults=100,
            )
        )
        found = next((x for x in intents if x.get("intentName") == request["intentName"]), None)
        if found:
            intent_id = found["intentId"]
            self.lex.update_intent(intentId=intent_id, **request)
        else:
            response = self.lex.create_intent(**request)
            intent_id = response["intentId"]
        return intent_id

    def _upsert_slot(self, bot_id: str, intent_id: str, request: dict[str, Any]) -> str:
        slots = list(
            self._paginate(
                self.lex,
                "list_slots",
                "slotSummaries",
                botId=bot_id,
                botVersion="DRAFT",
                localeId=self.cfg.locale,
                intentId=intent_id,
                maxResults=100,
            )
        )
        found = next((x for x in slots if x.get("slotName") == request["slotName"]), None)
        if found:
            slot_id = found["slotId"]
            self.lex.update_slot(slotId=slot_id, **request)
        else:
            response = self.lex.create_slot(**request)
            slot_id = response["slotId"]
        return slot_id

    def _find_alias(self, bot_id: str) -> dict[str, Any] | None:
        return next(
            (
                x
                for x in self._paginate(
                    self.lex, "list_bot_aliases", "botAliasSummaries", botId=bot_id, maxResults=100
                )
                if x.get("botAliasName") == self.cfg.bot_alias_name
            ),
            None,
        )

    def _find_intent_id(self, bot_id: str, version: str, intent_name: str) -> str | None:
        try:
            intents = list(
                self._paginate(
                    self.lex,
                    "list_intents",
                    "intentSummaries",
                    botId=bot_id,
                    botVersion=str(version),
                    localeId=self.cfg.locale,
                    maxResults=100,
                )
            )
        except ClientError:
            return None
        found = next((x for x in intents if x.get("intentName") == intent_name), None)
        return found.get("intentId") if found else None

    def _published_version_is_correct(
        self, bot_id: str, version: str, assistant_arn: str
    ) -> tuple[bool, str | None]:
        if not version or version == "DRAFT":
            return False, None
        try:
            version_meta = self.lex.describe_bot_version(botId=bot_id, botVersion=str(version))
            if version_meta.get("botStatus") != "Available":
                return False, None
            locale = self.lex.describe_bot_locale(
                botId=bot_id, botVersion=str(version), localeId=self.cfg.locale
            )
            if locale.get("botLocaleStatus") != "Built":
                return False, None
            model_arn = (
                locale.get("unifiedSpeechSettings", {})
                .get("speechFoundationModel", {})
                .get("modelArn", "")
            )
            if not model_arn.endswith("/" + self.cfg.speech_model_id):
                return False, None
            published_intent_id = self._find_intent_id(bot_id, str(version), "AmazonQinConnect")
            if not published_intent_id:
                return False, None
            intent = self.lex.describe_intent(
                botId=bot_id,
                botVersion=str(version),
                localeId=self.cfg.locale,
                intentId=published_intent_id,
            )
            actual = (
                intent.get("qInConnectIntentConfiguration", {})
                .get("qInConnectAssistantConfiguration", {})
                .get("assistantArn")
            )
            return actual == assistant_arn, published_intent_id
        except ClientError:
            return False, None

    def _find_best_published_version(
        self, bot_id: str, assistant_arn: str
    ) -> tuple[str | None, str | None]:
        # Recover cleanly from interrupted deployments: a correct numbered version
        # may already exist even if Live was never moved to it.
        summaries = list(
            self._paginate(
                self.lex,
                "list_bot_versions",
                "botVersionSummaries",
                botId=bot_id,
                maxResults=20,
                sortBy={"attribute": "BotVersion", "order": "Descending"},
            )
        )
        numeric = []
        for item in summaries:
            version = str(item.get("botVersion", ""))
            if version.isdigit():
                numeric.append((int(version), version, item.get("botStatus", "")))
        for _, version, status in sorted(numeric, reverse=True):
            if status != "Available":
                continue
            ok, intent_id = self._published_version_is_correct(bot_id, version, assistant_arn)
            if ok:
                return version, intent_id
        return None, None

    def _numeric_version_summaries(self, bot_id: str) -> list[dict[str, Any]]:
        summaries = list(
            self._paginate(
                self.lex,
                "list_bot_versions",
                "botVersionSummaries",
                botId=bot_id,
                maxResults=100,
                sortBy={"attribute": "BotVersion", "order": "Descending"},
            )
        )
        numeric = [x for x in summaries if str(x.get("botVersion", "")).isdigit()]
        return sorted(numeric, key=lambda x: int(str(x["botVersion"])), reverse=True)

    def _settle_draft_for_versioning(
        self, bot_id: str, q_intent_id: str, assistant_arn: str
    ) -> dict[str, Any]:
        """Wait for Nova unified-speech DRAFT resources to become consistently readable.

        A new Nova 2 Sonic locale often reports ReadyExpressTesting before all of
        the backing resources used by CreateBotVersion are immediately visible.
        Waiting forever for Built is also wrong for this integration because a
        unified-speech DRAFT can remain ReadyExpressTesting.  Require several
        consecutive consistent reads instead, while accepting Built immediately.
        """
        deadline = time.time() + 240
        consecutive_ready_reads = 0
        announced = False
        last_locale: dict[str, Any] = {}

        while time.time() < deadline:
            locale = self.lex.describe_bot_locale(
                botId=bot_id, botVersion="DRAFT", localeId=self.cfg.locale
            )
            last_locale = locale
            status = locale.get("botLocaleStatus", "")
            if status == "Failed":
                raise DeploymentError(
                    f"Lex DRAFT locale failed before versioning: {locale.get('failureReasons')}"
                )
            if status == "Built":
                self.log("    DRAFT locale is Built; ready to create immutable version")
                return locale
            if status != "ReadyExpressTesting":
                consecutive_ready_reads = 0
                time.sleep(5)
                continue

            if not announced:
                self.log(
                    "    DRAFT is ReadyExpressTesting; allowing Lex unified-speech resources to settle"
                )
                announced = True

            try:
                intent = self.lex.describe_intent(
                    botId=bot_id,
                    botVersion="DRAFT",
                    localeId=self.cfg.locale,
                    intentId=q_intent_id,
                )
                actual = (
                    intent.get("qInConnectIntentConfiguration", {})
                    .get("qInConnectAssistantConfiguration", {})
                    .get("assistantArn")
                )
                if actual != assistant_arn:
                    raise DeploymentError(
                        f"DRAFT QinConnect assistant changed before versioning: {actual!r} != {assistant_arn!r}"
                    )
                # list_intents forces a second read path through the locale and
                # catches the short eventual-consistency window seen on fresh bots.
                intent_names = {
                    x.get("intentName")
                    for x in self._paginate(
                        self.lex,
                        "list_intents",
                        "intentSummaries",
                        botId=bot_id,
                        botVersion="DRAFT",
                        localeId=self.cfg.locale,
                        maxResults=100,
                    )
                }
                if {"AmazonQinConnect", "FallbackIntent"}.issubset(intent_names):
                    consecutive_ready_reads += 1
                else:
                    consecutive_ready_reads = 0
            except ClientError as error:
                if not self._is_error(error, "ResourceNotFoundException", "ConflictException"):
                    raise
                consecutive_ready_reads = 0

            # Six reads at five-second intervals gives fresh Lex resources a
            # bounded ~30 second consistency window without the old Built-only hang.
            if consecutive_ready_reads >= 6:
                self.log("    DRAFT remained consistently publishable for 30 seconds")
                return locale
            time.sleep(5)

        raise DeploymentError(
            "Lex DRAFT never became consistently publishable after ReadyExpressTesting; "
            f"last locale response={last_locale}"
        )

    def _recover_new_version_after_create_error(
        self, bot_id: str, baseline_versions: set[str], assistant_arn: str
    ) -> str | None:
        """Recover if CreateBotVersion was accepted but the client saw a transient error."""
        for item in self._numeric_version_summaries(bot_id):
            version = str(item.get("botVersion", ""))
            if version in baseline_versions:
                continue
            status = item.get("botStatus", "")
            if status == "Failed":
                continue
            if status != "Available":
                try:
                    self._wait(
                        f"Lex bot version {version}",
                        lambda: self._read_numbered_version_status(bot_id, version),
                        {"Available"},
                        {"Failed"},
                        timeout_seconds=1200,
                        interval_seconds=5,
                    )
                except DeploymentError:
                    continue
            try:
                self._wait(
                    f"Lex version {version} locale",
                    lambda: self._read_numbered_locale_status(bot_id, version),
                    {"Built"},
                    {"Failed"},
                    timeout_seconds=600,
                    interval_seconds=5,
                )
            except DeploymentError:
                continue
            ok, _ = self._published_version_is_correct(bot_id, version, assistant_arn)
            if ok:
                self.log(
                    f"    Recovered Lex version {version} created during a transient API response"
                )
                return version
        return None

    def _create_bot_version_resilient(
        self, bot_id: str, assistant_arn: str
    ) -> str:
        baseline_versions = {
            str(x.get("botVersion")) for x in self._numeric_version_summaries(bot_id)
        }
        retryable = {
            "ResourceNotFoundException",
            "ConflictException",
            "PreconditionFailedException",
            "InternalServerException",
            "ServiceUnavailableException",
            "ThrottlingException",
        }
        last_error: ClientError | None = None

        for attempt in range(1, 13):
            if attempt > 1:
                recovered = self._recover_new_version_after_create_error(
                    bot_id, baseline_versions, assistant_arn
                )
                if recovered:
                    return recovered
            try:
                response = self.lex.create_bot_version(
                    botId=bot_id,
                    description="Cara Health Bot with the current Q assistant and Nova 2 Sonic locale",
                    botVersionLocaleSpecification={
                        self.cfg.locale: {"sourceBotVersion": "DRAFT"}
                    },
                )
                version = str(response["botVersion"])
                self.log(f"    Creating Lex version {version}")
                return version
            except ClientError as error:
                if self._error_code(error) not in retryable:
                    raise
                last_error = error

                # CreateBotVersion has no idempotency token. Give the version list
                # a short propagation window, then check whether AWS created a
                # version despite returning an error before issuing another create.
                time.sleep(5)
                recovered = self._recover_new_version_after_create_error(
                    bot_id, baseline_versions, assistant_arn
                )
                if recovered:
                    return recovered

                if attempt < 12:
                    delay = min(10 + (attempt - 1) * 5, 30)
                    self.log(
                        f"    Lex version creation is not consistent yet "
                        f"({self._error_code(error)}); retrying in {delay}s [{attempt}/12]"
                    )
                    time.sleep(delay)

        raise DeploymentError(
            "Lex CreateBotVersion remained unavailable after consistency retries: "
            f"{format_aws_error(last_error)}"
        )

    def _build_and_version(
        self, bot_id: str, q_intent_id: str, assistant_arn: str
    ) -> str:
        try:
            self.lex.build_bot_locale(botId=bot_id, botVersion="DRAFT", localeId=self.cfg.locale)
            self.log("    Submitted Lex locale build")
        except ClientError as error:
            if not self._is_error(error, "ConflictException"):
                raise
        locale = self._wait_draft_locale_after_build(bot_id)
        if locale.get("failureReasons"):
            raise DeploymentError(f"Lex locale build failures: {locale['failureReasons']}")

        self._settle_draft_for_versioning(bot_id, q_intent_id, assistant_arn)
        version = self._create_bot_version_resilient(bot_id, assistant_arn)

        self._wait(
            f"Lex bot version {version}",
            lambda: self._read_numbered_version_status(bot_id, version),
            {"Available"},
            {"Failed"},
            timeout_seconds=1200,
            interval_seconds=5,
        )
        # A usable numbered version must contain a Built locale. Describe may
        # briefly return ResourceNotFound immediately after the version becomes
        # visible, so make that read resilient too.
        self._wait(
            f"Lex version {version} locale",
            lambda: self._read_numbered_locale_status(bot_id, version),
            {"Built"},
            {"Failed"},
            timeout_seconds=600,
            interval_seconds=5,
        )
        return version

    def _read_numbered_version_status(
        self, bot_id: str, version: str
    ) -> tuple[str, Any]:
        try:
            r = self.lex.describe_bot_version(botId=bot_id, botVersion=version)
            return r.get("botStatus", ""), r
        except ClientError as error:
            if self._is_error(error, "ResourceNotFoundException"):
                return "Propagating", {"message": format_aws_error(error)}
            raise

    def _read_numbered_locale_status(
        self, bot_id: str, version: str
    ) -> tuple[str, Any]:
        try:
            r = self.lex.describe_bot_locale(
                botId=bot_id, botVersion=version, localeId=self.cfg.locale
            )
            return r.get("botLocaleStatus", ""), r
        except ClientError as error:
            if self._is_error(error, "ResourceNotFoundException"):
                return "Propagating", {"message": format_aws_error(error)}
            raise

    def ensure_lex(
        self,
        role_name: str,
        role_arn: str,
        assistant_arn: str,
        connect_instance_arn: str,
    ) -> tuple[str, str, str, str]:
        self.log("10/12 Nova 2 Sonic coaching Lex + correct Q assistant binding")
        bot_id = self.ensure_bot(role_name, role_arn)

        locale_request = lex_locale_request(self.cfg, bot_id)
        if self._locale_exists(bot_id):
            current = self.lex.describe_bot_locale(
                botId=bot_id, botVersion="DRAFT", localeId=self.cfg.locale
            )
            if current.get("botLocaleStatus") not in {"NotBuilt", "Built", "ReadyExpressTesting", "Failed"}:
                self._wait_draft_locale_stable(bot_id)
            self.lex.update_bot_locale(**locale_request)
        else:
            self.lex.create_bot_locale(**locale_request)
        self._wait_draft_locale_stable(bot_id)

        q_intent_id = self._upsert_intent(
            bot_id, lex_qinconnect_intent_request(self.cfg, bot_id, assistant_arn)
        )
        self._upsert_intent(bot_id, safety_medical_intent_request(self.cfg, bot_id))
        self._upsert_intent(bot_id, safety_behavioral_intent_request(self.cfg, bot_id))
        fallback_id = self._upsert_intent(bot_id, lex_fallback_intent_request(self.cfg, bot_id))
        # Critical invariant: never publish a Lex version until DRAFT explicitly
        # points at the exact assistant created/attached earlier in this same run.
        draft_intent = self.lex.describe_intent(
            botId=bot_id,
            botVersion="DRAFT",
            localeId=self.cfg.locale,
            intentId=q_intent_id,
        )
        draft_assistant = (
            draft_intent.get("qInConnectIntentConfiguration", {})
            .get("qInConnectAssistantConfiguration", {})
            .get("assistantArn")
        )
        if draft_assistant != assistant_arn:
            raise DeploymentError(
                f"DRAFT QinConnect assistant mismatch: {draft_assistant!r} != {assistant_arn!r}"
            )

        alias = self._find_alias(bot_id)
        version = str(alias.get("botVersion")) if alias else ""
        published_ok, published_q_intent_id = self._published_version_is_correct(
            bot_id, version, assistant_arn
        ) if alias else (False, None)
        if alias and published_ok:
            self.log(f"    Existing Live version {version} already has the correct assistant and Built Nova 2 Sonic locale")
        else:
            recovered_version, recovered_intent = self._find_best_published_version(
                bot_id, assistant_arn
            )
            if recovered_version:
                version = recovered_version
                published_q_intent_id = recovered_intent
                self.log(
                    f"    Reusing already-published correct Lex version {version} from an earlier/interrupted run"
                )
            else:
                version = self._build_and_version(bot_id, q_intent_id, assistant_arn)
                published_ok, published_q_intent_id = self._published_version_is_correct(
                    bot_id, version, assistant_arn
                )
                if not published_ok or not published_q_intent_id:
                    raise DeploymentError(
                        "The newly published Lex version failed the assistant/locale consistency check"
                    )

        conversation_log_group = self.state.resources.get("lexConversationLogGroup")
        if not conversation_log_group:
            raise DeploymentError("Lex conversation log group was not initialized")
        conversation_log_group_arn = f"arn:aws:logs:{self.cfg.region}:{self.account_id}:log-group:{conversation_log_group}"
        alias_request = lex_alias_request(self.cfg, bot_id, version, conversation_log_group_arn)
        if alias:
            alias_id = alias["botAliasId"]
            current_alias = self.lex.describe_bot_alias(botId=bot_id, botAliasId=alias_id)
            if current_alias.get("botAliasStatus") not in {"Available", "Failed"}:
                self._wait(
                    "Lex Live alias",
                    lambda: (
                        (r := self.lex.describe_bot_alias(botId=bot_id, botAliasId=alias_id)).get("botAliasStatus", ""),
                        r,
                    ),
                    {"Available"},
                    {"Failed"},
                )
            self.lex.update_bot_alias(botAliasId=alias_id, **alias_request)
        else:
            response = self.lex.create_bot_alias(
                **alias_request,
                tags={"AmazonConnectEnabled": "True", "Project": self.cfg.project_name},
            )
            alias_id = response["botAliasId"]

        alias_data = self._wait(
            "Lex Live alias",
            lambda: (
                (r := self.lex.describe_bot_alias(botId=bot_id, botAliasId=alias_id)).get("botAliasStatus", ""),
                r,
            ),
            {"Available"},
            {"Failed"},
        )
        # Critical invariant learned from the runtime error:
        # Live MUST explicitly enable en_US after every alias update.
        locale_setting = (alias_data.get("botAliasLocaleSettings") or {}).get(self.cfg.locale, {})
        if locale_setting.get("enabled") is not True:
            raise DeploymentError(
                f"Live alias does not have {self.cfg.locale} enabled: {alias_data.get('botAliasLocaleSettings')}"
            )
        if str(alias_data.get("botVersion")) != version:
            raise DeploymentError("Live alias is not pointing to the expected version")
        text_logs = (alias_data.get("conversationLogSettings") or {}).get("textLogSettings") or []
        if not any(
            x.get("enabled") is True
            and ((x.get("destination") or {}).get("cloudWatch") or {}).get("cloudWatchLogGroupArn") == conversation_log_group_arn
            for x in text_logs
        ):
            raise DeploymentError("Live alias does not have Cara Health Bot Lex text conversation logs enabled")

        alias_arn = f"arn:aws:lex:{self.cfg.region}:{self.account_id}:bot-alias/{bot_id}/{alias_id}"
        policy = json.dumps(
            lex_alias_resource_policy(self.account_id, connect_instance_arn, alias_arn)
        )
        try:
            current_policy = self.lex.describe_resource_policy(resourceArn=alias_arn)
            self.lex.update_resource_policy(
                resourceArn=alias_arn,
                policy=policy,
                expectedRevisionId=current_policy["revisionId"],
            )
        except ClientError as error:
            if not self._is_error(error, "ResourceNotFoundException"):
                raise
            self.lex.create_resource_policy(resourceArn=alias_arn, policy=policy)

        self.lex.tag_resource(
            resourceARN=alias_arn,
            tags={"AmazonConnectEnabled": "True", "Project": self.cfg.project_name},
        )
        self.state.update(
            botId=bot_id,
            qInConnectIntentId=published_q_intent_id,
            draftQInConnectIntentId=q_intent_id,
            fallbackIntentId=fallback_id,
            botVersion=version,
            botAliasId=alias_id,
            botAliasArn=alias_arn,
        )
        return bot_id, version, alias_id, alias_arn

    def ensure_connect_bot_association(self, instance_id: str, alias_arn: str) -> None:
        bots = list(
            self._paginate(
                self.connect,
                "list_bots",
                "LexBots",
                InstanceId=instance_id,
                LexVersion="V2",
            )
        )
        if any(x.get("LexV2Bot", {}).get("AliasArn") == alias_arn for x in bots):
            return
        self.connect.associate_bot(
            InstanceId=instance_id,
            LexV2Bot={"AliasArn": alias_arn},
            ClientToken=str(uuid.uuid4()),
        )
        deadline = time.time() + 180
        while time.time() < deadline:
            current = list(
                self._paginate(
                    self.connect,
                    "list_bots",
                    "LexBots",
                    InstanceId=instance_id,
                    LexVersion="V2",
                )
            )
            if any(x.get("LexV2Bot", {}).get("AliasArn") == alias_arn for x in current):
                return
            time.sleep(3)
        raise DeploymentError("Timed out waiting for the Lex Live alias to associate with Connect")

    # ---------- Human transfer queue ----------

    def ensure_human_transfer_queue(self, instance_id: str) -> tuple[str, str]:
        """Create/reuse Cara Health Bot-owned hours and STANDARD transfer queue."""
        self.log("10a/12 Cara Health Bot human transfer queue")

        hours_name = "CaraHealthBotHours"
        hours = list(
            self._paginate(
                self.connect,
                "list_hours_of_operations",
                "HoursOfOperationSummaryList",
                InstanceId=instance_id,
            )
        )
        hours_found = next((x for x in hours if x.get("Name") == hours_name), None)
        if hours_found:
            hours_id = hours_found["Id"]
        else:
            day_config = []
            for day in ("SUNDAY", "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY"):
                day_config.append(
                    {
                        "Day": day,
                        "StartTime": {"Hours": 0, "Minutes": 0},
                        "EndTime": {"Hours": 23, "Minutes": 59},
                    }
                )
            response = self.connect.create_hours_of_operation(
                InstanceId=instance_id,
                Name=hours_name,
                Description="24x7 hours for Cara Health Bot human transfer testing",
                TimeZone="UTC",
                Config=day_config,
                Tags={"Project": self.cfg.project_name},
            )
            hours_id = response["HoursOfOperationId"]
            self.log(f"    Created hours of operation {hours_name} ({hours_id})")

        queues = list(
            self._paginate(
                self.connect,
                "list_queues",
                "QueueSummaryList",
                InstanceId=instance_id,
                QueueTypes=["STANDARD"],
            )
        )
        found = next((q for q in queues if q.get("Name") == self.cfg.human_transfer_queue_name), None)
        if found:
            queue_id = found["Id"]
            details = self.connect.describe_queue(InstanceId=instance_id, QueueId=queue_id)["Queue"]
            queue_arn = details.get("QueueArn") or found.get("Arn")
            if details.get("Status") != "ENABLED":
                self.connect.update_queue_status(
                    InstanceId=instance_id,
                    QueueId=queue_id,
                    Status="ENABLED",
                )
                self.log(f"    Enabled queue {self.cfg.human_transfer_queue_name}")
        else:
            response = self.connect.create_queue(
                InstanceId=instance_id,
                Name=self.cfg.human_transfer_queue_name,
                Description="Cara Health Bot human specialist transfer queue",
                HoursOfOperationId=hours_id,
                Tags={"Project": self.cfg.project_name, "Purpose": "HumanTransfer"},
            )
            queue_id = response["QueueId"]
            queue_arn = response["QueueArn"]
            self.log(f"    Created human transfer queue {self.cfg.human_transfer_queue_name} ({queue_id})")

        if not queue_arn:
            raise DeploymentError("Could not resolve human transfer queue ARN")
        self.state.update(
            humanTransferHoursOfOperationId=hours_id,
            humanTransferHoursOfOperationName=hours_name,
            humanTransferQueueId=queue_id,
            humanTransferQueueArn=queue_arn,
            humanTransferQueueName=self.cfg.human_transfer_queue_name,
        )
        self.log(f"    Human transfer queue {self.cfg.human_transfer_queue_name} ({queue_id})")
        return queue_id, queue_arn

    def ensure_human_agent(self, instance_id: str, queue_id: str) -> tuple[str, str, str]:
        """Provision/reuse the Connect human agent and make the Cara queue routable for VOICE.

        The password is consumed only when the CONNECT_MANAGED user must be created.
        It is never written to config.json or deployment-state.json.
        """
        self.log("10b/12 Human transfer agent and routing")

        profiles = list(
            self._paginate(
                self.connect,
                "list_routing_profiles",
                "RoutingProfileSummaryList",
                InstanceId=instance_id,
            )
        )
        routing = next(
            (x for x in profiles if x.get("Name") == self.cfg.human_agent_routing_profile_name),
            None,
        )
        desired_queue_config = {
            "QueueReference": {"QueueId": queue_id, "Channel": "VOICE"},
            "Priority": 1,
            "Delay": 0,
        }
        if routing:
            routing_profile_id = routing["Id"]
        else:
            response = self.connect.create_routing_profile(
                InstanceId=instance_id,
                Name=self.cfg.human_agent_routing_profile_name,
                Description="Cara Health Bot human specialist routing profile",
                DefaultOutboundQueueId=queue_id,
                QueueConfigs=[desired_queue_config],
                MediaConcurrencies=[{"Channel": "VOICE", "Concurrency": 1}],
                Tags={"Project": self.cfg.project_name, "Purpose": "HumanTransfer"},
            )
            routing_profile_id = response["RoutingProfileId"]
            self.log(
                f"    Created routing profile {self.cfg.human_agent_routing_profile_name} "
                f"({routing_profile_id})"
            )

        queue_configs = list(
            self._paginate(
                self.connect,
                "list_routing_profile_queues",
                "RoutingProfileQueueConfigSummaryList",
                InstanceId=instance_id,
                RoutingProfileId=routing_profile_id,
            )
        )
        voice_config = next(
            (
                x
                for x in queue_configs
                if x.get("QueueId") == queue_id and x.get("Channel") == "VOICE"
            ),
            None,
        )
        if not voice_config:
            self.connect.associate_routing_profile_queues(
                InstanceId=instance_id,
                RoutingProfileId=routing_profile_id,
                QueueConfigs=[desired_queue_config],
            )
            self.log(
                f"    Associated {self.cfg.human_transfer_queue_name} / VOICE with "
                f"{self.cfg.human_agent_routing_profile_name}"
            )
        elif voice_config.get("Priority") != 1 or voice_config.get("Delay") != 0:
            self.connect.update_routing_profile_queues(
                InstanceId=instance_id,
                RoutingProfileId=routing_profile_id,
                QueueConfigs=[desired_queue_config],
            )
            self.log(
                f"    Normalized {self.cfg.human_transfer_queue_name} / VOICE routing to priority 1, delay 0"
            )
        else:
            self.log(
                f"    {self.cfg.human_transfer_queue_name} / VOICE already attached to "
                f"{self.cfg.human_agent_routing_profile_name}"
            )

        security_profiles = list(
            self._paginate(
                self.connect,
                "list_security_profiles",
                "SecurityProfileSummaryList",
                InstanceId=instance_id,
            )
        )
        security = next(
            (x for x in security_profiles if x.get("Name") == self.cfg.human_agent_security_profile_name),
            None,
        )
        if security:
            security_profile_id = security["Id"]
            self.connect.update_security_profile(
                InstanceId=instance_id,
                SecurityProfileId=security_profile_id,
                Description="Cara Health Bot human specialist security profile",
                Permissions=["BasicAgentAccess"],
            )
        else:
            response = self.connect.create_security_profile(
                InstanceId=instance_id,
                SecurityProfileName=self.cfg.human_agent_security_profile_name,
                Description="Cara Health Bot human specialist security profile",
                Permissions=["BasicAgentAccess"],
                Tags={"Project": self.cfg.project_name, "Purpose": "HumanTransfer"},
            )
            security_profile_id = response["SecurityProfileId"]
            self.log(
                f"    Created human security profile {self.cfg.human_agent_security_profile_name} "
                f"({security_profile_id})"
            )

        users = list(
            self._paginate(
                self.connect,
                "list_users",
                "UserSummaryList",
                InstanceId=instance_id,
            )
        )
        user = next((x for x in users if x.get("Username") == self.cfg.human_agent_username), None)
        phone_config = {
            "PhoneType": "SOFT_PHONE",
            "AutoAccept": False,
            "AfterContactWorkTimeLimit": self.cfg.human_agent_after_contact_work_seconds,
        }
        identity_info = {
            "FirstName": self.cfg.human_agent_first_name,
            "LastName": self.cfg.human_agent_last_name,
        }

        if user:
            user_id = user["Id"]
            user_arn = user.get("Arn") or self.connect.describe_user(
                InstanceId=instance_id, UserId=user_id
            )["User"]["Arn"]
            self.connect.update_user_routing_profile(
                InstanceId=instance_id,
                UserId=user_id,
                RoutingProfileId=routing_profile_id,
            )
            self.connect.update_user_security_profiles(
                InstanceId=instance_id,
                UserId=user_id,
                SecurityProfileIds=[security_profile_id],
            )
            self.connect.update_user_identity_info(
                InstanceId=instance_id,
                UserId=user_id,
                IdentityInfo=identity_info,
            )
            self.connect.update_user_phone_config(
                InstanceId=instance_id,
                UserId=user_id,
                PhoneConfig=phone_config,
            )
            self.log(f"    Reused and updated Connect user {self.cfg.human_agent_username} ({user_id})")
        else:
            instance = self.connect.describe_instance(InstanceId=instance_id)["Instance"]
            if instance.get("IdentityManagementType") != "CONNECT_MANAGED":
                raise DeploymentError(
                    "Automatic human-agent creation currently requires a CONNECT_MANAGED instance"
                )
            password = os.environ.get("CARA_AGENT_PASSWORD", "")
            if not re.fullmatch(r"(?=.*[a-z])(?=.*[A-Z])(?=.*\d)\S{8,64}", password):
                raise DeploymentError(
                    "CARA_AGENT_PASSWORD is required when creating the human agent and must be "
                    "8-64 non-space characters with at least one lowercase letter, uppercase letter, "
                    "and digit. Pass it inline, for example: CARA_AGENT_PASSWORD='<your-password>' ./deploy.sh"
                )
            response = self.connect.create_user(
                InstanceId=instance_id,
                Username=self.cfg.human_agent_username,
                Password=password,
                IdentityInfo=identity_info,
                PhoneConfig=phone_config,
                RoutingProfileId=routing_profile_id,
                SecurityProfileIds=[security_profile_id],
                Tags={"Project": self.cfg.project_name, "Purpose": "HumanTransferAgent"},
            )
            user_id = response["UserId"]
            user_arn = response["UserArn"]
            self.log(f"    Created Connect user {self.cfg.human_agent_username} ({user_id})")

        access_url = self.connect.describe_instance(InstanceId=instance_id)["Instance"].get(
            "InstanceAccessUrl"
        )
        if not access_url:
            raise DeploymentError("Could not resolve the Amazon Connect instance access URL")
        workspace_url = access_url.rstrip("/") + "/agent-app-v2/"
        self.state.update(
            humanAgentUserId=user_id,
            humanAgentUserArn=user_arn,
            humanAgentUsername=self.cfg.human_agent_username,
            humanAgentRoutingProfileId=routing_profile_id,
            humanAgentRoutingProfileName=self.cfg.human_agent_routing_profile_name,
            humanAgentSecurityProfileId=security_profile_id,
            humanAgentSecurityProfileName=self.cfg.human_agent_security_profile_name,
            humanAgentWorkspaceUrl=workspace_url,
        )
        self.log(f"    Agent Workspace: {workspace_url}")
        return user_id, user_arn, workspace_url

    # ---------- Connect flow ----------

    def _find_flow(self, instance_id: str) -> dict[str, Any] | None:
        return next(
            (
                x
                for x in self._paginate(
                    self.connect,
                    "list_contact_flows",
                    "ContactFlowSummaryList",
                    InstanceId=instance_id,
                    ContactFlowTypes=["CONTACT_FLOW"],
                )
                if x.get("Name") == self.cfg.flow_name
            ),
            None,
        )

    def ensure_contact_flow(
        self,
        instance_id: str,
        assistant_id: str,
        assistant_arn: str,
        alias_arn: str,
        identity_alias_arn: str,
        availability_alias_arn: str,
        session_context_lambda_arn: str,
        human_transfer_queue_arn: str,
    ) -> tuple[str, str]:
        self.log("11/12 Published Amazon Connect conversation flow")
        content = render_contact_flow(
            self.cfg,
            assistant_id,
            assistant_arn,
            alias_arn,
            identity_alias_arn,
            availability_alias_arn,
            session_context_lambda_arn,
            human_transfer_queue_arn,
        )
        found = self._find_flow(instance_id)
        description = "Outbound Cara Health Bot life-coach conversation using Lex, Nova 2 Sonic, and Amazon Q in Connect"
        if found:
            flow_id = found["Id"]
            try:
                self.connect.update_contact_flow_content(
                    InstanceId=instance_id, ContactFlowId=flow_id, Content=content
                )
                self.connect.update_contact_flow_metadata(
                    InstanceId=instance_id,
                    ContactFlowId=flow_id,
                    Name=self.cfg.flow_name,
                    Description=description,
                    ContactFlowState="ACTIVE",
                )
            except ClientError as error:
                raise DeploymentError(format_aws_error(error)) from error
            current = self.connect.describe_contact_flow(
                InstanceId=instance_id, ContactFlowId=flow_id
            )["ContactFlow"]
            if current.get("Status") != "PUBLISHED":
                self.connect.delete_contact_flow(InstanceId=instance_id, ContactFlowId=flow_id)
                time.sleep(3)
                found = None
            else:
                flow_arn = current["Arn"]
                self.log(f"    Updated published flow {self.cfg.flow_name} ({flow_id})")
        if not found:
            try:
                response = self.connect.create_contact_flow(
                    InstanceId=instance_id,
                    Name=self.cfg.flow_name,
                    Type="CONTACT_FLOW",
                    Description=description,
                    Content=content,
                    Status="PUBLISHED",
                    Tags={"Project": self.cfg.project_name},
                )
            except ClientError as error:
                raise DeploymentError(format_aws_error(error)) from error
            flow_id, flow_arn = response["ContactFlowId"], response["ContactFlowArn"]
            self.log(f"    Created and published flow {self.cfg.flow_name} ({flow_id})")

        flow = self.connect.describe_contact_flow(InstanceId=instance_id, ContactFlowId=flow_id)["ContactFlow"]
        if flow.get("Status") != "PUBLISHED":
            raise DeploymentError(f"Contact flow is not PUBLISHED: {flow.get('Status')}")
        flow_content = flow.get("Content") or content
        if (
            assistant_arn not in flow_content
            or alias_arn not in flow_content
            or identity_alias_arn not in flow_content
            or availability_alias_arn not in flow_content
            or session_context_lambda_arn not in flow_content
            or human_transfer_queue_arn not in flow_content
        ):
            raise DeploymentError(
                "Published contact flow does not contain the expected identity gate and human-transfer dependencies"
            )
        if "x-amz-lex:q-in-connect:ai-agent-arn" in flow_content:
            raise DeploymentError("Published flow still contains the unsupported direct AI-agent Lex session override")
        self.state.update(contactFlowId=flow_id, contactFlowArn=flow_arn)
        return flow_id, flow_arn

    # ---------- Verification ----------

    def verify(self) -> dict[str, Any]:
        self.log("12/12 Cross-service runtime consistency checks")
        r = self.state.resources
        required = [
            "connectInstanceId",
            "connectInstanceArn",
            "connectInstanceAlias",
            "sourcePhoneNumber",
            "assistantId",
            "assistantArn",
            "aiAgentId",
            "aiAgentVersion",
            "aiAgentVersionArn",
            "lexRuntimeRoleName",
            "lexRuntimeRoleArn",
            "botId",
            "botVersion",
            "botAliasId",
            "botAliasArn",
            "identityBotId",
            "identityBotVersion",
            "identityBotAliasId",
            "identityBotAliasArn",
            "availabilityBotId",
            "availabilityBotVersion",
            "availabilityBotAliasId",
            "availabilityBotAliasArn",
            "identityLexRuntimeRoleName",
            "identityLexRuntimeRoleArn",
            "qInConnectIntentId",
            "contactFlowId",
            "contactFlowArn",
            "connectLogGroup",
            "lexConversationLogGroup",
            "sessionContextLambdaName",
            "sessionContextLambdaArn",
            "sessionContextLambdaRoleName",
            "humanTransferQueueId",
            "humanTransferQueueArn",
            "humanTransferQueueName",
            "humanAgentUserId",
            "humanAgentUserArn",
            "humanAgentUsername",
            "humanAgentRoutingProfileId",
            "humanAgentRoutingProfileName",
            "humanAgentSecurityProfileId",
            "humanAgentSecurityProfileName",
            "humanAgentWorkspaceUrl",
        ]
        missing = [x for x in required if not r.get(x)]
        if missing:
            raise DeploymentError("Deployment state is missing: " + ", ".join(missing))

        instance = self.connect.describe_instance(InstanceId=r["connectInstanceId"])["Instance"]
        if instance.get("InstanceStatus") != "ACTIVE" or not instance.get("OutboundCallsEnabled"):
            raise DeploymentError("Connect instance is not ACTIVE with outbound calls enabled")

        transfer_queue = self.connect.describe_queue(
            InstanceId=r["connectInstanceId"], QueueId=r["humanTransferQueueId"]
        )["Queue"]
        if transfer_queue.get("Status") != "ENABLED" or transfer_queue.get("QueueArn") != r["humanTransferQueueArn"]:
            raise DeploymentError("Human transfer queue is not ENABLED or does not match deployment state")

        human_user = self.connect.describe_user(
            InstanceId=r["connectInstanceId"], UserId=r["humanAgentUserId"]
        )["User"]
        if human_user.get("Username") != r["humanAgentUsername"]:
            raise DeploymentError("Human agent username does not match deployment state")
        if human_user.get("RoutingProfileId") != r["humanAgentRoutingProfileId"]:
            raise DeploymentError("Human agent is not assigned to the expected routing profile")
        if r["humanAgentSecurityProfileId"] not in human_user.get("SecurityProfileIds", []):
            raise DeploymentError("Human agent is not assigned to the expected Agent security profile")
        if (human_user.get("PhoneConfig") or {}).get("PhoneType") != "SOFT_PHONE":
            raise DeploymentError("Human agent is not configured for SOFT_PHONE")
        routing_queues = list(
            self._paginate(
                self.connect,
                "list_routing_profile_queues",
                "RoutingProfileQueueConfigSummaryList",
                InstanceId=r["connectInstanceId"],
                RoutingProfileId=r["humanAgentRoutingProfileId"],
            )
        )
        if not any(
            x.get("QueueId") == r["humanTransferQueueId"] and x.get("Channel") == "VOICE"
            for x in routing_queues
        ):
            raise DeploymentError("Human agent routing profile does not include the transfer queue for VOICE")

        integrations = list(
            self._paginate(
                self.connect,
                "list_integration_associations",
                "IntegrationAssociationSummaryList",
                InstanceId=r["connectInstanceId"],
                IntegrationType="WISDOM_ASSISTANT",
            )
        )
        if len(integrations) != 1 or integrations[0].get("IntegrationArn") != r["assistantArn"]:
            raise DeploymentError(f"Connect assistant integration is inconsistent: {integrations}")

        lambda_functions = self.connect.list_lambda_functions(
            InstanceId=r["connectInstanceId"]
        ).get("LambdaFunctions", [])
        if r["sessionContextLambdaArn"] not in lambda_functions:
            raise DeploymentError("Session-context Lambda is not associated with the Connect instance")
        lambda_cfg = self.lambda_client.get_function_configuration(
            FunctionName=r["sessionContextLambdaName"]
        )
        if lambda_cfg.get("State") != "Active":
            raise DeploymentError("Session-context Lambda is not Active")
        lambda_policy = self.iam.get_role_policy(
            RoleName=r["sessionContextLambdaRoleName"],
            PolicyName=self.cfg.session_context_lambda_policy_name,
        )["PolicyDocument"]
        lambda_policy_text = json.dumps(lambda_policy)
        if "wisdom:UpdateSessionData" not in lambda_policy_text or r["assistantId"] not in lambda_policy_text:
            raise DeploymentError("Session-context Lambda role is not scoped to UpdateSessionData for the active assistant")

        phones = list(
            self._paginate(
                self.connect,
                "list_phone_numbers_v2",
                "ListPhoneNumbersSummaryList",
                InstanceId=r["connectInstanceId"],
            )
        )
        if not any(x.get("PhoneNumber") == r["sourcePhoneNumber"] for x in phones):
            raise DeploymentError("Source phone number is not assigned to the Cara Health Bot Connect instance")

        assistant = self.qconnect.get_assistant(assistantId=r["assistantId"])["assistant"]
        expected_orchestrator = {
            "aiAgentId": f"{r['aiAgentId']}:{r['aiAgentVersion']}",
            "orchestratorUseCase": "Connect.SelfService",
        }
        if expected_orchestrator not in assistant.get("orchestratorConfigurationList", []):
            raise DeploymentError("Current Q agent version is not configured as Connect.SelfService")
        agent = self.qconnect.get_ai_agent(
            assistantId=r["assistantId"],
            aiAgentId=f"{r['aiAgentId']}:{r['aiAgentVersion']}",
        )["aiAgent"]
        tools = (
            agent.get("configuration", {})
            .get("orchestrationAIAgentConfiguration", {})
            .get("toolConfigurations", [])
        )
        if any(t.get("toolName") in {"IdentityConfirmed", "EndCall"} for t in tools):
            raise DeploymentError(
                "Published Q orchestrator still contains identity tools; identity must be handled before Q"
            )

        identity_bot = self.lex.describe_bot(botId=r["identityBotId"])
        if identity_bot.get("roleArn") != r["identityLexRuntimeRoleArn"]:
            raise DeploymentError("Identity Lex bot is not using its dedicated runtime role")
        identity_alias = self.lex.describe_bot_alias(
            botId=r["identityBotId"], botAliasId=r["identityBotAliasId"]
        )
        if identity_alias.get("botAliasStatus") != "Available":
            raise DeploymentError("Identity Lex Live alias is not Available")
        if str(identity_alias.get("botVersion")) != str(r["identityBotVersion"]):
            raise DeploymentError("Identity Lex Live alias points to the wrong version")
        if (
            identity_alias.get("botAliasLocaleSettings", {})
            .get(self.cfg.locale, {})
            .get("enabled")
            is not True
        ):
            raise DeploymentError("Identity Lex Live alias does not have en_US enabled")
        identity_locale = self.lex.describe_bot_locale(
            botId=r["identityBotId"],
            botVersion=str(r["identityBotVersion"]),
            localeId=self.cfg.locale,
        )
        if identity_locale.get("botLocaleStatus") != "Built":
            raise DeploymentError("Identity Lex locale is not Built")
        if identity_locale.get("unifiedSpeechSettings"):
            raise DeploymentError("Identity Lex bot must remain a deterministic NLU gate, not Nova unified speech")
        identity_intents = list(
            self._paginate(
                self.lex,
                "list_intents",
                "intentSummaries",
                botId=r["identityBotId"],
                botVersion=str(r["identityBotVersion"]),
                localeId=self.cfg.locale,
                maxResults=100,
            )
        )
        identity_names = {x.get("intentName") for x in identity_intents}
        for required_intent in {
            "IdentityConfirmed",
            "IdentityDenied",
            "IdentityAmbiguous",
            "ThirdPartyDetected",
            "PatientUnavailable",
            "FallbackIntent",
        }:
            if required_intent not in identity_names:
                raise DeploymentError(f"Identity Lex bot is missing intent {required_intent}")
        identity_alias_policy = self.lex.describe_resource_policy(
            resourceArn=r["identityBotAliasArn"]
        ).get("policy", "")
        if (
            r["connectInstanceArn"] not in identity_alias_policy
            or "connect.amazonaws.com" not in identity_alias_policy
        ):
            raise DeploymentError(
                "Identity Lex alias resource policy is not scoped to the Cara Health Bot Connect instance"
            )
        availability_bot = self.lex.describe_bot(botId=r["availabilityBotId"])
        if availability_bot.get("roleArn") != r["identityLexRuntimeRoleArn"]:
            raise DeploymentError("Availability Lex bot is not using the deterministic Lex runtime role")
        availability_alias = self.lex.describe_bot_alias(
            botId=r["availabilityBotId"], botAliasId=r["availabilityBotAliasId"]
        )
        if availability_alias.get("botAliasStatus") != "Available":
            raise DeploymentError("Availability Lex Live alias is not Available")
        if str(availability_alias.get("botVersion")) != str(r["availabilityBotVersion"]):
            raise DeploymentError("Availability Lex Live alias points to the wrong version")
        if (
            availability_alias.get("botAliasLocaleSettings", {})
            .get(self.cfg.locale, {})
            .get("enabled")
            is not True
        ):
            raise DeploymentError("Availability Lex Live alias does not have en_US enabled")
        availability_locale = self.lex.describe_bot_locale(
            botId=r["availabilityBotId"],
            botVersion=str(r["availabilityBotVersion"]),
            localeId=self.cfg.locale,
        )
        if availability_locale.get("botLocaleStatus") != "Built":
            raise DeploymentError("Availability Lex locale is not Built")
        availability_intents = list(
            self._paginate(
                self.lex,
                "list_intents",
                "intentSummaries",
                botId=r["availabilityBotId"],
                botVersion=str(r["availabilityBotVersion"]),
                localeId=self.cfg.locale,
                maxResults=100,
            )
        )
        availability_by_name = {x.get("intentName"): x.get("intentId") for x in availability_intents}
        for required_intent in {
            "TargetAvailableNow", "TargetUnavailable", "AvailabilityUnknown", "Deceased", "FallbackIntent"
        }:
            if required_intent not in availability_by_name:
                raise DeploymentError(f"Availability Lex bot is missing intent {required_intent}")
        unavailable_id = availability_by_name["TargetUnavailable"]
        availability_slots = list(
            self._paginate(
                self.lex,
                "list_slots",
                "slotSummaries",
                botId=r["availabilityBotId"],
                botVersion=str(r["availabilityBotVersion"]),
                localeId=self.cfg.locale,
                intentId=unavailable_id,
                maxResults=100,
            )
        )
        if {x.get("slotName") for x in availability_slots} < {"callbackDate", "callbackTime"}:
            raise DeploymentError("Availability Lex TargetUnavailable intent is missing callback date/time slots")
        availability_alias_policy = self.lex.describe_resource_policy(
            resourceArn=r["availabilityBotAliasArn"]
        ).get("policy", "")
        if (
            r["connectInstanceArn"] not in availability_alias_policy
            or "connect.amazonaws.com" not in availability_alias_policy
        ):
            raise DeploymentError(
                "Availability Lex alias resource policy is not scoped to the Cara Health Bot Connect instance"
            )
        availability_text_logs = (
            availability_alias.get("conversationLogSettings") or {}
        ).get("textLogSettings") or []
        expected_availability_log_arn = (
            f"arn:aws:logs:{self.cfg.region}:{self.account_id}:log-group:{r['lexConversationLogGroup']}"
        )
        if not any(
            x.get("enabled") is True
            and ((x.get("destination") or {}).get("cloudWatch") or {}).get(
                "cloudWatchLogGroupArn"
            ) == expected_availability_log_arn
            for x in availability_text_logs
        ):
            raise DeploymentError("Availability Lex alias text conversation logging is not enabled")

        identity_text_logs = (
            identity_alias.get("conversationLogSettings") or {}
        ).get("textLogSettings") or []
        expected_identity_log_arn = (
            f"arn:aws:logs:{self.cfg.region}:{self.account_id}:log-group:{r['lexConversationLogGroup']}"
        )
        if not any(
            x.get("enabled") is True
            and ((x.get("destination") or {}).get("cloudWatch") or {}).get(
                "cloudWatchLogGroupArn"
            ) == expected_identity_log_arn
            for x in identity_text_logs
        ):
            raise DeploymentError("Identity Lex alias text conversation logging is not enabled")

        bot = self.lex.describe_bot(botId=r["botId"])
        if bot.get("roleArn") != r["lexRuntimeRoleArn"]:
            raise DeploymentError("Lex bot is not using the Cara Health Bot custom runtime role")
        alias = self.lex.describe_bot_alias(botId=r["botId"], botAliasId=r["botAliasId"])
        if alias.get("botAliasStatus") != "Available":
            raise DeploymentError("Live Lex alias is not Available")
        if str(alias.get("botVersion")) != str(r["botVersion"]):
            raise DeploymentError("Live Lex alias points to the wrong bot version")
        if (alias.get("botAliasLocaleSettings", {}).get(self.cfg.locale, {}).get("enabled")) is not True:
            raise DeploymentError(f"Live Lex alias does not have {self.cfg.locale} enabled")
        expected_log_arn = f"arn:aws:logs:{self.cfg.region}:{self.account_id}:log-group:{r['lexConversationLogGroup']}"
        text_logs = (alias.get("conversationLogSettings") or {}).get("textLogSettings") or []
        if not any(
            x.get("enabled") is True
            and ((x.get("destination") or {}).get("cloudWatch") or {}).get("cloudWatchLogGroupArn") == expected_log_arn
            for x in text_logs
        ):
            raise DeploymentError("Live Lex alias text conversation logging is not enabled")

        locale = self.lex.describe_bot_locale(
            botId=r["botId"], botVersion=str(r["botVersion"]), localeId=self.cfg.locale
        )
        if locale.get("botLocaleStatus") != "Built":
            raise DeploymentError(f"Published Lex locale is not Built: {locale.get('botLocaleStatus')}")
        model_arn = locale.get("unifiedSpeechSettings", {}).get("speechFoundationModel", {}).get("modelArn", "")
        if not model_arn.endswith("/" + self.cfg.speech_model_id):
            raise DeploymentError(f"Published Lex locale is not using {self.cfg.speech_model_id}: {model_arn}")

        intent = self.lex.describe_intent(
            botId=r["botId"],
            botVersion=str(r["botVersion"]),
            localeId=self.cfg.locale,
            intentId=r["qInConnectIntentId"],
        )
        published_assistant = (
            intent.get("qInConnectIntentConfiguration", {})
            .get("qInConnectAssistantConfiguration", {})
            .get("assistantArn")
        )
        if published_assistant != r["assistantArn"]:
            raise DeploymentError(
                f"Published QinConnect intent points to wrong assistant: {published_assistant}"
            )

        role_policy = self.iam.get_role_policy(
            RoleName=r["lexRuntimeRoleName"], PolicyName=self.cfg.lex_runtime_policy_name
        )["PolicyDocument"]
        policy_text = json.dumps(role_policy)
        for required_text in (
            r["assistantId"],
            "wisdom:CreateSession",
            "wisdom:GetAssistant",
            "wisdom:SendMessage",
            "wisdom:GetNextMessage",
        ):
            if required_text not in policy_text:
                raise DeploymentError(f"Lex runtime policy is missing {required_text}")
        if '"wisdom:*"' in policy_text or '"qconnect:*"' in policy_text:
            raise DeploymentError("Lex runtime policy is unexpectedly broad")

        alias_policy = self.lex.describe_resource_policy(resourceArn=r["botAliasArn"]).get("policy", "")
        if r["connectInstanceArn"] not in alias_policy or "connect.amazonaws.com" not in alias_policy:
            raise DeploymentError("Lex alias resource policy is not scoped to the Cara Health Bot Connect instance")

        bots = list(
            self._paginate(
                self.connect,
                "list_bots",
                "LexBots",
                InstanceId=r["connectInstanceId"],
                LexVersion="V2",
            )
        )
        associated_aliases = {x.get("LexV2Bot", {}).get("AliasArn") for x in bots}
        if r["botAliasArn"] not in associated_aliases:
            raise DeploymentError("Coaching Lex Live alias is not associated with the Connect instance")
        if r["identityBotAliasArn"] not in associated_aliases:
            raise DeploymentError("Identity Lex Live alias is not associated with the Connect instance")
        if r["availabilityBotAliasArn"] not in associated_aliases:
            raise DeploymentError("Availability Lex Live alias is not associated with the Connect instance")

        flow = self.connect.describe_contact_flow(
            InstanceId=r["connectInstanceId"], ContactFlowId=r["contactFlowId"]
        )["ContactFlow"]
        if flow.get("Status") != "PUBLISHED":
            raise DeploymentError("Cara Health Bot contact flow is not PUBLISHED")
        flow_content = flow.get("Content", "")
        if (
            r["sessionContextLambdaArn"] not in flow_content
            or r["identityBotAliasArn"] not in flow_content
            or r["availabilityBotAliasArn"] not in flow_content
            or "IdentityConfirmed" not in flow_content
            or "IdentityNamedConfirmation" not in flow_content
            or "IdentityDenied" not in flow_content
            or "IdentityAmbiguous" not in flow_content
            or "ThirdPartyDetected" not in flow_content
            or "PatientUnavailable" not in flow_content
            or "TargetAvailableNow" not in flow_content
            or "TargetUnavailable" not in flow_content
            or "SafetyMedical" not in flow_content
            or "SafetyBehavioral" not in flow_content
            or "$.Attributes.identityPrompt" not in flow_content
            or "$.Attributes.thirdPartyAvailabilityPrompt" not in flow_content
            or "$.Attributes.patientUnavailablePrompt" not in flow_content
        ):
            raise DeploymentError(
                "Published flow does not contain the safety-first identity and third-party availability behavior"
            )
        try:
            flow_doc = json.loads(flow_content)
            flow_actions = {a.get("Identifier"): a for a in flow_doc.get("Actions", [])}
            identity_1 = flow_actions["10000000-0000-4000-8000-000000000001"]
            identity_2 = flow_actions["10000000-0000-4000-8000-000000000003"]
            first_routes = {
                c["Condition"]["Operands"][0]: c["NextAction"]
                for c in identity_1.get("Transitions", {}).get("Conditions", [])
            }
            second_routes = {
                c["Condition"]["Operands"][0]: c["NextAction"]
                for c in identity_2.get("Transitions", {}).get("Conditions", [])
            }
            if first_routes.get("IdentityConfirmed") != "90000000-0000-4000-8000-000000000004":
                raise DeploymentError("IdentityConfirmed attempt 1 is not routed to persisted confirmed-target state")
            if first_routes.get("IdentityNamedConfirmation") != "f1000000-0000-4000-8000-000000000001":
                raise DeploymentError("Full-name identity attempt 1 is not routed through deterministic name validation")
            if first_routes.get("IdentityDenied") != "e0000000-0000-4000-8000-000000000003":
                raise DeploymentError("IdentityDenied does not persist identityResult=Denied before availability handling")
            if first_routes.get("SafetyMedical") != "d0000000-0000-4000-8000-000000000001":
                raise DeploymentError("Medical safety does not override identity attempt 1")
            if first_routes.get("SafetyBehavioral") != "d0000000-0000-4000-8000-000000000002":
                raise DeploymentError("Behavioral safety does not override identity attempt 1")
            if first_routes.get("PatientUnavailable") != "e0000000-0000-4000-8000-000000000004":
                raise DeploymentError("PatientUnavailable does not persist identityResult=Denied before callback availability")
            if first_routes.get("ThirdPartyDetected") != "e0000000-0000-4000-8000-000000000003":
                raise DeploymentError("ThirdPartyDetected does not persist identityResult=Denied before availability")
            if first_routes.get("IdentityAmbiguous") != "10000000-0000-4000-8000-000000000003":
                raise DeploymentError("IdentityAmbiguous is not routed from identity attempt 1 to clarification")
            if second_routes.get("IdentityConfirmed") != "90000000-0000-4000-8000-000000000004":
                raise DeploymentError("IdentityConfirmed attempt 2 is not routed to persisted confirmed-target state")
            if second_routes.get("IdentityNamedConfirmation") != "f1000000-0000-4000-8000-000000000003":
                raise DeploymentError("Full-name identity attempt 2 is not routed through deterministic name validation")
            if second_routes.get("SafetyMedical") != "d0000000-0000-4000-8000-000000000001":
                raise DeploymentError("Medical safety does not override identity attempt 2")
            if second_routes.get("SafetyBehavioral") != "d0000000-0000-4000-8000-000000000002":
                raise DeploymentError("Behavioral safety does not override identity attempt 2")
            if second_routes.get("PatientUnavailable") != "e0000000-0000-4000-8000-000000000004":
                raise DeploymentError("PatientUnavailable attempt 2 does not persist identityResult=Denied before callback availability")
            if second_routes.get("ThirdPartyDetected") != "e0000000-0000-4000-8000-000000000003":
                raise DeploymentError("ThirdPartyDetected attempt 2 does not persist identityResult=Denied before availability")
            if second_routes.get("IdentityAmbiguous") != "e0000000-0000-4000-8000-000000000006":
                raise DeploymentError("IdentityAmbiguous attempt 2 does not persist identityResult=Ambiguous")
            if second_routes.get("FallbackIntent") != "e0000000-0000-4000-8000-000000000006":
                raise DeploymentError("FallbackIntent attempt 2 does not persist identityResult=Ambiguous")
            if identity_2.get("Transitions", {}).get("NextAction") != "e0000000-0000-4000-8000-000000000006":
                raise DeploymentError("Unresolved identity attempt 2 does not persist identityResult=Ambiguous")
            denied_to_availability = flow_actions["e0000000-0000-4000-8000-000000000003"]
            denied_to_callback = flow_actions["e0000000-0000-4000-8000-000000000004"]
            ambiguous_terminal = flow_actions["e0000000-0000-4000-8000-000000000006"]
            if (denied_to_availability.get("Parameters", {}).get("Attributes", {}).get("identityResult") != "Denied"
                    or denied_to_availability.get("Transitions", {}).get("NextAction") != "a0000000-0000-4000-8000-000000000001"):
                raise DeploymentError("Denied identity persistence block does not continue to privacy-minimal availability")
            if (denied_to_callback.get("Parameters", {}).get("Attributes", {}).get("identityResult") != "Denied"
                    or denied_to_callback.get("Transitions", {}).get("NextAction") != "a0000000-0000-4000-8000-000000000011"):
                raise DeploymentError("PatientUnavailable persistence block does not continue to callback availability")
            if (ambiguous_terminal.get("Parameters", {}).get("Attributes", {}).get("identityResult") != "Ambiguous"
                    or ambiguous_terminal.get("Transitions", {}).get("NextAction") != "10000000-0000-4000-8000-000000000005"):
                raise DeploymentError("Ambiguous identity persistence block must end without being overwritten as Denied")

            for invoke_id, compare_id in (
                ("f1000000-0000-4000-8000-000000000001", "f1000000-0000-4000-8000-000000000002"),
                ("f1000000-0000-4000-8000-000000000003", "f1000000-0000-4000-8000-000000000004"),
                ("f1000000-0000-4000-8000-000000000005", "f1000000-0000-4000-8000-000000000006"),
                ("f1000000-0000-4000-8000-000000000007", "f1000000-0000-4000-8000-000000000008"),
            ):
                invoke = flow_actions.get(invoke_id, {})
                attrs = (invoke.get("Parameters") or {}).get("LambdaInvocationAttributes", {})
                if invoke.get("Type") != "InvokeLambdaFunction" or attrs.get("operation") != "verifyIdentityName":
                    raise DeploymentError("Full-name identity validation Lambda action is missing or malformed")
                if attrs.get("expectedCustomerName") != "$.Attributes.customerName":
                    raise DeploymentError("Full-name validator does not receive expected customer name")
                compare = flow_actions.get(compare_id, {})
                if compare.get("Type") != "Compare" or (compare.get("Parameters") or {}).get("ComparisonValue") != "$.External.identityMatch":
                    raise DeploymentError("Full-name identity validation result router is missing or malformed")
            availability_1 = flow_actions["a0000000-0000-4000-8000-000000000001"]
            availability_routes = {
                c["Condition"]["Operands"][0]: c["NextAction"]
                for c in availability_1.get("Transitions", {}).get("Conditions", [])
            }
            if availability_routes.get("SafetyMedical") != "d0000000-0000-4000-8000-000000000001":
                raise DeploymentError("Medical safety does not override third-party availability")
            if availability_routes.get("SafetyBehavioral") != "d0000000-0000-4000-8000-000000000002":
                raise DeploymentError("Behavioral safety does not override third-party availability")
            if availability_routes.get("WrongNumber") != "e0000000-0000-4000-8000-000000000001":
                raise DeploymentError("WrongNumber is not routed from third-party availability to Denied/wrong-number exit")
            if availability_routes.get("Deceased") != "c0000000-0000-4000-8000-000000000003":
                raise DeploymentError("Deceased is not routed from third-party availability to deceased exit")
            deceased_check = flow_actions["c0000000-0000-4000-8000-000000000003"]
            if deceased_check.get("Type") != "MessageParticipant" or deceased_check.get("Transitions", {}).get("NextAction") != "77777777-7777-4777-8777-777777777777":
                raise DeploymentError("Deceased exit block does not play message and disconnect directly")
            if availability_routes.get("TargetAvailableNow") != "a0000000-0000-4000-8000-000000000006":
                raise DeploymentError("Available third party path does not lead to pass-the-phone re-verification")
            if availability_routes.get("TargetUnavailable") != "a0000000-0000-4000-8000-000000000011":
                raise DeploymentError("Unavailable third party path does not route to patientUnavailablePrompt")
            availability_2 = flow_actions["a0000000-0000-4000-8000-000000000005"]
            availability_2_routes = {
                c["Condition"]["Operands"][0]: c["NextAction"]
                for c in availability_2.get("Transitions", {}).get("Conditions", [])
            }
            if availability_2_routes.get("WrongNumber") != "e0000000-0000-4000-8000-000000000001":
                raise DeploymentError("WrongNumber is not routed from availability clarification to Denied/wrong-number exit")
            if availability_2_routes.get("Deceased") != "c0000000-0000-4000-8000-000000000003":
                raise DeploymentError("Deceased is not routed from availability clarification to deceased exit")
            direct_unavailable = flow_actions.get("a0000000-0000-4000-8000-000000000011", {})
            if direct_unavailable.get("Parameters", {}).get("Text") != "$.Attributes.patientUnavailablePrompt":
                raise DeploymentError("PatientUnavailable path does not use the direct callback prompt")
            direct_routes = {
                c["Condition"]["Operands"][0]: c["NextAction"]
                for c in direct_unavailable.get("Transitions", {}).get("Conditions", [])
            }
            if direct_routes.get("SafetyMedical") != "d0000000-0000-4000-8000-000000000001":
                raise DeploymentError("Medical safety does not override direct unavailable callback handling")
            if direct_routes.get("SafetyBehavioral") != "d0000000-0000-4000-8000-000000000002":
                raise DeploymentError("Behavioral safety does not override direct unavailable callback handling")
            if direct_routes.get("TargetUnavailable") != "a0000000-0000-4000-8000-000000000007":
                raise DeploymentError("Direct unavailable path does not persist callback availability")
            callback_state = flow_actions["a0000000-0000-4000-8000-000000000007"]
            callback_attrs = callback_state.get("Parameters", {}).get("Attributes", {})
            if callback_attrs.get("callbackDate") != "$.Lex.Slots.callbackDate" or callback_attrs.get("callbackTime") != "$.Lex.Slots.callbackTime":
                raise DeploymentError("Callback date/time Lex slots are not persisted to contact attributes")
            transfer_prompt = flow_actions["90000000-0000-4000-8000-000000000003"]
            set_queue = flow_actions["90000000-0000-4000-8000-000000000001"]
            transfer_queue = flow_actions["90000000-0000-4000-8000-000000000002"]
            if transfer_prompt.get("Transitions", {}).get("NextAction") != "90000000-0000-4000-8000-000000000001":
                raise DeploymentError("Identity success message does not route to Set working queue")
            if set_queue.get("Type") != "UpdateContactTargetQueue" or set_queue.get("Parameters", {}).get("QueueId") != r["humanTransferQueueArn"]:
                raise DeploymentError("Set working queue action is not configured for the human transfer queue")
            if set_queue.get("Transitions", {}).get("NextAction") != "90000000-0000-4000-8000-000000000002":
                raise DeploymentError("Set working queue does not route to Transfer to queue")
            if transfer_queue.get("Type") != "TransferContactToQueue":
                raise DeploymentError("Human transfer action is not TransferContactToQueue")
            coaching_q = flow_actions.get("55555555-5555-4555-8555-555555555555", {})
            coaching_routes = {
                c.get("Condition", {}).get("Operands", [None])[0]: c.get("NextAction")
                for c in coaching_q.get("Transitions", {}).get("Conditions", [])
            }
            if coaching_routes.get("SafetyMedical") != "d0000000-0000-4000-8000-000000000001":
                raise DeploymentError("Coaching block does not route SafetyMedical to medical safety exit")
            if coaching_routes.get("SafetyBehavioral") != "d0000000-0000-4000-8000-000000000002":
                raise DeploymentError("Coaching block does not route SafetyBehavioral to behavioral safety exit")
            coaching_errors = {
                e.get("ErrorType"): e.get("NextAction")
                for e in coaching_q.get("Transitions", {}).get("Errors", [])
            }
            if coaching_errors.get("NoMatchingCondition") != "b0000000-0000-4000-8000-000000000001":
                raise DeploymentError(
                    "QinConnect NoMatchingCondition does not route to the Return-to-Control Tool router"
                )
            compares = [a for a in flow_doc.get("Actions", []) if a.get("Type") == "Compare"]
            compare_values = {
                (a.get("Parameters") or {}).get("ComparisonValue") for a in compares
            }
            required_compare_values = {
                "$.Lex.SessionAttributes.Tool",
                "$.Lex.SessionAttributes.endReason",
                "$.External.identityMatch",
            }
            if not required_compare_values <= compare_values:
                raise DeploymentError("Published Cara outcome/name-validation routers are missing or malformed")
            confirmed_attr = (flow_actions.get("90000000-0000-4000-8000-000000000004", {}).get("Parameters") or {}).get("Attributes", {})
            denied_attr = (flow_actions.get("e0000000-0000-4000-8000-000000000001", {}).get("Parameters") or {}).get("Attributes", {})
            ambiguous_attr = (flow_actions.get("e0000000-0000-4000-8000-000000000002", {}).get("Parameters") or {}).get("Attributes", {})
            ambiguous_availability_attr = (flow_actions.get("e0000000-0000-4000-8000-000000000006", {}).get("Parameters") or {}).get("Attributes", {})
            if confirmed_attr.get("identityResult") != "Confirmed":
                raise DeploymentError("Published flow does not persist identityResult=Confirmed")
            if denied_attr.get("identityResult") != "Denied":
                raise DeploymentError("Published flow does not persist identityResult=Denied")
            if ambiguous_attr.get("identityResult") != "Ambiguous":
                raise DeploymentError("Published flow does not persist identityResult=Ambiguous")
            if ambiguous_availability_attr.get("identityResult") != "Ambiguous":
                raise DeploymentError("Published privacy-minimal fallback does not persist identityResult=Ambiguous")
            medical_safety = flow_actions.get("d0000000-0000-4000-8000-000000000003", {})
            behavioral_safety = flow_actions.get("d0000000-0000-4000-8000-000000000004", {})
            if (medical_safety.get("Parameters") or {}).get("Text") != self.cfg.cara_behavior["safetyMedicalResponse"]:
                raise DeploymentError("Published medical safety response is not the configured response")
            if (behavioral_safety.get("Parameters") or {}).get("Text") != self.cfg.cara_behavior["safetyBehavioralResponse"]:
                raise DeploymentError("Published behavioral safety response is not the configured response")
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise DeploymentError(f"Published identity routing is malformed: {exc}") from exc
        if flow_content.find(r["identityBotAliasArn"]) > flow_content.find(r["assistantArn"]):
            raise DeploymentError("Identity gate is not positioned before Amazon Q session creation")

        attr = self.connect.describe_instance_attribute(
            InstanceId=r["connectInstanceId"], AttributeType="CONTACTFLOW_LOGS"
        )["Attribute"]
        if str(attr.get("Value")).lower() != "true":
            raise DeploymentError("Connect flow logging is not enabled")

        storage_configs = list(
            self._paginate(
                self.connect,
                "list_instance_storage_configs",
                "StorageConfigs",
                InstanceId=r["connectInstanceId"],
                ResourceType="CALL_RECORDINGS",
            )
        )
        expected_bucket = r.get("recordingBucket")
        expected_prefix = r.get("recordingPrefix")
        if not any(
            x.get("StorageType") == "S3"
            and (x.get("S3Config") or {}).get("BucketName") == expected_bucket
            and (x.get("S3Config") or {}).get("BucketPrefix") == expected_prefix
            for x in storage_configs
        ):
            raise DeploymentError("Connect CALL_RECORDINGS S3 storage is not configured correctly")

        # The published flow must explicitly enable automated/IVR recording.
        try:
            published_actions = json.loads(flow_content).get("Actions", [])
        except json.JSONDecodeError as error:
            raise DeploymentError(f"Published contact flow content is invalid JSON: {error}") from error
        recording_actions = [x for x in published_actions if x.get("Type") == "UpdateContactRecordingBehavior"]
        if not any(
            ((x.get("Parameters") or {}).get("RecordingBehavior") or {}).get("IVRRecordingBehavior") == "Enabled"
            for x in recording_actions
        ):
            raise DeploymentError("Published flow does not enable automated-interaction (IVR) recording")
        if not any(
            set(((x.get("Parameters") or {}).get("RecordingBehavior") or {}).get("RecordedParticipants") or [])
            >= {"Agent", "Customer"}
            for x in recording_actions
        ):
            raise DeploymentError("Published flow must explicitly record Customer and Agent participants")

        output = {
            "DisplayName": self.cfg.display_name,
            "ProjectName": self.cfg.project_name,
            "Region": self.cfg.region,
            "AccountId": self.account_id,
            "InstanceId": r["connectInstanceId"],
            "InstanceArn": r["connectInstanceArn"],
            "InstanceAlias": r["connectInstanceAlias"],
            "SourcePhoneNumber": r["sourcePhoneNumber"],
            "AssistantId": r["assistantId"],
            "AssistantArn": r["assistantArn"],
            "AIAgentVersionArn": r["aiAgentVersionArn"],
            "BotId": r["botId"],
            "BotVersion": str(r["botVersion"]),
            "BotAliasArn": r["botAliasArn"],
            "IdentityBotId": r["identityBotId"],
            "IdentityBotVersion": str(r["identityBotVersion"]),
            "IdentityBotAliasArn": r["identityBotAliasArn"],
            "AvailabilityBotId": r["availabilityBotId"],
            "AvailabilityBotVersion": str(r["availabilityBotVersion"]),
            "AvailabilityBotAliasArn": r["availabilityBotAliasArn"],
            "SpeechModel": self.cfg.speech_model_id,
            "ContactFlowId": r["contactFlowId"],
            "ContactFlowArn": r["contactFlowArn"],
            "ConnectLogGroup": r["connectLogGroup"],
            "LexConversationLogGroup": r["lexConversationLogGroup"],
            "SessionContextLambdaArn": r["sessionContextLambdaArn"],
            "RecordingBucket": r["recordingBucket"],
            "RecordingPrefix": r["recordingPrefix"],
            "TranscriptPrefix": r["transcriptPrefix"],
            "HumanTransferQueueName": r["humanTransferQueueName"],
            "HumanTransferQueueId": r["humanTransferQueueId"],
            "HumanTransferQueueArn": r["humanTransferQueueArn"],
            "HumanAgentUsername": r["humanAgentUsername"],
            "HumanAgentUserId": r["humanAgentUserId"],
            "HumanAgentRoutingProfileName": r["humanAgentRoutingProfileName"],
            "HumanAgentSecurityProfileName": r["humanAgentSecurityProfileName"],
            "AgentWorkspaceUrl": r["humanAgentWorkspaceUrl"],
        }
        self.state.data["outputs"] = output
        self.state.save()
        self.log("    All cross-service checks passed")
        return output

    def deploy(self) -> dict[str, Any]:
        self.preflight()
        instance_id, instance_arn, alias = self.ensure_connect_instance()
        self.ensure_logging(instance_id, alias)
        self.ensure_recording_storage(instance_id)
        self.ensure_phone_number(instance_id)
        assistant_id, assistant_arn = self.ensure_assistant(instance_id)
        _, session_context_lambda_arn = self.ensure_session_context_lambda(
            instance_id, instance_arn, assistant_id
        )
        security_profile_id, _ = self.ensure_security_profile(instance_id)
        self.ensure_prompt_and_agent(
            instance_id, instance_arn, assistant_id, security_profile_id
        )
        role_name, role_arn = self.ensure_lex_role(assistant_id, assistant_arn)
        identity_role_name, identity_role_arn = self.ensure_identity_lex_role()
        _, _, _, identity_alias_arn = self.ensure_identity_lex(
            identity_role_arn, instance_arn
        )
        _, _, _, availability_alias_arn = self.ensure_availability_lex(
            identity_role_arn, instance_arn
        )
        _, _, _, alias_arn = self.ensure_lex(
            role_name, role_arn, assistant_arn, instance_arn
        )
        self.ensure_connect_bot_association(instance_id, identity_alias_arn)
        self.ensure_connect_bot_association(instance_id, availability_alias_arn)
        self.ensure_connect_bot_association(instance_id, alias_arn)
        human_transfer_queue_id, human_transfer_queue_arn = self.ensure_human_transfer_queue(instance_id)
        self.ensure_human_agent(instance_id, human_transfer_queue_id)
        self.ensure_contact_flow(
            instance_id,
            assistant_id,
            assistant_arn,
            alias_arn,
            identity_alias_arn,
            availability_alias_arn,
            session_context_lambda_arn,
            human_transfer_queue_arn,
        )
        output = self.verify()
        self.log("Deployment complete")
        return output


def format_aws_error(error: Exception | None) -> str:
    if error is None:
        return "Unknown AWS error"
    if isinstance(error, ClientError):
        details = error.response.get("Error", {})
        code = details.get("Code", "ClientError")
        message = details.get("Message") or str(error)
        problems = error.response.get("problems") or error.response.get("Problems")
        request_id = error.response.get("ResponseMetadata", {}).get("RequestId")
        suffix = f" (RequestId: {request_id})" if request_id else ""
        extra = f"; problems={json.dumps(problems)}" if problems else ""
        return f"{code}: {message}{extra}{suffix}"
    if isinstance(error, BotoCoreError):
        return str(error)
    return str(error)
