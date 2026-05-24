# Project Research Summary

**Project:** MealTracker
**Domain:** Self-hosted single-user photo-based meal tracker with multimodal LLM pipeline
**Researched:** 2026-05-24
**Confidence:** HIGH (stack, architecture); MEDIUM-HIGH (features, pitfalls)

## Executive Summary

MealTracker is a personal nutrition logger that accepts a photo from an iOS Shortcut and runs a fully automated detect → segment → embed → vector-match → LLM reason → Telegram interview pipeline, writing confirmed items into a growing FoodVisuals library that makes future matches faster. The recommended approach is a single FastAPI process hosting the API, pipeline worker, Telegram bot, and APScheduler together on one asyncio event loop — no Redis, no Celery, Postgres itself is the work queue via `FOR UPDATE SKIP LOCKED`. All LLM calls go through OpenRouter via the standard OpenAI SDK with a `base_url` swap; multimodal embeddings require a thin httpx wrapper because the SDK's typed `embeddings.create()` does not accept image content arrays.

The core competitive bet is the self-improving FoodVisuals vocabulary: after ~5–10 confirmed meals the system begins vector-matching without any LLM call. This only works if the vector dimension is correct from the start (Gemini Embedding 2 native is 3072 dims; MRL truncation to **768** is Google's production recommendation — the schema's current `vector(1024)` must be changed before any embedding code is written). The most dangerous failure modes are silent: wrong auto-confirmed matches poison the FoodVisuals index, miscalibrated LLM confidence gates silently commit wrong identifications, and bounding-box hallucinations double-count food items. All three must be addressed architecturally in the same phase that introduces each feature, not retroactively.

Accuracy expectations should be set honestly: ±20% calorie MAPE on mixed/restaurant meals is industry standard; portion estimation is the dominant error source because monocular photos cannot recover scale. Use discrete portion buckets (small/standard/large) in v1, not continuous multipliers, and always surface uncertainty in Telegram messages. The self-improving vocabulary is the realistic path to beating generic apps for this user's specific diet over time.

## Key Findings

### Stack Pins

- **Python 3.12 + FastAPI 0.115 + Pydantic 2.10** — runtime; FastAPI lifespan API, Pydantic v2-only; `@app.on_event` is deprecated
- **PostgreSQL 17 + pgvector 0.8.2** — `pgvector/pgvector:pg17` Docker image; HNSW index from day one (`m=16, ef_construction=64`)
- **SQLAlchemy 2.0 async + asyncpg 0.30 + Alembic 1.13** — only async-capable ORM path; `pgvector.sqlalchemy.Vector` column type
- **OpenAI Python SDK 1.55 + base_url swap** — verified working for vision, tool calling, and structured outputs through OpenRouter for all pinned Gemini models
- **httpx 0.27** — required for multimodal embedding calls (SDK typed path is text-only); also used for SearXNG/Firecrawl tool calls
- **python-telegram-bot 22.7 (long polling)** — ConversationHandler for interview FSM; webhooks not viable on Mac mini behind home NAT
- **APScheduler 3.10.x with AsyncIOScheduler** — NOT 4.x (alpha); started in FastAPI lifespan for daily summary cron
- **Pillow 10** — crop bounding-box regions before embedding
- **uv + ruff + pyright** — toolchain
- **searxng/searxng:latest + ghcr.io/firecrawl/firecrawl:latest** — local grounding; `devflowinc/firecrawl-simple` if Mac mini RAM is tight

**Model pins (all verified live on OpenRouter 2026-05-24):**
- `google/gemma-4-31b-it` — detect stage (is-food binary, cheap)
- `google/gemini-3-flash-preview` — segment, reason, re-ground (vision + tools + structured output)
- `google/gemini-3.1-flash-lite` — interview turns (text-driven, cheap tier)
- `google/gemini-embedding-2-preview` — multimodal embedding; **768 dims via MRL**, $0.20/M tokens

### Feature Categories

