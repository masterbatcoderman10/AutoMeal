---
status: planned
phase: 05-agentic-grounding
source:
  - 05-01-SUMMARY.md
  - 05-02-SUMMARY.md
  - 05-03-SUMMARY.md
  - 05-04-SUMMARY.md
  - 05-05-SUMMARY.md
  - 05-06-SUMMARY.md
  - 05-07-SUMMARY.md
  - 05-08-SUMMARY.md
  - 05-09-SUMMARY.md
  - 05-10-SUMMARY.md
  - 05-11-PLAN.md
started: 2026-06-06T11:57:55Z
updated: 2026-06-06T14:55:15Z
---

## Current Test

[testing complete]

## Tests

### 1. Automated 05 Regression Gate
expected: The targeted Phase 05 regression slices stay green on the current checkout before live verification begins.
result: pass
reported: "Containerized Phase 05 slices passed cleanly on the current checkout: `tests.test_bot_contract tests.test_match_flow` (101 tests), `tests.test_interview_schema tests.test_interview_flow` (71 tests), and the full Phase 05 target suite (197 tests)."

### 2. Clean Deploy And Grounding Stack Boot
expected: A clean-state redeploy should rebuild the stack from scratch, run migrations on an empty database, bring `api` and `bot` up cleanly, and keep the real SearXNG plus Firecrawl grounding services reachable from inside the compose network.
result: pass
reported: "Ran `docker compose down -v` and `docker compose up -d --build`, confirmed Postgres tables were empty, verified `GET /health -> {\"status\":\"ok\"}` from the API container, and proved live in-network search responses from both SearXNG JSON search and Firecrawl `/v1/search`."

### 3. Clean Blank-State Meal Reaches Interview And Confirmation
expected: On a blank database, a live meal upload should progress through detect, segment, embed, match, and reasoning without hanging, then enter the interview flow and build a confirmation state that preserves the Phase 05 source and finalizer path.
result: pass
reported: "Uploaded `sample_images/IMG_4583.HEIC` through `/ingest/photo` as meal `7d8d099b-3bd7-4ee4-a6fa-20636903886d`. The meal advanced through `SEGMENTING -> EMBEDDING -> MATCHING -> REASONING -> INTERVIEWING`, created 3 meal segments, recorded 18 interview messages, captured packaged-brand clarification for flatbread (`Al Khayam`), and reached `CONFIRMATION` with three confirmation items."

### 4. Final Confirmation Produces Verified Save-Ready Nutrition
expected: After clarification reaches confirmation, inline finalization should either ground and save usable verified nutrition for each group or fail in a way that does not persist a completed meal with empty nutrition.
result: issue
reported: "Meal `7d8d099b-3bd7-4ee4-a6fa-20636903886d` ended `COMPLETED`, but all 3 saved diary rows point to unverified `FoodItem` records with null calories and macros. `meal_logs.reasoning_state_json.finalizer_groups[*]` is `DEGRADED` for every group, `grounding_status` is `DEGRADED_SAVED`, and the packaged flatbread group (`Al Khayam` / `PACKAGED`) still recorded no fetched URLs in the persisted trace. A direct live replay of the group-3 finalizer showed only one search query, no scrape call, and a partial JSON response that omitted `serving_size_g`, `fiber_g`, `is_verified`, and proper trace fields while stuffing provenance notes into `source_url`."
severity: blocker

## Summary

total: 4
passed: 3
issues: 1
pending: 0
skipped: 0
blocked: 0

## Follow-up Trace Evidence

