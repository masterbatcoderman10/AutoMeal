# Phase 04: Reason, Interview & Learning Loop - Research

**Researched:** 2026-05-28
**Domain:** Meal-level multimodal reasoning, Telegram interview state, correction learning, crash recovery
**Confidence:** MEDIUM

<user_constraints>
## User Constraints (from CONTEXT.md) [VERIFIED: codebase grep]

### Locked Decisions
## Implementation Decisions

### Reasoning Scope And Inputs
- **D-01:** Reasoning is meal-level, not one call per segment. It receives the original meal image plus all segment crops in one multimodal message.
- **D-02:** Segment inputs must be stable and indexed (`segment_1`, `segment_2`, etc.) with crop, bounding box, provisional label, and persisted match context.
- **D-03:** Matched segments receive identity-first FoodItem metadata: name, aliases, source_type, brand/restaurant if identity-relevant, verification, times_confirmed, and similarity score. Nutrition fields are not included by default.
- **D-04:** Reasoning must handle all-unmatched, all-matched, and partial meals. All matched meals still run reasoning for quantification, dedupe, composite handling, specificity, and conflict checks.
- **D-05:** Reasoning model target is `google/gemini-3.5-flash`; researcher/planner must verify exact OpenRouter model ID, structured outputs, multi-image support, and prompt caching support.
- **D-06:** Stable reasoning prompt/schema/taxonomy should be cache-friendly. Use OpenRouter/provider input or prompt caching when supported.

### Reasoning Specificity And Quantity
- **D-07:** Reasoning must avoid sparse labels when nutrition identity changes. Chicken should specify cut when visible or ask if unclear; rolls/sandwiches should identify filling unless visible; rice should distinguish useful grain/prep types; unclear meat must be flagged.
- **D-08:** Specificity policy lives in both prompt and a plain editable JSON taxonomy file, such as `config/reasoning_taxonomy.json`.
- **D-09:** Detail escalation is nutrition-impact based. Ask when missing detail likely changes calories/macros materially, with roughly 25% likely impact as a planning heuristic.
- **D-10:** Bucket-only product logic is rejected. Reasoning uses intelligent quantity units: count, grams, ml/litre/glass, serving/container, or composite components as appropriate.
- **D-11:** For open metrics such as rice, pasta, noodles, and liquids, output ranges and visual basis, not fake exact values. Example: estimated 90-130 g from a shallow half-plate long-grain rice mound.
- **D-12:** Quantity uncertainty triggers a user question only when nutrition impact is large. Identity/detail questions come before quantity questions.
- **D-13:** Composite foods are adaptive: default to one food with components, but create multiple line items when visible components are distinct and nutrition-relevant.
- **D-14:** `SPLIT_REQUIRED` creates virtual line items from the same segment when multiple nutritionally meaningful foods are clearly visible. If unclear and impactful, ask one targeted question. Do not re-segment in Phase 4.
- **D-15:** Reasoning detail is additive, not automatic DB churn. A broad match such as `chicken curry` can get detail like `visible chicken leg piece` without creating a new FoodItem/FoodVisual for every detail variant.
- **D-16:** Additive detail may promote to durable FoodItem data only after user confirmation and/or repeated confirmed observations, not immediately.

### Reasoning Outputs And Gates
- **D-17:** Known actions are `AUTO_CONFIRM`, `ASK_CHOICE`, `INTERVIEW`, `ASK_QUANTITY`, `MERGE_SEGMENTS`, `SPLIT_REQUIRED`, `FAIL_UNCLEAR`, and `NEEDS_GROUNDING`. The action taxonomy must remain open to future expansion.
- **D-18:** Use strict JSON object shape, but keep `action` as an open string. Unknown actions must route to `NEEDS_SCHEMA_REVIEW` rather than crashing only because a new action appeared.
- **D-19:** Reasoning may reject a high-similarity DB match when visual/details conflict. Rejection does not mutate DB. It presents original match plus top alternatives and/or all-wrong.
- **D-20:** `ASK_CHOICE` display is adaptive: original DB match plus top-3 alternatives plus all-wrong when a DB match exists; top-3 alternatives plus all-wrong when no match exists.
- **D-21:** Top candidates are ranked by visual specificity, DB match signal, meal/cuisine context, nutrition-impact clarity, and uncertainty honesty. Generic fallback candidates are allowed only as explicit uncertainty candidates.
- **D-22:** Candidate records use split confidence and evidence fields, not a single opaque score. Include identity confidence, visual evidence, missing evidence, specificity level, nutrition relevance, and candidate source.
- **D-23:** Segment/group reasoning output includes `identity_confidence`, `quantity_confidence`, `match_consistency_confidence`, `decision_rationale`, and `gate_reason`.
- **D-24:** Final meal states are `READY_TO_WRITE`, `PENDING_CHOICE`, `PENDING_INTERVIEW`, `PARTIAL_RESOLVED_WAITING`, `FAILED_UNCLEAR`, and `NEEDS_SCHEMA_REVIEW`.
- **D-25:** Invalid schema, contradictory actions, or lazy generic output retries once with a stricter prompt. If still bad, mark `FAILED_UNCLEAR` and notify safely; do not invent diary entries.
- **D-26:** Visible text is handled by the reasoning model prompt, not a separate OCR stage. Clear package/brand/restaurant/menu text may be used; blurry or partial text is marked uncertain.
- **D-27:** `NEEDS_GROUNDING` is allowed as an action hint. Phase 4 stores it; Phase 5 implements the full SearXNG/Firecrawl loop.

### Match And Parallel Processing
- **D-28:** Bounded per-meal parallelism applies only to segment embedding and vector matching. Reasoning remains one meal-level call.
- **D-29:** Default per-meal segment parallelism is 4 and must be configurable by env.
- **D-30:** If one segment embed/match fails, retry that segment. If still failing after retry budget, do not run reasoning with missing segment inputs; safe-fail or recover through janitor policy.
- **D-31:** Persist per-segment match results before reasoning. Crash recovery should resume from persisted embeddings/matches when possible.
- **D-32:** Matching provides top 3 vector candidates per segment to reasoning. Always keep the best candidate; include additional candidates only above a planner-chosen floor, suggested around 0.65.
- **D-33:** Update match threshold from 0.85 to 0.90. It is now a trusted prior signal, not permission to bypass reasoning or write a DiaryEntry directly.
- **D-34:** Exclude invalidated FoodVisuals from vector candidates.
- **D-35:** Keep the current bot-owned status-driven worker pattern for Phase 4. A dedicated worker service is a future refactor, not required now.

### Persistence And Writes
- **D-36:** Persist segment-level reasoning JSON on `MealSegment.ai_reasoning` or equivalent. It should include action, evidence, missing evidence, quantity, confidence, trace id, and pending question if any.
- **D-37:** Add or choose a meal-level reasoning JSON persistence surface for merge groups, composite notes, final meal state, pending questions, and overall decision. Current `MealLog` has no such field.
- **D-38:** Persist reasoning state immediately, but create DiaryEntry and new FoodVisual rows only when all meal segments are resolved and final confirmation has passed when needed.
- **D-39:** Final write is one DB transaction: DiaryEntries, eligible FoodVisuals, old visual invalidations for corrections, correction events, final reasoning/interview state, and `MealLog.processing_status = COMPLETED`.
- **D-40:** Telegram result send happens after DB commit; send failure must not roll back committed meal state.
- **D-41:** Coarse `MealLog.processing_status` uses `INTERVIEWING` for waiting-user states. Fine state lives in persisted interview/session/reasoning records.
- **D-42:** `portion_bucket` fields are insufficient for product logic. Planning must introduce intelligent quantity persistence with unit, amount/range, visual basis, confidence, and components.

