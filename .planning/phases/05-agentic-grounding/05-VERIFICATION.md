---
phase: 05-agentic-grounding
verified: 2026-06-04T09:45:42Z
status: gaps_found
score: 5/10 must-haves verified
overrides_applied: 0
gaps:
  - truth: "Reasoning-stage grounding exists alongside post-interview inline grounding for branded or restaurant meals"
    status: failed
    reason: "The live reasoning path never exposes grounding tools; only the inline post-interview finalizer can call tools."
    artifacts:
      - path: "app/services/reasoning_service.py"
        issue: "Reasoning calls `chat_completion()` with `response_format` only and no `tools` or `tool_choice`."
      - path: "app/services/interview_service.py"
        issue: "Tool loop exists only in `_bounded_group_finalizer_response()`."
    missing:
      - "Add a tool-capable reasoning-stage path for branded/restaurant nutrition lookups, or record an approved override narrowing Phase 5 to post-interview grounding only."
  - truth: "The grounding loop is hard-bounded by 90-second wall-clock and configured caps"
    status: failed
    reason: "Max tool calls are enforced, but HTTP search/scrape still use fixed per-call timeouts and can overrun the remaining wall-clock budget."
    artifacts:
      - path: "app/services/interview_service.py"
        issue: "`_tool_timeout_s()` applies only to model calls before tool execution."
      - path: "app/services/grounding_service.py"
        issue: "`search()` and `scrape()` always use `self.tool_timeout_s` instead of the loop's remaining budget."
    missing:
      - "Thread remaining wall-clock budget into `GroundingService.search()` and `GroundingService.scrape()`."
      - "Enforce the documented cost/call-cap policy at the same level as the wall-clock bound."
  - truth: "MealSegment.ai_reasoning stores a complete, auditable grounding trace with query, URL, and snippet/provenance evidence"
    status: failed
    reason: "The saved trace is append-only and human-readable, but the live schema only stores queries/URLs/stop metadata; snippet excerpts and persisted provenance/source URLs are absent."
    artifacts:
      - path: "app/services/interview_schema.py"
        issue: "`GroundingTracePayload` has no snippet fields, and `FinalizedGroupResult` has no provenance/source-url fields."
      - path: "app/services/interview_service.py"
        issue: "Trace formatting writes queries and fetched URLs only."
      - path: "app/services/reasoning_schema.py"
        issue: "A provenance-bearing grounding schema exists but is not used by the live finalizer."
    missing:
      - "Persist snippet excerpts in `grounding_trace`."
      - "Carry provenance/source URL fields through the live finalizer schema and save path."
  - truth: "Grounding failure paths are safe to ship and do not corrupt future learning or trust untrusted tool output"
    status: failed
    reason: "Best-effort/unverified saves can still create `FoodVisual` rows, matching does not filter verified food items, and raw tool output is fed back to the model without prompt-injection hardening."
    artifacts:
      - path: "app/services/interview_service.py"
        issue: "Best-effort resolutions still set `create_food_visual` when visual inputs exist; tool payloads are re-injected as raw JSON."
      - path: "app/services/meal_resolution_service.py"
        issue: "Any `create_food_visual` resolution with an embedding persists a `FoodVisual`."
      - path: "app/services/matching_service.py"
        issue: "Matcher filters only `FoodVisual.is_invalidated`, not `FoodItem.is_verified`."
    missing:
      - "Disable visual learning for degraded/unverified saves and filter match corpus to verified food items."
      - "Treat tool output as untrusted evidence and harden the finalizer prompt/tool payload handling against prompt injection."
  - truth: "Legacy grounding handoff/runtime wiring is fully cleaned up"
    status: partial
    reason: "The active runtime no longer schedules grounding workers, but orphaned polling functions still exist and reference the deleted `build_grounding_reasoning_state()` API."
    artifacts:
      - path: "bot/main.py"
        issue: "Active startup no longer schedules grounding workers."
      - path: "bot/polling.py"
        issue: "Legacy `GROUNDING_PENDING` workers remain and call a missing interview-service helper."
    missing:
      - "Delete the dead polling helpers or restore a coherent legacy API surface; the current code is broken if those entry points are invoked."
---

# Phase 05: Agentic Grounding Verification Report

