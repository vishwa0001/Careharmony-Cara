# Lessons and regressions

The deployment contains regression checks for failures encountered while building Cara Health Bot:

- published QinConnect intent must use the same Q assistant as Connect
- Live Lex alias must explicitly enable `en_US`
- fresh Nova 2 Sonic versioning must tolerate eventual consistency
- Q prompt template variables may appear only once
- Connect logging block must not contain an unsupported error transition
- Lex runtime IAM is scoped to the active Q assistant/session resources
- Q assistant quota fallback only reuses explicitly approved assistants
- identity confirmation is no longer prompt/tool driven
- identity is completed by a separate traditional Lex V2 gate before the Q session exists
- the identity gate allows one clarification only
- all identity, availability, and coaching Lex Live aliases may keep text conversation logs for debugging, but transcript.py does not depend on them
- transcript source of truth is the Connect stereo automated-interaction recording
- transcript parser accepts Connect bare bucket/key, s3://, virtual-hosted HTTPS, and path-style HTTPS locations
- failed Transcribe jobs are deleted/restarted instead of poisoning repeated transcript attempts


## v1.6.3 — customer channel was silent

The automated-interaction recording block used `RecordedParticipants: []` together with `IVRRecordingBehavior: Enabled`. AWS flow-language documentation defines an empty participant list as recording disabled for participants. In live testing this produced a valid stereo IVR WAV with system prompts on `ch_0` but a silent customer channel on `ch_1`. The flow now explicitly sets `RecordedParticipants` to `Agent` and `Customer` while keeping IVR recording enabled. Deployment verification and offline tests enforce this invariant.

## v1.6.4 — route identity intents directly from Lex actions

Live Connect testing proved that successful `ConnectParticipantWithLexBot` actions must branch directly on the returned Lex intent. The previous flow sent both identity attempts to separate `Compare` actions reading `$.Lex.IntentName`; in live calls this caused `IdentityConfirmed` and `IdentityDenied` to fall through incorrectly. v1.6.4 removes those Compare actions and puts the intent conditions directly on each identity Lex action.


## v1.7.0 — verified identity transfers directly to a human

Live testing confirmed the desired production path is identity confirmation followed immediately by a transfer notice and `CaraHealthBotQueue` transfer. The source now routes `IdentityConfirmed` directly to `MessageParticipant -> UpdateContactTargetQueue -> TransferContactToQueue`; it no longer sends verified callers into the Nova/Q coaching path. The queue ARN is resolved by queue name during deployment so account-specific queue IDs are never hard-coded into the package.

## v1.8.0 — third-party availability is a separate deterministic branch

Relative/third-party responses are no longer grouped into `IdentityDenied`. The identity bot now returns `ThirdPartyDetected`, which routes to a separate traditional Lex V2 availability bot. Separating the bots avoids intent conflicts such as bare `yes` meaning ambiguous identity in one phase but available-now in another. The availability bot has `TargetAvailableNow`, `TargetUnavailable`, `AvailabilityUnknown`, and fallback intents. `TargetUnavailable` requires `callbackDate` (`AMAZON.Date`) and `callbackTime` (`AMAZON.Time`); Connect persists those slots as contact attributes before disconnecting. If the target is available, the third party is asked to pass the phone and a fresh identity check runs before human transfer. No third party can reach the human queue without the target subsequently confirming identity.


## v1.9.0 — one-command human-agent provisioning and identity confidence hardening

Deployment now provisions/reuses the configured Connect human agent instead of requiring manual `list-routing-profiles`, `list-security-profiles`, `create-user`, and queue-assignment commands. It creates/reuses the Cara-owned `CaraHealthBotRoutingProfile`, `CaraHealthBotHumanAgent` security profile, and `CaraHealthBotQueue`, attaches the queue for `VOICE`, creates/reuses `caraagent`, configures `SOFT_PHONE`, and prints the direct Agent Workspace URL. `CARA_AGENT_PASSWORD` is required only for first creation and is never persisted.

A live identity test also showed the correctly transcribed question “may I know whom I am talking with” being classified as `IdentityConfirmed` at 0.78 confidence. v1.9.0 raises the identity locale NLU threshold to 0.90 and explicitly trains common identity questions as `IdentityAmbiguous`, preventing that observed false-positive path from reaching human transfer.

