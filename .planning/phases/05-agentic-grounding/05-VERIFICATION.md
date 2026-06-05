---
phase: 05-agentic-grounding
verified: 2026-06-05T02:01:44Z
status: gaps_found
score: 7/10 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 7/9
  gaps_closed:
    - "Reasoning failures do not bypass the grounded reasoning path by auto-confirming from raw vector hits."
    - "Embedding and matching workers now keep single-owner stage claims while slow work is in flight."
  gaps_remaining: []
  regressions:
    - "Detect and segment workers still release their row claim before slow work, so the Phase 05 per-meal hard-cap guarantee is not true end-to-end."
    - "MATCHING meals with zero segment rows still move to REASONING with no live worker consuming that state, so meals can hang until janitor recovery."
    - "Finalizer source_type validation still coerces unknown values to HOME, which can suppress packaged/restaurant grounding."
gaps:
  - truth: "Hard per-meal grounding/cost caps survive concurrent workers end-to-end"
    status: failed
    reason: "Embedding and matching ownership is now durable, but detect and segment still commit before their slow external calls. A second worker can reacquire the same meal before the first worker finishes, which can duplicate downstream grounding work and break the per-meal hard-cap contract."
    artifacts:
      - path: "bot/polling.py"
        issue: "poll_and_detect_food() commits the skip-locked claim before detect_food_photo() at lines 432-438."
      - path: "bot/polling.py"
        issue: "poll_and_segment_food() commits the skip-locked claim before segment_food_photo_with_retry() at lines 490-497."
    missing:
      - "Keep detect-stage ownership durable until detect_food_photo() completes and the meal status advances."
      - "Keep segment-stage ownership durable until segmentation and crop persistence complete and the meal status advances."
      - "Add detect/segment duplicate-worker regressions similar to the existing embedding/matching ownership tests."
  - truth: "The bounded grounding flow exits cleanly without leaving hanging meals in the live MATCHING/runtime path"
    status: failed
    reason: "When a MATCHING meal has no segment rows, poll_and_match_food_segments() transitions it to REASONING and continues, but no worker selects REASONING directly. The meal then relies on later janitor recovery instead of exiting cleanly."
    artifacts:
      - path: "bot/polling.py"
        issue: "The zero-segment branch at lines 855-857 sets MealProcessingStatus.REASONING and returns."
      - path: "bot/polling.py"
        issue: "No poller in bot/polling.py selects MealProcessingStatus.REASONING as an input state."
    missing:
      - "Fail or recover zero-segment MATCHING meals immediately instead of parking them in REASONING."
      - "Add a regression proving the zero-segment MATCHING path cannot strand a meal."
  - truth: "Packaged/restaurant grounding intent is preserved or rejected explicitly rather than coerced into HOME"
    status: failed
    reason: "The finalizer schemas still normalize unknown source_type values through normalize_source_type(), which converts them to HOME. build_grounding_prep() only triggers on PACKAGED or RESTAURANT, so malformed finalizer output can silently suppress required grounding."
    artifacts:
      - path: "app/services/interview_schema.py"
        issue: "ConfirmationItem and FinalizedGroupResult both call normalize_source_type() at lines 82-85 and 315-318."
      - path: "app/services/grounding_stub.py"
        issue: "normalize_source_type() coerces unknown values to HOME and build_grounding_prep() returns None for HOME at lines 9-20."
    missing:
      - "Make source_type validation strict for finalizer-facing schemas: reject unknown values instead of coercing them."
      - "Add explicit tests that invalid source_type values fail validation rather than becoming HOME."
---

# Phase 05: Agentic Grounding Verification Report

**Phase Goal:** The reasoning stage and post-interview re-grounding stage can invoke SearXNG and Firecrawl as tools when the LLM needs brand or restaurant nutrition data; every tool call is bounded, traced, and the loop cannot run away on cost.
**Verified:** 2026-06-05T02:01:44Z
**Status:** gaps_found
**Re-verification:** Yes — after prior gap closure work

**MVP Mode Note:** ROADMAP marks Phase 5 as `mvp`, but `gsd-sdk query user-story.validate` still reports the stored goal is not a valid `As a..., I want..., so that...` user story. Verification therefore uses the roadmap success criteria plus plan-frontmatter must-haves, as in the prior report.

