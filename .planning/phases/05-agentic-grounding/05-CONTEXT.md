# Phase 5: Agentic Grounding - Context

**Gathered:** 2026-06-04
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 5 wires the real bounded SearXNG + Firecrawl agentic tool loop into the pipeline so brand/restaurant/unknown-food nutrition can be searched and fetched. The orchestration scaffolding already exists from prior phases (compose services wired, an async grounding handoff + worker, failure classification) but the actual tool-calling loop, the two tool functions, the HTTP clients, the URL allowlist, and the cost cap were never built — that is the hole this phase fills.

The key architectural decision: grounding is folded INTO the existing Phase 4.4 per-group enrichment finalizer (the synchronous call that already runs once per food group before save), NOT into the strict-JSON reasoning call and NOT via the existing async `poll_post_interview_grounding` worker. The finalizer is upgraded from a metadata composer into a nutrition-enrichment + grounding agent. The async grounding handoff path is retired.

Two contract changes accompany this: (1) meal_reasoning gains a per-group **constituents** block (major nutrition contributors with per-serving quantities and prep richness) and a **serving_count**, and (2) the discrete **portion bucket** model is replaced wholesale by **detailed per-constituent quantification**. The LLM never does arithmetic — it emits per-constituent macros + provenance, and application code sums deterministically.

**This phase does NOT:** turn reasoning into a tool-calling call, keep the async grounding worker, introduce an agent framework (deferred), or do live $ token accounting.

</domain>

<decisions>
## Implementation Decisions

### Loop Architecture & Placement
- **D-01:** The grounding tool loop lives INSIDE the per-group enrichment finalizer (the Phase 4.4 finalizer that already runs once per food group before save). The finalizer is upgraded from "save-ready metadata composer" to "nutrition enrichment + grounding agent" — it now searches for nutrition in addition to finalizing the record.
- **D-02:** The strict-JSON meal_reasoning call stays tool-free (avoids the strict `response_format` + tool-calling conflict). Reasoning only emits the structured data the finalizer consumes.
- **D-03:** Retire the async grounding path entirely. Delete `poll_post_interview_grounding`, the `GROUNDING_PENDING` interview state, the `needs_grounding` → handoff seam, and `build_grounding_reasoning_state`. Grounding is now synchronous inside the finalizer fan-out.
- **D-04:** Salvage the worker's failure logic into the finalizer. Lift `_classify_grounding_failure` (httpx / provider_quota / provider_auth / tool_execution / timeout categorization) and the best-effort save policy into the finalizer's tool-loop error path. Tool failure or timeout → commit best-effort with `is_verified=false`, same failure categories.

### Trigger & Scope
- **D-05:** ALL food groups run through the same enrichment finalizer (one uniform code path), in parallel using the existing bounded fan-out (`_run_group_finalizers`).
- **D-06:** Tools are always AVAILABLE but search fires by **model discretion** — the model only calls `searxng_search`/`firecrawl_fetch` when it lacks knowledge or a brand/restaurant is involved (e.g. "KKN seekh kebab" → search; home chicken breast → no search, uses own knowledge). There is NO hard PACKAGED/RESTAURANT source gate on the loop. (Deterministic source clarification from Phase 4.5 still feeds the finalizer as input, but does not gate whether tools run.)
- **D-07:** The finalizer receives NO image input — only structured text (reasoning output for the group + that group's interview answers + a copy of the descriptive rationale + a thin meal summary).

### Tool Surface & Loop Implementation
- **D-08:** Use **Firecrawl as the single grounding provider** — Firecrawl's native search (`/v1/search`) is configured to use the self-hosted SearXNG as its search backend (`SEARXNG_ENDPOINT`), so the app does NOT build or call a separate SearXNG client/tool. Expose two app-level tools, both backed by Firecrawl: `firecrawl_search` (SearXNG-backed search → candidate results + snippets/URLs) and `firecrawl_scrape` (fetch one URL → markdown). The search-then-scrape split is kept for cost control (don't scrape every result); collapsing to a single search-with-inline-scrape call is planner discretion if cost stays bounded. SearXNG remains a compose service but only as Firecrawl's backend, not a directly-called tool.
- **D-09:** Hand-roll the async tool loop using the OpenAI SDK's native tool-calling on flash-lite. NO agent framework now — this matches the locked CLAUDE.md "What NOT to Use" decision (no LangChain/LlamaIndex/LangGraph; ~80-120 line loop). A migration to **pydantic-ai** is explicitly DEFERRED to a later phase (see Deferred Ideas). (During discussion pydantic-ai was briefly chosen then reversed.)
- **D-10:** Firecrawl deployment: replace the heavy full stack with a leaner footprint, BUT this is now gated on a verification item — `devflowinc/firecrawl-simple` (api + redis + playwright) drops rabbitmq + nuq-postgres and is the preferred lean target, HOWEVER the planner/researcher MUST confirm the chosen Firecrawl variant exposes `/v1/search` with a `SEARXNG_ENDPOINT` backend (required by D-08). If firecrawl-simple lacks native search, either (a) use the official Firecrawl image trimmed to the services that support `/v1/search`, or (b) keep a direct SearXNG search path as a fallback. Decision: lean footprint preferred; native-search support is the hard constraint that picks the variant. `/v1/scrape` + `/v1/search` REST surface must both be available.

