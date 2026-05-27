# Phase 03: Embed & Match - Pattern Map

**Mapped:** 2026-05-27
**Files analyzed:** 20
**Analogs found:** 20 / 20

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `app/services/llm_client.py` | service | request-response | `app/services/llm_client.py` | exact |
| `app/services/embedding_service.py` | service | request-response | `app/services/llm_client.py` | role-match |
| `app/services/matching_service.py` | service | request-response + db-query (`SELECT` + cosine rank) | `bot/polling.py`, `app/models/food_visual.py` | role-match |
| `app/database.py` | utility | request-response | `app/database.py` | exact |
| `bot/polling.py` | component (status worker) | status-driven pipeline | `bot/polling.py` | exact |
| `bot/messages.py` | component | request-response | `bot/messages.py` | exact |
| `bot/main.py` | component | status-driven startup | `bot/main.py` | exact |
| `app/models/meal_log.py` | model | status-transition metadata | `app/models/meal_log.py` | exact |
| `app/models/meal_segment.py` | model | CRUD + vector persistence | `app/models/meal_segment.py` | exact |
| `app/models/food_visual.py` | model | CRUD + vector persistence + ANN index | `app/models/food_visual.py` | exact |
| `app/models/food_item.py` | model | CRUD | `app/models/food_item.py` | exact |
| `app/models/diary_entry.py` | model | CRUD + status result rows | `app/models/diary_entry.py` | exact |
| `migrations/versions/001_initial_schema.py` | config (schema) | db migration | `migrations/versions/001_initial_schema.py` | exact |
| `scripts/vision_smoke.py` | utility script | file I/O + service calls | `scripts/vision_smoke.py` | exact |
| `scripts/check_schema_contract.py` | utility script/test | validation contract checks | `scripts/check_schema_contract.py` | exact |
| `tests/test_vision_service.py` | test | unit service contract | `tests/test_vision_service.py` | exact |
| `tests/test_bot_contract.py` | test | worker/message contract | `tests/test_bot_contract.py` | exact |
| `tests/test_embedding_service.py` | test | unit + mocked HTTP contract | `tests/test_vision_service.py`, `app/services/llm_client.py` | role-match |
| `tests/test_match_flow.py` | test | transaction + matching flow contract | `tests/test_bot_contract.py`, `app/models/*`, `migrations/001_initial_schema.py` | role-match |
| `scripts/seed_demo_foods.py` | utility script | seeded fixture + DB writes | `scripts/vision_smoke.py`, `scripts/check_schema_contract.py` | role-match |

## Pattern Assignments

### `app/services/llm_client.py` (service, request-response)

**Analog:** self

**Imports pattern** (lines 5-13):
```python
import httpx
from openai import AsyncOpenAI

from app.config import get_settings
```

**Dual-client setup** (lines 21-35):
```python
self._chat_client = AsyncOpenAI(
    api_key=api_key,
    base_url=base_url,
    max_retries=2,
    timeout=60.0,
    default_headers=OPENROUTER_HEADERS,
)
self._http = httpx.AsyncClient(
    base_url=base_url,
    timeout=60.0,
    headers={
        "Authorization": f"Bearer {api_key}",
        **OPENROUTER_HEADERS,
    },
)
```

**OpenAI request path** (lines 37-52):
```python
response = await self._chat_client.chat.completions.create(
    model=model,
    messages=messages,
    response_format=response_format,
    tools=tools,
    extra_body=extra_body,
)
```

**Raw embeddings path** (lines 54-74):
```python
payload = {
    "model": model,
    "input": [{"content": content}],
    "dimensions": output_dimensionality,
    "task_type": task_type,
}
response = await self._http.post("/embeddings", json=payload)
response.raise_for_status()
data = response.json()
return data["data"][0]["embedding"]
```

### `app/services/embedding_service.py` (service, request-response)

**Closest analog:** `app/services/llm_client.py` (role-match)