## Goal Achievement

## User Flow Coverage

| Step | Expected | Evidence in codebase | Status |
| --- | --- | --- | --- |
| Reasoning-stage packaged/restaurant flow can invoke tools before save | Ready-to-write reasoning groups route through the shared bounded group finalizer instead of writing directly | `app/services/reasoning_service.py:2330-2427` builds finalizer inputs, calls `_run_group_finalizers()`, then saves through `apply_final_meal_resolution()` | ✓ VERIFIED |
| Post-interview packaged/restaurant flow can invoke tools and save through the same authoritative path | `finalize_confirmed_interview()` uses the same bounded finalizer loop and authoritative save transaction | `app/services/interview_service.py:1352-1410`, `1551-1705` | ✓ VERIFIED |
| Tool loop is bounded and degraded exits save best-effort with `is_verified=false` | Per-loop max calls, wall-clock timeout, remaining HTTP timeout, degraded-save audit state, and no-visual-learning guard exist | `app/services/grounding_service.py:23-62,113-165`; `app/services/interview_service.py:1387-1409,1674-1705`; targeted tests passed | ✓ VERIFIED |
| Per-meal cost cap and no-hang guarantees hold in the live runtime | No duplicate workers or stranded meals can bypass the hard cap | Embedding/matching are fixed, but detect/segment still release claims early and zero-segment MATCHING meals still strand into REASONING | ✗ FAILED |

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Reasoning-complete groups route through the shared bounded grounding finalizer before save | ✓ VERIFIED | `app/services/reasoning_service.py:2367-2427` uses `_build_group_finalizer_inputs()`, `_run_group_finalizers()`, and `apply_final_meal_resolution()`. |
| 2 | Post-interview finalization uses the same bounded grounding finalizer and single authoritative save path | ✓ VERIFIED | `app/services/interview_service.py:1352-1410` and `1551-1705` use the same grouped finalizer flow and save boundary. |
| 3 | Reasoning-model failure stays fail-closed even with a strong vector hit | ✓ VERIFIED | `run_reasoning_request()` preserves failed state through `_fallback_food_groups_from_match_results()` at `app/services/reasoning_service.py:1517-1545,2031-2041`; regression tests `tests/test_reasoning_flow.py:828-900` passed. |
| 4 | Per-loop bounds are implemented across model turns and Firecrawl HTTP calls | ✓ VERIFIED | `GroundingLoopState` enforces `MAX_TOOL_CALLS`, duplicate-call stop, and wall-clock timeout in `app/services/grounding_service.py:23-62`; HTTP timeout uses remaining loop time at `113-119`. |
| 5 | Firecrawl scrape is limited to URLs returned by prior search results in the same loop | ✓ VERIFIED | `GroundingService.scrape()` rejects non-allowlisted URLs at `app/services/grounding_service.py:145-152`; covered by `tests/test_grounding_service.py:99-165`. |
| 6 | Tool-call trace fields are appended to `MealSegment.ai_reasoning` and remain human-readable | ✓ VERIFIED | Live finalizer output persists `snippet_excerpts`, `provenance`, and `source_url`; verified by `tests/test_interview_flow.py:1477-1612`. |
| 7 | Degraded grounded outcomes commit best-effort with `is_verified=false` and do not learn visuals | ✓ VERIFIED | Degraded saves are emitted via `_degraded_group_finalizer_outcome()` and saved with `DEGRADED_SAVED`; visual learning remains disabled (`tests/test_interview_flow.py:1614-1703`). |
| 8 | Hard per-meal grounding/cost caps survive concurrent workers end-to-end | ✗ FAILED | `poll_and_detect_food()` commits before `detect_food_photo()` at `bot/polling.py:432-438`, and `poll_and_segment_food()` commits before `segment_food_photo_with_retry()` at `490-497`. |
| 9 | The live MATCHING/runtime path exits cleanly without hanging meals | ✗ FAILED | `poll_and_match_food_segments()` moves zero-segment meals to `REASONING` at `bot/polling.py:855-857`, but no worker selects `MealProcessingStatus.REASONING` directly. |
| 10 | Finalizer source typing preserves or explicitly rejects packaged/restaurant identity instead of coercing it to HOME | ✗ FAILED | `app/services/interview_schema.py:82-85,315-318` calls `normalize_source_type()`, and `app/services/grounding_stub.py:9-20` converts unknown values to `HOME`; a probe showed invalid `source_type=\"takeout?\"` becomes `HOME`. |

