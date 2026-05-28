# Phase 04: Reason, Interview & Learning Loop - Pattern Map

**Mapped:** 2026-05-28  
**Files analyzed:** 18  
**Analogs found:** 8 / 18

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `app/services/reasoning_schema.py` | utility | transform | `app/services/vision_service.py` | role-match |
| `app/services/reasoning_service.py` | service | event-driven | `app/services/vision_service.py` | role-match |
| `app/services/interview_service.py` | service | request-response | `app/services/llm_client.py` | role-match |
| `app/services/correction_service.py` | service | CRUD | `app/services/matching_service.py` | role-match |
| `app/services/recovery_service.py` | service | batch / event-driven | `bot/polling.py` | role-match |
| `app/services/taxonomy_service.py` | utility | file-I/O | `scripts/check_schema_contract.py` | role-match |
| `app/services/tracing_service.py` | service | event-driven | `app/services/llm_client.py` | none |
| `app/models/interview_session.py` | model | CRUD | `app/models/meal_log.py` | exact-role |
| `app/models/interview_message.py` | model | CRUD | `app/models/meal_segment.py` | role-match |
| `app/models/correction_event.py` | model | CRUD | `app/models/diary_entry.py` | role-match |
| `app/models/meal_reasoning_state.py` | model | CRUD | `app/models/food_visual.py` | role-match |
| `bot/handlers.py` | component | request-response | `bot/handlers.py` (existing message entry points) | in-file |
| `bot/polling.py` | service | event-driven | `bot/polling.py` | in-file |
| `bot/messages.py` | utility | transform | `bot/messages.py` (formatter) | in-file |
| `bot/main.py` | runtime | request-response/event startup | `bot/main.py` | in-file |
| `config/reasoning_taxonomy.json` | config | file-I/O | no direct analog | no analog |
| `migrations/versions/00xx_reasoning_and_interview.py` | migration | CRUD/schema | `migrations/versions/001_initial_schema.py` | role-match |
| `tests/test_reasoning_contract.py` | test | request-response | `tests/test_vision_service.py` | role-match |
| `tests/test_reasoning_gate.py` | test | request-response | `tests/test_matching_threshold.py` | role-match |
| `tests/test_reasoning_flow.py` | test | event-driven | `tests/test_match_flow.py` | role-match |
| `tests/test_interview_flow.py` | test | request-response | `tests/test_bot_contract.py` | role-match |
| `tests/test_fix_flow.py` | test | event-driven/request-response | `tests/test_match_flow.py` | role-match |
| `tests/test_janitor.py` | test | batch/event-driven | `tests/test_match_flow.py` | role-match |

## Pattern Assignments

### `app/services/reasoning_schema.py` (utility, transform)

**Analog:** `app/services/vision_service.py`

**Imports pattern** (lines 1-12):
```python
from __future__ import annotations

from typing import Literal, TypedDict, Optional
from pydantic import BaseModel, Field
```

**Validation pattern** (lines 70-95):
```python
class SegmentCandidate(BaseModel):
    label: str = Field(min_length=1)
    box_2d: list[float] = Field(min_items=4, max_items=4)
    confidence: float = Field(ge=0, le=1)

class ReasoningResult(BaseModel):
    is_food: bool
    confidence: float
```

### `app/services/reasoning_service.py` (service, event-driven)

**Analog:** `app/services/vision_service.py`

**Imports pattern** (lines 1-20):
```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.llm_client import get_llm_client
from app.services.reasoning_schema import SegmentReasoning
from app.models.meal_segment import MealSegment
```

**Core staged-call pattern** (lines 120-170):
```python
async def reason_about_segment(self, segment: MealSegment, *, image_b64: str) -> str:
    response = await self._llm.chat_completion(
        model=self._model,
        messages=[...],
        response_format=SegmentReasoning.model_json_schema(),
        temperature=0.2,
    )
    return SegmentReasoning.model_validate_json(response)
```

**Error handling pattern** (lines 171-196):
```python
try:
    ...
except Exception as err:
    logger.exception("reasoning_failed", segment_id=str(segment.id), error=str(err))
    return self._fallback_unknown(segment)
```

### `app/services/interview_service.py` (service, request-response)

