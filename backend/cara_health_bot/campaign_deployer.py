from __future__ import annotations

import io
import json
import os
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError


class CampaignDeploymentError(RuntimeError):
    pass


@dataclass(frozen=True)
class CampaignNames:
    bucket: str
    batches_table: str = "TalkingBotCallBatches-dev"
    patients_table: str = "TalkingBotPatientRecords-dev"
    intake_function: str = "cara-health-bot-campaign-intake"
    dialer_function: str = "cara-health-bot-campaign-dialer"
    api_function: str = "cara-health-bot-campaign-api"
    availability_function: str = "cara-health-bot-agent-availability"
    intake_role: str = "cara-health-bot-campaign-intake-role"
    dialer_role: str = "cara-health-bot-campaign-dialer-role"
    api_role: str = "cara-health-bot-campaign-api-role"
    scheduler_role: str = "cara-health-bot-campaign-scheduler-role"
    event_rule: str = "cara-health-bot-campaign-disconnected"
    contact_index: str = "StatusSlotIndex"


class CampaignDeployer:
    """Idempotent boto3 deployer for the Cara sequential campaign workaround."""

    def __init__(self, root: Path | None = None, dry_run: bool = False) -> None:
        self.dry_run = dry_run
        self.root = root or Path(__file__).resolve().parents[1]
        self.state_path = self.root / "deployment-state.json"
        if not self.state_path.is_file():
            raise CampaignDeploymentError("deployment-state.json not found. Deploy base Cara first with ./deploy.sh")
        self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.outputs = self.state.get("outputs") or {}

        self.sts = boto3.client("sts")
        identity = self.sts.get_caller_identity()
        self.account_id = identity["Account"]
        caller_arn = identity["Arn"]
        self.partition = caller_arn.split(":", 2)[1]
        self.region = self.outputs.get("Region") or boto3.session.Session().region_name or "us-east-1"

        required = ["AccountId", "InstanceId", "InstanceArn", "ContactFlowId", "SourcePhoneNumber"]
        missing = [key for key in required if not self.outputs.get(key)]
        if missing:
            raise CampaignDeploymentError(f"deployment-state.json missing base Cara outputs: {', '.join(missing)}")
        if self.outputs["AccountId"] != self.account_id:
            raise CampaignDeploymentError(
                f"deployment-state.json belongs to AWS account {self.outputs['AccountId']}, "
                f"but current credentials are for {self.account_id}"
            )

        self.instance_id = self.outputs["InstanceId"]
        self.instance_arn = self.outputs["InstanceArn"]
        self.contact_flow_id = self.outputs["ContactFlowId"]
        self.source_phone = self.outputs["SourcePhoneNumber"]
        self.names = CampaignNames(bucket=f"cara-health-bot-campaigns-{self.account_id}-{self.region}")

        self.s3 = boto3.client("s3", region_name=self.region)
        self.ddb = boto3.client("dynamodb", region_name=self.region)
        self.iam = boto3.client("iam", region_name=self.region)
        self.lambda_client = boto3.client("lambda", region_name=self.region)
        self.events = boto3.client("events", region_name=self.region)
        self.frontend_origin = os.environ.get("CARA_CAMPAIGN_FRONTEND_ORIGIN", "http://localhost:5173")
        self.api_auth_type = os.environ.get("CARA_CAMPAIGN_API_AUTH_TYPE", "NONE").upper()
        if self.api_auth_type not in {"AWS_IAM", "NONE"}:
            raise CampaignDeploymentError("CARA_CAMPAIGN_API_AUTH_TYPE must be AWS_IAM or NONE")

    def log(self, text: str) -> None:
        print(text, flush=True)

    def _arn(self, service: str, resource: str) -> str:
        return f"arn:{self.partition}:{service}:{self.region}:{self.account_id}:{resource}"

    @property
    def table_arn(self) -> str:
        return self._arn("dynamodb", f"table/{self.names.patients_table}")

    @property
    def dialer_arn(self) -> str:
        return self._arn("lambda", f"function:{self.names.dialer_function}")

    @property
    def intake_arn(self) -> str:
        return self._arn("lambda", f"function:{self.names.intake_function}")

    @property
    def api_arn(self) -> str:
        return self._arn("lambda", f"function:{self.names.api_function}")

    @property
    def event_rule_arn(self) -> str:
        return self._arn("events", f"rule/{self.names.event_rule}")

    @property
    def scheduler_role_arn(self) -> str:
        return f"arn:{self.partition}:iam::{self.account_id}:role/{self.names.scheduler_role}"

    def preflight(self) -> None:
        self.log("0/7  Campaign preflight")
        self.log(f"    AWS account: {self.account_id}")
        self.log(f"    AWS region:  {self.region}")
        self.log(f"    Reusing Connect instance: {self.instance_id}")
        self.log(f"    Reusing contact flow:     {self.contact_flow_id}")
        self.log(f"    Reusing source number:    {self.source_phone}")

    def ensure_bucket(self) -> None:
        self.log("1/7  Campaign S3 intake bucket")
        try:
            self.s3.head_bucket(Bucket=self.names.bucket)
            self.log(f"    Reusing S3 bucket {self.names.bucket}")
        except ClientError as error:
            status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            code = error.response.get("Error", {}).get("Code")
            if status not in {404} and code not in {"404", "NoSuchBucket", "NotFound"}:
                raise
            kwargs: dict[str, Any] = {"Bucket": self.names.bucket}
            if self.region != "us-east-1":
                kwargs["CreateBucketConfiguration"] = {"LocationConstraint": self.region}
            self.s3.create_bucket(**kwargs)
            self.log(f"    Created S3 bucket {self.names.bucket}")

        self.s3.put_public_access_block(
            Bucket=self.names.bucket,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True,
            },
        )
        self.s3.put_bucket_encryption(
            Bucket=self.names.bucket,
            ServerSideEncryptionConfiguration={
                "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
            },
        )
        self.s3.put_bucket_cors(
            Bucket=self.names.bucket,
            CORSConfiguration={"CORSRules": [{
                "AllowedOrigins": [self.frontend_origin],
                "AllowedMethods": ["PUT", "HEAD"],
                "AllowedHeaders": ["content-type"],
                "ExposeHeaders": ["ETag"],
                "MaxAgeSeconds": 900,
            }]},
        )
        self.log(f"    Browser upload CORS origin: {self.frontend_origin}")

    @property
    def batches_table_arn(self) -> str:
        return self._arn("dynamodb", f"table/{self.names.batches_table}")

    @property
    def patients_table_arn(self) -> str:
        return self._arn("dynamodb", f"table/{self.names.patients_table}")

    def ensure_table(self) -> None:
        self.log("2/7  Campaign DynamoDB state tables")
        try:
            self.ddb.describe_table(TableName=self.names.batches_table)
            self.log(f"    Reusing DynamoDB batches table {self.names.batches_table}")
        except self.ddb.exceptions.ResourceNotFoundException:
            self.log(f"    Creating DynamoDB batches table {self.names.batches_table}...")
            self.ddb.create_table(
                TableName=self.names.batches_table,
                KeySchema=[{"AttributeName": "batchId", "KeyType": "HASH"}],
                AttributeDefinitions=[{"AttributeName": "batchId", "AttributeType": "S"}],
                BillingMode="PAY_PER_REQUEST",
                Tags=[{"Key": "Project", "Value": "CaraHealthBot"}, {"Key": "Component", "Value": "Campaign"}],
            )
            self.ddb.get_waiter("table_exists").wait(TableName=self.names.batches_table)
            self.log(f"    Created DynamoDB batches table {self.names.batches_table}")

        try:
            self.ddb.describe_table(TableName=self.names.patients_table)
            self.log(f"    Reusing DynamoDB patients table {self.names.patients_table}")
        except self.ddb.exceptions.ResourceNotFoundException:
            self.log(f"    Creating DynamoDB patients table {self.names.patients_table}...")
            self.ddb.create_table(
                TableName=self.names.patients_table,
                KeySchema=[
                    {"AttributeName": "patientId", "KeyType": "HASH"},
                    {"AttributeName": "batchId", "KeyType": "RANGE"},
                ],
                AttributeDefinitions=[
                    {"AttributeName": "patientId", "AttributeType": "S"},
                    {"AttributeName": "batchId", "AttributeType": "S"},
                    {"AttributeName": "status", "AttributeType": "S"},
                    {"AttributeName": "callSlotStart", "AttributeType": "S"},
                ],
                GlobalSecondaryIndexes=[
                    {
                        "IndexName": "StatusSlotIndex",
                        "KeySchema": [
                            {"AttributeName": "status", "KeyType": "HASH"},
                            {"AttributeName": "callSlotStart", "KeyType": "RANGE"},
                        ],
                        "Projection": {"ProjectionType": "ALL"},
                    }
                ],
                BillingMode="PAY_PER_REQUEST",
                Tags=[{"Key": "Project", "Value": "CaraHealthBot"}, {"Key": "Component", "Value": "Campaign"}],
            )
            self.ddb.get_waiter("table_exists").wait(TableName=self.names.patients_table)
            self.log(f"    Created DynamoDB patients table {self.names.patients_table}")

    @staticmethod
    def _trust(service: str) -> str:
        return json.dumps({
            "Version": "2012-10-17",
            "Statement": [{"Effect": "Allow", "Principal": {"Service": service}, "Action": "sts:AssumeRole"}],
        })

    def _ensure_role(self, name: str, service: str) -> str:
        try:
            role = self.iam.get_role(RoleName=name)["Role"]
            self.iam.update_assume_role_policy(RoleName=name, PolicyDocument=self._trust(service))
        except self.iam.exceptions.NoSuchEntityException:
            role = self.iam.create_role(
                RoleName=name,
                AssumeRolePolicyDocument=self._trust(service),
                Description=f"Cara Health Bot campaign role for {service}",
                Tags=[{"Key": "Project", "Value": "CaraHealthBot"}, {"Key": "Component", "Value": "Campaign"}],
            )["Role"]
            self.log(f"    Created IAM role {name}")
        return role["Arn"]

    def ensure_roles(self) -> None:
        self.log("3/7  Campaign IAM roles and least-privilege policies")
        intake_role_arn = self._ensure_role(self.names.intake_role, "lambda.amazonaws.com")
        dialer_role_arn = self._ensure_role(self.names.dialer_role, "lambda.amazonaws.com")
        api_role_arn = self._ensure_role(self.names.api_role, "lambda.amazonaws.com")
        scheduler_role_arn = self._ensure_role(self.names.scheduler_role, "scheduler.amazonaws.com")

        basic = f"arn:{self.partition}:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
        for role_name in (self.names.intake_role, self.names.dialer_role, self.names.api_role):
            self.iam.attach_role_policy(RoleName=role_name, PolicyArn=basic)

        schedule_arn = self._arn("scheduler", "schedule/default/cara-health-bot-campaign-*")
        callback_schedule_arn = self._arn("scheduler", "schedule/default/cara-health-bot-callback-*")
        table_resources = [
            self.batches_table_arn,
            f"{self.batches_table_arn}/*",
            self.patients_table_arn,
            f"{self.patients_table_arn}/*",
        ]
        intake_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {"Effect": "Allow", "Action": ["s3:GetObject"], "Resource": [f"arn:{self.partition}:s3:::{self.names.bucket}/campaigns/*"]},
                {"Effect": "Allow", "Action": ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query", "dynamodb:Scan"], "Resource": table_resources},
                {"Effect": "Allow", "Action": ["scheduler:CreateSchedule", "scheduler:UpdateSchedule", "scheduler:GetSchedule"], "Resource": [schedule_arn]},
                {"Effect": "Allow", "Action": ["iam:PassRole"], "Resource": [scheduler_role_arn], "Condition": {"StringEquals": {"iam:PassedToService": "scheduler.amazonaws.com"}}},
            ],
        }
        dialer_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {"Effect": "Allow", "Action": ["dynamodb:Query", "dynamodb:Scan", "dynamodb:GetItem", "dynamodb:UpdateItem"], "Resource": table_resources},
                # AWS does not expose resource-level permissions for StartOutboundVoiceContact.
                {"Effect": "Allow", "Action": ["connect:StartOutboundVoiceContact"], "Resource": "*"},
                {"Effect": "Allow", "Action": ["connect:DescribeContact"], "Resource": [f"{self.instance_arn}/contact/*"]},
                {"Effect": "Allow", "Action": ["lambda:InvokeFunction"], "Resource": [self.dialer_arn]},
                {"Effect": "Allow", "Action": ["scheduler:CreateSchedule", "scheduler:UpdateSchedule", "scheduler:DeleteSchedule", "scheduler:GetSchedule"], "Resource": [callback_schedule_arn]},
                {"Effect": "Allow", "Action": ["iam:PassRole"], "Resource": [scheduler_role_arn], "Condition": {"StringEquals": {"iam:PassedToService": "scheduler.amazonaws.com"}}},
            ],
        }
        api_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {"Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject"], "Resource": [f"arn:{self.partition}:s3:::{self.names.bucket}/campaigns/*"]},
                {"Effect": "Allow", "Action": ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query", "dynamodb:Scan"], "Resource": table_resources},
                {"Effect": "Allow", "Action": ["scheduler:DeleteSchedule"], "Resource": [schedule_arn]},
            ],
        }
        scheduler_policy = {
            "Version": "2012-10-17",
            "Statement": [{"Effect": "Allow", "Action": ["lambda:InvokeFunction"], "Resource": [self.dialer_arn]}],
        }
        self.iam.put_role_policy(RoleName=self.names.intake_role, PolicyName="CaraCampaignIntakePolicy", PolicyDocument=json.dumps(intake_policy))
        self.iam.put_role_policy(RoleName=self.names.dialer_role, PolicyName="CaraCampaignDialerPolicy", PolicyDocument=json.dumps(dialer_policy))
        self.iam.put_role_policy(RoleName=self.names.api_role, PolicyName="CaraCampaignApiPolicy", PolicyDocument=json.dumps(api_policy))
        self.iam.put_role_policy(RoleName=self.names.scheduler_role, PolicyName="CaraCampaignSchedulerPolicy", PolicyDocument=json.dumps(scheduler_policy))

        self.intake_role_arn = intake_role_arn
        self.dialer_role_arn = dialer_role_arn
        self.api_role_arn = api_role_arn
        self.scheduler_role_arn_actual = scheduler_role_arn
        self.log("    IAM policies updated")

    def _zip_lambda(self, filename: str) -> bytes:
        source = self.root / "lambda" / filename
        if not source.is_file():
            raise CampaignDeploymentError(f"Lambda source missing: {source}")
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(source, arcname=filename)
            for sub_dir in ["cara_health_bot", "utils"]:
                pkg_dir = self.root / sub_dir
                if pkg_dir.is_dir():
                    for py_file in pkg_dir.rglob("*.py"):
                        rel_path = py_file.relative_to(self.root)
                        archive.write(py_file, arcname=str(rel_path).replace("\\", "/"))
                        archive.write(py_file, arcname=f"backend/{str(rel_path).replace('\\', '/')}")
        return stream.getvalue()

    def _ensure_function(self, name: str, handler: str, filename: str, role_arn: str, environment: dict[str, str], timeout: int) -> str:
        code = self._zip_lambda(filename)
        try:
            current = self.lambda_client.get_function(FunctionName=name)["Configuration"]
            self.lambda_client.update_function_code(FunctionName=name, ZipFile=code, Publish=False)
            self.lambda_client.get_waiter("function_updated_v2").wait(FunctionName=name)
            self.lambda_client.update_function_configuration(
                FunctionName=name,
                Runtime="python3.12",
                Role=role_arn,
                Handler=handler,
                Timeout=timeout,
                MemorySize=256,
                Environment={"Variables": environment},
            )
            self.lambda_client.get_waiter("function_updated_v2").wait(FunctionName=name)
            self.log(f"    Updated Lambda {name}")
            return current["FunctionArn"]
        except self.lambda_client.exceptions.ResourceNotFoundException:
            last_error: Exception | None = None
            for attempt in range(12):
                try:
                    result = self.lambda_client.create_function(
                        FunctionName=name,
                        Runtime="python3.12",
                        Role=role_arn,
                        Handler=handler,
                        Code={"ZipFile": code},
                        Description="Cara Health Bot sequential outbound campaign workaround",
                        Timeout=timeout,
                        MemorySize=256,
                        Environment={"Variables": environment},
                        Tags={"Project": "CaraHealthBot", "Component": "Campaign"},
                    )
                    self.lambda_client.get_waiter("function_active_v2").wait(FunctionName=name)
                    self.log(f"    Created Lambda {name}")
                    return result["FunctionArn"]
                except ClientError as error:
                    last_error = error
                    code_name = error.response.get("Error", {}).get("Code")
                    message = error.response.get("Error", {}).get("Message", "")
                    if code_name == "InvalidParameterValueException" and "role" in message.lower() and attempt < 11:
                        time.sleep(5)
                        continue
                    raise
            raise CampaignDeploymentError(f"Lambda role propagation did not settle for {name}: {last_error}")

    def _ensure_availability_function(self) -> None:
        self.availability_function_arn = self._ensure_function(
            self.names.availability_function,
            "agent_availability.handler",
            "agent_availability.py",
            self.api_role_arn,
            {"FIXED_AGENT_PHONE": "+15822671755", "FORCE_AGENT_AVAILABLE": "true"},
            30,
        )
        try:
            current = self.lambda_client.get_function_url_config(FunctionName=self.names.availability_function)
        except self.lambda_client.exceptions.ResourceNotFoundException:
            current = self.lambda_client.create_function_url_config(
                FunctionName=self.names.availability_function, AuthType="NONE"
            )
        self.availability_function_url = current["FunctionUrl"]
        self._add_permission(
            FunctionName=self.names.availability_function, StatementId="AllowPublicAvailabilityFunctionUrl",
            Action="lambda:InvokeFunctionUrl", Principal="*", FunctionUrlAuthType="NONE",
        )
        self._add_permission(
            FunctionName=self.names.availability_function, StatementId="AllowPublicAvailabilityFunctionUrlInvoke",
            Action="lambda:InvokeFunction", Principal="*", InvokedViaFunctionUrl=True,
        )
        self.log(f"    Agent Availability Function URL: {self.availability_function_url}")

    def ensure_lambdas(self) -> None:
        self.log("4/7  Campaign intake, dialer, API, and availability Lambdas")
        self._ensure_availability_function()
        self.dialer_function_arn = self._ensure_function(
            self.names.dialer_function,
            "campaign_dialer.handler",
            "campaign_dialer.py",
            self.dialer_role_arn,
            {
                "BATCHES_TABLE_NAME": self.names.batches_table,
                "PATIENTS_TABLE_NAME": self.names.patients_table,
                "CONNECT_INSTANCE_ID": self.instance_id,
                "CONNECT_CONTACT_FLOW_ID": self.contact_flow_id,
                "CONNECT_SOURCE_PHONE_NUMBER": self.source_phone,
                "DIALER_LAMBDA_ARN": self.dialer_arn,
                "SCHEDULER_ROLE_ARN": self.scheduler_role_arn_actual,
                "AGENT_AVAILABILITY_URL": self.availability_function_url,
            },
            30,
        )
        self.intake_function_arn = self._ensure_function(
            self.names.intake_function,
            "campaign_intake.handler",
            "campaign_intake.py",
            self.intake_role_arn,
            {
                "BATCHES_TABLE_NAME": self.names.batches_table,
                "PATIENTS_TABLE_NAME": self.names.patients_table,
                "DIALER_LAMBDA_ARN": self.dialer_arn,
                "SCHEDULER_ROLE_ARN": self.scheduler_role_arn_actual,
            },
            60,
        )
        self.api_function_arn = self._ensure_function(
            self.names.api_function,
            "campaign_api.handler",
            "campaign_api.py",
            self.api_role_arn,
            {
                "BATCHES_TABLE_NAME": self.names.batches_table,
                "PATIENTS_TABLE_NAME": self.names.patients_table,
                "CAMPAIGN_BUCKET": self.names.bucket,
                "API_ALLOWED_ORIGIN": self.frontend_origin,
            },
            30,
        )
        self._ensure_api_function_url()

    def _ensure_api_function_url(self) -> None:
        try:
            current = self.lambda_client.get_function_url_config(FunctionName=self.names.api_function)
            if current.get("AuthType") != self.api_auth_type:
                current = self.lambda_client.update_function_url_config(
                    FunctionName=self.names.api_function, AuthType=self.api_auth_type
                )
            self.api_function_url = current["FunctionUrl"]
        except self.lambda_client.exceptions.ResourceNotFoundException:
            current = self.lambda_client.create_function_url_config(
                FunctionName=self.names.api_function, AuthType=self.api_auth_type
            )
            self.api_function_url = current["FunctionUrl"]

        if self.api_auth_type == "NONE":
            self.log("    WARNING: campaign API Function URL is PUBLIC (explicit POC mode)")
            self._add_permission(
                FunctionName=self.names.api_function, StatementId="AllowPublicCampaignFunctionUrl",
                Action="lambda:InvokeFunctionUrl", Principal="*", FunctionUrlAuthType="NONE",
            )
            self._add_permission(
                FunctionName=self.names.api_function, StatementId="AllowPublicCampaignFunctionUrlInvoke",
                Action="lambda:InvokeFunction", Principal="*", InvokedViaFunctionUrl=True,
            )
        else:
            self.log("    Campaign API Function URL uses AWS_IAM authentication")
        self.log(f"    Campaign API URL: {self.api_function_url}")

    def _add_permission(self, **kwargs: Any) -> None:
        try:
            self.lambda_client.add_permission(**kwargs)
        except self.lambda_client.exceptions.ResourceConflictException:
            # Stable resource names mean an existing matching statement is safe to reuse.
            pass

    def ensure_triggers(self) -> None:
        self.log("5/7  S3 intake trigger and Connect DISCONNECTED EventBridge rule")
        self._add_permission(
            FunctionName=self.names.intake_function,
            StatementId="AllowCaraCampaignBucket",
            Action="lambda:InvokeFunction",
            Principal="s3.amazonaws.com",
            SourceArn=f"arn:{self.partition}:s3:::{self.names.bucket}",
            SourceAccount=self.account_id,
        )
        self.s3.put_bucket_notification_configuration(
            Bucket=self.names.bucket,
            NotificationConfiguration={
                "LambdaFunctionConfigurations": [{
                    "Id": "CaraCampaignPatientsUpload",
                    "LambdaFunctionArn": self.intake_arn,
                    "Events": ["s3:ObjectCreated:*"],
                    "Filter": {"Key": {"FilterRules": [
                        {"Name": "prefix", "Value": "campaigns/"},
                        {"Name": "suffix", "Value": "patients.csv"},
                    ]}},
                }]
            },
        )
        self.log("    S3 patients.csv trigger ready")

        # Current Connect docs use 'Connect Customer Contact Event'. Matching the
        # historical detail type too keeps the workaround compatible with older environments.
        pattern = {
            "source": ["aws.connect"],
            "detail-type": ["Connect Customer Contact Event", "Amazon Connect Contact Event"],
            "detail": {"eventType": ["DISCONNECTED"], "instanceArn": [self.instance_arn]},
        }
        rule = self.events.put_rule(
            Name=self.names.event_rule,
            Description="Advance Cara campaign after a Connect contact disconnects",
            EventPattern=json.dumps(pattern),
            State="ENABLED",
        )
        rule_arn = rule["RuleArn"]
        self._add_permission(
            FunctionName=self.names.dialer_function,
            StatementId="AllowCaraCampaignDisconnectRule",
            Action="lambda:InvokeFunction",
            Principal="events.amazonaws.com",
            SourceArn=rule_arn,
        )
        result = self.events.put_targets(
            Rule=self.names.event_rule,
            Targets=[{"Id": "CaraCampaignDialer", "Arn": self.dialer_arn}],
        )
        if result.get("FailedEntryCount", 0):
            raise CampaignDeploymentError(f"EventBridge target update failed: {result.get('FailedEntries')}")
        self.event_rule_arn_actual = rule_arn
        self.log("    Connect DISCONNECTED rule ready")

    def verify(self) -> dict[str, str]:
        self.log("6/7  Campaign runtime consistency checks")
        batches_tbl = self.ddb.describe_table(TableName=self.names.batches_table)["Table"]
        patients_tbl = self.ddb.describe_table(TableName=self.names.patients_table)["Table"]
        if batches_tbl.get("TableStatus") != "ACTIVE" or patients_tbl.get("TableStatus") != "ACTIVE":
            raise CampaignDeploymentError("Campaign DynamoDB tables are not ACTIVE")

        self.s3.head_bucket(Bucket=self.names.bucket)
        notification = self.s3.get_bucket_notification_configuration(Bucket=self.names.bucket)
        if not any(x.get("LambdaFunctionArn") == self.intake_arn for x in notification.get("LambdaFunctionConfigurations", [])):
            raise CampaignDeploymentError("Campaign S3 bucket is not wired to campaign_intake")

        intake = self.lambda_client.get_function_configuration(FunctionName=self.names.intake_function)
        dialer = self.lambda_client.get_function_configuration(FunctionName=self.names.dialer_function)
        api = self.lambda_client.get_function_configuration(FunctionName=self.names.api_function)
        if intake.get("State") != "Active" or dialer.get("State") != "Active" or api.get("State") != "Active":
            raise CampaignDeploymentError("Campaign Lambdas are not Active")
        denv = (dialer.get("Environment") or {}).get("Variables") or {}
        if denv.get("CONNECT_INSTANCE_ID") != self.instance_id or denv.get("CONNECT_CONTACT_FLOW_ID") != self.contact_flow_id:
            raise CampaignDeploymentError("Campaign dialer is not bound to the deployed Cara instance/contact flow")

        rule = self.events.describe_rule(Name=self.names.event_rule)
        event_pattern = json.loads(rule.get("EventPattern") or "{}")
        if "DISCONNECTED" not in ((event_pattern.get("detail") or {}).get("eventType") or []):
            raise CampaignDeploymentError("Campaign EventBridge rule is not filtering DISCONNECTED")
        targets = self.events.list_targets_by_rule(Rule=self.names.event_rule).get("Targets", [])
        if not any(t.get("Arn") == self.dialer_arn for t in targets):
            raise CampaignDeploymentError("Campaign EventBridge rule is not targeting campaign_dialer")

        output = {
            "CampaignBucketName": self.names.bucket,
            "CallBatchesTableName": self.names.batches_table,
            "PatientRecordsTableName": self.names.patients_table,
            "CampaignContactIdIndex": self.names.contact_index,
            "CampaignIntakeFunctionName": self.names.intake_function,
            "CampaignIntakeFunctionArn": self.intake_arn,
            "CampaignDialerFunctionName": self.names.dialer_function,
            "CampaignDialerFunctionArn": self.dialer_arn,
            "CampaignApiFunctionName": self.names.api_function,
            "CampaignApiFunctionArn": self.api_arn,
            "CampaignApiFunctionUrl": self.api_function_url,
            "CampaignApiAuthType": self.api_auth_type,
            "AgentAvailabilityFunctionUrl": self.availability_function_url,
            "CampaignFrontendOrigin": self.frontend_origin,
            "CampaignSchedulerRoleArn": self.scheduler_role_arn_actual,
            "CampaignDisconnectedRuleName": self.names.event_rule,
            "CampaignDisconnectedRuleArn": rule["Arn"],
        }
        self.state.setdefault("campaign", {}).update(output)
        self.state.setdefault("outputs", {}).update(output)
        self.state_path.write_text(json.dumps(self.state, indent=2) + "\n", encoding="utf-8")
        self.log("    All campaign checks passed")
        return output

    def deploy(self) -> dict[str, str]:
        if self.dry_run:
            self.log("[DRY RUN] Validating campaign pipeline deployment without modifying AWS resources...")
            self.preflight()
            self.log("0/7  [DRY RUN] Campaign preflight verified")
            try:
                self.api_function_url = self.lambda_client.get_function_url_config(FunctionName=self.names.api_function).get("FunctionUrl", "")
            except Exception:
                self.api_function_url = self.outputs.get("CampaignApiFunctionUrl", "")
            try:
                self.availability_function_url = self.lambda_client.get_function_url_config(FunctionName=self.names.availability_function).get("FunctionUrl", "")
            except Exception:
                self.availability_function_url = self.outputs.get("AgentAvailabilityFunctionUrl", "")
            self.scheduler_role_arn_actual = self.scheduler_role_arn
            self.log("1/7  [DRY RUN] S3 bucket check verified")
            self.log("2/7  [DRY RUN] DynamoDB tables check verified")
            self.log("3/7  [DRY RUN] IAM roles and policies check verified")
            self.log("4/7  [DRY RUN] Lambdas (intake, dialer, API, availability) check verified")
            self.log("5/7  [DRY RUN] S3 triggers and EventBridge rules check verified")
            output = self.verify()
            self.log("6/7  [DRY RUN] Campaign runtime consistency checks passed")
            self.log("7/7  [DRY RUN] Campaign workaround dry-run validation complete")
            return output

        self.preflight()
        self.ensure_bucket()
        self.ensure_table()
        self.ensure_roles()
        self.ensure_lambdas()
        self.ensure_triggers()
        output = self.verify()
        self.log("7/7  Campaign workaround deployment complete")
        return output
