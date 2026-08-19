# Cara Health Bot v1.9 architecture

```text
Outbound API call
    |
    v
Amazon Connect
    |
    +--> flow logging + stereo IVR/call recording
    |
    v
cara-health-bot-identity (Lex V2, 0.90 NLU confidence threshold)
    |
    +-- IdentityConfirmed ------------------------------+
    |                                                   |
    |                                                   v
    |                                       persist identityConfirmed=true
    |                                                   |
    |                                                   v
    |                                        transfer notice -> queue -> agent
    |
    +-- IdentityDenied / wrong number ---> goodbye -> disconnect
    |
    +-- ambiguous/fallback attempt 1 ---> one clarification
    |                                      |
    |                                      +-- confirmed -> human transfer
    |                                      +-- third party -> availability
    |                                      +-- otherwise -> goodbye
    |
    +-- ThirdPartyDetected
             |
             v
      cara-health-bot-availability (separate deterministic Lex V2)
             |
             +-- TargetAvailableNow
             |       |
             |       v
             |   persist THIRD_PARTY_THEN_TARGET
             |       |
             |       v
             |   "Please pass the phone to <name>."
             |       |
             |       v
             |   fresh identity check (up to 2 attempts)
             |       |
             |       +-- IdentityConfirmed -> human transfer
             |       +-- otherwise -> goodbye
             |
             +-- TargetUnavailable
             |       |
             |       +-- callbackDate : AMAZON.Date (required)
             |       +-- callbackTime : AMAZON.Time (required)
             |       |
             |       v
             |   save callback attributes -> thank relative -> disconnect
             |
             +-- AvailabilityUnknown / repeated fallback
                     |
                     v
                 generic goodbye -> disconnect
```

## Why availability uses a separate Lex bot

A bare `yes` is deliberately ambiguous during identity confirmation, but in an availability question a `yes` should mean the intended customer is available now. Keeping availability in its own Lex bot prevents those meanings from competing inside one NLU model.

## Privacy boundary

The relative/third-party branch is intentionally narrow. It does not disclose why the business is calling, any account or case details, or any sensitive information. It only asks whether the named intended customer can come to the phone and, if unavailable, a better callback day and time.

## Human transfer

The flow resolves the STANDARD Connect queue configured by `humanTransferQueueName` and substitutes its ARN into `UpdateContactTargetQueue`. `TransferContactToQueue` is reachable only after `IdentityConfirmed` for the actual target, including after a third party passes the phone.

Deployment creates/reuses `CaraHealthBotQueue`, `CaraHealthBotRoutingProfile`, and `CaraHealthBotHumanAgent`, associates the queue for `VOICE`, and creates/reuses `caraagent` with `SOFT_PHONE`. The password is consumed from `CARA_AGENT_PASSWORD` only on first creation and is never persisted in project state.

## Identity confidence hardening

The identity Lex locale uses a 0.90 NLU confidence threshold and explicitly trains question-like responses such as “may I know whom I am talking with?” as `IdentityAmbiguous`. The previously observed 0.78 false-positive `IdentityConfirmed` therefore falls below the locale threshold. This is still conversational identity confirmation, not strong authentication.

## Recording/transcript

The flow records Agent + Customer participants and enables IVR recording. `scripts/transcript.py` uses the single Connect stereo recording and Amazon Transcribe to print `Cara:` and `Customer:` turns.
