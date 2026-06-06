---
phase: 05-agentic-grounding
verified: 2026-06-06T16:08:32Z
status: gaps_found
score: 8/10 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 7/10
  gaps_closed:
    - "Detect and segment workers now keep single-owner stage claims while slow work is in flight."
    - "MATCHING meals with zero segment rows now fail instead of being parked in REASONING."
    - "Finalizer-facing source_type validation now rejects unknown values instead of coercing them to HOME."
    - "Post-interview all-degraded finalizer runs now fail closed instead of saving completed empty rows."
  gaps_remaining:
    - "Reasoning-stage all-degraded finalizer runs can still persist MealProcessingStatus.COMPLETED."
    - "Telegram confirmation handlers can still send success for empty or failed meal finalizations."
  regressions: []
gaps:
  - truth: "Reasoning-stage all-degraded finalizer runs cannot persist MealProcessingStatus.COMPLETED with empty best-effort nutrition rows."
    status: failed
    reason: "finalize_meal_from_reasoning() imports and runs the shared finalizer, but it does not apply the all-degraded policy that finalize_confirmed_interview() now applies. It passes degraded final_resolution rows into apply_final_meal_resolution() with meal_status=MealProcessingStatus.COMPLETED."
    artifacts:
      - path: "app/services/reasoning_service.py"
        issue: "Lines 2379-2389 collect _run_group_finalizers() outcomes, including DEGRADED outcomes; lines 2420-2424 always save final_segments with MealProcessingStatus.COMPLETED."
      - path: "app/services/interview_service.py"
        issue: "Lines 2013-2050 show degraded outcomes still carry writable best-effort final_resolution values; only the interview caller filters all-degraded runs before write."
    missing:
      - "Apply the same all-finalizer-groups-degraded policy in finalize_meal_from_reasoning() before calling apply_final_meal_resolution()."
      - "When all reasoning finalizer groups degrade, write no final segments and set MealProcessingStatus.FAILED with ALL_FINALIZER_GROUPS_DEGRADED reasoning state."
      - "Add a reasoning-path regression where _run_group_finalizers() returns only DEGRADED audit states and assert COMPLETED is not used."
  - truth: "Telegram/user-facing confirmation must not imply a meal was saved when finalization wrote no entries or failed closed."
    status: failed
    reason: "The meal confirmation handlers deactivate the interview and send Meal confirmation saved. without checking finalized result meal_entries or the meal processing_status. Existing bot tests still assert success for empty finalization results."
    artifacts:
      - path: "bot/handlers.py"
        issue: "Callback confirmation lines 749-763, text confirmation lines 841-853, and auto-ready confirmation lines 1006-1018 all send success after _finalize_interview_confirmation() without checking empty meal_entries or failed meal status."
      - path: "tests/test_bot_contract.py"
        issue: "Lines 570-590 and 2275-2296 explicitly assert Meal confirmation saved. when finalize_confirmed_interview() returns empty meal_entries."
    missing:
      - "Centralize a finalization-result check that treats MealProcessingStatus.FAILED or empty meal_entries as a non-success response for meal interviews."
      - "Do not deactivate the interview as successful or send Meal confirmation saved. when finalization failed closed or produced no entries."
      - "Update bot contract tests so empty/failed finalizations expect the blocker/on-hold copy, not a success message."
human_verification:
  - test: "Live post-fix confirmation of a packaged or restaurant meal that previously all-degraded."
    expected: "If grounding cannot produce verified nutrition, the bot reports that the meal was not safely saved and no completed empty diary rows are created."
    why_human: "The current static verification found blocking code paths; after fixes, a live Telegram/Langfuse/Postgres run is still needed to validate provider behavior and user-facing wording."
---

# Phase 05: Agentic Grounding Verification Report

**Phase Goal:** Agentic grounding finalizer path closes Phase 05 requirements by using grounded evidence, deterministic provenance, bounded finalizer output, and fail-closed behavior.
**Verified:** 2026-06-06T16:08:32Z
**Status:** gaps_found
**Re-verification:** Yes - after 05-11 finalizer schema ownership changes and code review findings

