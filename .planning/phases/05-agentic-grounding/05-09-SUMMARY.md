---
phase: 05-agentic-grounding
plan: 09
subsystem: api
tags: [grounding, finalizer, nutrition, provenance, tdd]
requires:
  - phase: 05-07
    provides: finalizer runtime gap fixes before safety closure
  - phase: 05-08
    provides: strict authoritative finalizer source typing
provides:
  - validated configurable finalizer output-token budget
  - service-layer save-ready invariant for successful finalizer outputs
  - regression coverage for truncated retry followed by null-macro finalizer output
affects: [interview, finalizer, grounding, meal-resolution, verification]
tech-stack:
  added: []
  patterns:
    - successful finalizer results are validated after parsing and before SUCCEEDED audit state
    - schema-valid but unusable finalizer payloads route through the existing degraded-save path
key-files:
  created:
    - .planning/phases/05-agentic-grounding/05-09-SUMMARY.md
  modified:
    - app/config.py
    - app/services/interview_service.py
    - tests/test_interview_schema.py
    - tests/test_interview_flow.py
    - tests/test_match_flow.py
key-decisions:
  - "Keep finalizer schema permissive for degraded fallback parsing, but enforce nutrition/provenance success invariants in the service before SUCCEEDED audit state."
  - "Use `FINALIZER_MAX_TOKENS` from runtime settings for finalizer LLM calls, with a default of 4096 and a lower bound of 2048."
patterns-established:
  - "Packaged or restaurant finalizer success requires searched provenance plus source URL or fetched URL evidence; complete HOME foods may succeed with model_knowledge provenance."
requirements-completed: [GROUND-01, GROUND-02]
duration: 11min
completed: 2026-06-05
---

# Phase 5 Plan 9: Agentic Grounding Summary

**Configurable finalizer token budget with save-ready nutrition and provenance guards**

## Performance

- **Duration:** 11 min
- **Started:** 2026-06-05T17:01:55Z
- **Completed:** 2026-06-05T17:12:14Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- Added RED regressions for the live UAT blocker: missing finalizer token config, hardcoded `1200` max tokens, and truncated retry followed by null-macro unverified output.
- Added `Settings.FINALIZER_MAX_TOKENS` with a 4096 default and 2048 lower bound, then threaded it into `_bounded_group_finalizer_response()`.
- Added a service-layer finalizer success check requiring complete nutrition, `is_verified=true`, valid provenance, and searched URL evidence for packaged/restaurant outcomes.
- Preserved D-17 behavior: complete verified HOME foods can still succeed with `provenance="model_knowledge"`.

## Task Commits

1. **Task 1: RED - capture finalizer truncation and unusable success output** - `cd858ef` (test)
2. **Task 2: GREEN - make finalizer success require usable nutrition and provenance** - `faca752` (feat)

**Plan metadata:** recorded in the docs commit for this summary

## Files Created/Modified

- `app/config.py` - Adds validated `FINALIZER_MAX_TOKENS`.
- `app/services/interview_service.py` - Uses the config-driven token budget and rejects unusable parsed finalizer output before `SUCCEEDED`.
- `tests/test_interview_schema.py` - Covers finalizer max-token config default and lower-bound validation.
- `tests/test_interview_flow.py` - Covers max-token propagation, null-macro retry degradation, and HOME/model-knowledge success.
- `tests/test_match_flow.py` - Updates an existing successful HOME fixture with explicit `model_knowledge` provenance.
- `.planning/phases/05-agentic-grounding/05-09-SUMMARY.md` - Records plan outcome.

## Decisions Made

- Enforced success readiness in `interview_service` rather than `interview_schema` so schema-valid degraded payloads can still be audited and saved as best-effort failures.
- Treated parsed-but-empty nutrition as an `InterviewTurnValidationError`, reusing the existing failed-attempt and degraded-save path.
- Kept the module-level `FINALIZER_MAX_TOKENS` as a 4096 compatibility default, but the LLM call reads `settings.FINALIZER_MAX_TOKENS`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Used available Phase 05 verification artifact for missing UAT path**
- **Found during:** Task 1 context load
- **Issue:** The plan referenced `.planning/phases/05-agentic-grounding/05-UAT.md`, but that file was absent from the worktree.
- **Fix:** Loaded `.planning/phases/05-agentic-grounding/05-VERIFICATION.md`, which contained the Phase 05 UAT/verification gap context for this blocker.
- **Files modified:** None
- **Verification:** Continued after confirming the phase directory contained `05-VERIFICATION.md` and no `05-UAT.md`.
- **Committed in:** Not applicable

**2. [Rule 1 - Bug] Updated stale success fixture to include provenance**
- **Found during:** Task 2 full Phase 05 regression run
- **Issue:** `tests/test_match_flow.py` had a HOME finalizer success fixture with complete macros and `is_verified=true` but no explicit provenance, so the new success invariant correctly degraded it.
- **Fix:** Added `provenance="model_knowledge"` and matching trace provenance to the fixture.
- **Files modified:** `tests/test_match_flow.py`
- **Verification:** Full Phase 05 regression suite passed.
- **Committed in:** `faca752`

---

**Total deviations:** 2 auto-fixed (1 Rule 3, 1 Rule 1)
**Impact on plan:** Both deviations were necessary to complete the planned validation without expanding runtime scope.

## Issues Encountered

None beyond the documented deviations.

## Known Stubs

None. Stub scan hits were existing optional defaults and test-local capture lists, not UI/data-flow stubs.

## Auth Gates

None.

## Verification

- `rtk docker run --rm -v "$PWD":/app -w /app mealttracker-plan05-test python -m unittest tests.test_interview_schema tests.test_interview_flow -q` - passed, 70 tests.
- `rtk docker run --rm -v "$PWD":/app -w /app mealttracker-plan05-test python -m unittest tests.test_reasoning_contract tests.test_reasoning_flow tests.test_grounding_service tests.test_interview_flow tests.test_match_flow tests.test_bot_contract -q` - passed, 195 tests. Expected mocked-error log output was emitted by existing bot contract tests.

## TDD Gate Compliance

- RED commit present: `cd858ef`
- GREEN commit present after RED: `faca752`
- Refactor commit: not needed

## Next Phase Readiness

- The finalizer can emit larger realistic JSON without the Phase 05 hardcoded 1200-token cap.
- Null nutrition and unverified provenance can no longer become a `SUCCEEDED` finalizer group.
- Downstream completion still uses the existing degraded-save semantics for unusable finalizer output, with visual learning disabled.

## Self-Check: PASSED

- Found `.planning/phases/05-agentic-grounding/05-09-SUMMARY.md` on disk.
- Found task commit `cd858ef` in git history.
- Found task commit `faca752` in git history.
- Verified both plan-level test commands passed after task commits.

---
*Phase: 05-agentic-grounding*
*Completed: 2026-06-05*