- observed: "After promoting `FINALIZER_MODEL` to `google/gemini-3-flash-preview` and removing the old 4096-token cap, live meal `bb61dd46-5e86-46c4-ae39-d97af6a86b55` still ended `COMPLETED` with all groups degraded and nutrition-empty diary rows."
  langfuse:
    - "Observation `f362fd681067499f7c8edfed9771e390`: model output count was 65,528 tokens and repeated `333333...` inside model-authored `grounding_trace.tool_calls_used`; the input did not contain that repeated digit pattern."
    - "Observation `262ff6796ff601fec143c92d739d140f`: model output count was 65,528 tokens and repeated provenance narrative inside `source_url` until truncation."
    - "Observations `3f7dd041fbac2a131e511763715eb414`, `78e2e3348a34d800ccfe8d59937a8c9b`, and `963114ccc9b175fba205bcc3be764feb`: model outputs contained complete nutrition but omitted `is_verified`, `provenance`, and trace fields, so the service rejected them and degraded the groups."
  conclusion: "The repeated-number traces are best explained by model/provider output degeneration under an unbounded operational schema, not by prompt injection. The state mis-sync comes from making the model author deterministic service fields and then discarding otherwise useful nutrition when those fields are absent."
  planned_closure: "05-11-PLAN.md"

## Gaps

- truth: "Inline confirmation must not persist a completed meal whose saved foods all remain unverified and nutrition-empty after finalizer failure."
  status: failed
  reason: "Live clean-state meal `7d8d099b-3bd7-4ee4-a6fa-20636903886d` completed with 3 diary rows whose linked `food_items` all had `is_verified=false` and null nutrition fields, while `reasoning_state_json.grounding_status` was `DEGRADED_SAVED`."
  severity: blocker
  test: 4
  root_cause: "The Phase 05 success validation now rejects malformed finalizer output, but `_degraded_group_finalizer_outcome()` still converts each failed group into a best-effort resolution and `finalize_confirmed_interview()` still calls `apply_final_meal_resolution(..., meal_status=MealProcessingStatus.COMPLETED)` even when every group degraded. That keeps the older user-facing regression alive through the degraded-save path instead of the old false-success path."
  artifacts:
    - path: "app/services/interview_service.py"
      issue: "`finalize_confirmed_interview()` always writes `MealProcessingStatus.COMPLETED`, even when `grounding_status` becomes `DEGRADED_SAVED` for all groups."
    - path: "app/services/interview_service.py"
      issue: "`_degraded_group_finalizer_outcome()` builds best-effort fallback items with no nutrition and routes them into the authoritative save path."
  missing:
    - "Decide and enforce a different terminal behavior for all-group finalizer degradation on ordinary confirmed meals: reopen interview, fail the meal, or persist a clearly non-completed state instead of `COMPLETED`."
    - "Add a live-path regression proving a fully degraded confirmation cannot create a completed diary entry set with empty nutrition."
    - "Execute 05-11-PLAN.md Task 5 to fail closed when every finalizer group degrades."
  debug_session: ""

- truth: "Packaged or restaurant finalizer groups must actually use the grounding contract and return save-ready strict output, rather than silently degrading after partial search-only JSON."
  status: failed
  reason: "The packaged flatbread group (`PACKAGED_BRANDED` with brand `Al Khayam`) degraded in the live run with no persisted fetched URLs, and a direct replay of the same finalizer call showed one search query, no scrape call, and a partial JSON answer missing `serving_size_g`, `fiber_g`, `is_verified`, and structured grounding trace fields."
  severity: blocker
  test: 4
  root_cause: "The original clean UAT hit this gap while `FINALIZER_MODEL` was `google/gemini-3.1-flash-lite`; follow-up Langfuse traces after promotion to `google/gemini-3-flash-preview` show the same class of failure persists. Model capability alone is not enough while the response contract still asks the model to author verification, provenance, source URL, and trace fields."
  artifacts:
    - path: "app/config.py"
      issue: "`FINALIZER_MODEL` was promoted after the original UAT, but the gap remains because the model/service ownership boundary is still wrong."
    - path: "app/services/interview_service.py"
      issue: "`_group_finalizer_messages()` instructs packaged flows to use `firecrawl_search` and `firecrawl_scrape`, but the live packaged replay still returned search-only partial JSON."
    - path: "app/services/interview_service.py"
      issue: "`_validate_successful_finalizer_result()` correctly rejects the live response, but there is no stronger runtime fallback to a more capable model or a forced scrape pass when packaged grounding remains incomplete."
  missing:
    - "Keep the more capable finalizer model, but stop relying on any model to author verification/provenance fields directly."
    - "Require packaged/restaurant groups to perform scrape-backed grounding before verified success, with a regression that proves `fetched_urls` and structured trace fields are populated."
    - "Add a live-contract regression for the observed malformed response shape: partial nutrition, missing verification fields, and prose stuffed into `source_url` must not be the terminal packaged-group behavior."
    - "Execute 05-11-PLAN.md Tasks 2 and 3 so packaged/restaurant verification is derived from selected same-loop source IDs instead of model-authored provenance fields."
  debug_session: ""