### Bounds (GROUND-02 / GROUND-03)
- **D-11:** Cost cap = a **per-group tool-call count** cap (≤ ~6 search+fetch calls, mapping onto the 6-iteration bound), enforced in the loop. Per-meal cost is implicitly bounded by `group_count × per-group cap`. No live token-$ accounting.
- **D-12:** 90-second wall-clock timeout applies per group loop.
- **D-13:** URL allowlist scope is **per group finalizer loop**: `firecrawl_scrape` may only fetch URLs harvested from THAT loop's `firecrawl_search` (SearXNG-backed) results; fabricated or cross-group URLs are rejected (GROUND-03). Matches the parallel-isolation model.

### Finalizer / Enrichment Model
- **D-14:** Keep `google/gemini-3.1-flash-lite` for the now tool-enabled finalizer, but expose an explicit enrichment/finalizer model + fallback config key. Verify lite handles the search loop reliably in UAT; escalate to `google/gemini-3-flash-preview` only if it under-performs on branded lookups.

### Nutrition Model (LLM does no math)
- **D-15:** The LLM does ZERO arithmetic. It emits per-constituent macros expressed for the constituent's own unit + provenance; application code deterministically computes `per-unit × magnitude × serving_count` and sums to group totals written on `FoodItem` (calories, protein_g, carbs_g, fat_g, fiber_g, serving_size_g) and `DiaryEntry`.
- **D-16:** Per-constituent finalizer output = `{ identity, unit_type (count|grams), magnitude, per-unit calories, protein_g, carbs_g, fat_g, fiber_g, provenance: searched|model_knowledge, source_url|null }`. Provenance is per constituent so a mixed grounded/estimated group is explicit.
- **D-17:** `is_verified` per group = `true` when the model was confident from its own knowledge OR a search succeeded; `false` ONLY when grounding was genuinely needed (unknown/branded) but the bounded loop failed or timed out → best-effort save. `ai_reasoning` records, per constituent, whether it was grounded (with URL) or model-estimated.

### meal_reasoning Schema Refactor
- **D-18:** Add a per-group `constituents` array = `[{ identity, identity_confidence, unit_type (count|grams), magnitude, unit_label?, cooking_method?, notes? }]`, expressed per ONE serving and carrying NO macros. Constituents are the major nutrition contributors (curry → tomato, cream/yoghurt, chicken; parotta → wheat, ghee), not spice-level detail.
- **D-19:** Add a per-group `serving_count`; constituents are per-serving (nested model). Group total = `serving_count × per-serving constituent costs`, summed deterministically. A quantity clarification updates `serving_count` only.
- **D-20:** Preparation richness is modeled primarily as explicit added constituents (glistening parotta → add `{ ghee/butter, qty }`; creamy curry → add `{ cream, grams }`). The fat's identity itself can be uncertain (ghee vs butter) and trigger an affirmation/identification clarification. Additionally each constituent carries an open `cooking_method` / `notes` field for richness/prep cues the constituent list doesn't capture.
- **D-21:** REMOVE the `group_actions` array AND the primary `group_action` from the model-facing schema. They are redundant with `clarification_actions` and bias the model into a single lane, suppressing other valid questions encoded below.
- **D-22:** Lean the root `action`/`meal_state` enums: drop `ASK_SOURCE_ORIGIN` (source is deterministic since Phase 4.5) and the `*_REQUIRED` variants. Root collapses toward `AUTO_CONFIRM` vs `INTERVIEW` (plus safety states `FAILED_UNCLEAR` / `NEEDS_SCHEMA_REVIEW`). Forcing a single rich root action biases the model; detail belongs in `clarification_actions`.
- **D-23:** `clarification_actions` may contain MULTIPLE actions of the same kind per group — e.g. 3 chicken pieces → 2 affirmations + 1 identification + 1 quantification, all coexisting. There is NO "one-question-per-type" rule.
- **D-24:** No new clarification *type* is needed for constituents. Existing `AFFIRMATION` / `IDENTITY`(CHOICE) / `QUANTITY` kinds cover constituent uncertainty too (e.g. parotta maida-vs-wheat → an affirmation or identification action).
- **D-25:** No structured target field on clarification actions. The self-describing `user_prompt` names the thing ("the second chicken piece") and the finalizer folds answers back from context. Stable `question_id` is retained.
- **D-26:** meal_reasoning emits a meal-level summary (or reuse the meal-level `decision_rationale`) to provide the finalizer's thin read-only meal summary.