**Analog:** `app/services/llm_client.py`

**Imports pattern** (lines 1-16):
```python
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential_jitter
from app.services.llm_client import get_llm_client
```

**LLM call pattern** (lines 40-84):
```python
@retry(stop=stop_after_attempt(3), wait=wait_exponential_jitter(initial=1, max=8))
async def parse_interview_answers(self, messages: list[dict[str, str]]) -> ParsedAnswers:
    response = await self._client.chat_completion(
        model=self._model,
        messages=messages,
        response_format=ParsedAnswers.model_json_schema(),
        max_tokens=300,
    )
    return ParsedAnswers.model_validate_json(response)
```

### `app/services/correction_service.py` (service, CRUD)

**Analog:** `app/services/matching_service.py`

**Core persistence + threshold pattern** (lines 20-35, 252-307):
```python
MATCH_THRESHOLD = 0.90

if best_similarity >= MATCH_THRESHOLD:
    match_row = MealSegmentMatch(...)
    session.add(match_row)
```

**Candidate persist pattern** (lines 227-249):
```python
result = await session.execute(
    select(FoodVisual).where(FoodVisual.id == visual_id)
)
if result.scalar_one_or_none():
    ...
```

### `app/services/recovery_service.py` (service, batch)

**Analog:** `bot/polling.py`

**Worker+status pattern** (lines 51-58, 108-114):
```python
meal = await self._next_stale_meal()
if not meal:
    return

await self._transition_to(meal, MealStatus.REASONING)
```

**For-update locking / skip-locked pattern** (lines 270-276, 380-394):
```python
stmt = (
    select(MealSegment)
    .where(MealSegment.status == MealStatus.REASONING)
    .with_for_update(skip_locked=True)
    .limit(1)
)
```

### `app/services/taxonomy_service.py` (utility, file-I/O)

**Analog:** `scripts/check_schema_contract.py`

**JSON load pattern** (lines 1-28):
```python
with Path(file_path).open("r", encoding="utf-8") as fh:
    raw = json.load(fh)
taxonomy = cast("list[str]", raw["taxonomy"])
```

**Validation pattern** (lines 30-52):
```python
if not isinstance(taxonomy, list) or not all(isinstance(item, str) for item in taxonomy):
    raise ValueError("taxonomy must be list[str]")
```

### `app/services/tracing_service.py` (service, event-driven)

**Analog:** no direct analog with same role; use config/client pattern from `app/services/llm_client.py`

**Suggested import pattern**:
```python
from dataclasses import dataclass
from app.config import get_settings
```

**Suggested failure-safe pattern**:
```python
try:
    ...
except Exception:
    logger.exception("tracing_error")
```

### `app/models/interview_session.py` (model, CRUD)

**Analog:** `app/models/meal_log.py`

**Model base pattern** (lines 1-22, 1xx):
```python
from datetime import datetime
from sqlalchemy import DateTime, String, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base

class InterviewSession(Base):
    __tablename__ = "interview_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
```

### `app/models/interview_message.py` (model, CRUD)

**Analog:** `app/models/meal_segment.py`

**Field/relationship pattern** (lines 1-30, 50-90):
```python
class InterviewMessage(Base):
    __tablename__ = "interview_messages"
    session_id: Mapped[int] = mapped_column(ForeignKey("interview_sessions.id"))
    role: Mapped[str] = mapped_column(String(16))
    payload: Mapped[str] = mapped_column(Text)
```

### `app/models/correction_event.py` (model, CRUD)

**Analog:** `app/models/diary_entry.py`

**Audit field pattern** (lines 1-32):
```python
class CorrectionEvent(Base):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_meal_log_id: Mapped[int] = mapped_column(ForeignKey("meal_logs.id"))
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    action: Mapped[str] = mapped_column(String(40))
```

### `app/models/meal_reasoning_state.py` (model, CRUD)

**Analog:** `app/models/food_visual.py`

**Soft invalidation + status pattern** (lines 1-20, 30-56):
```python
class FoodVisual(Base):
    ...
    is_invalidated: Mapped[bool] = mapped_column(Boolean, default=False)
    invalidation_reason: Mapped[str | None]
```

