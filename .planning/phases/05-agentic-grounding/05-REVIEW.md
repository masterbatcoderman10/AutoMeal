---
phase: 05-agentic-grounding
reviewed: 2026-06-06T16:01:54Z
depth: standard
files_reviewed: 9
files_reviewed_list:
  - app/config.py
  - app/services/interview_schema.py
  - app/services/interview_service.py
  - bot/messages.py
  - tests/test_interview_schema.py
  - tests/test_interview_flow.py
  - tests/test_match_flow.py
  - tests/test_reasoning_contract.py
  - tests/test_bot_contract.py
findings:
  critical: 2
  warning: 1
  info: 0
  total: 3
status: issues_found
---

# Phase 05: Code Review Report

**Reviewed:** 2026-06-06T16:01:54Z
**Depth:** standard
**Files Reviewed:** 9
**Status:** issues_found

## Summary

Reviewed the Phase 05 plan 05-11 finalizer schema ownership changes and the listed contract tests. The implementation removes model-authored provenance from the finalizer schema, but the fail-closed degraded behavior is only applied in one caller. The auto-reasoning finalization path can still persist an all-degraded finalizer run as `COMPLETED`, and Telegram-facing tests still codify success messages for empty finalization results.

## Critical Issues

### CR-01: BLOCKER - All-degraded finalizer outcomes still complete through the reasoning path

**Classification:** BLOCKER
**File:** `app/services/interview_service.py:2013` (exposed by `app/services/reasoning_service.py:2379`)

**Issue:** `_degraded_group_finalizer_outcome()` still returns a writable `FinalSegmentResolution` for every degraded group. `finalize_confirmed_interview()` compensates by checking `_all_finalizer_groups_degraded()` before writing, but `reasoning_service.finalize_meal_from_reasoning()` imports `_run_group_finalizers()` directly, collects those degraded `final_resolution` values, and calls `apply_final_meal_resolution(..., meal_status=MealProcessingStatus.COMPLETED)`. A meal that auto-finalizes from reasoning can therefore hit the exact Phase 05-11 regression: all finalizer groups degrade, fallback rows are written, and the meal is marked completed.

**Fix:**
```python
finalizer_groups = [dict(outcome.audit_state) for outcome in finalizer_outcomes]
all_degraded = finalizer_groups and all(
    str(group.get("status") or "").upper() == "DEGRADED"
    for group in finalizer_groups
)
if all_degraded:
    final_segments = []
    meal_status = MealProcessingStatus.FAILED
    reasoning_state_json["grounding_status"] = "ALL_FINALIZER_GROUPS_DEGRADED"
    reasoning_state_json["grounding_failure"] = {
        "category": "all_finalizer_groups_degraded",
        "reason": "Every finalizer group degraded; no verified nutrition was saved.",
    }
else:
    meal_status = MealProcessingStatus.COMPLETED
```

Apply the same centralized finalizer-outcome policy in both `finalize_confirmed_interview()` and `reasoning_service.finalize_meal_from_reasoning()` so no caller can treat all-degraded outcomes as completed saves.

### CR-02: BLOCKER - Telegram confirmation tests bless successful replies for empty failed finalizations

**Classification:** BLOCKER
**File:** `tests/test_bot_contract.py:2280`

**Issue:** The test patches `finalize_confirmed_interview()` to return `SimpleNamespace(meal_entries=[])` and still asserts `reply_text.assert_awaited_once_with("Meal confirmation saved.")` at line 2296. That is now an invalid contract: plan 05-11 intentionally makes all-degraded finalization return no entries and `MealProcessingStatus.FAILED`. The bot handler paths still close the interview and send success text without checking whether the returned meal resolution actually wrote entries or failed. This can tell the user a meal was saved even when finalization failed closed and no nutrition was persisted.

**Fix:** Update the bot confirmation handlers and tests to branch on the finalization result before deactivating the interview or sending success text.
```python
result = finalized.get("result")
meal_entries = list(getattr(result, "meal_entries", []) or [])
meal = finalized.get("meal")
if getattr(meal, "processing_status", None) == MealProcessingStatus.FAILED or not meal_entries:
    await update.message.reply_text(
        "I couldn't safely save that meal yet. No final entries were written."
    )
    return
```

Then change `tests/test_bot_contract.py` so empty `meal_entries` expects a failure/on-hold reply, not `"Meal confirmation saved."`.

## Warnings

### WR-01: WARNING - Stale finalizer helper references fields removed from the schema

**Classification:** WARNING
**File:** `app/services/interview_service.py:1935`

**Issue:** `_finalizer_has_grounded_url()` still reads `parsed.source_url` and `parsed.grounding_trace`, but `FinalizedGroupResult` no longer defines either field. The helper is currently dead code, which is why the test suite does not catch it, but any future reuse will raise `AttributeError` on a valid finalizer draft.

**Fix:** Remove `_finalizer_has_grounded_url()` and `_trace_has_url_evidence()` if they are obsolete, or rewrite the helper around service-owned `grounding_trace` and `selected_source_ids` only.

---

_Reviewed: 2026-06-06T16:01:54Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: standard_