### Finalizer Input Contract
- **D-27:** Each per-group enrichment finalizer call receives: the group's `constituents` (per-serving) + `serving_count`; group `decision_rationale` + `visual_evidence` + `missing_evidence` (the descriptive-rationale copy); selected identity/label; source/brand/restaurant from the Phase 4.5 deterministic clarification; the full clarification Q&A (self-describing prompts + answers); segment crop refs (available but NOT sent as image); AND a thin read-only **meal summary** (overall dish description / what else is on the plate) for disambiguation. The group stays the unit of decision; the meal summary is context-only — never sibling answers. Quantity-override rule: the finalizer overwrites the initial reasoning quantity estimate when that group had a quantity clarification.

### Quantity Migration (clean cut)
- **D-28:** Replace `portion_bucket` with structured detailed quantification. Drop the `PortionBucket` enum and the `portion_bucket` columns on `DiaryEntry` and `MealSegment` via an Alembic migration; remove the `PORTION_CONTEXT` bucket interview step; update the existing per-meal result message to render real quantities. UAT/dev DBs are disposable, so a clean cut (not additive coexistence) is taken.

### Tool Trace (GROUND-03)
- **D-29:** The grounding trace stored in `MealSegment.ai_reasoning` = a structured JSON block (`queries[]`, `fetched_urls[]`, per-constituent provenance, `iteration_count`, bounds-hit reason) PLUS a human-readable rendering. It APPENDS to — never overwrites — the meal_reasoning rationale already in `ai_reasoning`.

### Claude's Discretion
- SearXNG `settings.yml` JSON-format enablement and the engine allowlist (e.g. google/duckduckgo/bing/brave).
- Exact Pydantic model / field names for `constituents`, `serving_count`, finalizer output, and the trace block.
- Alembic migration mechanics for the portion_bucket → quantification cut.
- The exact per-group tool-call cap number (≤ ~6) and the precise mechanism enforcing the 90s wall-clock.
- Where the deterministic per-constituent summation lives (service vs resolution layer), as long as the LLM does no math.
- Exact config key names for the enrichment model/fallback, SearXNG/Firecrawl base URLs, iteration/timeout/allowlist knobs.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase Scope & Prior Decisions
- `.planning/ROADMAP.md` — Phase 5 goal, success criteria, dependency, and the Firecrawl-resource-envelope phase note.
- `.planning/REQUIREMENTS.md` — `GROUND-01`, `GROUND-02`, `GROUND-03`; also `REASON-01`, `REASON-04`, `INTERVIEW-03`, `INTERVIEW-04`, `MATCH-04`.
- `.planning/PROJECT.md` — stack constraints, the SearXNG+Firecrawl-as-tools key decision, best-effort `is_verified=false` decision, and the now-OVERRIDDEN "portion buckets, never a continuous multiplier" decision (superseded by D-28).
- `.planning/STATE.md` — accumulated decisions and the Phase 5 Firecrawl blocker note.
- `.planning/phases/04-reason-interview-learning-loop/04-CONTEXT.md` — original reasoning/interview/final-write/audit backbone; the INTERVIEW-03 post-interview re-grounding intent this phase finally implements.
- `.planning/phases/04.3-deterministic-clarification-schema-interview-ui/04.3-CONTEXT.md` — deterministic clarification schema, the resolver seam Phase 5 extends, and the explicit "Phase 5 replaces the resolver with a nutrition/grounding resolver" note.
- `.planning/phases/04.4-parallel-group-finalization-lite-detect/04.4-CONTEXT.md` — the per-group finalizer contract (D-01..D-17 there) that Phase 5 upgrades into the enrichment+grounding agent.
- `.planning/phases/04.5-source-aware-clarification-expansion/04.5-CONTEXT.md` — deterministic source/brand/restaurant clarification + `segment_ids` group contract that feeds the finalizer.

