# Phase 5: Agentic Grounding - Research

**Researched:** 2026-06-04  
**Status:** Ready for planning

## Questions Answered

1. Which self-hosted grounding stack actually satisfies Phase 5's required `search -> allowlisted fetch -> structured save` loop?
2. Can the current OpenRouter/OpenAI SDK setup support a bounded manual tool loop without introducing a framework?
3. What concrete verification is required before trusting Firecrawl search and scrape in this deployment?

## Executive Summary

- **Use the existing app-owned tool loop, not a framework.** OpenRouter's tool-calling contract is explicit: the model proposes `tool_calls`, the app executes them, then the app resubmits the full message history plus tool results. That matches the current repo's `llm_client` pattern and the phase context's no-framework decision.
- **Do not switch Phase 5 to `firecrawl-simple` if Phase 5 still requires Firecrawl-backed search.** The `firecrawl-simple` repo and its v1 OpenAPI advertise `/scrape` and `/crawl` routes, not `/search`. By contrast, the official Firecrawl self-host guide explicitly documents `/search` and `SEARXNG_ENDPOINT`.
- **Keep the search and strict-final-output turns separate.** This is an implementation recommendation from the current code shape plus OpenRouter's strict JSON requirements: use tool turns for search/scrape, then do one no-tools strict JSON finalization pass before save.
- **The main operational risk is self-hosted search reliability, not SDK capability.** Official Firecrawl docs support the intended config, but a real self-host issue (`firecrawl/firecrawl#2139`) shows `/search` returning empty results while `/scrape` still worked. Phase 5 must ship with verification probes and a documented fallback.

## Phase Requirements

### GROUND-01
Reasoning and post-interview stages can call search/fetch tools for branded or restaurant nutrition data.

### GROUND-02
The tool loop is bounded by:
- max iterations
- wall-clock timeout
- per-meal or per-group cost/call caps
- URL allowlist

### GROUND-03
The tool trace is appended to `MealSegment.ai_reasoning` in a readable and auditable form.

## Verified Findings

### 1. OpenRouter tool-calling fits the current architecture

**What the docs say**
- OpenRouter's tool-calling flow is app-mediated: the model does not call the tool directly; the client executes the tool and sends the tool result back in a follow-up request.
- The request/response shape is OpenAI-compatible and works with Gemini-family examples.

**Implication for Phase 5**
- The existing `app/services/llm_client.py` abstraction is already the right ownership boundary.
- A manual loop inside `interview_service` or a dedicated grounding service is sufficient; no LangChain/LangGraph/PydanticAI introduction is required for this phase.

### 2. Strict JSON finalization remains viable

**What the docs say**
- OpenRouter structured outputs use `response_format.type = json_schema`.
- Strict mode expects `strict: true`, explicit `required`, and `additionalProperties: false`.

**Implication for Phase 5**
- The final save-ready grounding result should still go through a strict schema pass.
- Best fit for the current codebase: tool loop first, strict finalization second.
- This separation is an implementation recommendation inferred from repo constraints plus strict-schema requirements, not an OpenRouter prohibition on mixing features.

### 3. Official Firecrawl self-host supports the exact search backend Phase 5 wants

**What the docs say**
- Firecrawl's self-host guide documents `/search`.
- It says `/search` uses Google by default.
- It also documents `SEARXNG_ENDPOINT`, plus optional `SEARXNG_ENGINES` and `SEARXNG_CATEGORIES`, to point Firecrawl search at a SearXNG server with JSON enabled.

**Implication for Phase 5**
- The cleanest Phase 5 architecture is:
  - app tool `firecrawl_search`
  - app tool `firecrawl_scrape`
  - Firecrawl `/search` configured to use the internal SearXNG instance
- This preserves the user's decided split between search and fetch while keeping SearXNG behind Firecrawl.

### 4. `firecrawl-simple` is not a drop-in replacement for this phase

