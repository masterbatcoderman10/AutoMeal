---
phase: 05-agentic-grounding
plan: 04
subsystem: api
tags: [grounding, reasoning, firecrawl, trace, tdd]
requires:
  - phase: 05-03
    provides: inline group finalizer, grounding loop controls, post-interview trace append
provides:
  - reasoning-ready groups now reuse the shared bounded finalizer path
  - Firecrawl search and scrape obey remaining loop wall-clock budget
  - live grounding traces persist snippet excerpts, provenance, and source_url evidence
affects: [reasoning, interview, grounding, verification]
tech-stack:
  added: []
  patterns:
    - shared finalizer reuse through interview_service group finalizers
    - loop-budget-derived HTTP timeouts for grounding tools
    - live trace schema mirrored to saved ai_reasoning payloads
key-files:
  created:
    - .planning/phases/05-agentic-grounding/05-04-SUMMARY.md
  modified:
    - app/services/reasoning_service.py
    - app/services/grounding_service.py
    - app/services/interview_schema.py
    - app/services/interview_service.py
    - tests/test_reasoning_contract.py
    - tests/test_reasoning_flow.py
    - tests/test_grounding_service.py
    - tests/test_interview_flow.py
key-decisions:
  - "Reuse interview_service group finalizers for reasoning-ready completions instead of maintaining a second write-through path."
  - "Derive Firecrawl HTTP timeouts from GroundingLoopState.remaining_time_s() so tool calls cannot outlive the enclosing wall-clock budget."
  - "Promote snippet_excerpts, provenance, and source_url into the live finalizer schema and merged grounding trace."
patterns-established:
  - "Reasoning and interview completion paths share the same bounded finalizer loop."
  - "Grounding evidence is stored both machine-readably and as appended human-readable trace text."
requirements-completed: [GROUND-01, GROUND-02, GROUND-03]
duration: 10min
completed: 2026-06-04
---

# Phase 5 Plan 4: Agentic Grounding Summary

**Shared bounded finalization for reasoning-ready meals with loop-budgeted Firecrawl calls and persisted snippet/provenance grounding evidence**

## Performance

- **Duration:** 10 min
- **Started:** 2026-06-04T19:07:00Z
- **Completed:** 2026-06-04T19:17:19Z
- **Tasks:** 2
- **Files modified:** 8

## Accomplishments
- Replaced the reasoning auto-complete write-through path with the same `_run_group_finalizers` loop already used after interview confirmation.
- Bound `GroundingService.search()` and `GroundingService.scrape()` to the remaining grounding-loop wall clock instead of a fixed per-call timeout.
- Expanded the live finalizer and trace contract so `MealSegment.ai_reasoning` retains snippet excerpts, provenance, source URL, iteration count, and stop-reason context.

## Task Commits

Each task was committed atomically:

1. **Task 1: RED - reproduce reasoning-path grounding, loop-budget, and trace-provenance regressions** - `93f01e1` (test)
2. **Task 2: GREEN - share the bounded finalizer across reasoning and interview paths, then persist the richer trace** - `7e91b73` (feat)

## Files Created/Modified
- `app/services/reasoning_service.py` - routes reasoning-ready groups through shared finalizer inputs and outcomes instead of direct grouped resolution writes.
- `app/services/grounding_service.py` - accepts loop budget context on search and derives Firecrawl HTTP timeouts from remaining wall-clock time.
- `app/services/interview_schema.py` - adds snippet/provenance/source_url fields to the live grounding trace and finalizer result models.
- `app/services/interview_service.py` - records richer trace excerpts, preserves provenance/source_url in merged traces, and formats the appended audit text with the new evidence.
- `tests/test_reasoning_contract.py` - locks live finalizer schema parity with the provenance-aware grounding contract.
- `tests/test_reasoning_flow.py` - locks reasoning finalization onto the shared bounded group finalizer path while keeping `_run_reasoning_model()` tool-free.
- `tests/test_grounding_service.py` - verifies loop-budget-aware search/scrape signatures and timeout behavior.
- `tests/test_interview_flow.py` - verifies post-interview completion persists snippet/provenance/source_url evidence into segment grounding traces.

## Decisions Made
- Reused the existing interview finalizer seam instead of introducing a second reasoning-only grounding implementation.
- Kept `_run_reasoning_model()` strict-json and tool-free; tool access remains limited to the bounded finalizer loop.
- Stored trace evidence on the live schema surface first, then appended it into the human-readable `grounding_trace_text` summary.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- The first RED run exposed a missing `json` import in a new contract test rather than a product gap; the test harness was corrected and the RED verification rerun immediately.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Reasoning-stage and post-interview grounding now share one bounded finalizer policy surface.
- The targeted Phase 5 regression suites pass; this gap-closure slice is ready for broader phase verification.

## Self-Check: PASSED

- Verified summary file exists on disk.
- Verified task commits `93f01e1` and `7e91b73` exist in git history.