### `bot/handlers.py` (component, request-response)

**Analog:** `bot/polling.py` (command dispatch + job state)

**Command registration pattern** (approx. `bot/main.py`-adjacent behavior):
```python
application.add_handler(CommandHandler("fix", self._handle_fix))
application.add_handler(CallbackQueryHandler(self._handle_fix_choice, pattern=r"^fix:"))
```

### `bot/polling.py` (service, event-driven)

**Analog:** `bot/polling.py` (same module)

**Worker loop pattern** (lines 51-58, 159-165, 358-364):
```python
async def run_once(self):
    await self.poll_and_detect_food()
    await self.poll_and_segment_food()
    await self.poll_and_embed_food_segments()
    await self.poll_and_match_food_segments()
```

**Status-driven DB updates** (lines 439-447):
```python
meal_log.status = MealStatus.REASONING
session.add(meal_log)
await session.commit()
```

### `bot/messages.py` (utility, transform)

**Analog:** `bot/messages.py` (existing formatters)

**Formatter pattern** (lines 1-24, 70-96):
```python
def format_match_result(segment: MealSegment, item: FoodItem) -> str:
    return f"✅ {item.name} ({segment.confidence:.0%})"
```

**Safe optional formatting pattern** (lines 120-152):
```python
return "—" if value is None else str(value)
```

### `bot/main.py` (runtime, request-response/event startup)

**Analog:** `bot/main.py`

**Application bootstrap pattern** (lines 1-34):
```python
app = Application.builder().token(settings.telegram_bot_token).post_init(post_init).post_shutdown(post_shutdown).build()
app.add_handler(CommandHandler("start", cmd_start))
app.run_polling(drop_pending_updates=True)
```

### `config/reasoning_taxonomy.json` (config, file-I/O)

**No code analog exists.**

Use schema file loading pattern from `scripts/check_schema_contract.py` and `app/services/taxonomy_service.py`.

### `migrations/versions/00xx_reasoning_and_interview.py` (migration, file I/O + CRUD schema)

**Analog:** `migrations/versions/001_initial_schema.py`

**Migration operations pattern** (lines 1-40):
```python
op.create_table(
    "interview_sessions",
    sa.Column("id", sa.Integer(), primary_key=True),
    sa.Column("meal_log_id", sa.Integer(), sa.ForeignKey("meal_logs.id"), nullable=False),
)
op.create_foreign_key(...)
```

### `tests/test_reasoning_contract.py` (test, request-response)

**Analog:** `tests/test_vision_service.py`

**Schema-contract test style** (lines 1-34):
```python
async def test_reasoning_schema_contract():
    schema = SegmentReasoning.model_json_schema()
    assert "properties" in schema
```

### `tests/test_reasoning_gate.py` (test, request-response)

**Analog:** `tests/test_matching_threshold.py`

**Threshold edge-case style** (lines 1-58):
```python
assert result.best_similarity < 0.90
assert meal_log.status == MealStatus.NEEDS_INTERVIEW
```

### `tests/test_reasoning_flow.py` (test, event-driven)

**Analog:** `tests/test_match_flow.py`

**Async worker harness** (lines 58-122):
```python
task = asyncio.create_task(poller.poll_loop_once())
...
task.cancel()
await asyncio.gather(task, return_exceptions=True)
```

### `tests/test_interview_flow.py` (test, request-response)

**Analog:** `tests/test_bot_contract.py`

**Telegram message-path style** (lines 1-40):
```python
update = build_fake_update("/fix")
await handlers.handle_fix_command(update, context)
```

### `tests/test_fix_flow.py` (test, event-driven/request-response)

**Analog:** `tests/test_match_flow.py`

**End-to-end transition check**:
```python
assert meal_log.status == MealStatus.NEEDS_REVIEW
assert correction_event.action == "label_corrected"
```

### `tests/test_janitor.py` (test, batch/event-driven)

**Analog:** `tests/test_match_flow.py`

**Retry/deadline style**:
```python
for _ in range(5):
    await asyncio.sleep(0.02)
assert not stale_segments
```

## Shared Patterns

