# Phase 1: Foundation & Ingest - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-24
**Phase:** 1-Foundation & Ingest
**Areas discussed:** Telegram bot topology, Image file storage, iOS Shortcut deliverable, Schema artifact update

---

## Telegram Bot Topology

| Option | Description | Selected |
|--------|-------------|----------|
| Same container, same process | Bot polling runs as async task inside FastAPI. One container. No fault isolation. | |
| Same container, separate thread/task | Bot runs in separate asyncio task in FastAPI lifespan. Restartable within process. | |
| Separate service in docker-compose | Dedicated `telegram-bot` container. Fault isolation. | ✓ |

**User's choice:** Separate service in docker-compose

| Option | Description | Selected |
|--------|-------------|----------|
| Direct DB polling | Bot polls `meal_logs` for new PENDING rows | ✓ |
| Shared async queue (Redis) | FastAPI writes to queue; bot reads and acts | |
| FastAPI calls bot via internal HTTP | Tight coupling between two services | |

**User's choice:** Direct DB polling

| Option | Description | Selected |
|--------|-------------|----------|
| Application.run_polling() as __main__ | Standalone `bot/main.py`, PTB manages its own event loop | ✓ |
| FastAPI BackgroundTasks/lifespan task | Bot started inside FastAPI's lifespan even in separate container | |
| You decide | Leave to planner | |

**User's choice:** `Application.run_polling()` as `__main__`

| Option | Description | Selected |
|--------|-------------|----------|
| Same repo, shared package | `app/` and `bot/` share DB models, config, utilities; different CMD per service | ✓ |
| Same image, different CMD | Single Dockerfile, docker-compose sets CMD per service | |
| Separate codebases | Fully independent repos | |

**User's choice:** Same repo, shared package

---

## Image File Storage

| Option | Description | Selected |
|--------|-------------|----------|
| Named Docker volume, flat structure | `uploads` volume at `/data/uploads`. Simple, portable. | ✓ |
| Host bind mount | `./data/uploads` mounted into container. Visible on host. | |
| Date-bucketed within the volume | `/data/uploads/2026-05-24/{id}.jpg`. Prevents large flat dirs. | |

**User's choice:** Named Docker volume, flat structure

| Option | Description | Selected |
|--------|-------------|----------|
| Absolute container path | `/data/uploads/meals/{meal_id}.jpg` stored in DB | ✓ |
| Relative path | `meals/{meal_id}.jpg` joined with base-path config | |
| You decide | Leave to planner | |

**User's choice:** Absolute container path

| Option | Description | Selected |
|--------|-------------|----------|
| JPEG, UUID-named | Transcode HEIC → JPEG on ingest | ✓ |
| Original format preserved, UUID-named | Keep HEIC; add pillow-heif for downstream | |
| You decide | Leave to planner | |

**User's choice:** JPEG, UUID-named (HEIC transcoded on ingest)

---

## iOS Shortcut Deliverable

| Option | Description | Selected |
|--------|-------------|----------|
| Share Sheet only | Manual share from Photos. Reliable. | |
| Automatic trigger only | Fires when camera app closes. CF-3 risk. | |
| Both | Share sheet + automatic trigger | |

**User's choice:** Free text — "I already have a shortcut that sends the last taken picture once the camera app closes, now I just need to configure an actual target URL and test that the image is coming through"
**Notes:** Shortcut already exists and uses the automatic trigger (camera-close Personal Automation). Phase 1 just needs to provide the Tailscale endpoint URL and verify the image arrives correctly.

| Option | Description | Selected |
|--------|-------------|----------|
| JPEG | Converted before sending | |
| HEIC | Native iPhone format, no conversion in shortcut | ✓ |
| Not sure | Handle both | |

**User's choice:** HEIC — "probably heic cause I'm not doing any conversion, it sends as a form body with the field named picture"

| Option | Description | Selected |
|--------|-------------|----------|
| Local network IP | LAN only, home WiFi | |
| Tailscale / VPN | Stable IP, works anywhere | ✓ |
| Port forwarding / DDNS | Public-facing, requires router config | |

**User's choice:** Tailscale

---

## Schema Artifact Update

| Option | Description | Selected |
|--------|-------------|----------|
| Python/SQLAlchemy is source of truth; .ts/.mermaid become read-only | Pre-work files kept as reference only | ✓ |
| Update both .ts and .mermaid | Fix all errors, keep in sync with Python | |
| Delete them | Remove to avoid confusion | |

**User's choice:** Python/SQLAlchemy is source of truth; .ts/.mermaid become read-only docs

| Option | Description | Selected |
|--------|-------------|----------|
| SQLAlchemy 2 declarative models + Alembic migrations | Standard pattern, incremental migration history | ✓ |
| SQLAlchemy 2 models + raw SQL init script | Simpler but no migration history | |
| You decide | Leave to planner | |

**User's choice:** SQLAlchemy 2 declarative models + Alembic migrations

**Additional columns to include in Phase 1 schema (all three selected):**
- `image_hash` on `MealLogs` — SHA-256 for 60-second dedup (INGEST-05)
- `is_invalidated` on `FoodVisuals` — for USER_CORRECTED cascade (INTERVIEW-06, Phase 4)
- `portion_bucket` ENUM on `MealSegments` — SMALL/STANDARD/LARGE replacing quantity_multiplier float

---

## Claude's Discretion

- Bot DB poll interval (2–5 seconds recommended; user did not specify exact value)
- Exact Tailscale URL format for `.env.example`

## Deferred Ideas

None — discussion stayed within phase scope.
