---
phase: 04-reason-interview-learning-loop
plan: 08
subsystem: infra
tags: [apscheduler, recovery, telegram, unittest, fastapi]
requires:
  - phase: 04-05
    provides: persisted segment embeddings, candidate snapshots, and reasoning-state writes
  - phase: 04-06
    provides: durable interview session state for waiting-user recovery
provides:
  - artifact-first janitor recovery planning for stale machine-stage meals
  - single-instance APScheduler wiring for periodic recovery ticks
  - live crash-recovery smoke helper that reuses production janitor logic
affects: [reasoning, interview, bot-polling, scheduler]
tech-stack:
  added: []
  patterns: [artifact-backed recovery inference, stamped machine-stage timestamps, single-instance APScheduler janitor]
key-files:
  created:
    - app/services/recovery_service.py
    - scripts/assert_janitor_red.py
    - scripts/recovery_smoke.py
    - tests/__init__.py
  modified:
    - app/main.py
    - bot/polling.py
    - tests/test_janitor.py
key-decisions:
  - "Janitor recovery resumes from the most durable artifact boundary: interview session, candidate snapshots, embeddings, then crops."
  - "Worker stage transitions stamp `last_stage_started_at` and preserve `recovery_attempt_count` so stale detection is deterministic across crashes."
  - "The FastAPI scheduler owns the janitor tick with `max_instances=1` and `coalesce=True` to avoid overlapping recovery mutations."
patterns-established:
  - "Recovery planning stays mostly pure and dict-driven so tests, smoke scripts, and the scheduler all exercise the same logic."
  - "Reasoning inputs are committed before the reasoning call so janitor replay can resume from persisted candidate snapshots."
requirements-completed: [INFRA-04, PIPELINE-01]
duration: 14min
completed: 2026-05-28
---

# Phase 4 Plan 08: Janitor Recovery Summary

**Artifact-first stale-meal recovery with a single-instance APScheduler janitor, stamped worker stages, and a DB-backed crash-recovery smoke helper**

## Performance

- **Duration:** 14 min
- **Started:** 2026-05-28T17:57:07.016000+00:00
- **Completed:** 2026-05-28T18:12:05.970446+00:00
- **Tasks:** 3
- **Files modified:** 7

## Accomplishments

- Added a janitor recovery service that classifies stale machine-stage meals from persisted interview state, candidate snapshots, embeddings, and crop artifacts before deciding whether to resume or fail.
- Wired the FastAPI scheduler to run the janitor as a single in-flight interval job and updated polling workers to stamp machine-stage timestamps around every durable stage transition.
- Added both a strict RED harness for the janitor contract and a live smoke script that inspects or applies the production recovery path for a real meal row.

## Task Commits

1. **Task 1: RED - run the Wave 0 janitor module as the failing recovery contract** - `bebef40` (`test`)
2. **Task 2: GREEN - implement recovery service, scheduler job, and stage timestamp stamping** - `70be08b` (`feat`)
3. **Task 3: REFACTOR - add a crash-recovery smoke helper for live worker-kill verification** - `951e7d1` (`refactor`)

## Files Created/Modified

- `app/services/recovery_service.py` - Pure recovery planner plus DB-backed janitor execution and inspection helpers.
- `app/main.py` - APScheduler janitor registration inside FastAPI lifespan with single-instance guardrails.
- `bot/polling.py` - Centralized stage-transition stamping for durable `last_stage_started_at` metadata.
- `tests/test_janitor.py` - Recovery contract coverage for artifact-backed resume, stale exclusion, and one-notification failure exhaustion.
- `scripts/assert_janitor_red.py` - Machine-checkable RED harness for the named janitor contract failures.
- `scripts/recovery_smoke.py` - Live inspection/apply helper for crash-recovery verification against a real database.
- `tests/__init__.py` - Makes the plan-mandated `python -m unittest tests.test_janitor` invocation importable.

## Verification

- `rtk proxy .venv/bin/python scripts/assert_janitor_red.py --expect tests.test_janitor.JanitorTests.test_stale_reasoning_resumes_from_last_safe_artifact_stage --expect tests.test_janitor.JanitorTests.test_failed_after_three_recoveries_notifies_once` during RED: passed by observing the expected assertion failures only.
- `rtk proxy .venv/bin/python -m unittest tests.test_janitor -q`: passed.
- `rtk proxy .venv/bin/python scripts/recovery_smoke.py --help`: passed.
- `rtk rg -n "meal-janitor|max_instances=1|coalesce=True|last_stage_started_at|recovery_attempt_count" app/main.py app/services/recovery_service.py bot/polling.py`: passed.

## Decisions Made

- Resume from `INTERVIEWING` immediately when an active interview session already exists; this avoids replaying reasoning and re-sending unresolved prompts.
- Treat candidate snapshots as the durable boundary for rerunning `REASONING`, embeddings as the durable boundary for rerunning `MATCHING`, and crop paths as the durable boundary for rerunning `EMBEDDING`.
- Persist the janitor’s last action into `reasoning_state_json["janitor"]` instead of adding new schema fields mid-phase.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added test-package plumbing for the mandated unittest command**
- **Found during:** Task 1 (RED harness)
- **Issue:** `python -m unittest tests.test_janitor` could not import `tests.test_janitor` because `tests/` was not a Python package.
- **Fix:** Added `tests/__init__.py` so the plan’s explicit unittest invocation resolves consistently from the repo root.
- **Files modified:** `tests/__init__.py`
- **Verification:** The RED harness loaded the named tests successfully, and the later full `unittest` command passed.
- **Committed in:** `bebef40`

---

**Total deviations:** 1 auto-fixed (Rule 3: 1)
**Impact on plan:** No scope creep. The deviation only made the plan’s required verification command executable.

## Issues Encountered

- The handed-off worktree had no local `.venv`, and the machine defaulted to Python `3.14.4`, which could not build pinned wheels such as `orjson==3.10.12` and `pydantic-core==2.27.1`. Recreated the worktree virtualenv with `/Users/mali/.local/bin/python3.12` and installed the pinned requirements successfully.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Janitor recovery now has both automated contract coverage and a live smoke path for a real worker-kill scenario.
- The next phase can assume stale machine-stage meals either resume from persisted artifacts or fail once with duplicate notifications suppressed.

## Self-Check: PASSED

- Summary file present at `.planning/phases/04-reason-interview-learning-loop/04-08-SUMMARY.md`
- Task commits found: `bebef40`, `70be08b`, `951e7d1`
