# Phase 1 Vertical Slice Design

## Goal

Build the first end-to-end MealTracker slice that proves the core runtime topology:

- iOS Shortcut uploads a photo to `POST /ingest`
- the app authenticates the request with a shared secret
- the image is persisted to a mounted local filesystem volume
- Postgres stores metadata and queue state
- the API returns `202 Accepted` immediately
- Telegram sends a pinned-chat acknowledgment that the photo was received
- a background worker claims the queued row and transitions it from `PENDING` to `PROCESSING`

This phase intentionally stops before any LLM-based food detection, segmentation, matching, reasoning, or interview flow.

## Phase Boundary

Included in phase 1:

- FastAPI app scaffold
- typed settings and `.env` loading
- async Postgres connectivity
- initial SQLAlchemy models and migrations
- local file storage adapter for raw uploads
- multipart `/ingest` endpoint with shared-secret auth
- Telegram notifier for pinned-chat acks
- background worker loop that claims pending jobs
- healthcheck endpoint
- `docker-compose` for app + Postgres
- placeholder configuration for future SearXNG and Firecrawl services

Explicitly excluded from phase 1:

- OpenRouter calls
- food / non-food classification
- segmentation
- embeddings and pgvector search
- nutrition reasoning
- Telegram interview state machine
- daily summary scheduler jobs
- SearXNG and Firecrawl runtime activation

## Recommended Runtime Shape

Run one Python app process that owns:

- FastAPI HTTP server
- Telegram bot polling client
- background worker loop
- scheduler bootstrap point for later phases

This matches the researched architecture and avoids premature inter-process coordination. The worker and bot are sidecar responsibilities inside the same asyncio process, not separate services.

## Deployment Shape

Phase 1 `docker-compose.yml` should run:

- `app`
- `postgres`

The compose file should also reserve the future shape for:

- `searxng`
- `firecrawl`

Those future services should remain placeholders only in phase 1, such as commented blocks, disabled profiles, or clearly marked non-started service definitions. The point is to codify the future topology without introducing unused runtime dependencies yet.

## Request Contract

### Endpoint

- `POST /ingest`

### Authentication

- Header: `X-MealTracker-Secret`
- The value is a shared secret configured in env and used by the iOS Shortcut

### Request Body

- `multipart/form-data`
- one required image file field
- optional metadata fields may be accepted now only if they are cheap and stable, such as client timestamp or source label

### Response

- `202 Accepted` on successful persistence
- response body should include the internal ingest ID and a small status payload

Example response shape:

```json
{
  "meal_log_id": "01JXYZ...",
  "status": "PENDING"
}
```

## Data Model Slice

Phase 1 needs only the schema needed to persist an uploaded photo and track queue state. The DB row should be future-proof enough that later phases do not need a redesign.

Minimum fields for the main ingest row:

- stable primary key
- `processing_status`
- `source_type` or equivalent marker for `ios_shortcut`
- `storage_path`
- `original_filename`
- `content_type`
- `received_at`
- `processing_started_at` nullable
- `created_at`
- `updated_at`

Initial status enum values should include at least:

- `PENDING`
- `PROCESSING`
- `FAILED`

If the existing requirements already imply more statuses, they can be declared now, but phase 1 behavior only needs to exercise `PENDING -> PROCESSING`.

## File Storage Decision

Raw uploaded images should be stored on a mounted local filesystem volume, not as `bytea` blobs in Postgres.

Reasoning:

- keeps binary payloads out of the primary relational store
- reduces backup and WAL amplification
- avoids coupling queue throughput to image storage I/O
- makes later migration to object storage easier

The DB stores metadata and path references only.

## Component Boundaries

Recommended module responsibilities:

- `app/main.py`
  - FastAPI app creation
  - lifespan wiring
  - startup and shutdown orchestration

- `app/config.py`
  - typed settings from env
  - required secret validation

- `app/api/routes/ingest.py`
  - request parsing
  - auth dependency use
  - HTTP response contract

- `app/services/ingest.py`
  - orchestrates file save, DB insert, and notifier dispatch

- `app/storage/files.py`
  - local filesystem adapter for raw uploads

- `app/db/`
  - engine
  - session management
  - repositories

- `app/models/`
  - SQLAlchemy models for the phase-1 schema slice

- `app/worker/loop.py`
  - DB polling and row claiming
  - transition from `PENDING` to `PROCESSING`

- `app/bot/`
  - Telegram application bootstrap
  - pinned-chat notifier abstraction

