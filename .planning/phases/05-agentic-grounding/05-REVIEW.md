---
phase: 05-agentic-grounding
reviewed: 2026-06-05T01:52:12Z
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
  critical: 3
  warning: 4
  info: 0
  total: 7
status: issues_found
---
# Phase 05: Code Review Report

**Reviewed:** 2026-06-05T01:52:12Z
**Depth:** standard
**Files Reviewed:** 13
**Status:** issues_found

## Summary

The reviewed files contain three ship blockers in the exact areas this phase was supposed to harden: the shared finalizer path still saves degraded results as completed meals, two slow-stage workers drop their meal claim before the expensive external call, and the strict-schema layer silently coerces invalid identity/portion fields into `HOME` and `STANDARD`. I also found four robustness gaps that can strand work or drift learned identity data.

## Narrative Findings (AI reviewer)

### CR-01: Grounding/finalizer failures still write completed meals

**Classification:** BLOCKER  
**File:** `app/services/interview_service.py:1551-1705`, `app/services/interview_service.py:1392-1415`, `app/services/reasoning_service.py:2402-2427`  
**Issue:** The shared group-finalizer path converts any timeout/tool/provider failure into `_degraded_group_finalizer_outcome()`, builds a `best_effort=True` resolution, and still calls `apply_final_meal_resolution(..., meal_status=MealProcessingStatus.COMPLETED)`. That is fail-open behavior: a Firecrawl/OpenRouter outage now persists ungrounded or partially grounded food as a completed meal instead of holding the meal for interview/retry. The reviewed tests explicitly lock this in via `DEGRADED_SAVED`, so the bad behavior is currently contract-protected as well.  
**Fix:** Fail closed when the finalizer cannot produce a valid grounded result. Return the meal to an interview/review state, persist the failure metadata, and do not call `apply_final_meal_resolution` until the group is resolved.

```python
if any(group.get("status") == "DEGRADED" for group in finalizer_groups):
    meal.processing_status = MealProcessingStatus.INTERVIEWING
    meal.reasoning_state_json = {
        **existing_state,
        "grounding_status": "FAILED_CLOSED",
        "grounding_failure": degraded_failure,
        "finalizer_groups": finalizer_groups,
    }
    session.add(meal)
    await session.commit()
    return {"finalized": False, "meal_reasoning": meal.reasoning_state_json}
```

### CR-02: Detect/segment workers release the meal claim before slow external work

**Classification:** BLOCKER  
**File:** `bot/polling.py:432-443`, `bot/polling.py:490-534`  
**Issue:** `poll_and_detect_food()` and `poll_and_segment_food()` select a meal with `FOR UPDATE SKIP LOCKED`, then `commit()` before calling `detect_food_photo()` / `segment_food_photo_with_retry()`. The row stays in the same status (`DETECTING` or `SEGMENTING`) until after the expensive call finishes, so another worker can immediately reacquire the same meal and run duplicate LLM work, crop creation, and state transitions. That breaks the single-owner slow-stage guarantee this phase was meant to add.  
**Fix:** Persist a claim before releasing the transaction, or keep the transaction open through the expensive call. A claim token / claimed-at field is safer than holding long locks.

```python
meal.processing_status = MealProcessingStatus.DETECTING_IN_FLIGHT
meal.last_stage_started_at = datetime.now(UTC)
meal.stage_claim_token = str(uuid.uuid4())
await session.commit()

# do slow work here

update = (
    sa.update(MealLog)
    .where(MealLog.id == meal.id, MealLog.stage_claim_token == claim_token)
    .values(processing_status=next_status, stage_claim_token=None)
)
```

### CR-03: Invalid finalizer fields are silently coerced into `HOME` / `STANDARD`

