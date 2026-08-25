from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")


@dataclass(frozen=True)
class ProjectConfig:
    project_name: str
    display_name: str
    region: str
    connect_instance_alias_base: str
    assistant_name: str
    prompt_name: str
    agent_name: str
    security_profile_name: str
    lex_runtime_role_name: str
    lex_runtime_policy_name: str
    identity_bot_name: str
    identity_bot_alias_name: str
    identity_lex_runtime_role_name: str
    identity_lex_runtime_policy_name: str
    availability_bot_name: str
    availability_bot_alias_name: str
    session_context_lambda_name: str
    session_context_lambda_role_name: str
    session_context_lambda_policy_name: str
    bot_name: str
    bot_alias_name: str
    flow_name: str
    locale: str
    voice_id: str
    orchestration_model_id: str
    speech_model_id: str
    phone_country_code: str
    phone_number_type: str
    allowed_destination_prefixes: tuple[str, ...]
    greeting: str
    fallback_message: str
    human_transfer_queue_name: str
    identity_success_transfer_message: str
    human_agent_username: str
    human_agent_first_name: str
    human_agent_last_name: str
    human_agent_routing_profile_name: str
    human_agent_security_profile_name: str
    human_agent_after_contact_work_seconds: int
    identity_nlu_confidence_threshold: float
    cara_behavior: dict[str, Any]
    root: Path

    @property
    def prompt_path(self) -> Path:
        return self.root / "prompts" / "life-coach.yaml"

    @property
    def flow_path(self) -> Path:
        return self.root / "contact-flows" / "cara-health-bot-flow.json"

    @property
    def state_path(self) -> Path:
        return self.root / "deployment-state.json"

    def instance_alias(self, account_id: str) -> str:
        # Connect instance aliases become part of the access URL. A deterministic
        # account suffix avoids collisions while keeping reruns idempotent.
        return f"{self.connect_instance_alias_base}-{account_id[-6:]}"

    def log_group(self, account_id: str) -> str:
        return f"/aws/connect/{self.instance_alias(account_id)}"

    def lex_conversation_log_group(self, account_id: str) -> str:
        return f"/aws/lex/{self.connect_instance_alias_base}-conversations-{account_id[-6:]}"

    def recording_bucket(self, account_id: str) -> str:
        return f"{self.connect_instance_alias_base}-recordings-{account_id}-{self.region}"

    @property
    def recording_prefix(self) -> str:
        return "connect-recordings"

    @property
    def transcript_prefix(self) -> str:
        return "transcribe-output"


def _required(data: dict[str, Any], key: str) -> Any:
    value = data.get(key)
    if value is None or value == "":
        raise ValueError(f"config.json is missing required value: {key}")
    return value


def load_config(path: str | Path | None = None) -> ProjectConfig:
    root = Path(path).resolve().parent if path else Path(__file__).resolve().parents[1]
    config_path = Path(path).resolve() if path else root / "config.json"
    data = json.loads(config_path.read_text(encoding="utf-8"))
    cfg = ProjectConfig(
        project_name=str(_required(data, "projectName")),
        display_name=str(_required(data, "displayName")),
        region=str(_required(data, "region")),
        connect_instance_alias_base=str(_required(data, "connectInstanceAliasBase")),
        assistant_name=str(_required(data, "assistantName")),
        prompt_name=str(_required(data, "promptName")),
        agent_name=str(_required(data, "agentName")),
        security_profile_name=str(_required(data, "securityProfileName")),
        lex_runtime_role_name=str(_required(data, "lexRuntimeRoleName")),
        lex_runtime_policy_name=str(_required(data, "lexRuntimePolicyName")),
        identity_bot_name=str(_required(data, "identityBotName")),
        identity_bot_alias_name=str(_required(data, "identityBotAliasName")),
        identity_lex_runtime_role_name=str(_required(data, "identityLexRuntimeRoleName")),
        identity_lex_runtime_policy_name=str(_required(data, "identityLexRuntimePolicyName")),
        availability_bot_name=str(_required(data, "availabilityBotName")),
        availability_bot_alias_name=str(_required(data, "availabilityBotAliasName")),
        session_context_lambda_name=str(_required(data, "sessionContextLambdaName")),
        session_context_lambda_role_name=str(_required(data, "sessionContextLambdaRoleName")),
        session_context_lambda_policy_name=str(_required(data, "sessionContextLambdaPolicyName")),
        bot_name=str(_required(data, "botName")),
        bot_alias_name=str(_required(data, "botAliasName")),
        flow_name=str(_required(data, "flowName")),
        locale=str(_required(data, "locale")),
        voice_id=str(_required(data, "voiceId")),
        orchestration_model_id=str(_required(data, "orchestrationModelId")),
        speech_model_id=str(_required(data, "speechModelId")),
        phone_country_code=str(_required(data, "phoneCountryCode")),
        phone_number_type=str(_required(data, "phoneNumberType")),
        allowed_destination_prefixes=tuple(str(x) for x in _required(data, "allowedDestinationPrefixes")),
        greeting=str(_required(data, "greeting")),
        fallback_message=str(_required(data, "fallbackMessage")),
        human_transfer_queue_name=str(_required(data, "humanTransferQueueName")),
        identity_success_transfer_message=str(_required(data, "identitySuccessTransferMessage")),
        human_agent_username=str(_required(data, "humanAgentUsername")),
        human_agent_first_name=str(_required(data, "humanAgentFirstName")),
        human_agent_last_name=str(_required(data, "humanAgentLastName")),
        human_agent_routing_profile_name=str(_required(data, "humanAgentRoutingProfileName")),
        human_agent_security_profile_name=str(_required(data, "humanAgentSecurityProfileName")),
        human_agent_after_contact_work_seconds=int(_required(data, "humanAgentAfterContactWorkSeconds")),
        identity_nlu_confidence_threshold=float(_required(data, "identityNluConfidenceThreshold")),
        cara_behavior=dict(_required(data, "caraBehavior")),
        root=root,
    )
    validate_config(cfg)
    return cfg


