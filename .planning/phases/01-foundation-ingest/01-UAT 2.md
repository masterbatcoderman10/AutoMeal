---
status: complete
phase: 01-foundation-ingest
source: [.planning/phases/01-foundation-ingest/01-01-SUMMARY.md, .planning/phases/01-foundation-ingest/01-02-SUMMARY.md, .planning/phases/01-foundation-ingest/01-03-SUMMARY.md, .planning/phases/01-foundation-ingest/01-04-SUMMARY.md, .planning/phases/01-foundation-ingest/01-05-SUMMARY.md]
started: 2026-05-26T19:06:08Z
updated: 2026-05-26T20:38:08Z
---

## Current Test

[testing complete]

## Tests

### 1. User Flow - Start MealTracker
expected: From a clean checkout with local `.env` values filled, start MealTracker with Docker Compose. The stack should come up without fatal errors, the API should report healthy, and the bot service should remain running so it is ready to acknowledge meals.
result: pass

### 2. User Flow - Submit a Meal Photo and See Acknowledgement
expected: Submit a meal photo using the iOS Shortcut or a local sample image with the shared secret. Within about 5 seconds, the submission should be accepted and Telegram should show the "received, processing..." acknowledgement, so photo ingest is confirmed without checking the database manually.
result: pass

### 3. Cold Start Smoke Test
expected: Stop any running MealTracker containers, clear only ephemeral container state, then start the application from scratch. Migrations should complete, the server should boot without errors, and the primary health check should return live data.
result: pass

### 4. Duplicate Photo Deduplication
expected: Re-submit the identical photo within 60 seconds. The second submission should return the existing MealLog identifier instead of creating a new meal record.
result: pass

### 5. Shared Secret Rejection
expected: Submit the same photo without the ingest secret, or with a wrong secret. The API should reject it immediately and should not save or process the image.
result: pass

### 6. Database Schema Contract
expected: Run the schema contract check or inspect the migrated database. Both embedding columns should use vector(1536), all timestamp columns should be timezone-aware, the processing status enum should include FAILED, and the FoodVisual embedding index should be HNSW cosine with m=16 and ef_construction=64.
result: pass

### 7. Telegram Pending Meal Handoff
expected: After a meal is accepted, the bot should claim the pending meal, send the acknowledgement, and advance the row to DETECTING only after the Telegram send succeeds.
result: pass

### 8. OpenRouter Client and Local Env Surface
expected: The local environment template should include every required secret, real `.env` values should stay untracked, and the LLM client should fail fast when OPENROUTER_API_KEY is missing while preserving the SDK chat path and raw httpx embeddings path.
result: pass

## Summary

total: 8
passed: 8
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

[none yet]

## Notes

- 2026-05-26T20:06:15Z: iPhone/Tailscale health check did not load when Docker was bound directly to `100.78.228.31:18000`. Reproduced from the Mac: `127.0.0.1:18000` was not bound and `100.78.228.31:18000` timed out. Tailscale Serve was also unsuitable in this setup because it proxied to SearXNG from the Tailscale daemon's localhost view. Set local `API_HOST_BIND=0.0.0.0` with `API_HOST_PORT=18000`; verified `curl http://127.0.0.1:18000/health` and `curl http://100.78.228.31:18000/health` both return `{"status":"ok"}`.
- 2026-05-26T20:31:28Z: Duplicate-photo behavior verified with two immediate local `POST /ingest/photo` requests using the same HEIC sample. First response returned `deduplicated:false`; second response returned the same `meal_log_id` with `deduplicated:true`. No second Telegram acknowledgement is expected for the duplicate because no new `PENDING` row is created.
- 2026-05-26T20:38:08Z: Completed remaining technical checks via automation/operator verification rather than manual UAT. `python -m unittest discover tests` ran 12 tests OK, including ingest auth contract tests. `scripts/check_schema_contract.py` printed `schema contract ok`. Live API probes confirmed missing and wrong `X-Ingest-Secret` both return 401. Live dedup probe confirmed identical uploads return the same meal ID with second response `deduplicated:true`. `docker compose ps` showed all 9 services up, with API, Postgres, RabbitMQ, and Firecrawl NUQ Postgres healthy. OpenRouter fail-fast was verified with a patched missing-key settings object raising `OPENROUTER_API_KEY must be set`.
