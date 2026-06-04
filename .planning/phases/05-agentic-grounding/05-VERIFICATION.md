---
phase: 05-agentic-grounding
verified: 2026-06-04T19:55:38Z
status: gaps_found
score: 7/9 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 5/10
  gaps_closed:
    - "Reasoning-stage grounding now routes through the shared bounded group finalizer instead of requiring a post-interview-only tool path."
    - "Grounding HTTP search/scrape now consume remaining loop budget instead of fixed timeouts."
    - "Live grounding traces now persist snippet excerpts, provenance, source URL, and human-readable trace text."
    - "Degraded or unverified outcomes no longer create FoodVisual rows, and matching now filters to verified FoodItems only."
    - "Legacy grounding handoff entry points (`poll_grounding_handoffs`, `poll_post_interview_grounding`, `GROUNDING_PENDING`) are removed."
  gaps_remaining:
    - "Reasoning-model failure can still synthesize READY_TO_WRITE fallback groups from vector hits and bypass the grounded reasoning path."
    - "Per-meal grounding/cost caps are not actually hard because embedding and matching workers release their `skip_locked` claim before slow work finishes."
  regressions: []
gaps:
  - truth: "Reasoning failures do not bypass the grounded reasoning path by auto-confirming from raw vector hits"
    status: failed
    reason: "After a reasoning exception or unparseable response, `run_reasoning_request()` still replaces the failed payload with `_fallback_food_groups_from_match_results()`, which manufactures `AUTO_CONFIRM` / `READY_TO_WRITE` groups from high-similarity vector matches."
    artifacts:
      - path: "app/services/reasoning_service.py"
        issue: "Failure handling at lines 1977-1994 is followed by unconditional fallback-group synthesis, and `_fallback_food_groups_from_match_results()` emits `group_action='AUTO_CONFIRM'` and `group_state='READY_TO_WRITE'`."
      - path: "tests/test_reasoning_flow.py"
        issue: "The regression only covers the empty-candidate unparseable case; it does not cover a 0.99 vector-hit case that would expose the bypass."
    missing:
      - "Do not synthesize fallback groups when the reasoning action is `FAILED_UNCLEAR` or `NEEDS_SCHEMA_REVIEW`."
      - "Add a regression where reasoning output is invalid but the segment has a strong cached vector candidate; the result must not auto-confirm."
  - truth: "Hard per-meal grounding budget caps survive concurrent workers"
    status: failed
    reason: "Both embedding and matching workers select a row with `FOR UPDATE SKIP LOCKED` and then `commit()` before the expensive stage work completes, which releases the claim while the meal is still in the same stage. A second worker can therefore reprocess the same meal and trigger duplicate tool loops, writes, or notifications."
    artifacts:
      - path: "bot/polling.py"
        issue: "Embedding worker commits at line 606 before embeddings finish; matching worker commits at line 861 before matching/reasoning/finalization finish."
      - path: "tests/test_match_flow.py"
        issue: "Current polling tests do not pin multi-worker claim durability or duplicate-stage exclusion."
    missing:
      - "Persist an in-progress claim or separate `*_IN_PROGRESS` status before releasing the lock, or hold the transaction through the expensive work."
      - "Add a regression proving a second poller cannot pick the same meal while stage work is still running."
---

# Phase 05: Agentic Grounding Verification Report

**Phase Goal:** The reasoning stage and post-interview re-grounding stage can invoke SearXNG and Firecrawl as tools when the LLM needs brand or restaurant nutrition data; every tool call is bounded, traced, and the loop cannot run away on cost.
**Verified:** 2026-06-04T19:55:38Z
**Status:** gaps_found
**Re-verification:** Yes — prior `05-VERIFICATION.md` existed with gaps

**MVP Mode Note:** ROADMAP marks Phase 5 as `mvp`, but `gsd-sdk query user-story.validate` reports the stored goal is not a valid `As a..., I want..., so that...` user story. Verification below therefore uses the roadmap success criteria plus plan frontmatter must-haves.

## Goal Achievement

## User Flow Coverage

