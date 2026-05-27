---
phase: 02-vision-slice
plan: 01
subsystem: api
tags:
  - fastapi
  - openrouter
  - openai-sdk
  - bot
  - unittest

requires:
  - phase: 01-foundation-ingest
    provides: ingest, bot poller, OpenRouter client, and MealLog status model
provides:
  - Vision detect settings in runtime config
  - Shared chat completion passthrough for multimodal arrays and extra_body
  - Conservative detect parser and detect worker transition logic
affects:
  - phase: 02-vision-slice

tech-stack:
  added:
    - none
  patterns:
    - OpenRouter multimodal request/response through shared llm_client
    - DB-driven worker loop for detect stage with status transitions

key-files:
  created:
    - app/services/vision_service.py
    - tests/test_vision_service.py
  modified:
    - app/config.py
    - app/services/llm_client.py
    - bot/main.py
    - bot/polling.py
    - tests/test_bot_contract.py

key-decisions:
  - "Keep detect conservative by requiring high-confidence `is_food=true` before transitioning to segmentation."
  - "Honor D-04 by explicitly prompting for continuation when a meal is present despite clutter."
  - "Handle detection failures by defaulting to `skip` to avoid unsafe downstream work."
  - "Register detect worker as a separate background task and cancel it symmetrically with polling."

patterns-established:
  - "Single shared OpenRouter client wrapper remains the transport for all detection calls."
  - "Detect parsing is deterministic and fail-closed: malformed/missing payloads always return skip."

requirements-completed:
  - VISION-01
  - VISION-02

duration: 1m
completed: 2026-05-27
---

# Phase 02: Detect Slice Summary

**Implemented multimodal detect gate with conservative skip policy and phase-aware bot worker transitions**

## Performance

- **Duration:** 0m53s (recorded start 2026-05-27T15:46:53Z, completed 2026-05-27T15:47:46Z)
- **Started:** 2026-05-27T15:46:53Z
- **Completed:** 2026-05-27T15:47:46Z
- **Tasks:** 3
- **Files modified:** 7

## Accomplishments

- Added vision runtime settings for detect/segment/label model IDs and max-segment ceiling.
- Extended shared OpenRouter transport to forward multimodal messages and `extra_body` unchanged for future tool/model tuning.
- Added deterministic detect schema/prompt/parse logic that fails closed and a detection worker that marks non-food as `COMPLETED` without a final result message.

## Task Commits

1. **Task 1: Extend runtime settings and shared OpenRouter wrapper** - `47ea919` (feat)
2. **Task 2: Create detect-stage schemas and conservative parsing helpers** - `b8cde3d` (feat)
3. **Task 3: Add detect worker slice for non-food completion and food handoff** - `af2e153` (feat)

**Plan metadata:** `docs(02-01): complete 02-01-PLAN` (to be recorded in final plan metadata commit)

## Files Created/Modified

- `app/config.py` - Added `DETECT_MODEL`, `SEGMENT_MODEL`, `SEGMENT_RETRY_MODEL`, `LABEL_MODEL`, and `VISION_MAX_SEGMENTS`.
- `app/services/llm_client.py` - Added optional `extra_body` passthrough for `chat_completion` and preserved argument forwarding.
- `app/services/vision_service.py` - Added detect prompt, strict response format, response parsing, and decision normalizer.
- `bot/main.py` - Added detect worker task registration and cancel-on-shutdown handling.
- `bot/polling.py` - Added detect worker loop for `DETECTING` meals to transition to `COMPLETED` or `SEGMENTING`.
- `tests/test_vision_service.py` - Added unit tests for prompt contract, malformed payload handling, and confidence gate behavior.
- `tests/test_bot_contract.py` - Added client passthrough contract test and detect-worker lifecycle/status transition tests.

## Decisions Made

- Conservative detect policy (`is_food` + confidence threshold) is preferred over optimistic segmentation.
- Non-food and uncertain detections complete silently with `MealLog.processing_status = COMPLETED`.
- Keep segmentation for later plans by only moving accepted images to `MealLog.processing_status = SEGMENTING`.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- No blocking issues were encountered.

## User Setup Required

None.

## Known Stubs

None.

## Threat Flags

None.

## Next Phase Readiness

- Plan is ready to proceed to segmentation implementation and segment validation/cropping (`02-02`) with conservative detect handoff and no user-visible final message on non-food.

---
*Phase: 02-vision-slice*
*Completed: 2026-05-27*

## Self-Check: PASSED

**PASS** Created file exists: `.planning/phases/02-vision-slice/02-01-SUMMARY.md`
**PASS** Commit hash `47ea919` exists
**PASS** Commit hash `b8cde3d` exists
**PASS** Commit hash `af2e153` exists