**Recommended imports**:
```python
from app.services.llm_client import OpenRouterClient
from app.models.meal_segment import MealSegment
from app.models.food_visual import FoodVisual
```

**Core semantics to copy**
- Call `OpenRouterClient.embed_multimodal(..., task_type=...)` directly so raw multimodal behavior stays centralized.
- Enforce `output_dimensionality` and `len(embedding) == 1536` validation before setting `MealSegment.embedding` or `FoodVisual.embedding`.
- Raise a typed parse error for malformed response shape (`KeyError`/`IndexError`) rather than silently storing bad vectors.
- Use retry wrapper at service boundary (e.g., tenacity) instead of adding transport policy in call sites.

**Error handling template**
```python
try:
    embedding = await client.embed_multimodal(...)
except (KeyError, IndexError) as exc:
    raise ValueError("Unexpected embedding response shape") from exc
except httpx.HTTPError as exc:
    raise
```

### `app/services/matching_service.py` (service, request-response + DB query)

**Closest analogs:** `app/models/food_visual.py` (exact vector shape/index), `migrations/versions/001_initial_schema.py` (index settings), `bot/polling.py` (status-driven worker pattern)

**Model / index contract to copy**
```python
class FoodVisual(Base):
    embedding: Mapped[list[float]] = mapped_column(Vector(1536), nullable=False)
    is_invalidated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    __table_args__ = (
        Index(
            "ix_food_visuals_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_with={"m": 16, "ef_construction": 64},
        ),
    )
```

**Match query pattern** (build from `pgvector` semantics and existing index)
- Query only `is_invalidated=False`.
- Fetch nearest row ordered by `FoodVisual.embedding.cosine_distance(query_vector)`.
- Convert to similarity with `1 - distance` in Python for `MATCH_THRESHOLD >= 0.85` decision.
- Return `(food_visual, segment, score)` for each segment and keep all-or-nothing semantics upstream.

**Transactional resolution pattern** (phase 3-specific):
- Resolve all segment matches first.
- If any segment below threshold, set `MealLog.processing_status = REASONING` and do not write diary/visual rows.
- If all pass, within one transaction write per-segment `DiaryEntry` + `FoodVisual` and set `MealLog.processing_status = COMPLETED`.

### `app/database.py` (utility, request-response)

**Imports pattern** (lines 3-8):
```python
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
```

**Session factory pattern** (lines 17-41):
```python
_engine = create_async_engine(
    url,
    echo=echo,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
)

return async_sessionmaker(
    bind=get_engine(),
    expire_on_commit=False,
    autoflush=False,
    class_=AsyncSession,
)
```

### `bot/polling.py` (status worker, state machine)

**Closest analog:** self

**Claim pattern with lock** (`PENDING` in lines 46-53 and `SEGMENTING` in lines 153-160):
```python
statement = (
    select(MealLog)
    .where(MealLog.processing_status == MealProcessingStatus.PENDING)
    .order_by(MealLog.created_at.asc())
    .limit(1)
    .with_for_update(skip_locked=True)
)
```

**State transition + commit** (ack loop and detect loop lines 57-63, 117-121):
```python
meal.processing_status = MealProcessingStatus.DETECTING
await session.commit()

meal.processing_status = MealProcessingStatus.SEGMENTING
await session.commit()
```

**Segment persistence flow** (lines 187-219):
```python
segment_rows.append(MealSegment(...))
session.add_all(segment_rows)
... label each segment ...
meal.processing_status = MealProcessingStatus.COMPLETED
await session.commit()
```

**Error pattern** (lines 124-127, 240-250, 251-255):
- Broad exception logging with `logger.exception`.
- On commit/send failure, mark failed via `MealLog.processing_status = FAILED` and `rollback`.
- Cleanup created crops with `crop_path.unlink(missing_ok=True)`.

### `bot/messages.py` (message formatting, request-response)

**Imports**: none; plain functions returning strings.

