---
phase: 05-agentic-grounding
plan: 11
subsystem: agentic-grounding
tags: [finalizer, grounding, citations, tdd, fastapi]

requires:
  - phase: 05-agentic-grounding
    provides: "05-10 finalizer prompt context and live Langfuse gap evidence"
provides:
  - "Draft-only finalizer schema where the model owns food identity, quantity, nutrition, confidence, and selected source IDs"
  - "Service-derived finalizer provenance, verification, source URLs, and grounding trace metadata"
  - "Deterministic source registry with selected-source citation resolution"
  - "High finite finalizer output cap and fail-closed all-degraded state handling"
affects: [phase-05, interview-finalizer, grounding, telegram-confirmation]

tech-stack:
  added: []
  patterns:
    - "Model output schemas exclude service-owned audit/provenance fields"
    - "Finalizer citations resolve through service-generated source IDs"
    - "All-degraded finalizer outcomes fail closed with MealProcessingStatus.FAILED"

key-files:
  created:
    - ".planning/phases/05-agentic-grounding/05-11-SUMMARY.md"
  modified:
    - "app/config.py"
    - "app/services/interview_schema.py"
    - "app/services/interview_service.py"
    - "tests/test_interview_schema.py"
    - "tests/test_interview_flow.py"
    - "tests/test_match_flow.py"
    - "tests/test_reasoning_contract.py"

key-decisions:
  - "The model-facing finalizer schema is a draft schema; the service derives verification, provenance, source_url, and grounding_trace."
  - "Packaged, store-bought, and restaurant finalizer success requires selected source IDs that resolve to same-loop source registry entries."
  - "All finalizer groups degrading is a failed meal finalization, not a completed degraded save."

patterns-established:
  - "Source registry IDs (`src_1`, `src_2`, ...) are the only citation handles a finalizer draft can select."
  - "HOME/HOME_COOKED complete nutrition promotes to service-derived `model_knowledge` provenance when confidence is explicit and above threshold."
  - "Finalizer output uses `FINALIZER_OUTPUT_MAX_TOKENS=12000` instead of the old 4096 cap or an unbounded call."

requirements-completed: [GROUND-01, GROUND-02, GROUND-03]

duration: 23min
completed: 2026-06-06
---

# Phase 05 Plan 11: Finalizer Schema Ownership Summary

**Draft-only finalizer output with deterministic service-owned provenance, bounded output, and fail-closed degraded finalization**

## Performance

- **Duration:** 23 min
- **Started:** 2026-06-06T15:30:09Z
- **Completed:** 2026-06-06T15:53:15Z
- **Tasks:** 5
- **Files modified:** 7

## Accomplishments

- Removed model-authored `is_verified`, `provenance`, `source_url`, and `grounding_trace` from the finalizer response schema.
- Added selected-source citation resolution through a deterministic source registry populated by the finalizer tool loop.
- Added `FINALIZER_OUTPUT_MAX_TOKENS=12000` and wired it into finalizer chat completions.
- Changed all-degraded finalizer runs to write `MealProcessingStatus.FAILED` with `ALL_FINALIZER_GROUPS_DEGRADED`, using no final segments.

## Task Commits

Each task was committed atomically; TDD tasks produced RED and GREEN commits where applicable:

1. **Task 1: RED - lock model-owned finalizer schema** - `ca38b96` (test)
2. **Task 2: GREEN - split draft output from deterministic finalization metadata** - `104b137` (feat)
3. **Task 3: RED/GREEN - add deterministic source registry and bounded citation contract** - `4e87bbd` (test), `854e9e9` (feat)
4. **Task 4: RED/GREEN - contain runaway outputs without restoring the 4096 cap** - `184ce33` (test), `597e6cb` (feat)
5. **Task 5: RED/GREEN - fail closed when every group degrades** - `4b28ca9` (test), `0e9ccfa` (feat)
6. **Verification contract fix** - `eb7e033` (test)

## Files Created/Modified

