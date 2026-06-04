---
phase: 05-agentic-grounding
plan: 03
subsystem: infra
tags: [firecrawl, searxng, grounding, docker-compose, alembic, persistence, testing]
requires:
  - phase: 05-01
    provides: bounded grounding service primitives, strict grounding contracts, and allowlist semantics
  - phase: 05-02
    provides: inline finalizer grounding path and degraded-save persistence wiring
provides:
  - official Firecrawl `/search` runtime wiring backed by SearXNG JSON output
  - bounded grounding failure traces that preserve loop-stop reasons on degraded saves
  - quantity-json persistence on `MealSegment` plus compatibility-only `DiaryEntry.portion_bucket`
affects: [phase-05-runtime-verification, grounding, interview-finalization, database, compose]
tech-stack:
  added: []
  patterns: [compose-backed search runtime wiring, compatibility-shim quantity persistence, bounded loop-stop trace preservation]
key-files:
  created: [.planning/phases/05-agentic-grounding/05-03-SUMMARY.md, migrations/versions/phase5_grounding_quantity.py]
  modified: [docker-compose.yml, .env.example, app/config.py, app/models/meal_segment.py, app/models/diary_entry.py, app/services/interview_service.py, app/services/meal_resolution_service.py, tests/test_grounding_service.py, tests/test_interview_flow.py, tests/test_match_flow.py]
key-decisions:
  - "Kept `DiaryEntry.portion_bucket` as a compatibility-only mirror derived from `quantity_json` instead of making the legacy bucket field authoritative."
  - "Treat bounded loop exits as terminal degraded-save events: preserve `MAX_TOOL_CALLS`/timeout metadata and do not retry them into a generic tool-execution failure."
patterns-established:
  - "Runtime configuration proves architecture choice in-repo: Firecrawl self-host search is explicitly pointed at SearXNG and resource caps are documented in compose/env surfaces."
  - "Segment-level quantity persistence now travels with the authoritative final write, so downstream readers can reconstruct quantity detail without consulting legacy bucket state."
requirements-completed: [GROUND-01, GROUND-02, GROUND-03, MATCH-04]
duration: 11min
completed: 2026-06-04
---

# Phase 05 Plan 03: Agentic Grounding Summary

**Official Firecrawl `/search` wired to SearXNG with bounded degraded-save stop reasons and quantity-json persistence carried through the final write path**

## Performance

- **Duration:** 11 min
- **Started:** 2026-06-04T09:14:00Z
- **Completed:** 2026-06-04T09:25:03Z
- **Tasks:** 2
- **Files modified:** 11

## Accomplishments
- Added RED coverage for the final Phase 5 runtime contract: compose/env search wiring, allowlist-safe scrape candidates, bounded call-cap degradation, and quantity persistence through `MealSegment` plus `DiaryEntry`.
- Wired the checked-in compose stack so the official self-hosted Firecrawl `/search` path uses SearXNG JSON output and documented the runtime knobs and fallback expectation in `.env.example`.
- Cleaned up the authoritative save path so quantity JSON persists at the segment level, legacy bucket storage is removed from `meal_segments`, and `DiaryEntry.portion_bucket` is now derived from detailed quantity data instead of leading it.

## Task Commits

Each task was committed atomically:

1. **Task 1: RED - capture compose/runtime and quantity-migration regressions** - `b3971ce` (`test`)
2. **Task 2: GREEN - wire official Firecrawl search runtime, cleanup persistence, and lock verification** - `5d19a3b` (`feat`)

## Files Created/Modified
- `docker-compose.yml` - Added Firecrawl self-host search env wiring, SearXNG dependency, and resource-cap settings for the official `/search` stack.
- `.env.example` - Documented Firecrawl search backend knobs and the explicit direct-SearXNG fallback if self-host `/search` is unstable.
- `app/config.py` - Added typed runtime settings for Firecrawl search tuning, resource caps, and Phase 5 verification/fallback metadata.
- `app/models/meal_segment.py` - Replaced segment-level `portion_bucket` persistence with `quantity_json` and `quantity_display`.
- `app/models/diary_entry.py` - Marked `portion_bucket` as a compatibility mirror while keeping quantity JSON as the authoritative quantity surface.
- `app/services/interview_service.py` - Preserved bounded loop stop reasons on degraded saves and stopped retrying terminal timeout/call-cap exits.
- `app/services/meal_resolution_service.py` - Imported `MealSegment`, persisted segment quantity detail, and derived diary-entry buckets from `quantity_json`.
- `migrations/versions/phase5_grounding_quantity.py` - Added the meal-segment quantity migration and removed obsolete segment `portion_bucket` storage.
- `tests/test_grounding_service.py` - Locked compose/env runtime assumptions and the search-result-to-scrape happy path.
- `tests/test_interview_flow.py` - Locked bounded call-cap degradation to preserve `MAX_TOOL_CALLS` in failure metadata.
- `tests/test_match_flow.py` - Locked quantity persistence onto `MealSegment` and compatibility-bucket derivation on `DiaryEntry`.