**Phase Goal:** The reasoning stage and post-interview re-grounding stage can invoke SearXNG and Firecrawl as tools when the LLM needs brand or restaurant nutrition data; every tool call is bounded, traced, and the loop cannot run away on cost.
**Verified:** 2026-06-04T09:45:42Z
**Status:** gaps_found
**Re-verification:** No — initial verification

**MVP Mode Note:** ROADMAP marks Phase 5 as `mvp`, but the stored phase goal is not a valid user story (`gsd-sdk query user-story.validate` returned `valid=false`). Coverage below falls back to the explicit Phase 5 success criteria plus plan frontmatter must-haves.

## Goal Achievement

## User Flow Coverage

| Step | Expected | Evidence in codebase | Status |
| --- | --- | --- | --- |
| Branded/restaurant meal can trigger grounding during reasoning or post-interview | Both stages can invoke tools when needed | Post-interview inline finalizer exposes `firecrawl_search` / `firecrawl_scrape` in [app/services/interview_service.py](/Users/mali/Documents/Projects/MealTracker/app/services/interview_service.py:269); reasoning stage never passes tools in [app/services/reasoning_service.py](/Users/mali/Documents/Projects/MealTracker/app/services/reasoning_service.py:1907) | ✗ FAILED |
| Bounded loop exits cleanly and saves best-effort unverified output | Max calls / wall-clock / cap all enforced, with `is_verified=false` degradation | Max-call degradation exists and is tested; HTTP tools still use fixed timeouts in [app/services/grounding_service.py](/Users/mali/Documents/Projects/MealTracker/app/services/grounding_service.py:118) | ✗ FAILED |
| Fabricated scrape URLs are rejected | Only URLs returned by prior search in the same loop are scrape-eligible | Allowlist enforced in [app/services/grounding_service.py](/Users/mali/Documents/Projects/MealTracker/app/services/grounding_service.py:138); targeted tests passed | ✓ VERIFIED |
| Full human-readable tool trace is appended | Queries, URLs, snippet excerpts, iteration count are preserved in `MealSegment.ai_reasoning` | Queries/URLs/iteration metadata append in [app/services/interview_service.py](/Users/mali/Documents/Projects/MealTracker/app/services/interview_service.py:416), but snippet fields do not exist in [app/services/interview_schema.py](/Users/mali/Documents/Projects/MealTracker/app/services/interview_schema.py:177) | ✗ FAILED |

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Reasoning-stage grounding exists for branded/restaurant meals | ✗ FAILED | [app/services/reasoning_service.py](/Users/mali/Documents/Projects/MealTracker/app/services/reasoning_service.py:1907) sends no `tools` or `tool_choice`; only the post-interview finalizer does. |
| 2 | Post-interview inline grounding uses tools and flows directly into the authoritative save path | ✓ VERIFIED | `_bounded_group_finalizer_response()` calls tools in [app/services/interview_service.py](/Users/mali/Documents/Projects/MealTracker/app/services/interview_service.py:269), and `finalize_confirmed_interview()` writes through `apply_final_meal_resolution()` at [app/services/interview_service.py](/Users/mali/Documents/Projects/MealTracker/app/services/interview_service.py:1262). |
| 3 | Max-call bounded degradation exists and commits `is_verified=false` best-effort output | ✓ VERIFIED | Degraded finalizer outcomes route to `INTERVIEW_BEST_EFFORT` in [app/services/interview_service.py](/Users/mali/Documents/Projects/MealTracker/app/services/interview_service.py:1574) and targeted tests passed. |
| 4 | The 90-second wall-clock bound applies across both model turns and HTTP tool executions | ✗ FAILED | Model calls use remaining-time budgets in [app/services/interview_service.py](/Users/mali/Documents/Projects/MealTracker/app/services/interview_service.py:278), but `search()` / `scrape()` ignore remaining loop time in [app/services/grounding_service.py](/Users/mali/Documents/Projects/MealTracker/app/services/grounding_service.py:118). |
| 5 | URL allowlist enforcement works per grounding loop | ✓ VERIFIED | Search results populate `_allowed_urls`, and `scrape()` rejects non-allowlisted URLs in [app/services/grounding_service.py](/Users/mali/Documents/Projects/MealTracker/app/services/grounding_service.py:138). |
| 6 | `MealSegment.ai_reasoning` append is human-readable and preserves prior reasoning metadata | ✓ VERIFIED | Existing reasoning is merged and `grounding_trace_text` / `final_reasoning` are appended in [app/services/interview_service.py](/Users/mali/Documents/Projects/MealTracker/app/services/interview_service.py:416). |
| 7 | The appended trace includes snippet excerpts, not just query/URL metadata | ✗ FAILED | `GroundingTracePayload` supports only `queries`, `fetched_urls`, and stop/failure counters in [app/services/interview_schema.py](/Users/mali/Documents/Projects/MealTracker/app/services/interview_schema.py:177). |
| 8 | The live finalizer contract persists provenance/source URL for grounded nutrition facts | ✗ FAILED | The live parser uses `FinalizedGroupResult` / `group_finalizer_response_format()` in [app/services/interview_schema.py](/Users/mali/Documents/Projects/MealTracker/app/services/interview_schema.py:216), which lacks provenance/source-url fields; the provenance-bearing schema in [app/services/reasoning_schema.py](/Users/mali/Documents/Projects/MealTracker/app/services/reasoning_schema.py:183) is unused. |
| 9 | Official Firecrawl `/search` backed by SearXNG JSON is the runtime default and works locally | ✓ VERIFIED | Compose wires `SEARXNG_ENDPOINT` in [docker-compose.yml](/Users/mali/Documents/Projects/MealTracker/docker-compose.yml:103), SearXNG enables JSON in [searxng/settings.yml](/Users/mali/Documents/Projects/MealTracker/searxng/settings.yml:7), and live `curl` spot-checks returned search and scrape data. |
| 10 | Quantity persistence cleanup landed in the authoritative save path | ✓ VERIFIED | `MealSegment` now stores `quantity_json` / `quantity_display` in [app/models/meal_segment.py](/Users/mali/Documents/Projects/MealTracker/app/models/meal_segment.py:36), and the migration removes `meal_segments.portion_bucket` in [migrations/versions/phase5_grounding_quantity.py](/Users/mali/Documents/Projects/MealTracker/migrations/versions/phase5_grounding_quantity.py:31). |
| 11 | Failure paths are safe for future matching and learning | ✗ FAILED | Best-effort resolutions still set `create_food_visual` in [app/services/interview_service.py](/Users/mali/Documents/Projects/MealTracker/app/services/interview_service.py:1207), `FoodVisual` rows are still written in [app/services/meal_resolution_service.py](/Users/mali/Documents/Projects/MealTracker/app/services/meal_resolution_service.py:545), and matcher queries do not filter verified food items in [app/services/matching_service.py](/Users/mali/Documents/Projects/MealTracker/app/services/matching_service.py:136). |
| 12 | Tool output is treated as untrusted evidence and the legacy handoff runtime is fully cleaned up | ✗ FAILED | Raw tool payloads are fed back as JSON in [app/services/interview_service.py](/Users/mali/Documents/Projects/MealTracker/app/services/interview_service.py:194) without any untrusted-content rule in the finalizer system prompt at [app/services/interview_service.py](/Users/mali/Documents/Projects/MealTracker/app/services/interview_service.py:1665); dead `GROUNDING_PENDING` workers remain in [bot/polling.py](/Users/mali/Documents/Projects/MealTracker/bot/polling.py:852). |

