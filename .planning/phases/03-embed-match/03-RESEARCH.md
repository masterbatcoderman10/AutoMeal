# Phase 03: Embed & Match - Research

**Researched:** 2026-05-27
**Domain:** Multimodal embeddings, pgvector similarity search, transactional meal resolution
**Confidence:** MEDIUM

<user_constraints>
## User Constraints (from CONTEXT.md) [VERIFIED: codebase grep]

### Locked Decisions
### Seed Contract
- **D-01:** Production `FoodVisuals` may start empty. Empty index behavior is valid and should not be treated as infrastructure failure.
- **D-02:** Phase 3 UAT uses existing local `sample_images/*.HEIC` as seed material.
- **D-03:** The planner may segment sample images and create 1-2 hardcoded demo `FoodItem` rows with known nutrition values for smoke/UAT. This is a demo seed path only, not a preloaded food database.
- **D-04:** UAT should include both an exact/self-similarity embedding check and a same-food/different-photo similarity check when the sample images allow it.
- **D-05:** Seed helper placement is at agent discretion. A script under `scripts/`, such as `scripts/seed_demo_foods.py`, is appropriate if the planner wants an operator-run UAT helper; reusable helper code for tests is also acceptable.

### Embedding And Matching Semantics
- **D-06:** Matching is strictly per `MealSegment` crop. Do not embed or match the whole meal image for Phase 3 match logic.
- **D-07:** Use `output_dimensionality=1536` for all embeddings. Use `task_type=RETRIEVAL_DOCUMENT` for `FoodVisual` writes and `task_type=RETRIEVAL_QUERY` for segment searches.
- **D-08:** The auto-match threshold remains `score >= 0.85` for SIMILARITY matches.
- **D-09:** No-match or below-threshold match is an expected branch. It should move the meal to `REASONING`, create no `DiaryEntry`, and leave resolution to Phase 4.
- **D-10:** Tests should cover below-threshold match -> `REASONING` with no `DiaryEntry`; this branch is not a Phase 3 failure.
- **D-11:** On no-match, send one transparent Telegram note that the meal was seen but is not known yet and will need future identification/interview capability.
- **D-12:** If any segment in a meal is unresolved, hold all `DiaryEntry` creation for that meal. Do not create partial diary entries for matched segments while any segment remains unmatched.

### Portion And Nutrition Defaults
- **D-13:** Every Phase 3 similarity-created `DiaryEntry` uses `portion_bucket=STANDARD`.
- **D-14:** Telegram output should not caveat that the portion is defaulted or assumed.
- **D-15:** Treat `FoodItem` calories/macros as standard-portion values directly. Do not scale from `serving_size_g` in Phase 3.
- **D-16:** Telegram nutrition output uses only fields already present on matched `FoodItem` rows. Omit missing nutrition fields and never invent values.

### Telegram Result Shape
- **D-17:** For Phase 3 dev/UAT clarity, include identification method and verified flag in the Telegram meal result. Later UX phases may hide this if it feels noisy.
- **D-18:** Use a two-line per-item style for partial nutrition fields: item identity/status on one line, known nutrition fields on the next.
- **D-19:** Include a total line for known summed fields only. Sum calories/macros when present; omit unavailable totals.
- **D-20:** Keep the result user-facing and terse. Do not expose embedding scores, raw vector details, or debug traces in Telegram.

### FoodVisual Write-Back
- **D-21:** For a fully resolved similarity-matched meal, append a new `FoodVisual` for every auto-matched segment.
- **D-22:** Duplicate confirmations of the same food create multiple `FoodVisual` rows. Do not dedupe same-food visuals in Phase 3.
- **D-23:** If any segment is unmatched and the meal moves to `REASONING`, do not append new `FoodVisual` rows for the matched segments yet.
- **D-24:** For fully matched meals, write `DiaryEntry` rows, write new `FoodVisual` rows, and transition `MealLog.processing_status` to `COMPLETED` in the same database transaction.
- **D-25:** Telegram notification success should not be required for the database transaction to commit.

### the agent's Discretion
- The planner may choose the exact seed helper shape and filename.
- The planner may decide whether the embedding/match logic lives in new service modules or in the existing polling module first, as long as the resulting design follows the repo's status-driven worker pattern.

### Deferred Ideas (OUT OF SCOPE)
None - discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements [VERIFIED: codebase grep]