**MVP Mode Note:** ROADMAP marks Phase 5 as `mvp`, but `gsd-sdk query user-story.validate` reports the stored goal is not a valid `As a..., I want..., so that...` user story. Verification therefore uses the roadmap success criteria plus plan-frontmatter must-haves.

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Finalizer model schema contains only model-owned identity, quantity, nutrition, confidence, and selected evidence references | VERIFIED | `FinalizedGroupResult` exposes food/nutrition fields plus `selected_source_ids`; it no longer exposes `is_verified`, `provenance`, `source_url`, or `grounding_trace` in `app/services/interview_schema.py:224-248`. |
| 2 | Service-owned verification, provenance, source URL, and grounding trace are derived deterministically by the app | VERIFIED | `_derive_finalizer_provenance()` and `_service_owned_grounding_trace()` derive metadata from same-loop selected sources in `app/services/interview_service.py:1788-1907`. |
| 3 | Packaged and restaurant verified success requires selected source IDs from the same finalizer loop | VERIFIED | `_derive_finalizer_provenance()` requires selected evidence for PACKAGED/RESTAURANT or source-origin grounding and rejects unknown IDs through `_validate_selected_evidence_ids()` in `app/services/interview_service.py:1788-1875`. |
| 4 | Complete HOME nutrition can promote through service-derived model_knowledge provenance | VERIFIED | No selected evidence is required for HOME, but confidence must be present and above threshold before `model_knowledge` provenance is returned in `app/services/interview_service.py:1828-1842`. |
| 5 | Finalizer output has a high finite cap, not the old 4096 cap or an unbounded budget | VERIFIED | `FINALIZER_OUTPUT_MAX_TOKENS=12000` is defined and validated above 4096 in `app/config.py:27,74-79`, and passed into chat completion at `app/services/interview_service.py:467`. |
| 6 | Post-interview all-degraded finalizer runs do not persist completed empty rows | VERIFIED | `finalize_confirmed_interview()` detects all `DEGRADED` finalizer groups, switches to `MealProcessingStatus.FAILED`, and writes no final segments at `app/services/interview_service.py:1497-1515`. |
| 7 | Reasoning-stage all-degraded finalizer runs do not persist completed empty rows | FAILED | `finalize_meal_from_reasoning()` collects `_run_group_finalizers()` outcomes and always calls `apply_final_meal_resolution(..., meal_status=MealProcessingStatus.COMPLETED)` at `app/services/reasoning_service.py:2379-2424`. |
| 8 | Telegram confirmation does not send success for empty or failed finalizations | FAILED | `bot/handlers.py:749-763`, `841-853`, and `1006-1018` send `"Meal confirmation saved."` without checking `meal_entries` or failed meal status; `tests/test_bot_contract.py:570-590` and `2275-2296` still assert success for empty results. |
| 9 | Previous worker ownership and no-hang runtime gaps remain closed | VERIFIED | Detect and segment now hold the `skip_locked` transaction through slow work, and zero-segment MATCHING transitions to `FAILED` in `bot/polling.py`; matching tests include single-worker claim regressions. |
| 10 | Finalizer-facing source typing preserves or rejects packaged/restaurant identity | VERIFIED | `ConfirmationItem` and `FinalizedGroupResult` use `parse_authoritative_source_type()` in `app/services/interview_schema.py:82-85,325-328`; invalid values now raise instead of normalizing to HOME. |

