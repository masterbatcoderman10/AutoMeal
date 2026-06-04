# Phase 5: Agentic Grounding - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-04
**Phase:** 5-agentic-grounding
**Areas discussed:** Loop architecture & trigger, Nutrition output schema, Meal-reasoning enhancements/schema refactor, Finalizer input contract, Firecrawl footprint & tool surface, Cost cap & bounds, Migration & ripple, Finalizer output/provenance

---

## Area selection

| Option | Description | Selected |
|--------|-------------|----------|
| Loop architecture & trigger | Where the loop runs; trigger policy | ✓ |
| Nutrition extraction | Scraped → FoodItem macros | (reached via follow-ups) |
| Cost cap mechanism | Per-meal cap value/mechanism | (reached via follow-ups) |
| Firecrawl footprint | Full vs simple on Mac mini | (reached via follow-ups) |

**User's choice:** Started with "Loop architecture & trigger"; organically expanded into nutrition schema, reasoning refactor, finalizer I/O, firecrawl/tools, cost cap, and migration.

---

## Loop architecture & placement

| Option | Description | Selected |
|--------|-------------|----------|
| Separate grounding pass | Reasoning flags needs_grounding; distinct grounding agent runs the loop | ✓ (realized as: loop inside the per-group finalizer) |
| Inline tools in reasoning | Add tools to the strict-JSON reasoning call | |
| You decide | — | |

**User's choice:** Grounding goes into the post-interview per-group **nutrition finalizer** (which already takes meal_reasoning output + interview answers and currently only finalizes). It becomes an enrichment+search step. Reasoning prompt gains a per-group constituents block.
**Notes:** Search matters for unknown/branded foods (KKN seekh kebab); not for known macros (chicken breast).

## Worker reconciliation

| Option | Description | Selected |
|--------|-------------|----------|
| Retire the async handoff | Finalizer does it inline; remove worker/state/handoff | ✓ |
| Keep worker as the loop host | Upgrade poll_post_interview_grounding to host the loop | |
| You decide | — | |

**User's choice:** Retire the async handoff. Failure/retry logic folds into the finalizer.

## Trigger scope

| Option | Description | Selected |
|--------|-------------|----------|
| All groups, model-discretion search | Uniform path, tools always available, model decides when to search | ✓ |
| Gate search by signal | Attach tools only on PACKAGED/RESTAURANT/no-match | |
| You decide | — | |

**User's choice:** All groups, parallel, model-discretion search. No image input — inputs = meal_reasoning output + that group's interview answers + a copy of the descriptive rationale. Constituents are objects `{identity, quantity}`. Finalizer overwrites the initial quantity estimate when a group had a quantity clarification.

## Finalizer model

| Option | Description | Selected |
|--------|-------------|----------|
| Keep flash-lite, config override | Stay on gemini-3.1-flash-lite, expose config key, verify in UAT | ✓ |
| Upgrade to flash-preview | Move to gemini-3-flash-preview | |
| You decide | — | |

**User's choice:** Keep flash-lite with config override.

---

## Nutrition output schema

| Option | Description | Selected |
|--------|-------------|----------|
| Per-constituent, then sum | Estimate per constituent, sum to group | ✓ |
| Group total only | One macro total per group | |
| You decide | — | |

**User's choice:** Per-constituent then deterministic sum. The LLM does NO math — it produces per-constituent macros per unit/item (search is specific, e.g. "calories in a small/large chicken drumstick, per item"); quantities come from reasoning or interview; app sums deterministically. Portion buckets are removed in favor of detailed quantification.

## Quantity shape

| Option | Description | Selected |
|--------|-------------|----------|
| Count × named unit | per-one-unit macros + unit label + count | |
| Grams-based | per-100g + grams | |
| Hybrid per-constituent unit | each constituent picks count or grams + magnitude | ✓ |

**User's choice:** Hybrid per-constituent unit.

## Verified rule

| Option | Description | Selected |
|--------|-------------|----------|
| Verified only if search-backed | true only when a fetched page backed it | |
| Verified if no search needed OR search succeeded | confident model knowledge counts; false only on failed grounding | ✓ |
| You decide | — | |

**User's choice (paraphrased):** Model knowledge is trustworthy for non-branded items (homemade wheat parotta ≈ 100–120g, glistening → ½ tsp ghee). So verified=true on confident knowledge OR successful search; false only when grounding was needed but the bounded loop failed.

---

## Meal-reasoning: division of labour

| Option | Description | Selected |
|--------|-------------|----------|
| Reasoning: identity+qty+cues; finalizer: macros | reasoning emits constituents (no macros), finalizer fills macros | ✓ |
| Reasoning emits constituents + rough macros | duplicate nutrition logic | |
| You decide | — | |

**User's choice:** Reasoning emits identity+quantity+cues only; finalizer computes macros (searching when needed).

## Prep richness cues

| Option | Description | Selected |
|--------|-------------|----------|
| Richness becomes a constituent | glistening → add {ghee, qty} | ✓ (primary) |
| Constituent + structured cue field | cooking_method/notes descriptor | ✓ (also) |
| No new constituent questions | — | |

**User's choice:** Both — richness as explicit constituents (fat identity ghee-vs-butter can itself be clarified) PLUS an open cooking_method/notes field.

## Quantity shape (multi-item groups)

