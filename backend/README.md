# Cara Health Bot

> **Standalone package — v3.1.2.** Cara Health Bot is designed to deploy into a fresh AWS account without any Talking Bot files, resource IDs, or shared Amazon Q assistant. Reruns are idempotent for Cara-owned resources; same-name resources that are not tagged as Cara Health Bot are treated as collisions instead of being silently reused.

AWS CloudShell deployment for an outbound identity-gated conversational voice bot using Amazon Connect, Amazon Lex V2, Amazon Q in Connect, and Nova 2 Sonic.

## Runtime behavior

1. Amazon Connect places the outbound call and starts stereo IVR/call recording in a new Cara-specific S3 bucket.
2. `cara-health-bot-identity` performs the privacy-minimal identity/recipient gate.
3. Safety intents have highest priority and immediately use the configured medical or behavioral safety response, then end.
4. Confirmed customers enter Cara's conversational layer for questions, objections, callbacks, refusals, and natural movement toward a human specialist.
5. Clear refusal ends persuasion. Unknown or business-specific questions use configured fallback responses instead of invented facts.
6. `ThirdPartyDetected` asks only whether the intended customer is available; `PatientUnavailable` moves directly toward callback timing.
7. If the intended customer comes to the phone, identity is checked again before Cara continues.
8. `TRANSFER_READY` context is preserved across normal questions so Cara answers and resumes the already-agreed handoff without restarting the conversation.

The identity gate is conversational confirmation, not strong authentication such as OTP/DOB verification.

## Human agent provisioning

`deploy.sh` creates/reuses Cara Health Bot-owned human-transfer resources: `CaraHealthBotQueue`, `CaraHealthBotRoutingProfile`, and `CaraHealthBotHumanAgent`. It associates the queue for `VOICE`, creates/reuses `caraagent`, and configures `SOFT_PHONE`. Existing Cara resources are updated idempotently; the deployment does not depend on `BasicQueue`, `Basic Routing Profile`, or the built-in `Agent` profile.

For the first creation of `caraagent`, provide `CARA_AGENT_PASSWORD` as an environment variable. The password is **not** written to `config.json`, `deployment-state.json`, or deployment output. On later deploys, if the user already exists, the password is not required.

The agent still needs to sign in to Agent Workspace and set status to `Available`; that is a live agent-session action, not infrastructure provisioning.

## Standalone fresh-account deployment

No Talking Bot directory, deployment state, assistant, queue, user, or other legacy resource is required. Upload this ZIP as `cara-health-bot.zip`, then run:

```bash
cd ~ && \
rm -rf cara-health-bot && \
unzip -oq cara-health-bot.zip && \
cd cara-health-bot && \
chmod +x deploy.sh cleanup.sh && \
CARA_AGENT_PASSWORD='<your-agent-password>' ./deploy.sh
```

On a fresh account, the deployer creates Cara-owned resources including:

```text
Amazon Connect instance:    cara-health-bot-<account-suffix>
Amazon Q assistant:         CaraHealthBotAssistant
Q prompt:                   CaraHealthBotPrompt
Q orchestration agent:      cara-health-bot-orchestrator
Identity Lex bot:           cara-health-bot-identity
Availability Lex bot:       cara-health-bot-availability
Conversation Lex bot:       cara-health-bot-nova-2-sonic
Lambda:                     cara-health-bot-session-context
Human queue:                CaraHealthBotQueue
Routing profile:            CaraHealthBotRoutingProfile
Human security profile:     CaraHealthBotHumanAgent
Human username:             caraagent
Recording bucket:           cara-health-bot-recordings-<account>-us-east-1
Contact flow:               CaraHealthBotNova2Sonic
```

The deployment also searches for and claims an available US source number for the new Connect instance. If the account cannot create the dedicated Q assistant because of service quota, deployment fails with a clear error and does **not** reuse another project's assistant.

`deployment-state.json` is written after deployment and is used by `cleanup.sh` to remove only Cara Health Bot-owned resources later.

## Start a call

```bash
python3 scripts/call.py "+18148316822" --customer-name "John" --i-confirm-consent
```

Use straight quotes, not smart quotes.

## Expected third-party examples

```text
Cara: Hi, may I speak with John?
Relative: This is his wife. He isn't here right now.
Cara: Thanks. I'm trying to reach John directly. Is John available to come to the phone?
Relative: No.
Cara/Lex: What day would be better to reach them?
Relative: Tomorrow.
Cara/Lex: What time would be better to reach them?
Relative: After six.
Cara: Thank you. I'll note that as a better time to reach them. Have a good day.
```

If John is present:

```text
Relative: Yes, he's here.
Cara: Thanks. Please pass the phone to John.
Cara: Hi. May I confirm I'm speaking with John?
John: Yes, this is John.
Cara: Thanks, John. I'm Cara, an automated assistant. I can help with the first part of this call and connect you with a human specialist when appropriate.
```

## Callback attributes

For an unavailable target, the contact record stores:

```text
recipientType=THIRD_PARTY
identityConfirmed=false
targetAvailableNow=false
callbackDate=<Lex AMAZON.Date normalized value>
callbackTime=<Lex AMAZON.Time normalized value>
identityPolicyVersion=v5-confidence-hardened-third-party
```

For a third party who passes the phone and the target then confirms:

```text
recipientType=THIRD_PARTY_THEN_TARGET
identityConfirmed=true
targetAvailableNow=true
identityPolicyVersion=v5-confidence-hardened-third-party
```

## Transcript

```bash
python3 scripts/transcript.py CONTACT_ID
```

The transcript helper uses the Connect stereo automated/IVR recording: system audio on one channel and customer audio on the other.

## Debug

```bash
python3 scripts/logs.py CONTACT_ID
```

See `ARCHITECTURE.md` for the current flow.

## Outbound campaign add-on (v3.3.0)

Cara includes an optional sequential outbound campaign workaround deployed with the same boto3/AWS SDK model as the base project. No CDK bootstrap, ECR repository, or CDKToolkit stack is required. Deploy the normal Cara stack first with `./deploy.sh`, then deploy only the campaign-side S3/DynamoDB/Lambda/Scheduler/EventBridge resources with `./deploy-campaign.sh`. The campaign deployer reuses the existing Connect instance, published contact flow, and source phone number from `deployment-state.json`. See `CAMPAIGN.md`.

## Campaign frontend integration (v3.4.0)

The campaign workaround now includes a unified `cara-health-bot-campaign-api` Lambda that matches the supplied React frontend. See `CAMPAIGN.md` for the `/uploads`, `/campaigns`, cancel/reschedule, rich CSV, timezone, and security contract. Campaign API Function URLs default to `AWS_IAM`; public `NONE` mode is explicit POC-only opt-in.
