# Phase 03 UAT Checklist

**Prepared:** 2026-05-28  
**Scope:** completion Telegram contract, calibration, match growth, and unresolved branch evidence

## 1) Wave 0 calibration checks (D-04)

1. Run calibration:
   - Command: `python3 scripts/embed_match_smoke.py --mode calibrate --sample sample_images/IMG_4583.HEIC --same-food-peer sample_images/IMG_4584.HEIC --cross-modal-text "rice and lentils" --random-food sample_images/IMG_4585.HEIC`
2. Expected:
   - JSON includes `"mode": "calibrate"` and `"status": "pass"`.
   - `"same_food_similarity"` exists and is stable (`>= 0.99`).
   - `"cross_modal_target_similarity"` is greater than `"cross_modal_random_similarity"` (or margin non-negative).
3. Evidence field:
   - paste full JSON payload and screenshot command output.

## 2) Same-food re-photo match behavior (D-08, D-09)

1. Run seed-demo first to ensure a known food visual exists:
   - Command: `python3 scripts/embed_match_smoke.py --mode seed-demo --sample sample_images/IMG_4583.HEIC`
2. Run repeat confirmation for the same seed image:
   - Command: `python3 scripts/embed_match_smoke.py --mode repeat-confirmation --sample sample_images/IMG_4583.HEIC`
3. Expected:
   - Both rounds report `round` entries and `meal_id`.
   - `"routed_state"` is effectively `COMPLETED` (function exits with `status: pass` and does not raise).
   - `"committed_before_notification": true`.
4. Evidence field:
   - record full JSON outputs for seed and repeat runs.
   - confirm meal IDs are unique and both rounds succeed.

## 3) Unresolved match routing (D-09, D-22)

1. Command: `python3 scripts/embed_match_smoke.py --mode unresolved-probe --sample sample_images/IMG_4583.HEIC`
2. Expected:
   - JSON includes `"routed_state": "REASONING"` when corpus is populated with opposite-leaning visuals.
   - `is_below_threshold` is `true` for the probe when route is `REASONING`.
3. Evidence field:
   - paste output block and note whether `probe_route` is `below-threshold` or `empty-corpus` and why that matters.

## 4) Duplicate FoodVisual growth on repeated confirmations (D-22, D-25)

1. Run:
   - `python3 scripts/embed_match_smoke.py --mode repeat-confirmation --sample sample_images/IMG_4583.HEIC`
2. Expected:
   - `seed_visual_count_after - seed_visual_count_before == 2` after two rounds, demonstrating duplicate growth.
   - each entry in `rounds` has `"visual_added": true`.
3. Evidence field:
   - record the `seed_visual_count_before`, `seed_visual_count_after`, and both `rounds` records.

## 5) Telegram match-completion payload contract (D-17, D-18, D-19, D-20, D-14)

1. Seed or confirm a visible seed, then send a same-food image through normal bot flow until a meal becomes `COMPLETED`.
2. Capture the Telegram message text.
3. Expected:
   - Per-item line format: `<Food> | portion=STANDARD | method=SIMILARITY | verified=<true|false>`
   - Immediate next line lists only present macros/energy fields (`Calories`, `Protein`, `Carbs`, `Fat`), with missing fields omitted.
   - Total line includes only fields with at least one known segment value.
   - No internal debug fields: no score, no vector, no embedding fragment.
4. Evidence field:
   - paste exact Telegram message text and meal ID.
   - include `MealLog.processing_status` DB check for `COMPLETED`.