**Table stakes (must ship v1):**
- Photo to per-segment identification with macros
- Per-segment bounding-box segmentation on multi-item plates
- Confidence-gated Telegram interview when certainty is low
- Per-meal Telegram push when MealLog reaches COMPLETED
- Daily summary at 03:00 local (configurable)
- `/today`, `/week`, `/summary` slash commands
- `/fix <entry_id>` and `/delete <entry_id>` corrections (not in PROJECT.md Active list — roadmapper should add; see CF-6)
- Graceful NOT_FOOD handling with bot message
- Image-hash dedup within short window
- Verification status surfaced in every push message

**Differentiators:**
- Self-improving FoodVisuals vocabulary — vectors written on every confirmation; compounds over weeks
- Zero-friction iOS Shortcut entry — one tap, no app required
- Agentic web grounding — SearXNG + Firecrawl tools for restaurant/brand items
- Structured Telegram interview with `InterviewMessageKey` state machine (not freeform chat)
- Honest `is_verified=false` surfacing and full audit trail per DiaryEntry

**Anti-features (explicitly excluded):**
- Calorie/macro goals, streaks, gamification
- Mobile app, barcode scanner, recipe builder
- Multi-user / OAuth
- Direct Telegram image upload (iOS Shortcut is the only photo path)
- Pre-loaded USDA food database (conflicts with self-improving vocabulary thesis)

**Defer to v1.x:**
- `/last`, `/status`, `/why <entry_id>` debug commands
- Free-text conversational diary queries
- `/find <food>` history search

### Architecture Approach

One container, one process, one asyncio event loop. FastAPI + pipeline worker (`asyncio.create_task`) + python-telegram-bot polling + APScheduler all co-exist in a single Uvicorn worker. Postgres IS the work queue: `meal_logs.processing_status` with `FOR UPDATE SKIP LOCKED` drives the worker loop. Stage modules are pure async functions dispatched by a dict in `pipeline/worker.py`. The LLM gateway is the only code touching OpenRouter; repositories are the only code touching SQLAlchemy; the bot writes to the same DB the pipeline reads.

**Major components:**
1. `POST /ingest` endpoint — verifies shared secret, saves image, inserts `MealLog(status=PENDING)`, returns 202 immediately
2. Pipeline Worker — polls `meal_logs` with `SKIP LOCKED`, dispatches stages, advances status machine
3. LLM Client — wraps OpenAI SDK; methods per stage; owns agentic tool loop (`max_iterations=6`, 90s timeout)
4. Telegram Bot — push messages, `ConversationHandler` interview FSM, slash command handlers, correction handler
5. APScheduler — daily 03:00 summary job registered in lifespan
6. Repositories — all DB I/O; `food_visuals.py` owns cosine HNSW search

**State machine:** `PENDING → DETECTING → SEGMENTING → MATCHING → REVIEWING → COMPLETED` (also `NOT_FOOD`; add `FAILED` from day one)

### Critical Pitfalls

1. **`vector(1024)` schema is wrong** — Gemini Embedding 2 native is 3072 dims; 1024 is not an MRL truncation point; produces garbage similarity scores. Change to `vector(768)` before any embedding code.
2. **FoodVisuals self-poisoning** — one wrong auto-confirmed match writes a bad embedding that compounds. USER_CORRECTED events must cascade to FoodVisual invalidation in the same phase as FoodVisual writes.
3. **LLM confidence is not a probability** — ECE of 0.15–0.25 is typical. Cross-check with vector similarity score; use top-2 candidate margin; bias toward escalation.
4. **Bounding box hallucinations** — fabricated coordinates produce silent double-counting. Validate every box, IoU-dedup overlapping boxes, round-trip sanity check each crop.
5. **OpenRouter feature gaps** — structured outputs + tool calling simultaneously is buggy on some models. Run capability smoke tests at startup per stage.
6. **Pipeline stuck mid-state** — add `FAILED` status and a janitor cron that resets `*ING` rows older than 10 min. Idempotent stage handlers required.
7. **APScheduler + Mac mini sleep** — `pmset -a sleep 0` is mandatory. Module-level jobs only. Heartbeat cron verifies daily summary fires.

