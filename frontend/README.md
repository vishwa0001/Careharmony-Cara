# Cara Health Bot Campaign Frontend

React/TypeScript frontend for scheduling and monitoring Cara outbound campaigns.

## Backend contract

Preferred API configuration:

```env
VITE_CAMPAIGN_API_BASE_URL=https://your-authenticated-campaign-api.example.com
```

The frontend uses:

- `POST /uploads`
- direct presigned `PUT` to S3
- `GET /campaigns`
- `GET /campaigns/{campaignId}`
- `GET /campaigns/{campaignId}/patients`
- `POST /campaigns/{campaignId}/cancel`
- `POST /campaigns/{campaignId}/reschedule`

The previous split `VITE_UPLOAD_URL_API` / `VITE_LIST_API_URL` variables remain as read-only backward compatibility, but the unified Cara campaign API is recommended.

## Scheduling semantics

`datetime-local` is sent as a wall-clock value together with the selected IANA timezone. Both frontend and backend interpret the pair together; the backend is authoritative and converts it to UTC before creating the EventBridge Scheduler entry.

## CSV schema

Required headers:

```csv
empi,first_name,last_name,gender,phone_number,practice_name,practice_callback_number
```

The browser validates the file before upload, and the Lambda intake validates it again server-side.

## Live campaign behavior

The UI maps backend states as follows:

- `UPLOAD_PENDING` -> Uploaded
- `PENDING` -> Scheduled
- `RUNNING` -> Processing
- `COMPLETED` -> Completed
- `VALIDATION_FAILED` -> Validation Failed
- `CANCELLED` -> Cancelled

While any campaign is active, the page refreshes status every 20 seconds. The details drawer shows aggregate campaign outcomes and patient results returned by the backend; patient phone numbers are limited to the last four digits.

## Cancel / reschedule / re-upload

- Scheduled/pre-start campaigns can be cancelled through the real backend API.
- Cancelled campaigns can be rescheduled, producing a new linked campaign.
- Failed/validation-failed campaigns can be re-uploaded and retain `originalRecordId` lineage.

## Authentication

Do not put long-lived AWS access keys or production secrets into Vite environment variables. `VITE_CAMPAIGN_API_BASE_URL` should normally point to an authenticated API layer. The service can attach a short-lived bearer token from `sessionStorage.caraCampaignApiToken` when your host application provides one.

For a temporary local POC, the backend can explicitly expose a public Function URL, but that is not the production configuration.

## Run locally

```bash
cp .env.example .env
# set VITE_CAMPAIGN_API_BASE_URL
npm install
npm run dev
```

## Validate

```bash
npm test
npm run build
```