### Stack / Tooling (CLAUDE.md + research)
- `CLAUDE.md` — "OpenRouter Compatibility Surface" (tool calling + structured outputs), "Self-Hosted Grounding Tools" (SearXNG JSON enable, Firecrawl full vs `firecrawl-simple`), "Tool Calling / Grounding Libraries" (direct OpenAI SDK loop, no LangChain), and "What NOT to Use" (the no-framework rule that D-09 honors and the pydantic-ai migration defers against).
- `research/STACK.md`, `research/PITFALLS.md`, `research/ARCHITECTURE.md` — grounding stack and OpenRouter tool-call findings.

### Runtime Code
- `app/services/reasoning_schema.py` — `reasoning_response_format()` / `coerce_reasoning_response()`; add `constituents` + `serving_count`, remove `group_actions`/`group_action`, lean the action enums (D-18..D-26).
- `app/services/reasoning_service.py` — reasoning prompt + grouped gate; constituents/serving prompt work and the leaner action contract.
- `app/services/interview_service.py` — `GroupFinalizerInput`, `_build_group_finalizer_inputs()`, `_run_group_finalizers()`, `finalize_confirmed_interview()`, `build_grounding_reasoning_state()` (to retire); the finalizer is upgraded here (D-01, D-27).
- `app/services/grounding_stub.py` — current `build_grounding_prep` / `GROUNDING_REQUIRED_SOURCES`; the source-gate stub is superseded by model-discretion search (D-06).
- `app/services/meal_resolution_service.py` — authoritative `apply_final_meal_resolution()` write path + `needs_grounding`/`is_verified` fields; stays the save boundary, receives summed totals (D-15).
- `bot/polling.py` — `poll_post_interview_grounding`, `poll_grounding_handoffs`, `_classify_grounding_failure`, `_apply_grounding_failure_policy`, `_set_grounding_interview_status`, `GROUNDING_PENDING` plumbing — retire the worker, salvage failure logic into the finalizer (D-03, D-04).
- `bot/handlers.py` — `GROUNDING_PENDING` routing to remove.
- `app/config.py` — add grounding/tool config keys (enrichment model + fallback, SearXNG/Firecrawl base URLs, iteration/timeout/allowlist/cap).
- `app/models/food_item.py` — nutrition fields (`calories`, `protein_g`, `carbs_g`, `fat_g`, `fiber_g`, `serving_size_g`) the summed totals land on.
- `app/models/diary_entry.py`, `app/models/meal_segment.py` — `portion_bucket` columns + `PortionBucket` enum to drop in the D-28 migration.
- `docker-compose.yml` — lean Firecrawl footprint gated on native-`/v1/search` support (D-10); add `SEARXNG_ENDPOINT` to the Firecrawl env so SearXNG is its search backend; `searxng/settings.yml` for JSON format + engines.
- `migrations/` (Alembic) — portion_bucket removal + any new quantity columns.

### Tests
- `tests/test_interview_flow.py` — finalizer handoff, clarification, source parsing; extend for enrichment + grounding.
- `tests/test_reasoning_contract.py`, `tests/test_reasoning_flow.py`, `tests/test_reasoning_gate.py` — schema refactor (constituents, serving_count, removed group_actions, leaner enums).
- `tests/test_bot_contract.py` — retired grounding worker / state surface.
- `tests/test_match_flow.py` — quantification migration ripple.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- The per-group finalizer (`finalize_confirmed_interview` → `_build_group_finalizer_inputs` → `_run_group_finalizers`) already runs one bounded parallel structured call per group; Phase 5 attaches tools and nutrition enrichment to exactly this seam.
- `_classify_grounding_failure` in `bot/polling.py` already categorizes httpx/quota/auth/tool errors and is lifted into the finalizer's error path rather than rewritten (D-04).
- `meal_resolution_service.apply_final_meal_resolution()` already owns the authoritative FoodItem/DiaryEntry/FoodVisual write and the `needs_grounding`/`is_verified` fields; it stays the save boundary and receives app-summed totals.
- `docker-compose.yml` already wires `SEARXNG_BASE_URL` + `FIRECRAWL_BASE_URL` env into app+bot; only the Firecrawl service images change (full → simple).
- `reasoning_schema.py` coercion helpers (`_coerce_*`) are the pattern to extend for `constituents` and to delete `group_actions`/`group_action` handling.

