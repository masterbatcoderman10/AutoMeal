---
phase: 03-embed-match
plan: 02
subsystem: api
tags: [fastapi, pgvector, embeddings, telegram, vector-search]
requires:
  - phase: 03-01
    provides: 1536-d embedding contract and calibration/smoke script baseline
provides:
  - segment-level query embedding generation in `app/services/matching_service.py`
  - EMBEDDING and MATCHING stage handoff in the worker chain before completion
  - unresolved branch routing to REASONING with one transparent Telegram message
  - unresolved-wave smoke probe path that reuses matching services
affects:
  - 03-reasoning
  - 04-reasoning-interview
  - bot workers
  - scripts
tech-stack:
  added: []
  patterns:
    - stage-owned worker pipeline (`SEGMENTING` -> `EMBEDDING` -> `MATCHING` -> `REASONING|COMPLETED`)
    - segment-only similarity service via `matching_service` and strict cosine thresholding
    - service-first matching logic reused by both runtime workers and smoke diagnostics
key-files:
  created:
    - app/services/matching_service.py
  modified:
    - bot/main.py
    - bot/messages.py
    - bot/polling.py
    - scripts/embed_match_smoke.py
    - tests/test_match_flow.py
key-decisions:
  - "Use `1 - cosine_distance` as similarity and enforce threshold `0.85` directly after filtering invalidated visuals."
  - "Persist each `MealSegment.embedding` from a per-segment `RETRIEVAL_QUERY` call before nearest-neighbor lookup."
  - "Route unresolved meals to `REASONING` only, with no `DiaryEntry` write path and one user-facing note."
patterns-established:
  - "Per-segment matching is query-driven: use `MealSegment.cropped_image_url` only, not meal-level image inputs."
  - "Unknown meals follow the unresolved branch only after explicit failed match conditions (`empty corpus`, no row, or low similarity)."
requirements-completed:
  - MATCH-02
  - MATCH-03
duration: 4m
completed: 2026-05-28
---

# Phase 3: Embed-Match Summary

**Built segment-level embedding, nearest-neighbor matching, and unresolved-meal handoff before diary completion**

## Performance

- **Duration:** 4m
- **Started:** 2026-05-28T00:00:00Z
- **Completed:** 2026-05-28T00:04:00Z
- **Tasks:** 3
- **Files modified:** 7

## Accomplishments

- Added `app/services/matching_service.py` with per-segment query embedding, similarity conversion, and nearest-neighbor matching against non-invalidated `FoodVisual` rows at `MATCH_THRESHOLD = 0.85`.
- Corrected the worker ownership model so `SEGMENTING` transitions to `EMBEDDING`, then to `MATCHING`, and only escalates unresolved meals to `REASONING` without partial writes.
- Expanded `scripts/embed_match_smoke.py` with an `unresolved-probe` mode that reuses shared matching service logic and reports `routed_state` as an unresolved branch signal.

## Task Commits

1. **Task 1: RED - add failing tests for per-segment similarity search and unresolved-meal routing** - `5660cf2` (test)
2. **Task 2: GREEN - implement per-segment embedding, cosine similarity search, and status handoff** - `c2f88ec` (feat)
3. **Task 3: REFACTOR - prove Wave 1 behavior through the shared smoke path** - `97576d0` (refactor)

**Plan metadata:** not committed separately (docs commit contains plan metadata)

## Files Created/Modified

- `app/services/matching_service.py` - Added query embedding and cosine-similarity matching helpers plus segment-result dataclass.
- `bot/main.py` - Started/stopped embed and match worker tasks in application lifecycle.
- `bot/messages.py` - Added `format_unresolved_match_message` for a single transparent unresolved notification.
- `bot/polling.py` - Implemented EMBEDDING and MATCHING workers plus new phase handoff logic.
- `scripts/embed_match_smoke.py` - Added `unresolved-probe` mode to drive unresolved-match behavior via `matching_service`.
- `tests/test_match_flow.py` - Extended worker contract tests for empty corpus, below-threshold, and unresolved routing.

## Decisions Made

- Enforced segment-level matching and avoided whole-meal matching checks for correctness.
- Kept the unresolved path explicit (`REASONING`) and idempotent, with no partial persistence when unresolved.
- Kept unresolved Telegram messaging terse, with no similarity scores or internal routing internals exposed.

## Deviations from Plan

None - plan executed as written.

## Issues Encountered

- In this worktree runtime, full verification commands were blocked by missing project dependencies, so the subagent could not prove the plan locally before merge.
- Post-merge verification in the primary checkout exposed three real gaps: a stale `pgvector` helper import path in `matching_service`, test harness drift around polling-loop cancellation and imported formatter symbols, and a live OpenRouter embeddings wire-format bug inherited from Wave 0.
- After correcting those issues, `rtk .venv/bin/python -m unittest tests.test_match_flow` passes and the live unresolved probe succeeds against the running compose Postgres with `routed_state=REASONING` on an empty corpus.

## Known Stubs

No stubs introduced by this plan.

## Self-Check: PASSED

- FOUND: `.planning/phases/03-embed-match/03-02-SUMMARY.md`
- FOUND: commit `5660cf2`
- FOUND: commit `c2f88ec`
- FOUND: commit `97576d0`

---
*Phase: 03-embed-match*
*Completed: 2026-05-28*