def validate_config(cfg: ProjectConfig) -> None:
    errors: list[str] = []
    if cfg.region != "us-east-1":
        errors.append("this tested Nova 2 Sonic package currently requires region us-east-1")
    if cfg.locale != "en_US":
        errors.append("this tested package currently requires locale en_US")
    if cfg.phone_country_code != "US":
        errors.append("this tested package currently auto-claims a US phone number")
    if cfg.phone_number_type not in {"TOLL_FREE", "DID"}:
        errors.append("phoneNumberType must be TOLL_FREE or DID")
    if not cfg.allowed_destination_prefixes:
        errors.append("allowedDestinationPrefixes must not be empty")
    for prefix in cfg.allowed_destination_prefixes:
        if not prefix.startswith("+") or not prefix[1:].isdigit():
            errors.append(f"invalid destination prefix {prefix!r}")
    if not cfg.prompt_path.is_file():
        errors.append(f"prompt file not found: {cfg.prompt_path}")
    if not cfg.flow_path.is_file():
        errors.append(f"flow file not found: {cfg.flow_path}")
    if not cfg.greeting.strip():
        errors.append("greeting must not be empty")
    if not cfg.availability_bot_name.strip():
        errors.append("availabilityBotName must not be empty")
    if not cfg.availability_bot_alias_name.strip():
        errors.append("availabilityBotAliasName must not be empty")
    if not cfg.human_transfer_queue_name.strip():
        errors.append("humanTransferQueueName must not be empty")
    if not cfg.identity_success_transfer_message.strip():
        errors.append("identitySuccessTransferMessage must not be empty")
    if not cfg.human_agent_username.strip():
        errors.append("humanAgentUsername must not be empty")
    if len(cfg.human_agent_username) > 20:
        errors.append("humanAgentUsername must be at most 20 characters for CONNECT_MANAGED instances")
    if not cfg.human_agent_first_name.strip() or not cfg.human_agent_last_name.strip():
        errors.append("humanAgentFirstName and humanAgentLastName must not be empty")
    if not cfg.human_agent_routing_profile_name.strip():
        errors.append("humanAgentRoutingProfileName must not be empty")
    if not cfg.human_agent_security_profile_name.strip():
        errors.append("humanAgentSecurityProfileName must not be empty")
    if not (0 <= cfg.human_agent_after_contact_work_seconds <= 99999999):
        errors.append("humanAgentAfterContactWorkSeconds is out of range")
    if not (0.0 <= cfg.identity_nlu_confidence_threshold <= 1.0):
        errors.append("identityNluConfidenceThreshold must be between 0 and 1")

    cara = cfg.cara_behavior
    required_cara_keys = {
        "agentName", "practiceName", "openingMessage", "transferMessage",
        "fallbackMessage", "preIdentityQuestionResponse", "questionResponses",
        "objectionResponses", "callbackResponses", "otherPersonResponse",
        "representativeResponse", "patientUnavailableResponse",
        "wrongNumberResponse", "deceasedResponse", "refusalResponse",
        "safetyMedicalResponse", "safetyBehavioralResponse",
        "respectfulClosingMessage",
    }
    missing_cara = sorted(key for key in required_cara_keys if key not in cara)
    if missing_cara:
        errors.append("caraBehavior is missing required keys: " + ", ".join(missing_cara))
    if not isinstance(cara.get("questionResponses"), dict):
        errors.append("caraBehavior.questionResponses must be an object")
    else:
        for category, response in cara["questionResponses"].items():
            if not isinstance(response, dict) or not {"short", "detailed"} <= set(response):
                errors.append(
                    f"caraBehavior.questionResponses.{category} must contain short and detailed"
                )
    if not isinstance(cara.get("objectionResponses"), dict) or not cara.get("objectionResponses"):
        errors.append("caraBehavior.objectionResponses must be a non-empty object")
    callback = cara.get("callbackResponses")
    if not isinstance(callback, dict) or not {"specificAcknowledgement", "unspecified", "endMessage"} <= set(callback):
        errors.append(
            "caraBehavior.callbackResponses must contain specificAcknowledgement, unspecified, and endMessage"
        )
    if errors:
        raise ValueError("Invalid configuration:\n- " + "\n- ".join(errors))