### Telegram Interview
- **D-43:** Telegram interview is hybrid: buttons for known choices, free text for names/details/other/corrections.
- **D-44:** Keep roadmap states as fallback backbone: `INITIAL_QUESTION -> FOOD_NAME -> SOURCE_TYPE -> RESTAURANT_NAME/BRAND_NAME -> PORTION_CONTEXT -> CONFIRMATION`. Reasoning decides which states are needed and skips known fields.
- **D-45:** Ask one targeted question per uncertain segment/group. Identity/detail questions happen one at a time; simple confirmations can be grouped compactly.
- **D-46:** Free text parsing is hybrid. Rules/buttons handle exact choices; messy text is parsed with structured LLM output using `google/gemini-3.1-flash-lite`, falling back to `google/gemini-3.5-flash`.
- **D-47:** Always show final meal confirmation before DB write after choices/interview. User can confirm or edit.
- **D-48:** Confirmation edits support both item-specific targeted edit and free-text bulk correction. Show updated confirmation again after edits.
- **D-49:** If user says all wrong, use photo-aware correction first: reference the segment/group and brief evidence, ask what it is, then follow dynamic backbone questions only as needed.
- **D-50:** Postgres DB is source of truth for interview state. PTB context/cache is optional only.
- **D-51:** If user ignores an interview, send one reminder after configurable delay, then leave pending. No hard expiry in v1.
- **D-52:** Final confirmation nutrition display is adaptive: show nutrition for verified/known items when derivable; hide or flag uncertain estimates.
- **D-53:** Interview tone is brief plus context: one short evidence/context sentence, then choices or free-text prompt.
- **D-54:** After final confirmation and write, bot sends a final logged result message.

### `/fix` Correction Flow
- **D-55:** Support both `/fix <entry_id>` and bare `/fix` showing recent entries/items with buttons.
- **D-56:** `/fix` can correct full line item data: identity, quantity, components, source/brand, and detail. Only identity correction invalidates a FoodVisual.
- **D-57:** Identity correction invalidates only the linked FoodVisual for that DiaryEntry/segment. Do not mass-invalidate other visuals.
- **D-58:** `/fix` uses both free-text correction and dynamic interview. Show current logged item, quantity, and brief reasoning if available; ask what is wrong; confirm before mutation.
- **D-59:** Corrected visual write-back happens only if visually useful. Store `visual_learning_eligible` and reason.
- **D-60:** Append a correction event rather than overwriting without history. Capture previous/new identity, quantity, components/source, visual invalidation, new visual write, timestamp, trace id, and optional reason.
- **D-61:** Quantity-only fixes recompute nutrition immediately if enough data exists; otherwise mark `NEEDS_GROUNDING` or `needs_nutrition_derivation`. Do not invalidate FoodVisual.
- **D-62:** If corrected food does not exist, ask enough questions first, then create an unverified/needs-grounding FoodItem if nutrition remains incomplete.
- **D-63:** `/fix` confirmation shows both a side-effect diff before apply and updated meal summary after apply.
- **D-64:** Cancelling `/fix` leaves original entry unchanged. No invalidation or nutrition change occurs before final confirm.

### Langfuse And Audit
- **D-65:** Incorporate Langfuse in Phase 4 as optional tracing. Missing env disables tracing; Langfuse outage must not block the pipeline.
- **D-66:** App DB remains source of truth. Store compact structured decision state and optional `trace_id`; do not build a custom observability dashboard in Phase 4.
- **D-67:** Trace spans should cover meal-level reasoning, retry, choice/interview prompt generation, user answer handling, correction, and write-back.
- **D-68:** Researcher must verify Langfuse image capture behavior for multimodal OpenAI-compatible calls. If automatic, use default behavior. If not, add config for metadata-only default and optional local image payload capture.
- **D-69:** Do not ask models for hidden chain-of-thought. Ask for visible evidence, missing evidence, decision rationale, gate reason, and confidence scores.

### Crash Recovery And Janitor
- **D-70:** Janitor resets stale machine-stage meals to the last incomplete stage, not always `PENDING`.
- **D-71:** Stale timeout is 5 minutes for active machine stages; janitor runs every 2 minutes.
- **D-72:** Machine-stage stale statuses are `DETECTING`, `SEGMENTING`, `EMBEDDING`, `MATCHING`, and `REASONING`. `PENDING`, `INTERVIEWING`, `COMPLETED`, and `FAILED` are not machine-stage stale.
- **D-73:** Use global janitor recovery attempts max 3, while individual stages/calls keep their own retry budgets. After global recovery attempts are exhausted, mark `FAILED`.
- **D-74:** Store Telegram message IDs for interactive/editable messages and sent flags for simple notifications to avoid duplicate spam on recovery.
- **D-75:** After 3 failed machine-stage recoveries, notify user once. Active interview/user states are not janitor-failed.
- **D-76:** Janitor should use both stored stage metadata and artifact inference; artifact inference wins if stored state is stale.
- **D-77:** Keep committed crops, embeddings, and match results. Delete only orphan files. Discard invalid/incomplete reasoning drafts; keep interview drafts once a user-facing question was sent.
- **D-78:** Janitor runs via FastAPI APScheduler. Single API worker remains important.
- **D-79:** `/retry` is deferred. In Phase 4, failed machine-stage meals get a failure notice; user can send the photo again.

### the agent's Discretion
- The planner may choose exact storage shape for match results, meal-level reasoning JSON, correction events, and interview sessions, as long as the source-of-truth and recovery decisions above hold.
- The planner may keep Phase 4 in the current bot polling topology or do a low-risk extraction only if it clearly reduces complexity.
- The planner may choose exact top-match floor, stage retry counts, and nutrition-derivation status names.

### Deferred Ideas (OUT OF SCOPE)
## Deferred Ideas

- Full SearXNG/Firecrawl grounding loop belongs to Phase 5; Phase 4 may only store `NEEDS_GROUNDING`.
- Full observability project, custom dashboards, per-stage timing/cost reporting beyond optional Langfuse trace IDs remains v2/OPS-02.
- `/retry <meal_id>` is deferred.
- Dedicated worker service extraction is deferred unless planner finds a very low-risk improvement.
- Promotion of repeated additive details into durable FoodItem profile/aliases/components can come after deployed learning proves the pattern.
- Action taxonomy may expand after real testing; Phase 4 should keep it evolvable.
</user_constraints>

<phase_requirements>
## Phase Requirements [VERIFIED: codebase grep]