**Score:** 8/10 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `app/config.py` | High finite finalizer output cap | VERIFIED | `FINALIZER_OUTPUT_MAX_TOKENS=12000` exists and rejects values at or below 4096. |
| `app/services/interview_schema.py` | Draft-only finalizer schema without model-authored service metadata | VERIFIED | Model-facing fields are narrowed and strict authoritative source typing is present. |
| `app/services/interview_service.py` | Evidence registry, deterministic provenance, output cap wiring, post-interview all-degraded fail-closed policy | PARTIAL | Core schema/provenance/cap/post-interview policy exists, but stale dead helpers still reference removed fields. |
| `app/services/reasoning_service.py` | Reasoning-stage finalizer path with same fail-closed all-degraded policy | FAILED | Shared finalizer is wired, but all-degraded reasoning outcomes still complete. |
| `bot/handlers.py` | User-facing confirmation honors failed/empty finalization result | FAILED | Success reply is unconditional on meal finalization quality for meal confirmations. |
| `bot/messages.py` | Failure/on-hold copy exists for unsafe saves | VERIFIED | `format_grounding_blocker_message(..., saved_as_unverified=False)` provides appropriate wording. |
| `tests/test_interview_schema.py` | Schema regression for removed service-owned fields | VERIFIED | Tests assert finalizer schema excludes operational/service-owned fields and includes `selected_source_ids`. |
| `tests/test_interview_flow.py` | Finalizer promotion, source registry, malformed output, and post-interview all-degraded coverage | VERIFIED | Tests cover the post-interview path and selected-source promotion. |
| `tests/test_match_flow.py` | Reasoning-stage shared finalizer routing coverage | PARTIAL | Existing tests cover successful reasoning finalization, but not all-degraded fail-closed behavior. |
| `tests/test_bot_contract.py` | Bot confirmation contract for failed/empty finalization | FAILED | Current tests bless success for empty finalization results. |

### Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| `group_finalizer_response_format()` | `FinalizedGroupResult` | Pydantic schema | WIRED | Response format now points at the draft-only schema with `selected_source_ids`. |
| `_bounded_group_finalizer_response()` | LLM finalizer call | `max_tokens=FINALIZER_OUTPUT_MAX_TOKENS` | WIRED | Finalizer chat completion uses the finite output cap. |
| Finalizer tool loop | source registry | `search`/`scrape` trace capture | WIRED | Service trace includes `source_registry`; selected IDs resolve through `_validate_selected_evidence_ids()`. |
| `finalize_confirmed_interview()` | `apply_final_meal_resolution()` | all-degraded policy before write | WIRED | All-degraded post-interview writes `FAILED` with no final segments. |
| `finalize_meal_from_reasoning()` | `apply_final_meal_resolution()` | all-degraded policy before write | NOT_WIRED | Reasoning caller always passes `MealProcessingStatus.COMPLETED`. |
| `bot.handlers` | user success reply | finalization result inspection | NOT_WIRED | Empty or failed finalization results are not checked before success copy. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| --- | --- | --- | --- | --- |
| `app/services/interview_schema.py` | finalizer draft fields | LLM response schema | Yes | FLOWING - narrowed draft schema excludes service-owned fields. |
| `app/services/interview_service.py` | `selected_source_ids` -> provenance/source_url/trace | same-loop `source_registry` | Yes | FLOWING - packaged/restaurant success derives citations from registry entries. |
| `app/services/interview_service.py` | all-degraded post-interview finalizer groups | `_run_group_finalizers()` audit states | Yes | FLOWING - maps to FAILED and no final segments. |
| `app/services/reasoning_service.py` | all-degraded reasoning finalizer groups | `_run_group_finalizers()` audit states | No | HOLLOW - audit state is recorded, but write policy ignores all-degraded status and completes. |
| `bot/handlers.py` | finalization result `meal_entries` / meal status | `_finalize_interview_confirmation()` | No | DISCONNECTED - helper can extract entries, but success branches do not gate on empty/failed results. |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| MVP goal format guard | `rtk gsd-sdk query user-story.validate --story "$PHASE_GOAL" --raw` | Returned `valid: false` with missing `As a`, `I want`, and `so that` clauses | PASS |
| 05-11 artifact contract | `rtk gsd-sdk query verify.artifacts .planning/phases/05-agentic-grounding/05-11-PLAN.md --raw` | `all_passed: true`, 4/4 artifacts passed existence/substance checks | PASS |
| Targeted unittest slices | `rtk python3 -m unittest ... -q` | Host `python3` unittest invocations produced no output for 40s and were terminated; no passing result recorded | SKIP |
| Probe discovery | `find scripts -path '*/tests/probe-*.sh' -type f` plus phase doc grep | No conventional `probe-*.sh` scripts or executable phase probes found | SKIP |

