---
phase: 05-agentic-grounding
plan: 06
subsystem: api
tags: [grounding, reasoning, polling, concurrency, tdd]
requires:
  - phase: 05-05
    provides: shared bounded finalizer, verified-only match corpus, sanitized tool evidence
provides:
  - reasoning failures with strong cached candidates stay fail-closed instead of synthesizing save-ready fallback groups
  - embedding and matching workers keep exclusive meal ownership until the stage advances or fails
affects: [reasoning, polling, matching, verification]
tech-stack:
  added: []
  patterns:
    - fail-closed fallback groups preserve review or failure state after unusable reasoning output
    - slow polling stages hold the row claim until status changes out of the claimed stage
key-files:
  created:
    - .planning/phases/05-agentic-grounding/05-06-SUMMARY.md
  modified:
    - app/services/reasoning_service.py
    - bot/polling.py
    - tests/test_reasoning_flow.py
    - tests/test_match_flow.py
    - tests/test_bot_contract.py
key-decisions:
  - "Preserve cached vector candidates for audit and review only when reasoning fails; never upgrade those failures into AUTO_CONFIRM or READY_TO_WRITE."
  - "Keep the existing skip_locked workflow, but hold the claim until EMBEDDING or MATCHING finishes instead of releasing it at an early commit."
patterns-established:
  - "Reasoning fallback may preserve candidate context, but meal-level FAILED_UNCLEAR must win over generic interview routing."
  - "Polling stages can use a single transaction boundary to enforce one owner per meal without new enums or migrations."
requirements-completed: [GROUND-01, GROUND-02]
duration: 13min
completed: 2026-06-05
---

# Phase 5 Plan 6: Agentic Grounding Summary

**Fail-closed reasoning fallback with durable single-worker ownership across embedding and matching stages**

## Performance

- **Duration:** 13 min
- **Started:** 2026-06-05T01:30:00Z
- **Completed:** 2026-06-05T01:42:50Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- Added RED regressions that reproduce the strong-vector reasoning bypass and the duplicate-worker ownership hole.
- Prevented unusable reasoning output from synthesizing save-ready fallback groups while still preserving cached candidates for review.
- Kept `EMBEDDING` and `MATCHING` meal claims exclusive until the stage advances, which blocks duplicate reasoning, finalization, and completion notifications.

## Task Commits

Each task was committed atomically:

1. **Task 1: RED - capture the reasoning-fallback bypass and duplicate-worker claim regressions** - `42b8ba7` (test)
2. **Task 2: GREEN - make reasoning failure fail closed and keep stage claims durable through slow work** - `bc93eae` (fix)

## Files Created/Modified
- `app/services/reasoning_service.py` - preserves failure or review state when fallback groups are synthesized after unusable reasoning output.
- `bot/polling.py` - removes the early claim-release commits from embedding and matching stage workers.
- `tests/test_reasoning_flow.py` - locks the strong-vector reasoning failure path and helper behavior.
- `tests/test_match_flow.py` - proves a second embed poller cannot steal the same in-flight meal.
- `tests/test_bot_contract.py` - proves a second matching poller cannot duplicate reasoning or completion side effects.

## Decisions Made
- Reused the existing fallback-group helper, but made failure-state propagation explicit so compatibility paths still work while failure paths stay closed.
- Solved the worker race by extending the existing transaction boundary rather than adding new processing statuses or schema changes.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- The new concurrency regressions initially assumed the buggy early-commit timing. The harness was tightened to model claim ownership directly so it stays valid after the fix.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- The two remaining Phase 05 verification blockers are closed in code and locked by regression coverage.
- Phase 05 targeted verification remains green after the gap closure.

## Self-Check: PASSED

- Verified `.planning/phases/05-agentic-grounding/05-06-SUMMARY.md` exists on disk.
- Verified task commits `42b8ba7` and `bc93eae` exist in git history.