## Critical Flags

**CF-1 Schema change required:** Change `vector(1024)` → `vector(768)` in `food_visuals` and `meal_segments` before any embedding code. 1024 is NOT a valid MRL truncation point for Gemini Embedding 2 (native 3072; MRL points: 1536/768/512/256/128). Set `output_dimensionality=768`, `task_type=RETRIEVAL_DOCUMENT` for FoodVisual writes, `task_type=RETRIEVAL_QUERY` for segment search vectors.

**CF-2 OpenRouter embeddings caveat:** The OpenAI Python SDK's typed `embeddings.create()` accepts only string/list-of-strings — it does NOT model multimodal content arrays. For image embeddings, POST directly to `https://openrouter.ai/api/v1/embeddings` using `httpx`. SDK is fine for text-only calls. Implement a thin wrapper in `llm/client.py` that routes based on input type.

**CF-3 iOS Shortcuts trigger uncertainty:** Apple docs are vague on whether "new photo added to Camera Roll" fires automatically or requires unlock/charger. Verify on real device in Phase 0. Implement Share Sheet fallback shortcut immediately if automatic trigger is unreliable.

**CF-4 Confidence threshold defaults:** Start with ≥0.85 auto-match (similarity), 0.65–0.84 LLM reasoning, <0.65 interview. Do not gate on a single LLM-self-reported number. Corroborate with similarity score. Use margin between top-2 candidates as primary signal. Recalibrate after 50 real meals.

**CF-5 Cold-start UX:** Empty FoodVisuals means the first ~50 meals run heavy on LLM + interview. This is expected, not a bug. Consider bootstrap mode (relaxed threshold 0.70) for first N=30 meals, then auto-ratchet. Schema must support pre-creating FoodItems without FoodVisuals.

**CF-6 Edit/delete slash commands:** `/fix` and `/delete` are table-stakes per FEATURES.md but are NOT in PROJECT.md Active list. Roadmapper should add them to Active before phase planning. These are P1, not P2.

**CF-7 APScheduler 4 is alpha:** Use `APScheduler==3.10.*` with `AsyncIOScheduler`. 4.0.0a6 is marked "do NOT use in production" by the maintainer. Start in FastAPI `lifespan`, not `@app.on_event("startup")` (deprecated since FastAPI 0.95).

## Implications for Roadmap

### Phase 0: Foundation — Schema, Infra, Ingest Endpoint
**Rationale:** DB type correctness and working Docker stack are prerequisites for everything. TZ-aware types and schema corrections are catastrophically expensive to retrofit.
**Delivers:** docker-compose (app + postgres), correct schema with `vector(768)`, `TIMESTAMPTZ logged_at`, `FAILED` in status enum, iOS Shortcut posts photo and gets 202, Telegram bot sends "received photo, processing..." ack.
**Addresses:** CF-1, CF-7, Pitfall 10 (TZ bugs), Pitfall 12 (no denormalized totals), Pitfall 16 (endpoint ack <5s)
**Research flag:** Standard patterns — skip research phase.

### Phase 1: Vision Slice — Detect + Segment
**Rationale:** OpenRouter vision + structured output compatibility must be proven before any downstream logic depends on it. Box validation and IoU dedup belong here, not as later polish.
**Delivers:** Photo upload → bot reports "I see N items: [labels]" (no nutrition). DETECT and SEGMENT stages, box validation, IoU dedup, crop saving to disk.
**Addresses:** Pitfall 5 (OpenRouter capability smoke tests), Pitfall 6 (bounding box hallucinations)
**Research flag:** Skip research phase — OpenRouter vision + structured output is well-documented.

### Phase 2: Embed + Match + Food Library
**Rationale:** Vector dimension and normalization must be verified end-to-end before pipeline logic depends on similarity scores. Seed a handful of FoodItems by hand to test the match path.
**Delivers:** Per-crop embeddings at 768 dims, HNSW cosine search, similarity-matched segments produce DiaryEntries, FoodVisual write-back on confirmation, bot meal-result message.
**Addresses:** CF-1 (verify 768 dims), CF-2 (httpx embedding path), Pitfall 1 (calibration script: self-similarity ≈1.0, cross-modal sanity)
**Research flag:** Light research recommended at phase planning — verify Gemini Embedding 2 multimodal input format through OpenRouter's embeddings endpoint is still stable.

### Phase 3: Full Pipeline — Reason + Interview + Learning Loop
**Rationale:** LLM reasoning without tools first, then interview FSM. FoodVisual invalidation on USER_CORRECTED must ship in the same phase as FoodVisual writes.
**Delivers:** Full pipeline end-to-end. Multi-signal confidence gate (similarity + LLM margin). ConversationHandler interview FSM. USER_CORRECTED cascade to FoodVisual invalidation. Janitor cron. FAILED status + retry_count. Portion buckets (small/standard/large) not continuous multipliers.
**Addresses:** Pitfall 2 (FoodVisuals poisoning), Pitfall 3 (confidence gate), Pitfall 4 (portion estimation), Pitfall 8 (stuck pipeline), CF-4, CF-6
**Research flag:** Needs research phase — confidence calibration prompt patterns and multi-signal gating for Gemini 3 Flash specifically are sparse in existing docs.

### Phase 4: Agentic Grounding — SearXNG + Firecrawl Tools
**Rationale:** Tool integration builds on a stable pipeline. Cost and loop caps must ship with the feature, never afterward.
**Delivers:** SearXNG and Firecrawl wired as tools in reason + post-interview re-grounding. `max_iterations=6`, 90s timeout, URL allowlist, per-meal cost budget, tool-call dedup, trace in `ai_reasoning`.
**Addresses:** Pitfall 7 (agentic tool loops)
**Research flag:** Skip research phase — OpenRouter tool calling is fully documented with Gemini examples.

### Phase 5: Telegram Bot Surface — Commands + Daily Summary
**Rationale:** Full UX arrives when push, slash commands, daily summary, and corrections are all wired. APScheduler heartbeat and Mac sleep prevention ship here.
**Delivers:** All slash commands (`/today`, `/week`, `/summary`, `/fix`, `/delete`, `/last`). APScheduler daily 03:00 summary. Correction handler. HTML parse mode throughout. `disable_notification=True` on daily summary. Heartbeat cron verifying scheduler liveness.
**Addresses:** Pitfall 9 (APScheduler silent death, Mac sleep), Pitfall 15 (Telegram MarkdownV2 crashes)
**Research flag:** Standard patterns — skip research phase.

### Phase 6: Observability + Resilience
**Rationale:** The system must run for months without babysitting.
**Delivers:** `/admin/queue`, `/admin/meals/{id}` endpoints. Structured JSON logging. Per-meal token + dollar cost logged. Startup capability smoke tests. Image storage rotation.
**Addresses:** Pitfall 5 (startup capability verification), long-term cost visibility
**Research flag:** Standard patterns — skip research phase.

### Phase 7: Bootstrap + Polish
**Rationale:** Cold-start UX only matters after the pipeline is proven. Seed flow and empirical threshold calibration close the quality loop.
**Delivers:** Bootstrap mode (relaxed thresholds for first N meals). Seed-photos command. Interview-fatigue throttle (cap concurrent open interviews at 3). Reliability diagram on 50+ meals for threshold recalibration.
**Addresses:** Pitfall 11 (cold-start interview fatigue), Pitfall 3 (empirical calibration), CF-5
**Research flag:** Skip research phase.

### Phase Ordering Rationale

- Schema correctness (Phase 0) is a prerequisite for everything — `vector(768)` and `TIMESTAMPTZ` cannot be retrofitted.
- Vision pipeline (Phase 1) before embedding (Phase 2) — OpenRouter capability must be proven before vector matching logic is built on top.
- Full pipeline (Phase 3) deferred until after embed/match is proven — building the interview FSM before similarity search works creates an unverifiable system.
- Agentic tools (Phase 4) after pipeline stabilizes — adding tool calls before confidence gating is reliable compounds debugging.
- Bot surface (Phase 5) last among core features — requires DiaryEntries to exist.
- Observability (Phase 6) and bootstrap (Phase 7) are explicitly post-MVP.

### Research Flags

Needs deeper research during phase planning:
- **Phase 3 (Reason + Interview):** Confidence calibration prompt patterns and multi-signal gating for Gemini 3 Flash specifically.
- **Phase 2 (Embed + Match):** Verify Gemini Embedding 2 multimodal input format through OpenRouter embeddings endpoint at implementation time.

Standard patterns (skip research phase):
- Phase 0, 1, 4, 5, 6, 7

## Open Questions

Items requiring real-device or runtime verification:

1. **iOS Shortcut trigger reliability** — does "new photo added" fire automatically without user interaction? Verify on device in Phase 0.
2. **Gemini Embedding 2 cross-modal alignment on food** — does "daal chawal" text rank closer to its photo than to random food? Verify with calibration script in Phase 2 before building matching logic.
3. **Gemini 3 Flash: structured output + tool calling in same request** — verify empirically in Phase 1; split into two calls if broken.
4. **Firecrawl resource envelope on Mac mini** — verify Docker memory limits hold under 5 sequential Chromium fetches before Phase 4 ships.
5. **OpenRouter preview model ID stability** — add startup check asserting all four pinned model IDs are present in `/api/v1/models`.
6. **Confidence threshold starting values** — 0.85/0.65 are industry-derived; log every (predicted_confidence, post_interview_outcome) pair from Phase 3 onward and recalibrate in Phase 7.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Core libs verified against official docs. Model IDs verified live on OpenRouter 2026-05-24. APScheduler alpha status confirmed from maintainer release notes. |
| Features | MEDIUM-HIGH | Competitor benchmarks from 2026 sources (multiple agreeing). iOS Shortcut trigger semantics are MEDIUM — Apple docs sparse. |
| Architecture | HIGH | Single-process topology, Postgres-as-queue, lifespan wiring are established FastAPI patterns. ConversationHandler FSM is standard python-telegram-bot. |
| Pitfalls | HIGH | Embedding dim mismatch, FoodVisuals poisoning, LLM confidence miscalibration, and bounding box hallucinations all documented with primary sources for this exact stack. |

**Overall confidence:** HIGH

### Gaps to Address

- **Gemini Embedding 2 through OpenRouter — live multimodal behavior:** Documented as supported but preview. Phase 2 is the verification gate.
- **iOS Shortcut trigger semantics:** Budget Phase 0 time for real-device smoke test; implement Share Sheet fallback immediately if unreliable.
- **Confidence threshold calibration:** 0.85/0.65 are starting points. Reserve Phase 7 for empirical tuning.
- **Firecrawl vs firecrawl-simple:** Depends on Mac mini RAM budget. Flag for Phase 4 planning.

## Sources

### Primary (HIGH confidence)
- OpenRouter docs (quickstart, vision, tool calling, structured outputs, embeddings, model pages)
- Google Blog + Google Developers Blog — Gemini Embedding 2 MRL, 768 production recommendation
- FastAPI release notes + lifespan docs
- python-telegram-bot v22 docs
- APScheduler version history — 4.x alpha status
- pgvector-python README + HNSW/IVFFlat benchmarks

### Secondary (MEDIUM confidence)
- Cal AI, SnapCalorie, Foodvisor, Cronometer reviews (2026) — accuracy benchmarks ±15–40% MAPE
- arXiv papers on portion estimation, LLM confidence calibration, RAG poisoning
- SearXNG self-host community guides
- Firecrawl SELF_HOST.md (official)
- iOS Shortcuts documentation (sparse)

### Tertiary (LOW confidence)
- APScheduler silent failure GitHub issues — behavioral edge cases under Mac sleep
- OpenRouter provider routing reliability reports — anecdotal

---
*Research completed: 2026-05-24*
*Ready for roadmap: yes*
