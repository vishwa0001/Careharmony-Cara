# Cara Health Bot campaign workaround

This add-on reuses the already-deployed Cara Amazon Connect instance, published contact flow, source phone number, Lex bots, Q assistant, session-context Lambda, transfer queue, and safety behavior. It does not create another Connect instance or replace Cara's conversational flow.

## End-to-end flow

Frontend -> `POST /uploads` -> backend writes `config.json` and returns a presigned S3 PUT URL -> browser uploads `patients.csv` -> S3 triggers `campaign_intake` -> DynamoDB -> one EventBridge Scheduler entry -> `campaign_dialer` -> `StartOutboundVoiceContact` -> existing Cara flow -> `identityResult` Connect contact attribute -> Connect `DISCONNECTED` event -> EventBridge -> dialer -> `DescribeContact` -> disposition -> next patient.

## Frontend API contract

The `cara-health-bot-campaign-api` Lambda supports:

- `POST /uploads` - initialize a campaign and return a presigned S3 upload URL.
- `GET /campaigns` - list campaign records.
- `GET /campaigns/{campaignId}` - campaign detail plus outcome summary.
- `GET /campaigns/{campaignId}/patients` - patient-level status/result rows with only the last four phone digits returned.
- `POST /campaigns/{campaignId}/cancel` - cancel only before the campaign starts.
- `POST /campaigns/{campaignId}/reschedule` - create a new linked campaign from a cancelled campaign.

The upload request accepts the frontend's wall-clock schedule and IANA timezone separately. The backend converts that pair to UTC using `zoneinfo`, so `2026-08-25T10:00` + `America/New_York` is interpreted as 10:00 AM New York time, not 10:00 UTC.

## CSV schema

The server validates the same richer Cara CSV contract as the frontend:

```csv
empi,first_name,last_name,gender,phone_number,practice_name,practice_callback_number
TESTPT-0001,John,Doe,Male,+18148316822,Sample Practice,+18145550100
```

Required headers:

- `empi`
- `first_name`
- `last_name`
- `gender`
- `phone_number`
- `practice_name`
- `practice_callback_number`

The intake Lambda rejects duplicate EMPI values, duplicate phone numbers, empty required fields, and invalid phone/callback formats. It avoids logging names and phone numbers.

## DynamoDB model

Table: `cara-health-bot-campaign-state`

- PK: `campaignId`
- SK: `recordKey`
- campaign row: `recordKey=CAMPAIGN`
- patient row: `recordKey=PATIENT#<sequence>#<patientId>`
- GSI: `contactId-index` on `contactId`

Campaign states include `UPLOAD_PENDING`, `PENDING`, `RUNNING`, `COMPLETED`, `VALIDATION_FAILED`, and `CANCELLED`.
Patient states include `PENDING`, `IN_PROGRESS`, `COMPLETED`, and `CALL_SETUP_FAILED`.

## identityResult and disposition

The existing Cara flow persists the Amazon Connect contact attribute:

- `Confirmed` -> `Identity Confirmed`
- `Denied` -> `Wrong Person / Identity Denied`
- `Ambiguous` -> `Identity Unclear`
- missing -> `Unknown / Undetermined`
- recognized telecom non-connection -> `No Answer / Not Connected`

Connection outcome and identity outcome remain separate.

## Sequential/idempotent dialing

- Only one patient can atomically transition `PENDING -> IN_PROGRESS`.
- A duplicate campaign-start event cannot dial a second patient while one is already in progress.
- Finalization is conditional `IN_PROGRESS -> COMPLETED`.
- Duplicate DISCONNECTED events are ignored after finalization.
- Contact lookup uses `contactId-index`, not a table scan.
- Setup failures transition to `CALL_SETUP_FAILED` and the dialer continues with a bounded loop/asynchronous continuation.

## API security

The campaign Function URL defaults to `AWS_IAM` authentication. AWS IAM-protected Function URLs require authenticated/signed callers. For a production browser application, put an authenticated API layer (for example API Gateway/Cognito or an existing application backend) in front of this Lambda or sign requests with short-lived user credentials.

For a short-lived isolated POC only, public Function URL mode is explicit opt-in:

```bash
export CARA_CAMPAIGN_API_AUTH_TYPE=NONE
export CARA_CAMPAIGN_FRONTEND_ORIGIN=http://localhost:5173
./deploy-campaign.sh
```

`NONE` makes the Function URL public; do not use that mode for production or sensitive campaign operations.

## Deploy

Base Cara must already be deployed and `deployment-state.json` must exist.

```bash
export CARA_CAMPAIGN_FRONTEND_ORIGIN=http://localhost:5173
./deploy-campaign.sh
```

The deployer creates/reuses only campaign resources and writes these outputs into `deployment-state.json`, including `CampaignApiFunctionUrl` and `CampaignApiAuthType`.
