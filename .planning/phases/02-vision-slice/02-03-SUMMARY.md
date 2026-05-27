---
phase: 02-vision-slice
plan: 03
subsystem: vision
tags:
  - vision
  - segmentation
  - retry
  - telegram
  - unittest

requires:
  - phase: 02-vision-slice
    provides: normalized boxes, crop persistence, label flow, segment worker wiring
provides:
  - Full-response rejection with one retry on stronger segment model
  - IoU dedupe before crop persistence
  - Soft-failure message and duplicate-label collapse
affects:
  - phase: 02-vision-slice

tech-stack:
  added:
    - none
  patterns:
    - Reject partially invalid segmentation payloads wholesale
    - Retry segmentation once on `SEGMENT_RETRY_MODEL`
    - Keep overlapping boxes out of persistence and user output

key-files:
  created:
    - none
  modified:
    - app/services/vision_service.py
    - bot/messages.py
    - bot/polling.py
    - tests/test_vision_service.py
    - tests/test_bot_contract.py

key-decisions:
  - "Any invalid box invalidates the entire segmentation response."
  - "Segmentation retries exactly once using `SEGMENT_RETRY_MODEL`."
  - "IoU > 0.5 keeps the stronger region before any crop or DB write."
  - "Final sentence collapses duplicate labels and hedges only weak items inline."

patterns-established:
  - "Segmentation failure is bounded: primary model once, stronger retry once, then FAILED + soft message."
  - "User output is less noisy than internal segment rows: duplicate labels collapse in message only."

requirements-completed:
  - VISION-03

duration: 11m
completed: 2026-05-27
---

# Phase 02: Segmentation Hardening Summary

**Implemented one-retry segmentation hardening, IoU dedupe, and soft-failure handling**

## Accomplishments

- Added `segment_food_photo_with_retry()` so malformed or unusable segment payloads retry once on `SEGMENT_RETRY_MODEL`.
- Added normalized-box IoU dedupe that keeps stronger overlapping regions before crop persistence.
- Added soft-failure Telegram output when detect said food but both segmentation attempts produced nothing usable.
- Updated final result formatting to collapse duplicate labels and hedge only weak items inline.

## Verification

- `.venv/bin/python -m unittest tests.test_vision_service tests.test_bot_contract`

## Files Created/Modified

- `app/services/vision_service.py` - Added retry orchestration, IoU helper, dedupe helper, and weak-confidence constant.
- `bot/messages.py` - Added soft-failure formatter and duplicate-collapse/weak-label result formatting.
- `bot/polling.py` - Switched segment worker to retry+dedupe flow and soft-failure output.
- `tests/test_vision_service.py` - Added retry-model and IoU dedupe coverage.
- `tests/test_bot_contract.py` - Added soft-failure and duplicate-label contract coverage.

## Decisions Made

- Treat empty and partially invalid segmentation payloads the same for retry purposes: unusable response.
- Deduplicate overlaps before crop persistence so later phases never learn from duplicate regions.
- Preserve separate `MealSegment` rows only for accepted deduped regions; collapse duplicate labels only at message time.

## Known Stubs

- `02-04` still needed for live OpenRouter smoke coverage, env-template confirmation, and UAT evidence capture.

## Next Phase Readiness

- Ready for `02-04`.

---
*Phase: 02-vision-slice*
*Completed: 2026-05-27*