### Probe Execution

| Probe | Command | Result | Status |
| --- | --- | --- | --- |
| Conventional phase probes | `find scripts -path '*/tests/probe-*.sh' -type f` | No probe scripts found; phase docs mention live probes/UAT but no `probe-*.sh` artifact exists | SKIP |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| `GROUND-01` | ROADMAP / 05 plans | Reasoning and post-interview stages can call SearXNG and Firecrawl tools for brand/restaurant nutrition | BLOCKED | Tool/finalizer path is wired, but the reasoning-stage all-degraded path can still mark a failed grounding run as completed. |
| `GROUND-02` | ROADMAP / 05 plans | Tool loop is bounded: max iterations, wall-clock timeout, per-meal cost cap, URL allowlist, clean exit | BLOCKED | Loop bounds and previous worker no-hang gaps are fixed, but reasoning all-degraded clean-exit policy and Telegram failure surface are incomplete. |
| `GROUND-03` | ROADMAP / 05 plans | Tool-call trace is appended to `MealSegment.ai_reasoning` | SATISFIED | Service-owned trace fields are derived from loop state and selected source IDs; trace persistence tests cover snippets/provenance/source URL. |

**Orphaned requirements:** None found for Phase 05. Phase 6 is the only later roadmap phase and covers bot surface/daily summary, but it does not explicitly own Phase 05 finalizer fail-closed behavior; no current blocker is deferred.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| `app/services/reasoning_service.py` | 2424 | `MealProcessingStatus.COMPLETED` hardcoded after shared finalizer outcomes | BLOCKER | All-degraded reasoning finalizer runs can complete with best-effort empty nutrition rows. |
| `bot/handlers.py` | 763, 853, 1018 | Unconditional `"Meal confirmation saved."` after finalization | BLOCKER | User can be told a meal was saved even when finalization produced no entries or failed closed. |
| `tests/test_bot_contract.py` | 590, 2296 | Tests assert success for empty finalization results | BLOCKER | Test suite preserves the wrong user-facing contract. |
| `app/services/interview_service.py` | 1935, 1937 | Dead helper references removed `FinalizedGroupResult.source_url` and `.grounding_trace` fields | WARNING | `rg` shows no callers, so this is not live today, but any future reuse will raise `AttributeError`. |

### Human Verification Required

### 1. Live Packaged/Restaurant All-Degraded Confirmation

**Test:** After the blockers are fixed, run a live Telegram confirmation for a packaged or restaurant meal whose finalizer cannot produce verified nutrition.
**Expected:** The meal does not become `COMPLETED` with empty nutrition rows, and the bot clearly reports that the meal was not safely saved.
**Why human:** Provider behavior, Telegram wording, Langfuse trace shape, and Postgres rows need a real end-to-end run.

### Gaps Summary

Phase 05 is still not complete. The 05-11 schema ownership work is mostly real: the model-facing finalizer schema is draft-only, source IDs drive deterministic provenance, the high finite output cap is present, strict source typing is fixed, and the post-interview all-degraded path now fails closed.

Two blockers remain. The reasoning finalizer caller did not adopt the all-degraded policy, so auto-finalization from reasoning can still save degraded fallback rows as `COMPLETED`. Separately, Telegram confirmation handlers still send success and close the interview without checking whether finalization wrote entries or failed; the bot tests explicitly assert that wrong behavior for empty results. The stale helper that references removed finalizer fields is a warning because it is dead code, but it should be removed or updated while closing the blockers.

---

_Verified: 2026-06-06T16:08:32Z_
_Verifier: the agent (gsd-verifier)_