**What the repo says**
- `firecrawl-simple` describes itself as a stripped-down fork with billing and AI features removed.
- Its README says only v1 `/scrape`, `/crawl/{id}`, and `/crawl` are supported.
- Its published v1 OpenAPI shows `/scrape` and `/crawl`, and does not expose `/search`.

**Implication for Phase 5**
- If Phase 5 keeps the current "Firecrawl-backed search + scrape" design, `firecrawl-simple` is insufficient.
- A Phase 5 switch to `firecrawl-simple` only works if the app also reintroduces a **direct SearXNG client/tool** for search.
- Recommended planning stance: prefer official Firecrawl for Phase 5 unless the plan explicitly chooses the fallback architecture `searxng_search + firecrawl_scrape`.

### 5. Self-hosted Firecrawl search needs live verification

**What the primary source says**
- Firecrawl issue `#2139` reports a self-hosted deployment where `crawl` and `scrape` worked, but both `v1/search` and `v2/search` returned empty results.

**Implication for Phase 5**
- Search support is not enough on paper; the phase must verify it in the target compose stack.
- Planner should require:
  - one search smoke test without scraping
  - one search result piped into scrape
  - one negative test proving empty or invalid search results degrade safely

### 6. SearXNG JSON output must be enabled or Firecrawl search backend will not work

**What the docs say**
- SearXNG's Search API supports `/search`.
- JSON output requires `format=json`.
- Allowed output formats come from `settings.yml -> search.formats`; requesting an unset format returns `403`.

**Implication for Phase 5**
- `searxng/settings.yml` must explicitly enable JSON output.
- This should be treated as a hard compose/config prerequisite for Firecrawl-backed search.

### 7. Firecrawl exposes resource throttles the phase can reuse operationally

**What the self-host guide says**
- Firecrawl documents `MAX_CPU` and `MAX_RAM` thresholds for worker admission control.

**Implication for Phase 5**
- The phase note about "5 sequential Chromium scrapes under Docker memory limits" has a concrete place to land:
  - compose env limits
  - Firecrawl `MAX_RAM`
  - verification scripts that prove no OOM or dead queue state

## Recommended Architecture

### Recommended Variant

Use **official self-hosted Firecrawl** for Phase 5 with:
- `SEARXNG_ENDPOINT=http://searxng:8080`
- SearXNG JSON format enabled
- two app-owned tools:
  - `firecrawl_search`
  - `firecrawl_scrape`

### Fallback Variant

If official Firecrawl search proves unstable in verification:
- keep Firecrawl only for `/scrape`
- add a direct app-owned `searxng_search` client/tool
- preserve the same allowlist and trace contract

### Not Recommended For This Phase

- `firecrawl-simple` as the only grounding service while still expecting Firecrawl-native `/search`

## Loop Design Guidance

### Control Flow

1. Build one per-group grounding context from:
   - finalized group identity inputs
   - source/brand/restaurant answers
   - constituent candidates
   - thin meal summary
2. Start a bounded tool loop with tools available.
3. Enforce app-side limits:
   - max tool calls / iterations
   - wall-clock timeout
   - URL allowlist
   - duplicate-call suppression
4. When the model stops calling tools, run one strict JSON finalization pass.
5. Deterministically sum and persist through the existing final write path.

### Bounds

Recommended concrete bounds for planning:
- max tool calls per group: `6`
- wall-clock timeout per group: `90s`
- `parallel_tool_calls=False`
- request timeout per LLM call materially below `90s`
- reject scrape requests for URLs not returned by search in the same group loop

### Failure Policy

Preserve the repo's existing degradation semantics:
- tool/search/scrape failure -> best-effort finalization
- `is_verified=false` when grounding was needed but not completed reliably
- append failure category and trace to `ai_reasoning`
- do not leave meals hanging in a handoff state

## Traceability Guidance

Append, do not overwrite, existing `MealSegment.ai_reasoning`.

