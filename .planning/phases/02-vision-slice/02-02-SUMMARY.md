---
phase: 02-vision-slice
plan: 02
subsystem: bot
tags:
  - vision
  - segmentation
  - pillow
  - sqlalchemy
  - unittest

requires:
  - phase: 02-vision-slice
    provides: detect gate, detect worker, shared OpenRouter multimodal transport
provides:
  - Segment-stage normalization and validation helpers
  - Crop persistence under /data/uploads/crops/
  - One-sentence labeled Phase 2 result output
affects:
  - phase: 02-vision-slice

tech-stack:
  added:
    - none
  patterns:
    - Normalize provider 0..1000 boxes before persistence
    - Persist MealSegment rows before labeling and final result send

key-files:
  created:
    - none
  modified:
    - bot/main.py
    - app/services/vision_service.py
    - app/services/image_service.py
    - bot/messages.py
    - bot/polling.py
    - tests/test_vision_service.py
    - tests/test_bot_contract.py

key-decisions:
  - "Normalize raw provider boxes from 0..1000 into stored [0,1] floats before any crop or DB write."
  - "Persist accepted segment crops to /data/uploads/crops/{segment_id}.jpg before label calls."
  - "Keep Phase 2 user output to one plain sentence built from distinct accepted labels only."

patterns-established:
  - "Segment validation is fail-closed: malformed, reversed, out-of-range, or tiny boxes are rejected before persistence."
  - "SEGMENTING worker owns crop save, MealSegment creation, label calls, and final one-sentence bot output."

requirements-completed:
  - VISION-04

duration: 18m
completed: 2026-05-27
---

# Phase 02: Segmentation Happy Path Summary

**Implemented normalized segment validation, crop persistence, and first food-result sentence**

## Performance

- **Duration:** 26m (approx. execution window 2026-05-27T15:49:32Z to 2026-05-27T16:15:05Z)
- **Tasks:** 3
- **Files modified:** 7

## Accomplishments

- Added segmentation prompt/schema helpers plus normalization of raw `[y,x,y,x]` provider coordinates into validated `[0,1]` floats.
- Added crop persistence helper that saves accepted segment JPEGs to `/data/uploads/crops/{segment_id}.jpg`.
- Added segment worker flow that is wired into bot startup, creates `MealSegment` rows, labels accepted crops, sends `I see ...` output, and marks the meal `COMPLETED`.
- Converted local image paths into data URLs before OpenRouter vision calls and made malformed label responses fail closed.

## Task Commits

1. **Task 1: Add segmentation schemas, normalization, and validation helpers** - `58604e7` (feat)
2. **Task 2-3: Persist crops, label accepted segments, and send final sentence** - `05eeece` (feat)
3. **Review-blocker repair: wire runtime path and local image input conversion** - `d6bdcba` (fix)

## Files Created/Modified

- `bot/main.py` - Added segment worker task registration and cancel-on-shutdown handling.
- `app/services/vision_service.py` - Added segmentation and labeling prompts, response formats, box normalization, validation, and parsing.
- `app/services/image_service.py` - Added `save_segment_crop()` for normalized-box JPEG crop persistence.
- `bot/messages.py` - Added one-sentence result formatter for accepted segment labels.
- `bot/polling.py` - Added `SEGMENTING` worker to create segment rows, save crops, label them, and send final result output.
- `tests/test_vision_service.py` - Added coverage for normalization, invalid box rejection, segment caps, and label prompt contracts.
- `tests/test_bot_contract.py` - Added segmentation worker success/failure tests and result sentence assertions.

## Decisions Made

- Save crops before labeling so later phases can reuse stable crop paths and segment rows.
- Keep Phase 2 result formatting to one plain sentence without introducing nutrition or DiaryEntry work.
- Treat malformed label responses as failures instead of fabricating a generic `food` label.
- Leave IoU dedupe, retry escalation, and soft-failure message handling for `02-03`.

## Deviations from Plan

- Independent review exposed runtime blockers after the first happy-path implementation pass: missing segment-worker startup wiring and local filesystem paths being passed directly to OpenRouter. Both were fixed inline before closing the plan.
- Execution verification also exposed two test-harness mismatches (`AsyncMock` for sync `add_all`, and a status-insensitive mocked query loop). Fixed tests to mirror real `AsyncSession` behavior.

## Issues Encountered

- Review found runtime blockers after the initial implementation pass; they were resolved before completion.

## User Setup Required

None.

## Known Stubs

- `VISION-03` is not fully closed yet; IoU dedupe and retry/soft-failure handling remain in `02-03`.

## Threat Flags

None.

## Next Phase Readiness

- Ready for `02-03` to add full-response rejection, stronger-model retry, IoU dedupe, and soft-failure messaging on top of the now-working crop/label happy path.

---
*Phase: 02-vision-slice*
*Completed: 2026-05-27*