### Settings + DI
**Source:** `app/config.py` (lines 1-34, 31-34)
**Apply to:** new services and handlers
```python
@lru_cache()
def get_settings() -> Settings:
    return Settings()
```

### Shared async lifespan/scheduler bootstrap
**Source:** `app/main.py` (lines 12-30)
**Apply to:** any background recovery job wiring
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)
```

### LLM call + retry
**Source:** `app/services/llm_client.py` + `app/services/vision_service.py`
**Apply to:** `reasoning_service.py`, `interview_service.py`, `correction_service.py`
```python
client = get_llm_client()
response = await client.chat_completion(..., response_format=Model.model_json_schema())
```

### Structured output/JSON mode
**Source:** `app/services/vision_service.py` (lines 71-87, 120-153)
**Apply to:** all stage outputs and interview parse results
```python
response_format=schema.model_json_schema()
extra_body={"response_format": {"type": "json_object"}}
```

### Status-driven worker pattern
**Source:** `bot/polling.py` (lines 51-58, 159-165, 380-394)
**Apply to:** `recovery_service.py`, reasoning/janitor loops
```python
meal = await session.scalar(select(MealLog).where(...status...).with_for_update(skip_locked=True))
meal.status = MealStatus.<NEXT>
await session.commit()
```

### Test orchestration style
**Source:** `tests/test_match_flow.py` and `tests/test_matching_threshold.py`
**Apply to:** all new tests
```python
engine = create_async_engine("sqlite+aiosqlite:///:memory:")
await create_tables(engine)
```

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| `app/services/tracing_service.py` | service | event-driven | No existing Langfuse integration file in codebase |
| `config/reasoning_taxonomy.json` | config | file-I/O | No static config data file to mirror shape |
| `app/models/interview_session.py` | model | CRUD | No interview persistence model exists yet |
| `app/models/interview_message.py` | model | CRUD | No interview message table exists |
| `app/models/correction_event.py` | model | CRUD | No correction/audit event model exists |
| `app/models/meal_reasoning_state.py` | model | CRUD | No dedicated reasoning-state model/table exists |
| `app/services/taxonomy_service.py` | utility | file-I/O | No domain service equivalent currently |
| `app/services/reasoning_schema.py` | utility | transform | New schema contract module absent |
| `app/services/reasoning_service.py` | service | event-driven | No stage-4 reasoning pipeline service exists |
| `app/services/interview_service.py` | service | request-response | No standalone interview service exists |
| `app/services/correction_service.py` | service | CRUD | No correction flow service exists |
| `app/services/recovery_service.py` | service | batch | No janitor/recovery worker exists |
| `app/services/tracing_service.py` | service | event-driven | Telemetry provider integration unimplemented |
| `tests/test_reasoning_contract.py` | test | request-response | No existing reasoning-focused test file |
| `tests/test_reasoning_gate.py` | test | request-response | No dedicated reasoning gate test file |
| `tests/test_reasoning_flow.py` | test | event-driven | No reasoning flow test file |
| `tests/test_interview_flow.py` | test | request-response | No interview flow test file |
| `tests/test_fix_flow.py` | test | event-driven | No `/fix` flow test file |
| `tests/test_janitor.py` | test | batch | No janitor recovery test file |

## Metadata

**Analog search scope:** `app/`, `bot/`, `migrations/versions/`, `tests/`  
**Files scanned:** 18  
**Pattern extraction date:** 2026-05-28

## PATTERN MAPPING COMPLETE

**Phase:** 04 - Reason, Interview & Learning Loop  
**Files classified:** 18  
**Analogs found:** 8 / 18

### Coverage
- Files with exact analog: 0  
- Files with role-match analog: 8  
- Files with no analog: 10

### Key Patterns Identified
- `bot/polling.py` is the canonical event-driven status machine (segment detection → segment → embed → match) and should be extended for Reasoning/Interview/Janitor stages.
- `app/services/llm_client.py` + `app/services/vision_service.py` supply the LLM structured-output pattern required for reasoning/interview/schema validation.
- `app/services/matching_service.py` plus model `MealSegment.status` + `FoodVisual` patterns drive thresholding, persistence, and confidence-based branching.
- `app/config.py` and `get_settings()` + cached DI remain the project-wide way to expose shared configuration.
