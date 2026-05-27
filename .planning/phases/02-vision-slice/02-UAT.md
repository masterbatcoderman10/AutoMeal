---
status: draft
phase: 02-vision-slice
source:
  - .planning/phases/02-vision-slice/02-01-SUMMARY.md
  - .planning/phases/02-vision-slice/02-02-SUMMARY.md
  - .planning/phases/02-vision-slice/02-03-SUMMARY.md
  - .planning/phases/02-vision-slice/02-04-PLAN.md
started: 2026-05-27T16:26:38Z
updated: 2026-05-27T16:33:00Z
---

## Current Test

[pending execution]

## Tests

### 1. Non-food Silent Completion
expected: Submit a clearly non-food image such as a screenshot or receipt through the normal ingest path. The Phase 1 acknowledgement may appear, but no final Phase 2 result sentence should be sent after detect finishes.
steps:
1. Submit non-food image through iOS Shortcut or authenticated `POST /ingest/photo`.
2. Wait for queue to settle.
3. Check Telegram chat for absence of `I see ...` result output.
result: pending
evidence: [telegram output or note]

### 2. Simple Meal Success Sentence
expected: Submit a simple food image and receive one plain result sentence naming detected items, with duplicate foods collapsed in the message text.
steps:
1. Submit a meal image through the normal ingest path.
2. Wait for detect + segment workers to complete.
3. Record final Telegram text.
result: pending
evidence: [telegram output or note]

### 3. Crop Files Exist Under `/data/uploads/crops/`
expected: After a successful segmented meal, one or more crop files should exist under `/data/uploads/crops/`.
steps:
1. Run `rtk find /data/uploads/crops -type f | tail`.
2. Confirm new crop files appeared for the tested meal.
result: pending
evidence: [filesystem output or note]

### 4. Invalid-box Retry and Soft Failure
expected: When detect says food but segmentation still yields nothing usable after the stronger retry, the meal should move to `FAILED` and Telegram should send exactly one soft failure message.
steps:
1. Reproduce with a known troublesome photo or controlled staging input.
2. Confirm final Telegram text is `⚠️ I couldn't confidently segment that meal photo. Please try another photo.`
3. Confirm the meal status ends at `FAILED`.
result: pending
evidence: [telegram output, DB note, or log note]

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
passed: 1
issues: 0
pending: 4
skipped: 0
blocked: 0

## Gaps

- Manual Telegram verification still pending.

## Notes

- Use this file to capture exact Telegram text, crop paths, and any mismatch between grouped-region expectations and provider output.
- 2026-05-27: first `--mode all` rerun failed closed at detect with `{is_food:false, confidence:0.0}`; second rerun passed end-to-end. Keep as provider-drift note for later calibration.