- truth: "The finalizer model must not be responsible for service-owned verification, provenance, citation URLs, or operational trace fields."
  status: failed
  reason: "Latest Langfuse traces show the model can produce complete nutrition while omitting `is_verified`, `provenance`, and `grounding_trace`, after which the service rejects the useful nutrition and persists degraded fallbacks. Other traces show the model filling operational fields with repeated digits or repeated narrative."
  severity: blocker
  test: 4
  root_cause: "`FinalizedGroupResult` is doing double duty as both the model response schema and the service/persistence result shape. `_validate_successful_finalizer_result()` then requires model-authored fields that the application can determine from source taxonomy and tool-loop state."
  artifacts:
    - path: "app/services/interview_schema.py"
      issue: "`FinalizedGroupResult` exposes `is_verified`, `provenance`, `source_url`, and `grounding_trace` to the model even though those are deterministic service-owned fields."
    - path: "app/services/interview_service.py"
      issue: "`_validate_successful_finalizer_result()` rejects complete nutrition when the model omits service-owned verification fields."
    - path: "app/services/interview_service.py"
      issue: "`_degraded_group_finalizer_outcome()` discards parseable nutrition and falls back to unverified nutrition-empty rows."
  missing:
    - "Split the model-facing finalizer draft schema from the internal/persisted finalizer result schema."
    - "Derive `is_verified`, `provenance`, `source_url`, and `grounding_trace` in the service from source taxonomy plus same-loop tool evidence."
    - "Execute 05-11-PLAN.md Tasks 1 through 3."
  debug_session: ""

- truth: "Finalizer output must be bounded by a high finite cap and a narrow schema, not the old 4096-token cap and not an unbounded provider output budget."
  status: failed
  reason: "Removing the 4096 cap allowed Gemini 3 Flash Preview to produce two roughly 65,000-output-token malformed finalizer observations: one repeated `333333...` in an operational counter field, and one repeated provenance/source narrative inside a URL field."
  severity: blocker
  test: 4
  root_cause: "The old 4096 cap hid the schema/ownership issue through truncation, but the unbounded call gave the provider enough room to degenerate. The finalizer needs enough room for legitimate grounded JSON, while still bounding malformed output cost and making repeated operational fields impossible to promote."
  artifacts:
    - path: "app/config.py"
      issue: "After removing `FINALIZER_MAX_TOKENS`, the finalizer has no explicit output budget safety rail."
    - path: "app/services/interview_service.py"
      issue: "The finalizer chat completion no longer passes a high finite output limit and still parses legacy operational fields when present."
    - path: "app/services/interview_schema.py"
      issue: "The model-facing schema includes fields where repeated digits or provenance narrative can be emitted."
  missing:
    - "Add a high finite output cap greater than 4096, for example `FINALIZER_OUTPUT_MAX_TOKENS=12000`."
    - "Remove operational trace/citation fields from the model-facing schema so repeated counters and prose URLs cannot become candidate persisted state."
    - "Execute 05-11-PLAN.md Task 4."
  debug_session: ""
