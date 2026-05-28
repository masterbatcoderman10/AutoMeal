# Phase 04: Reasoning happy path and bounded match fan-out

---
phase: 04-reason-interview-learning-loop
plan: 05
subsystem: pipeline
tags: [reasoning, matching, telegram, smoke]

# Dependency graph
requires:
  - phase: 04-runtime-interfaces
    provides: shared final-write service, reasoning config, and tracing wrapper from 04-04
provides:
  - strict meal-level reasoning response contract and deterministic gate
  - top-3 match candidate snapshots before final write
  - bounded parallel segment matching before one meal-level reasoning call
  - reasoning-probe smoke path through production matching/reasoning services
affects:
  - 04-reason-interview-learning-loop
  - 05

# Tech tracking
tech-stack:
  added: []
  patterns:
    - strict JSON schema normalization with unknown action fallback to NEEDS_SCHEMA_REVIEW
    - deterministic gate over similarity threshold, candidate margin, missing evidence, and nutrition impact
    - semaphore-bounded per-segment match preparation followed by single meal-level reasoning

key-files:
  created:
    - app/services/reasoning_schema.py
    - app/services/reasoning_service.py
  modified:
    - app/services/matching_service.py
    - bot/polling.py
    - bot/messages.py
    - scripts/embed_match_smoke.py
    - tests/test_reasoning_contract.py
    - tests/test_reasoning_gate.py
    - tests/test_reasoning_flow.py
    - tests/test_parallel_pipeline.py
    - tests/test_embed_match_smoke.py
    - tests/test_match_flow.py
    - tests/test_matching_threshold.py

key-decisions:
  - Every segmented meal now passes through meal-level reasoning before completion; similarity alone no longer writes DiaryEntry rows.
  - Keep `action` open-string in the schema, but route unknown or missing actions to `NEEDS_SCHEMA_REVIEW`.
  - Lift matching threshold to 0.90 and preserve up to three candidate payloads for later reasoning/interview traces.

requirements-completed:
  - REASON-01
  - REASON-02
  - REASON-03
  - REASON-04
  - PIPELINE-01

# Metrics
duration: 55min
completed: 2026-05-28
---

## Performance

- **Duration:** 55 min
- **Started:** 2026-05-28T17:47:00Z
- **Completed:** 2026-05-28T18:42:00Z
- **Tasks:** 3
- **Files modified:** 13

## Accomplishments
- Added the Phase 4 reasoning schema and service for model invocation, schema repair fallback, deterministic gate evaluation, persistence, and shared finalization.
- Extended matching to persist top-3 candidate snapshots, filter invalidated visuals, apply the 0.90 threshold, and expose candidate payloads for reasoning.
- Updated the match worker to prepare segments with bounded fan-out, persist candidate snapshots, run one meal-level reasoning call, and route final writes through `finalize_meal_from_reasoning()`.
- Reworked `reasoning-probe` smoke mode to use production matching and reasoning services instead of a parallel prompt/schema implementation.

## Task Commits

Each task was committed atomically:

1. Task 1: RED reasoning contracts and harness - 1589313, bbfb7d8
2. Task 2: GREEN reasoning happy path - pending local commit
3. Task 3: Smoke helper production-path refactor - pending local commit

## Files Created/Modified
- app/services/reasoning_schema.py - Strict response schema and safe normalization for model outputs.
- app/services/reasoning_service.py - Reasoning orchestration, gate evaluation, persistence, and finalization bridge.
- app/services/matching_service.py - Candidate snapshots, top candidate payloads, invalidated visual filtering, and threshold update.
- bot/polling.py - Bounded match fan-out and meal-level reasoning/finalization handoff.
- scripts/embed_match_smoke.py - Reasoning probe now exercises production matching/reasoning services.

## Decisions Made
- Treat READY_TO_WRITE as a gate state, not a database processing enum.
- Keep unresolved reasoning results in `INTERVIEWING` so later interview phases can resume from persisted state.
- Allow the smoke reasoning probe to accept whole image files because the production matching image payload path already handles regular image inputs.

## Deviations from Plan
- The live smoke command was not executed in the isolated worktree because `.env` and `sample_images/IMG_4583.HEIC` were unavailable there. Unit coverage verifies the smoke helper calls the production services.

## Issues Encountered
- The executor subagent hit repeated model-capacity errors after producing RED commits, so the GREEN implementation and smoke refactor were completed inline in the isolated worktree.
- Existing Phase 3 worker tests expected direct similarity completion; they were updated to the Phase 4 finalization handoff.

## Next Phase Readiness
- Interview implementation can now consume persisted meal/segment reasoning state and candidate snapshots.
- Final write behavior is centralized behind the shared meal resolution service.

---
*Phase: 04-reason-interview-learning-loop*
*Completed: 2026-05-28*

## Self-Check: PASSED

- FOUND: .planning/phases/04-reason-interview-learning-loop/04-05-SUMMARY.md
- VERIFIED: targeted reasoning contracts pass
- VERIFIED: match, threshold, embed worker, smoke, reasoning, and parallel pipeline tests pass
