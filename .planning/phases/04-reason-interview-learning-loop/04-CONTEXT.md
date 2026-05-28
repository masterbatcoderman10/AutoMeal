# Phase 4: Reason, Interview & Learning Loop - Context

**Gathered:** 2026-05-28
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 4 turns the post-segmentation pipeline into a durable reasoning and correction loop. Segment crops embed and vector-match in bounded parallel per meal, then one meal-level reasoning call receives the original meal image, all segment crops, and persisted top vector candidates. Reasoning validates matches, adds nutrition-relevant detail and quantity, detects duplicates/composites, and routes unresolved cases into Telegram choices/interviews. Final DiaryEntry/FoodVisual writes happen only after all meal segments are resolved and, when user input was needed, the user confirms the final meal. The phase also adds `/fix`, durable interview state, optional Langfuse tracing, and janitor recovery for stuck machine stages.

This phase does not implement the full SearXNG/Firecrawl grounding loop, custom observability dashboards, `/retry`, or a dedicated worker service. It may emit `NEEDS_GROUNDING` hints for Phase 5.

</domain>

<decisions>
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

### The Agent's Discretion
- The planner may choose exact storage shape for match results, meal-level reasoning JSON, correction events, and interview sessions, as long as the source-of-truth and recovery decisions above hold.
- The planner may keep Phase 4 in the current bot polling topology or do a low-risk extraction only if it clearly reduces complexity.
- The planner may choose exact top-match floor, stage retry counts, and nutrition-derivation status names.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase Scope And Prior Decisions
- `.planning/ROADMAP.md` — Phase 4 goal, success criteria, model/grounding note, and janitor requirement.
- `.planning/REQUIREMENTS.md` — `REASON-01` through `REASON-04`, `PIPELINE-01`, `INTERVIEW-01` through `INTERVIEW-06`, `INFRA-04`, and relevant Phase 5 grounding boundaries.
- `.planning/PROJECT.md` — core value, single-user Telegram/iOS Shortcut product shape, OpenRouter-only constraint, and pipeline shape.
- `.planning/STATE.md` — accumulated decisions, known concerns, and carried phase constraints.
- `.planning/phases/01-foundation-ingest/01-CONTEXT.md` — bot topology, uploads path conventions, schema locks, and DB polling pattern.
- `.planning/phases/02-vision-slice/02-CONTEXT.md` — segment semantics, crop persistence, label behavior, and Telegram tone baseline.
- `.planning/phases/03-embed-match/03-CONTEXT.md` — per-segment embedding/matching, FoodVisual write-back rules, no-match branch, Phase 3 threshold decisions that Phase 4 overrides or extends.

### Runtime Code
- `app/config.py` — runtime settings surface for model IDs, poll intervals, uploads dir, and new Phase 4 env config.
- `app/main.py` — FastAPI lifespan/APScheduler integration point for janitor.
- `app/models/meal_log.py` — processing status enum and coarse status state machine.
- `app/models/meal_segment.py` — crop path, embedding, `ai_reasoning`, and currently insufficient `portion_bucket`.
- `app/models/food_item.py` — identity/source/nutrition fields used by match/reasoning/corrections.
- `app/models/food_visual.py` — embedding and `is_invalidated` field for correction learning.
- `app/models/diary_entry.py` — target diary row and currently insufficient quantity model.
- `app/services/llm_client.py` — OpenRouter chat/embedding client surface to extend for reasoning, parsing, caching, and Langfuse tracing.
- `app/services/embedding_service.py` — embedding validation/retry helpers and 1536-dim constants.
- `app/services/matching_service.py` — current best-match logic, threshold, FoodVisual query, and similarity write-back helpers.
- `bot/polling.py` — current status-driven worker loops for ack/detect/segment/embed/match.
- `bot/messages.py` — terse Telegram message formatting baseline.
- `bot/handlers.py` — current command handler surface to extend for `/fix` and interview callbacks.