**Score:** 5/10 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `app/services/grounding_service.py` | App-owned Firecrawl search/scrape client, allowlist, bounded-loop primitives | ⚠ PARTIAL | Exists and is wired, but tool HTTP timeouts ignore remaining wall-clock budget. |
| `app/config.py` | Grounding endpoints, models, limits, fallback knobs | ✓ VERIFIED | Phase 5 runtime settings are present and validated. |
| `app/services/reasoning_schema.py` | Provenance-aware grounding schema and stop reasons | ⚠ ORPHANED | `grounding_result_response_format()` is strict and provenance-aware, but the live finalizer never uses it. |
| `app/services/reasoning_service.py` | Reasoning-stage grounding/tool invocation | ✗ FAILED | No tool-enabled reasoning path exists. |
| `app/services/interview_schema.py` | Live finalizer schema with persisted grounding metadata | ✗ FAILED | Live schema omits snippet/provenance/source-url fields. |
| `app/services/interview_service.py` | Inline grounding orchestration and append-only trace merge | ⚠ PARTIAL | Inline path works, but raw tool output is trusted and degraded saves can still learn visuals. |
| `app/services/meal_resolution_service.py` | Singular authoritative write path | ⚠ PARTIAL | Save path is singular, but it persists `FoodVisual` rows for degraded/unverified outcomes when asked. |
| `docker-compose.yml` | Official Firecrawl + SearXNG runtime wiring | ✓ VERIFIED | Live compose stack is up and health checks passed. |
| `searxng/settings.yml` | JSON-enabled SearXNG backend for Firecrawl search | ✓ VERIFIED | JSON output is explicitly enabled. |
| `migrations/versions/phase5_grounding_quantity.py` | Quantity-model cleanup aligned to current persistence | ✓ VERIFIED | `meal_segments.portion_bucket` is removed and replaced by quantity JSON/display fields. |

### Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| `app/services/reasoning_service.py` | `app/services/llm_client.py` | reasoning-stage tool invocation | ✗ NOT_WIRED | Reasoning uses `chat_completion()` without tools. |
| `app/services/interview_service.py` | `app/services/grounding_service.py` | inline `firecrawl_search` / `firecrawl_scrape` loop | ✓ WIRED | Tool loop calls `GroundingService.search()` and `.scrape()`. |
| `app/services/interview_service.py` | `app/services/meal_resolution_service.py` | final grounded resolutions -> `apply_final_meal_resolution()` | ✓ WIRED | Active finalizer writes through the single save boundary. |
| `GroundingLoopState` allowlist | `GroundingService.scrape()` | prior-search URL gating | ✓ WIRED | `scrape()` rejects non-allowlisted URLs before HTTP execution. |
| Remaining loop budget | `GroundingService.search()` / `.scrape()` | wall-clock enforcement | ✗ PARTIAL | Remaining time is computed, but not propagated into HTTP tool timeouts. |
| `bot/main.py` | `bot/polling.py` | retirement of `GROUNDING_PENDING` workers | ⚠ PARTIAL | Active startup no longer schedules them, but dead worker code still exists and is broken. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| --- | --- | --- | --- | --- |
| `app/services/interview_service.py` | grounded nutrition fields (`serving_size_g`, `calories`, macros) | Finalizer JSON -> `final_resolution_from_confirmation()` -> `resolve_or_create_food_item()` | Yes | ✓ FLOWING |
| `app/services/interview_service.py` | `grounding_trace` | Tool loop trace -> `segment_ai_reasoning` -> `MealSegment.ai_reasoning` | Partial only: queries/URLs/stop metadata | ⚠ PARTIAL |
| `app/services/grounding_service.py` | `_allowed_urls` | Search result URLs from the same loop | Yes | ✓ FLOWING |
| `app/services/reasoning_service.py` | reasoning-stage grounding/tool state | None | No tool source exists | ✗ DISCONNECTED |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| Phase 5 targeted regression suites | `docker run --rm -v "$PWD":/app -w /app mealttracker-plan05-test python -m unittest tests.test_reasoning_contract tests.test_reasoning_flow tests.test_grounding_service tests.test_interview_flow tests.test_match_flow tests.test_bot_contract -q` | `Ran 175 tests ... OK` | ✓ PASS |
| API health | `curl -sS http://127.0.0.1:18000/health` | `{"status":"ok"}` | ✓ PASS |
| Firecrawl search via live compose network | `docker compose exec -T api ... POST http://firecrawl-api:3002/v1/search` | HTTP 200 with `success:true` and result for `shawarma` | ✓ PASS |
| Firecrawl scrape via live compose network | `docker compose exec -T api ... POST http://firecrawl-api:3002/v1/scrape` | HTTP 200 with markdown payload for `https://en.wikipedia.org/wiki/Shawarma` | ✓ PASS |
| Sequential scrape stability | `docker compose exec -T api ... 5 sequential scrape calls` | `5/5` successful | ✓ PASS |

### Probe Execution

