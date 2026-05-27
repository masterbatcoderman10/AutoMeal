# Requirements: MealTracker

**Defined:** 2026-05-24
**Core Value:** Lowest-friction meal logging for one person: snap a photo, get logged nutrition with zero manual entry, and have the system get faster and more accurate the more I use it.

## v1 Requirements

### Ingest

- [x] **INGEST-01**: iOS Shortcut posts the last-taken photo to the authenticated endpoint
- [x] **INGEST-02**: Endpoint verifies a shared-secret header; rejects missing or wrong secret with 401
- [x] **INGEST-03**: Endpoint saves the image to local disk and returns 202 ack within 5 seconds
- [x] **INGEST-04**: A `MealLog` row is created with `processing_status=PENDING` on every accepted photo
- [x] **INGEST-05**: Re-submitting the same image-hash within a 60-second window returns the existing `MealLog` (dedup)

### Vision

- [x] **VISION-01**: Detect stage classifies image as food vs not-food
- [x] **VISION-02**: NOT_FOOD photos skip the rest of the pipeline and produce no final Phase 2 result message
- [x] **VISION-03**: Segment stage outputs `[y0,x0,y1,x1]` bounding boxes per food item, validated and IoU-deduped
- [x] **VISION-04**: Each accepted segment is cropped and saved to disk

### Match