## Request and Runtime Flow

1. iOS Shortcut sends multipart upload to `POST /ingest` with `X-MealTracker-Secret`.
2. The app validates the shared secret before doing meaningful work.
3. The ingest service allocates an internal ID.
4. The file storage adapter writes the image to the mounted uploads directory.
5. The DB transaction inserts the ingest row in `PENDING`.
6. The API returns `202 Accepted` as soon as persistence is committed.
7. A Telegram notifier sends a pinned-chat acknowledgment such as "photo received, processing started."
8. The worker loop polls for `PENDING` rows.
9. The worker claims a row using a safe DB queue pattern such as `FOR UPDATE SKIP LOCKED`.
10. The worker updates the row to `PROCESSING` and stamps `processing_started_at`.
11. Phase 1 ends there.

## Lifespan Behavior

Startup order:

1. load and validate settings
2. initialize structured logging
3. verify DB connectivity
4. initialize Telegram application
5. initialize scheduler bootstrap point
6. create background worker task
7. begin serving HTTP

Shutdown order:

1. stop accepting new background work
2. cancel or drain worker loop cleanly
3. stop Telegram polling cleanly
4. close DB resources
5. finish process shutdown

## Error Handling

Phase 1 should keep failure handling narrow and explicit:

- invalid or missing shared secret: `401 Unauthorized`
- missing image field or malformed multipart: `400 Bad Request`
- unsupported media type: `415 Unsupported Media Type`
- file write failure: `500 Internal Server Error`
- DB insert failure: `500 Internal Server Error`

Side-effect rule:

- Telegram acknowledgment failure must not invalidate an already-persisted ingest request
- once the DB transaction commits, the request should still be considered accepted even if the notifier fails
- notifier failures should be logged with the ingest ID for manual diagnosis

Worker safety rule:

- queue claim and status transition must be atomic enough to avoid duplicate claims
- failures before a successful transition should leave the row retryable

## Observability

Minimum observability for phase 1:

- structured logs
- one correlation ID per ingest request carried across route, storage, DB, notifier, and worker logs
- `/healthz` endpoint
- clear timestamps in DB so stuck jobs can be inspected manually

Useful log events:

- request accepted
- file persisted
- DB row inserted
- Telegram ack attempted
- Telegram ack succeeded or failed
- worker claimed row
- status transitioned to `PROCESSING`

## Testing Strategy

Phase 1 tests should prove the vertical slice only.

Core tests:

- auth test for valid shared secret
- auth test for invalid shared secret
- API test for multipart upload returning `202`
- storage test proving the file is written to disk
- repository test proving metadata is inserted correctly
- notifier test proving Telegram ack dispatch is requested
- worker test proving `PENDING` rows transition to `PROCESSING`
- happy-path integration test covering ingest through worker claim

Fixture strategy:

- use small dedicated fixtures in tests where possible
- the existing `sample_images/` directory can be used for manual and integration testing
- current sample files are HEIC images, so phase-1 validation must either accept HEIC uploads explicitly or the test suite must include an additional lightweight JPEG/PNG fixture for deterministic automated tests

## Environment Variables

Required for phase 1:

- `DATABASE_URL`
- `MEALTRACKER_API_SECRET`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `UPLOAD_DIR`
- `APP_TIMEZONE`

Optional or placeholder-only for phase 1:

- `OPENROUTER_API_KEY`
- `OPENROUTER_BASE_URL`
- `SEARXNG_BASE_URL`
- `FIRECRAWL_BASE_URL`
- future model ID settings

Decision:

- you do need Telegram credentials in `.env` for phase 1 because the acknowledgment is in scope
- you do not need a real OpenRouter API key to complete phase 1, because no LLM stage runs yet

## Success Criteria

Phase 1 is complete when all of the following are true:

- `docker-compose` starts the app and Postgres successfully
- `/ingest` accepts a real photo upload from a client using the shared secret
- the raw image appears in the mounted upload directory
- a DB row is created with `PENDING`
- the pinned Telegram chat receives the acknowledgment message
- the worker claims the row and updates it to `PROCESSING`
- tests cover the happy path and core failure cases

## Open Questions Resolved

- store raw photos on local filesystem volume, not Postgres blobs
- return immediate `202` and do not block on worker activity
- include only placeholders for SearXNG and Firecrawl in phase 1
- keep FastAPI, Telegram, scheduler bootstrap, and worker in one process
- phase 1 ends at Telegram ack plus worker transition to `PROCESSING`