| ID | Description | Research Support |
|----|-------------|------------------|
| MATCH-02 | Per-crop multimodal embedding is generated with `output_dimensionality=1536`, `task_type=RETRIEVAL_DOCUMENT` on writes / `RETRIEVAL_QUERY` on searches; stored on `MealSegment.embedding` [VERIFIED: codebase grep] | Summary, Standard Stack, Architecture Patterns Pattern 1 and Pattern 3, Common Pitfalls 1 and 2, Code Examples 1 [CITED: https://openrouter.ai/docs/api/reference/embeddings] [CITED: https://ai.google.dev/api/embeddings] |
| MATCH-03 | HNSW cosine index (`m=16, ef_construction=64`) on `FoodVisuals.embedding`; cosine similarity search returns the top match + score [VERIFIED: codebase grep] | Summary, Standard Stack, Don't Hand-Roll, Code Examples 2, Common Pitfalls 2 [CITED: https://github.com/pgvector/pgvector] [CITED: https://github.com/pgvector/pgvector-python] |
| MATCH-04 | On confirmed identification (any method) a `FoodVisual` row is written so the visual vocabulary grows [VERIFIED: codebase grep] | Summary, Architecture Patterns Pattern 2, Common Pitfalls 3 and 4, Validation Architecture [VERIFIED: codebase grep] |
</phase_requirements>

## Project Constraints (from AGENTS.md) [VERIFIED: codebase grep]

- Keep the locked stack: Python + FastAPI backend, Postgres + pgvector, `python-telegram-bot`, APScheduler, and `docker-compose`; do not research alternatives that replace this baseline. [VERIFIED: codebase grep]
- LLM access stays OpenRouter-only; chat/tools use the OpenAI SDK shape, while multimodal embeddings use a thin raw `httpx` wrapper. [VERIFIED: codebase grep]
- Deployment remains a single `docker-compose.yml` with local-only ingestion and a single pinned Telegram chat ID. [VERIFIED: codebase grep]
- GSD execution must stay worktree-based; planning should not assume direct ad hoc repo edits outside the workflow. [VERIFIED: codebase grep]
- Shell commands in downstream plans should prefer the local `rtk` wrapper because the repo explicitly asks for it. [VERIFIED: codebase grep]

## Summary

Phase 3 should extend the existing bot-owned, status-driven worker pipeline instead of adding a second queue or service bus: the repo already uses `SELECT ... FOR UPDATE SKIP LOCKED` polling against `MealLog.processing_status`, and `MealProcessingStatus` already includes `EMBEDDING`, `MATCHING`, `REASONING`, and `COMPLETED`. [VERIFIED: codebase grep] The important repo mismatch is that the current segment worker still marks meals `COMPLETED` and sends the Phase 2 label-only message immediately after segmentation, so Phase 3 must move the success handoff to `SEGMENTING -> EMBEDDING` and reserve `COMPLETED` for the post-match transaction. [VERIFIED: codebase grep]

The existing `OpenRouterClient.embed_multimodal()` method is the correct reuse point, but it is not yet Phase 3 safe: it does no response-shape validation, it does not distinguish retryable transport/status failures, and its default `task_type` is `RETRIEVE_DOCUMENT`, while Google's documented enum is `RETRIEVAL_DOCUMENT`. [VERIFIED: codebase grep] [CITED: https://ai.google.dev/api/embeddings] OpenRouter's current embeddings docs confirm the multimodal `input[].content[]` request shape and image support, and the Gemini Embedding 2 model page confirms a unified text-image space with recommended 1536-dimensional output, so a thin hardened wrapper remains the right architecture. [CITED: https://openrouter.ai/docs/api/reference/embeddings] [CITED: https://openrouter.ai/google/gemini-embedding-2-preview/api] [CITED: https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-embedding-2/]

The planner should treat calibration as Wave 0, not as optional polish. The roadmap explicitly requires same-image self-similarity `>= 0.99` and a cross-modal sanity check before match logic, because Phase 3 is only valid if text queries and image crops land in a useful shared space. [VERIFIED: codebase grep] If the seed/demo set cannot produce stable same-image and same-food ranking behavior at 1536 dimensions, stop the phase and surface the embedding-model decision instead of shipping brittle threshold logic. [VERIFIED: codebase grep] [ASSUMED]

**Primary recommendation:** Build Phase 3 as a vertical slice with four bounded waves: calibration gate, hardened embedding wrapper, transactional match/write-back path, and final Telegram completion push. [VERIFIED: codebase grep] [ASSUMED]

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|--------------|----------------|-----------|
| Crop embedding generation | API / Backend | Database / Storage | The bot worker reads saved crop files and calls OpenRouter; only the resulting vector is persisted. [VERIFIED: codebase grep] [CITED: https://openrouter.ai/docs/api/reference/embeddings] |
| Nearest-neighbor similarity search | Database / Storage | API / Backend | pgvector owns cosine distance computation and HNSW acceleration; backend only supplies the query vector and threshold decision. [VERIFIED: codebase grep] [CITED: https://github.com/pgvector/pgvector] |
| Match thresholding and meal branching | API / Backend | Database / Storage | `score >= 0.85` and all-or-nothing meal resolution are application rules applied after DB search results return. [VERIFIED: codebase grep] |
| `DiaryEntry` + `FoodVisual` write-back | API / Backend | Database / Storage | The backend must create rows and change `MealLog.processing_status` inside one transaction. [VERIFIED: codebase grep] |
| Telegram meal-result push | API / Backend | -- | PTB `send_message()` is backend-side only; Telegram success is explicitly non-transactional. [VERIFIED: codebase grep] [CITED: https://docs.python-telegram-bot.org/en/latest/telegram.bot.html] |
| Calibration / smoke gating | API / Backend | Database / Storage | Scripts/tests orchestrate live embeddings and local seeded visuals before the main match flow is trusted. [VERIFIED: codebase grep] [ASSUMED] |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `httpx` | `0.27.2` repo pin; `0.28.1` current on PyPI [VERIFIED: codebase grep] [VERIFIED: PyPI] | Raw OpenRouter embedding client | The phase needs explicit JSON control for multimodal `input[].content[]`, timeout tuning, and error handling around the OpenRouter embeddings endpoint. [CITED: https://openrouter.ai/docs/api/reference/embeddings] [CITED: https://www.python-httpx.org/advanced/timeouts/] |
| `openai` | `1.55.3` repo pin; `2.38.0` current on PyPI [VERIFIED: codebase grep] [VERIFIED: PyPI] | Existing chat/tool path only | Keep it for detect/segment/label and later reasoning; do not introduce a second chat client. Multimodal embeddings still stay on raw `httpx`. [VERIFIED: codebase grep] [CITED: https://openrouter.ai/google/gemini-embedding-2-preview/api] |
| `SQLAlchemy[asyncio]` | `2.0.36` repo pin; `2.0.50` current on PyPI [VERIFIED: codebase grep] [VERIFIED: PyPI] | Async transaction orchestration | The repo already uses async ORM sessions and can express transactional writes and cosine-distance ordering without bypassing the existing DB layer. [VERIFIED: codebase grep] [CITED: https://github.com/pgvector/pgvector-python] |
| `asyncpg` | `0.30.0` repo pin; `0.31.0` current on PyPI [VERIFIED: codebase grep] [VERIFIED: PyPI] | Postgres transport | Keep the existing async driver pairing; this phase adds query patterns, not a driver change. [VERIFIED: codebase grep] |
| `pgvector` (Python) | `0.3.6` repo pin; `0.4.2` current on PyPI [VERIFIED: codebase grep] [VERIFIED: PyPI] | Vector column type and cosine-distance helpers | The repo already models both `MealSegment.embedding` and `FoodVisual.embedding` as `Vector(1536)` and uses an HNSW cosine index on `FoodVisuals`. [VERIFIED: codebase grep] [CITED: https://github.com/pgvector/pgvector-python] |
| `python-telegram-bot` | `22.7` repo pin and current on PyPI [VERIFIED: codebase grep] [VERIFIED: PyPI] | Completion push delivery | PTB remains the existing async bot surface; Phase 3 only extends message composition and dispatch timing. [VERIFIED: codebase grep] [CITED: https://docs.python-telegram-bot.org/en/stable/] |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `tenacity` | `9.0.0` repo pin; `9.1.4` current on PyPI [VERIFIED: codebase grep] [VERIFIED: PyPI] | Bounded async retries | Wrap only retryable OpenRouter embedding failures such as `429`, `503`, transport timeouts, and provider overload; do not retry schema/validation failures. [CITED: https://openrouter.ai/docs/api/reference/errors-and-debugging] [CITED: https://tenacity.readthedocs.io/en/stable/index.html] |
| `Pillow` | `10.4.0` repo pin [VERIFIED: codebase grep] | Crop file IO reuse | Use the already-saved crop JPEGs from Phase 2; do not recrop originals during match time unless a crop is missing or corrupted. [VERIFIED: codebase grep] |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Raw `httpx` embedding POST | OpenAI SDK embeddings call | The repo already chose raw `httpx` because the phase needs direct multimodal payload control; adding a second embeddings abstraction increases risk without reducing code. [VERIFIED: codebase grep] [CITED: https://openrouter.ai/docs/api/reference/embeddings] |
| HNSW cosine search | Exact scan over `FoodVisuals` | Exact scan is simpler at tiny scale, but HNSW + cosine is already a locked schema requirement and already present in the migration/model layer. [VERIFIED: codebase grep] [CITED: https://github.com/pgvector/pgvector] |
| Whole-meal embedding | Per-segment embedding only | Whole-meal embeddings directly violate D-06 and blur the visual-vocabulary loop the phase is trying to prove. [VERIFIED: codebase grep] |

**Installation:** No new packages are required for Phase 3; reuse the repo-pinned dependencies already in `requirements.txt`. [VERIFIED: codebase grep]

## Package Legitimacy Audit

No new external packages are introduced by this phase; the phase reuses the existing pinned Python stack, so the package-legitimacy gate is not required for planning this slice. [VERIFIED: codebase grep]

## Architecture Patterns

### System Architecture Diagram

```text
iOS Shortcut photo
    |
    v
FastAPI ingest -> MealLog(PENDING)
    |
    v
bot.poll_and_acknowledge -> DETECTING -> SEGMENTING
    |
    v
Phase 2 segment worker saves crops + labels
    |
    v
MealLog(EMBEDDING)
    |
    v
embed worker
    |- read MealSegment.cropped_image_url
    |- POST OpenRouter /embeddings
    |- validate len == 1536
    `- persist MealSegment.embedding
    |
    v
MealLog(MATCHING)
    |
    v
match worker
    |- query FoodVisuals where is_invalidated = false
    |- order by cosine distance, compute score = 1 - distance
    |- if any segment score < 0.85 -> REASONING + no-match note
    `- else begin transaction
           |- create DiaryEntry per segment
           |- create new FoodVisual per segment
           |- set portion_bucket=STANDARD
           `- MealLog(COMPLETED)
    |
    v
Telegram result push
```

### Recommended Project Structure

```text
app/
├── services/
│   ├── llm_client.py          # Harden embed_multimodal() instead of adding a second client
│   ├── embedding_service.py   # calibration + request/response validation + retries [ASSUMED]
│   └── matching_service.py    # top-match query, thresholding, transaction helpers [ASSUMED]
app/models/
├── meal_segment.py            # per-crop embedding target
├── food_visual.py             # visual corpus + HNSW index
└── diary_entry.py             # similarity-committed output rows
bot/
├── polling.py                 # status-driven workers only
└── messages.py                # final nutrition/no-match text formatting
scripts/
└── seed_demo_foods.py         # demo seed + calibration helper
tests/
├── test_bot_contract.py       # worker/message flow contract tests
├── test_embedding_service.py  # new wrapper + calibration unit tests [ASSUMED]
└── test_match_flow.py         # new DB-backed integration tests [ASSUMED]
```

### Pattern 1: Status-Driven Handoff, Thin Workers

**What:** Keep `bot/polling.py` responsible for claiming rows, advancing `MealLog.processing_status`, and calling small service-layer helpers; move embedding and matching logic into focused service modules. [VERIFIED: codebase grep] [ASSUMED]

**When to use:** Use this for every new pipeline stage in Phase 3 so the app stays consistent with the Phase 1 and Phase 2 worker pattern. [VERIFIED: codebase grep]

**Example:**

```python
# Source: repo worker pattern + OpenRouter embeddings docs
async def poll_and_embed_segments(bot, settings, poll_interval):
    async with session_factory() as session:
        meal = await claim_meal(session, MealProcessingStatus.EMBEDDING)
        if meal is None:
            return

        segment_rows = await load_segments(session, meal.id)
        for segment in segment_rows:
            segment.embedding = await embedding_service.embed_crop(
                crop_path=segment.cropped_image_url,
                model=settings.EMBED_MODEL,
                output_dimensionality=1536,
                task_type="RETRIEVAL_QUERY",
            )
        meal.processing_status = MealProcessingStatus.MATCHING
        await session.commit()
```

### Pattern 2: Resolve Entire Meal Before Commit

**What:** Load every segment, compute the top match for each one, and branch only after the entire meal has been evaluated. If any segment is unresolved, commit only the `REASONING` transition and optional no-match note; otherwise commit all `DiaryEntry` rows, all new `FoodVisual` rows, and the `COMPLETED` transition together. [VERIFIED: codebase grep] [ASSUMED]

**When to use:** Use this for the final match stage so D-12, D-23, and D-24 stay true. [VERIFIED: codebase grep]

**Example:**

```python
# Source: repo transaction rules + phase decisions
async with session.begin():
    if any(result.score < 0.85 for result in match_results):
        meal.processing_status = MealProcessingStatus.REASONING
        return

    for result in match_results:
        session.add(
            DiaryEntry(
                id=str(uuid4()),
                meal_log_id=meal.id,
                food_item_id=result.food_item_id,
                segment_id=result.segment_id,
                portion_bucket="STANDARD",
                identification_method="SIMILARITY",
                is_verified=result.food_item_is_verified,
            )
        )
        session.add(
            FoodVisual(
                id=str(uuid4()),
                food_item_id=result.food_item_id,
                cropped_image_url=result.crop_path,
                embedding=result.query_embedding,
                is_invalidated=False,
            )
        )
    meal.processing_status = MealProcessingStatus.COMPLETED
```

### Pattern 3: Calibration Gate Before Threshold Logic

**What:** Run a live or smoke calibration step that proves same-image determinism, same-food nearest-neighbor behavior, and cross-modal text-image sanity before trusting the `0.85` threshold. [VERIFIED: codebase grep] [ASSUMED]

**When to use:** Run this in Wave 0 and again after any model-id or request-shape change. [VERIFIED: codebase grep] [ASSUMED]

**Example:**

```python
# Source: roadmap calibration note + Gemini Embedding 2 multimodal capability docs
self_score = cosine(embed(img_a), embed(img_a_again))
assert self_score >= 0.99

query = embed_text("rice and lentils", task_type="RETRIEVAL_QUERY")
photo_scores = rank_against_seeded_photos(query)
assert photo_scores[0].label == "daal chawal"
```

### Anti-Patterns to Avoid

- **Completing at segmentation time:** Phase 2 currently does this; Phase 3 must stop it or final result pushes, `DiaryEntry` creation, and `FoodVisual` growth cannot be sequenced correctly. [VERIFIED: codebase grep]
- **Comparing cosine distance directly to `0.85`:** pgvector returns cosine distance with `<=>`; the Phase 3 threshold is similarity, so compare `1 - distance`. [CITED: https://github.com/pgvector/pgvector]
- **Writing `FoodVisual` rows for partially matched meals:** D-23 forbids this and it pollutes the corpus with unresolved crops. [VERIFIED: codebase grep]
- **Retrying malformed payloads:** Validation and enum mistakes should fail fast; only transport/status failures should retry. [CITED: https://www.python-httpx.org/exceptions/] [CITED: https://tenacity.readthedocs.io/en/stable/index.html]

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Vector nearest-neighbor search | Python loops over all `FoodVisual` rows plus manual cosine math | pgvector cosine ordering and HNSW index | The DB already stores vectors and exposes cosine distance/similarity directly, with index support and filtering. [VERIFIED: codebase grep] [CITED: https://github.com/pgvector/pgvector] |
| Ad hoc background queue | New Redis/Celery pipeline for Phase 3 | Existing polling workers keyed by `MealProcessingStatus` | The repo already has the coordination pattern and tests for it. [VERIFIED: codebase grep] |
| Custom retry loops | `while True` network retry code in the wrapper | `tenacity.AsyncRetrying` plus `Retry-After` honoring | OpenRouter documents `Retry-After` on `429` and `503`, and Tenacity already supports bounded async retry policies. [CITED: https://openrouter.ai/docs/api/reference/errors-and-debugging] [CITED: https://tenacity.readthedocs.io/en/stable/index.html] |
| Second crop pipeline | Re-cropping originals during matching | Reuse `MealSegment.cropped_image_url` | Phase 2 already saved canonical crop JPEGs for later phases. [VERIFIED: codebase grep] |

**Key insight:** Phase 3 is mostly orchestration and transaction design, not new infrastructure. The fastest safe plan is to harden the existing surfaces instead of adding new ones. [VERIFIED: codebase grep] [ASSUMED]

## Common Pitfalls

### Pitfall 1: Wrong Embedding Enum or Shape

**What goes wrong:** OpenRouter receives a structurally valid request that does not actually express the intended Gemini task semantics, or the response length is not checked and a bad vector silently lands in the DB. [VERIFIED: codebase grep] [ASSUMED]

**Why it happens:** The repo currently defaults to `RETRIEVE_DOCUMENT`, but Google's enum is `RETRIEVAL_DOCUMENT`; OpenRouter's generic embeddings docs describe the multimodal `input[].content[]` shape but not Gemini-specific enum names on the page itself. [VERIFIED: codebase grep] [CITED: https://ai.google.dev/api/embeddings] [CITED: https://openrouter.ai/docs/api/reference/embeddings]

**How to avoid:** Make task type an explicit argument per call, validate `len(embedding) == 1536`, and add a live smoke test before wiring the match loop. [VERIFIED: codebase grep] [ASSUMED]

**Warning signs:** `400` responses, successful responses with unexpected vector length, or calibration scores far below the roadmap thresholds. [CITED: https://openrouter.ai/docs/api/reference/errors-and-debugging] [ASSUMED]

### Pitfall 2: Distance/Similarity Mix-Up

**What goes wrong:** A real match is rejected or a bad match is accepted because the code compares cosine distance to a similarity threshold. [CITED: https://github.com/pgvector/pgvector]

**Why it happens:** pgvector's cosine operator returns distance, while the phase decision is expressed as similarity `>= 0.85`. [CITED: https://github.com/pgvector/pgvector] [VERIFIED: codebase grep]

**How to avoid:** Compute `score = 1 - cosine_distance` in the query or immediately after fetching the top result, and keep the threshold comparison in one place. [CITED: https://github.com/pgvector/pgvector-python] [ASSUMED]

**Warning signs:** Scores clustering near `0.1` to `0.2` for obvious matches, or tests passing only when the threshold is inverted. [ASSUMED]

### Pitfall 3: Completing the Meal Too Early

**What goes wrong:** The bot sends the old Phase 2 label sentence, the meal leaves the work queue, and no embedding/match worker ever sees it. [VERIFIED: codebase grep]

**Why it happens:** `poll_and_segment_food()` still sets `MealLog.processing_status = COMPLETED` and sends the result sentence immediately after labeling. [VERIFIED: codebase grep]

**How to avoid:** Make segmentation commit `EMBEDDING`, not `COMPLETED`, and move the Phase 3 final result push to the successful end of the match transaction or immediately after it. [VERIFIED: codebase grep] [ASSUMED]

**Warning signs:** New crops exist in `meal_segments`, but no `embedding` values, no `DiaryEntry` rows, and no `FoodVisual` write-back after a happy-path meal. [VERIFIED: codebase grep] [ASSUMED]

### Pitfall 4: Corpus Pollution from Partial Matches

**What goes wrong:** The system learns from unresolved or ambiguous crops and drifts toward reinforcing bad IDs. [VERIFIED: codebase grep] [ASSUMED]

**Why it happens:** It is tempting to write matched segments immediately and defer only the unmatched one, but D-12 and D-23 forbid partial write-back. [VERIFIED: codebase grep]

**How to avoid:** Hold all `FoodVisual` and `DiaryEntry` writes until every segment has either passed similarity or the meal is rerouted to `REASONING`. [VERIFIED: codebase grep]

**Warning signs:** Meals in `REASONING` already have new `FoodVisual` rows, or duplicate diary entries appear for meals with unresolved segments. [VERIFIED: codebase grep] [ASSUMED]

### Pitfall 5: Treating Telegram Delivery as Transactional

**What goes wrong:** A temporary bot/API failure undoes a correct DB commit and forces unnecessary retries. [VERIFIED: codebase grep]

**Why it happens:** The current Phase 2 worker sends the Telegram message after commit; Phase 3 needs to preserve that separation for final result pushes as well. [VERIFIED: codebase grep]

**How to avoid:** Commit the DB transaction first, then best-effort `send_message()`, logging but not rolling back on Telegram failure. [VERIFIED: codebase grep] [CITED: https://docs.python-telegram-bot.org/en/latest/telegram.bot.html]

**Warning signs:** `DiaryEntry` rows disappear after a bot outage, or `COMPLETED` meals get retried because the push failed. [ASSUMED]

## Code Examples

Verified patterns from official sources:

### OpenRouter Multimodal Embedding Request

```python
# Source: https://openrouter.ai/docs/api/reference/embeddings
payload = {
    "model": "google/gemini-embedding-2-preview",
    "input": [
        {
            "content": [
                {"type": "text", "text": "rice and lentils"},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]
        }
    ],
    # Phase-local semantic requirement:
    "dimensions": 1536,
    "task_type": "RETRIEVAL_QUERY",  # see Google task enum docs
}
response = await httpx_client.post("/embeddings", json=payload)
response.raise_for_status()
embedding = response.json()["data"][0]["embedding"]
assert len(embedding) == 1536
```

### SQLAlchemy + pgvector Cosine Search

```python
# Source: https://github.com/pgvector/pgvector-python
score_expr = 1 - FoodVisual.embedding.cosine_distance(query_embedding)
stmt = (
    select(
        FoodVisual.id,
        FoodVisual.food_item_id,
        score_expr.label("score"),
    )
    .where(FoodVisual.is_invalidated.is_(False))
    .order_by(FoodVisual.embedding.cosine_distance(query_embedding))
    .limit(1)
)
top_match = (await session.execute(stmt)).first()
```

### Bounded Async Retry Skeleton

```python
# Source: https://openrouter.ai/docs/api/reference/errors-and-debugging
# Source: https://tenacity.readthedocs.io/en/stable/index.html
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

async for attempt in AsyncRetrying(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError)),
    reraise=True,
):
    with attempt:
        response = await client.post("/embeddings", json=payload)
        if response.status_code in {429, 503}:
            response.raise_for_status()
        response.raise_for_status()
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Text-only embeddings and separate modality pipelines | Gemini Embedding 2 unified text-image embedding space | March 10, 2026 public preview; GA announced April 22, 2026 [CITED: https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-embedding-2/] [CITED: https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-embedding-2-generally-available/] | Makes the Phase 3 cross-modal sanity check meaningful instead of speculative. |
| Fixed-width embedding assumptions | Flexible output dimensions with MRL; Google recommends `3072`, `1536`, or `768` | March 10, 2026 [CITED: https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-embedding-2/] | Confirms that the phase-local `1536` target is valid even though the broader project stack research later preferred `768`. |
| IVFFlat as the common pgvector default | HNSW is the preferred speed/recall tradeoff for pgvector ANN search | Current pgvector 0.8 docs [CITED: https://github.com/pgvector/pgvector] | Supports keeping the locked schema/index choice from Phase 1. |

**Deprecated/outdated:**

- Repo default `task_type="RETRIEVE_DOCUMENT"` in `app/services/llm_client.py` should be treated as incorrect for Gemini task semantics. [VERIFIED: codebase grep] [CITED: https://ai.google.dev/api/embeddings]
- The old Phase 2 assumption that segmentation completion equals meal completion is outdated once embedding and match stages exist. [VERIFIED: codebase grep]

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Splitting the implementation into `embedding_service.py` and `matching_service.py` is the cleanest extension point, even though the context leaves exact module placement to planner discretion. [ASSUMED] | Architecture Patterns | Low - the planner can keep the logic inside `bot/polling.py` if it preserves the worker pattern. |
| A2 | A bounded `tenacity` policy with 3 attempts and exponential backoff is the right first-pass retry envelope for Phase 3 embeddings. [ASSUMED] | Code Examples, Common Pitfalls | Low - the exact retry counts can be tuned without changing the architecture. |
| A3 | The match worker should be a separate handoff from the embed worker instead of one giant `EMBEDDING` stage. [ASSUMED] | Summary, Architecture Patterns | Medium - merging them is possible, but it weakens observability and phase verification. |

## Open Questions (RESOLVED)

1. **OpenRouter embedding contract ambiguity is resolved as a Wave 0 live-smoke gate, not downstream implementation uncertainty.**
   - What we know: OpenRouter documents the multimodal `input[].content[]` shape and OpenAI-compatible embeddings endpoint, while Google documents the Gemini task enums and reduced-dimensionality semantics. [CITED: https://openrouter.ai/docs/api/reference/embeddings] [CITED: https://ai.google.dev/api/embeddings]
   - Resolution: Phase 03 must begin with a live OpenRouter smoke verification that exercises the real `google/gemini-embedding-2-preview` model id with `dimensions=1536` plus the intended `task_type` values, then blocks all threshold-match implementation if the provider rejects or normalizes them incorrectly. This is now a Wave 0 calibration blocker in planning, not an open research dependency. [VERIFIED: codebase grep] [ASSUMED]

2. **`FoodItem.times_confirmed` is explicitly out of Phase 3 scope.**
   - What we know: The column exists and semantically fits confirmation counting. [VERIFIED: codebase grep]
   - Resolution: No locked decision in `.planning/phases/03-embed-match/03-CONTEXT.md`, `.planning/ROADMAP.md`, or `.planning/REQUIREMENTS.md` requires `times_confirmed` updates for MATCH-02 through MATCH-04, so Phase 03 should not plan or block on that field. If later phases want confirmation analytics, they can add it explicitly. [VERIFIED: codebase grep]

3. **Same-food/different-photo HEIC coverage is resolved as an operator calibration input with a hard stop.**
   - What we know: The files are present in this checkout and the context allows 1-2 hardcoded demo `FoodItem` rows plus segmentation-based seeding. [VERIFIED: local command] [VERIFIED: codebase grep]
   - Resolution: Wave 0 must require the operator to identify at least one usable same-food/different-photo pair from `sample_images/*.HEIC`, record the chosen pair for calibration, and stop Phase 03 execution if no pair supports the required UAT. That makes the sample-set question a calibration precondition, not an unresolved planning gap. [VERIFIED: local command] [ASSUMED]

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Docker | Local stack, Postgres, bot/app orchestration | Yes [VERIFIED: local command] | `29.4.0` [VERIFIED: local command] | -- |
| Docker Compose | Local stack orchestration | Yes [VERIFIED: local command] | `v5.1.2` [VERIFIED: local command] | `docker-compose` alias if present [ASSUMED] |
| `uv` | Python env/package workflow | Yes [VERIFIED: local command] | `0.10.0` [VERIFIED: local command] | Plain `pip` if needed [ASSUMED] |
| Project venv Python | Running scripts/tests | Yes [VERIFIED: local command] | `3.13.12` [VERIFIED: local command] | System `python3 3.14.4` exists, but does not reflect the project env. [VERIFIED: local command] |
| `pytest` in active env | Fast test command from planner template | No [VERIFIED: local command] | -- | Use `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`. [VERIFIED: local command] |
| `psql` CLI | Manual DB inspection | No [VERIFIED: local command] | -- | Use `docker compose exec db psql ...` or SQLAlchemy scripts. [VERIFIED: local command] [ASSUMED] |
| `sample_images/*.HEIC` | Seed/calibration/UAT | Yes in this checkout [VERIFIED: local command] | 6 files [VERIFIED: local command] | In worktrees, copy from the primary checkout if missing. [VERIFIED: codebase grep] |

**Missing dependencies with no fallback:**

- None discovered for planning. [VERIFIED: local command] [ASSUMED]

**Missing dependencies with fallback:**

- `pytest` is not installed in the project venv, but the current suite runs cleanly with `unittest discover` and completed 50 tests in this checkout. [VERIFIED: local command]
- `psql` is not on PATH, but containerized Postgres access remains available through Docker Compose. [VERIFIED: local command] [ASSUMED]

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | `unittest` test modules executed via Python test discovery; repo also names them `test_*.py`. [VERIFIED: codebase grep] [VERIFIED: local command] |
| Config file | none. [VERIFIED: codebase grep] |
| Quick run command | ``rtk .venv/bin/python -m unittest tests.test_bot_contract`` [VERIFIED: local command] [ASSUMED] |
| Full suite command | ``rtk .venv/bin/python -m unittest discover -s tests -p 'test_*.py'`` [VERIFIED: local command] |

### Phase Requirements -> Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| MATCH-02 | Crop embeddings use 1536 dims, correct task types, and persist to `MealSegment.embedding` | unit + integration | ``rtk .venv/bin/python -m unittest tests.test_embedding_service`` [ASSUMED] | No - Wave 0 |
| MATCH-03 | Top cosine match comes from `FoodVisuals` HNSW search and returns a similarity score | integration | ``rtk .venv/bin/python -m unittest tests.test_match_flow`` [ASSUMED] | No - Wave 0 |
| MATCH-04 | Successful confirmation writes new `FoodVisual` rows; failed similarity branch does not | integration | ``rtk .venv/bin/python -m unittest tests.test_match_flow`` [ASSUMED] | No - Wave 0 |
| Phase 3 SC-4 | Telegram meal-result message fires after `MealLog.processing_status=COMPLETED` and DB commit survives bot failure | unit | ``rtk .venv/bin/python -m unittest tests.test_bot_contract`` [VERIFIED: local command] | Yes |

### Sampling Rate

- **Per task commit:** ``rtk .venv/bin/python -m unittest tests.test_bot_contract`` plus the smallest new Phase 3 module test target. [VERIFIED: local command] [ASSUMED]
- **Per wave merge:** ``rtk .venv/bin/python -m unittest discover -s tests -p 'test_*.py'``. [VERIFIED: local command]
- **Phase gate:** Full suite green plus manual calibration/seed smoke before `$gsd-verify-work`. [VERIFIED: codebase grep] [ASSUMED]

### Wave 0 Gaps

- [ ] `tests/test_embedding_service.py` - wrapper request shape, retries, vector-length validation, same-image self-similarity helper. [ASSUMED]
- [ ] `tests/test_match_flow.py` - seeded `FoodVisual` search, below-threshold `REASONING`, duplicate `FoodVisual` append, atomic completion path. [ASSUMED]
- [ ] DB-backed test fixture or helper for seeded `FoodItem` / `FoodVisual` rows. [ASSUMED]
- [ ] A manual or scripted calibration command using local `sample_images/*.HEIC`. [VERIFIED: codebase grep] [ASSUMED]

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | Keep the existing shared-secret ingestion gate; Phase 3 must not introduce a bypass or new unauthenticated path. [VERIFIED: codebase grep] |
| V3 Session Management | no | No user session surface is introduced in this phase. [VERIFIED: codebase grep] [ASSUMED] |
| V4 Access Control | yes | Hard-pinned single Telegram chat and local-only backend services remain the access boundary. [VERIFIED: codebase grep] |
| V5 Input Validation | yes | Validate crop path presence, response JSON shape, vector length, and threshold logic before DB writes. [VERIFIED: codebase grep] [ASSUMED] |
| V6 Cryptography | no | Phase 3 does not add new cryptographic primitives; continue using provider HTTPS and existing secret handling. [VERIFIED: codebase grep] [ASSUMED] |

### Known Threat Patterns for This Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Untrusted image content sent to external embedding API | Information Disclosure | Send only the crop required for matching, not the whole meal image; keep OpenRouter routing constrained and avoid provider data collection where possible. [CITED: https://openrouter.ai/docs/guides/routing/provider-selection] [ASSUMED] |
| Prompt/corpus poisoning by unresolved visuals | Tampering | Do not write `FoodVisual` rows for `REASONING` meals; only append after confirmed identification. [VERIFIED: codebase grep] |
| DB corruption from malformed embedding responses | Tampering | Enforce response-shape and vector-length validation before assigning `MealSegment.embedding` or `FoodVisual.embedding`. [VERIFIED: codebase grep] [ASSUMED] |
| Replay or branch confusion in worker loops | Repudiation / Tampering | Keep `FOR UPDATE SKIP LOCKED`, explicit state transitions, and one status owner per stage. [VERIFIED: codebase grep] |
| Telegram message disclosure of internal scores/debug data | Information Disclosure | Keep messages terse and user-facing; omit raw scores and vector details. [VERIFIED: codebase grep] |

## Sources

### Primary (HIGH confidence)

- Local codebase (`app/services/llm_client.py`, `bot/polling.py`, `bot/messages.py`, `app/models/*`, `migrations/versions/001_initial_schema.py`, `requirements.txt`, `.planning/*`) - current repo behavior, phase constraints, schema, and test infrastructure. [VERIFIED: codebase grep]
- OpenRouter Embeddings API - multimodal `input[].content[]` shape, image support, deterministic embeddings, provider routing hooks, and retry guidance. [CITED: https://openrouter.ai/docs/api/reference/embeddings]
- OpenRouter Errors and Debugging - `429`/`503` handling and `Retry-After` semantics. [CITED: https://openrouter.ai/docs/api/reference/errors-and-debugging]
- OpenRouter Gemini Embedding 2 model page - current OpenRouter model id, supported dimensions, context length, and text-image unified space. [CITED: https://openrouter.ai/google/gemini-embedding-2-preview/api]
- Google Gemini Embeddings API reference - task enum names, output dimensionality semantics, and request/response fields. [CITED: https://ai.google.dev/api/embeddings]
- Google Gemini Embedding 2 launch/GA posts - multimodal capability, recommended dimensions, and current product status. [CITED: https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-embedding-2/] [CITED: https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-embedding-2-generally-available/]
- pgvector README - cosine distance operator, HNSW behavior, vector dimension ceilings, and `ef_search`. [CITED: https://github.com/pgvector/pgvector]
- pgvector-python README - SQLAlchemy `cosine_distance()` pattern and HNSW SQLAlchemy index configuration. [CITED: https://github.com/pgvector/pgvector-python]
- python-telegram-bot docs - current bot API surface and `send_message()` availability in v22.7. [CITED: https://docs.python-telegram-bot.org/en/stable/] [CITED: https://docs.python-telegram-bot.org/en/latest/telegram.bot.html]
- HTTPX docs - default timeout behavior and exception classes. [CITED: https://www.python-httpx.org/advanced/timeouts/] [CITED: https://www.python-httpx.org/exceptions/]
- Tenacity docs - async retry primitives. [CITED: https://tenacity.readthedocs.io/en/stable/index.html]

### Secondary (MEDIUM confidence)

- PyPI `pip index versions` results for repo-pinned libraries versus current upstream versions. [VERIFIED: PyPI]

### Tertiary (LOW confidence)

- None. Low-confidence findings were kept in the Assumptions Log instead of being stated as facts. [ASSUMED]

## Metadata

**Confidence breakdown:**

- Standard stack: HIGH - the phase reuses an already-pinned repo stack and the external capability claims were cross-checked against current official docs. [VERIFIED: codebase grep] [CITED: https://openrouter.ai/docs/api/reference/embeddings]
- Architecture: MEDIUM - the worker/transaction pattern is clear from the repo, but the exact OpenRouter parameter normalization for Gemini embedding task fields still needs a live smoke check. [VERIFIED: codebase grep] [CITED: https://ai.google.dev/api/embeddings]
- Pitfalls: HIGH - the key failure modes come directly from current repo behavior, locked phase decisions, and pgvector/OpenRouter semantics. [VERIFIED: codebase grep] [CITED: https://github.com/pgvector/pgvector]

**Research date:** 2026-05-27
**Valid until:** 2026-06-03 for OpenRouter/Gemini specifics; 2026-06-26 for repo-architecture findings. [ASSUMED]