| Step | Expected | Evidence in codebase | Status |
| --- | --- | --- | --- |
| Reasoning-stage grouped finalization can invoke tools before any interview | Ready-to-write reasoning groups route through `_run_group_finalizers()` and the bounded tool loop | `polling._run_reasoning_pipeline()` calls `reasoning_service.finalize_meal_from_reasoning()`; that function routes ready groups into `_run_group_finalizers()` at `app/services/reasoning_service.py:2322-2335`, and the shared bounded loop exposes tools at `app/services/interview_service.py:364-392` | ✓ VERIFIED |
| Post-interview grouped finalization can invoke tools and save through the single authoritative write path | `finalize_confirmed_interview()` uses the same finalizer loop and writes through `apply_final_meal_resolution()` | Verified in `app/services/interview_service.py` and covered by `tests/test_interview_flow.py:1332-1840` | ✓ VERIFIED |
| Bounded loop exits cleanly with hard caps | Per-group max calls, wall-clock, remaining HTTP timeout, and degraded-save path all enforce a hard budget | Per-loop bounds are implemented in `app/services/grounding_service.py:23-62,113-165` and `app/services/interview_service.py:349-385`, but `bot/polling.py:606,861` releases row claims before slow work, so the same meal can be processed twice and exceed the intended per-meal hard cap | ✗ FAILED |
| URL allowlist blocks fabricated scrape targets | `firecrawl_scrape` only accepts URLs returned by prior search in the same loop | `GroundingLoopState._allowed_urls` and `GroundingService.scrape()` enforce this at `app/services/grounding_service.py:31-42,145-165`; targeted tests passed | ✓ VERIFIED |
| Tool trace is appended and human-readable | Queries, URLs, snippets, provenance, source URL, iteration count, stop reason appear in `MealSegment.ai_reasoning` | Trace schema and formatter live at `app/services/interview_schema.py:174-250` and `app/services/interview_service.py:462-530,1716-1780` | ✓ VERIFIED |

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Reasoning-complete food groups route through the shared bounded grounding finalizer before save | ✓ VERIFIED | `finalize_meal_from_reasoning()` calls `_build_group_finalizer_inputs()` and `_run_group_finalizers()` in `app/services/reasoning_service.py:2322-2335`. |
| 2 | Post-interview finalization uses the same bounded grounding finalizer and the single authoritative save path | ✓ VERIFIED | `_bounded_group_finalizer_response()` is the shared tool loop in `app/services/interview_service.py:349-385`, and both flows end at `apply_final_meal_resolution()`. |
| 3 | Per-loop bounds are implemented across model turns and Firecrawl HTTP calls | ✓ VERIFIED | `GroundingLoopState` tracks `MAX_TOOL_CALLS`, `DUPLICATE_TOOL_CALL`, and `WALL_CLOCK_TIMEOUT` in `app/services/grounding_service.py:23-62`; HTTP timeouts use remaining budget in `app/services/grounding_service.py:113-165`. |
| 4 | Hard per-meal grounding/cost caps cannot be bypassed by duplicate worker execution | ✗ FAILED | `bot/polling.py:606` and `bot/polling.py:861` commit before the slow work completes, releasing the `skip_locked` claim while the meal is still in `EMBEDDING` or `MATCHING`. |
| 5 | Firecrawl scrape is limited to prior-search URLs from the same loop | ✓ VERIFIED | `GroundingService.scrape()` rejects non-allowlisted URLs at `app/services/grounding_service.py:151-152`. |
| 6 | Grounding traces persist queries, fetched URLs, snippet excerpts, provenance, source URL, iteration count, and readable summary text | ✓ VERIFIED | `GroundingTracePayload` includes those fields at `app/services/interview_schema.py:177-186`, and `_format_grounding_trace_text()` renders them at `app/services/interview_service.py:462-490`. |
| 7 | Untrusted tool output is sanitized before being re-fed to the model | ✓ VERIFIED | `_sanitize_tool_payload()` strips tool results to `title` / `url` / `snippet` evidence and marks them `untrusted_tool_output` at `app/services/interview_service.py:194-238`. |
| 8 | Degraded or unverified outcomes do not pollute the learned visual corpus, and matching only uses verified foods | ✓ VERIFIED | `visual_learning_allowed` is gated by resolved verification in `app/services/interview_service.py:1274-1317`; `apply_final_meal_resolution()` creates visuals only when `resolved_food.is_verified` is true at `app/services/meal_resolution_service.py:545-556`; matching filters `FoodItem.is_verified` at `app/services/matching_service.py:132-138`. |
| 9 | Reasoning-model failure cannot bypass grounded reasoning by synthesizing ready-to-write fallback groups | ✗ FAILED | `run_reasoning_request()` catches failure into `FAILED_UNCLEAR` but then repopulates `food_groups` from `_fallback_food_groups_from_match_results()` at `app/services/reasoning_service.py:1977-1994`; the fallback helper emits `AUTO_CONFIRM` / `READY_TO_WRITE` groups at `app/services/reasoning_service.py:1519-1533`. |

