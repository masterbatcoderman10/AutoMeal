---
phase: 05-agentic-grounding
plan: 05
subsystem: api
tags: [grounding, safety, matching, telegram, tdd]
requires:
  - phase: 05-04
    provides: shared bounded finalizer, live grounding trace persistence, post-interview grounding completion path
provides:
  - degraded or unverified grounding results can no longer create FoodVisual learning rows
  - matcher corpus only considers verified FoodItems behind non-invalidated FoodVisuals
  - tool evidence is sanitized and explicitly marked untrusted before re-entering model context
  - dead grounding polling workers and handoff helpers are removed from bot runtime
affects: [grounding, interview, matching, runtime-cleanup, verification]
tech-stack:
  added: []
  patterns:
    - defense-in-depth visual learning guard at both finalizer and authoritative save boundaries
    - sanitized tool evidence envelope for model-visible search and scrape results
    - deletion over deactivation for dead runtime entry points
key-files:
  created:
    - .planning/phases/05-agentic-grounding/05-05-SUMMARY.md
  modified:
    - app/services/interview_service.py
    - app/services/meal_resolution_service.py
    - app/services/matching_service.py
    - bot/polling.py
    - tests/test_interview_flow.py
    - tests/test_match_flow.py
    - tests/test_bot_contract.py
key-decisions:
  - "Only verified final resolutions may request visual learning, even if an upstream caller still sets create_food_visual."
  - "Grounding tool outputs re-enter the model only through a bounded title/url/snippet evidence envelope marked as untrusted."
  - "The obsolete GROUNDING_PENDING polling runtime was removed instead of preserved behind dead helpers."
patterns-established:
  - "Degraded grounding saves remain writable for diary completion but are excluded from future corpus growth."
  - "Similarity search trusts both FoodVisual invalidation state and FoodItem verification state."
requirements-completed: [GROUND-01, GROUND-02, GROUND-03]
duration: 20min
completed: 2026-06-04
---

# Phase 5 Plan 5: Agentic Grounding Summary

**Verified-only learning guards, sanitized grounding evidence envelopes, and removal of the dead GROUNDING_PENDING polling runtime**

## Performance

- **Duration:** 20 min
- **Started:** 2026-06-04T19:20:00Z
- **Completed:** 2026-06-04T19:39:52Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments
- Prevented degraded, pending-grounding, and otherwise unverified finalizations from creating new `FoodVisual` rows.
- Restricted similarity matching to verified `FoodItem` records and sanitized tool output before it re-entered the finalizer prompt.
- Removed the obsolete grounding handoff pollers and their broken helper surface from [bot/polling.py](/var/folders/r5/qpbtpqpj5j54bw2w5_jvbxw00000gn/T//gsd-executor-05-05-05-8MeMKR/bot/polling.py).

## Task Commits

Each task was committed atomically:

1. **Task 1: RED - reproduce degraded-learning, verified-corpus, prompt-hardening, and dead-worker regressions** - `1ce678f` (test)
2. **Task 2: GREEN - block unsafe learning, sanitize tool evidence, and remove the dead grounding runtime** - `bda16c3` (feat)

## Files Created/Modified
- `app/services/interview_service.py` - blocks degraded visual learning and sanitizes model-visible tool evidence.
- `app/services/meal_resolution_service.py` - enforces verified-only visual persistence at the authoritative save boundary.
- `app/services/matching_service.py` - filters the match corpus to verified food items only.
- `bot/polling.py` - removes dead grounding polling workers and helper code tied to deleted handoff APIs.
- `tests/test_interview_flow.py` - covers degraded-save learning guards and tool-evidence prompt hardening.
- `tests/test_match_flow.py` - covers verified-only matching and authoritative visual-write blocking.
- `tests/test_bot_contract.py` - locks out the removed grounding worker symbols from the bot runtime contract.

## Decisions Made
- Learning eligibility is now derived from final verification state, not just from the presence of a crop and embedding.
- Raw search and scrape JSON no longer re-enters the model; only bounded `title` / `url` / `snippet` evidence survives.
- The dead grounding runtime was deleted outright so broken handoff code cannot accidentally re-activate in production.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Isolated grouped auto-confirm tests from live finalizer dependencies**
- **Found during:** Task 1 and Task 2 verification
- **Issue:** Existing grouped reasoning tests in `tests/test_match_flow.py` relied on live settings and finalizer behavior, which made the plan's targeted command non-deterministic in the executor container.
- **Fix:** Added local `_run_group_finalizers` stubs inside the affected tests so the targeted suite stays hermetic while preserving each test's intended naming assertions.
- **Files modified:** `tests/test_match_flow.py`
- **Verification:** `rtk docker run --rm -v "$PWD":/app -w /app mealttracker-plan05-test python -m unittest tests.test_interview_flow tests.test_match_flow tests.test_bot_contract -q`
- **Committed in:** `1ce678f` and `bda16c3`

---

**Total deviations:** 1 auto-fixed (Rule 3)
**Impact on plan:** Verification became deterministic without changing production scope; all planned safety fixes still landed in live code.

## Issues Encountered

- The targeted suites initially picked up non-hermetic grouped-finalizer behavior and missing test-environment assumptions. Those checks were localized in test doubles so the plan's RED/GREEN loop measured only the intended grounding-safety changes.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Grounding failures can still produce a best-effort meal write, but they no longer poison the learned visual corpus.
- Matching and prompt hardening now align with the Phase 5 verification gaps, and the legacy polling runtime has been removed cleanly.

## Self-Check: PASSED

- Verified summary file exists on disk.
- Verified task commits `1ce678f` and `bda16c3` exist in git history.