**Current style** (lines 17-34):
```python
def format_result_sentence(labels: list[str], weak_labels: set[str] | None = None) -> str:
    cleaned: list[str] = []
    ...
    return f"I see {item_count} items: {', '.join(cleaned)}."
```

Phase 3 should preserve terse one-output format and replace phase2 labels with nutrition/tally lines per D-17 to D-20.

### `bot/main.py` (worker startup/shutdown)

**Pattern to copy** (lines 14-36):
```python
application.bot_data["poll_task"] = asyncio.create_task(poll_and_acknowledge(...))
application.bot_data["detect_task"] = asyncio.create_task(poll_and_detect_food(...))
application.bot_data["segment_task"] = asyncio.create_task(poll_and_segment_food(...))
```
Add embed/match workers using the same lifecycle.

### `app/models/meal_log.py` (model/state)

**Status enum includes phase-3 states** (lines 17-26):
```python
class MealProcessingStatus(PyEnum):
    EMBEDDING = "EMBEDDING"
    MATCHING = "MATCHING"
    REASONING = "REASONING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
```

**Use**:
- `processing_status` is typed as enum and defaulted to `PENDING`.
- Query boundaries in workers should read/update this field directly.

### `app/models/meal_segment.py` (model/repo)

**Per-crop embedding target** (lines 24-33):
```python
class MealSegment(Base):
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    meal_log_id: Mapped[str] = mapped_column(ForeignKey("meal_logs.id"), nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
```

### `app/models/food_visual.py` (model/repo + ANN index)

**Visual corpus rows** (lines 17-29):
```python
food_item_id: Mapped[str] = mapped_column(ForeignKey("food_items.id"), nullable=False)
embedding: Mapped[list[float]] = mapped_column(Vector(1536), nullable=False)
is_invalidated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
```

### `app/models/food_item.py` (model)

**Nutrition + verification source** (lines 27-34, 33-34):
```python
calories: Mapped[float | None]
protein_g: Mapped[float | None]
carbs_g: Mapped[float | None]
fat_g: Mapped[float | None]
is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
```

### `app/models/diary_entry.py` (model)

**Phase-3 write target** (lines 21-30):
```python
portion_bucket: Mapped[str] = mapped_column(String(32), nullable=False)
identification_method: Mapped[str] = mapped_column(String(32), nullable=False)
is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
```

### `migrations/versions/001_initial_schema.py` (DDL/capacity)

**ANN index DDL pattern** (lines 192-199):
```sql
CREATE INDEX ix_food_visuals_embedding
ON food_visuals
USING hnsw (embedding vector_cosine_ops)
WITH (m=16, ef_construction=64)
```

### `scripts/vision_smoke.py` (utility script)

**CLI pattern** (lines 33-37):
```python
parser = argparse.ArgumentParser(...)
parser.add_argument("--mode", choices=["detect", "segment", "label", "all"], required=True)
```

**Run + teardown pattern** (lines 184-201):
- Build async runner with `asyncio.run(main())`.
- Close shared LLM client via `await client.close()`.
- Cleanup temp dirs in `finally`.

### `scripts/check_schema_contract.py` (verification utility)

**Contract checks** (lines 35-47, 82-90, 104-118):
- Assert enum/state contracts from `Settings` and `Base.metadata`.
- Assert vector dimensions and HNSW index options.
- Assert migration text contains `USING hnsw`, `m=16`, `ef_construction=64`.

### `tests/test_vision_service.py` (unit test template)

**Style to mirror for `test_embedding_service.py`**:
- Use `unittest.TestCase` plus `unittest.IsolatedAsyncioTestCase`.
- Use explicit schema assertions for strict JSON or response shape checks.
- Use `AsyncMock` for service client and assert awaited kwargs.

**Example** (line 225-229):
```python
client.chat_completion.assert_awaited_once_with(
    model="google/gemma-4-31b-it",
    messages=detect_prompt("https://example.test/meal.jpg"),
    response_format=detect_response_format(),
)
```

