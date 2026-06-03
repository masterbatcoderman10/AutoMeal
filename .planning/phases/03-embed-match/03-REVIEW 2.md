---
phase: 03-embed-match
reviewed: 2026-05-27T22:04:54Z
depth: standard
files_reviewed: 16
files_reviewed_list:
  - app/services/embedding_service.py
  - app/services/llm_client.py
  - app/services/matching_service.py
  - bot/main.py
  - bot/messages.py
  - bot/polling.py
  - scripts/embed_match_smoke.py
  - tests/test_embedding_service.py
  - tests/test_match_flow.py
  - tests/test_bot_contract.py
  - app/models/meal_segment.py
  - app/models/food_visual.py
  - app/models/food_item.py
  - app/models/diary_entry.py
  - app/models/meal_log.py
  - app/config.py
findings:
  critical: 1
  warning: 3
  info: 0
  total: 4
status: issues_found
---

# Phase 03: Code Review Report

**Reviewed:** 2026-05-27T22:04:54Z
**Depth:** standard
**Files Reviewed:** 16
**Status:** issues_found

## Summary

Reviewed the final Phase 03 checkout, including the post-merge repair state referenced by commit `6235787`. The mocked unit suite passes, but the real happy-path runtime is still unsafe: the successful match flow can crash before commit, and the smoke helper both misimplements the calibration gate and persists invalid file paths into the database.

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: Successful matches dereference an unloaded async relationship before commit

**File:** `app/services/matching_service.py:218-233`, `bot/polling.py:407-435`
**Issue:** `_best_food_visual_match()` returns a plain `FoodVisual` row with no eager loading. The completion path then reads `result.food_visual.food_item` before `session.commit()`. Under `AsyncSession`, that relationship access performs implicit IO; on real ORM rows it raises `MissingGreenlet`, so a meal that should complete can fall into the outer failure handler instead of committing its `DiaryEntry`/`FoodVisual` rows.
**Fix:**
```python
from sqlalchemy.orm import selectinload

statement = (
    select(FoodVisual, distance_expr.label("distance"))
    .options(selectinload(FoodVisual.food_item))
    .where(FoodVisual.is_invalidated.is_(False))
    .order_by(distance_expr)
    .limit(1)
)
```
Or return the needed `FoodItem` fields directly from the match query and carry them in `SegmentMatchResult`.

## Warnings

### WR-01: Calibration applies the 0.99 self-similarity gate to a different photo

**File:** `scripts/embed_match_smoke.py:132-143`
**Issue:** Phase 03's acceptance contract requires same-image self-similarity `>= 0.99`. `_run_calibrate()` instead embeds `--same-food-peer` and rejects the run unless that different image also clears `0.99`. That is stricter than the roadmap and will false-fail valid re-photo samples.
**Fix:** Embed `sample_path` twice for the 0.99 gate, report the peer image as a separate same-food check, and only apply a distinct threshold to the re-photo comparison if that is an explicit requirement.

### WR-02: Smoke modes commit database rows that point at deleted temp files

**File:** `scripts/embed_match_smoke.py:243-253`, `scripts/embed_match_smoke.py:267-278`, `scripts/embed_match_smoke.py:385-420`, `scripts/embed_match_smoke.py:431-508`
**Issue:** For HEIC inputs, `_prepare_sample_image()` writes a temp JPEG. `seed-demo` and `repeat-confirmation` persist that temp path into `FoodVisual.cropped_image_url`, `MealLog.image_url`, and `MealSegment.cropped_image_url`, then call `temp_dir.cleanup()`. After the script exits, those committed rows reference files that no longer exist.
**Fix:** Copy the prepared JPEG into a durable uploads path before persisting it, or persist the original source asset path and transcode on read instead of storing a temp filename.

### WR-03: Match-time embedding retries miss actual transport failures and retry validation bugs instead

**File:** `app/services/matching_service.py:106-127`
**Issue:** `_embed_with_retry()` retries `TypeError`, `ValueError`, and `RuntimeError`, but not `httpx.HTTPError`. The query/write-back embedding path therefore fails immediately on transient 429/5xx/network errors from OpenRouter, while malformed vectors are retried instead of failing closed.
**Fix:**
```python
import httpx

async for attempt in AsyncRetrying(
    stop=stop_after_attempt(MAX_MATCHING_RETRIES),
    wait=wait_exponential_jitter(initial=0.4, max=1.8),
    retry=retry_if_exception_type((httpx.HTTPError,)),
    reraise=True,
):
    ...
```
Let validation exceptions bubble without retry.

---

_Reviewed: 2026-05-27T22:04:54Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: standard_
