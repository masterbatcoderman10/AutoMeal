---
phase: 01-foundation-ingest
plan: 05
subsystem: infra
tags:
  - openrouter
  - openai-sdk
  - httpx
  - fastapi

requires:
  - phase: 01-foundation-ingest
    provides: app package scaffolding and settings-ready entry surface from previous plans
provides:
  - OpenRouter dual-path client skeleton (chat via SDK, embeddings via httpx)
  - Package-level exports for routers, services, and schemas
  - Database session factory accessor and module exports
  - Local `.env` guidance plus updated `.env.example`
affects:
  - phase: 01-foundation-ingest

tech-stack:
  added:
    - openai AsyncOpenAI client
    - httpx AsyncClient
    - shared `.env` template with searxng secret
  patterns:
    - OpenRouter SDK/chat-and-tools, raw httpx embeddings split
    - Explicit package barrel exports via `__all__`

key-files:
  created:
    - app/services/llm_client.py
  modified:
    - app/__init__.py
    - app/routers/__init__.py
    - app/services/__init__.py
    - app/schemas/__init__.py
    - app/database.py
    - .env.example
    - .env

key-decisions:
  - "Use a strict fail-fast check in `get_llm_client()` when `OPENROUTER_API_KEY` is missing."
  - "Keep `.env` local-only and ignored from source control while ensuring required keys are documented."

requirements-completed:
  - INFRA-02

duration: 2min
completed: 2026-05-26
---

# Phase 01: Foundation & Ingest Summary

**Wired OpenRouter dual-path LLM client scaffold and package exports for API/bot infrastructure setup**

## Performance

- **Duration:** 1.27m (recorded start 2026-05-26T12:20:17Z, completed 2026-05-26T12:21:33Z)
- **Started:** 2026-05-26T12:20:17Z
- **Completed:** 2026-05-26T12:21:33Z
- **Tasks:** 5
- **Files modified:** 7

## Accomplishments

- Added `app/services/llm_client.py` with `OpenRouterClient`, OpenAI SDK chat/tool path, and raw httpx embeddings path.
- Populated package `__init__.py` files to support clean imports for routers, services, and schemas.
- Added `get_session_factory` export surface in `app/database.py` and updated `.env.example` with `SEARXNG_SECRET`.
- Added `.env` scaffold (local, uncommitted) with required environment keys documented for user fill-in.

## Task Commits

1. **Task 1: Create LLM client skeleton with dual-path routing** - `2083f7a` (feat) and `6fe9399` (fix)
2. **Task 2: Fill remaining __init__.py files** - `c03385e` (feat)
3. **Task 3: Add get_session_factory accessor to database.py** - `496de01` (feat)
4. **Task 4: Preserve or create local .env from .env.example template** - no commit (local untracked `.env`)
5. **Task 5: Create .env.example with SEARXNG_SECRET** - `6b3816e` (feat)

**Plan metadata:** latest docs commit in git history (docs: complete llm wiring plan)

## Files Created/Modified

- `app/services/llm_client.py` - dual-path OpenRouter client skeleton with singleton accessor.
- `app/__init__.py` - application package marker.
- `app/routers/__init__.py` - router barrel exports.
- `app/services/__init__.py` - service and LLM client exports.
- `app/schemas/__init__.py` - response schema exports.
- `app/database.py` - exported `get_session_factory` in `__all__`.
- `.env` - local untracked environment template with required keys.
- `.env.example` - added `SEARXNG_SECRET=changeme`.

## Decisions Made

- Keep `.env` secret material local-only (ignored, never committed), and derive from template when absent.
- Use `get_llm_client()` singleton with fail-fast on missing `OPENROUTER_API_KEY` for safer startup behavior.
- Use split paths for OpenRouter: SDK for chat completions, httpx for multimodal embeddings.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added explicit `OPENROUTER_API_KEY` fail-fast guard**
- **Found during:** Task 1
- **Issue:** Initial implementation could initialize `OpenRouterClient` with an empty API key and defer failure to runtime call sites.
- **Fix:** Added validation in `get_llm_client()` to raise `RuntimeError` when `OPENROUTER_API_KEY` is missing.
- **Files modified:** `app/services/llm_client.py`
- **Verification:** Threat-model check for missing key requirement and runtime import path.
- **Committed in:** `6fe9399`

## Issues Encountered

- `.env` in the primary checkout currently uses a different legacy key layout; implementation follows plan by creating a local, safe template and documenting required keys.
- `.env` is intentionally untracked and therefore not included in commits.

## User Setup Required

- Fill required values in local `.env` from `.env.example` before `docker compose up`.
- Ensure at minimum:
  - `POSTGRES_PASSWORD`
  - `INGEST_SECRET`
  - `TELEGRAM_BOT_TOKEN`
  - `TELEGRAM_CHAT_ID`
  - `OPENROUTER_API_KEY`
  - `FIRECRAWL_PASSWORD`
  - `SEARXNG_SECRET`

## Known Stubs

None.

## Threat Flags

None.

## Next Phase Readiness

- API ingest, bot polling, schema, and DB lifecycle scaffolding are wired to consume the new client and exports.
- Ready for phase 1 pipeline/modeling work that depends on OpenRouter client skeleton availability.

---
*Phase: 01-foundation-ingest*
*Completed: 2026-05-26*

## Self-Check: PASSED

**PASS** Created file exists: `.planning/phases/01-foundation-ingest/01-05-SUMMARY.md`
**PASS** Commit hash `2083f7a` exists
**PASS** Commit hash `6fe9399` exists
**PASS** Commit hash `c03385e` exists
**PASS** Commit hash `496de01` exists
**PASS** Commit hash `6b3816e` exists

---
