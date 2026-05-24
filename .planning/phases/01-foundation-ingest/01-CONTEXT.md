# Phase 1: Foundation & Ingest - Context

**Gathered:** 2026-05-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Boot the entire infrastructure stack with the correct schema from day one: `vector(1536)` on both embedding columns, HNSW cosine index (`m=16, ef_construction=64`), TIMESTAMPTZ on all timestamp columns, and `FAILED` status in the processing enum. The ingest endpoint accepts a HEIC photo from the existing iOS Shortcut (triggers on camera-app close, sends via Tailscale), transcodes to JPEG, creates a `MealLog(PENDING)`, deduplicates re-submissions within 60 seconds by image hash, and triggers an immediate Telegram "received, processing…" acknowledgement from a separate bot service. No vision, embedding, or pipeline logic in this phase.

</domain>

<decisions>
## Implementation Decisions

### Telegram Bot Topology
- **D-01:** Bot runs as a **separate service** in `docker-compose.yml` (not inside the FastAPI container). Fault isolation: a bot crash does not take down the API.
- **D-02:** FastAPI → bot communication via **direct DB polling** — the bot polls `meal_logs` for new `PENDING` rows and sends the ack message. No Redis or inter-service HTTP.
- **D-03:** Bot entry point: `python-telegram-bot` `Application.run_polling()` in `bot/main.py` as `__main__`. PTB manages its own event loop.
- **D-04:** Bot and FastAPI share the **same repo, same Python package** (`app/` and `bot/` directories). Shared DB models, config (`pydantic-settings`), and utilities. Different `CMD` per service in docker-compose.

### Image File Storage
- **D-05:** Images stored on a **named Docker volume** (`uploads`) mounted at `/data/uploads` inside the app container. Flat structure — no date-bucketing.
- **D-06:** Path convention: `/data/uploads/meals/{meal_id}.jpg` for originals; `/data/uploads/crops/{segment_id}.jpg` for crops (Phase 2+).
- **D-07:** DB columns (`MealLog.image_url`, `MealSegment.cropped_image_url`) store **absolute container paths** (e.g. `/data/uploads/meals/{uuid}.jpg`).
- **D-08:** All stored files are **JPEG, UUID-named**. Incoming HEIC images from the iOS Shortcut are transcoded to JPEG on ingest (Pillow + `pillow-heif`).

### iOS Shortcut
- **D-09:** Shortcut already exists. It fires automatically when the camera app closes and sends the last-taken photo. Phase 1 deliverable: expose the endpoint at a stable Tailscale URL, configure the shared-secret header, and verify the image arrives correctly.
- **D-10:** Shortcut sends image as **HEIC** via `multipart/form-data`, field name `picture`. Server must handle HEIC → JPEG transcoding on ingest.
- **D-11:** Shortcut reaches the Mac mini via **Tailscale** (stable VPN IP). No port forwarding or DDNS needed.

### Schema Definition
- **D-12:** `MealTracker_Schema_Types.ts` and `MealTracker_Schema.mermaid` become **read-only reference docs** after Phase 1. Python/SQLAlchemy models are the sole source of truth going forward.
- **D-13:** Schema defined via **SQLAlchemy 2 declarative models + Alembic migrations**. Models live in `app/models/`. Alembic generates versioned migration files for incremental schema changes across phases.
- **D-14:** Phase 1 schema includes all **three additional columns** beyond the locked requirements:
  - `image_hash` on `MealLogs` — SHA-256 of raw bytes, used for 60-second dedup (INGEST-05)
  - `is_invalidated` on `FoodVisuals` — for USER_CORRECTED cascade (INTERVIEW-06, Phase 4)
  - `portion_bucket` ENUM on `MealSegments` — `SMALL/STANDARD/LARGE` replacing `quantity_multiplier` float (Phase 4 uses this)

### Locked Schema Requirements (from REQUIREMENTS.md MATCH-01 + Phase 1 SC)
- `vector(1536)` on `food_visuals.embedding` and `meal_segments.embedding`
- HNSW cosine index: `m=16, ef_construction=64` on `food_visuals.embedding`
- `TIMESTAMPTZ` on all timestamp columns
- `FAILED` status added to `MealProcessingStatus` enum
- `IVFFlat` index in pre-work schema is **wrong** — must not be created

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Schema Pre-work (read-only reference, contains errors — see D-12 to D-14)
- `MealTracker_Schema_Types.ts` — TypeScript type definitions for all entities. Has `vector(1024)` and IVFFlat (both wrong). Read for entity shape; do not copy vector dimensions or index config.
- `MealTracker_Schema.mermaid` — ER diagram. Useful for entity relationships; does not show vector/index config.

### Requirements & Roadmap
- `.planning/REQUIREMENTS.md` — Full v1 requirements with IDs (INGEST-01 through INFRA-05). Phase 1 covers: INGEST-01..05, INFRA-01..03, INFRA-05, MATCH-01.
- `.planning/ROADMAP.md` — Phase 1 goal, success criteria, and phase note (CF-3 iOS Shortcut concern; LLM client skeleton routing note).

### Project Context
- `.planning/PROJECT.md` — Core constraints (OpenRouter via OpenAI SDK, APScheduler 3.10.x, multimodal embeddings via httpx wrapper) and key decisions table.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- None yet — blank repo. Phase 1 creates the foundational structure.

### Established Patterns
- None yet — Phase 1 establishes all patterns (project layout, SQLAlchemy async models, Alembic config, FastAPI lifespan, docker-compose service layout).

### Integration Points
- The `uploads` Docker volume is a shared integration point — Phase 2 (crop saves) and Phase 3 (embedding reads) both depend on the path convention established in D-06.
- The `meal_logs.processing_status` state machine is the coordination backbone — bot polls it, pipeline advances it.

### Schema Corrections Required
The pre-work `.ts` file has these errors that Python models must NOT replicate:
- `vector(1024)` → use `vector(1536)` (D-05 / MATCH-01)
- `IVFFlat` index → use HNSW `m=16, ef_construction=64` (MATCH-01)
- Missing `FAILED` in `MealProcessingStatus` → add it (Phase 1 SC #5)
- `quantity_multiplier: float` on `MealSegments` → replace with `portion_bucket` ENUM (D-14)
- Missing `image_hash` on `MealLogs` → add SHA-256 column (D-14)
- Missing `is_invalidated` on `FoodVisuals` → add boolean (D-14)

</code_context>

<specifics>
## Specific Ideas

- iOS Shortcut sends HEIC via `multipart/form-data` field `picture`. Server must use `python-multipart` for form parsing + `pillow-heif` for HEIC transcoding before storing.
- Tailscale URL will be the endpoint target — document in `.env.example` so user can fill in their Tailscale IP.
- Bot's DB poll interval: short (e.g. 2–5 seconds) to keep the "received" ack feeling responsive. This is a tunable config value.
- Phase 1 note from ROADMAP: wire the LLM client skeleton with routing logic now (httpx path for multimodal embeddings vs. OpenAI SDK path for chat/tools). This is a skeleton only — no actual LLM calls yet.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 1-Foundation-Ingest*
*Context gathered: 2026-05-24*
