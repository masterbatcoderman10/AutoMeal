---
phase: 03-embed-match
reviewed: 2026-05-28T10:07:21Z
depth: deep
files_reviewed: 7
files_reviewed_list:
  - scripts/embed_match_smoke.py
  - tests/test_embed_match_smoke.py
  - bot/polling.py
  - tests/test_embed_worker.py
  - tests/test_match_flow.py
  - tests/test_matching_threshold.py
  - .planning/phases/03-embed-match/03-SECURITY.md
findings:
  critical: 1
  warning: 1
  info: 0
  total: 2
status: issues_found
---

# Phase 03: Code Review Report

**Reviewed:** 2026-05-28T10:07:21Z
**Depth:** deep
**Files Reviewed:** 7
**Status:** issues_found

## Summary

Reviewed the requested Phase 03 security-fix scope and traced the changed paths into `matching_service`, `embedding_service`, and bot message formatting where needed. The embed worker fix in [bot/polling.py](/Users/mali/Documents/Projects/MealTracker/bot/polling.py:287) is valid, but the smoke-helper changes still leave an information-disclosure hole open and the new calibration logic can no longer prove the re-photo behavior it is supposed to validate.

Focused execution evidence: `python -m unittest tests.test_embed_match_smoke tests.test_embed_worker tests.test_match_flow tests.test_matching_threshold` passed (`24` tests). `pytest` was not available in the local venv.

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: Smoke helper still uploads full sample photos and retains extra copies

**Files:** [scripts/embed_match_smoke.py](/Users/mali/Documents/Projects/MealTracker/scripts/embed_match_smoke.py:100), [scripts/embed_match_smoke.py](/Users/mali/Documents/Projects/MealTracker/scripts/embed_match_smoke.py:171), [scripts/embed_match_smoke.py](/Users/mali/Documents/Projects/MealTracker/scripts/embed_match_smoke.py:315), [scripts/embed_match_smoke.py](/Users/mali/Documents/Projects/MealTracker/scripts/embed_match_smoke.py:377), [scripts/embed_match_smoke.py](/Users/mali/Documents/Projects/MealTracker/scripts/embed_match_smoke.py:461), [tests/test_embed_match_smoke.py](/Users/mali/Documents/Projects/MealTracker/tests/test_embed_match_smoke.py:59), [.planning/phases/03-embed-match/03-SECURITY.md](/Users/mali/Documents/Projects/MealTracker/.planning/phases/03-embed-match/03-SECURITY.md:38)

**Issue:** The new helper does not enforce “saved crop artifacts” at all. `_persist_smoke_image_reference()` simply copies whatever file the caller supplied, and the callers still pass full sample images from `--sample`, `--random-food`, and `--second-sample`. `unresolved-probe` bypasses the persisted helper entirely and still embeds the raw prepared sample path directly. For `calibrate`, those copied full-photo artifacts are also left behind in `UPLOADS_DIR/smokes` after the run. The new test at `tests/test_embed_match_smoke.py:59` explicitly blesses copying the original JPEG source image, so the code and tests now harden the exact disclosure path that `T-03-01` says must be removed.

**Fix:**
```python
def _require_crop_artifact(path: Path) -> Path:
    crop_root = (get_settings().UPLOADS_DIR / "crops").resolve()
    resolved = path.expanduser().resolve()
    if crop_root not in resolved.parents:
        raise RuntimeError("smoke inputs must be existing saved crop artifacts")
    return resolved


def _prepare_smoke_crop(path: Path) -> Path:
    return _require_crop_artifact(path)
```

Use that gate in every mode instead of copying arbitrary sample files, or generate an actual crop first and only upload that crop. For calibration-only runs, delete any temporary/persisted artifact in `finally`. Replace the current test with one that rejects non-crop sample paths.

## Warnings

### WR-01: Calibration now self-validates and can no longer catch a broken re-photo path

**Files:** [scripts/embed_match_smoke.py](/Users/mali/Documents/Projects/MealTracker/scripts/embed_match_smoke.py:46), [scripts/embed_match_smoke.py](/Users/mali/Documents/Projects/MealTracker/scripts/embed_match_smoke.py:171), [scripts/embed_match_smoke.py](/Users/mali/Documents/Projects/MealTracker/scripts/embed_match_smoke.py:198), [tests/test_embed_match_smoke.py](/Users/mali/Documents/Projects/MealTracker/tests/test_embed_match_smoke.py:164), [tests/test_embed_match_smoke.py](/Users/mali/Documents/Projects/MealTracker/tests/test_embed_match_smoke.py:212)

**Issue:** `--same-food-peer` is now optional, and the only enforced “same image” gate is `cosine_similarity(sample_vector, sample_vector)`. That check is tautological for any valid non-zero embedding, so `calibrate` can report `"status": "pass"` even when a distinct same-food photo embeds poorly. The tests encode this weakened contract by asserting that a run with no peer is acceptable and by only checking that the gate saw `1.0`.

**Fix:**
```python
if not args.same_food_peer:
    raise RuntimeError("--same-food-peer is required for calibrate")

same_food_similarity = embedding_service.cosine_similarity(sample_vector, same_food_vector)
if same_food_similarity < REQUIRED_REPHOTO_THRESHOLD:
    raise RuntimeError(
        f"same-food/rephoto similarity {same_food_similarity:.6f} below {REQUIRED_REPHOTO_THRESHOLD:.2f}"
    )
```

Keep the self-similarity check only as a secondary sanity assertion. Add a regression test that fails when the peer similarity drops below the required threshold.

---

_Reviewed: 2026-05-28T10:07:21Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: deep_