### External/Research References To Verify
- OpenRouter docs/model pages — verify `google/gemini-3.5-flash`, `google/gemini-3.1-flash-lite`, structured outputs, multi-image chat input, and prompt caching behavior.
- Langfuse docs — verify OpenAI SDK/OpenRouter tracing integration, multimodal input capture behavior, trace IDs, failure behavior, and dashboard/cost visibility.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `OpenRouterClient.chat_completion()` already centralizes chat calls through OpenRouter and can host reasoning/parser calls.
- `OpenRouterClient.embed_multimodal()` plus `matching_service.embed_segment_query_embedding()` already handle per-crop embedding.
- `MealSegment.embedding` already stores 1536-dim vectors and `MealSegment.ai_reasoning` can carry segment-level reasoning JSON.
- `FoodVisual.is_invalidated` already exists for `/fix` identity correction.
- `bot/polling.py` already uses DB-driven polling loops and `FOR UPDATE SKIP LOCKED`, matching the current worker topology decision.
- `bot/messages.py` gives the terse style to extend for brief-evidence prompts, confirmations, failure notices, and final logged results.

### Established Patterns
- `MealLog.processing_status` is the coordination backbone. Phase 4 should extend it carefully rather than introduce a separate queue.
- Telegram send failures should not roll back committed DB state.
- Image/crop files live at container-absolute `/data/uploads/...` paths and should remain the image source for reasoning and embeddings.
- Prior phases prefer bounded retries and fail-closed behavior over infinite loops.

### Integration Points
- Add Phase 4 settings in `app/config.py`: reasoning model, parser model, match threshold 0.90, segment parallelism 4, janitor interval 2 minutes, stale timeout 5 minutes, Langfuse env toggles, and optional image trace capture.
- Extend matching to persist top vector candidates per segment before reasoning.
- Add reasoning service that builds meal-level multimodal input from original meal image, crops, match metadata, and taxonomy JSON.
- Add durable interview/session persistence and Telegram callback/free-text handlers.
- Add `/fix` command and correction event/write-back path.
- Add APScheduler janitor in FastAPI lifespan.

</code_context>

<specifics>
## Specific Ideas

- Asian-cuisine suitability matters. Rice grain/prep, noodle type, curry composition, meat cut, oiliness, sauces, bread type, and fillings should be treated as nutrition-relevant details, not cosmetic labels.
- For curry, a broad FoodItem match like `chicken curry` can stay stable while reasoning adds detail such as visible chicken leg, oiliness, or portion. Do not explode the DB into every curry/cut variant automatically.
- For sandwiches/rolls/wraps, output one sandwich/roll by default with component detail; ask about filling when not visible and meaningful.
- For rice/pasta/noodles, grams and confidence ranges are more useful than buckets.
- For meat pieces/fruits, count and concrete unit names are more useful: drumstick, steak, shank, piece, etc.
- User wants Langfuse because the built-in dashboard makes reasoning/correction tuning visible without building custom observability.
- `/fix` must distinguish reasoning rejection from confirmed user correction: only confirmed user correction mutates FoodVisuals.

</specifics>

<deferred>
## Deferred Ideas

- Full SearXNG/Firecrawl grounding loop belongs to Phase 5; Phase 4 may only store `NEEDS_GROUNDING`.
- Full observability project, custom dashboards, per-stage timing/cost reporting beyond optional Langfuse trace IDs remains v2/OPS-02.
- `/retry <meal_id>` is deferred.
- Dedicated worker service extraction is deferred unless planner finds a very low-risk improvement.
- Promotion of repeated additive details into durable FoodItem profile/aliases/components can come after deployed learning proves the pattern.
- Action taxonomy may expand after real testing; Phase 4 should keep it evolvable.

</deferred>

---

*Phase: 4-Reason, Interview & Learning Loop*
*Context gathered: 2026-05-28*