- `app/config.py` - Added and validated the high finite finalizer output cap.
- `app/services/interview_schema.py` - Converted the finalizer response to draft-owned fields plus `confidence` and `selected_source_ids`.
- `app/services/interview_service.py` - Added source registry capture, source ID promotion, service-owned metadata derivation, bounded finalizer output, and all-degraded failure handling.
- `tests/test_interview_schema.py` - Added schema ownership and output-cap regression coverage.
- `tests/test_interview_flow.py` - Added finalizer promotion, source registry, malformed output, and all-degraded flow regressions.
- `tests/test_match_flow.py` - Updated finalizer fixture to the draft-only schema.
- `tests/test_reasoning_contract.py` - Updated finalizer contract expectations to the new schema boundary.

## Decisions Made

- Keep `FinalizedGroupResult` as the model-facing draft class name for compatibility, but remove service-owned fields from it.
- Store deterministic source registry entries in the service trace and allow the model to select only `selected_source_ids`.
- Use `MealProcessingStatus.FAILED` for all-degraded finalizer runs instead of a completed degraded save.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fixed missing `ValidationError` import in schema tests**
- **Found during:** Task 1 RED verification
- **Issue:** Existing schema tests referenced `ValidationError` without importing it, causing unrelated errors before the intended RED failures.
- **Fix:** Added the missing `pydantic.ValidationError` import in `tests/test_interview_schema.py`.
- **Verification:** RED rerun failed only on the intended finalizer ownership assertions.
- **Committed in:** `ca38b96`

**2. [Rule 3 - Blocking] Updated stale finalizer contract fixtures after schema split**
- **Found during:** Task 5 and plan-level verification
- **Issue:** `tests/test_match_flow.py` and `tests/test_reasoning_contract.py` still expected model-authored provenance/trace fields.
- **Fix:** Updated fixtures and contract assertions to the draft-only finalizer schema.
- **Verification:** Broad Phase 05 regression suite passed.
- **Committed in:** `4b28ca9`, `eb7e033`

---

**Total deviations:** 2 auto-fixed blocking issues
**Impact on plan:** Both fixes were required to keep the regression suite aligned with the planned model/service ownership split.

## Issues Encountered

- Python bytecode in the containerized test mount repeatedly surfaced stale parser errors immediately after rapid edits. Direct `compile()` checks against mounted source succeeded, and reruns passed.
- `rtk docker compose up -d --build api bot` and `rtk docker compose up -d --no-deps --build api bot` built the `api` and `bot` images, but deploy was blocked by fixed live container names already in use: `mealttracker-postgres` and `mealttracker-api`. The worktree also lacked local secret env vars. I did not remove or rename the live healthy stack from this executor worktree.
- Live Telegram confirmation, Langfuse inspection, and Postgres inspection were not run because the updated worktree images could not be safely deployed over the existing fixed-name live stack.

## Verification

Passed:

- `rtk docker run --rm -v "$PWD":/app -w /app mealttracker-plan05-test python -m unittest tests.test_interview_schema tests.test_interview_flow -q`
- `rtk docker run --rm -v "$PWD":/app -w /app mealttracker-plan05-test python -m unittest tests.test_reasoning_contract tests.test_reasoning_flow tests.test_grounding_service tests.test_interview_flow tests.test_match_flow tests.test_bot_contract -q`

Partially completed:

- `rtk docker compose up -d --build api bot` built images, then failed on existing `mealttracker-postgres` container-name conflict.
- `rtk docker compose up -d --no-deps --build api bot` built images, then failed on existing `mealttracker-api` container-name conflict.

Not completed:

- Live Telegram confirmation plus Langfuse/Postgres inspection, blocked by deploy conflict and missing worktree env secrets.

## Known Stubs

None. Stub-pattern scan found only intentional test fixtures, empty containers, and nullable values used in tests or validation paths.

## Threat Flags

None. This plan changed finalizer schema/promotion logic and tests; it did not introduce new network endpoints, auth paths, file access patterns, or schema changes at a trust boundary beyond the threat model already listed in the plan.

## User Setup Required

None for code. Live verification requires running the updated code in the existing single live stack or changing compose container names for isolated worktree deployment.

## Next Phase Readiness

The finalizer now produces draft nutrition facts while the service owns provenance, citations, trace state, and completion status. Before marking Phase 05 UAT fully closed, redeploy the main stack from the merged branch and run the live Telegram/Langfuse/Postgres checks from the plan.

## Self-Check: PASSED

Verified all modified files and the summary exist, and verified all task/verification commits are present in git history.

---
*Phase: 05-agentic-grounding*
*Completed: 2026-06-06*
