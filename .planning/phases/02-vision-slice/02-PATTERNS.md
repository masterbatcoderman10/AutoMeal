# Phase 2: Vision Slice - Pattern Map

**Mapped:** 2026-05-27
**Files analyzed:** 11 planned file targets
**Analogs found:** 8 direct codebase analogs, 3 research-driven targets

This map identifies the closest existing project patterns for the files Phase 2 is expected to touch. Executors should copy these shapes before inventing new structure.

---

## File Classification

| Planned File | Role | Data Flow | Closest Analog | Match Quality |
|--------------|------|-----------|----------------|---------------|
| `app/services/vision_service.py` | service | LLM -> validation -> DB | `app/services/llm_client.py` + `app/services/image_service.py` | composite |
| `app/services/image_service.py` | service | file I/O | existing file | exact |
| `app/config.py` | config | runtime settings | existing file | exact |
| `bot/polling.py` | service | DB -> Telegram -> DB | existing file | exact |
| `bot/main.py` | entrypoint | background task wiring | existing file | exact |
| `bot/messages.py` | presentation | Telegram text | existing file | exact |
| `tests/test_vision_service.py` | contract test | pure/service logic | `tests/test_bot_contract.py` | close |
| `tests/test_bot_contract.py` | contract test | async orchestration | existing file | exact |
| `scripts/vision_smoke.py` | verification script | live OpenRouter probe | research-only | research |
| `.planning/phases/02-vision-slice/02-UAT.md` | evidence doc | manual verification | `01-UAT.md` | close |
| `.env.example` | config doc | model/env vars | existing file | exact |

---

## Concrete Reuse Patterns

### `app/services/llm_client.py` -> `app/services/vision_service.py`

**Why it matters:** Phase 2 should not create a second OpenRouter client abstraction.

**Existing shape to reuse:**

- `get_llm_client()` centralizes API-key validation
- `chat_completion()` already owns model, messages, response_format, and tool-call transport
- `OpenRouterClient` also keeps a raw `httpx.AsyncClient` for the later embedding path

**Phase 2 application:**

- add any missing `extra_body` passthrough to `chat_completion()`
- build detect/segment/label helpers on top of the shared client
- keep all parsing/normalization in `vision_service.py`, not in the transport wrapper

### `app/services/image_service.py` -> crop persistence helpers

**Why it matters:** image transcoding, hashing, and writes are already centralized.

**Existing shape to reuse:**

- `transcode_to_jpeg(...)`
- `save_upload(...)`
- `save_and_hash(...)`

**Phase 2 application:**

- add crop helpers in the same module
- continue using `Path`-based writes with `mkdir(parents=True, exist_ok=True)`
- preserve the container-absolute path contract under `/data/uploads/...`

### `bot/polling.py` -> vision worker orchestration

**Why it matters:** Phase 1 already established the DB-claim -> send Telegram -> commit transaction pattern.

**Existing shape to reuse:**

- create a local async engine in the bot process
- use `async_sessionmaker(... expire_on_commit=False, autoflush=False)`
- claim one row at a time with `with_for_update(skip_locked=True)`
- mutate the ORM object, then `await session.commit()`

**Phase 2 application:**

- keep the acknowledgement loop intact
- add a second worker loop or equivalent branch for `DETECTING` / `SEGMENTING`
- preserve error handling style: log exception, continue polling

### `bot/main.py` -> background task registration

**Why it matters:** the bot process already owns application lifecycle hooks.

**Existing shape to reuse:**

- `post_init()` creates background tasks and stores them in `application.bot_data`
- `post_shutdown()` cancels stored tasks and awaits them

**Phase 2 application:**

- register a second polling task for the vision pipeline
- keep shutdown symmetric so both tasks are canceled cleanly

### `bot/messages.py` -> terse result formatting

**Why it matters:** message tone is intentionally short and user-facing.

**Existing shape to reuse:**

- one helper per message type
- simple return-string functions with no business logic hidden inside

**Phase 2 application:**

- add one function for the final sentence result
- add one function for the soft-failure path
- keep non-food silent by letting the worker skip message send entirely

### `tests/test_bot_contract.py` -> async polling tests

**Why it matters:** this file already demonstrates the project’s preferred async test style.

**Existing shape to reuse:**

- `unittest.IsolatedAsyncioTestCase`
- `AsyncMock`, `Mock`, and `SimpleNamespace`
- patching `asyncio.sleep` to stop infinite poll loops cleanly
- asserting both side effects and final status values

**Phase 2 application:**

- add detect-worker tests beside existing polling tests
- mock model/service calls rather than hitting the network
- assert Telegram sends only on the paths that should emit final messages

### `tests/test_ingest_contract.py` -> light contract scope

**Why it matters:** contract tests in this repo stay focused and narrow.

**Phase 2 application:**

- keep `tests/test_vision_service.py` mostly pure and deterministic
- mock model payloads directly
- avoid spinning up the full FastAPI app when a service-level assertion is enough

---

## Research-Driven Targets

### `app/services/vision_service.py`

No direct file exists yet. Build it as a composition layer with these responsibilities only:

- detect schema definitions
- segment schema definitions
- label schema definitions
- raw-provider box normalization
- validation + IoU dedupe helpers
- orchestration helpers that return plain Python data structures to `bot/polling.py`

Do **not** move database writes or Telegram sends into this service. Those belong in the polling/orchestration layer.

### `scripts/vision_smoke.py`

No direct analog exists yet. Keep it script-shaped, not framework-shaped:

- read one sample image path
- call shared OpenRouter helpers through project code, not copied HTTP snippets
- print concise human-readable results for detect/segment/label
- exit non-zero if structured parsing fails

### `02-UAT.md`

Follow the same evidence style as Phase 1 UAT:

- numbered checks
- concrete commands or manual steps
- pass/fail result and notes

---

## High-Risk Files

These files will accumulate cross-plan edits and should stay wave-sequential:

- `app/services/vision_service.py`
- `bot/polling.py`
- `bot/main.py`
- `tests/test_bot_contract.py`

Do not place two plans touching the same file in the same wave.

---

*Pattern map created: 2026-05-27*
