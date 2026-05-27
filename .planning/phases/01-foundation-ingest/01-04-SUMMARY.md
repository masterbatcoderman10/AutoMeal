---
phase: 01-foundation-ingest
plan: 04
subsystem: bot
tags: [python-telegram-bot, telegram, sqlalchemy, asyncpg, docker-compose, tdd]

# Dependency graph
requires:
  - phase: 01-01
    provides: "Docker service layout plus shared config/database scaffolding"
  - phase: 01-02
    provides: "MealLog schema and processing status enum"
  - phase: 01-03
    provides: "Authenticated ingest endpoint creating PENDING MealLog rows"
provides:
  - "Separate Telegram bot service using PTB long polling"
  - "DB-backed pending-meal acknowledgement loop advancing rows to DETECTING"
  - "Start/help handlers and reusable bot message templates"
affects:
  - "Phase 02 vision pipeline handoff from DETECTING status"
  - "Phase 06 Telegram command surface"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "PTB Application.run_polling entrypoint with post_init/post_shutdown lifecycle hooks"
    - "Separate bot container creates its own async SQLAlchemy engine and polls MealLog with FOR UPDATE SKIP LOCKED"

key-files:
  created:
    - bot/messages.py
    - bot/polling.py
    - bot/handlers.py
    - bot/main.py
    - tests/test_bot_contract.py
    - tests/__init__.py
  modified:
    - docker-compose.yml

key-decisions:
  - "Use synchronous PTB Application.run_polling() as the process entrypoint and attach the DB poll loop through post_init/post_shutdown hooks."
  - "Advance MealLog to DETECTING only after Telegram send_message succeeds so duplicate-claim protection and user-visible acknowledgement stay aligned."

patterns-established:
  - "Bot code stays in a separate service but reuses app config, ORM models, and DB utilities from the shared repo."
  - "Pending-meal acknowledgement is coordinated through DB row locking rather than Redis or inter-service HTTP."

requirements-completed:
  - INGEST-03

# Metrics
duration: 56min
completed: 2026-05-26
---

# Phase 01 Plan 04: Telegram Bot Acknowledgement Summary

**Implemented the separate Telegram bot service for Phase 1, including PTB long polling, DB-backed pending-meal acknowledgement, start/help handlers, and a verified `PENDING -> DETECTING` acknowledgement handoff.**

## Performance

- **Duration:** 56 min
- **Started:** 2026-05-26T11:18:55Z
- **Completed:** 2026-05-26T12:15:16Z
- **Tasks:** 4
- **Files modified:** 7

## Accomplishments

- Added pure bot message formatters plus `/start` and `/help` handlers for the Phase 1 Telegram surface.
- Added an async poll loop that claims the oldest `PENDING` `MealLog` with `FOR UPDATE SKIP LOCKED`, sends the acknowledgement, and advances the row to `DETECTING`.
- Wired the bot entrypoint through `Application.run_polling()` with clean startup/shutdown hooks and verified a live seeded meal transitions to `DETECTING` after a successful Telegram API `sendMessage` call.

## Task Commits

Each task was committed atomically:

1. **TDD RED: contract tests for bot behavior** - `10a8eab` (test)
2. **Task 1: message templates** - `a135d1e` (feat)
3. **Task 2: pending-meal poll loop** - `d40751f` (feat)
4. **Task 3: `/start` and `/help` handlers** - `b4b8721` (feat)
5. **Task 4: PTB entrypoint and compose wiring** - `388cfd9` (feat)

## Files Created/Modified

- `bot/messages.py` - Pure message template helpers for ack, start, and retry/error text.
- `bot/polling.py` - Async Telegram acknowledgement poller with row locking, status transition, and resilient exception handling.
- `bot/handlers.py` - `/start` and `/help` command handlers.
- `bot/main.py` - PTB polling entrypoint with background task lifecycle hooks.
- `tests/test_bot_contract.py` - Docker-runnable contract coverage for messages, handlers, poll loop, and PTB wiring.
- `tests/__init__.py` - Test package marker for `unittest` discovery.
- `docker-compose.yml` - Bot env passthrough aligned with the shared settings contract used by `app.config`.

## Decisions Made

- Kept the bot in a separate container but reused the shared `app.config.Settings` and ORM model layer instead of duplicating DB/config code.
- Let the bot tolerate transient startup failures, such as polling before migrations complete, because the plan already requires loop-level exception logging and retry rather than process exit.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added missing shared-settings env passthrough for the bot service**
- **Found during:** Task 4 verification
- **Issue:** The bot container used the shared `app.config.Settings` contract, but `docker-compose.yml` did not pass all required env values into the `bot` service, preventing startup.
- **Fix:** Added the missing `INGEST_SECRET` and `OPENROUTER_API_KEY` env passthrough alongside the existing Telegram and database settings.
- **Files modified:** `docker-compose.yml`
- **Verification:** Bot container booted successfully after restart and completed a live Telegram `sendMessage` call during the seeded-meal smoke test.
- **Committed in:** `388cfd9`

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** The fix was required for the separate bot service to start under the shared settings model. No scope creep beyond runtime correctness.

## Issues Encountered

- Host port `8000` was already occupied by another local process, so runtime verification avoided `docker compose up api` and instead used `docker compose run --rm api alembic ...` plus direct DB seeding.
- The local `.env` copied into the worktree had a real Telegram token but an empty `DATABASE_URL`; worktree-local env normalization was required to supply DB credentials for verification without changing tracked project files.
- When the bot started before migrations had finished, it logged `relation "meal_logs" does not exist`, then recovered automatically and continued polling once Alembic completed. This matched the plan's "log and continue" resilience rule.

## User Setup Required

None - no tracked setup files were added. Runtime secrets remain local and untracked.

## Next Phase Readiness

- Phase 1 now has the full vertical acknowledgement slice: ingest creates `PENDING` rows and the separate bot service claims them, notifies Telegram, and advances them to `DETECTING`.
- Phase 2 can build on the `DETECTING` handoff to run food detection/segmentation and replace the temporary acknowledgement-only behavior with real processing updates.

## Known Stubs

No stubs found in created/modified files.

## Self-Check: PASSED

Verified the summary file exists and all five Plan 04 task commits are present in git history. Stub scan found no production stubs; the only pattern match was a test-only `bot_data={}` mock in `tests/test_bot_contract.py`.

---
*Phase: 01-foundation-ingest*
*Completed: 2026-05-26*
