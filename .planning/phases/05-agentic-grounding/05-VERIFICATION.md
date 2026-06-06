---
phase: 05-agentic-grounding
verified: 2026-06-06T17:21:01Z
status: human_needed
score: 10/10 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 8/10
  gaps_closed:
    - "Reasoning-stage all-degraded finalizer runs now fail closed with MealProcessingStatus.FAILED and no final segments."
    - "Telegram meal confirmation handlers now avoid success copy, successful deactivation, and recent-entry context writes when finalization is empty or failed."
  gaps_remaining: []
  regressions: []
human_verification:
  - test: "Live packaged/restaurant all-degraded confirmation after redeploy"
    expected: "A packaged or restaurant meal whose grounding finalizer all-degrades does not become COMPLETED with empty diary rows, sends non-success Telegram copy, and persists ALL_FINALIZER_GROUPS_DEGRADED failure state."
    why_human: "This crosses live Telegram, Docker services, provider/tool behavior, Langfuse/Postgres traces, and the self-hosted SearXNG/Firecrawl stack."
---

# Phase 05: Agentic Grounding Verification Report

**Phase Goal:** Agentic grounding - reasoning and post-interview stages can call bounded grounding tools, persist provenance/trace state, and fail closed instead of producing unsafe completed meals.
**Verified:** 2026-06-06T17:21:01Z
**Status:** human_needed
**Re-verification:** Yes - after 05-12 gap closure

**MVP Mode Note:** ROADMAP marks Phase 5 as `mvp`, but `gsd-sdk query user-story.validate` reports the stored goal is not a valid `As a..., I want..., so that...` user story. This verification uses the roadmap success criteria, Phase 05 plan must-haves, and the previous gap list.

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Finalizer model schema contains only model-owned identity, quantity, nutrition, confidence, and selected evidence references | VERIFIED | `FinalizedGroupResult` excludes model-authored `is_verified`, `provenance`, `source_url`, and `grounding_trace`; tests assert those fields are absent and `selected_source_ids` is present. |
| 2 | Service-owned verification, provenance, source URL, and grounding trace are derived deterministically by the app | VERIFIED | `_derive_finalizer_provenance()` and `_service_owned_grounding_trace()` derive provenance/source/trace from selected same-loop sources in `app/services/interview_service.py:1788`. |
| 3 | Packaged and restaurant verified success requires selected source IDs from the same finalizer loop | VERIFIED | Packaged/restaurant or brand/restaurant groups require selected same-loop evidence and reject unknown selected IDs in `app/services/interview_service.py:1801`. |
| 4 | Complete HOME nutrition can promote through service-derived `model_knowledge` provenance | VERIFIED | HOME/model-knowledge promotion requires explicit confidence above threshold before deriving `model_knowledge` trace in `app/services/interview_service.py:1826`. |
| 5 | Finalizer output has a high finite cap, not the old 4096 cap or an unbounded budget | VERIFIED | `FINALIZER_OUTPUT_MAX_TOKENS=12000` is configured and validated above 4096 in `app/config.py:27`; finalizer calls pass it at `app/services/interview_service.py:467`. |
| 6 | Post-interview all-degraded finalizer runs do not persist completed empty rows | VERIFIED | `finalize_confirmed_interview()` uses `_all_finalizer_groups_degraded()`, switches to `MealProcessingStatus.FAILED`, and writes `final_segments=[]` in `app/services/interview_service.py:1497`. |
| 7 | Reasoning-stage all-degraded finalizer runs do not persist completed empty rows | VERIFIED | `finalize_meal_from_reasoning()` imports the shared policy and, when all groups degrade, passes `meal_status=MealProcessingStatus.FAILED` and `final_segments=[]` to `apply_final_meal_resolution()` in `app/services/reasoning_service.py:2421`. |
| 8 | Telegram confirmation does not send success for empty or failed finalizations | VERIFIED | `_meal_finalization_succeeded()` rejects empty `meal_entries` and FAILED meals; callback, text confirm, and auto-ready paths use it before deactivation/recent-entry writes/success copy in `bot/handlers.py:293`, `780`, `879`, and `1049`. |
| 9 | Previous worker ownership and no-hang runtime gaps remain closed | VERIFIED | Targeted match/bot suites still pass; tests cover single-owner worker claims and zero-segment MATCHING failure paths. |
| 10 | Finalizer-facing source typing preserves or rejects packaged/restaurant identity | VERIFIED | Source typing and schema regressions remain covered in the Phase 05 targeted suite; packaged/restaurant success still requires selected source registry evidence. |

