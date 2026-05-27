---
status: complete
phase: 02-vision-slice
source:
  - .planning/phases/02-vision-slice/02-01-SUMMARY.md
  - .planning/phases/02-vision-slice/02-02-SUMMARY.md
  - .planning/phases/02-vision-slice/02-03-SUMMARY.md
  - .planning/phases/02-vision-slice/02-04-SUMMARY.md
started: 2026-05-27T16:26:38Z
updated: 2026-05-27T17:55:30Z
---

## Current Test

[testing complete]

## Tests

### 1. Non-food Silent Completion
expected: Submit a clearly non-food image such as a screenshot or receipt through the normal ingest path. The Phase 1 acknowledgement may appear, but no final Phase 2 result sentence should be sent after detect finishes.
steps:
1. Submit non-food image through iOS Shortcut or authenticated `POST /ingest/photo`.
2. Wait for queue to settle.
3. Check Telegram chat for absence of `I see ...` result output.
result: pass
evidence: User reported that nothing appeared after the initial ack.

### 2. Simple Meal Success Sentence
expected: Submit a simple food image and receive one plain result sentence naming detected items, with duplicate foods collapsed in the message text.
steps:
1. Submit a meal image through the normal ingest path.
2. Wait for detect + segment workers to complete.
3. Record final Telegram text.
reported: "sent something with food, got nothing but the initial ack"
severity: major
evidence: Initial failure was traced to stale Docker images missing Phase 2 vision settings. After `docker compose up -d --build api bot`, user reran the food test and reported pass.
result: pass

### 3. Crop Files Exist Under `/data/uploads/crops/`
expected: After a successful segmented meal, one or more crop files should exist under `/data/uploads/crops/`.
steps:
1. Run `rtk find /data/uploads/crops -type f | tail`.
2. Confirm new crop files appeared for the tested meal.
result: pass
evidence: Verified directly on 2026-05-27. `/data/uploads/crops/` contains persisted JPEG crops, and recent `meal_segments.cropped_image_url` rows point to those files, including `/data/uploads/crops/65cc8d4f-d247-47bb-9706-1e5fce70e584.jpg` and `/data/uploads/crops/d427a7b5-4ee9-4f91-a958-88ea3ebf43ad.jpg` for completed meal `9bd54453-b9a6-4bae-a948-0be7d0508762`.

### 4. Invalid-box Retry and Soft Failure
expected: When detect says food but segmentation still yields nothing usable after the stronger retry, the meal should move to `FAILED` and Telegram should send exactly one soft failure message.
steps:
1. Reproduce with a known troublesome photo or controlled staging input.
2. Confirm final Telegram text is `⚠️ I couldn't confidently segment that meal photo. Please try another photo.`
3. Confirm the meal status ends at `FAILED`.
result: skipped
reason: Covered by deterministic automated verification. Confirmed by targeted unit tests for the exact soft-failure message, FAILED state transition when segmentation returns no usable segments, and one-retry segmentation behavior.
evidence: `MessageTemplateTests.test_soft_failure_message`, `PollingTests.test_poll_segments_rejects_empty_segments_with_no_result_message`, and `DetectServiceTests.test_segment_food_photo_retries_once_with_retry_model_after_invalid_primary_response` all passed on 2026-05-27.

### 5. Sample Image Grouping Against `sample_images/IMG_4583.HEIC`
expected: The grouped sample-image behavior follows the discussion contract: breads grouped together, curry/chicken grouped as one dish region, and vegetables grouped as one side region.
steps:
1. Run `.venv/bin/python scripts/vision_smoke.py --mode all --sample sample_images/IMG_4583.HEIC`.
2. Review printed segment boxes and labels.
3. Confirm output behavior matches grouped breads, curry/dish, and vegetables/side expectations.
result: pass
evidence: 2026-05-27 live smoke rerun produced three grouped items via `scripts/vision_smoke.py --mode all --sample sample_images/IMG_4583.HEIC`: pita bread, mixed vegetables, chicken curry.

## Summary

total: 5
passed: 4
issues: 0
pending: 0
skipped: 1
blocked: 0

## Gaps

[none]

## Notes

- Use this file to capture exact Telegram text, crop paths, and any mismatch between grouped-region expectations and provider output.
- 2026-05-27: first `--mode all` rerun failed closed at detect with `{is_food:false, confidence:0.0}`; second rerun passed end-to-end. Keep as provider-drift note for later calibration.
- 2026-05-27 diagnosis: the running Docker services were built from an older image revision. Rebuilt `api` and `bot`, then verified recovery with `scripts/vision_smoke.py --mode all --sample sample_images/IMG_4583.HEIC`, which returned detect=`segment`, 3 grouped regions, and labels `pita bread`, `chicken curry`, and `steamed vegetables`.
- Additional sample checks after rebuild: `sample_images/IMG_4629.HEIC` detect=`segment` and `sample_images/IMG_4646.HEIC` detect=`segment`.
- 2026-05-27 automated verification for Test 4: `.venv/bin/python -m unittest tests.test_bot_contract.MessageTemplateTests.test_soft_failure_message tests.test_bot_contract.PollingTests.test_poll_segments_rejects_empty_segments_with_no_result_message tests.test_vision_service.DetectServiceTests.test_segment_food_photo_retries_once_with_retry_model_after_invalid_primary_response` -> `OK`.
