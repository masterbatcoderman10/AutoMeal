---
status: complete
phase: 03-embed-match
source:
  - 03-01-SUMMARY.md
  - 03-02-SUMMARY.md
  - 03-03-SUMMARY.md
  - 03-04-SUMMARY.md
started: 2026-05-28T08:31:47Z
updated: 2026-05-28T11:32:47Z
---

## Current Test

[testing complete]

## Tests

### 1. Wave 0 calibration checks
expected: Run `rtk .venv/bin/python scripts/embed_match_smoke.py --mode calibrate --sample /data/uploads/crops/meal-a-seg-1.jpg --same-food-peer /data/uploads/crops/meal-b-seg-1.jpg --cross-modal-text "rice and lentils" --random-food /data/uploads/crops/random-seg-1.jpg`; JSON should show `"mode": "calibrate"`, `"status": "pass"`, `"self_similarity" >= 0.99`, a non-null `"same_food_peer"` and `"same_food_similarity"`, and the target similarity beating or tying the random-food comparison.
result: pass
evidence: User confirmed the crop-only `calibrate` rerun succeeded with two real photos (`--sample` plus `--same-food-peer`): "i tried with 2 pictures, it worked you can mark this as done".

### 2. Same-food re-photo match behavior
expected: Run `seed-demo` first, then `repeat-confirmation` against a real saved crop artifact such as `/data/uploads/crops/meal-a-seg-1.jpg`; both runs should report rounds and meal IDs, exit with pass semantics, and show `"committed_before_notification": true`.
result: pass
evidence: User confirmed the same-food re-photo match behavior worked with a real crop artifact: "that also works, same food re-photo match worked".

### 3. Unresolved match routing
expected: Run `unresolved-probe` against a real saved crop artifact such as `/data/uploads/crops/meal-a-seg-1.jpg`; the JSON should route to `"REASONING"` when the corpus is opposite-leaning, and `is_below_threshold` should be `true` for that route.
result: pass
evidence: User confirmed the unresolved routing check passed with a real crop artifact: "yeah that works too".

### 4. Duplicate FoodVisual growth on repeated confirmations
expected: Run `repeat-confirmation` again and confirm `seed_visual_count_after - seed_visual_count_before == 2`, with each round reporting `"visual_added": true`.
result: pass
evidence: Live rerun passed against a real crop artifact after reseeding the stale smoke fixture to the current crop. `repeat-confirmation` returned `status=pass`, `seed_visual_count_before=7`, `seed_visual_count_after=9`, both rounds reported `visual_added=true`, and `committed_before_notification=true`.

### 5. Telegram match-completion payload contract
expected: Send the same-food image through the normal bot flow until a meal is `COMPLETED`; the Telegram message should use `<Food> | portion=STANDARD | method=SIMILARITY | verified=<true|false>`, list only known nutrition fields, include totals only for known values, and omit all debug internals.
result: pass
evidence: User observed the Phase 03 completion payload exactly: `Chicken Curry With Pita Bread | portion=STANDARD | method=SIMILARITY | verified=true`, `Pita Bread | portion=STANDARD | method=SIMILARITY | verified=true`, `Steamed Vegetables | portion=STANDARD | method=SIMILARITY | verified=true`, followed by per-item nutrition lines and `Total | Calories: 655 kcal | Protein: 32.5 g | Carbs: 73 g | Fat: 24 g`.

## Summary

total: 5
passed: 5
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps
