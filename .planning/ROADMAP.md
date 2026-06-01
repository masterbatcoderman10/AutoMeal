# Roadmap: MealTracker

## Overview

Eight phases transform a blank repo into a fully operational personal meal tracker: the photo arrives via iOS Shortcut, runs through detect → segment → embed → vector-match → LLM reason → AI-assisted Telegram interview, and every confirmed identification grows the FoodVisuals library so future matches are faster. Each phase ends with a working vertical slice — something you can actually fire the Shortcut at and observe improving. Schema correctness (vector(1536), TIMESTAMPTZ, FAILED status) is locked in Phase 1 and never revisited.

## Phases

- [x] **Phase 1: Foundation & Ingest** - Docker stack running, correct schema, iOS Shortcut posts a photo and gets a Telegram ack (completed 2026-05-26)
- [ ] **Phase 2: Vision Slice** - Photo upload produces a bot message listing detected food items by name (no nutrition yet)
- [ ] **Phase 3: Embed & Match** - Seeded foods matched by vector similarity produce DiaryEntries and a nutrition push
- [x] **Phase 4: Reason, Interview & Learning Loop** - Full pipeline end-to-end: segmented foods continue in bounded async parallel; unknown foods flow through LLM reasoning and structured Telegram interview; corrections cascade to FoodVisual invalidation; pipeline is resilient to crashes (completed 2026-05-28)
- [x] **Phase 4.1: Grouped Reasoning & Human Interview Correction** - Correct the Phase 4 UAT gap where whole-meal top-3 candidates and raw segment prompts produce confusing interviews; reasoning must group distinct foods first, produce per-food top-3 candidates, and ask one human question per unresolved food group (completed 2026-05-29)
- [x] **Phase 4.2: LLM-Threaded Interview Orchestration** - Replace deterministic interview continuation with an LLM interview agent that receives grouped reasoning context, conversation history, pending unclear targets, and clear auto-proposed items for approval; it asks natural follow-ups, decides when enough information is collected, and hands structured confirmed items back to final write-back/grounding. (completed 2026-05-30)
- [ ] **Phase 4.3: Deterministic Clarification Schema & Interview UI** - Replace freeform LLM interview turns with a reasoning-produced clarification schema, deterministic Telegram MCQ/open-field rendering, structured answer capture, and a compact final resolver that feeds the existing authoritative FoodItem/DiaryEntry/FoodVisual write path.
- [ ] **Phase 5: Agentic Grounding** - Reasoning and post-interview stages can search and fetch brand/restaurant nutrition via SearXNG + Firecrawl with hard budget caps
- [ ] **Phase 6: Bot Surface & Daily Summary** - All slash commands, daily 03:00 summary via APScheduler, per-meal push with entry IDs for corrections

## Phase Details

### Phase 1: Foundation & Ingest

**Goal**: As a single MealTracker user, I want to submit a meal photo and get an immediate Telegram acknowledgement, so that I can confirm photo ingest is working without manual database checks.
**Mode:** mvp
**Depends on**: Nothing (first phase)
**Requirements**: INFRA-01, INFRA-02, INFRA-03, INFRA-05, INGEST-01, INGEST-02, INGEST-03, INGEST-04, INGEST-05, MATCH-01
**Success Criteria** (what must be TRUE):

  1. Running `docker compose up` brings up the full stack (app + postgres + searxng + firecrawl) on arm64; the stack also declares correct amd64 image layers for future VM portability
  2. Submitting a photo via the iOS Shortcut (or curl with the shared secret) returns a 202 acknowledgement within 5 seconds and a Telegram "received, processing..." message appears
  3. Re-submitting the identical photo within 60 seconds returns the existing MealLog ID (dedup), not a new row
  4. A rejected request (missing or wrong secret) returns 401 — the endpoint never processes it
  5. The database schema uses `vector(1536)` on `food_visuals.embedding` and `meal_segments.embedding`, `TIMESTAMPTZ` on all timestamp columns, and includes `FAILED` in the `MealProcessingStatus` enum; the HNSW cosine index (`m=16, ef_construction=64`) is present on `food_visuals.embedding`

**Plans**: TBD
**Phase note**: CF-3 research item — verify iOS Shortcut "new photo added to Camera Roll" trigger fires automatically on the real device during this phase. Implement Share Sheet fallback shortcut immediately if automatic trigger is unreliable. CF-2 note: multimodal embedding calls will use a thin httpx wrapper (not the OpenAI SDK typed path) — wire the LLM client skeleton with routing logic now.

---

### Phase 2: Vision Slice

**Goal**: Every accepted photo runs through the detect and segment stages; the Telegram bot reports what it sees by name with bounding-box crops saved to disk — no nutrition, no vector matching yet, but the computer vision pipeline is proven end-to-end.
**Mode:** mvp
**Depends on**: Phase 1
**Requirements**: VISION-01, VISION-02, VISION-03, VISION-04
**Success Criteria** (what must be TRUE):

  1. Submitting a food photo produces a Telegram message listing each detected food item by label (e.g. "I see 3 items: rice, daal, naan")
  2. Submitting a non-food photo (screenshot, pet, receipt) stops after detect with no final Phase 2 result message and no DiaryEntry is created
  3. Bounding boxes are validated before use: coordinates within [0,1], y0<y1, x0<x1, area >1% of image, count capped at 8; invalid or hallucinated boxes are rejected and the segment stage re-prompts
  4. IoU deduplication removes overlapping boxes (>0.5 IoU) so the same food item is never double-counted
  5. Each accepted segment has a cropped image file saved to disk at the correct path

**Plans**:

  - `02-01` (Wave 1) — detect-stage gate and non-food completion slice
  - `02-02` (Wave 2, blocked on `02-01`) — simple food happy path with normalized boxes, saved crops, and one-sentence result output
  - `02-03` (Wave 3, blocked on `02-02`) — segmentation retry, IoU dedupe, duplicate-label collapse, and soft-failure handling
  - `02-04` (Wave 4, blocked on `02-03`) — live OpenRouter smoke coverage, env-template updates, and UAT scaffolding

**Phase note**: Run OpenRouter capability smoke tests during this phase: verify vision input + structured output + bounding-box format ([y,x,y,x] normalized 0–1000 at the provider boundary, converted to `[0,1]` in application code) all work for the pinned model. Discuss-phase clarification also overrides the earlier VISION-02 wording: confident non-food photos still stop the pipeline, but the final Phase 2 result message is suppressed instead of sending a polite skip text.

---

### Phase 3: Embed & Match

**Goal**: As a MealTracker user, I want to have accepted meal-segment crops auto-match against my seeded FoodVisual library and immediately produce DiaryEntries plus a Telegram nutrition push, so that repeat meals log themselves before I need any reasoning or interview flow.
**Mode:** mvp
**Depends on**: Phase 2
**Requirements**: MATCH-02, MATCH-03, MATCH-04
**Success Criteria** (what must be TRUE):

  1. A crop embedding is generated with `output_dimensionality=1536`, `task_type=RETRIEVAL_DOCUMENT` for FoodVisual writes and `task_type=RETRIEVAL_QUERY` for segment searches; the output dimension is verified (calibration: self-similarity of the same image embedded twice is ≥ 0.99)
  2. Re-photographing a food item that was manually seeded in FoodItems/FoodVisuals triggers a SIMILARITY match (score ≥ 0.85) and produces a DiaryEntry without LLM or interview involvement
  3. After any confirmation (SIMILARITY, LLM, or INTERVIEW path), a new FoodVisual row is written to the index so the visual vocabulary grows; confirming the same food twice produces two FoodVisual rows
  4. A Telegram meal-result message is pushed when MealLog.processing_status reaches COMPLETED, showing food name, estimated portion bucket, macros, and verification status

**Plans**: 4 plansPlans:

  - [ ] `03-01-PLAN.md` — Wave 0 embedding contract hardening, calibration gate, and demo seed helper
  - [ ] `03-02-PLAN.md` — per-segment embed/search gate with unresolved-meal routing to `REASONING`
  - [ ] `03-03-PLAN.md` — transactional similarity completion with `DiaryEntry` creation and `FoodVisual` write-back
  - [ ] `03-04-PLAN.md` — post-commit Telegram nutrition push and Phase 03 UAT evidence scaffold

**Phase note**: Run cross-modal sanity calibration before building match logic: "rice and lentils" text embedding should rank closer to a daal chawal photo than to a random food. If cross-modal alignment is degenerate, stop and evaluate alternative embedding models before proceeding.

---

### Phase 4: Reason, Interview & Learning Loop

**Goal**: Once segmentation is done, each segment continues through the remaining pipeline independently with bounded async parallelism; unknown or low-confidence segments flow through LLM reasoning (top-3 candidates with multi-signal confidence gating) and a structured Telegram interview; user corrections cascade to FoodVisual invalidation; the pipeline is resilient to mid-stage crashes via a janitor job and FAILED status.
**Mode:** mvp
**Depends on**: Phase 3
**Requirements**: REASON-01, REASON-02, REASON-03, REASON-04, PIPELINE-01, INTERVIEW-01, INTERVIEW-02, INTERVIEW-03, INTERVIEW-04, INTERVIEW-05, INTERVIEW-06, INFRA-04
**Success Criteria** (what must be TRUE):

  1. A segment below the auto-match threshold triggers the LLM reasoning stage, which emits top-3 candidate identifications each with a confidence value and rationale — not a single guess; the reasoning trace is stored in `MealSegment.ai_reasoning`
  2. The escalation gate uses the vector similarity score AND the top-1-vs-top-2 margin from the LLM — not the raw self-reported confidence alone — and biases toward interview when signals disagree
  3. Once segments exist, multiple segments in the same meal proceed through embed → match → reason → interview/confirmation → write-back asynchronously with a configurable semaphore; one slow or interview-bound segment does not block automated progress on sibling segments
  4. A segment that fails the confidence gate triggers a structured Telegram interview walking INITIAL_QUESTION → FOOD_NAME → SOURCE_TYPE → (RESTAURANT_NAME | BRAND_NAME) → PORTION_CONTEXT → CONFIRMATION; completing the interview writes a FoodItem (or updates an existing one) and advances the pipeline
  5. Portion estimates are discrete buckets (small / standard / large mapping to 0.5 / 1.0 / 1.5×), never a continuous multiplier; the per-meal message reads "~small portion" not "0.63×"
  6. Sending `/fix <entry_id>` re-opens the interview for that segment and the user can correct the identification; a USER_CORRECTED event invalidates the previously written FoodVisual (`is_invalidated=true`) and writes a new one for the correct FoodItem
  7. A MealLog stuck in any `*ING` status for longer than 10 minutes is automatically reset to PENDING or marked FAILED (after 3 retries) by the janitor job; killing the worker mid-stage and waiting 10 minutes results in the meal recovering and completing

**Plans**: 8 plansPlans:

- [ ] `04-01-PLAN.md` — Wave 0 reasoning contract, gate, parallel-pipeline tests, and live cache/trace smoke coverage
- [ ] `04-02-PLAN.md` — Wave 0 interview, `/fix`, and janitor test scaffolds including D-48 and D-49 confirmation-edit branches
- [ ] `04-03-PLAN.md` — durable schema and ORM state surfaces for reasoning, quantity, interview, correction, and recovery
- [x] `04-04-PLAN.md` — shared runtime interfaces, editable taxonomy, Phase 4 config keys, and optional Langfuse tracing wrapper (completed 2026-05-28)
- [x] `04-05-PLAN.md` — meal-level reasoning gate, top-3 trace persistence, and bounded parallel auto-confirm slice
- [x] `04-06-PLAN.md` — Telegram interview, confirmation edit loops, reminder, and minimal grounding-prep slice
- [x] `04-07-PLAN.md` — `/fix` correction, scoped invalidation, and correction history slice
- [ ] `04-08-PLAN.md` — APScheduler janitor recovery, duplicate-notify suppression, and crash smoke slice

**Phase note**: Research flag from SUMMARY.md — confidence calibration prompt patterns and multi-signal gating for Gemini 3 Flash are sparsely documented. Plan this phase with a mini-research pass before writing the confidence gate. INTERVIEW-03 includes a post-interview re-grounding pass with tools (SearXNG + Firecrawl) for PACKAGED/RESTAURANT items — tool infrastructure must be stubbed or minimally wired before this phase completes; full tool loop ships in Phase 5. Observability work such as Langfuse tracing and persisted per-stage timing metrics remains deferred to v2 OPS-02.

---

### Phase 4.1: Grouped Reasoning & Human Interview Correction

**Goal**: Fix the Phase 4 UAT failure where the system treats separate foods in one meal as competing top-3 candidates and asks robotic raw-segment interview questions; the system must reason over food groups, rank candidates per group, and ask concise human questions only for unresolved groups.
**Mode:** mvp
**Depends on**: Phase 4
**Requirements**: REASON-01, REASON-02, REASON-04, INTERVIEW-01, INTERVIEW-02, INTERVIEW-03, INTERVIEW-06
**Success Criteria** (what must be TRUE):

  1. Reasoning output contains grouped food records for distinct foods/components in a meal; each group includes stable `segment_ids`, a human label, action/state, evidence, missing evidence, and exactly three candidate identifications for that group.
  2. Meal-level gating compares candidates within each food group, not unrelated foods across the whole meal; a clear chicken/pita group and an egg-curry group are not treated as competing alternatives.
  3. Persisted reasoning keeps both meal-level summary state and group-level/per-segment auditability without copying the same whole-meal top-3 onto every segment.
  4. Telegram interview session targets unresolved food groups, not raw detector segments; duplicate/overlapping segment labels are collapsed before any user-facing question.
  5. User-facing interview copy is brief, human, and answerable without developer knowledge; it avoids internal phrases such as "nutrition-relevant detail" and asks the concrete missing thing, for example which vegetable is inside a curry.
  6. Re-running the known UAT sample `sample_images/IMG_4646.HEIC` records Langfuse image traces and produces group-level reasoning where egg curry, chicken curry, and pita/flatbread are handled as separate food groups.

**Plans**: 2 plans

- [ ] `04.1-01-PLAN.md` — grouped reasoning contract, per-group gate and persistence, and grouped final-write adapter regression
- [ ] `04.1-02-PLAN.md` — group-target interview prompts plus `IMG_4646.HEIC` UAT and Langfuse trace verification

**Phase note**: This is a corrective polish phase created from Phase 4 UAT on 2026-05-29. It should remain isolated from Phase 5 grounding work: no SearXNG/Firecrawl tool loop, no nutrition derivation expansion, and no broader Telegram command work. The first executable plan should be small enough to run independently with `/gsd-execute-phase 4.1`.

---

### Phase 4.2: LLM-Threaded Interview Orchestration

**Goal**: Replace the deterministic Telegram interview continuation with an LLM-assisted interview agent that starts from grouped reasoning context, includes both unclear targets and clear auto-proposed items for approval, uses conversation history, asks natural follow-ups, determines when the answers are sufficient, and returns structured confirmation items for final write-back or post-interview grounding.
**Mode:** mvp
**Depends on**: Phase 4.1
**Requirements**: REASON-01, REASON-04, INTERVIEW-01, INTERVIEW-02, INTERVIEW-03, INTERVIEW-06
**Success Criteria** (what must be TRUE):

  1. When reasoning creates unresolved food groups, the interview prompt starter includes the grouped reasoning payload, candidate choices, missing evidence, segment IDs, image/crop references where available, and the current user-facing question.
  2. Clear/high-confidence food groups are included in the same interview turn as approval candidates, so the user can accept or correct them while answering unclear items.
  3. Each Telegram user reply is appended to durable conversation history and sent to the interview LLM with unresolved targets, approval candidates, prior assistant prompts, prior user answers, and current structured state.
  4. The interview LLM returns strict structured output: `continue_interview` with the next natural prompt, `need_clarification` with a targeted correction prompt, or `ready_to_confirm` with normalized confirmation items and explicit approval/correction status for every clear and unclear group.
  5. A reply like "bottle gourd" to an egg/vegetable curry target resolves the missing vegetable detail and composes the confirmed item name, e.g. `egg curry with bottle gourd`, instead of advancing to a second deterministic "what should I call..." naming question.
  6. The active interview is scoped to the meal/thread being answered; stale active sessions cannot steal replies from the newest meal.
  7. On `ready_to_confirm`, the structured confirmation items flow through the existing final write-back/grounding path so FoodItems, DiaryEntries, and FoodVisuals are written by the same authoritative transaction used by Phase 4.1.
  8. The interview model and fallback are explicit config keys, defaulting to a low-cost text model such as `google/gemini-3.1-flash-lite`, and Langfuse traces show the model, prompt context, and structured response.

**Plans**: 3 plansPlans:

- [ ] `04.2-01-PLAN.md` — Wave 0 Python 3.12 bootstrap, strict interview-turn contract, explicit model config, and authoritative grouped state scaffold
- [ ] `04.2-02-PLAN.md` — single-active-session LLM meal interview kickoff, continuation, bounded repair, and fail-closed finalizer handoff
- [ ] `04.2-03-PLAN.md` — prompt-scoped reply routing, `/fix` preservation, and Phase 04.2 live UAT checklist

**Phase note**: This phase exists because UAT showed the deterministic roadmap `INITIAL_QUESTION -> FOOD_NAME -> SOURCE_TYPE -> PORTION_CONTEXT` cannot interpret natural answers in context. It should not add web grounding or nutrition lookup; it only upgrades the human interview brain and its handoff back into existing write paths.

---

### Phase 4.3: Deterministic Clarification Schema & Interview UI

**Goal**: Replace the freeform interview-turn LLM with a deterministic clarification UI driven by reasoning output: meal reasoning emits a strict per-food-group clarification schema; Telegram renders MCQ/open-field prompts from templates; replies are stored as structured answers; a compact resolver/finalizer consumes the answers and writes through the existing authoritative FoodItem, DiaryEntry, and FoodVisual path.
**Mode:** mvp
**Depends on**: Phase 4.2
**Requirements**: REASON-01, REASON-02, REASON-03, REASON-04, INTERVIEW-01, INTERVIEW-03, INTERVIEW-04, MATCH-04
**Success Criteria** (what must be TRUE):

  1. Meal reasoning no longer emits a root-level `top_3` as an active source of truth; candidate ranking lives under `food_groups[*].top_3`, with compatibility handled only where needed during migration.
  2. Meal reasoning emits a strict `clarification_schema` for unresolved or approval-needed food groups, including stable question IDs, group IDs, segment IDs, question kind, answer type (`single_choice`, `multi_choice`, `free_text`, or `confirm`), candidate options, and validation hints.
  3. Telegram questions are rendered deterministically from templates, not composed by an interview LLM; replies by button/MCQ or free text are mapped back to the exact question ID and stored in durable interview state.
  4. Conditional source-origin clarification is asked only when it can materially change nutrition or grounding behavior, such as flatbreads, packaged-looking foods, bakery items, sauces, takeout, desserts, or brand/restaurant-looking items; obvious home-cooked foods are not burdened with source-origin questions.
  5. A user can answer only part of a clarification batch and the system deterministically re-prompts only the unanswered required questions, without losing prior answers or looping on already-satisfied approvals.
  6. The final resolver consumes grouped reasoning plus structured answers and emits normalized confirmation items into the existing final write path so FoodItems, DiaryEntries, and FoodVisual rows are created exactly as in Phase 4.2.
  7. Live repeated-meal UAT with the saved UAT embedding checkpoint proves vector candidates inform reasoning, template questions are asked, partial replies recover deterministically, and final save creates/updates the expected diary and visual rows.

**Plans**: 3 plans:

- [ ] `04.3-01-PLAN.md` - grouped reasoning contract cleanup, strict `clarification_schema`, source-origin rules, and removal of live root `top_3` branching.
- [ ] `04.3-02-PLAN.md` - deterministic Telegram rendering, stable question/choice answer capture, and partial reply recovery.
- [ ] `04.3-03-PLAN.md` - resolver-only finalization handoff, authoritative save-path preservation, and live 04.3 UAT.

**Phase note**: This is an interview architecture cleanup before Phase 5 grounding, not a nutrition-grounding expansion. Keep SearXNG/Firecrawl tool loops out of scope except preserving handoff fields for Phase 5. Preserve the existing LLM finalizer only as a compact resolver if needed; it should not ask user-facing interview questions.

---

### Phase 5: Agentic Grounding

**Goal**: The reasoning stage and post-interview re-grounding stage can invoke SearXNG and Firecrawl as tools when the LLM needs brand or restaurant nutrition data; every tool call is bounded, traced, and the loop cannot run away on cost.
**Mode:** mvp
**Depends on**: Phase 4.3
**Requirements**: GROUND-01, GROUND-02, GROUND-03
**Success Criteria** (what must be TRUE):

  1. Photographing a branded packaged food or a restaurant dish triggers a tool call to `searxng_search` and/or `firecrawl_fetch` within the reasoning stage; the fetched nutrition data lands in the FoodItem and is attributed in `MealSegment.ai_reasoning`
  2. The tool loop is bounded: after 6 iterations OR 90 seconds wall-clock OR per-meal cost cap, the loop exits cleanly and commits the best available result with `is_verified=false` — no hanging meals, no infinite retries
  3. Firecrawl can only fetch URLs that appeared in a prior SearXNG result in the same session (URL allowlist); attempting to fetch a model-fabricated URL is silently rejected
  4. The full tool-call trace (queries, URLs, snippet excerpts, iteration count) is appended to `MealSegment.ai_reasoning` and is human-readable

**Plans**: TBD
**Phase note**: Verify Firecrawl resource envelope on Mac mini before shipping: run 5 sequential Chromium fetches under Docker memory limits and confirm OOM does not occur. If headroom is insufficient, switch to `devflowinc/firecrawl-simple` during this phase.

---

### Phase 6: Bot Surface & Daily Summary

**Goal**: The complete Telegram UX is live — per-meal pushes with entry IDs, all slash commands, the configurable daily summary via APScheduler, and the delete slash command; the user can operate the system entirely through Telegram with no manual DB access needed.
**Mode:** mvp
**Depends on**: Phase 5
**Requirements**: OUTPUT-01, OUTPUT-02, OUTPUT-03, OUTPUT-04, OUTPUT-05, OUTPUT-06, OUTPUT-07, OUTPUT-08
**Success Criteria** (what must be TRUE):

  1. Every completed MealLog triggers a Telegram push containing display name(s), estimated portion bucket, macros, verification status (`is_verified` flag), and identification method; each item includes a referenceable `entry_id`
  2. The APScheduler daily summary fires at the configured local time (default 03:00) with `disable_notification=True`, covering the prior calendar day in the configured timezone; it survives a Docker restart without losing the schedule
  3. `/today` returns today's logged meals with running totals; `/week` returns the last 7 days with daily and 7-day aggregate totals; `/summary` returns the current day's summary on demand
  4. `/delete <entry_id>` removes a DiaryEntry, invalidates its linked FoodVisual, and the deletion is reflected in the next `/today` or `/week` call
  5. All Telegram messages use HTML parse mode — food names containing `.`, `_`, `*`, `(`, `)` or other MarkdownV2 special characters do not cause send failures

**Plans**: TBD
**Phase note**: CF-7 compliance — APScheduler must be 3.10.x with AsyncIOScheduler started in FastAPI lifespan (not `@app.on_event`). Add a heartbeat cron every hour that writes a row to a `scheduler_heartbeats` table; if the daily summary does not fire within 5 minutes of its scheduled time the next heartbeat sends a Telegram alert. `pmset -a sleep 0` must be set on the Mac mini before declaring this phase complete.
**UI hint**: yes

---

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation & Ingest | 5/5 | Complete   | 2026-05-26 |
| 2. Vision Slice | 4/4 | In Progress|  |
| 3. Embed & Match | 4/4 | In Progress|  |
| 4. Reason, Interview & Learning Loop | 8/8 | Complete    | 2026-05-28 |
| 4.1. Grouped Reasoning & Human Interview Correction | 2/2 | Complete   | 2026-05-29 |
| 4.2. LLM-Threaded Interview Orchestration | 3/3 | Complete   | 2026-05-30 |
| 4.3. Deterministic Clarification Schema & Interview UI | 1/3 | In Progress|  |
| 5. Agentic Grounding | 0/TBD | Not started | - |
| 6. Bot Surface & Daily Summary | 0/TBD | Not started | - |