**Score:** 7/9 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `app/services/reasoning_service.py` | Reasoning-stage handoff into the shared grounded group finalizer | ⚠ PARTIAL | The shared finalizer handoff exists, but failure fallback can still auto-confirm from vector hits. |
| `app/services/interview_service.py` | Shared bounded grounding finalizer, trace assembly, safe degraded-save handling | ✓ VERIFIED | Tools, sanitization, trace merge, degraded-save visual-learning guard, and authoritative write handoff are present. |
| `app/services/grounding_service.py` | App-owned Firecrawl search/scrape client with loop budget and allowlist enforcement | ✓ VERIFIED | Remaining timeout is threaded into HTTP requests and fabricated URLs are rejected. |
| `app/services/interview_schema.py` | Live finalizer schema with trace/provenance/source-url fields | ✓ VERIFIED | `GroundingTracePayload` and `FinalizedGroupResult` include live trace and provenance fields. |
| `app/services/meal_resolution_service.py` | Singular authoritative save path that blocks unverified visual learning | ✓ VERIFIED | Visual writes are guarded by `resolved_food.is_verified`. |
| `app/services/matching_service.py` | Verified-only match corpus | ✓ VERIFIED | Candidate query filters `FoodItem.is_verified.is_(True)`. |
| `bot/polling.py` | Runtime wiring with retired grounding handoff and durable stage claims | ⚠ PARTIAL | Dead grounding worker entry points are gone, but worker claims are not durable across slow work. |
| `tests/test_reasoning_flow.py` | Regression coverage for reasoning-stage shared finalizer behavior | ⚠ PARTIAL | Coverage proves the shared finalizer path exists, but it does not cover the strong-vector-hit failure bypass. |
| `tests/test_grounding_service.py` | Budget, timeout, allowlist, and duplicate-call regressions | ✓ VERIFIED | Tests cover loop budget propagation, allowlist rejection, and timeout/cap semantics. |
| `tests/test_interview_flow.py` | Inline grounding success/failure trace coverage | ✓ VERIFIED | Tests cover inline grounding, snippets/provenance persistence, and degraded-save stop reasons. |
| `tests/test_match_flow.py` | Authoritative write-path coverage for grounded results | ⚠ PARTIAL | Verified write-path behavior is covered, but duplicate-worker exclusion is not. |
| `tests/test_bot_contract.py` | Removal of dead grounding worker entry points | ✓ VERIFIED | Test asserts `GROUNDING_PENDING` and old worker helpers are absent. |

### Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| `bot/polling.py` | `app/services/reasoning_service.py` | reasoning pipeline calls `finalize_meal_from_reasoning()` | ✓ WIRED | `_run_reasoning_pipeline()` invokes `finalize_meal_from_reasoning()` at `bot/polling.py:67-84`. |
| `app/services/reasoning_service.py` | `app/services/interview_service.py` | ready-to-write reasoning groups -> shared finalizer | ✓ WIRED | `_run_group_finalizers()` is called from `app/services/reasoning_service.py:2331-2335`. |
| `app/services/interview_service.py` | `app/services/grounding_service.py` | bounded tool loop passes remaining budget into search/scrape | ✓ WIRED | Shared loop builds `GroundingLoopState` and uses `GroundingService.search()` / `.scrape()` in `app/services/interview_service.py:349-392`. |
| `GroundingLoopState` | Firecrawl HTTP requests | remaining loop time -> HTTP timeout | ✓ WIRED | `GroundingService._request_timeout_s()` caps each request to `min(tool_timeout, remaining_time)` at `app/services/grounding_service.py:113-119`. |
| `app/services/interview_service.py` | `app/services/meal_resolution_service.py` | degraded/unverified outcomes -> `create_food_visual=False` | ✓ WIRED | `visual_learning_allowed` is false unless resolved verification is true at `app/services/interview_service.py:1274-1317`, and the save path rechecks `resolved_food.is_verified`. |
| `app/services/matching_service.py` | `FoodItem` verification state | only verified foods remain match candidates | ✓ WIRED | Query filter includes `FoodItem.is_verified.is_(True)` at `app/services/matching_service.py:137`. |
| `bot/polling.py` | expensive stage work | `skip_locked` claim remains durable until stage completion | ✗ NOT_WIRED | Pollers release the claim before embedding or matching/reasoning finish at `bot/polling.py:606` and `bot/polling.py:861`. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| --- | --- | --- | --- | --- |
| `app/services/reasoning_service.py` | `final_segments` for ready-to-write reasoning groups | grouped reasoning output -> `_build_group_finalizer_inputs()` -> `_run_group_finalizers()` -> `apply_final_meal_resolution()` | Yes | ✓ FLOWING |
| `app/services/interview_service.py` | grounded nutrition fields and trace on post-interview resolution | finalizer JSON -> merged confirmation item -> `final_resolution_from_confirmation()` | Yes | ✓ FLOWING |
| `app/services/interview_service.py` | `segment.ai_reasoning["grounding_trace"]` and `grounding_trace_text` | `GroundingTracePayload` + merged loop trace | Yes | ✓ FLOWING |
| `bot/polling.py` | per-meal stage ownership | `FOR UPDATE SKIP LOCKED` row claim | No durable claim survives slow work | ✗ DISCONNECTED |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| Reasoning contract + flow + grounding + interview targeted suite | `rtk docker run --rm -v "$PWD":/app -w /app mealttracker-plan05-test python -m unittest tests.test_reasoning_contract tests.test_reasoning_flow tests.test_grounding_service tests.test_interview_flow -q` | Passed, `87` tests | ✓ PASS |
| Interview + match + bot targeted suite | `rtk docker run --rm -v "$PWD":/app -w /app mealttracker-plan05-test python -m unittest tests.test_interview_flow tests.test_match_flow tests.test_bot_contract -q` | Passed, `143` tests | ✓ PASS |
| Combined Phase 05 targeted suite | `rtk docker run --rm -v "$PWD":/app -w /app mealttracker-plan05-test python -m unittest tests.test_reasoning_contract tests.test_reasoning_flow tests.test_grounding_service tests.test_interview_flow tests.test_match_flow tests.test_bot_contract -q` | Passed, `183` tests | ✓ PASS |
| Full unit discovery | `rtk docker run --rm -v "$PWD":/app -w /app mealttracker-plan05-test python -m unittest discover -q` | Passed, `313` tests | ✓ PASS |

### Probe Execution

