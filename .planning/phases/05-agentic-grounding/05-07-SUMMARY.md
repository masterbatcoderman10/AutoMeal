---
phase: 05-agentic-grounding
plan: 07
subsystem: api
tags: [grounding, polling, concurrency, runtime, tdd]
requires:
  - phase: 05-06
    provides: fail-closed reasoning fallback, durable embedding and matching claims
provides:
  - detecting and segmenting workers keep exclusive ownership through slow stage work
  - zero-segment MATCHING meals fail immediately instead of stranding in REASONING
affects: [polling, matching, runtime, verification]
tech-stack:
  added: []
  patterns:
    - slow poller stages hold the row claim until the meal leaves that stage
    - malformed runtime prerequisites fail closed instead of parking in an unconsumed state
key-files:
  created:
    - .planning/phases/05-agentic-grounding/05-07-SUMMARY.md
  modified:
    - bot/polling.py
    - tests/test_bot_contract.py
    - tests/test_match_flow.py
key-decisions:
  - "Detect and segment now follow the same durable-claim pattern already established for embedding and matching."
  - "A MATCHING meal without segment rows is treated as a live runtime failure, not as a REASONING handoff."
patterns-established:
  - "Concurrency regressions use blocked-worker harnesses that assert ownership at the row-claim boundary, not just after downstream side effects."
  - "Poller stages do not need new statuses to enforce single ownership; one transaction boundary per stage is enough."
requirements-completed: [GROUND-02]
duration: 18min
completed: 2026-06-05
---

# Phase 5 Plan 7: Agentic Grounding Summary

**Durable DETECTING and SEGMENTING claims plus a fail-closed zero-segment MATCHING exit**

## Performance

- **Duration:** 18 min
- **Started:** 2026-06-05T07:00:00Z
- **Completed:** 2026-06-05T07:18:00Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Added RED regressions proving a second worker could steal a DETECTING or SEGMENTING meal while the first worker was still inside slow stage work.
- Kept detect and segment row ownership alive until the stage transitions out of the claimed state.
- Replaced the zero-segment MATCHING handoff to bare `REASONING` with an immediate fail-closed runtime outcome.

## Task Commits

No git commits were created during this inline execution run.

## Files Created/Modified
- `bot/polling.py` - holds detect and segment claims through slow work and fails zero-segment matching meals immediately.
- `tests/test_bot_contract.py` - adds blocked-worker regressions for detect and segment ownership.
- `tests/test_match_flow.py` - proves zero-segment MATCHING meals fail instead of stranding.

## Decisions Made
- Reused the existing `skip_locked` pattern and fixed claim lifetime rather than adding new statuses or queue machinery.
- Treated missing segments in MATCHING as a terminal runtime defect because no live worker consumes the old `REASONING` transition.

## Deviations from Plan

None - plan executed within the intended scope.

## Issues Encountered

- The old detect-stage tests asserted the early-commit behavior directly through commit counts. Those assertions were updated to match the durable-claim contract instead of the previous bug.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- The remaining Phase 05 runtime-cap hole is closed from detect through matching.
- The targeted poller and matching regressions are now locked by automated tests.

## Verification

- `rtk docker run --rm -v "$PWD":/app -w /app mealttracker-plan05-test python -m unittest tests.test_bot_contract tests.test_match_flow -q`
- `rtk docker run --rm -v "$PWD":/app -w /app mealttracker-plan05-test python -m unittest tests.test_reasoning_contract tests.test_reasoning_flow tests.test_grounding_service tests.test_interview_flow tests.test_match_flow tests.test_bot_contract -q`

## Self-Check: PASSED

- Verified `.planning/phases/05-agentic-grounding/05-07-SUMMARY.md` exists on disk.
- Verified the targeted and full Phase 05 validation commands passed after the fix.