| ID | Description | Research Support |
|----|-------------|------------------|
| REASON-01 | Below-threshold segments trigger LLM reasoning after match. [VERIFIED: codebase grep] | Summary, Architecture Patterns Pattern 1, Code Examples 1, Common Pitfalls 1 and 2. [CITED: https://openrouter.ai/docs/guides/features/structured-outputs] [CITED: https://openrouter.ai/google/gemini-3.5-flash/api] |
| REASON-02 | Reasoning emits top-3 candidates with rationale and confidence, not one guess. [VERIFIED: codebase grep] | Summary, Standard Stack, Architecture Patterns Pattern 1, Don't Hand-Roll, Common Pitfalls 1. [VERIFIED: codebase grep] [CITED: https://openrouter.ai/docs/guides/features/structured-outputs] |
| REASON-03 | Escalation must use margin plus vector similarity, not self-confidence alone. [VERIFIED: codebase grep] | Summary, Architecture Patterns Pattern 1, Common Pitfalls 1, Security Domain. [VERIFIED: codebase grep] [ASSUMED] |
| REASON-04 | Persist reasoning trace on `MealSegment.ai_reasoning`. [VERIFIED: codebase grep] | Summary, Architecture Patterns Pattern 2, Validation Architecture, Security Domain. [VERIFIED: codebase grep] |
| PIPELINE-01 | Segments continue independently with bounded async parallelism and meal-level completion gating. [VERIFIED: codebase grep] | Summary, Architecture Patterns Pattern 1, Environment Availability, Common Pitfalls 2 and 4. [VERIFIED: codebase grep] [ASSUMED] |
| INTERVIEW-01 | Low-confidence items start a Telegram interview session. [VERIFIED: codebase grep] | Summary, Standard Stack, Architecture Patterns Pattern 2, Code Examples 2. [CITED: https://docs.python-telegram-bot.org/en/v22.7/telegram.ext.conversationhandler.html] [CITED: https://docs.python-telegram-bot.org/en/stable/telegram.ext.basepersistence.html] |
| INTERVIEW-02 | Interview follows the structured backbone flow. [VERIFIED: codebase grep] | Summary, Architecture Patterns Pattern 2, Code Examples 2, Common Pitfalls 3. [VERIFIED: codebase grep] |
| INTERVIEW-03 | Interview answers create/update `FoodItem`; packaged/restaurant answers support minimal re-grounding preparation. [VERIFIED: codebase grep] | Summary, Architecture Patterns Pattern 2, Open Questions 2, Security Domain. [VERIFIED: codebase grep] [CITED: https://openrouter.ai/docs/guides/features/tool-calling] [ASSUMED] |
| INTERVIEW-04 | Best-effort unresolved post-interview writes are allowed; no infinite loop. [VERIFIED: codebase grep] | Summary, Common Pitfalls 5, Validation Architecture. [VERIFIED: codebase grep] [ASSUMED] |
| INTERVIEW-05 | User can override an existing identification. [VERIFIED: codebase grep] | Summary, Architecture Patterns Pattern 3, Common Pitfalls 5, Security Domain. [VERIFIED: codebase grep] |
| INTERVIEW-06 | `USER_CORRECTED` invalidates only the offending `FoodVisual` and writes a corrected one. [VERIFIED: codebase grep] | Summary, Architecture Patterns Pattern 3, Common Pitfalls 5, Security Domain. [VERIFIED: codebase grep] |
| INFRA-04 | Janitor resets stale `*ING` rows and eventually marks `FAILED`. [VERIFIED: codebase grep] | Summary, Standard Stack, Architecture Patterns Pattern 4, Code Examples 3, Common Pitfalls 4. [CITED: https://apscheduler.readthedocs.io/en/stable/userguide.html] [VERIFIED: codebase grep] |
</phase_requirements>

## Project Constraints (from AGENTS.md) [VERIFIED: codebase grep]

- Keep the locked application stack: Python, FastAPI, Postgres plus pgvector, `python-telegram-bot`, APScheduler, and a single `docker-compose.yml`. [VERIFIED: codebase grep]
- Keep OpenRouter as the only model gateway, with OpenAI SDK-compatible chat/tool calls and raw `httpx` where the SDK surface is insufficient. [VERIFIED: codebase grep]
- Respect the single-user security model: shared-secret ingest auth and one pinned Telegram chat ID. [VERIFIED: codebase grep]
- Preserve the current bot-owned polling topology unless a low-risk extraction clearly reduces complexity. [VERIFIED: codebase grep]
- Prefer `rtk`-prefixed shell commands in downstream plans because the repo explicitly requires that wrapper. [VERIFIED: codebase grep]
- `GEMINI.md` is absent, so there are no additional Gemini-specific local instructions beyond `AGENTS.md` and the phase context. [VERIFIED: codebase grep]
- No project-specific skills are defined in `.agents/skills` or `.codex/skills`; downstream planning should follow repo and GSD conventions rather than hidden local skill rules. [VERIFIED: codebase grep]

## Summary

Phase 4 is not just a new worker stage. The current runtime already handles `PENDING -> DETECTING -> SEGMENTING -> EMBEDDING -> MATCHING`, then stops at an unresolved `REASONING` handoff with a placeholder Telegram note; there are no runtime `InterviewSession`, `InterviewMessage`, correction-event, or meal-level reasoning models in the actual SQLAlchemy layer or initial migration, even though the schema draft files describe them. [VERIFIED: codebase grep] The planner should therefore treat this phase as the first real pipeline-state expansion: new durable state surfaces, richer quantity persistence than `portion_bucket`, interactive Telegram state, correction history, and janitor metadata all need to land before the reasoning loop is trustworthy. [VERIFIED: codebase grep]

The architecture should stay aligned with the existing worker pattern: per-segment embedding and vector matching can run in bounded async parallelism, but reasoning remains one meal-level multimodal call that sees the original meal image, stable ordered segment crops, and persisted top vector candidates. [VERIFIED: codebase grep] [CITED: https://ai.google.dev/gemini-api/docs/image-understanding] [CITED: https://openrouter.ai/google/gemini-3.5-flash/api] The reasoning call should always use strict JSON schema plus app-side validation, because OpenRouter structured outputs guarantee response shape, not business-rule correctness; invalid or contradictory outputs must retry once and then fail closed to `FAILED_UNCLEAR` or `NEEDS_SCHEMA_REVIEW`, never to a diary write. [CITED: https://openrouter.ai/docs/guides/features/structured-outputs] [VERIFIED: codebase grep]

The sparsest documentation area is the multi-signal confidence gate. Current official docs support structured outputs, multi-image prompts, and tool wiring, but they do not prescribe a nutrition-specific escalation formula for Gemini 3.5 Flash. [CITED: https://openrouter.ai/docs/guides/features/structured-outputs] [CITED: https://openrouter.ai/docs/guides/features/tool-calling] [CITED: https://ai.google.dev/gemini-api/docs/image-understanding] The safest planning stance is to make the gate deterministic and inspectable: compare vector similarity, candidate margin, missing evidence, and nutrition-impact uncertainty explicitly instead of trusting the LLM’s self-confidence field. [VERIFIED: codebase grep] [ASSUMED]

**Primary recommendation:** Plan Phase 4 as four tightly-coupled waves: schema and state surfaces, meal-level reasoning plus gate, Telegram interview and `/fix`, then janitor and optional Langfuse tracing. [VERIFIED: codebase grep] [ASSUMED]

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|--------------|----------------|-----------|
| Per-segment embed/match fan-out | API / Backend | Database / Storage | The bot worker owns semaphore-bounded task orchestration while Postgres stores segment embeddings and vector candidates. [VERIFIED: codebase grep] |
| Meal-level reasoning call | API / Backend | Database / Storage | The app assembles the multimodal request from stored artifacts and persists the structured result back onto meal and segment records. [VERIFIED: codebase grep] [CITED: https://openrouter.ai/google/gemini-3.5-flash/api] |
| Telegram interview routing | API / Backend | Database / Storage | PTB handles updates and buttons, but Postgres must remain the source of truth for interview progress and final correction state. [VERIFIED: codebase grep] [CITED: https://docs.python-telegram-bot.org/en/v22.7/telegram.ext.conversationhandler.html] |
| Final transactional meal write | API / Backend | Database / Storage | Only the backend can bundle `DiaryEntry`, `FoodVisual`, invalidation, correction history, and meal completion into one commit. [VERIFIED: codebase grep] |
| Crash recovery and janitor | API / Backend | Database / Storage | APScheduler runs the janitor in-process, while recovery decisions depend on persisted statuses, artifacts, and retry counters. [VERIFIED: codebase grep] [CITED: https://apscheduler.readthedocs.io/en/stable/userguide.html] |
| Optional tracing | API / Backend | External Observability | Langfuse can wrap OpenAI-compatible calls directly, but tracing must remain non-blocking and non-authoritative relative to app DB state. [CITED: https://langfuse.com/integrations/gateways/openrouter] [CITED: https://langfuse.com/integrations/model-providers/openai-py] |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `openai` | `1.55.3` repo pin; `2.38.0` current on PyPI. [VERIFIED: codebase grep] [VERIFIED: PyPI] | OpenRouter-compatible chat client for reasoning and parser calls | Keep the repo pin for this phase because the current code already wraps the v1 client, and Phase 4 complexity does not justify an SDK-major upgrade. [VERIFIED: codebase grep] [CITED: https://langfuse.com/integrations/model-providers/openai-py] |
| `httpx` | `0.27.2` repo pin; `0.28.1` current on PyPI. [VERIFIED: codebase grep] [VERIFIED: PyPI] | Raw HTTP for embeddings and any thin future grounding stub | This remains the right low-level surface for exact multimodal payload control and retry classification. [VERIFIED: codebase grep] [CITED: https://openrouter.ai/docs/api-reference/overview] |
| `python-telegram-bot` | `22.7` repo pin and current on PyPI. [VERIFIED: codebase grep] [VERIFIED: PyPI] | Interview and correction UX | PTB already owns the bot runtime, and `ConversationHandler` plus inline keyboards fit the structured question flow required here. [CITED: https://docs.python-telegram-bot.org/en/v22.7/telegram.ext.conversationhandler.html] [CITED: https://docs.python-telegram-bot.org/en/stable/telegram.inlinekeyboardbutton.html] |
| `APScheduler` | `3.10.4` repo pin; `3.11.2` current on PyPI. [VERIFIED: codebase grep] [VERIFIED: PyPI] | In-process janitor scheduling | The repo already starts `AsyncIOScheduler` in FastAPI lifespan, and the phase only needs a careful job configuration, not a scheduler swap. [VERIFIED: codebase grep] [CITED: https://apscheduler.readthedocs.io/en/stable/userguide.html] |
| `pydantic` | `2.10.3` repo pin; `2.13.4` current on PyPI. [VERIFIED: codebase grep] [VERIFIED: PyPI] | App-side validation of reasoning and parser outputs | Strict schema at the provider boundary still needs local validation for cross-field invariants and nutrition-impact rules. [VERIFIED: codebase grep] [CITED: https://openrouter.ai/docs/guides/features/structured-outputs] |
| `SQLAlchemy[asyncio]` | `2.0.36` repo pin. [VERIFIED: codebase grep] | Transactional state machine, final writes, correction history | The phase needs richer transactions and new tables, but the existing async ORM layer is already the canonical persistence surface. [VERIFIED: codebase grep] |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `tenacity` | `9.0.0` repo pin; `9.1.4` current on PyPI. [VERIFIED: codebase grep] [VERIFIED: PyPI] | Bounded retries for model and grounding-adjacent calls | Use only for retryable transport and provider errors; never retry validation failures or contradictory model outputs blindly. [VERIFIED: codebase grep] [CITED: https://openrouter.ai/docs/api-reference/overview] |
| `langfuse` | `4.7.0` current on PyPI; not currently pinned in repo. [VERIFIED: PyPI] [VERIFIED: codebase grep] | Optional tracing for reasoning, interview, and correction spans | Use only if Phase 4 enables tracing; self-hosted multimodal capture requires media object storage configuration. [CITED: https://langfuse.com/integrations/model-providers/openai-py] [CITED: https://langfuse.com/docs/observability/features/multi-modality] |
| `orjson` | `3.10.12` repo pin; `3.11.9` current on PyPI. [VERIFIED: codebase grep] [VERIFIED: PyPI] | Fast serialization of structured reasoning payloads | Useful if the planner stores JSON state as JSONB or serialized text and wants deterministic compact payloads. [VERIFIED: codebase grep] [ASSUMED] |
| `pydantic-settings` | `2.7.0` repo pin; `2.14.1` current on PyPI. [VERIFIED: codebase grep] [VERIFIED: PyPI] | New Phase 4 config flags | Extend the existing `Settings` class for models, semaphore size, janitor interval, reminder delay, and Langfuse toggles. [VERIFIED: codebase grep] |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Direct OpenRouter plus app-owned orchestration | LangGraph | LangGraph could model checkpoints, but the repo already has DB-owned statuses and transactional boundaries; adding a second workflow state machine would raise Phase 4 risk. [VERIFIED: codebase grep] [ASSUMED] |
| `ConversationHandler` plus DB source of truth | Hand-rolled update routing | PTB already solves callback routing, fallback flow, and persistence hooks; custom routing would recreate fragile state machinery. [CITED: https://docs.python-telegram-bot.org/en/v22.7/telegram.ext.conversationhandler.html] |
| JSONB-backed structured reasoning state | Opaque free-text blobs | Free-text is harder to recover from, validate, diff, and inspect during `/fix` and janitor recovery. [VERIFIED: codebase grep] [ASSUMED] |
| Optional Langfuse SDK wrapper | OpenRouter Broadcast only | Broadcast is lower effort, but the SDK wrapper gives richer app-level spans and multimodal handling; Broadcast is acceptable only if the planner wants zero-code tracing. [CITED: https://langfuse.com/integrations/gateways/openrouter] [ASSUMED] |

**Installation:** No mandatory new package is required for Phase 4 beyond the existing repo pins. If optional tracing is enabled in-scope, add `langfuse==4.7.0`. [VERIFIED: codebase grep] [VERIFIED: PyPI]

## Package Legitimacy Audit

> **Required** because optional Phase 4 tracing may add one new external package.

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| `langfuse` | PyPI. [VERIFIED: PyPI] | Current release uploaded `2026-05-27`. [VERIFIED: PyPI] | Not checked from an authoritative registry source. [ASSUMED] | Not listed in PyPI metadata; official docs are at `langfuse.com`. [VERIFIED: PyPI] [CITED: https://langfuse.com/integrations/model-providers/openai-py] | `OK` with info flag `NO_REPO`. [VERIFIED: slopcheck] | Approved as optional, but self-hosted media capture must be gated on Langfuse storage config. [CITED: https://langfuse.com/docs/observability/features/multi-modality] |

**Packages removed due to slopcheck [SLOP] verdict:** none. [VERIFIED: slopcheck]
**Packages flagged as suspicious [SUS]:** none. [VERIFIED: slopcheck]

## Architecture Patterns

### System Architecture Diagram

```text
MealLog in MATCHING
    |
    v
claim meal row (worker loop)
    |
    +--> bounded async per-segment fan-out (max 4 default)
    |      |- ensure segment.embedding exists
    |      |- fetch top-3 FoodVisual candidates excluding invalidated rows
    |      `- persist candidate snapshot per segment
    |
    v
if any segment failed after retry budget
    |- persist failure metadata
    `- janitor or FAILED path
    |
    v
meal-level reasoning call
    |- input: original meal image
    |- input: stable segment_1..N crops
    |- input: top candidates + similarity + identity metadata
    |- output: structured actions, evidence, quantities, meal_state
    `- persist segment + meal reasoning state
    |
    +--> READY_TO_WRITE
    |      `- final DB transaction:
    |           DiaryEntries + eligible FoodVisuals + invalidations + correction events
    |
    +--> PENDING_CHOICE / PENDING_INTERVIEW
    |      |- PTB buttons / free text
    |      |- DB-owned InterviewSession + InterviewMessage + sent message ids
    |      `- final confirmation -> same DB transaction
    |
    +--> NEEDS_SCHEMA_REVIEW / FAILED_UNCLEAR
    |      `- fail closed, notify once
    |
    v
post-commit Telegram result send
    |
    v
APScheduler janitor
    |- scans stale machine stages
    |- infers last safe stage from artifacts
    `- resets or marks FAILED after 3 recoveries
```

### Recommended Project Structure

```text
app/
├── config.py                    # Phase 4 env flags and model ids
├── models/
│   ├── meal_log.py              # coarse status + meal-level reasoning summary refs
│   ├── meal_segment.py          # segment reasoning JSON + quantity refs
│   ├── interview_session.py     # new durable interview state [ASSUMED]
│   ├── interview_message.py     # new durable interview transcript [ASSUMED]
│   └── correction_event.py      # new correction history + side effects [ASSUMED]
├── services/
│   ├── reasoning_service.py     # meal-level prompt assembly, validation, gate
│   ├── interview_service.py     # session transitions and final confirmation
│   ├── correction_service.py    # `/fix` diff, invalidation, write-back
│   ├── recovery_service.py      # janitor inference and reset logic
│   └── taxonomy.py              # editable specificity taxonomy loader [ASSUMED]
bot/
├── main.py                      # PTB Application setup + concurrent_updates guard
├── polling.py                   # stage claim loops for matching, reasoning, reminders
├── handlers.py                  # `/fix`, callbacks, free-text dispatch
└── messages.py                  # concise evidence-first prompts and confirmations
tests/
├── test_reasoning_flow.py       # gate, schema failure, ready-to-write flow [ASSUMED]
├── test_interview_flow.py       # choice, free text, final confirmation [ASSUMED]
├── test_fix_flow.py             # invalidation and correction history [ASSUMED]
└── test_janitor.py              # stale-stage reset and duplicate-notify guards [ASSUMED]
```

### Pattern 1: Persist Candidates First, Reason Once Per Meal

**What:** Run embed and match per segment with a semaphore, persist the top candidate snapshot for each segment, then make one meal-level reasoning call over the whole meal. [VERIFIED: codebase grep] [CITED: https://ai.google.dev/gemini-api/docs/image-understanding]

**When to use:** Use this for all meals that have at least one accepted segment, including all-matched meals, because Phase 4 reasoning is responsible for quantity, specificity, dedupe, and composite handling, not just unresolved cases. [VERIFIED: codebase grep]

**Example:**

```python
# Source: repo worker topology + OpenRouter structured-output docs
async def reason_meal(session, meal, settings):
    candidates = await load_persisted_segment_candidates(session, meal.id)
    ordered_segments = sorted(candidates, key=lambda item: item.segment_index)
    response = await llm_client.chat_completion(
        model=settings.REASONING_MODEL,
        messages=build_reasoning_prompt(meal.image_url, ordered_segments),
        response_format=reasoning_response_format(),
    )
    decision = parse_reasoning_payload(response)
    await persist_reasoning_state(session, meal, decision)
    return apply_reasoning_gate(meal, decision)
```

### Pattern 2: DB-Owned Interview State, Thin PTB Conversation State

**What:** Keep the actual interview source of truth in Postgres and use `ConversationHandler` only as the routing shell for callbacks and free text. [VERIFIED: codebase grep] [CITED: https://docs.python-telegram-bot.org/en/stable/telegram.ext.basepersistence.html] [CITED: https://docs.python-telegram-bot.org/en/v22.7/telegram.ext.conversationhandler.html]

**When to use:** Use this for all unresolved choice and interview paths, including `/fix`, because the bot process can restart and the janitor must reconcile message sends and session states without trusting in-memory PTB context. [VERIFIED: codebase grep]

**Example:**

```python
# Source: PTB ConversationHandler + BasePersistence docs
application = (
    Application.builder()
    .token(settings.TELEGRAM_BOT_TOKEN)
    .concurrent_updates(False)
    .persistence(postgres_persistence)
    .build()
)

interview_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(start_interview, pattern="^choice:")],
    states={
        FOOD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_food_name)],
        SOURCE_TYPE: [CallbackQueryHandler(receive_source_type, pattern="^source:")],
        CONFIRMATION: [CallbackQueryHandler(receive_confirmation, pattern="^confirm:")],
    },
    fallbacks=[CommandHandler("cancel", cancel_interview)],
    name="meal_interview",
    persistent=True,
)
```

### Pattern 3: Final Write Is the Only Mutation Point for Learning

**What:** Persist reasoning and interview state immediately, but delay `DiaryEntry`, `FoodVisual`, and invalidation mutations until final meal confirmation resolves. [VERIFIED: codebase grep]

**When to use:** Use this for both normal interview completion and `/fix`, because only confirmed identity changes should poison or correct the visual corpus. [VERIFIED: codebase grep]

**Example:**

```python
# Source: repo transaction pattern + Phase 4 decisions
async with session.begin():
    apply_diary_entries(meal_resolution)
    apply_food_visual_writes(meal_resolution)
    apply_visual_invalidations(correction_plan)
    append_correction_events(correction_plan)
    meal.processing_status = MealProcessingStatus.COMPLETED
```

### Pattern 4: Single-Instance Janitor With Artifact-First Recovery

**What:** Run one APScheduler janitor job that checks stale machine-stage meals, infers the last safe stage from persisted artifacts, and either resets the stage or marks `FAILED` after global recovery exhaustion. [VERIFIED: codebase grep] [CITED: https://apscheduler.readthedocs.io/en/stable/userguide.html]

**When to use:** Use this for `DETECTING`, `SEGMENTING`, `EMBEDDING`, `MATCHING`, and `REASONING` only, never for active interview states. [VERIFIED: codebase grep]

**Example:**

```python
# Source: APScheduler job configuration guidance
scheduler.add_job(
    run_meal_janitor,
    "interval",
    minutes=2,
    id="meal-janitor",
    max_instances=1,
    coalesce=True,
    misfire_grace_time=300,
)
```

### Anti-Patterns to Avoid

- **Single-score gating:** Do not auto-confirm from one opaque LLM confidence score. Use explicit candidate margin, similarity, missing evidence, and nutrition-impact checks. [VERIFIED: codebase grep] [ASSUMED]
- **Partial writes before final confirmation:** Do not append `FoodVisual` rows for matched siblings while another segment is still unresolved. [VERIFIED: codebase grep]
- **Large callback payloads:** Do not encode structured state inside Telegram callback payloads; callback data is limited to 1-64 UTF-8 bytes. [CITED: https://docs.python-telegram-bot.org/en/stable/telegram.inlinekeyboardbutton.html]
- **Memory-only interviews:** Do not let interview progress live only in PTB context or in-flight messages. [VERIFIED: codebase grep] [CITED: https://docs.python-telegram-bot.org/en/stable/telegram.ext.basepersistence.html]

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Telegram state routing | Custom callback parser and ad hoc state map | `ConversationHandler` plus `BasePersistence` or DB-backed rebuild logic | PTB already covers structured states, fallback routing, and persistence integration. [CITED: https://docs.python-telegram-bot.org/en/v22.7/telegram.ext.conversationhandler.html] [CITED: https://docs.python-telegram-bot.org/en/stable/telegram.ext.basepersistence.html] |
| Retry logic | Homegrown exponential backoff | `tenacity` | The repo already uses `tenacity`, and bounded retries are required at several model and network boundaries. [VERIFIED: codebase grep] |
| Multimodal tracing upload | Custom media extraction and blob store protocol | Langfuse SDK multimodal support | Langfuse already auto-detects base64 data URIs and external image URLs. [CITED: https://langfuse.com/docs/observability/features/multi-modality] |
| Vector ranking | Python-side nearest-neighbor loops | pgvector HNSW + SQL query ordering | The schema already depends on pgvector and invalidation filtering, and DB-level search is simpler to recover and audit. [VERIFIED: codebase grep] |
| Tool-call schema | Bespoke LLM-to-tool pseudo-protocol | OpenRouter `tools=` interface | OpenRouter already standardizes tool calling across providers; Phase 4 only needs thin stubs and action hints. [CITED: https://openrouter.ai/docs/guides/features/tool-calling] |

**Key insight:** This phase is risky because it touches persistence, human interaction, and recovery simultaneously. Reusing the framework pieces that already own routing, retries, tracing, and vector search keeps the planner focused on the actual product logic: meal reasoning, question targeting, and safe learning mutation. [VERIFIED: codebase grep] [ASSUMED]

## Common Pitfalls

### Pitfall 1: Treating LLM Self-Confidence as the Gate
**What goes wrong:** The model sounds confident, but the top candidate disagrees with the vector signal or still lacks nutrition-relevant detail. [VERIFIED: codebase grep]
**Why it happens:** Official docs explain structured outputs and reasoning controls, but they do not provide a nutrition-specific escalation formula. [CITED: https://openrouter.ai/docs/guides/features/structured-outputs] [CITED: https://openrouter.ai/google/gemini-3.5-flash/api]
**How to avoid:** Make the gate deterministic and inspectable with separate fields for similarity, margin, evidence, and nutrition impact. [VERIFIED: codebase grep] [ASSUMED]
**Warning signs:** `AUTO_CONFIRM` appears when `similarity < 0.90`, when top-1 and top-2 are near-tied, or when the model explicitly cites missing evidence. [VERIFIED: codebase grep] [ASSUMED]

### Pitfall 2: Losing Meal Context by Reasoning Per Segment
**What goes wrong:** Duplicate items are double-counted, composite dishes get split badly, and portions ignore the whole plate context. [VERIFIED: codebase grep]
**Why it happens:** Per-segment reasoning cannot see the meal-level arrangement or sibling evidence. [VERIFIED: codebase grep]
**How to avoid:** Persist per-segment candidates, then reason once over the original meal image plus ordered crops. [VERIFIED: codebase grep] [CITED: https://ai.google.dev/gemini-api/docs/image-understanding]
**Warning signs:** Multiple `segment_n` outputs describe the same visible food, or the same curry is both merged and split in one decision payload. [VERIFIED: codebase grep] [ASSUMED]

### Pitfall 3: Letting PTB Concurrency Fight Conversation State
**What goes wrong:** Buttons and free-text replies race, the wrong session state advances, or persistence replays stale transitions. [CITED: https://docs.python-telegram-bot.org/en/v22.7/telegram.ext.conversationhandler.html] [CITED: https://docs.python-telegram-bot.org/en/stable/telegram.ext.basepersistence.html]
**Why it happens:** `ConversationHandler` expects updates to be processed one by one, and persistence hooks can race when concurrent updates are enabled. [CITED: https://docs.python-telegram-bot.org/en/v22.7/telegram.ext.conversationhandler.html] [CITED: https://docs.python-telegram-bot.org/en/stable/telegram.ext.basepersistence.html]
**How to avoid:** Set `concurrent_updates(False)`, keep callback payloads short, and derive the canonical next step from DB state before mutating anything. [CITED: https://docs.python-telegram-bot.org/en/v22.7/telegram.ext.conversationhandler.html] [CITED: https://docs.python-telegram-bot.org/en/stable/telegram.inlinekeyboardbutton.html] [ASSUMED]
**Warning signs:** Two answers move the same session twice, callback payloads exceed 64 bytes, or restart recovery loses the active confirmation step. [CITED: https://docs.python-telegram-bot.org/en/stable/telegram.inlinekeyboardbutton.html] [ASSUMED]

### Pitfall 4: Janitor Jobs Replaying or Overlapping
**What goes wrong:** A restarted app runs multiple missed janitor passes, or a second janitor invocation collides with a still-running first pass. [CITED: https://apscheduler.readthedocs.io/en/stable/userguide.html]
**Why it happens:** APScheduler treats overlapping runs as misfires unless configured; missed executions can also replay after downtime. [CITED: https://apscheduler.readthedocs.io/en/stable/userguide.html]
**How to avoid:** Add the janitor with `max_instances=1`, `coalesce=True`, and an explicit `misfire_grace_time`, and keep recovery idempotent. [CITED: https://apscheduler.readthedocs.io/en/stable/userguide.html] [ASSUMED]
**Warning signs:** Duplicate failure notices, more than one recovery attempt increment per interval, or stage resets that ignore persisted embeddings and match artifacts. [VERIFIED: codebase grep] [ASSUMED]

### Pitfall 5: Poisoning the Visual Library During `/fix`
**What goes wrong:** Quantity-only edits invalidate visuals, or one corrected entry invalidates many unrelated visuals for the same food. [VERIFIED: codebase grep]
**Why it happens:** Correction semantics are broader than similarity semantics, and the repo currently has only a boolean invalidation field with no correction history tables. [VERIFIED: codebase grep]
**How to avoid:** Separate identity corrections from quantity/detail edits, append correction events, and scope invalidation to the offending `DiaryEntry`-linked visual only. [VERIFIED: codebase grep]
**Warning signs:** `is_invalidated=true` appears after a quantity-only fix, or future meals lose good matches after one narrow correction. [VERIFIED: codebase grep] [ASSUMED]

### Pitfall 6: Assuming Prompt Caching Is a Guaranteed Win
**What goes wrong:** The planner designs the reasoning flow around cache hits that do not materialize for the exact model or request shape. [CITED: https://openrouter.ai/docs/guides/best-practices/prompt-caching]
**Why it happens:** OpenRouter documents Gemini caching behavior generically and warns that only certain Gemini models support caching, while exact `google/gemini-3.5-flash` cache behavior is not spelled out on the model page. [CITED: https://openrouter.ai/docs/guides/best-practices/prompt-caching] [CITED: https://openrouter.ai/google/gemini-3.5-flash/api]
**How to avoid:** Make prompts cache-friendly, but treat caching as opportunistic until a live smoke proves non-zero cached tokens for the pinned model and prompt shape. [CITED: https://openrouter.ai/docs/guides/best-practices/prompt-caching] [ASSUMED]
**Warning signs:** No `cached_tokens` in usage, dynamic tails placed inside the first cached system block, or planning tasks that depend on cache economics to be acceptable. [CITED: https://openrouter.ai/docs/guides/best-practices/prompt-caching] [ASSUMED]

## Code Examples

Verified patterns from official sources:

### Strict Meal-Level Reasoning Call

```python
# Source: https://openrouter.ai/docs/guides/features/structured-outputs
response = await client.chat.completions.create(
    model="google/gemini-3.5-flash",
    messages=build_reasoning_messages(meal_image, segment_parts),
    response_format={
        "type": "json_schema",
        "json_schema": {
            "name": "meal_reasoning",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["meal_state", "segments"],
                "properties": {
                    "meal_state": {"type": "string"},
                    "segments": {"type": "array"},
                },
            },
        },
    },
)
```

### PTB Interview Shell With Persistent State

```python
# Source: https://docs.python-telegram-bot.org/en/v22.7/telegram.ext.conversationhandler.html
# Source: https://docs.python-telegram-bot.org/en/stable/telegram.ext.basepersistence.html
application = (
    Application.builder()
    .token(token)
    .concurrent_updates(False)
    .persistence(persistence)
    .build()
)

handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(start_interview, pattern="^choice:")],
    states={CONFIRMATION: [CallbackQueryHandler(confirm, pattern="^confirm:")]},
    fallbacks=[CommandHandler("cancel", cancel)],
    name="meal_interview",
    persistent=True,
)
```

### Single-Instance Janitor Job

```python
# Source: https://apscheduler.readthedocs.io/en/stable/userguide.html
scheduler.add_job(
    run_meal_janitor,
    "interval",
    minutes=2,
    id="meal-janitor",
    max_instances=1,
    coalesce=True,
    misfire_grace_time=300,
)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Similarity-only auto-resolution with unresolved handoff to `REASONING` | Similarity becomes one prior signal inside a meal-level multimodal reasoning gate. [VERIFIED: codebase grep] | Phase 4 context locked on 2026-05-28. [VERIFIED: codebase grep] | Planner must add candidate snapshot persistence and explicit gate fields. [VERIFIED: codebase grep] |
| `portion_bucket` as the only quantity model | Quantity persistence should capture unit, amount or range, evidence, confidence, and components. [VERIFIED: codebase grep] | Phase 4 context locked on 2026-05-28. [VERIFIED: codebase grep] | This phase needs a schema migration, not just prompt changes. [VERIFIED: codebase grep] |
| Ephemeral unresolved note with no interview tables | Durable DB-owned interview sessions, messages, reminder state, and final confirmation loop. [VERIFIED: codebase grep] | Phase 4 context and AI-SPEC. [VERIFIED: codebase grep] | Planner must allocate schema and handler work before UX polish. [VERIFIED: codebase grep] |
| Optional observability deferred entirely | Optional Langfuse spans are acceptable now, but custom dashboards remain deferred. [VERIFIED: codebase grep] | Phase 4 context and roadmap note. [VERIFIED: codebase grep] | Trace IDs can land in state now without committing to a v2 observability project. [VERIFIED: codebase grep] |

**Deprecated/outdated:**
- `MealSegment.ai_reasoning` as a plain text dump is too weak for the final Phase 4 state machine if the planner needs structured recovery, `/fix`, and audit behavior. [VERIFIED: codebase grep] [ASSUMED]
- Callback payloads that carry business state directly are outdated for PTB 22.x interview flows because callback data is short and DB state is already the authoritative source. [CITED: https://docs.python-telegram-bot.org/en/stable/telegram.inlinekeyboardbutton.html] [VERIFIED: codebase grep]
- Designing around unconditional Gemini prompt caching is outdated for this phase because OpenRouter documents model-specific limitations and explicit breakpoints. [CITED: https://openrouter.ai/docs/guides/best-practices/prompt-caching]

## Assumptions Log

> List all claims tagged `[ASSUMED]` in this research. The planner and discuss-phase use this section to identify decisions that need user confirmation before execution.

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The safest Phase 4 gate is a deterministic rule over similarity, candidate margin, missing evidence, and nutrition impact rather than a looser learned heuristic. | Summary, Common Pitfalls | Planner may under- or over-escalate interviews if a different gate shape is preferred. |
| A2 | `MealSegment.ai_reasoning` and the new meal-level reasoning surface should be JSONB-oriented rather than opaque text. | Standard Stack, Alternatives, Deprecated/outdated | Recovery and `/fix` may be harder if the planner intentionally keeps text blobs. |
| A3 | PTB should persist only minimal conversation routing state while domain truth lives in Postgres. | Architecture Patterns Pattern 2 | A richer PTB persistence implementation might be chosen instead, affecting scope and complexity. |
| A4 | The janitor job should use `coalesce=True`, `max_instances=1`, and `misfire_grace_time=300` as the practical Phase 4 defaults. | Architecture Patterns Pattern 4, Common Pitfalls 4 | Different deployment behavior could require tighter or looser scheduling semantics. |
| A5 | Gemini prompt caching for `google/gemini-3.5-flash` should be treated as opportunistic until live-tested. | Summary, Common Pitfalls 6 | If the model reliably caches in practice, the planner may be leaving cost savings unused; if it does not, this recommendation prevents a brittle dependency. |
| A6 | The optional Langfuse install should be `langfuse==4.7.0` if tracing is enabled now. | Standard Stack, Package Legitimacy Audit | If the team prefers the 3.x line from older planning artifacts, a pin decision is still needed before install. |

## Open Questions

1. **Does `google/gemini-3.5-flash` actually return prompt-cache hits for the intended reasoning prompt shape on OpenRouter?**
   - What we know: OpenRouter documents Gemini caching behavior, explicit `cache_control` breakpoints, and stable-opening-message sticky routing. [CITED: https://openrouter.ai/docs/guides/best-practices/prompt-caching]
   - What's unclear: The `google/gemini-3.5-flash` model page does not explicitly advertise cache support the way the general prompt-caching docs describe Gemini families. [CITED: https://openrouter.ai/google/gemini-3.5-flash/api]
   - Recommendation: Add one live smoke task in Wave 0 that checks `usage.prompt_tokens_details.cached_tokens` on two identical reasoning requests with a large static taxonomy block. [CITED: https://openrouter.ai/docs/guides/best-practices/prompt-caching] [ASSUMED]

2. **How minimal can the Phase 4 grounding stub be while still honoring `INTERVIEW-03`?**
   - What we know: The roadmap note says full SearXNG plus Firecrawl tool looping ships in Phase 5, but packaged and restaurant re-grounding must be stubbed or minimally wired before Phase 4 completes. [VERIFIED: codebase grep]
   - What's unclear: Whether the planner should implement only `NEEDS_GROUNDING` persistence and thin interfaces, or also a one-shot post-interview fetch for branded items. [VERIFIED: codebase grep]
   - Recommendation: Keep full iterative tool orchestration out of scope, but introduce stable request and result interfaces plus a minimal no-op or single-shot service boundary that Phase 5 can extend without schema churn. [VERIFIED: codebase grep] [ASSUMED]

3. **Should optional Langfuse multimodal capture be on by default in self-hosted mode?**
   - What we know: Langfuse auto-handles base64 data URIs and external URLs, but self-hosted multimodal attachments require `LANGFUSE_S3_MEDIA_UPLOAD_*` and a publicly resolvable bucket hostname. [CITED: https://langfuse.com/docs/observability/features/multi-modality]
   - What's unclear: Whether the operator wants image payloads uploaded at all in the local single-user deployment. [VERIFIED: codebase grep]
   - Recommendation: Default tracing to metadata-only when self-hosted media storage env vars are missing; expose an explicit opt-in toggle for image capture. [CITED: https://langfuse.com/docs/observability/features/multi-modality] [ASSUMED]

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python host runtime | Local tooling and install commands | ✓ | `3.14.4` | Use repo venv for project execution because the host version is newer than the repo guidance. [VERIFIED: local command] |
| Repo virtualenv Python | App and tests | ✓ | `3.13.12` | — [VERIFIED: local command] |
| Docker Engine | Compose stack and live Phase 4 smoke tests | ✓ | `29.4.0` | — [VERIFIED: local command] |
| Docker Compose | Stack orchestration | ✓ | `v5.1.2` | — [VERIFIED: local command] |
| `uv` | Optional package workflow | ✓ | Present at `/opt/homebrew/bin/uv` | Use `pip` and pinned `requirements.txt` if needed. [VERIFIED: local command] |
| Node.js | Existing Firecrawl and tooling ecosystem support | ✓ | `v20.20.2` | — [VERIFIED: local command] |
| `npm` | Existing tooling ecosystem support | ✓ | `10.8.2` | — [VERIFIED: local command] |
| `pytest` in repo venv | Optional test runner | ✗ | — | Use `python -m unittest`, which matches the current test suite style. [VERIFIED: local command] [VERIFIED: codebase grep] |
| `ctx7` CLI | Research-only documentation helper | ✗ | — | Official docs fallback worked; no implementation impact. [VERIFIED: local command] |

**Missing dependencies with no fallback:**
- None identified for Phase 4 planning. [VERIFIED: local command]

**Missing dependencies with fallback:**
- `.venv/bin/pytest` is missing, but the repo already uses `unittest`-style tests through the venv Python interpreter. [VERIFIED: local command] [VERIFIED: codebase grep]

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | Python `unittest` test suite driven from `.venv/bin/python`. [VERIFIED: codebase grep] [VERIFIED: local command] |
| Config file | None; test discovery is module-based. [VERIFIED: codebase grep] |
| Quick run command | `rtk .venv/bin/python -m unittest tests.test_match_flow -q` for current pipeline contracts; Phase 4 should add equivalent targeted modules. [VERIFIED: codebase grep] [ASSUMED] |
| Full suite command | `rtk .venv/bin/python -m unittest` [ASSUMED] |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| REASON-01 | Low-confidence meals call meal-level reasoning and persist the response | integration | `rtk .venv/bin/python -m unittest tests.test_reasoning_flow -q` | ❌ Wave 0 [ASSUMED] |
| REASON-02 | Reasoning returns top-3 candidates with explicit rationale fields | unit | `rtk .venv/bin/python -m unittest tests.test_reasoning_contract -q` | ❌ Wave 0 [ASSUMED] |
| REASON-03 | Gate combines similarity and candidate margin, not self-confidence alone | unit | `rtk .venv/bin/python -m unittest tests.test_reasoning_gate -q` | ❌ Wave 0 [ASSUMED] |
| REASON-04 | Segment reasoning trace persists on `MealSegment.ai_reasoning` | integration | `rtk .venv/bin/python -m unittest tests.test_reasoning_flow -q` | ❌ Wave 0 [ASSUMED] |
| PIPELINE-01 | Per-segment fan-out does not block sibling segments and meal completion waits for all | integration | `rtk .venv/bin/python -m unittest tests.test_parallel_pipeline -q` | ❌ Wave 0 [ASSUMED] |
| INTERVIEW-01 | Unresolved segments create a Telegram interview session | integration | `rtk .venv/bin/python -m unittest tests.test_interview_flow -q` | ❌ Wave 0 [ASSUMED] |
| INTERVIEW-02 | Interview backbone progresses correctly with skipped known fields | integration | `rtk .venv/bin/python -m unittest tests.test_interview_flow -q` | ❌ Wave 0 [ASSUMED] |
| INTERVIEW-03 | Interview answers create or update `FoodItem` and prep grounding handoff | integration | `rtk .venv/bin/python -m unittest tests.test_interview_flow -q` | ❌ Wave 0 [ASSUMED] |
| INTERVIEW-04 | Post-interview unresolved state commits best effort without infinite loops | integration | `rtk .venv/bin/python -m unittest tests.test_interview_flow -q` | ❌ Wave 0 [ASSUMED] |
| INTERVIEW-05 | User override path reopens and corrects an existing identification | integration | `rtk .venv/bin/python -m unittest tests.test_fix_flow -q` | ❌ Wave 0 [ASSUMED] |
| INTERVIEW-06 | Identity correction invalidates only the offending `FoodVisual` and writes the corrected one | integration | `rtk .venv/bin/python -m unittest tests.test_fix_flow -q` | ❌ Wave 0 [ASSUMED] |
| INFRA-04 | Janitor resets stale `*ING` rows and marks `FAILED` after exhaustion | integration | `rtk .venv/bin/python -m unittest tests.test_janitor -q` | ❌ Wave 0 [ASSUMED] |

### Sampling Rate

- **Per task commit:** Run the most specific new module for the touched surface, plus any existing `tests.test_match_flow` regressions when worker transitions change. [VERIFIED: codebase grep] [ASSUMED]
- **Per wave merge:** `rtk .venv/bin/python -m unittest` [ASSUMED]
- **Phase gate:** Full suite green plus one live smoke of reasoning, interview, and janitor recovery before `$gsd-verify-work`. [VERIFIED: codebase grep] [ASSUMED]

### Wave 0 Gaps

- [ ] `tests/test_reasoning_contract.py` - strict schema contract, unknown action handling, and retry-on-invalid behavior. [ASSUMED]
- [ ] `tests/test_reasoning_gate.py` - deterministic gate matrix for similarity, margin, missing evidence, and nutrition impact. [ASSUMED]
- [ ] `tests/test_reasoning_flow.py` - end-to-end `MATCHING -> REASONING -> READY_TO_WRITE|PENDING_*` behavior. [ASSUMED]
- [ ] `tests/test_interview_flow.py` - callback plus free-text backbone, final confirmation, reminder behavior, and best-effort unresolved closeout. [ASSUMED]
- [ ] `tests/test_fix_flow.py` - `/fix` item selection, side-effect diff, invalidation scoping, and correction history. [ASSUMED]
- [ ] `tests/test_janitor.py` - stale-stage recovery, duplicate-notify suppression, and artifact-first reset logic. [ASSUMED]
- [ ] Live smoke helper for prompt caching and Langfuse trace capture decisions. [ASSUMED]

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | Shared-secret ingest auth plus hard-pinned Telegram chat ID and command handlers that reject out-of-chat updates. [VERIFIED: codebase grep] |
| V3 Session Management | no | The app does not run a browser session model; interview state is DB-owned workflow state, not a web session. [VERIFIED: codebase grep] |
| V4 Access Control | yes | Scope `/fix`, interview callbacks, and correction writes to the single pinned Telegram user and the targeted `DiaryEntry` or session row. [VERIFIED: codebase grep] [ASSUMED] |
| V5 Input Validation | yes | Pydantic plus strict JSON schema for model outputs, explicit callback-pattern matching, and bounded free-text parsing. [CITED: https://openrouter.ai/docs/guides/features/structured-outputs] [CITED: https://docs.python-telegram-bot.org/en/stable/telegram.inlinekeyboardbutton.html] |
| V6 Cryptography | no | Use platform TLS and secret storage only; never hand-roll crypto inside the phase. [VERIFIED: codebase grep] |

### Known Threat Patterns for Python/FastAPI/PTB/OpenRouter

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Prompt injection from visible package text, restaurant menu text, or later tool results | Tampering | Ask for visible evidence and missing evidence, keep structured outputs strict, and never let text alone force a write without gate checks. [VERIFIED: codebase grep] [CITED: https://openrouter.ai/docs/guides/features/structured-outputs] |
| Duplicate writes after retries or janitor recovery | Repudiation | Persist stage artifacts before branching, make final writes transactional, and store message ids or sent flags for user-facing notifications. [VERIFIED: codebase grep] |
| Callback payload tampering or replay | Elevation of Privilege | Keep callback payloads short and opaque, resolve them server-side from DB state, and validate session ownership before mutation. [CITED: https://docs.python-telegram-bot.org/en/stable/telegram.inlinekeyboardbutton.html] [ASSUMED] |
| Over-broad visual invalidation during `/fix` | Tampering | Limit invalidation to the one offending linked visual and append a correction event instead of bulk mutation. [VERIFIED: codebase grep] |
| Langfuse outage or misconfigured media bucket blocking the pipeline | Denial of Service | Treat tracing as optional and non-blocking, and default multimodal capture off when self-host storage env vars are absent. [VERIFIED: codebase grep] [CITED: https://langfuse.com/docs/observability/features/multi-modality] [ASSUMED] |

## Sources

### Primary (HIGH confidence)
- Codebase and planning artifacts under `.planning/`, `app/`, `bot/`, `migrations/`, and schema draft files - current Phase 4 scope, runtime topology, missing persistence surfaces, and existing transitions. [VERIFIED: codebase grep]
- OpenRouter structured outputs docs - strict `json_schema` response format contract. [CITED: https://openrouter.ai/docs/guides/features/structured-outputs]
- OpenRouter tool-calling docs - standardized three-step tool loop interface. [CITED: https://openrouter.ai/docs/guides/features/tool-calling]
- OpenRouter prompt caching docs - Gemini cache behavior, sticky routing, breakpoints, and cache metrics. [CITED: https://openrouter.ai/docs/guides/best-practices/prompt-caching]
- OpenRouter `google/gemini-3.5-flash` model page - exact reasoning model id, multimodal inputs, thinking levels, release date. [CITED: https://openrouter.ai/google/gemini-3.5-flash/api]
- OpenRouter `google/gemini-3.1-flash-lite` model page - exact parser model id and intended lightweight workload fit. [CITED: https://openrouter.ai/google/gemini-3.1-flash-lite]
- Google Gemini image-understanding docs - multi-image prompts and multimodal capability. [CITED: https://ai.google.dev/gemini-api/docs/image-understanding]
- PTB `ConversationHandler`, `BasePersistence`, and `InlineKeyboardButton` docs - persistence, sequential update processing, and callback data limits. [CITED: https://docs.python-telegram-bot.org/en/v22.7/telegram.ext.conversationhandler.html] [CITED: https://docs.python-telegram-bot.org/en/stable/telegram.ext.basepersistence.html] [CITED: https://docs.python-telegram-bot.org/en/stable/telegram.inlinekeyboardbutton.html]
- APScheduler user guide - `max_instances`, `misfire_grace_time`, `coalescing`, and scheduler shutdown behavior. [CITED: https://apscheduler.readthedocs.io/en/stable/userguide.html]
- Langfuse OpenAI and OpenRouter integration docs - OpenAI SDK wrapper and OpenRouter compatibility. [CITED: https://langfuse.com/integrations/model-providers/openai-py] [CITED: https://langfuse.com/integrations/gateways/openrouter]
- Langfuse multimodality docs - automatic base64 handling, external URL rendering, and self-hosted media bucket requirement. [CITED: https://langfuse.com/docs/observability/features/multi-modality]
- PyPI registry metadata for package existence and current versions. [VERIFIED: PyPI]
- `slopcheck` local scan for package legitimacy. [VERIFIED: slopcheck]

### Secondary (MEDIUM confidence)
- None. Official docs and registry metadata covered the critical claims. [VERIFIED: local command]

### Tertiary (LOW confidence)
- None beyond the explicit `[ASSUMED]` design recommendations captured in the Assumptions Log. [VERIFIED: local command]

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - official docs, registry metadata, and repo pins all agree on the relevant libraries and model ids. [VERIFIED: codebase grep] [VERIFIED: PyPI] [CITED: https://openrouter.ai/google/gemini-3.5-flash/api]
- Architecture: MEDIUM - the worker topology and persistence gaps are clear in the repo, but some Phase 4 shape decisions remain planner discretion. [VERIFIED: codebase grep]
- Pitfalls: MEDIUM - the PTB, APScheduler, and Langfuse pitfalls are documented, but the nutrition-specific gating heuristics remain only partially documented and still need live calibration. [CITED: https://docs.python-telegram-bot.org/en/v22.7/telegram.ext.conversationhandler.html] [CITED: https://apscheduler.readthedocs.io/en/stable/userguide.html] [ASSUMED]

**Research date:** 2026-05-28
**Valid until:** 2026-06-04 for model and SDK surfaces; 2026-06-27 for repo-local architecture findings. [ASSUMED]