| Probe | Command | Result | Status |
| --- | --- | --- | --- |
| Conventional phase probe scripts | `find scripts -path '*/tests/probe-*.sh' -type f` | No Phase 5 probe scripts found; none declared in Phase 5 plans/summaries | ? SKIP |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| `GROUND-01` | 05-01, 05-02, 05-03 | Reasoning and post-interview stages can call search/fetch tools for branded or restaurant nutrition data | ✗ BLOCKED | Post-interview inline tools exist, but the reasoning stage has no tool path. |
| `GROUND-02` | 05-01, 05-02, 05-03 | Tool loop bounded by max iterations, wall-clock timeout, cost/call caps, URL allowlist | ✗ BLOCKED | Max-call and allowlist logic exist; wall-clock bound is not enforced across tool HTTP calls, and only a call-cap proxy exists. |
| `GROUND-03` | 05-01, 05-02, 05-03 | Tool-call trace (queries, URLs, snippets) is appended to `MealSegment.ai_reasoning` | ✗ BLOCKED | Queries/URLs append, but snippet excerpts are absent from the live trace schema. |
| `REASON-04` | 05-01 | Reasoning trace is written to `MealSegment.ai_reasoning` for audit | ✓ SATISFIED | Reasoning writes `segment.ai_reasoning` in [app/services/reasoning_service.py](/Users/mali/Documents/Projects/MealTracker/app/services/reasoning_service.py:2041), and Phase 5 append logic preserves it. |
| `INTERVIEW-03` | 05-01, 05-02 | Interview answers run a re-grounding pass with tools to populate nutrition | ✓ SATISFIED | Inline finalizer grounding replaces the old handoff path and writes nutrition through the final save path. |
| `INTERVIEW-04` | 05-02 | If post-interview confidence stays low, commit best-effort with `is_verified=false` | ✓ SATISFIED | Degraded group outcomes route to best-effort saves and tests passed. |
| `MATCH-04` | 05-02, 05-03 | On confirmed identification a `FoodVisual` row is written so the visual vocabulary grows | ✗ BLOCKED | Confirmed saves still learn visuals, but degraded/unverified saves can also write `FoodVisual` rows, contaminating the corpus. |

**Orphaned requirements:** None found for Phase 5 in `.planning/REQUIREMENTS.md`.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| `app/services/reasoning_service.py` | 1907 | Reasoning stage has no tool path | 🛑 BLOCKER | `GROUND-01` is only half-implemented. |
| `app/services/grounding_service.py` | 118 | Fixed HTTP timeout in `search()` | ⚠ WARNING | Loop can overrun the documented 90-second wall-clock bound. |
| `app/services/interview_schema.py` | 177 | Trace schema omits snippet/provenance fields | 🛑 BLOCKER | `GROUND-03` contract is not fully persisted. |
| `app/services/interview_service.py` | 194 | Raw tool payloads fed back to model as trusted content | 🛑 BLOCKER | Tool-output prompt injection remains possible. |
| `app/services/interview_service.py` | 1207 | Best-effort path can still request visual learning | 🛑 BLOCKER | Unverified results can poison future matching. |
| `app/services/matching_service.py` | 136 | Match corpus ignores `FoodItem.is_verified` | 🛑 BLOCKER | Unverified visuals remain eligible future candidates. |
| `bot/polling.py` | 852 | Dead grounding workers remain and call a deleted API | ⚠ WARNING | Runtime cleanup is incomplete; legacy entry points are broken. |

### Gaps Summary

Phase 5 is not goal-complete. The compose/runtime stack is genuinely wired: the local stack is up, health checks pass, Firecrawl `/search` works against SearXNG, scrape works, sequential scrape stability passed, inline post-interview grounding exists, and quantity persistence cleanup landed.

The blockers are in the contract itself, not file existence. The roadmap requires both reasoning-stage and post-interview grounding, but only the post-interview inline finalizer can call tools. The documented hard wall-clock bound is incomplete because tool HTTP calls ignore remaining loop time. The trace appended to `MealSegment.ai_reasoning` is readable, but it omits snippet excerpts, and the live finalizer schema still drops provenance/source URL fields even though a stricter provenance-aware schema exists elsewhere. On top of that, degraded/unverified saves can still enter the visual corpus, raw scraped content is re-fed to the model without prompt-injection hardening, and dead `GROUNDING_PENDING` workers remain in `bot/polling.py`.

These are codebase-observable gaps, not summary discrepancies. Phase 5 should not be treated as achieved until the blocking gaps above are closed or explicitly overridden.

---

_Verified: 2026-06-04T09:45:42Z_  
_Verifier: the agent (gsd-verifier)_
