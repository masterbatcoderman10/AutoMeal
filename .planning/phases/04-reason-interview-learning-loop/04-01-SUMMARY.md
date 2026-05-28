---
phase: 04-reason-interview-learning-loop
plan: 01
subsystem: testing
tags: [fastapi, openrouter, reasoning, unittest, async, ci]
requires:
  - phase: 03-embed-match
    provides: embedding/matching contracts and smoke harness foundations
provides:
  - strict reasoning contract and deterministic gate tests for wave 0
  - meal-level reasoning persistence and bounded parallel fan-out contracts
  - reasoning smoke mode that reports cache and trace metadata for tuning
affects:
  - app.services
  - bot
  - scripts
tech-stack:
  added:
    - unittest contract scaffolding for reasoning gate, flow, and fan-out
  patterns:
    - strict schema contract tests before production implementation
    - multi-signal escalation gate assertions replacing self-confidence-only logic
    - bounded concurrency smoke/observability checks without correctness coupling
key-files:
  created:
    - tests/test_reasoning_contract.py
    - tests/test_reasoning_gate.py
    - tests/test_reasoning_flow.py
    - tests/test_parallel_pipeline.py
  modified:
    - scripts/embed_match_smoke.py
key-decisions:
  - Keep reasoning trace and cache metadata as informational in the smoke probe.
  - Require unknown `action` values to route to `NEEDS_SCHEMA_REVIEW` via contract validation tests.
patterns-established:
  - Define strict JSON contract, gate, persistence, and concurrency semantics in test modules before service implementations.
requirements-completed:
  - REASON-01
  - REASON-02
  - REASON-03
  - REASON-04
  - PIPELINE-01
duration: 12m
completed: 2026-05-28
---

# Phase 04: Reason, Interview & Learning Loop Summary

**Created wave-0 reasoning validation contracts and a reasoning smoke probe that captures cache/trace metadata as non-blocking observability signals**

## Performance

- **Duration:** 12m (from task execution start to final summary write)
- **Started:** 2026-05-28T16:04:12Z
- **Completed:** 2026-05-28T16:16:12Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- Added `tests/test_reasoning_contract.py` with strict schema assertions for `top_3`, candidate evidence fields, and unknown-action downgrades to `NEEDS_SCHEMA_REVIEW`.
- Added `tests/test_reasoning_gate.py` to lock a deterministic escalation matrix based on similarity, candidate margin, missing evidence, and nutrition-impact uncertainty.
- Added `tests/test_reasoning_flow.py` and `tests/test_parallel_pipeline.py` for meal-level reasoning persistence sequencing and bounded per-meal fan-out sibling behavior.
- Extended `scripts/embed_match_smoke.py` with `reasoning-probe`, which runs two identical reasoning-like calls and emits trace IDs plus cached token metadata.

## Task Commits

1. **Task 1: Create Wave 0 contract and gate tests for meal-level reasoning per D-17 through D-25** - `a750cdc` (test)
2. **Task 2: Create Wave 0 flow and fan-out tests plus live cache/trace smoke coverage** - `db1cb3e` (test)

## Files Created/Modified

- `tests/test_reasoning_contract.py` - Contract tests for strict reasoning output shape and unknown-action handling.
- `tests/test_reasoning_gate.py` - Deterministic escalation matrix tests for similarity, margin, missing evidence, and nutrition uncertainty.
- `tests/test_reasoning_flow.py` - Meal-level persistence and pre-write reasoning trace expectations.
- `tests/test_parallel_pipeline.py` - Bounded async fan-out and sibling-progress smoke tests for segment matching.
- `scripts/embed_match_smoke.py` - Added `reasoning-probe` mode with dual-run metadata output (`cached_tokens`, trace id extraction).

## Decisions Made

- Locked requirement that prompt-cache and trace metadata are observability-only and must never block correctness.
- Kept script-facing reasoning probe schema open enough to keep future compatibility while surfacing required fields.
- Preserved unknown-action fallback and strict top-3 fields as explicit contract requirements before production changes.

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check: PASSED

- FOUND: `.planning/phases/04-reason-interview-learning-loop/04-01-SUMMARY.md`
- FOUND: commit `a750cdc`
- FOUND: commit `db1cb3e`

---
*Phase: 04-reason-interview-learning-loop*
*Completed: 2026-05-28*
