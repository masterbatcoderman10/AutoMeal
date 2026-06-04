---
phase: 05-agentic-grounding
reviewed: 2026-06-04T19:48:04Z
depth: standard
files_reviewed: 13
files_reviewed_list:
  - app/services/grounding_service.py
  - app/services/interview_schema.py
  - app/services/interview_service.py
  - app/services/matching_service.py
  - app/services/meal_resolution_service.py
  - app/services/reasoning_service.py
  - bot/polling.py
  - tests/test_bot_contract.py
  - tests/test_grounding_service.py
  - tests/test_interview_flow.py
  - tests/test_match_flow.py
  - tests/test_reasoning_contract.py
  - tests/test_reasoning_flow.py
findings:
  critical: 2
  warning: 2
  info: 0
  total: 4
status: issues_found
---

# Phase 05: Code Review Report

**Reviewed:** 2026-06-04T19:48:04Z
**Depth:** standard
**Files Reviewed:** 13
**Status:** issues_found

## Summary

Reviewed the grounding, reasoning, interview finalizer, matching, and polling paths for Phase 05 at standard depth. The highest-risk defects are a reasoning failure path that can still auto-confirm meals from raw vector hits, and worker loops that release their `skip_locked` claim before the expensive stage work, which makes duplicate processing possible as soon as a second poller instance exists.

The test suite covers many happy paths and contract shapes, but it does not currently pin the failure-mode behavior that would catch these regressions.

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: Reasoning outages still fall through to vector-only auto-confirm

**Classification:** BLOCKER
**File:** `app/services/reasoning_service.py:1977-1994`, `tests/test_reasoning_flow.py:795-827`
**Issue:** When `_run_reasoning_model()` raises or returns unparseable output, `run_reasoning_request()` builds a `FAILED_UNCLEAR` payload, then immediately replaces the empty `food_groups` with `_fallback_food_groups_from_match_results()`. For a segment that already has a high-similarity cached candidate, `evaluate_reasoning_gate()` can therefore return `AUTO_CONFIRM` even though the meal-level reasoning pass never succeeded. That bypasses the Phase 05 grouping/exclusion logic exactly when the model is unavailable. The existing regression only covers the empty-candidate case, so this failure mode is untested.
**Fix:** Do not synthesize fallback groups after a model exception or parse failure. Preserve `FAILED_UNCLEAR` and force interview/manual recovery instead, and add a regression where the reasoning response is invalid but the segment has a 0.99 vector hit.

```python
# app/services/reasoning_service.py
if (
    parsed.get("action") not in {_FAILED_UNCLEAR_STATE, _REVIEW_STATE}
    and not parsed.get("food_groups")
    and match_results
):
    parsed["food_groups"] = _fallback_food_groups_from_match_results(match_results)
    parsed["food_group_count"] = len(parsed["food_groups"])
```

### CR-02: Embedding and matching workers drop their row claim before stage work finishes

**Classification:** BLOCKER
**File:** `bot/polling.py:583-615`, `bot/polling.py:845-885`
**Issue:** Both polling loops select a meal with `FOR UPDATE SKIP LOCKED`, then `commit()` before performing the slow work. At that point the lock is gone but the meal is still in the same stage (`EMBEDDING` or `MATCHING`), so another worker process can pick the same row and run the stage a second time. In the matching stage that can duplicate `DiaryEntry`/`FoodVisual` writes or send duplicate interview/completion messages.
**Fix:** Keep the claim durable before releasing the lock: either hold the transaction through the stage, or persist an explicit in-progress claim/token or separate `*_IN_PROGRESS` status before committing, and make the poll query ignore claimed rows.

```python
# One viable shape
meal.processing_status = MealProcessingStatus.MATCHING_IN_PROGRESS
meal.worker_claim_id = claim_id
await session.commit()

# Later workers must exclude rows with an active claim/in-progress status.
```

## Warnings

### WR-01: Empty-segment meals get stranded in `REASONING`

**Classification:** WARNING
**File:** `bot/polling.py:856-859`
**Issue:** If the matching worker finds a `MATCHING` meal with zero segments, it transitions the meal to `REASONING` and continues. This loop only polls `MATCHING` meals, and Phase 05 does not have a separate reasoning worker consuming `REASONING`, so the meal becomes stuck permanently instead of failing fast.
**Fix:** Mirror the embedding worker’s behavior here: mark the meal `FAILED`, or handle the empty-meal finalization inline before leaving the loop. Add a regression for the zero-segment matching path.

```python
if not segments:
    logger.error("Matching worker found meal %s without segments; marking FAILED", meal.id)
    _transition_meal_status(meal, MealProcessingStatus.FAILED)
    await session.commit()
    continue
```

### WR-02: `is_verified=true` without nutrition silently loses the grounding handoff

**Classification:** WARNING
**File:** `app/services/interview_schema.py:224-339`, `app/services/interview_service.py:448-454`, `app/services/interview_service.py:1247-1319`, `app/services/meal_resolution_service.py:356-362`, `app/services/meal_resolution_service.py:423-429`
**Issue:** `FinalizedGroupResult` allows `is_verified=True` even when every nutrition field is null. `final_resolution_from_confirmation()` treats that flag as enough to skip `grounding_prep`, mark the item as inline-resolved, and set reasoning text like `finalized inline`. Later, `resolve_or_create_food_item()` notices nutrition is incomplete and downgrades the saved `FoodItem` back to unverified. The result is an unverified save with no grounding prep payload and no explicit `NEEDS_GROUNDING` marker, which makes the retry/handoff state inconsistent.
**Fix:** Make the contract enforce that verified finalizer outputs include complete nutrition, or change `_item_has_inline_grounding_result()` so `is_verified` alone is not enough to suppress grounding prep.

```python
def _item_has_inline_grounding_result(item: Mapping[str, Any]) -> bool:
    return all(
        _optional_float(item.get(field_name)) is not None
        for field_name in ("serving_size_g", "calories", "protein_g", "carbs_g", "fat_g", "fiber_g")
    )
```

---

_Reviewed: 2026-06-04T19:48:04Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: standard_