**Score:** 10/10 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `app/services/reasoning_service.py` | Reasoning caller applies all-degraded fail-closed policy | VERIFIED | Imports `_all_finalizer_groups_degraded()` and writes FAILED/no final segments for all-DEGRADED outcomes. |
| `app/services/interview_service.py` | Shared finalizer policy, provenance derivation, output cap wiring, trace persistence | VERIFIED | Shared helper exists; post-interview and reasoning callers both use the policy; stale helper references were removed. |
| `app/services/grounding_service.py` | Bounded loop and URL allowlist enforcement | VERIFIED | Tracks duplicate calls, max tool calls, remaining wall-clock time, per-call timeout, and scrape allowlist. |
| `bot/handlers.py` | Centralized meal-finalization success guard | VERIFIED | Callback, typed confirm, and auto-ready confirmation paths gate success on non-empty entries and non-FAILED meal status. |
| `bot/messages.py` | Non-success copy for unsafe finalization | VERIFIED | `format_grounding_blocker_message(..., saved_as_unverified=False)` reports meal on hold instead of saved. |
| `tests/test_match_flow.py` | Reasoning all-degraded regression | VERIFIED | `test_reasoning_all_degraded_finalizers_fail_closed_without_final_segments` asserts FAILED, no final segments, and `ALL_FINALIZER_GROUPS_DEGRADED`. |
| `tests/test_bot_contract.py` | Bot empty/FAILED finalization regressions | VERIFIED | Tests cover FAILED callback finalization, empty typed confirm, and empty auto-ready finalization without success copy/recent-entry context. |

### Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| `app/services/reasoning_service.py` | `app/services/interview_service.py` | `_all_finalizer_groups_degraded()` import | WIRED | `gsd-sdk verify.key-links` reports the 05-12 key link verified. |
| `bot/handlers.py` | `bot/messages.py` | `_meal_finalization_blocker_message()` uses `format_grounding_blocker_message()` | WIRED | `gsd-sdk verify.key-links` reports the 05-12 key link verified. |
| `finalize_meal_from_reasoning()` | `apply_final_meal_resolution()` | `meal_status` and `final_segments_for_write` | WIRED | All-DEGRADED sets FAILED/no segments before the authoritative write. |
| Confirmation handlers | User success reply | `_meal_finalization_succeeded()` guard | WIRED | Success copy is only after the guard and after successful interview deactivation. |
| Finalizer tool loop | SearXNG-backed Firecrawl search/scrape | `firecrawl_search` / `firecrawl_scrape` | WIRED | Tools are exposed to the finalizer; Firecrawl search is the SearXNG-backed implementation chosen in Phase 05 context. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| --- | --- | --- | --- | --- |
| `app/services/reasoning_service.py` | `finalizer_groups` audit state | `_run_group_finalizers()` | Yes | FLOWING - all-DEGRADED audit state changes the persisted meal status and clears write segments. |
| `bot/handlers.py` | `meal_entries` / meal status | `_finalize_interview_confirmation()` result | Yes | FLOWING - empty entries or FAILED meal status route to blocker copy and keep interview active. |
| `app/services/interview_service.py` | selected source IDs | `source_registry` from finalizer tool loop | Yes | FLOWING - selected IDs are resolved against same-loop registry before provenance is derived. |
| `app/services/grounding_service.py` | allowed URLs and loop budget | search results plus settings | Yes | FLOWING - scrape rejects non-allowlisted URLs and HTTP timeout is bounded by remaining loop time. |
| `MealSegment.ai_reasoning` | grounding trace text/JSON | promoted finalizer item trace | Yes | FLOWING - trace is merged into segment reasoning with structured JSON and readable text. |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| Compile representative Python files | `rtk proxy sh -lc 'python3 -m py_compile $(find app bot tests -name "*.py" | head -80 | tr "\n" " ")'` | Exit 0 | PASS |
| 05-12 artifacts/key links | `rtk gsd-sdk query verify.artifacts ...05-12-PLAN.md --raw` and `rtk gsd-sdk query verify.key-links ...05-12-PLAN.md --raw` | 5/5 artifacts passed; 2/2 key links verified | PASS |
| Gap-closure regression slice | `rtk docker run --rm -v "$PWD":/app -w /app mealttracker-plan05-test python -m unittest tests.test_match_flow tests.test_bot_contract -q` | 103 tests, OK | PASS |
| Phase 05 targeted suite | `rtk docker run --rm -v "$PWD":/app -w /app mealttracker-plan05-test python -m unittest tests.test_reasoning_contract tests.test_reasoning_flow tests.test_grounding_service tests.test_interview_flow tests.test_match_flow tests.test_bot_contract -q` | 205 tests, OK | PASS |
| Bot success literal check | `rtk rg -n "Meal confirmation saved\\." tests/test_bot_contract.py` | Only successful-save expectations at lines 351, 451, 534 | PASS |
| Broad unittest discover | Not run | User-provided evidence says the remaining broad-discover failure reproduces at pre-05-12 base and is unrelated to Phase 05 gap closure | SKIP |

