# Phase 04: Shared runtime interfaces for resolution, taxonomy, and tracing

---
phase: 04-reason-interview-learning-loop
plan: 04
subsystem: api
tags: [fastapi, sqlalchemy, pydantic, langfuse]

# Dependency graph
requires:
  - phase: 04-state
    provides: durable reasoning/interview state tables from 04-03
provides:
  - shared meal final-write contract that resolves or creates FoodItem and applies corrections atomically
  - validated reasoning taxonomy configuration loader + editable JSON policy surface
  - reconciled Phase 4 runtime settings and optional Langfuse tracing wrapper
affects:
  - 04-reason-interview-learning-loop
  - 05

# Tech tracking
tech-stack:
  added:
    - langfuse (optional optional tracing integration)
  patterns:
    - shared DB-first final-write service to avoid duplicate write logic in reasoning/interview/correction flows
    - strict taxonomy schema validation before runtime consumption
    - tracing wrapper that degrades to no-op on missing keys/provider failures

key-files:
  created:
    - app/services/meal_resolution_service.py
    - app/services/taxonomy_service.py
    - app/services/tracing_service.py
    - config/reasoning_taxonomy.json
  modified:
    - app/config.py
    - requirements.txt

key-decisions:
  - Keep phase-4 tracing best-effort and non-blocking: if Langfuse is unavailable or disabled, runtime continues without tracing state.
  - Resolve FoodItem by trusted food_item_id first, then by canonical identity tuple, then create new rows with NEEDS_GROUNDING behavior when nutrition is incomplete.
  - Put runtime policy into editable JSON so reasoning specificity/quantity/composite behavior remains configurable outside code.

requirements-completed:
  - REASON-04
  - PIPELINE-01
  - INTERVIEW-03
  - INTERVIEW-05
  - INTERVIEW-06
  - INFRA-04

# Metrics
duration: 2min
completed: 2026-05-28
---

## Performance

- **Duration:** 2 min
- **Started:** 2026-05-28T17:36:12Z
- **Completed:** 2026-05-28T17:38:05Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments
- Added app/services/meal_resolution_service.py with canonical final-write contract for creating/updating FoodItem, DiaryEntry, FoodVisual, CorrectionEvent, and meal state in one shared boundary.
- Added app/services/taxonomy_service.py plus config/reasoning_taxonomy.json to move reasoning policy (specificity, quantity, composites, question budget) into validated editable configuration.
- Added Phase 4 config surface (REASONING_*, tracing and recovery settings, Langfuse capture toggle) in app/config.py.
- Added best-effort, metadata-safe app/services/tracing_service.py and pinned langfuse==4.7.0 in requirements.txt.

## Task Commits

Each task was committed atomically:

1. Task 1: Add shared meal-resolution and taxonomy interfaces per D-08 and D-39 - 32de7f6 (feat)
2. Task 2: Add Phase 4 config keys and reconcile optional tracing on langfuse==4.7.0 - 346a7b3 (feat)

## Files Created/Modified
- app/services/meal_resolution_service.py - Added shared food resolution, correction, and final-write orchestration contract.
- app/services/taxonomy_service.py - Added strict JSON loader/validator for reasoning taxonomy.
- config/reasoning_taxonomy.json - Added editable policy data for nutrition impact, quantity units, composite behavior, and question budgets.
- app/config.py - Added Phase 4 reasoning, tracing, interview, and janitor configuration keys.
- app/services/tracing_service.py - Added optional trace wrapper with metadata-only image default.
- requirements.txt - Added langfuse==4.7.0.

## Decisions Made
- Treat tracing as optional infrastructure with explicit fallbacks so no pipeline writes depend on telemetry availability.
- Keep a single shared finalization contract that enforces canonical FoodItem lookup/creation and correction bookkeeping for all Phase 4 downstream flows.
- Validate taxonomy early with strict, fail-fast schema checks to avoid malformed policy driving model calls.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Runtime import verification commands that load app.services could not run in this worktree because neither .venv exists nor fastapi is installed in the default environment (ModuleNotFoundError: fastapi).

## Next Phase Readiness
- Reasoning/interview/correction services can now import a single final-write contract and shared taxonomy policy contract.
- Langfuse tracing and Phase 4 config knobs are available for implementation phases that need them.

---
*Phase: 04-reason-interview-learning-loop*
*Completed: 2026-05-28*

## Self-Check: PASSED

- FOUND: .planning/phases/04-reason-interview-learning-loop/04-04-SUMMARY.md
- FOUND: commit 32de7f6
- FOUND: commit 346a7b3