- [x] **MATCH-01**: Schema uses `vector(1536)` — Gemini Embedding 2 MRL truncated to 1536 dims (within pgvector's HNSW indexability ceiling of 2000); FoodVisuals and MealSegments columns updated accordingly
- [ ] **MATCH-02**: Per-crop multimodal embedding is generated with `output_dimensionality=1536`, `task_type=RETRIEVAL_DOCUMENT` on writes / `RETRIEVAL_QUERY` on searches; stored on `MealSegment.embedding`
- [ ] **MATCH-03**: HNSW cosine index (`m=16, ef_construction=64`) on `FoodVisuals.embedding`; cosine similarity search returns the top match + score
- [ ] **MATCH-04**: On confirmed identification (any method) a `FoodVisual` row is written so the visual vocabulary grows

### Reason

- [ ] **REASON-01**: When the top similarity score is below the auto-match threshold, the LLM reasoning stage runs against the cropped segment
- [ ] **REASON-02**: LLM reasoning emits the **top-3 candidate identifications**, each with a brutally-self-reported confidence value and short rationale (not a single guess + single confidence)
- [ ] **REASON-03**: Multi-signal confidence gate decides escalation using top-1-vs-top-2 margin AND the vector similarity score — not the LLM's self-reported confidence alone
- [ ] **REASON-04**: Reasoning trace (top-3, scores, similarity, decision) is written to `MealSegment.ai_reasoning` for audit

### Ground

- [ ] **GROUND-01**: Reasoning stage and post-interview stage can call `searxng_search` and `firecrawl_fetch` as tools when the LLM needs brand/restaurant nutrition data
- [ ] **GROUND-02**: Tool loop is bounded: `max_iterations=6`, 90 s wall-clock timeout, per-meal cost cap, URL allowlist
- [ ] **GROUND-03**: Tool-call trace (queries, URLs, snippets) is appended to `MealSegment.ai_reasoning`

### Interview

- [ ] **INTERVIEW-01**: Segments below the confidence threshold trigger a Telegram interview session
- [ ] **INTERVIEW-02**: Interview follows the structured `InterviewMessageKey` flow (name → source-type → restaurant/brand → portion-context → confirmation)
- [ ] **INTERVIEW-03**: Interview answers create or update a `FoodItem`; brands/restaurants run a re-grounding pass with tools to populate nutrition
- [ ] **INTERVIEW-04**: If post-interview confidence is still below threshold, commit best-effort with `is_verified=false` (no infinite interview loops)
- [ ] **INTERVIEW-05**: User can override an existing identification (`identification_method=USER_CORRECTED`)
- [ ] **INTERVIEW-06**: `USER_CORRECTED` invalidates the offending `FoodVisual` and writes a new one for the correct `FoodItem`

### Output

- [ ] **OUTPUT-01**: Bot pushes a per-meal result message when `MealLog.processing_status=COMPLETED`
- [ ] **OUTPUT-02**: Per-meal message contains display name(s), estimated portion (discrete bucket), macros, verification status, identification method
- [ ] **OUTPUT-03**: Daily summary message fires at a configurable time (default 03:00 local) summarising the previous day
- [ ] **OUTPUT-04**: `/today` returns today's meals + totals on demand
- [ ] **OUTPUT-05**: `/week` returns the last 7 days' summary on demand
- [ ] **OUTPUT-06**: `/summary` returns an on-demand summary for the current day
- [ ] **OUTPUT-07**: `/fix <entry_id>` re-opens the interview flow for that segment
- [ ] **OUTPUT-08**: `/delete <entry_id>` removes a `DiaryEntry` and invalidates its linked `FoodVisual`

### Infra

- [x] **INFRA-01**: A single `docker-compose.yml` brings up app + Postgres+pgvector + SearXNG + Firecrawl
- [x] **INFRA-02**: All LLM calls go through OpenRouter via the OpenAI SDK with swapped `base_url` (vision, tool calls, structured outputs through SDK; multimodal embeddings via a thin `httpx` wrapper)
- [x] **INFRA-03**: Runtime config (OpenRouter key, Telegram bot token + chat id, ingest secret, confidence thresholds, summary time + TZ) is loaded from an env file
- [ ] **INFRA-04**: Pipeline state machine includes a `FAILED` status; a janitor job resets `*ING` rows stuck longer than 10 minutes
- [x] **INFRA-05**: The full stack runs arm64 on the Mac mini and the same `docker-compose.yml` works on amd64 (multi-arch images preferred)

## v2 Requirements

Deferred to a later milestone. Tracked but not in v1 roadmap.

### Cold Start & Calibration

- **BOOT-01**: Bootstrap mode — relaxed thresholds for the first N meals, then auto-ratchet
- **BOOT-02**: Seed-photos command — pre-populate FoodVisuals from a folder of labeled images
- **CAL-01**: Empirical confidence-threshold recalibration tool using post-interview outcomes

### Bot Polish

- **OUTPUT2-01**: `/last` — show the most recent meal
- **OUTPUT2-02**: `/status` — pipeline / queue / scheduler health
- **OUTPUT2-03**: `/why <entry_id>` — surface the audit trail for an identification
- **OUTPUT2-04**: `/find <food>` — search history by food name
- **OUTPUT2-05**: Free-text conversational diary queries

### Resilience

- **OPS-01**: Interview-fatigue throttle — cap open interview sessions
- **OPS-02**: Structured JSON logging + per-meal token + USD cost log

## Out of Scope

Explicitly excluded from this project. Includes reasoning to prevent re-adding.

| Feature | Reason |
|---------|--------|
| Mobile app | Telegram + iOS Shortcut covers entry/output without app dev cost |
| Real-time / sub-minute latency SLA | Async pipeline; minutes is fine |
| Multi-user / OAuth | Single-user personal tool; auth = shared secret |
| Direct image upload via Telegram | iOS Shortcut is the only photo entry path by design |
| Calorie goals, streaks, gamification | Logger, not a planner |
| Recipe builder / meal planning | Logger, not a planner |
| Pre-loaded USDA / open-food-facts seed DB | Conflicts with self-improving vocabulary thesis |
| Barcode scanner | No app surface, and the photo pipeline subsumes this need |
| Manual food-search UI | Interview flow is the manual path |

## Traceability

Phase mapping populated by roadmapper on 2026-05-24. Status updated as phases complete.

| Requirement | Phase | Status |
|-------------|-------|--------|
| INGEST-01 | Phase 1 | Complete |
| INGEST-02 | Phase 1 | Complete |
| INGEST-03 | Phase 1 | Complete |
| INGEST-04 | Phase 1 | Complete |
| INGEST-05 | Phase 1 | Complete |
| VISION-01 | Phase 2 | Complete |
| VISION-02 | Phase 2 | Complete |
| VISION-03 | Phase 2 | Complete |
| VISION-04 | Phase 2 | Complete |
| MATCH-01 | Phase 1 | Complete |
| MATCH-02 | Phase 3 | Pending |
| MATCH-03 | Phase 3 | Pending |
| MATCH-04 | Phase 3 | Pending |
| REASON-01 | Phase 4 | Pending |
| REASON-02 | Phase 4 | Pending |
| REASON-03 | Phase 4 | Pending |
| REASON-04 | Phase 4 | Pending |
| GROUND-01 | Phase 5 | Pending |
| GROUND-02 | Phase 5 | Pending |
| GROUND-03 | Phase 5 | Pending |
| INTERVIEW-01 | Phase 4 | Pending |
| INTERVIEW-02 | Phase 4 | Pending |
| INTERVIEW-03 | Phase 4 | Pending |
| INTERVIEW-04 | Phase 4 | Pending |
| INTERVIEW-05 | Phase 4 | Pending |
| INTERVIEW-06 | Phase 4 | Pending |
| OUTPUT-01 | Phase 6 | Pending |
| OUTPUT-02 | Phase 6 | Pending |
| OUTPUT-03 | Phase 6 | Pending |
| OUTPUT-04 | Phase 6 | Pending |
| OUTPUT-05 | Phase 6 | Pending |
| OUTPUT-06 | Phase 6 | Pending |
| OUTPUT-07 | Phase 6 | Pending |
| OUTPUT-08 | Phase 6 | Pending |
| INFRA-01 | Phase 1 | Complete |
| INFRA-02 | Phase 1 | Complete |
| INFRA-03 | Phase 1 | Complete |
| INFRA-04 | Phase 4 | Pending |
| INFRA-05 | Phase 1 | Complete |

**Coverage:**
- v1 requirements: 39 total
- Mapped to phases: 39
- Unmapped: 0 (complete)

---
*Requirements defined: 2026-05-24*
*Last updated: 2026-05-27 — Vision retry + IoU dedupe completed in Phase 2 plan 02-03*
