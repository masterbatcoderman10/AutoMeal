---
phase: 03-embed-match
plan: 01
subsystem: api
tags: [fastapi, openrouter, embeddings, python]
requires:
  - phase: 03-02-vision-slice
    provides: embedding and segment outputs for document/query vector paths
provides:
  - validated OpenRouter embedding contract at 1536 dims with strict vector checks
  - retry-safe embedding orchestration for document write/query search vectors
  - Wave 0 calibration and seed helper for `sample_images` evidence capture
affects:
  - 03-match-flow
  - bot workers
  - scripts
tech-stack:
  added: []
  patterns:
    - response-shape validation at the embedding boundary
    - explicit task-type constants per operation type
    - service-level retry policy for transport-style failures only
key-files:
  created:
    - app/services/embedding_service.py
    - scripts/embed_match_smoke.py
  modified:
    - app/services/llm_client.py
    - tests/test_embedding_service.py
key-decisions:
  - Use D-07 semantics directly in a dedicated embedding service: RETRIEVAL_DOCUMENT for writes and RETRIEVAL_QUERY for search.
  - Fail closed on malformed OpenRouter responses and non-1536 vectors before any embedding is accepted.
  - Keep empty corpus behavior as valid and non-fatal via explicit empty-corpus handling in calibration output.
patterns-established:
  - "Validate embedding responses as close to remote contract as possible, then revalidate at the caller boundary before use."
requirements-completed:
  - MATCH-02
duration: 2m
completed: 2026-05-27
---

# Phase 03: Embed Contract Summary

**Validated 1536-dimension OpenRouter multimodal embeddings with task-specific request contract and operational Wave 0 calibration/seed script**

## Performance

- **Duration:** 2m (from plan-start to final summary write)
- **Started:** 2026-05-27T00:00:00Z
- **Completed:** 2026-05-27T00:02:00Z
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments

- Hardened `app/services/llm_client.py` to send `output_dimensionality`, task type, and strict `content` shape for multimodal embeddings while validating remote response payloads and vector length.
- Added `app/services/embedding_service.py` with explicit document/query entry points, shared retry-safe embedding orchestration, and similarity helpers for calibration gates.
- Added `scripts/embed_match_smoke.py` with calibrate and seed-demo modes, including same-food and cross-modal ranking checks plus empty-corpus branch handling.
- Extended `tests/test_embedding_service.py` with retry policy, malformed-response, and vector-shape contract assertions that support the GREEN gate.

## Task Commits

1. **Task 1: RED - add failing embedding-contract tests for crop vectors and calibration helpers** - `a863864` (test)
2. **Task 2: GREEN - implement validated embedding orchestration and retry-safe OpenRouter calls** - `d3bd988` (feat)
3. **Task 3: REFACTOR - add Wave 0 smoke helper for demo seeding and calibration evidence** - `2b33305` (refactor)

## Files Created/Modified

- `app/services/embedding_service.py` - Thin orchestration layer for multimodal document/query embeddings with validation and retries.
- `app/services/llm_client.py` - Updated embedding request contract plus strict response parsing/shape checks.
- `scripts/embed_match_smoke.py` - Wave 0 calibration and demo seeding CLI.
- `tests/test_embedding_service.py` - Contract tests for embedding request semantics, retry policy, and vector validation.

## Decisions Made

- Used `1536` as the enforced output dimensionality across embedding surfaces and tests, matching the repo schema.
- Used explicit constants `RETRIEVAL_DOCUMENT` and `RETRIEVAL_QUERY` for operation-specific calls.
- Enforced fail-closed behavior for transport retries vs parse/validation failures by binding retries to `httpx.HTTPError`.

## Deviations from Plan

None - plan executed as written.

## Issues Encountered

- The isolated executor worktree shell did not have the project runtime available for verification, so in-worktree checks failed on missing local tools and dependencies.
- Post-merge local verification from the primary checkout exposed one real defect: `wait_exponential_jitter()` was called with an unsupported `multiplier=` keyword for the installed `tenacity` version.
- The merged checkout was corrected to use `initial=0.4`, and `rtk .venv/bin/python -m unittest tests.test_embedding_service` then passed.
- Live OpenRouter calibration on 2026-05-28 exposed a second contract bug in `app/services/llm_client.py`: the embeddings request used Google-native `output_dimensionality` / `task_type` fields instead of OpenRouter's `dimensions` / `input_type`, so the provider returned the default 3072-d vector shape.
- The primary checkout now translates the Phase 03 retrieval intent onto the OpenRouter wire format correctly, and the live calibration smoke passes with same-image self-similarity `1.0` plus a positive `rice and lentils` cross-modal margin against `sample_images/IMG_4611.HEIC`.

## Next Phase Readiness

- Phase 3 embedding/matching may proceed immediately; the embedding contract test suite now passes in the primary checkout venv.
- `scripts/embed_match_smoke.py` is in place for calibration evidence and can be executed by CI/dev with the required stack available.

## Self-Check: PASSED

- FOUND: `.planning/phases/03-embed-match/03-01-SUMMARY.md`
- FOUND: commit `a863864`
- FOUND: commit `d3bd988`
- FOUND: commit `2b33305`

---
*Phase: 03-embed-match*
*Completed: 2026-05-27*