**Classification:** BLOCKER  
**File:** `app/services/interview_schema.py:82-91`, `app/services/interview_schema.py:315-323`  
**Issue:** The schema validators do not fail on bad model output. `source_type` is normalized through `normalize_source_type()` and `portion_bucket` falls back to `"STANDARD"` on any unknown value. In practice, malformed finalizer output like `"source_type": "takeout?"` or `"portion_bucket": "MEDIUM"` is accepted and written as `HOME` / `STANDARD`. That can suppress required grounding for packaged/restaurant meals and invent a default portion instead of rejecting the response.  
**Fix:** Make these validators strict. Reject unknown enum values so the finalizer attempt fails and the caller can retry or fail closed.

```python
@field_validator("source_type", mode="before")
@classmethod
def _normalize_source_type(cls, value: object) -> str:
    normalized = str(value or "").strip().upper()
    if normalized not in {"HOME", "PACKAGED", "RESTAURANT"}:
        raise ValueError("source_type must be HOME, PACKAGED, or RESTAURANT")
    return normalized
```

### WR-01: Match snapshots drop identity metadata that downstream finalization expects

**Classification:** WARNING  
**File:** `app/services/matching_service.py:66-84`, `app/services/reasoning_service.py:2298-2324`, `app/services/meal_resolution_service.py:154-166`, `tests/test_match_flow.py:572-582`  
**Issue:** `_format_candidate_payload()` only persists `candidate_id`, label/confidence fields, and generic evidence text. The downstream reasoning/finalization code tries to read `food_item_id`, `source_type`, `brand_name`, `restaurant_name`, `portion_bucket`, and `quantity_payload` from those candidate snapshots, but production snapshots do not carry them. The tests mask this by hand-building richer candidate dicts that production never emits. Result: auto-confirm writes cannot reliably reuse the matched learned item and may create the wrong duplicate `FoodItem` when the same label exists across different provenance buckets.  
**Fix:** Persist the non-prompt identity metadata in the candidate snapshot, and keep stripping it only from the LLM prompt text if needed.

```python
return {
    "candidate_id": candidate_id,
    "food_item_id": food_item_id,
    "source_type": source_type,
    "brand_name": brand_name,
    "restaurant_name": restaurant_name,
    "portion_bucket": portion_bucket,
    "quantity_payload": quantity_payload,
    ...
}
```

### WR-02: Detection exceptions leave meals stuck in `DETECTING`

**Classification:** WARNING  
**File:** `bot/polling.py:420-449`  
**Issue:** Unlike the segment/embed/match workers, `poll_and_detect_food()` only logs on exception and then sleeps. If `detect_food_photo()` or the DB round-trip fails after the meal is selected, the meal stays in `DETECTING` with no immediate terminal transition, so the pipeline depends on out-of-band recovery instead of making forward progress or failing fast.  
**Fix:** Mirror the other worker loops: reopen a session, merge the meal, and mark it `FAILED` (or a dedicated retryable state) on unexpected exceptions.

### WR-03: Reminder delivery failures are still marked as delivered

**Classification:** WARNING  
**File:** `bot/polling.py:382-393`  
**Issue:** `poll_interview_reminders()` catches `bot.send_message()` failures, but it still sets `last_reminder_at` and increments `reminder_count` afterwards. One transient Telegram failure therefore suppresses the only reminder even though the user never received it.  
**Fix:** Only stamp `last_reminder_at` after a successful send, or store a separate failure timestamp/counter for retries.

### WR-04: Empty-segment meals are stranded in `REASONING` with no worker to consume them

**Classification:** WARNING  
**File:** `bot/polling.py:838-858`  
**Issue:** In `poll_and_match_food_segments()`, the `if not segments:` branch flips the meal to `MealProcessingStatus.REASONING` and immediately `continue`s. This file has no worker that ever selects `REASONING` meals; the only reasoning call happens inline later in the `MATCHING` branch. A meal that reaches matching with zero segment rows is therefore stranded indefinitely.  
**Fix:** Treat “matching meal has no segments” as a hard failure, or call the inline reasoning/finalization path before leaving the `MATCHING` branch.

---

_Reviewed: 2026-06-05T01:52:12Z_  
_Reviewer: the agent (gsd-code-reviewer)_  
_Depth: standard_