### Established Patterns
- Postgres is the source of truth; reasoning/interview state lives in `MealLog.reasoning_state_json` + `InterviewSession.current_prompt_payload`.
- Pipeline stages fail closed and repair-once; tool failure must degrade to a best-effort save, never hang the meal.
- Strict structured outputs require `additionalProperties: false` + all keys `required` (OpenRouter strict mode) — constituent/finalizer schemas must follow this.
- Finalizers are group-scoped and parallel; new context is added per group, never as cross-group sibling answers.

### Integration Points
- Build `firecrawl_search` + `firecrawl_scrape` httpx tool functions hitting Firecrawl `/v1/search` (SearXNG-backed via `SEARXNG_ENDPOINT`) and `/v1/scrape`. No direct app→SearXNG client/tool.
- Configure Firecrawl with `SEARXNG_ENDPOINT` pointing at the in-compose SearXNG; SearXNG stays internal-only as the search backend (JSON format enabled).
- Wrap the finalizer call in a hand-rolled native tool-calling loop with the per-group allowlist, ≤6 tool-call cap, and 90s timeout.
- Add `constituents` + `serving_count` to the model-facing reasoning schema; remove `group_actions`; lean the action enums.
- App-side deterministic summation of per-constituent macros → group totals on the save path.
- Alembic migration to drop portion_bucket; update the per-meal message renderer.

</code_context>

<specifics>
## Specific Ideas

- KKN seekh kebab (brand) → the finalizer should search; a plain home chicken breast → no search, model knowledge suffices. Search must be specific ("calories in one small chicken drumstick", per item), never vague.
- Wheat parotta example: large size ≈ 100–120 g, calories mostly from wheat; if the image looks glistening, reasoning adds ~½ tsp ghee/butter as its own constituent (with the ghee-vs-butter identity itself possibly clarified).
- "2 parottas" → group `serving_count = 2`, constituents costed per single serving, app multiplies — quantity clarification just updates `serving_count`.
- "3 chicken pieces" demonstrates why `clarification_actions` must allow several same-kind questions (2 affirmations + 1 identification + 1 quantification) and why a single forced `group_action` is harmful.
- The finalizer prompt becomes "enrich + ground + finalize", not just finalize; meal_reasoning prompt/schema enhancements (constituents, richness cues, size→grams) are in-scope reasoning-side work for this phase.

## Research Flags

- **Firecrawl native search + SearXNG backend (HARD constraint, D-08/D-10):** Confirm which Firecrawl variant exposes `/v1/search` with a `SEARXNG_ENDPOINT` backend. Verify `devflowinc/firecrawl-simple` supports it; if not, pick the leanest official-Firecrawl service set that does (or fall back to a direct SearXNG search path). This choice picks the compose footprint.
- **Mac mini resource envelope (phase note):** 5 sequential Chromium scrapes under Docker memory limits without OOM, on the chosen Firecrawl variant.
- **OpenRouter native tool-calling on `gemini-3.1-flash-lite`:** confirm a hand-rolled multi-turn `tools=` loop (search → scrape → final) works through the OpenRouter compatibility layer for the lite model; verify per-group bounds (≤6 calls / 90s) are enforceable in plain code.

</specifics>

<deferred>
## Deferred Ideas

- **pydantic-ai migration** for the tool loop — adopt later as a deliberate, separate migration off the hand-rolled loop. (Considered and chosen during discussion, then reversed to ship hand-rolled first.)
- **Token-$ cost accounting** (real OpenRouter usage × price, per-meal $ ceiling) beyond the tool-call-count proxy — revisit if the proxy proves too coarse.
- **Per-meal shared URL allowlist** (cross-group URL reuse, e.g. one restaurant menu fetched once) — deferred in favor of per-group isolation.
- **Per-meal result message polish / detailed-quantity rendering** beyond the minimal update needed to not break the existing message — full treatment is Phase 6.
- Richer historical-brand suggestion UX and broader learned-distribution surfacing — post-Phase-5.

</deferred>

---

*Phase: 5-Agentic Grounding*
*Context gathered: 2026-06-04*
