# Architecture Research

**Domain:** Single-user AI photo-meal-tracking pipeline (FastAPI + Postgres/pgvector + Telegram bot + LLM agentic grounding)
**Researched:** 2026-05-24
**Confidence:** HIGH on stack/topology; MEDIUM on pipeline orchestration shape (intentional opinionated choice from multiple defensible options); MEDIUM on confidence-calibration prompt patterns (active research area).

---

## TL;DR — The Opinionated Take

- **One container, one process, one event loop.** FastAPI app + python-telegram-bot (polling) + APScheduler + pipeline worker all share a single AsyncIOScheduler-backed event loop inside one Docker container. Splitting them is premature at single-user scale and adds inter-process plumbing that buys nothing.
- **No Redis, no Celery, no arq.** Postgres is the queue. The `meal_logs.processing_status` column IS the state machine. A single in-process async worker loop (`asyncio.create_task` retained on app state) polls `WHERE processing_status IN ('PENDING','DETECTING','SEGMENTING','MATCHING','REVIEWING')` with `FOR UPDATE SKIP LOCKED` and advances each row through its next stage. This is the outbox pattern degenerate-case: the domain table IS the outbox.
- **Telegram = long polling.** Mac mini behind a home NAT has no static IP, no public HTTPS, and webhooks require all three. Long polling is the default for self-hosted setups and is what python-telegram-bot's `Application.run_polling()` is for.
- **SQLAlchemy 2.x async + asyncpg + Alembic + pgvector-python.** The well-trodden path. Aerich is Tortoise-only; we're not on Tortoise.
- **HNSW from day one.** Despite IVFFlat docs in the schema comments, HNSW wins on small-to-medium datasets, doesn't require a rebuild as the visual library grows, and is what pgvector recommends for incremental-insert workloads.
- **Agentic tool loop = manual while-loop with `max_iterations=6` and a hard wall-clock timeout.** OpenRouter Agent SDK is tempting but adds a dependency and abstraction layer; the OpenAI SDK loop is ~50 lines and gives full visibility into the trace that gets persisted into `meal_segments.ai_reasoning`.

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         iOS Shortcut                                 │
│           (photo upload, shared-secret Authorization header)         │
└────────────────────────────────┬────────────────────────────────────┘
                                 │ HTTPS POST /ingest (multipart)
                                 │ X-Shared-Secret: <token>
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Container: mealtracker-app  (Python 3.12, uvicorn, one event loop) │
│                                                                       │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                       FastAPI app                               │  │
│  │  ┌─────────────┐   ┌─────────────┐   ┌───────────────────┐    │  │
│  │  │  /ingest    │   │  /healthz   │   │  /admin/* (auth)  │    │  │
│  │  │  endpoint   │   │  endpoint   │   │  introspection    │    │  │
│  │  └──────┬──────┘   └─────────────┘   └───────────────────┘    │  │
│  └─────────┼─────────────────────────────────────────────────────┘  │
│            │ INSERT MealLog(status=PENDING) + image to /data/uploads │
│            ▼                                                          │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │              Pipeline Worker (asyncio.Task, lifespan)          │  │
│  │   while True: claim_next_row() → run_stage() → update_status() │  │
│  │                                                                 │  │
│  │   Stages dispatched by processing_status:                       │  │
│  │     PENDING    → DetectStage    (is-food classifier via OR)     │  │
│  │     DETECTING  → SegmentStage   (bounding boxes via OR vision)  │  │
│  │     SEGMENTING → EmbedStage     (per-crop embeddings via OR)    │  │
│  │     ↓ then per-segment fan-out:                                 │  │
│  │       MatchStage → ReasonStage  (with tools) → InterviewStage   │  │
│  │     MATCHING   → AggregateStage (DiaryEntries + totals)         │  │
│  └─────────┬──────────────────────┬──────────────────────────────┘  │
│            │                      │                                   │
│            │ tool calls           │ pushes meal-result message        │
│            ▼                      ▼                                   │
│  ┌───────────────────┐   ┌──────────────────────────────────────┐   │
│  │   LLM Gateway     │   │     Telegram Bot (python-telegram-bot)│  │
│  │  (OpenAI SDK,     │   │  Application.run_polling() coroutine  │  │
│  │   base_url=OR)    │   │  ConversationHandler for interview    │  │
│  │                   │   │  CommandHandlers: /today /week /sum   │  │
│  │  tools:           │   │  Receives interview answers,          │  │
│  │   searxng_search  │   │  resolves MealSegment, transitions    │  │
│  │   firecrawl_fetch │   │  status                               │  │
│  └─────────┬─────────┘   └──────────────────────────────────────┘   │
│            │                                                          │
│  ┌─────────┼──────────────────────────────────────────────────────┐ │
│  │         │       APScheduler (AsyncIOScheduler, lifespan)        │ │
│  │  ───────┴──────  cron("0 3 * * *") → DailySummaryJob            │ │
│  └────────────────────────────────────────────────────────────────┘ │
└──────────┬───────────────────────────┬──────────────────┬────────────┘
           │                           │                  │
           │ HTTPS to openrouter.ai    │ tool: HTTP       │ asyncpg
           │ (Internet)                │ to local svcs    │ pool
           ▼                           ▼                  ▼
   ┌───────────────┐           ┌──────────────┐   ┌──────────────────┐
   │   OpenRouter  │           │   searxng    │   │ postgres + pgvec │
   │   (external)  │           │  firecrawl   │   │  (volume mounted)│
   │               │           │ (containers) │   │                  │
   └───────────────┘           └──────────────┘   └──────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Implementation |
|-----------|----------------|----------------|
| **`/ingest` endpoint** | Accept photo + shared-secret, persist image, insert `MealLog(status=PENDING)`, return 202 immediately | FastAPI route, `UploadFile`, single dependency for auth |
| **Pipeline Worker** | Single async task that drains the work table. Owns all stage transitions. | `asyncio.create_task(...)` started in lifespan, retained on `app.state.worker` |
| **Stage modules** | One module per stage (`detect.py`, `segment.py`, `embed.py`, `match.py`, `reason.py`, `interview.py`, `aggregate.py`). Pure functions of `(segment_or_log, deps) → next_state` | Plain async functions; tested in isolation |
| **LLM Gateway** | Thin wrapper around OpenAI SDK with `base_url="https://openrouter.ai/api/v1"`. Owns model-name → stage mapping, structured-output schema enforcement, the agentic tool loop, and cost/token tracking | Single class `LLMClient`, methods `classify()`, `segment()`, `embed()`, `reason_with_tools()`, `interview_turn()` |
| **Tool Registry** | Maps tool name → async Python function. `searxng_search` and `firecrawl_fetch` call local containers over HTTP | `dict[str, Callable]`; each tool has a JSON schema for OpenRouter |
| **Telegram Bot** | Push (per-meal + daily summary), Interview (ConversationHandler), Commands (`/today /week /summary`), User correction handler | `python-telegram-bot` v22, `Application` built with `updater=None` would be webhook; here we use `run_polling()` |
| **APScheduler** | Daily summary at 03:00 local; configurable | `AsyncIOScheduler` started in FastAPI lifespan |
| **Repositories** | One module per entity (`food_items.py`, `meal_logs.py`, etc.). All DB I/O lives here. | SQLAlchemy 2.x `select()` constructs, `AsyncSession` |
| **Migrations** | Schema evolution | Alembic in async mode |
| **Image store** | Disk volume at `/data/uploads` for original photos and `/data/crops` for segment crops. `image_url` columns hold relative paths. | Docker named volume |

---

## Recommended Project Structure

```
mealtracker/
├── docker-compose.yml          # The whole stack
├── Dockerfile                  # Multi-arch (linux/amd64,linux/arm64)
├── pyproject.toml              # Python 3.12, uv or pip-tools
├── alembic.ini
├── alembic/
│   ├── env.py                  # Async-mode setup
│   └── versions/
├── searxng/
│   └── settings.yml            # Engines, secret_key, JSON output enabled
├── data/                       # Bind/volume mount target
│   ├── uploads/                # Original photos
│   └── crops/                  # Segment crops
└── src/mealtracker/
    ├── __init__.py
    ├── main.py                 # FastAPI app, lifespan, mounts everything
    ├── config.py               # Pydantic Settings: env-driven config
    ├── deps.py                 # Dependency-injected singletons
    │
    ├── api/
    │   ├── ingest.py           # POST /ingest
    │   ├── admin.py            # /admin/queue, /admin/meals/{id}
    │   └── health.py           # /healthz, /readyz
    │
    ├── db/
    │   ├── engine.py           # async_engine + sessionmaker
    │   ├── base.py             # DeclarativeBase
    │   ├── models/             # SQLAlchemy ORM mirror of the schema
    │   │   ├── food_item.py
    │   │   ├── food_visual.py  # has Vector(1024) column
    │   │   ├── meal_log.py
    │   │   ├── meal_segment.py
    │   │   ├── diary_entry.py
    │   │   ├── interview_session.py
    │   │   └── interview_message.py
    │   └── repositories/       # All queries live here
    │       ├── meal_logs.py
    │       ├── meal_segments.py
    │       ├── food_visuals.py # cosine search
    │       └── ...
    │
    ├── pipeline/
    │   ├── worker.py           # The polling loop; claims rows, dispatches
    │   ├── status.py           # State-machine: allowed_transitions(), next_status()
    │   ├── stages/
    │   │   ├── detect.py       # PENDING -> DETECTING -> (SEGMENTING | NOT_FOOD)
    │   │   ├── segment.py      # DETECTING -> SEGMENTING (creates MealSegments)
    │   │   ├── embed.py        # Per-segment embedding + writes to meal_segments.embedding
    │   │   ├── match.py        # Cosine search in food_visuals
    │   │   ├── reason.py       # LLM + tools (agentic loop)
    │   │   ├── interview.py    # Triggers InterviewSession + initial Telegram msg
    │   │   └── aggregate.py    # All segments resolved → MealLog totals + DiaryEntries
    │   └── confidence.py       # Single source of truth for thresholds
    │
    ├── llm/
    │   ├── client.py           # OpenAI SDK → OpenRouter wrapper
    │   ├── schemas.py          # Pydantic models for structured outputs
    │   ├── prompts/            # Prompt strings, one file per stage
    │   │   ├── detect.txt
    │   │   ├── segment.txt
    │   │   ├── reason.txt
    │   │   └── interview.txt
    │   ├── tools.py            # Tool registry, JSON schemas, dispatch
    │   └── trace.py            # Builds the ai_reasoning audit string
    │
    ├── grounding/
    │   ├── searxng.py          # async httpx client → http://searxng:8080
    │   └── firecrawl.py        # async httpx client → http://firecrawl:3002
    │
    ├── bot/
    │   ├── app.py              # Application builder, polling startup
    │   ├── commands.py         # /today /week /summary
    │   ├── interview.py        # ConversationHandler implementing InterviewMessageKey FSM
    │   ├── push.py             # send_meal_result(), send_daily_summary()
    │   └── corrections.py      # USER_CORRECTED handler (reply-to-message or callback)
    │
    ├── scheduler/
    │   └── jobs.py             # daily_summary_job(), registered in lifespan
    │
    └── observability/
        ├── logging.py          # Structured JSON logs
        ├── timing.py           # Per-stage timing context manager
        └── cost.py             # Token + USD tracking per meal
```

### Structure Rationale

- **`pipeline/stages/` is the architectural backbone.** Each file owns one status transition. To add a stage, add a file and register it in `worker.py`'s dispatch dict. State-machine logic stays in `status.py` — no stage may call another stage directly.
- **`llm/` is isolated from `pipeline/`.** Stages call `llm_client.reason_with_tools(prompt, schema, tools)` and receive a Pydantic object. The stage never sees raw HTTP, raw tool calls, or token counts — those bubble up through `trace.py` and `cost.py`.
- **`bot/` is isolated from `pipeline/` too.** The pipeline writes to the DB and queues a "send this meal-result" event (just a row update or a function call); the bot reads from the DB. The interview ConversationHandler updates `interview_sessions` and `meal_segments` directly, then nudges the pipeline (which is already polling).
- **`db/repositories/` is the only place that imports `sqlalchemy`.** Stages, bot, and scheduler never write inline queries — keeps the query surface auditable and indexable.

---

## Architectural Patterns

### Pattern 1: Postgres-as-Queue with `SKIP LOCKED`

**What:** Replace Redis+Celery/arq with a single SQL query that atomically claims work and advances the state machine.

**When to use:** Single-user, single-instance, async pipeline where the state machine IS the domain. Avoids three extra moving parts (Redis, broker, worker process) at the cost of writing ~30 lines of polling loop yourself.

**Trade-offs:**
- Pros: zero extra infra, every "queue entry" is also the domain row (no sync issues), trivial inspection via `SELECT * FROM meal_logs WHERE processing_status != 'COMPLETED'`, retries are free (a crashed stage leaves the row in its previous status).
- Cons: polling latency (mitigated by short interval, e.g. 500ms idle / 0ms when work seen); doesn't scale beyond one worker process — fine for single-user; needs careful `FOR UPDATE SKIP LOCKED` to allow concurrent stage execution if you ever fan out.

**Example:**
```python
# pipeline/worker.py
async def claim_next(session: AsyncSession) -> MealLog | None:
    stmt = (
        select(MealLog)
        .where(MealLog.processing_status.in_(ACTIVE_STATUSES))
        .order_by(MealLog.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    return (await session.execute(stmt)).scalar_one_or_none()

async def worker_loop(app_state):
    while not app_state.shutting_down:
        async with sessionmaker() as session, session.begin():
            row = await claim_next(session)
            if row is None:
                await asyncio.sleep(0.5); continue
            try:
                await dispatch(row, session)  # mutates row.processing_status
            except Exception:
                logger.exception("stage failed; row will retry next tick")
                # Transaction rolls back; row reverts to prior status.
                raise
```

**Retry/idempotency notes:**
- Idempotency comes free from the state machine: a stage only acts if the row is in its expected `from_status`. If a stage crashes mid-write, the transaction rolls back; the next loop iteration re-picks it up.
- For long-running LLM calls, write any **side-effect-producing** state (e.g. `food_items` insert, `food_visuals` insert) inside the same transaction that flips the status. Either everything lands or nothing does.
- Add a `retry_count` column to `meal_segments` (and bump on each transient failure); after N (e.g. 3), set `needs_interview = true` to escalate to the user.
- Crashed-mid-stage detection: add a `claimed_at` timestamp set when the row enters an `*ING` status; a sweeper at startup resets any `*ING` row older than 10 min back to its `from_status`.

### Pattern 2: Confidence-Gated Cascade with Single Shared Threshold

**What:** Every LLM stage that emits a result also emits a confidence number on the same structured-output object. One configurable threshold (default 0.75) decides whether to advance, escalate, or fall back.

**When to use:** Multi-stage pipelines where you'd rather over-ask than mis-log. Lets you tune one knob globally.

**Trade-offs:**
- Pros: one place to dial sensitivity; uniform mental model across stages; surfaces in `ai_reasoning` for forensics.
- Cons: self-reported LLM confidence is **not well-calibrated out of the box** — different models report differently, and absolute numbers don't transfer between models. Mitigation: include calibration anchors in the prompt ("0.95 = certain like 'this is rice'; 0.50 = could be one of several things; 0.20 = guessing"). Active research area; expect to retune after first week of real data.

**Example:**
```python
# llm/schemas.py
class ReasonResult(BaseModel):
    food_name: str
    source_type: FoodSourceType
    restaurant_name: str | None = None
    brand_name: str | None = None
    quantity_multiplier: float
    reasoning: str  # required — model must explain itself
    confidence: float = Field(ge=0.0, le=1.0)

# pipeline/stages/reason.py
async def run(segment: MealSegment, deps: Deps) -> None:
    result, trace = await deps.llm.reason_with_tools(
        prompt=load_prompt("reason"),
        image_url=segment.cropped_image_url,
        schema=ReasonResult,
        tools=[deps.tools.searxng_search, deps.tools.firecrawl_fetch],
        max_iterations=6,
        timeout_s=90,
    )
    segment.ai_reasoning = trace  # full tool-call audit
    if result.confidence >= deps.cfg.confidence_threshold:
        await finalize_segment(segment, result, IdentificationMethod.LLM)
    else:
        segment.needs_interview = True
        await create_interview_session(segment, ai_initial_guess=result.food_name,
                                        ai_initial_confidence=result.confidence)
```

**Threshold placement:** ONE threshold, applied at exactly two gates: (a) post-reason → escalate to interview; (b) post-interview-grounding → if still below, commit with `is_verified=false` and **stop** (the "best-effort commit" decision in PROJECT.md). The similarity threshold (0.75 in the schema notes) is a *different* knob — it lives in `match.py` and stays separate because vector-cosine distance is on a fundamentally different scale than LLM self-reports.

### Pattern 3: Agentic Tool Loop with Hard Budget Caps

**What:** A while-loop that feeds tool results back to the LLM until it stops calling tools or hits a budget cap (iterations, wall-clock, or tokens).

**When to use:** Reason stage and post-interview re-grounding stage only. Detect, segment, embed, and match never use tools.

**Trade-offs:**
- Pros: lets the model decide when it has enough info; same loop works for any tool you add later.
- Cons: runaway loops cost real money; tool-call traces can balloon `ai_reasoning`. Caps are mandatory.

**Example:**
```python
# llm/client.py
async def reason_with_tools(self, *, prompt, image_url, schema, tools,
                             max_iterations=6, timeout_s=90):
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": [{"type": "image_url", "image_url": image_url}]}
    ]
    tool_specs = [t.openai_spec for t in tools]
    trace_lines = []
    deadline = time.monotonic() + timeout_s

    for i in range(max_iterations):
        if time.monotonic() > deadline:
            trace_lines.append(f"[abort] timeout after {i} iterations")
            break
        resp = await self.openai.chat.completions.create(
            model=self.cfg.reason_model,
            messages=messages,
            tools=tool_specs,
            response_format={"type": "json_schema", "json_schema": schema.model_json_schema()},
        )
        choice = resp.choices[0]
        if not choice.message.tool_calls:
            # Final answer — parse into schema and return
            parsed = schema.model_validate_json(choice.message.content)
            trace_lines.append(f"[final] {parsed.confidence:.2f}: {parsed.reasoning}")
            return parsed, "\n".join(trace_lines)

        messages.append(choice.message.model_dump())
        for call in choice.message.tool_calls:
            tool = self.tool_registry[call.function.name]
            args = json.loads(call.function.arguments)
            trace_lines.append(f"[tool] {call.function.name}({args!r})")
            try:
                result = await asyncio.wait_for(tool(**args), timeout=15)
            except Exception as e:
                result = {"error": str(e)}
            trace_lines.append(f"[tool-result] {str(result)[:500]}")
            messages.append({"role": "tool", "tool_call_id": call.id,
                              "content": json.dumps(result)})
    else:
        trace_lines.append("[abort] max_iterations reached; committing best guess")
    # If we got here without returning, force one final no-tools call:
    return await self._final_answer(messages, schema), "\n".join(trace_lines)
```

The `trace_lines` string lands in `meal_segments.ai_reasoning` verbatim and becomes the audit trail. If something goes weird, you read that column.

### Pattern 4: Lifespan-Wired Singletons

**What:** All long-lived objects (DB engine, LLM client, scheduler, bot Application, worker task) are constructed in `lifespan` and stored on `app.state` for injection.

**When to use:** Always with FastAPI 0.93+. The pre-lifespan event-handler API is deprecated.

**Trade-offs:** None really — it's the canonical pattern.

**Example:**
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.engine = create_async_engine(cfg.database_url, pool_size=10)
    app.state.sessionmaker = async_sessionmaker(app.state.engine, expire_on_commit=False)
    app.state.llm = LLMClient(cfg)
    app.state.bot = build_bot_application(cfg, app.state.sessionmaker)
    app.state.scheduler = AsyncIOScheduler(); register_jobs(app.state.scheduler, cfg)
    app.state.shutting_down = False

    # Start background coroutines and keep references to allow clean shutdown.
    app.state.worker_task = asyncio.create_task(worker_loop(app.state))
    app.state.bot_task = asyncio.create_task(app.state.bot.run_polling(stop_signals=None))
    app.state.scheduler.start()

    try:
        yield
    finally:
        app.state.shutting_down = True
        app.state.scheduler.shutdown()
        await app.state.bot.shutdown()
        app.state.worker_task.cancel()
        await app.state.engine.dispose()
```

Keeping the `worker_task` reference is the difference between "works" and "the GC silently kills your pipeline" — see the Pitfalls research.

### Pattern 5: Telegram ConversationHandler as the Interview FSM

**What:** Use `python-telegram-bot`'s `ConversationHandler` with states matching the `InterviewMessageKey` enum order: `FOOD_NAME → SOURCE_TYPE → (RESTAURANT_NAME | BRAND_NAME | nothing) → PORTION_CONTEXT → CONFIRMATION`.

**When to use:** The interview flow is already an explicit state machine in your schema; ConversationHandler is its lib-level twin.

**Trade-offs:**
- Pros: free state, free fallback (`/cancel`), free timeout (`conversation_timeout=...`); persists conversation state to your DB if you back it with a `BasePersistence` subclass — but for single-user you can keep state in memory.
- Cons: ConversationHandler state is per-`(chat_id, user_id)` so resuming after a restart needs care. Solution: on bot startup, query `interview_sessions WHERE status='IN_PROGRESS'` and resend the last bot message to reprompt.

**Example:**
```python
# bot/interview.py
FOOD_NAME, SOURCE_TYPE, RESTAURANT, BRAND, PORTION, CONFIRM = range(6)

interview = ConversationHandler(
    entry_points=[CommandHandler("__internal_start_interview", start_interview)],
    states={
        FOOD_NAME:   [MessageHandler(filters.TEXT & ~filters.COMMAND, on_food_name)],
        SOURCE_TYPE: [CallbackQueryHandler(on_source_type)],
        RESTAURANT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, on_restaurant)],
        BRAND:       [MessageHandler(filters.TEXT & ~filters.COMMAND, on_brand)],
        PORTION:     [CallbackQueryHandler(on_portion)],
        CONFIRM:     [CallbackQueryHandler(on_confirm)],
    },
    fallbacks=[CommandHandler("cancel", cancel_interview)],
    conversation_timeout=timedelta(hours=2),
    name="meal_interview",
    persistent=False,  # Single user, single instance — memory is fine.
)
```

Each handler writes an `InterviewMessage` row with the appropriate `InterviewMessageKey`, mutates the `InterviewSession`, and on `CONFIRM` flips the session to `COMPLETED` and the segment to a state the pipeline worker will pick up (e.g. nudges the worker to do the post-interview re-grounding).

---

## Data Flow

### Ingestion → Diary (Happy Path)

```
[iOS Shortcut]
    │ POST /ingest (multipart photo, X-Shared-Secret)
    ▼
[FastAPI /ingest]
    │ 1. Verify shared secret
    │ 2. Save photo to /data/uploads/<uuid>.jpg
    │ 3. INSERT INTO meal_logs (image_url, processing_status='PENDING')
    │ 4. Return 202 {meal_id: <uuid>}
    ▼
[Pipeline worker (separate coroutine, same process)]
    │ claim_next() picks up PENDING row
    │ DETECT stage → LLM classifies is_food
    │   → if not food: status=NOT_FOOD, done
    │   → else: status=DETECTING then SEGMENTING
    │ SEGMENT stage → LLM emits bounding boxes
    │   → For each box: create MealSegment, crop image, save to /data/crops/
    │   → status=SEGMENTING then MATCHING
    │ For each segment (sequential; concurrency comes later):
    │   EMBED stage → embedding model → meal_segments.embedding
    │   MATCH stage → cosine search food_visuals
    │     → if similarity >= 0.85: SIMILARITY match, finalize segment
    │     → if 0.65–0.84: store top-K candidates, escalate to REASON stage
    │     → if < 0.65: REASON stage with no candidate hints
    │   REASON stage → LLM + tools (agentic loop, max 6 iterations)
    │     → if confidence >= 0.75: LLM method, finalize segment
    │     → else: needs_interview=true, create InterviewSession,
    │                meal_logs.status=REVIEWING, send first Telegram message
    │ AGGREGATE stage (when all segments resolved):
    │   For each segment: INSERT diary_entries (pre-calculated nutrition)
    │                     INSERT food_visuals (segment's embedding → grow library)
    │   UPDATE meal_logs SET total_*=..., processing_status='COMPLETED'
    │   Send Telegram "meal logged" push message
    ▼
[Telegram bot]
    Posts result message to pinned chat_id.
```

### Interview Branch

```
[Pipeline worker] reaches REASON below threshold
    │ Creates InterviewSession(status=PENDING)
    │ Sets meal_segment.needs_interview = true
    │ Calls bot.send_initial_question(session) — INITIAL_QUESTION message_key
    │ Worker leaves this segment alone (status holds at REVIEWING)
    ▼
[Telegram user types reply]
    ▼
[ConversationHandler] walks FOOD_NAME → SOURCE_TYPE → ... → CONFIRMATION
    │ Each turn writes an InterviewMessage row.
    │ On CONFIRMATION:
    │   - Find-or-create FoodItem (by name + source_type + restaurant/brand)
    │     IF nutrition unknown: re-invoke REASON stage with searxng/firecrawl tools
    │     to fill calories_per_unit etc.  (post-interview grounding)
    │   - InterviewSession.status=COMPLETED, resulting_food_item_id=<id>
    │   - MealSegment.matched_food_item_id=<id>, identification_method=INTERVIEW,
    │     interview_completed=true, user_confirmed=true
    │   - Nudge pipeline worker (just by virtue of the status change; loop picks it up)
    ▼
[Pipeline worker] sees the segment is resolved
    Continues with AGGREGATE stage as above.
```

### User Correction

```
[Telegram user] replies to a meal-result message with "actually that was X" OR
                taps an inline "wrong?" button on the result message.
    ▼
[Bot correction handler]
    Updates MealSegment: identification_method=USER_CORRECTED, matched_food_item_id=<X>
    Re-runs AGGREGATE for the parent MealLog (re-computes totals, replaces DiaryEntry).
    Optionally: add a FoodVisual(food_item_id=X, embedding=segment.embedding) so the
    library learns the correction. Worth doing.
```

### Daily Summary

```
[APScheduler] fires DailySummaryJob at 03:00 local
    │ Query diary_entries WHERE logged_at BETWEEN yesterday_start AND yesterday_end
    │ Sum totals per meal_log + grand total
    │ Format as Telegram message
    └ Send to pinned chat_id
```

### State Machine — `MealProcessingStatus`

```
PENDING ──► DETECTING ──► NOT_FOOD (terminal, leaf)
                │
                ▼
            SEGMENTING ──► MATCHING ──► REVIEWING ──► COMPLETED (terminal)
                                            │             ▲
                                            └─────────────┘
                                       (interview loop)
```

Each transition is owned by exactly one stage module. The worker's dispatch dict is the source of truth for which module handles which status.

---

## docker-compose Topology

```yaml
# docker-compose.yml (sketch — not final config)
services:

  app:
    build:
      context: .
      platforms:
        - linux/arm64    # Mac mini today (Apple Silicon)
        - linux/amd64    # Future VM
    image: mealtracker-app:latest
    restart: unless-stopped
    depends_on:
      postgres: { condition: service_healthy }
      searxng:  { condition: service_started }
      firecrawl: { condition: service_started }
    environment:
      DATABASE_URL: postgresql+asyncpg://mt:${POSTGRES_PASSWORD}@postgres:5432/mealtracker
      OPENROUTER_API_KEY: ${OPENROUTER_API_KEY}
      OPENROUTER_BASE_URL: https://openrouter.ai/api/v1
      TELEGRAM_BOT_TOKEN: ${TELEGRAM_BOT_TOKEN}
      TELEGRAM_CHAT_ID: ${TELEGRAM_CHAT_ID}
      INGEST_SHARED_SECRET: ${INGEST_SHARED_SECRET}
      CONFIDENCE_THRESHOLD: "0.75"
      SIMILARITY_AUTO_MATCH: "0.85"
      SIMILARITY_SUGGEST: "0.65"
      DAILY_SUMMARY_CRON: "0 3 * * *"
      LLM_MODEL_DETECT: google/gemma-4-31b-it
      LLM_MODEL_SEGMENT: google/gemini-3-flash-preview
      LLM_MODEL_REASON: google/gemini-3-flash-preview
      LLM_MODEL_INTERVIEW: google/gemini-3.1-flash-lite
      LLM_MODEL_EMBED: google/gemini-embedding-2-preview
      SEARXNG_URL: http://searxng:8080
      FIRECRAWL_URL: http://firecrawl:3002
    ports:
      - "8000:8000"   # /ingest reachable from LAN; iOS Shortcut posts here
    volumes:
      - ./data:/data  # uploads + crops
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/healthz"]
      interval: 30s

  postgres:
    image: pgvector/pgvector:pg17    # Multi-arch, pgvector preinstalled
    restart: unless-stopped
    environment:
      POSTGRES_USER: mt
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: mealtracker
    volumes:
      - postgres-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U mt -d mealtracker"]
      interval: 10s

  searxng:
    image: searxng/searxng:latest
    restart: unless-stopped
    volumes:
      - ./searxng:/etc/searxng:ro
    environment:
      SEARXNG_BASE_URL: http://searxng:8080
      SEARXNG_SECRET: ${SEARXNG_SECRET}
    # NOT exposed to host — internal-only

  firecrawl:
    # Use prebuilt image; the official compose ships RabbitMQ + Redis + Playwright
    # services. For single-user grounding we can use a slimmed-down config.
    # Confidence: MEDIUM — verify exact image tag at build time.
    image: ghcr.io/firecrawl/firecrawl:latest
    restart: unless-stopped
    environment:
      USE_DB_AUTHENTICATION: "false"
      SEARCH_PROVIDER: searxng
      SEARXNG_ENDPOINT: http://searxng:8080
    depends_on:
      - searxng

volumes:
  postgres-data:
```

**Topology notes:**
- One Docker bridge network (the default created by compose). Only `app` exposes a host port. `postgres`, `searxng`, `firecrawl` are reachable only by service name from inside the network.
- `pgvector/pgvector:pg17` ships multi-arch (arm64/amd64) — no fiddling needed on Mac mini.
- For ARM/AMD portability of the **app** image: build with `docker buildx build --platform linux/arm64,linux/amd64 --push`. For a Mac-mini-only deploy you can skip multi-arch and build native; do multi-arch when you're ready to copy to the VM.
- Firecrawl's official self-host compose is heavy (RabbitMQ + Redis + Playwright). If that turns out to be too much for the Mac mini, the alternative is `crawl4ai` (mentioned in research) as a lighter scraper. **Flag for verification in Phase 0.**
- Env file strategy: a single `.env` (gitignored) consumed by `docker-compose`, with `.env.example` checked in. Pydantic Settings inside the app reads the same vars.

**Single-container vs split:** Resist splitting `app` into `api` + `worker` + `bot`. At one user, the only thing splitting buys you is the ability to scale them independently, which you'll never need. Splitting costs you: shared connection-pool tuning, three log streams, three Docker images, and synchronization headaches (e.g. bot needs to read the same `meal_segments` row the worker is writing). One process, one event loop. Revisit only if observability shows CPU saturation, which is implausible at this scale.

---

## Configuration & Secrets

**All config via env vars** (pydantic-settings). No YAML, no JSON files for runtime config.

| Variable | Purpose | Notes |
|----------|---------|-------|
| `INGEST_SHARED_SECRET` | Header for iOS Shortcut auth | Long random string; rotate via env-file swap |
| `OPENROUTER_API_KEY` | LLM gateway | Single key for all stages |
| `TELEGRAM_BOT_TOKEN` | Bot identity | From @BotFather |
| `TELEGRAM_CHAT_ID` | Hard-pinned recipient | Single user; bot rejects messages from other chat_ids |
| `POSTGRES_PASSWORD` | DB | Strong random |
| `SEARXNG_SECRET` | SearXNG signing | Required by SearXNG |
| `CONFIDENCE_THRESHOLD` | LLM gate (default 0.75) | Runtime-tunable via env reload (restart container) |
| `SIMILARITY_AUTO_MATCH` | Vector gate (default 0.85) | Stays separate from LLM threshold |
| `SIMILARITY_SUGGEST` | Vector lower bound (default 0.65) | Below this, no candidates given to REASON |
| `DAILY_SUMMARY_CRON` | APScheduler spec | Default `0 3 * * *` (03:00 local) |
| `LLM_MODEL_*` | Per-stage model pins | One env var per stage = easy A/B swaps |

Secrets live in `.env` only. Never logged. Pydantic Settings has `SecretStr` for the obvious ones — use it.

---

## Observability Minimum (single-user grade)

| What | Where it lives | How to inspect |
|------|----------------|----------------|
| Per-stage timing | Log line + `meal_logs.stage_timings` JSON column (add in migration) | `psql` or `/admin/meals/{id}` endpoint |
| Per-meal token cost | `meal_logs.llm_cost_usd` (add) + structured log | `psql`; sum over date range |
| Stage failure reasons | Structured log line at ERROR + `meal_segments.last_error_text` (add) | `docker compose logs app \| jq` |
| Full LLM trace | `meal_segments.ai_reasoning` (already in schema) | DB query; this is the post-mortem column |
| Interview transcript | `interview_messages` table (already in schema) | DB query |
| Health | `GET /healthz` returns DB connectivity + scheduler state | curl from LAN |
| Admin | `GET /admin/queue` returns rows currently in non-terminal status; `GET /admin/meals/{id}` returns the full state for one meal incl. trace | Pinned to shared secret |

No Prometheus/Grafana at this scale. JSON logs to stdout, `docker compose logs`, and a `jq` cheat sheet are sufficient.

---

## Suggested Build Order (Working Slices, Not Horizontal Layers)

Each phase ends with **something you can actually use**. No "lay down all the models first" — that's the trap.

### Slice 1: Walking skeleton (1 working slice end-to-end with no AI)
**Deliverable:** iOS Shortcut posts a photo → MealLog row appears → Telegram bot pushes "got it: <image_url>".
- docker-compose with `app` + `postgres` (pgvector enabled) only
- Alembic baseline migration: `meal_logs` table only, with `processing_status`
- `POST /ingest` with shared-secret auth, persists image, inserts PENDING row
- Bot polling, hard-coded `/start` handler
- Tiny worker loop that picks up PENDING rows and immediately marks them COMPLETED with a Telegram push

**Validates:** event loop topology, lifespan wiring, polling vs worker contention, Mac-mini network reachability for iOS Shortcut, Telegram delivery.

### Slice 2: Detect + Segment (AI enters the picture)
**Deliverable:** Photo upload → bot reports "I see 3 items: rice, daal, naan" (no nutrition yet).
- Add `meal_segments` table
- Wire OpenAI SDK → OpenRouter (`base_url` swap)
- DETECT stage (is-food binary classification)
- SEGMENT stage (bounding boxes); save crops to `/data/crops/`
- Bot pushes a list-of-items message; no diary yet

**Validates:** OpenRouter compatibility for vision input + JSON structured outputs, image-crop pipeline, status transitions through multiple stages.

### Slice 3: Embed + Match + the food library (similarity path only)
**Deliverable:** Re-uploading a photo of food you've previously confirmed via DB seed → match by similarity, write DiaryEntry, push nutrition message.
- Add `food_items`, `food_visuals`, `diary_entries` tables
- pgvector HNSW index on `food_visuals.embedding`
- EMBED stage (one call per crop)
- MATCH stage (cosine search; `>=0.85` → finalize)
- AGGREGATE stage (write DiaryEntries, compute totals)
- Seed a few FoodItems by hand to test the match path
- Bot meal-result formatter

**Validates:** pgvector cosine search performance, embedding dimension correctness, the aggregation math, the FoodVisual write-back grows the library.

### Slice 4: REASON stage with structured output (no tools yet)
**Deliverable:** Unknown food → LLM creates a FoodItem with reasonable nutrition guesses, writes a DiaryEntry, push message includes "(my best guess)" caveat.
- Add `LLMClient.reason()` without tools
- Pydantic schema for the reason output (food_name, source_type, multiplier, confidence)
- High-confidence path: finalize with `identification_method=LLM`
- Low-confidence path: write `needs_interview=true` and stop (no interview yet)
- Confidence threshold becomes meaningful here

**Validates:** structured-output reliability across the OpenRouter compatibility layer, confidence calibration first impressions.

### Slice 5: Telegram interview ConversationHandler
**Deliverable:** Low-confidence segment triggers a back-and-forth interview; user confirmation creates the FoodItem properly and resolves the segment.
- Add `interview_sessions`, `interview_messages` tables
- ConversationHandler with full FSM
- Interview kickoff message from the pipeline
- On CONFIRMATION, find-or-create FoodItem, write FoodVisual, advance to AGGREGATE

**Validates:** the actual UX. This is the one to dogfood for a week before adding tools.

### Slice 6: Agentic tools (searxng + firecrawl)
**Deliverable:** REASON stage can search and fetch when uncertain about a brand or restaurant. Post-interview grounding fills nutrition from web sources for branded items.
- Add `searxng` and `firecrawl` services to compose
- Tool registry in `llm/tools.py`
- Agentic loop with `max_iterations=6` and 90s timeout
- Trace persisted to `ai_reasoning`
- Post-interview re-grounding for PACKAGED / RESTAURANT items where nutrition is empty

**Validates:** local grounding stack stability, tool-call traces being useful, cost ceiling.

### Slice 7: Daily summary + slash commands + corrections
**Deliverable:** Full UX. APScheduler fires 03:00 summary; `/today` `/week` `/summary` respond on demand; reply-to-message corrections work and feed the library.
- APScheduler job
- CommandHandlers
- Correction handler (reply parsing or inline button)

**Validates:** the "shipped" feel.

### Slice 8: Observability + admin + resilience
**Deliverable:** You can diagnose anything without `psql`-archaeology. Crashed-mid-stage rows auto-recover.
- `/admin/queue` + `/admin/meals/{id}` endpoints
- Startup sweeper for orphaned `*ING` rows
- `retry_count` + escalation logic
- Structured logging end-to-end
- Token/cost tracking column populated

**Validates:** you can run this for months without babysitting.

---

## Scaling Considerations

Single user. The interesting "scale" is not requests — it's `food_visuals` row count over time.

| Scale | Architecture Adjustments |
|-------|--------------------------|
| 0–6 months (under 1k FoodVisuals) | HNSW with default `m=16, ef_construction=64`; nothing to do |
| 6–24 months (1k–20k FoodVisuals) | Same indexes; possibly bump `ef_search` if recall dips |
| 2+ years (20k+) | Consider partitioning by `source_type` or pruning `food_visuals` rows that never matched (a `last_matched_at` column would let you GC unhelpful visuals) |

**First bottleneck:** LLM cost, not infra. OpenRouter spend per meal is the metric to watch — that's why `cost.py` exists. If cost gets out of hand: cheaper detect/segment model, only call REASON when MATCH found nothing in the suggest band, cap embedding to lower dimension (Gemini supports Matryoshka truncation).

**Second bottleneck:** Firecrawl + SearXNG resource usage on the Mac mini if the agentic loop fires often. Mitigation: cache tool calls keyed by `(tool_name, args_hash)` for 24h.

**The "scaling concern" that actually matters:** wrong-identification compounding. A bad SIMILARITY match writes a FoodVisual that makes the next bad match easier. Mitigation: USER_CORRECTED should soft-delete the offending FoodVisual (don't add the embedding to a denylist forever, just for this segment). Track this in Phase 5+.

---

## Anti-Patterns

### Anti-Pattern 1: Adding Celery/arq/Redis before there's a reason
**What people do:** Default to a task queue because "background processing."
**Why it's wrong:** At single-user scale you've added a broker, a worker process, and a dual source of truth (broker queue vs DB state). The state machine you already have IS the queue.
**Do this instead:** Postgres + `SKIP LOCKED` + a single async worker coroutine. Reach for arq the day you need >1 worker process or persistent scheduled retries with backoff that the DB can't express ergonomically.

### Anti-Pattern 2: Splitting bot, scheduler, and API into separate containers "for cleanliness"
**What people do:** Microservice instinct.
**Why it's wrong:** Three containers means three Python processes, three connection pools, three sets of logs, and synchronization issues between them. They all share the same domain DB — there's no isolation benefit.
**Do this instead:** One process, one event loop. AsyncIOScheduler + python-telegram-bot polling + FastAPI uvicorn all co-exist on the same loop with care taken in lifespan.

### Anti-Pattern 3: Trusting raw LLM self-confidence as a probability
**What people do:** Set threshold=0.5 because "that's a coin flip."
**Why it's wrong:** Self-reported confidence is poorly calibrated and varies per model. 0.5 from Gemini ≠ 0.5 from GPT.
**Do this instead:** (a) Include anchors in the prompt so the model has a calibration frame. (b) Start threshold at 0.75 (intentionally pessimistic — fail toward interviews). (c) Re-tune after a week of real data using `meal_segments.ai_reasoning` + actual outcomes.

### Anti-Pattern 4: Free-text-parsing interview responses
**What people do:** Take the user's reply and pattern-match it.
**Why it's wrong:** Ambiguous and fragile.
**Do this instead:** Use Telegram inline keyboards for `SOURCE_TYPE` and `PORTION_CONTEXT` (limited choice sets) — `CallbackQueryHandler` returns a clean enum. Only `FOOD_NAME` and free-form clarifications need text parsing, and those go straight into `food_items.name` and `interview_messages.message_text` respectively — no parsing required.

### Anti-Pattern 5: Webhooks on a home network
**What people do:** Read that webhooks are "more efficient" and try to expose port 8443 through their router.
**Why it's wrong:** Self-signed certs need uploads to Telegram; dynamic IPs break it; opening ports invites trouble.
**Do this instead:** Long polling. `Application.run_polling()`. The "efficiency" delta is irrelevant at one user.

### Anti-Pattern 6: Putting `await asyncio.sleep(...)` inside the worker transaction
**What people do:** Yield in the middle of a `session.begin()` block to "be nice."
**Why it's wrong:** Holds row locks for the duration. Other workers (if you ever add one) starve.
**Do this instead:** Open a session per claim, commit/rollback before sleeping. Worker idle sleep happens between transactions, never inside one.

### Anti-Pattern 7: Forgetting to keep a reference to `asyncio.create_task(worker_loop(...))`
**What people do:** Fire-and-forget the worker task in lifespan.
**Why it's wrong:** Python's GC can collect tasks with no strong reference. The worker dies silently and your pipeline stalls.
**Do this instead:** Stash on `app.state.worker_task` (and cancel in lifespan teardown).

---

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| **OpenRouter** | OpenAI SDK with `base_url="https://openrouter.ai/api/v1"`. One client instance. | Verify each stage's model supports vision input + tools + JSON-schema response format. Some models proxy by OpenRouter don't expose all three. |
| **Telegram Bot API** | python-telegram-bot v22, `Application.run_polling()` | Polling is the right call for home-network Mac mini. Reject messages from chat_ids ≠ pinned chat_id at handler level. |
| **iOS Shortcut** | Inbound HTTPS POST to `/ingest` with shared-secret header | Mac mini will need a stable LAN IP or a Tailscale tailnet (recommended) so the shortcut can reach it without port-forwarding. Tailscale is the painless answer here. |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| API → worker | Database row (status='PENDING') | No in-memory queue. State persists. |
| Worker → LLM | Direct method call on `LLMClient` (same process) | Connection pooled via openai SDK's httpx client |
| Worker → bot | Direct call on `bot.bot.send_message(...)` for push messages | Bot's `Application.bot` is shared via `app.state` |
| Bot → worker | Database row mutation (e.g. flipping `interview_sessions.status = COMPLETED`) | Worker loop picks up on next tick. No event bus. |
| Worker → SearXNG/Firecrawl | async httpx over the Docker network | Caching layer optional; add when costs justify |
| All → Postgres | SQLAlchemy 2.x async + asyncpg + pgvector-python | One engine, one pool (size ~10) — fine for single user |

---

## Migrations: Alembic in Async Mode

- Initial migration creates all 7 tables + the `vector` extension + the HNSW index.
- Use `alembic init -t async alembic/` to scaffold async-aware `env.py`.
- HNSW index needs to be created via raw SQL in the migration (Alembic autogenerate doesn't know about pgvector index types):
  ```sql
  CREATE INDEX food_visuals_embedding_idx ON food_visuals
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
  ```
- Pin Alembic to a recent version (1.13+) for clean async support.

---

## Sources

- [Managing Background Tasks in FastAPI: BackgroundTasks vs ARQ + Redis (davidmuraya.com)](https://davidmuraya.com/blog/fastapi-background-tasks-arq-vs-built-in/)
- [Python Background Tasks 2025: Celery, RQ, or Dramatiq? (DevPro Portal)](https://devproportal.com/languages/python/python-background-tasks-celery-rq-dramatiq-comparison-2025/)
- [Building Resilient Task Queues in FastAPI with ARQ Retries (davidmuraya.com)](https://davidmuraya.com/blog/fastapi-arq-retries/)
- [FastAPI + Celery Work Queues: Idempotent Tasks and Retries (Medium)](https://medium.com/@hjparmar1944/fastapi-celery-work-queues-idempotent-tasks-and-retries-that-dont-duplicate-d05e820c904b)
- [pgvector-python README (GitHub)](https://github.com/pgvector/pgvector-python/blob/master/README.md)
- [SQLAlchemy Integration | pgvector-python (DeepWiki)](https://deepwiki.com/pgvector/pgvector-python/3.1-sqlalchemy-integration)
- [IVFFlat vs HNSW in pgvector: Which Index Should You Use? (dev.to)](https://dev.to/philip_mcclarence_2ef9475/ivfflat-vs-hnsw-in-pgvector-which-index-should-you-use-305p)
- [An early look at HNSW performance with pgvector (Jonathan Katz)](https://jkatz05.com/post/postgres/pgvector-hnsw-performance/)
- [Optimize pgvector search (Neon Docs)](https://neon.com/docs/ai/ai-vector-search-optimization)
- [Long Polling vs. Webhooks (grammY)](https://grammy.dev/guide/deployment-types)
- [Webhook and ConversationHandler discussion (python-telegram-bot GitHub)](https://github.com/python-telegram-bot/python-telegram-bot/discussions/2898)
- [customwebhookbot.py example (python-telegram-bot v21.9)](https://docs.python-telegram-bot.org/en/v21.9/examples.customwebhookbot.html)
- [ConversationHandler (python-telegram-bot v21.8)](https://docs.python-telegram-bot.org/en/v21.8/telegram.ext.conversationhandler.html)
- [OpenRouter Quickstart Guide](https://openrouter.ai/docs/quickstart)
- [OpenRouter Tool & Function Calling](https://openrouter.ai/docs/guides/features/tool-calling)
- [OpenAI SDK Integration with OpenRouter](https://openrouter.ai/docs/guides/community/openai-sdk)
- [Schedule tasks with FastAPI (Sentry)](https://sentry.io/answers/schedule-tasks-with-fastapi/)
- [Lifespan Events (FastAPI Docs)](https://fastapi.tiangolo.com/advanced/events/)
- [Running Telegram bot alongside FastAPI server (Latenode Community)](https://community.latenode.com/t/running-telegram-bot-alongside-fastapi-server-in-single-python-application/26622)
- [Calibrating Uncertainty Quantification of Multi-Modal LLMs using Grounding (arxiv)](https://arxiv.org/pdf/2505.03788)
- [Confidence Calibration in LLMs (Emergent Mind)](https://www.emergentmind.com/topics/confidence-calibration-in-llms)
- [Alembic with Async SQLAlchemy (dev.to)](https://dev.to/matib/alembic-with-async-sqlalchemy-1ga)
- [Docker Deployment | pgvector (DeepWiki)](https://deepwiki.com/pgvector/pgvector/8.3-docker-deployment)
- [Firecrawl Self-Host Guide](https://github.com/firecrawl/firecrawl/blob/main/SELF_HOST.md)
- [Self-hosting FireCrawl: Complete Guide (addROM)](https://addrom.com/self-hosting-firecrawl-the-complete-guide-to-your-open-source-web-data-api-for-ai-agents/)

---
*Architecture research for: AI photo-meal-tracking pipeline (single-user, self-hosted)*
*Researched: 2026-05-24*
