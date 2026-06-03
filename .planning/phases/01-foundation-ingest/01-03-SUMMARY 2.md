---
phase: 01-foundation-ingest
plan: 03
status: complete
completed: 2026-05-25
requirements: [INGEST-01, INGEST-02, INGEST-03, INGEST-04, INGEST-05]
---

# Plan 03 Summary: FastAPI Ingest

## Completed

- Added FastAPI app with lifespan-based startup and ORJSON responses.
- Added `/health`.
- Added `/ingest/photo` accepting multipart field `picture`.
- Added shared-secret auth via `X-Ingest-Secret`.
- Added raw-byte SHA-256 dedup window.
- Added HEIC/HEIF to JPEG transcoding and upload save service.
- New accepted photos create `MealLog(PENDING)` rows and save image paths under `/data/uploads/meals`.

## Verification

- Local TestClient smoke:
  - `/health` returns 200.
  - missing secret returns 401.
  - wrong secret returns 401.
- Container smoke from inside the API container:
  - missing secret returns 401.
  - wrong secret returns 401.
  - first correct upload returns 202 with `deduplicated=false`.
  - repeated identical upload returns 200 with same `meal_log_id` and `deduplicated=true`.

## Notes

- Host `127.0.0.1:8000` was already answering with another service during verification, so live HTTP checks were run from inside the API container against its own localhost.