Recommended trace payload ingredients:
- `trace_id`
- per-group query list
- search result shortlist with chosen URL
- allowlist contents
- fetched URLs
- per-constituent provenance (`searched` vs `model_knowledge`)
- iteration count
- stop reason (`completed`, `max_calls`, `timeout`, `empty_search`, `tool_error`)
- degraded-save flag and failure category when applicable

Also render a compact human-readable block so production debugging does not require raw JSON inspection.

## Verification Architecture

### Required Pre-Ship Checks

1. **Firecrawl search backend probe**
   - call Firecrawl `/search`
   - confirm non-empty results for a stable branded-food query
   - confirm returned URLs are valid candidates for scrape

2. **Allowlist enforcement**
   - attempt scrape on a model-fabricated URL
   - confirm the app rejects it before HTTP execution

3. **Loop-bound enforcement**
   - simulate repeated tool requests
   - confirm hard stop at configured cap
   - confirm final degraded save instead of stalled meal

4. **90-second timeout**
   - inject slow tool behavior
   - confirm timeout exits cleanly with traced degraded result

5. **Sequential Chromium envelope**
   - run 5 sequential scrapes in the compose stack
   - confirm no OOM, dead playwright worker, or stuck queue/admin state

6. **Trace persistence**
   - verify `MealSegment.ai_reasoning` contains both machine-readable and readable trace output

### Test Surfaces

- `tests/test_interview_flow.py`
  - finalizer integration
  - degraded-save branch
  - removal of handoff-only states
- `tests/test_match_flow.py`
  - final write persistence of provenance and verification flags
- `tests/test_reasoning_contract.py`
  - final strict output schema for constituent nutrition/provenance
- new grounding-focused tests are warranted for:
  - Firecrawl client wrapper
  - allowlist policy
  - bounded loop orchestration

## Risks And Planning Notes

### Highest Risk

- **Search availability drift in self-hosted Firecrawl**
  - supported by docs
  - not guaranteed by recent user report
  - requires live verification in this stack

### Medium Risk

- **Over-scoping the refactor**
  - Phase 5 should retire the old polling handoff, but should not fork a new save path

- **Trace bloat**
  - raw snippets can explode `ai_reasoning`
  - planner should cap stored snippet lengths and keep only a shortlist

- **Tool-loop duplication**
  - repeated similar searches/scrapes can burn time and cost
  - planner should include deduplication rules

## Planning Recommendations

- Plan Phase 5 around the existing `interview_service` per-group finalizer seam.
- Introduce a dedicated grounding client/service layer rather than embedding raw HTTP inside handlers.
- Keep `apply_final_meal_resolution()` as the only authoritative save transaction.
- Treat official Firecrawl as the default Phase 5 target.
- Only choose `firecrawl-simple` if the plan explicitly adopts direct `searxng_search` in the app.

## Sources

### Primary

- OpenRouter Tool Calling: https://openrouter.ai/docs/guides/features/tool-calling
- OpenRouter Structured Outputs: https://openrouter.ai/docs/guides/features/structured-outputs
- Firecrawl Search API docs: https://docs.firecrawl.dev/api-reference/endpoint/search
- Firecrawl self-host guide: https://github.com/firecrawl/firecrawl/blob/main/SELF_HOST.md
- Firecrawl self-host issue `#2139`: https://github.com/firecrawl/firecrawl/issues/2139
- `firecrawl-simple` README: https://github.com/devflowinc/firecrawl-simple
- `firecrawl-simple` SELF_HOST: https://github.com/devflowinc/firecrawl-simple/blob/main/SELF_HOST.md
- `firecrawl-simple` v1 OpenAPI: https://github.com/devflowinc/firecrawl-simple/blob/main/apps/api/v1-openapi.json
- SearXNG Search API: https://docs.searxng.org/dev/search_api
- SearXNG `search.formats` settings: https://docs.searxng.org/admin/settings/settings_search.html

## Metadata

- Research mode: inline recovery after background researcher stall
- Confidence: high on Firecrawl/OpenRouter/SearXNG capability surface; medium on real-world self-host search stability until verified in this compose stack