| Probe | Command | Result | Status |
| --- | --- | --- | --- |
| Conventional phase probes | `find scripts -path '*/tests/probe-*.sh' -type f` | No Phase 05 probe scripts found and none were declared in the Phase 05 plans/summaries | ? SKIP |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| `GROUND-01` | 05-01, 05-02, 05-03, 05-04, 05-05 | Reasoning stage and post-interview stage can call search/fetch tools when nutrition needs grounding | ✗ BLOCKED | Shared tool-capable finalizer exists for reasoning and post-interview flows, but reasoning failure still falls through to synthesized `AUTO_CONFIRM` groups instead of reliably preserving the grounded path. |
| `GROUND-02` | 05-01, 05-02, 05-03, 05-04, 05-05 | Tool loop bounded by max iterations, wall-clock timeout, cost/call caps, URL allowlist | ✗ BLOCKED | Per-loop cap, wall-clock, and allowlist are implemented, but the effective per-meal hard cap is broken by duplicate-worker races in `bot/polling.py`. |
| `GROUND-03` | 05-01, 05-02, 05-03, 05-04, 05-05 | Tool-call trace (queries, URLs, snippets) is appended to `MealSegment.ai_reasoning` | ✓ SATISFIED | Live trace schema and formatting include queries, URLs, snippets, provenance, source URL, and iteration count. |
| `REASON-04` | 05-01 | Reasoning trace is written to `MealSegment.ai_reasoning` for audit | ✓ SATISFIED | Reasoning trace persistence remains intact, and Phase 05 grounding trace appends to it rather than replacing it. |
| `INTERVIEW-03` | 05-01, 05-02 | Interview answers run a re-grounding pass with tools to populate nutrition | ✓ SATISFIED | `finalize_confirmed_interview()` uses the shared grounded finalizer; targeted interview tests cover inline packaged-food grounding. |
| `INTERVIEW-04` | 05-02 | If post-interview confidence stays low, commit best-effort with `is_verified=false` | ✓ SATISFIED | Degraded-save path persists `INTERVIEW_BEST_EFFORT` with `is_verified=false` and no visual learning. |
| `MATCH-04` | 05-02, 05-03 | Confirmed identifications create `FoodVisual` rows so the visual vocabulary grows | ✓ SATISFIED | Verified outcomes still write `FoodVisual` rows through `apply_final_meal_resolution()`; degraded/unverified saves are correctly excluded. |

**Orphaned requirements:** None found for Phase 5 in `.planning/REQUIREMENTS.md`.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| `app/services/reasoning_service.py` | 1977 | Failure payload is immediately followed by fallback-group synthesis | 🛑 BLOCKER | Reasoning outages can bypass grounded reasoning and auto-confirm from raw vector hits. |
| `app/services/reasoning_service.py` | 1523 | `_fallback_food_groups_from_match_results()` emits `AUTO_CONFIRM` / `READY_TO_WRITE` groups | 🛑 BLOCKER | Manufactures a success path even when reasoning failed. |
| `bot/polling.py` | 606 | Embedding worker commits before embeddings finish | 🛑 BLOCKER | A second worker can re-pick the same `EMBEDDING` meal and duplicate expensive work. |
| `bot/polling.py` | 861 | Matching worker commits before matching/reasoning/finalization finish | 🛑 BLOCKER | A second worker can duplicate grounded reasoning, final writes, and notifications, defeating hard per-meal caps. |
| `bot/polling.py` | 856 | Empty-segment `MATCHING` meal is moved to `REASONING` | ⚠ WARNING | The meal can become stranded because no separate reasoning worker consumes that state. |
| `app/services/interview_service.py` | 448 | `is_verified=true` alone counts as inline-grounded even without nutrition fields | ⚠ WARNING | A finalizer payload can suppress `NEEDS_GROUNDING` semantics and still later save as unverified. |

### Gaps Summary

Phase 05 is materially closer to complete than the previous verification claimed. The original grounding-path gaps are closed in code: reasoning-complete groups now route through the shared tool-capable finalizer, remaining loop time is propagated into Firecrawl HTTP calls, live trace schema now carries snippets/provenance/source URLs, degraded saves no longer write `FoodVisual` rows, matching filters to verified foods only, tool output is sanitized before being re-shown to the model, and the old `GROUNDING_PENDING` worker surface is gone.

The remaining failures are not about missing artifacts. They are runtime-integrity failures in the live code. First, the reasoning fallback still manufactures `AUTO_CONFIRM` / `READY_TO_WRITE` groups after a model failure, which means the grounded reasoning path can be skipped exactly when the model is unavailable. Second, the embedding and matching workers release their `skip_locked` claim before the slow work finishes, so a second worker can process the same meal and exceed the intended hard per-meal grounding budget through duplicate loops and duplicate writes. Those two defects are enough to keep `GROUND-01` and `GROUND-02` blocked.

The Phase 05 code review findings therefore still matter for goal achievement. They are not cosmetic follow-ups; they directly contradict the claim that the grounded reasoning path is reliable and that the loop is hard-bounded per meal.

---

_Verified: 2026-06-04T19:55:38Z_  
_Verifier: the agent (gsd-verifier)_