## Decisions Made

- Kept the Firecrawl runtime on the official image shape and documented fallback behavior instead of drifting to an alternate stack with uncertain `/search` support.
- Limited schema cleanup to `meal_segments` in this slice: segment persistence now stores detailed quantity data directly, while `diary_entries` retains a derived legacy bucket for compatibility with existing readers.
- Treated bounded loop exits as deterministic degradation, not retryable noise, because a consumed call cap or wall-clock budget is already the terminal condition the plan wanted to verify.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Authoritative save path referenced `MealSegment` without importing it**
- **Found during:** Task 2 (GREEN - wire official Firecrawl search runtime, cleanup persistence, and lock verification)
- **Issue:** Once segment quantity persistence was exercised, `apply_final_meal_resolution()` raised `NameError: MealSegment is not defined`.
- **Fix:** Imported `MealSegment` into the save-path service and persisted segment quantity fields alongside `ai_reasoning`.
- **Files modified:** `app/services/meal_resolution_service.py`
- **Verification:** Targeted unittest suite passed in Docker after the fix.
- **Committed in:** `5d19a3b` (part of task commit)

**2. [Rule 1 - Bug] Bounded loop exits retried into generic tool-execution failures**
- **Found during:** Task 2 (GREEN - wire official Firecrawl search runtime, cleanup persistence, and lock verification)
- **Issue:** `MAX_TOOL_CALLS` exits were retried, which erased the intended timeout/call-cap classification and lost the loop stop reason.
- **Fix:** Preserved `loop_stop_reason` in grounding failures and stopped retrying terminal timeout-category failures.
- **Files modified:** `app/services/interview_service.py`
- **Verification:** Added regression passes in Docker, asserting degraded saves keep `MAX_TOOL_CALLS`.
- **Committed in:** `5d19a3b` (part of task commit)

---

**Total deviations:** 2 auto-fixed (2 rule-1 bugs)
**Impact on plan:** Both fixes were required to make the planned runtime verification surfaces truthful. No scope creep beyond the plan’s save-path and bounded-exit targets.

## Issues Encountered

- `rtk` was not installed in this executor environment, so shell verification fell back to direct commands.
- Host Python runners were not dependable in this worktree (`python` missing, `python3` hung), so automated verification ran in the existing `mealttracker-plan05-test` Docker image.
- The handed-off worktree did not include a local `.env`, so live `docker compose up -d` verification against a real runtime was not executed with fake secrets. Compose rendering was verified with `docker compose config` instead.

## User Setup Required

None - no new external service signup or dashboard setup is required. The local operator does need the new `.env.example` keys populated before running live Firecrawl `/search` probes during `$gsd-verify-work`.

## Next Phase Readiness

- Phase 5 now has checked-in runtime defaults that match the researched official Firecrawl + SearXNG architecture rather than only modeling it in application code.
- The next verification pass should use a real `.env` and run the live probes called for by the plan: Firecrawl `/search`, search-result-to-scrape, fabricated URL rejection, forced bounded degradation, and sequential scrape stability.

## Self-Check

PASSED

- Found `.planning/phases/05-agentic-grounding/05-03-SUMMARY.md`
- Found task commits `b3971ce` and `5d19a3b`
- Re-ran targeted verification: `docker run --rm -v "$PWD":/app -w /app mealttracker-plan05-test python -m unittest tests.test_grounding_service tests.test_interview_flow tests.test_match_flow -q`
- Validated compose rendering: `docker compose config`

---
*Phase: 05-agentic-grounding*
*Completed: 2026-06-04*