## v3.2.2 — Wrong-number must exist in availability NLU

Live call regression: after an ambiguous identity turn, a caller said "No, wrong number" and the identity bot returned FallbackIntent. The privacy-minimal availability bot then classified a longer explicit wrong-number statement as SafetyMedical because that bot had safety intents but no WrongNumber intent.

Fix: strengthen WrongNumber utterances in the identity bot, add the same WrongNumber intent to the availability bot, and route WrongNumber from either availability attempt to the existing identityResult=Denied wrong-number exit. Genuine mixed safety statements still route to SafetyMedical/SafetyBehavioral.

## v3.2.3 — TransferParticipantToThirdParty required parameters

Amazon Connect `UpdateContactFlowContent` failed during deployment with `InvalidContactFlowException` because action `Actions[61]` (`TransferParticipantToThirdParty`) was missing required parameters:
- `ThirdPartyConnectionTimeLimitSeconds`: string duration (e.g. `"60"`)
- `ContinueFlowExecution`: string boolean (`"False"`)

Fix: Added `ThirdPartyConnectionTimeLimitSeconds: "60"` and `ContinueFlowExecution: "False"` to action `e1000000-0000-4000-8000-000000000004` parameters in `cara-health-bot-flow.json` and updated unit tests.

## v3.2.4 — Compare block condition evaluation operands cannot be empty strings

Amazon Connect `UpdateContactFlowContent` failed during deployment with `InvalidContactFlowException: Invalid branch. Path: 59.Evaluate` because action index 59 (`e1000000-0000-4000-8000-000000000002`, `Compare`) contained an explicit condition operand set to an empty string `[""]`.

Fix: Removed the invalid `Operands: [""]` condition block from `e1000000-0000-4000-8000-000000000002` in `cara-health-bot-flow.json`. When `$.Attributes.humanAgentPhoneNumber` is valid/present, `Compare` follows `NextAction` to the courtesy prompt (`e1000000-0000-4000-8000-000000000003`); when missing or unassigned, it triggers `NoMatchingCondition` / `NoMatchingError` transitions directly to the failure prompt (`e1000000-0000-4000-8000-000000000005`). Updated unit tests accordingly.

## v3.2.5 — Outbound CallerID setting for third-party handoff transfer

Amazon Connect flow schema (v2019-10-30) does not accept `CallerIdNumber` as a parameter inside `TransferParticipantToThirdParty` directly (`Invalid Action property name`). Setting outbound caller ID requires an `UpdateContactAttributes` action block (`e1000000-0000-4000-8000-000000000006`) prior to `TransferParticipantToThirdParty`, setting `"CallerIdNumber": "+18775205924"` (`SourcePhoneNumber` from `deployment-state.json` outputs).

## v3.2.6 — Flow-level safety net for medical emergencies in coaching phase

Root cause (contactId 96db70fb-b9ef-4477-ba71-4280001bb0ea): In the coaching phase (`ConnectParticipantWithLexBot` action `55555555-5555-4555-8555-555555555555`), acute medical emergency statements were routed solely through Amazon Q in Connect / Nova Lite. When the model generated conversational spoken text rather than executing `EndConversation(endReason="safety_medical")`, Lex remained in `dialogAction: Delegate`, leaving the caller stranded in ConnectParticipantWithLexBot across silence timeouts and triggering foundation model crisis hotline messages.

Fix:
1. Contact Flow: Added explicit `SafetyMedical` and `SafetyBehavioral` condition transitions on coaching block `55555555-5555-4555-8555-555555555555` routing directly to `d0000000-0000-4000-8000-000000000001` (medical safety exit) and `d0000000-0000-4000-8000-000000000002` (behavioral safety exit), which play static prompts and immediately execute a hard `DisconnectParticipant`.
2. Lex Coaching Bot: Upsert `SafetyMedical` and `SafetyBehavioral` intents on the main coaching bot (`4S3WG7D9ZQ`) alongside `AmazonQinConnect`, providing deterministic NLU classification for 180+ acute emergency utterances independent of foundation model tool-calling.
3. AI Prompt: Removed the pre-filled `<message>` tag in the assistant role of `prompts/life-coach.yaml` to prevent forcing text-generation mode over tool invocation on safety turns.