### `tests/test_bot_contract.py` (integration-like worker contract)

**Pattern to mirror for `test_match_flow.py`**:
- Use `IsolatedAsyncioTestCase` for polling worker flows.
- Patch `create_async_engine`, `async_sessionmaker`, and service functions.
- Simulate `asyncio.CancelledError` as loop exit signal.
- Assert state transitions and `bot.send_message` calls are committed/non-transactional per design.

### `scripts/seed_demo_foods.py` (proposed)

**Closest analog:** `scripts/vision_smoke.py` and `scripts/check_schema_contract.py`

**Recommended structure**:
- CLI parser for seed mode and sample source folder path.
- DB session bootstrap via `app.database.get_session_factory()`.
- For each sample or generated crop:
  - Build embedding via `app.services.embedding_service`.
  - Upsert `FoodItem` rows and append `FoodVisual` rows.
- Keep this helper operator-only and re-runnable; no hidden side effects.

## Shared Patterns

### 1) Status-driven handoff and one-stage ownership
**Sources:** `bot/polling.py` (PENDING→DETECTING→SEGMENTING) and `app/models/meal_log.py` enum.

**Apply to all relevant files**:
- Use one worker to own one status state.
- Query with `SELECT ... FOR UPDATE SKIP LOCKED` and limit 1.
- Update status and commit inside the DB transaction before starting external calls where possible.

### 2) Async SQLAlchemy session and engine lifecycle
**Sources:** `app/database.py`, `bot/polling.py`, `app/routers/ingest.py`.

**Apply to new services/tests**:
- For long worker loops, create own async engine + sessionmaker similarly.
- Keep `expire_on_commit=False`, `autoflush=False`.
- Use `await session.commit()` only after all row updates for that worker stage are prepared.

### 3) Vector schema and ANN constraints
**Sources:** `app/models/meal_segment.py`, `app/models/food_visual.py`, `migrations/versions/001_initial_schema.py`, `scripts/check_schema_contract.py`.

**Apply globally**:
- `Vector(1536)` in both segment and visual embedding fields.
- Matching query must filter `FoodVisual.is_invalidated == false`.
- Use cosine distance and convert to similarity with `1 - distance`.
- Keep HNSW with `m=16`, `ef_construction=64`.

### 4) Telegram contract behavior
**Sources:** `bot/polling.py` (lines 218-236, 527-597), `bot/messages.py`, `tests/test_bot_contract.py`.

**Apply to match completion**:
- DB state change must commit before Telegram send.
- Telegram push can fail without rolling back DB transaction.
- Keep output terse and user-facing (no vector scores/debug fields).

### 5) Test style and failure behavior
**Sources:** `tests/test_vision_service.py`, `tests/test_bot_contract.py`.

**Apply to new tests**:
- Keep unittest framework.
- Use `AsyncMock` and `patch.object` for dependency boundaries.
- Assert negative branches explicitly (below-threshold path, empty crops, malformed responses).

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| `app/services/matching_service.py` | service | request-response + db-query | No existing cosine matching service yet; only schema/index + worker state transition patterns exist. |
| `tests/test_match_flow.py` | test | integration | No existing matching/transaction test for segment-level ANN + transactional write-all-or-nothing flow. |
| `scripts/seed_demo_foods.py` | utility script | file + DB bootstrapping | No existing demo-seed operator script for `FoodItem`/`FoodVisual` writes. |
| `app/services/embedding_service.py` | service | request-response | Raw embedding orchestration is present in `llm_client`, but no thin validation/retry wrapper with phase-3 semantics yet. |

## Metadata

**Analog search scope:** `app/services`, `app/models`, `bot`, `app/routers`, `app/database`, `migrations`, `tests`, `scripts`.
**Files scanned:** 17
**Pattern extraction date:** 2026-05-27
