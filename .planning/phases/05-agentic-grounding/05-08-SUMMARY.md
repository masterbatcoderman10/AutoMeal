---
phase: 05-agentic-grounding
plan: 08
subsystem: api
tags: [grounding, finalizer, schema, safety, tdd]
requires:
  - phase: 05-05
    provides: inline grouped finalizer, degraded-save grounding failure path
provides:
  - authoritative finalizer-facing source types are validated strictly
  - malformed finalizer source types degrade explicitly instead of silently becoming HOME
  - authoritative grounding prep can reject invalid source types on the strict path
affects: [interview, finalizer, grounding, schema, verification]
tech-stack:
  added: []
  patterns:
    - authoritative model-emitted enums use strict validation instead of permissive normalization
    - invalid finalizer payloads degrade through the existing failure path rather than creating plausible fallback saves
key-files:
  created:
    - .planning/phases/05-agentic-grounding/05-08-SUMMARY.md
  modified:
    - app/services/grounding_stub.py
    - app/services/interview_schema.py
    - app/services/interview_service.py
    - tests/test_interview_schema.py
    - tests/test_interview_flow.py
key-decisions:
  - "Keep permissive normalization for general user-input paths, but require strict authoritative source typing at the confirmation and finalizer seam."
  - "Finalizer payloads with invalid authoritative source types degrade through the existing tool-execution failure path instead of being coerced to HOME."
patterns-established:
  - "Grounding helper functions can expose an opt-in strict mode so authoritative flows reject malformed enums without destabilizing broader parsing paths."
requirements-completed: [GROUND-01]
duration: 16min
completed: 2026-06-05
---

# Phase 5 Plan 8: Agentic Grounding Summary

**Strict authoritative `source_type` validation for confirmation and finalizer flows**

## Performance

- **Duration:** 16 min
- **Started:** 2026-06-05T07:18:00Z
- **Completed:** 2026-06-05T07:34:00Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- Added RED regressions proving invalid authoritative `source_type` values were silently normalized to `HOME`.
- Made `ConfirmationItem` and `FinalizedGroupResult` reject malformed authoritative source types explicitly.
- Routed malformed finalizer output into the existing degraded-save path instead of allowing packaged or restaurant grounding intent to disappear.

## Task Commits

No git commits were created during this inline execution run.

## Files Created/Modified
- `app/services/grounding_stub.py` - adds strict authoritative source parsing and an opt-in strict grounding-prep path.
- `app/services/interview_schema.py` - validates authoritative `source_type` values strictly for confirmation and finalizer contracts.
- `app/services/interview_service.py` - uses strict source validation on the successful finalizer path while preserving degraded-save behavior on invalid finalizer output.
- `tests/test_interview_schema.py` - covers invalid authoritative `source_type` rejection.
- `tests/test_interview_flow.py` - proves malformed finalizer source typing degrades explicitly instead of suppressing grounding.

## Decisions Made
- Limited strictness to the authoritative seam so general interview parsing can keep its existing permissive normalization behavior.
- Reused the current degraded finalizer outcome path rather than inventing a new runtime status for malformed authoritative source types.

## Deviations from Plan

None - plan executed within the intended scope.

## Issues Encountered

- The existing contract models normalized invalid source values before enum validation could fail. The fix moved strictness into the field validators themselves so the failure happens at the schema boundary.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Finalizer-emitted packaged or restaurant intent can no longer be silently downgraded to HOME.
- The last authoritative source-typing gap is now covered by schema and runtime regressions.

## Verification

- `rtk docker run --rm -v "$PWD":/app -w /app mealttracker-plan05-test python -m unittest tests.test_interview_schema tests.test_interview_flow -q`
- `rtk docker run --rm -v "$PWD":/app -w /app mealttracker-plan05-test python -m unittest tests.test_reasoning_contract tests.test_reasoning_flow tests.test_grounding_service tests.test_interview_flow tests.test_match_flow tests.test_bot_contract -q`

## Self-Check: PASSED

- Verified `.planning/phases/05-agentic-grounding/05-08-SUMMARY.md` exists on disk.
- Verified the targeted and full Phase 05 validation commands passed after the fix.