| Option | Description | Selected |
|--------|-------------|----------|
| Nested: serving_count × per-serving constituents | group carries serving_count; constituents per serving | ✓ |
| Flat: absolute group amounts | constituents pre-multiplied | |
| You decide | — | |

**User's choice:** Nested.

## Clarification granularity / schema refactor

| Option | Description | Selected |
|--------|-------------|----------|
| Group-level, highest-impact only | one extra question per group | |
| Per-constituent questions | each uncertain constituent can ask | ✓ (via unified list) |
| No new constituent questions | finalizer/search only | |

**User's choice:** Remove `group_actions` entirely (redundant, biases the model); `clarification_actions` may hold multiple of the same kind (3 chicken pieces → 2 affirmations + 1 identification + 1 quantification). Lean the root action enum (drop ASK_SOURCE_ORIGIN — deterministic since 4.5 — and *_REQUIRED variants → AUTO_CONFIRM vs INTERVIEW). No new clarification type for constituents (reuse AFFIRMATION/IDENTITY/QUANTITY).

## Clarification targeting

| Option | Description | Selected |
|--------|-------------|----------|
| Target ref on the action | structured target_kind/target_ref | |
| Self-describing prompt only | user_prompt names the thing; finalizer folds from context | ✓ |
| You decide | — | |

**User's choice:** Self-describing prompt only.

---

## Finalizer input scope

| Option | Description | Selected |
|--------|-------------|----------|
| Group-only (keep 4.4 isolation) | only the group's own context | |
| Group + thin meal summary | add a read-only meal-level header | ✓ |
| You decide | — | |

**User's choice:** Group + thin meal summary (context-only; group stays the decision unit).

---

## Firecrawl footprint

| Option | Description | Selected |
|--------|-------------|----------|
| Verify full stack, swap only if it OOMs | keep full firecrawl, smoke-test | |
| Pre-swap to firecrawl-simple now | devflowinc/firecrawl-simple, compose rewrite | ✓ |
| You decide | — | |

**User's choice:** Pre-swap to firecrawl-simple now.

## URL allowlist scope / tool surface

| Option | Description | Selected |
|--------|-------------|----------|
| Per group finalizer loop | each loop's own allowlist from its searxng results | ✓ |
| Per meal (shared) | one allowlist across groups | |
| You decide | — | |

**User's choice:** Per-group ("of course"). Two tools: searxng_search (gather candidates) + firecrawl_fetch (markdown extract); native flash-lite tool calling, coded loop.

## Loop implementation framework

| Option | Description | Selected |
|--------|-------------|----------|
| Hand-rolled loop (matches locked stack) | plain async OpenAI SDK loop | ✓ (final) |
| Pydantic-AI (lightweight framework) | typed framework over the loop | (chosen then reversed) |
| You decide | — | |

**User's choice:** Initially chose pydantic-ai, then reversed: hand-roll the loop now, migrate to pydantic-ai later. (Hand-rolled matches the locked CLAUDE.md no-framework decision.)

## Cost cap mechanism

| Option | Description | Selected |
|--------|-------------|----------|
| Tool-call count proxy, per group | ≤6 tool calls per group, maps to iteration bound | ✓ |
| Token-$ via OpenRouter usage | live $ accounting + meal ceiling | |
| Both | per-group calls + meal $ ceiling | |

**User's choice:** Tool-call count proxy, per group. 90s wall-clock per group loop.

---

## Migration & ripple

### Portion migration

| Option | Description | Selected |
|--------|-------------|----------|
| Clean cut now | drop PortionBucket enum + columns, structured quantity | ✓ |
| Additive, derive bucket for now | keep bucket column, add quantity | |
| You decide | — | |

**User's choice:** Clean cut now (DBs disposable).

### Retire worker / failure logic

| Option | Description | Selected |
|--------|-------------|----------|
| Salvage failure logic into finalizer | lift _classify_grounding_failure + best-effort policy | ✓ |
| Hard remove, finalizer handles errors fresh | delete everything, fresh try/except | |
| You decide | — | |

**User's choice:** Salvage failure logic into the finalizer.

---

## Finalizer output / provenance

### Output shape

| Option | Description | Selected |
|--------|-------------|----------|
| LLM emits per-constituent macros+provenance; app sums | LLM math-free; deterministic app summation | ✓ |
| LLM also emits group totals | reintroduces LLM math | |
| You decide | — | |

**User's choice:** LLM emits per-constituent macros + provenance; app sums.

### Trace format

| Option | Description | Selected |
|--------|-------------|----------|
| Structured JSON + rendered text | machine-auditable + human-readable, appends | ✓ |
| Human-readable text only | plain text | |
| You decide | — | |

**User's choice:** Structured JSON + rendered text, appended to (not overwriting) the meal_reasoning rationale.

---

## Claude's Discretion

- SearXNG JSON-format enablement + engine allowlist.
- Exact Pydantic model/field names for constituents, serving_count, finalizer output, trace block.
- Alembic migration mechanics for the portion_bucket cut.
- Exact per-group tool-call cap number (≤~6) and 90s enforcement mechanism.
- Where the deterministic summation lives.
- Exact config key names.

## Deferred Ideas

- pydantic-ai migration for the tool loop (later phase).
- Token-$ cost accounting beyond the tool-call proxy.
- Per-meal shared URL allowlist (cross-group reuse).
- Phase 6 per-meal message detailed-quantity rendering polish.
- Richer historical-brand suggestion UX / learned-distribution surfacing.