### Probe Execution

| Probe | Command | Result | Status |
| --- | --- | --- | --- |
| Conventional `probe-*.sh` scripts | `find scripts -path '*/tests/probe-*.sh' -type f` | No conventional probe scripts found | SKIP |
| Phase-documented live probes | Phase docs mention live Firecrawl/SearXNG probes but do not declare executable `scripts/.../probe-*.sh` paths | Routed to human verification | SKIP |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| `GROUND-01` | ROADMAP / 05 plans / 05-12 | Reasoning and post-interview stages can call grounding tools when brand/restaurant nutrition data is needed | SATISFIED | Finalizer path exposes `firecrawl_search` and `firecrawl_scrape`; reasoning and post-interview both route through `_run_group_finalizers()`. |
| `GROUND-02` | ROADMAP / 05 plans / 05-12 | Tool loop is bounded by max iterations/calls, 90s wall-clock timeout, cost proxy, and URL allowlist | SATISFIED | Config defaults set 6 tool calls and 90s wall-clock; `GroundingLoopState` enforces call cap/duplicates/time and scrape allowlist; all-degraded bounded exits now fail closed. |
| `GROUND-03` | ROADMAP / 05 plans / 05-12 | Tool-call trace is appended to `MealSegment.ai_reasoning` | SATISFIED | Trace contains queries, fetched URLs, snippets, source registry, iteration/stop metadata and is merged into segment `ai_reasoning`. |

**Orphaned requirements:** None. Plans for Phase 05 account for `GROUND-01`, `GROUND-02`, and `GROUND-03`; `.planning/REQUIREMENTS.md` maps those IDs to Phase 5.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| Phase 05 modified files | n/a | No unreferenced `TBD`/`FIXME`/`XXX`, no actionable placeholder implementation, no success-copy regression | NONE | Empty-list/dict scan hits are normal initializers, helpers, or test fixtures; no blocker anti-pattern found. |

### Human Verification Required

### 1. Live Packaged/Restaurant All-Degraded Confirmation

**Test:** After redeploying the main stack, run a packaged or restaurant meal whose finalizer cannot produce verified nutrition.
**Expected:** The meal does not become `COMPLETED` with empty nutrition rows, Telegram sends non-success blocker/on-hold copy, and persisted state contains `ALL_FINALIZER_GROUPS_DEGRADED`.
**Why human:** This crosses live Telegram, Docker services, provider/tool behavior, Langfuse/Postgres traces, and self-hosted SearXNG/Firecrawl behavior.

### Gaps Summary

No automated codebase gaps remain after 05-12. The two previous blockers are closed in code and covered by targeted regressions:

- Reasoning all-DEGRADED finalizer outcomes now fail closed instead of saving completed empty rows.
- Telegram meal confirmations no longer report success or deactivate as successful when finalization is empty or failed.

The phase is not marked `passed` because live external-service UAT remains necessary for the real Telegram/SearXNG/Firecrawl/provider path.

---

_Verified: 2026-06-06T17:21:01Z_
_Verifier: the agent (gsd-verifier)_