**Score:** 7/10 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `app/services/reasoning_service.py` | Reasoning-stage handoff into shared bounded finalizer without fail-open fallback | ✓ VERIFIED | Shared finalizer path is wired; previous fail-open fallback gap is closed. |
| `app/services/interview_service.py` | Shared bounded grounding finalizer, degraded-save routing, trace merge, and authoritative save handoff | ✓ VERIFIED | Inline grouped finalization, degraded-save audit state, and authoritative save path are present. |
| `app/services/grounding_service.py` | App-owned search/scrape loop budget, duplicate-call tracking, allowlist, and remaining-time HTTP timeout | ✓ VERIFIED | Core loop budget and allowlist behavior are implemented and tested. |
| `app/services/interview_schema.py` | Strict finalizer-facing schema for source/portion/trace fields | ⚠ PARTIAL | Portion bucket is strict, but unknown `source_type` values still coerce to `HOME`. |
| `app/services/meal_resolution_service.py` | Singular authoritative persistence of grounded provenance, quantities, verification state, and visual-learning guard | ✓ VERIFIED | Final save path persists grounded outputs and only learns visuals for verified foods. |
| `app/services/matching_service.py` | Verified-only similarity corpus and candidate snapshot persistence | ✓ VERIFIED | Query filters to `FoodItem.is_verified`; candidate snapshots persist, though not all provenance metadata is preserved. |
| `bot/polling.py` | Live runtime wiring with durable ownership and no stranded Phase 05 paths | ⚠ PARTIAL | Embedding/matching ownership is durable now, but detect/segment ownership is not and zero-segment MATCHING still strands to REASONING. |
| `tests/test_reasoning_flow.py` | Regression coverage for fail-closed reasoning fallback and reasoning-stage finalizer routing | ✓ VERIFIED | Strong-vector failed-reasoning regressions exist and passed. |
| `tests/test_match_flow.py` | Regression coverage for durable EMBEDDING ownership and authoritative grounded save behavior | ✓ VERIFIED | Single-owner EMBEDDING regression exists and passed. |
| `tests/test_bot_contract.py` | Runtime-level regression coverage for durable MATCHING ownership and no duplicate completion side effects | ✓ VERIFIED | Single-owner MATCHING regression exists and passed. |
| `tests/test_interview_flow.py` | Inline grounding trace and degraded-save coverage | ✓ VERIFIED | Trace persistence and degraded-save behaviors are covered and passed. |
| `tests/test_grounding_service.py` | Allowlist, timeout, cap, and duplicate-call coverage | ✓ VERIFIED | Grounding service contract tests passed. |

### Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| `app/services/reasoning_service.py` | `app/services/interview_service.py` | Ready-to-write reasoning groups use the shared bounded group finalizer | ✓ WIRED | `finalize_meal_from_reasoning()` calls `_run_group_finalizers()` at `app/services/reasoning_service.py:2370-2389`. |
| `app/services/interview_service.py` | `app/services/grounding_service.py` | Bounded loop passes remaining budget into `search()` / `scrape()` | ✓ WIRED | `_bounded_group_finalizer_response()` and `GroundingService._request_timeout_s()` cooperate on remaining-time budgets. |
| `app/services/interview_service.py` | `app/services/meal_resolution_service.py` | Finalized/degraded group resolutions flow through the unchanged authoritative save transaction | ✓ WIRED | `finalize_confirmed_interview()` and `finalize_meal_from_reasoning()` both call `apply_final_meal_resolution()`. |
| `app/services/grounding_service.py` | Firecrawl HTTP calls | Loop budget -> per-request timeout | ✓ WIRED | `timeout=self._request_timeout_s(loop_state=loop_state)` in `search()` and `scrape()`. |
| `app/services/interview_schema.py` | `app/services/grounding_stub.py` | Finalizer `source_type` drives `build_grounding_prep()` eligibility | ✗ NOT_WIRED | Unknown `source_type` values are normalized to `HOME`, so malformed packaged/restaurant output can silently skip grounding. |
| `bot/polling.py` | Slow detect/segment stage work | `skip_locked` claim remains durable until stage completion | ✗ NOT_WIRED | Detect and segment release the claim before the expensive call starts. |
| `bot/polling.py` | Live consumer for `MealProcessingStatus.REASONING` | Zero-segment MATCHING edge case still exits cleanly | ✗ NOT_WIRED | No worker selects `REASONING`; the zero-segment branch parks the meal there. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| --- | --- | --- | --- | --- |
| `app/services/reasoning_service.py` | `final_segments` for reasoning-complete groups | grouped reasoning output -> `_build_group_finalizer_inputs()` -> `_run_group_finalizers()` -> `apply_final_meal_resolution()` | Yes | ✓ FLOWING |
| `app/services/interview_service.py` | grounded nutrition, provenance, and trace fields | finalizer JSON -> `FinalizedGroupResult` -> `final_resolution_from_confirmation()` -> authoritative save | Yes | ✓ FLOWING |
| `app/services/grounding_service.py` | allowlisted URLs and remaining timeout | loop state -> `search()` / `scrape()` | Yes | ✓ FLOWING |
| `bot/polling.py` | stage ownership for slow detect/segment work | `FOR UPDATE SKIP LOCKED` row claim | No durable claim survives the early commit | ✗ DISCONNECTED |
| `app/services/interview_schema.py` | finalizer `source_type` -> grounding eligibility | `normalize_source_type()` -> `build_grounding_prep()` | No; invalid values become `HOME`, which suppresses grounding | ✗ HOLLOW |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| Phase 05 regression slice for fail-closed reasoning and durable EMBEDDING/MATCHING ownership | `rtk docker run --rm -v "$PWD":/app -w /app mealttracker-plan05-test python -m unittest tests.test_reasoning_flow tests.test_match_flow tests.test_bot_contract -q` | Passed, `113` tests | ✓ PASS |
| Grounding contract + interview trace/degraded-save slice | `rtk docker run --rm -v "$PWD":/app -w /app mealttracker-plan05-test python -m unittest tests.test_reasoning_contract tests.test_grounding_service tests.test_interview_flow -q` | Passed, `74` tests | ✓ PASS |
| Invalid finalizer source type is rejected instead of coerced | `rtk docker run --rm -v "$PWD":/app -w /app mealttracker-plan05-test python -c '...'` | Output: `{\"confirmation_source_type\": \"HOME\", \"final_source_type\": \"HOME\"}` for input `source_type=\"takeout?\"` | ✗ FAIL |

### Probe Execution

| Probe | Command | Result | Status |
| --- | --- | --- | --- |
| Conventional phase probes | `find scripts -path '*/tests/probe-*.sh' -type f` | No Phase 05 `probe-*.sh` scripts found and no plan declared one | ? SKIP |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| `GROUND-01` | 05-01, 05-02, 05-03, 05-04, 05-05, 05-06 | Reasoning and post-interview stages can call search/fetch tools when brand/restaurant nutrition needs grounding | ✗ BLOCKED | Positive tool paths exist, but invalid finalizer `source_type` still coerces to `HOME`, which can suppress required packaged/restaurant grounding. |
| `GROUND-02` | 05-01, 05-02, 05-03, 05-04, 05-05, 05-06 | Tool loop is bounded: max iterations, wall-clock timeout, per-meal cost cap, URL allowlist | ✗ BLOCKED | Per-loop cap/timeout/allowlist are implemented, but detect/segment ownership is still not durable end-to-end and zero-segment MATCHING meals can hang. |
| `GROUND-03` | 05-01, 05-02, 05-03, 05-04, 05-05 | Tool-call trace (queries, URLs, snippets) is appended to `MealSegment.ai_reasoning` | ✓ SATISFIED | Live trace persistence is covered by `tests/test_interview_flow.py:1477-1612` and present in the finalizer code path. |
| `REASON-04` | 05-01 | Reasoning trace is written to `MealSegment.ai_reasoning` for audit | ✓ SATISFIED | Phase 05 appends grounding trace into the existing reasoning audit structure rather than replacing it. |
| `INTERVIEW-03` | 05-01, 05-02 | Interview answers trigger re-grounding with tools to populate nutrition | ✓ SATISFIED | `finalize_confirmed_interview()` uses the shared bounded grounded finalizer and populates nutrition/provenance fields. |
| `INTERVIEW-04` | 05-02 | If post-interview confidence stays low, commit best-effort with `is_verified=false` | ✓ SATISFIED | Degraded-save path persists `INTERVIEW_BEST_EFFORT`, `is_verified=false`, and disables visual learning. |
| `MATCH-04` | 05-02, 05-03 | Confirmed identifications create `FoodVisual` rows so the visual vocabulary grows | ✓ SATISFIED | Verified outcomes still create visuals through `apply_final_meal_resolution()`; degraded/unverified saves are blocked. |

**Orphaned requirements:** None found. All requirement IDs declared in Phase 05 plan frontmatter were accounted for above.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| `bot/polling.py` | 433 | Detect worker commits before `detect_food_photo()` | 🛑 BLOCKER | A second worker can reacquire the same meal before detect finishes, undermining end-to-end per-meal cap guarantees. |
| `bot/polling.py` | 490 | Segment worker commits before `segment_food_photo_with_retry()` | 🛑 BLOCKER | A second worker can duplicate segmentation/crop creation and later duplicate downstream grounding work. |
| `bot/polling.py` | 856 | Zero-segment MATCHING branch parks the meal in `REASONING` | 🛑 BLOCKER | No live worker consumes `REASONING` directly, so the meal hangs until janitor recovery instead of exiting cleanly. |
| `app/services/interview_schema.py` | 82 | Finalizer-facing `source_type` validation normalizes through `normalize_source_type()` | 🛑 BLOCKER | Malformed packaged/restaurant output can be rewritten to `HOME` instead of failing. |
| `app/services/interview_schema.py` | 315 | `FinalizedGroupResult.source_type` repeats the same coercion | 🛑 BLOCKER | The live grounded finalizer can silently suppress required grounding. |
| `app/services/matching_service.py` | 66 | Candidate snapshots omit `source_type`, `brand_name`, and `restaurant_name` that downstream code attempts to read | ⚠ WARNING | Production snapshots are thinner than several downstream reuse paths assume; this is still a provenance/identity robustness risk. |
| `bot/polling.py` | 446 | Detect-stage exceptions are only logged, not failed closed immediately | ⚠ WARNING | Meals can linger in `DETECTING` until janitor recovery rather than failing immediately. |

### Gaps Summary

Phase 05 is not complete. The prior verification gaps are genuinely closed: failed reasoning no longer auto-confirms from raw vector hits, and the Phase 05-owned EMBEDDING/MATCHING workers now keep single-owner claims while slow work is in flight. The shared bounded grounding finalizer, degraded-save path, allowlist enforcement, remaining-time HTTP timeout propagation, and live trace persistence are all present and backed by passing targeted tests.

The phase still misses three goal-level truths in the live runtime. First, the hard per-meal cap is not true end-to-end because DETECTING and SEGMENTING still release their row claim before the expensive stage call. Second, the MATCHING zero-segment branch still parks meals in `REASONING` with no live consumer, which violates the “no hanging meals” promise and depends on janitor recovery instead of a clean exit. Third, finalizer-facing `source_type` validation still coerces unknown values to `HOME`; because `build_grounding_prep()` only grounds PACKAGED or RESTAURANT flows, malformed finalizer output can silently suppress required grounding.

I did not count review finding CR-01 as a verification gap. The review recommended fail-closed behavior for grounded finalizer failures, but the Phase 05 roadmap contract explicitly requires the opposite: bounded loop exit with best-effort commit and `is_verified=false`. The current degraded-save behavior matches the phase contract.

---

_Verified: 2026-06-05T02:01:44Z_
_Verifier: the agent (gsd-verifier)_
