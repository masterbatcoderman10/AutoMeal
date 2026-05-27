# Stack Research

**Domain:** Self-hosted, single-user, photo-based meal tracker with multimodal LLM pipeline
**Researched:** 2026-05-24
**Confidence:** HIGH (core stack), MEDIUM (model behavior specifics under OpenRouter)

Pinned decisions from the brief are honored: Python + FastAPI, Postgres + pgvector, OpenRouter via OpenAI SDK, Telegram bot, local SearXNG + Firecrawl, single docker-compose, APScheduler in-process. This file specifies versions, libraries surrounding those decisions, and verified facts about model availability and SDK compatibility.

---

## TL;DR — The Verified Critical Facts

1. **OpenAI SDK ↔ OpenRouter works for vision + tool calling + structured outputs against Gemini 3 family.** All four are first-class on OpenRouter via the standard `chat.completions.create()` shape. Image input accepts both URL and `data:image/jpeg;base64,...` data URLs in the standard OpenAI `image_url` content part.
2. **`google/gemini-3-flash-preview` is live on OpenRouter.** Multimodal (text/image/audio/video/PDF), 1M context, 1M context window, $0.50/M in, $3/M out. Supports tool use, structured outputs, and configurable thinking levels.
3. **`google/gemini-3.1-flash-lite-preview` and `google/gemini-3.1-flash-lite` are live** on OpenRouter — the latter is the GA name; verify in the models listing at runtime.
4. **`google/gemma-4-31b-it` is live on OpenRouter** at $0.12/M in, $0.37/M out, 262K context. There is also a free tier.
5. **`google/gemini-embedding-2-preview` is live on OpenRouter and is natively multimodal** (text + image + audio + video + PDFs into one vector space). It uses **Matryoshka Representation Learning (MRL)** with **default 3,072 dimensions** and supports truncation to **1536, 768, 512, 256, 128** with auto-renormalization. $0.20/M tokens. 8K context. **Google explicitly recommends 768 for production.**
6. **OpenRouter DOES have an embeddings endpoint** at `POST /api/v1/embeddings`, supports multimodal input (text + image_url content array), and exposes `google/gemini-embedding-2-preview`. (Some older third-party docs incorrectly claim otherwise.)
7. **Gemini 3 Flash returns bounding boxes** as `[ymin, xmin, ymax, xmax]` normalized to 0–1000, matching the schema's `bounding_box: [number, number, number, number]` field. **Mask/segmentation output is available starting from Gemini 2.5+** (request "segmentation mask" in the prompt; returns a base64 PNG per box). Gemini 3 Flash inherits this.
8. **APScheduler 4 is still in alpha** (4.0.0a6 as of May 2026). Use **APScheduler 3.x** with `AsyncIOScheduler` for this project. Honors the pinned in-process decision and stays stable.
9. **OpenRouter has no native `embeddings.create()` typed wrapper in the official OpenAI Python SDK that accepts image content** — for text-only embeddings the SDK works as-is; for image embeddings, post to `/api/v1/embeddings` directly with `httpx` and the OpenAI-compatible JSON body. (Flagged as moderate gotcha; see Pitfalls.)
10. **Schema's `vector(1024)` should be changed to `vector(768)`** to match Gemini Embedding 2's MRL-recommended production truncation. See "Schema Adjustment Required" section.

---

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **Python** | 3.12.x (or 3.13) | Runtime | Native async, free-threaded preview in 3.13, broad lib support; do not jump to 3.14 yet — pgvector/SQLAlchemy/apscheduler wheels lag |
| **FastAPI** | 0.115.x (currently 0.115.13) | HTTP + webhook framework | Pinned. Mature lifespan API, Pydantic v2 native, async-first; minimum Pydantic v2.7+ enforced |
| **Pydantic** | 2.9.x – 2.10.x | Data validation, structured-output schemas | v2 is the only supported lineage; `model_json_schema()` feeds `response_format` cleanly |
| **Uvicorn** | 0.30.x – 0.32.x | ASGI server | Standard pairing with FastAPI. Single worker is correct here (APScheduler in-process requires it) |
| **PostgreSQL** | 17.x | Primary store | Latest stable; pgvector 0.8+ ships pre-built for it |
| **pgvector (extension)** | 0.8.2 | Vector column + ANN index | Current stable, supports HNSW, IVFFlat, halfvec, binary quantization. Use HNSW for this dataset size |
| **OpenAI Python SDK** | 1.51.x – 1.55.x | LLM client (chat completions, embeddings) | Pinned. Drop-in via `base_url="https://openrouter.ai/api/v1"`. Vision + tools + JSON schema all verified |
| **python-telegram-bot** | 22.7+ | Telegram bot | Pinned domain. Fully async since v20, mature ConversationHandler for interview flow, active maintenance, Bot API 9.5 |
| **APScheduler** | **3.10.x** (NOT 4.x) | In-process scheduler for daily summary | 4.x is alpha; 3.x `AsyncIOScheduler` integrates cleanly with FastAPI lifespan |
| **SQLAlchemy** | 2.0.x (async) | ORM, migrations | Pinned to v2 async API with `postgresql+asyncpg`. First-class pgvector type via `pgvector.sqlalchemy` |
| **asyncpg** | 0.29.x – 0.30.x | Postgres async driver | Fastest Python Postgres driver; pairs cleanly with SQLAlchemy 2 async engine |
| **Alembic** | 1.13.x | DB migrations | Standard companion to SQLAlchemy; supports async metadata |
| **pgvector-python** | 0.3.x | SQLAlchemy `Vector` column type + adapters | Works with SQLAlchemy async, psycopg, asyncpg |
| **httpx** | 0.27.x | HTTP client (Firecrawl, SearXNG, raw OpenRouter embeddings calls) | Async-native, replaces `requests` |
| **Pillow** | 10.x | Image crop + base64 encode for segments | Required to crop bounding-box regions before embedding |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| **structlog** | 24.x | Structured logging | Every service log line; pairs well with single-stream docker logs |
| **python-dotenv** | 1.0.x | `.env` loader for dev | Only in development; in compose, prefer env_file directive |
| **pydantic-settings** | 2.x | Typed config from env | Single `Settings` class consumed by FastAPI dependency |
| **tenacity** | 8.x – 9.x | Retry decorator | LLM calls, OpenRouter retries, SearXNG/Firecrawl tool calls |
| **python-multipart** | 0.0.x (latest) | FastAPI form/multipart parsing | Required for iOS Shortcut multipart photo POSTs |
| **orjson** | 3.x | Fast JSON | FastAPI `default_response_class=ORJSONResponse`; LLM payload parsing |
| **numpy** | 1.26.x – 2.x | Vector ops, normalization, cosine | Required by pgvector adapters anyway |
| **anyio** | 4.x | Concurrency primitives | Already a FastAPI dep; useful for fan-out per segment |
| **APScheduler[asyncio]** | 3.10.x | Async scheduler extra | Daily 03:00 summary job |
| **APScheduler `AsyncIOScheduler`** | — | The actual scheduler class | Started in FastAPI `lifespan` |

### Tool Calling / Grounding Libraries

| Library | Purpose | Notes |
|---------|---------|-------|
| **Raw OpenAI SDK `tools=`** | Function-calling spec for SearXNG/Firecrawl tools | Pinned approach. Don't add LangChain/LlamaIndex — agent loop is simple enough to write directly |
| **Custom search-and-fetch loop** | 3-step model→tool→model orchestration | Documented in OpenRouter Tool Calling guide; ~80 lines of Python |

### Telegram Bot

| Component | Choice | Reason |
|-----------|--------|--------|
| **Library** | `python-telegram-bot` v22.7+ | Pinned. More feature-rich than aiogram, ConversationHandler is exactly the interview pattern, larger doc surface, longer lifecycle |
| **Update mode** | Webhook (not long polling) | Mac mini behind dynamic IP → use ngrok/cloudflared tunnel, OR run as polling for v1 — polling is the lowest-friction starting point |
| **Conversation state** | `ConversationHandler` + Postgres-backed `BasePersistence` | Use the schema's `InterviewSession` + `InterviewMessage` tables as the source of truth; PTB persistence is the in-flight state machine |

### Self-Hosted Grounding Tools

| Service | Image | Notes |
|---------|-------|-------|
| **SearXNG** | `searxng/searxng:latest` (v1.5.2+) | Enable JSON in `settings.yml` (`formats: [html, json]`), set `secret_key`. Hit `GET /search?q=...&format=json`. Limit engines to a small reliable set (google, duckduckgo, bing, brave) to reduce latency |
| **Firecrawl** | `ghcr.io/firecrawl/firecrawl:latest` via official `docker-compose.yaml` (5 services: api, worker, redis, playwright, nuq-postgres) | OR `devflowinc/firecrawl-simple` for a leaner alternative without billing/AI logic. Self-hosted version exposes the same REST `/v1/scrape` and `/v1/crawl` endpoints as cloud. **Loses Fire-engine** (anti-bot/proxy rotation) — fine for branded/restaurant menu pages which are usually open |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| **uv** | Package manager / venv | 10-100x faster than pip; reproducible lockfile. Use `uv pip compile` for `requirements.txt` |
| **ruff** | Linter + formatter | Replaces black + isort + flake8 in one binary |
| **mypy** or **pyright** | Type checking | Pyright is faster; mypy has wider plugin ecosystem. Either is fine |
| **pytest** + **pytest-asyncio** | Tests | Standard. Add `pytest-postgresql` for ephemeral DB in tests |
| **httpx[testing]** | Async test client | Drop-in for FastAPI `TestClient` async patterns |
| **Docker Desktop** (Mac mini) → **Colima** | Container runtime | Colima is lighter on Mac mini for daemon-style deploys |

---

## Installation

```bash
# Initialize project
uv init mealtracker
cd mealtracker

# Core
uv add fastapi==0.115.* uvicorn==0.32.* pydantic==2.10.* pydantic-settings==2.* python-multipart

# Database
uv add "sqlalchemy[asyncio]==2.0.*" asyncpg==0.30.* alembic==1.13.* pgvector==0.3.*

# LLM gateway (OpenRouter via OpenAI SDK)
uv add openai==1.55.* httpx==0.27.*

# Telegram bot
uv add "python-telegram-bot[webhooks]==22.7"

# Scheduler (3.x — NOT 4.x)
uv add "APScheduler==3.10.*"

# Image processing
uv add Pillow==10.*

# Resilience + logging + utilities
uv add tenacity==9.* structlog==24.* orjson==3.* numpy==1.26.*

# Dev
uv add --dev ruff pyright pytest pytest-asyncio pytest-postgresql httpx
```

---

## OpenRouter Compatibility Surface — Verified Findings

This is the highest-risk area of the project (the entire pipeline depends on the OpenAI SDK ↔ OpenRouter ↔ Gemini path). Findings cite OpenRouter docs.

### 1. Vision input (image_url) — **WORKS** (HIGH confidence)

OpenRouter accepts the OpenAI vision content-part format unchanged:

```python
from openai import OpenAI
client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=...)

response = client.chat.completions.create(
    model="google/gemini-3-flash-preview",
    messages=[{
        "role": "user",
        "content": [
            {"type": "text", "text": "Detect each food item. Return JSON [{label, box_2d:[ymin,xmin,ymax,xmax]}], normalized 0-1000."},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        ],
    }],
)
```

Both `https://...` URLs and `data:image/jpeg;base64,...` data URLs work. Supported MIME: PNG, JPEG, WebP, GIF. **Best practice:** put text prompt first, image second (per OpenRouter docs). Number of images per request varies per provider.

Source: [OpenRouter — Image Inputs guide](https://openrouter.ai/docs/guides/overview/multimodal/image-understanding)

### 2. Function/tool calling — **WORKS** for Gemini family (HIGH confidence)

OpenRouter passes `tools=[...]` through, model returns `finish_reason="tool_calls"` and a `tool_calls` array. Same OpenAI SDK shape. OpenRouter documentation example uses `google/gemini-3-flash-preview` and `google/gemini-2-flash` directly.

Gotcha: include `tools=` in **every** follow-up call (router validates the schema each time).

Source: [OpenRouter — Tool & Function Calling](https://openrouter.ai/docs/guides/features/tool-calling)

### 3. Structured outputs (`response_format=json_schema`) — **WORKS** for ALL Gemini models (HIGH confidence)

OpenRouter docs state: "Google Gemini: All models" support structured outputs. Use the canonical OpenAI shape:

```python
response_format={
  "type": "json_schema",
  "json_schema": {
    "name": "segments",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "segments": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "box_2d": {"type": "array", "items": {"type": "integer"}, "minItems": 4, "maxItems": 4},
                    "confidence": {"type": "number"}
                },
                "required": ["label", "box_2d", "confidence"],
                "additionalProperties": False
            }}
        },
        "required": ["segments"],
        "additionalProperties": False
    }
  }
}
```

Gotchas to anticipate:
- **`additionalProperties: false` and `required: [all keys]` are mandatory** for strict mode (OpenAI's strict-schema subset).
- **Constraints like `minLength`, `maximum`, `pattern` are stripped** by OpenAI strict mode (they're moved to field descriptions). Don't rely on them for validation; enforce post-parse with Pydantic.
- Combining vision input + structured output is documented as working ("Gemini can also produce structured responses to multimodal requests that include images, videos, and audio").

Source: [OpenRouter — Structured Outputs](https://openrouter.ai/docs/guides/features/structured-outputs)

### 4. Embeddings — **WORKS with caveats** (MEDIUM-HIGH confidence)

- `POST /api/v1/embeddings` is supported, OpenAI-compatible.
- `google/gemini-embedding-2-preview` is listed in OpenRouter's embedding model collection as a multimodal embedding.
- **Multimodal input format** uses the same content-array pattern: `{"input": [{"content": [{"type": "text", "text": ...}, {"type": "image_url", "image_url": {"url": "data:..."}}]}]}` per OpenRouter's embeddings guide.
- The official OpenAI Python SDK's `client.embeddings.create(input=...)` accepts only string/list-of-strings/token-id input — it does **not** model multimodal embedding content in its typed signature.
  - **Workaround:** call OpenRouter's embeddings endpoint with `httpx` directly for image embeddings; use the OpenAI SDK only for text-only fallback embedding calls.
  - The `extra_body` parameter on OpenAI SDK calls is the documented escape hatch for provider-specific params if you choose to wrangle it through the SDK.

Source: [OpenRouter — Embeddings API](https://openrouter.ai/docs/api/reference/embeddings), [OpenRouter — Embedding Models collection](https://openrouter.ai/collections/embedding-models)

### 5. OpenRouter-specific headers

```python
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ["OPENROUTER_API_KEY"],
    default_headers={
        "HTTP-Referer": "https://mealtracker.local",   # optional, attribution
        "X-Title": "MealTracker",                       # optional, attribution
    },
)
```

Both headers are optional but recommended for OpenRouter dashboard/leaderboard attribution. Note OpenRouter docs use both `X-Title` and `X-OpenRouter-Title` in different examples — `X-Title` is the canonical form documented in their quickstart.

### 6. Provider routing / fallbacks

OpenRouter supports per-request provider routing via the `provider` field in the request body (passed through `extra_body`):

```python
extra_body={
    "provider": {
        "order": ["Google AI Studio", "Google Vertex"],
        "allow_fallbacks": True,
    }
}
```

Useful if Google AI Studio rate-limits — auto-fallback to Vertex. **Not required for v1**; default routing picks lowest-latency provider that meets the request's feature flags.

### 7. Streaming / retries / timeouts / errors

- **Streaming:** Works (`stream=True`); error events are sent as SSE comments. For this project, streaming is NOT needed (no UX waiting on tokens) — disable it.
- **Timeouts:** OpenAI SDK default 600s. Set explicit per-call: `client.with_options(timeout=60).chat.completions.create(...)`.
- **Retries:** OpenAI SDK has `max_retries=2` default. Wrap with `tenacity` for full control (exponential backoff, jitter, per-error retry policy).
- **Error shape:** OpenAI-style `APIError` subclasses. Provider-specific errors are surfaced in `error.metadata`. OpenRouter docs note rate-limit errors include `retry-after` metadata.

---

## Model Pins — Verified on OpenRouter (2026-05-24)

| Pinned ID (from brief) | Status on OpenRouter | Verified ID | Notes |
|------------------------|----------------------|-------------|-------|
| `google/gemma-4-31b-it` | LIVE | `google/gemma-4-31b-it` | 262K ctx, $0.12/M in / $0.37/M out; free tier exists |
| `google/gemini-3-flash-preview` | LIVE | `google/gemini-3-flash-preview` | 1M ctx, $0.50/M in / $3/M out; vision + tools + JSON schema + thinking levels |
| `google/gemini-3.1-flash-lite` | LIVE | `google/gemini-3.1-flash-lite` (and `google/gemini-3.1-flash-lite-preview` if preview is desired) | 1.05M ctx, $0.25/M in / $1.50/M out |
| `google/gemini-embedding-2-preview` | LIVE | `google/gemini-embedding-2-preview` | 8K ctx, $0.20/M tok, **multimodal**, MRL with default 3072 dims, truncatable to 1536/768/512/256/128 |

**One sharp edge to verify in code on first run:** OpenRouter occasionally renames preview IDs as models reach GA (`-preview` → no suffix). Add a lightweight startup check that GETs `/api/v1/models` and asserts all four pinned IDs are present; log and fall back to the closest non-preview variant if not.

### Gemini 3 Flash — Pipeline-Relevant Capabilities

| Capability | Status | Use in pipeline |
|------------|--------|-----------------|
| Multimodal input (image) | YES | Detection, segmentation, reasoning, interview prompts |
| Tool calling | YES | Reasoning + post-interview stages call SearXNG + Firecrawl |
| Structured outputs (JSON Schema) | YES | All stages should use this for reliable parsing of `{label, box_2d, confidence}` |
| Bounding boxes `[ymin,xmin,ymax,xmax]` 0–1000 | YES (inherited from Gemini 2.5+ behavior) | Direct match for schema's `MealSegment.bounding_box` |
| Segmentation masks (per-box base64 PNG) | YES (Gemini 2.5+ pattern carries into 3.x) | Optional — not required by schema; skip for v1 |
| Configurable thinking ("minimal/low/medium/high") | YES | Use `low` for detection, `medium` for reasoning, `minimal` for interview turns |
| 1M token context | YES | More than enough; interview history is tiny |

### Gemini Embedding 2 — Verified Specifics

| Attribute | Value | Source |
|-----------|-------|--------|
| Native dimensionality | **3072** | Google blog, OpenRouter model page |
| MRL truncation | YES — to 1536, 768, 512, 256, 128 | Google blog, MindStudio |
| Google's recommended production dim | **768** | Google blog, Google Developers blog |
| Modalities | text, image, audio, video, PDF (single vector space) | Google blog (March 2026) |
| Normalization | Native 3072 always normalized; truncated dims auto-renormalize | Google blog |
| Context window | 8,192 tokens | OpenRouter model page |
| Price | $0.20 / 1M tokens | OpenRouter model page |
| Task types | RETRIEVAL_QUERY, RETRIEVAL_DOCUMENT, SEMANTIC_SIMILARITY, CLASSIFICATION, CLUSTERING, CODE_RETRIEVAL_QUERY, QUESTION_ANSWERING, FACT_VERIFICATION | Google API docs — pass via `extra_body` |

### Schema Adjustment Required

The schema currently declares `vector(1024)`. **1024 is NOT a native or MRL-truncatable dimensionality** for Gemini Embedding 2. Options:

| Option | Vector size | Tradeoff |
|--------|-------------|----------|
| **Recommended: change schema to `vector(768)`** | 768 | Google's production recommendation; ~75% storage reduction vs 3072; near-peak retrieval quality |
| Use `vector(1536)` | 1536 | Higher quality, 2× storage, very small quality bump per Google's own benchmarks |
| Use `vector(3072)` | 3072 | Maximum quality, 4× storage. Overkill for ~few thousand visuals |
| Keep `vector(1024)` and pad/truncate | 1024 | **Don't.** MRL only guarantees quality at the published truncation points |

**Concrete recommendation: change `vector(1024)` → `vector(768)`** in `FoodVisuals.embedding` and `MealSegments.embedding`, set Gemini Embedding 2 `output_dimensionality=768`, and set `task_type="RETRIEVAL_DOCUMENT"` for FoodVisuals writes and `task_type="RETRIEVAL_QUERY"` for MealSegment search vectors.

---

## Stack Patterns by Variant

**If you ever need an LLM beyond Google (Claude/GPT-4o):**
- Code already routes through OpenRouter — flip the `model` string only. No SDK or schema changes needed (the JSON Schema strict mode behaviour is consistent across providers).

**If iOS Shortcuts photo capture trigger turns out to be unreliable:**
- Fall back to a personal automation on a time trigger that runs "Get Latest Photos (limit 1) → POST to endpoint", run on demand.
- Alternative: a "Share Sheet" shortcut from Photos that the user invokes manually after each meal photo. Slower but bulletproof.

**If Firecrawl self-hosted is too heavy (~5 containers):**
- Use `devflowinc/firecrawl-simple` instead — billing + AI services stripped, single API container + Redis + Playwright.

**If APScheduler 4 reaches stable before this project ships:**
- Migrate via its `current_scheduler()` async context manager and the SQLAlchemy data store; gain durability across restarts. Not worth the risk pre-stable.

**If Mac mini is replaced by an x86 VM:**
- Ensure all images are multi-arch (`linux/amd64,linux/arm64`). All pinned images above are multi-arch on Docker Hub / GHCR. Pillow + pgvector + asyncpg wheels are also multi-arch.

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| **python-telegram-bot** | aiogram 3.x | If you find PTB's middleware/state model heavy. aiogram is more "FastAPI-shaped" (router/middleware) but smaller community and steeper async learning curve |
| **APScheduler 3.x (in-process)** | arq + Redis worker | If pipeline ever needs durability (job survives crash). Adds Redis dependency. Not justified at v1 scale |
| **SQLAlchemy 2 async + asyncpg** | Raw asyncpg | 2× raw throughput, but you lose migrations, ORM-shaped models, and pgvector convenience adapters. Not worth it for solo dev |
| **HNSW index** | IVFFlat | Only if dataset grows to millions of vectors AND memory becomes a constraint. At <50K rows, HNSW wins on every axis |
| **pgvector 0.8 `vector` type** | pgvector `halfvec` (FP16) | If storage doubles by year-2 and you want to halve it. Easy migration later — no design lock-in now |
| **Firecrawl full self-host** | firecrawl-simple | If you don't need crawl orchestration / queues — only scrape one URL at a time |
| **httpx for raw OpenRouter embeddings call** | OpenAI SDK `embeddings.create()` | SDK works for **text-only** embedding input. For multimodal embeddings (image content), use httpx |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| **APScheduler 4.x (alpha)** | Pre-release; "do NOT use in production" per maintainer | APScheduler 3.10.x with `AsyncIOScheduler` |
| **psycopg2 / psycopg2-binary** | Sync only; doesn't play with FastAPI async lifecycle | `asyncpg` (with SQLAlchemy 2) or `psycopg[binary,pool]` v3 |
| **Pydantic v1** | EOL for FastAPI; v1 quirks differ in JSON Schema generation, breaking strict-mode structured outputs | Pydantic 2.9+ |
| **Celery** | Sync-first; broker overhead + worker complexity unjustified for single-user fire-and-forget | FastAPI `BackgroundTasks` for trivial work; arq if you ever need durable async jobs |
| **LangChain / LlamaIndex** | Heavy abstraction for a 3-call agent loop you can write in 80 lines; obscures OpenRouter-specific behavior | Direct OpenAI SDK + your own tool-orchestration loop |
| **Instructor / outlines / marvin** | Wrap structured outputs in extra abstraction; OpenRouter's native `response_format=json_schema` is already strict | Native `response_format` with Pydantic `model_json_schema()` |
| **`requests` (sync)** | Sync HTTP blocks the FastAPI event loop | `httpx.AsyncClient` |
| **FastAPI `@app.on_event("startup")`** | Deprecated since 0.95 | `lifespan` context manager |
| **`response_class=JSONResponse`** | 3-5× slower than orjson | `default_response_class=ORJSONResponse` app-wide |
| **`vector(1024)` in this schema** | Not an MRL truncation point for Gemini Embedding 2 | `vector(768)` (production-recommended) |
| **Webhook for Telegram on v1** | Mac mini behind dynamic IP; ngrok/cloudflared adds an external dep with auth churn | Long polling (`Application.run_polling()`) is the lowest-friction default |
| **iOS Shortcut `Take Photo` action** | Requires app focus / user tap | "When latest photo added to Camera Roll" personal automation, OR Share Sheet shortcut from Photos |

---

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| `fastapi==0.115.*` | `pydantic>=2.7,<3` | FastAPI 0.115 dropped Pydantic v1 entirely |
| `sqlalchemy==2.0.*[asyncio]` | `asyncpg==0.30.*` | Use connection URL `postgresql+asyncpg://...`. Avoid `+psycopg2` mixed with asyncpg in same engine |
| `pgvector==0.3.*` (python) | `pgvector` Postgres extension 0.5+ | `pgvector.sqlalchemy.Vector` is the column type |
| `python-telegram-bot==22.7` | `python>=3.10`, `httpx`, `tornado` (optional) | Webhook mode needs `[webhooks]` extra (pulls tornado) |
| `apscheduler==3.10.*` | `python>=3.8`, runs on existing asyncio loop | Set `event_loop=asyncio.get_event_loop()` inside FastAPI lifespan, OR use `AsyncIOScheduler()` which discovers it |
| `openai==1.55.*` | `httpx>=0.23`, `pydantic>=1.9` | SDK is OpenAI-shape only; Anthropic-shape (`messages.create`) is not exposed through OpenRouter via this SDK |
| `pgvector` Postgres extension 0.8.2 | `postgres>=13` | Pre-built in `pgvector/pgvector:pg17` image |

---

## Docker Compose Skeleton (verified, minimal)

```yaml
services:
  api:
    build: .
    env_file: .env
    ports: ["8000:8000"]
    depends_on:
      postgres: { condition: service_healthy }
      searxng:  { condition: service_started }
      firecrawl-api: { condition: service_started }
    restart: unless-stopped

  postgres:
    image: pgvector/pgvector:pg17
    env_file: .env
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $$POSTGRES_USER -d $$POSTGRES_DB"]
      interval: 5s
      timeout: 5s
      retries: 10
    restart: unless-stopped

  searxng:
    image: searxng/searxng:latest
    volumes:
      - ./searxng/settings.yml:/etc/searxng/settings.yml:ro
    environment:
      - SEARXNG_SECRET=${SEARXNG_SECRET}
    restart: unless-stopped

  firecrawl-api:
    image: ghcr.io/firecrawl/firecrawl:latest
    env_file: .env.firecrawl
    depends_on: [firecrawl-redis, firecrawl-playwright]
    restart: unless-stopped

  firecrawl-redis:
    image: redis:7-alpine
    restart: unless-stopped

  firecrawl-playwright:
    image: ghcr.io/firecrawl/playwright-service:latest
    restart: unless-stopped

volumes:
  pgdata:
```

Notes:
- All images above are multi-arch (`linux/amd64`, `linux/arm64`) — Mac mini → VM portability is intact.
- Single API container (one Uvicorn worker) so APScheduler runs in exactly one process.
- SearXNG `settings.yml` MUST set `search.formats: [html, json]` and `server.secret_key` — JSON output is off by default.
- Firecrawl image set comes from the official `firecrawl/docker-compose.yaml`; swap to `devflowinc/firecrawl-simple` if you want a leaner stack.

---

## Pipeline Stage → Model Map (for downstream roadmap consumers)

| Stage | Model | Mode | Notes |
|-------|-------|------|-------|
| 1. Detect (is-food) | `google/gemma-4-31b-it` | text+image, `response_format=json_schema` | Schema: `{is_food: bool, confidence: float}`. Cheap, fast |
| 2. Segment (bounding boxes) | `google/gemini-3-flash-preview` | text+image, structured output, thinking=low | Schema: `{segments: [{label, box_2d:[y,x,y,x], confidence}]}`. Coords 0–1000 |
| 3. Embed (per-crop) | `google/gemini-embedding-2-preview` | multimodal embedding via raw httpx POST | `output_dimensionality=768`, `task_type=RETRIEVAL_DOCUMENT` for writes, `RETRIEVAL_QUERY` for searches |
| 4. Match | pgvector HNSW | cosine `<=>` operator | Threshold 0.75 (cosine similarity) initially; tune later |
| 5. Reason (uncertain) | `google/gemini-3-flash-preview` | text+image, **with tools** (SearXNG, Firecrawl), thinking=medium | Tools called when LLM uncertain about brand/restaurant |
| 6. Interview | `google/gemini-3.1-flash-lite` (cheap tier) OR `google/gemini-3-flash-preview` | text only after initial image context, structured output for parsed answers | Per `InterviewMessageKey` turns. Cheap tier is fine — interview is text-driven |
| 7. Re-ground (post-interview) | `google/gemini-3-flash-preview` | text + tools | Same as stage 5 but with interview answers in context |

---

## Sources

### OpenRouter (HIGH confidence)
- [OpenRouter Quickstart — OpenAI SDK base_url + headers](https://openrouter.ai/docs/quickstart)
- [OpenRouter Image Inputs — vision content array, URL + base64](https://openrouter.ai/docs/guides/overview/multimodal/image-understanding)
- [OpenRouter Tool & Function Calling — Gemini 3 Flash example](https://openrouter.ai/docs/guides/features/tool-calling)
- [OpenRouter Structured Outputs — "Google Gemini: All models" support](https://openrouter.ai/docs/guides/features/structured-outputs)
- [OpenRouter Embeddings API — POST /api/v1/embeddings, multimodal input](https://openrouter.ai/docs/api/reference/embeddings)
- [OpenRouter Embedding Models — Gemini Embedding 2 Preview listed as multimodal](https://openrouter.ai/collections/embedding-models)
- [OpenRouter Google models — Gemini 3 Flash Preview specs/pricing](https://openrouter.ai/google)
- [OpenRouter Gemini 3 Flash Preview model page](https://openrouter.ai/google/gemini-3-flash-preview)
- [OpenRouter Gemini Embedding 2 Preview model page](https://openrouter.ai/google/gemini-embedding-2-preview)

### Google Gemini (HIGH confidence)
- [Google Blog — Gemini Embedding 2: first natively multimodal embedding model](https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-embedding-2/)
- [Google Developers — Building with Gemini Embedding 2](https://developers.googleblog.com/building-with-gemini-embedding-2/)
- [Gemini API — Image Understanding (bounding boxes 0–1000 normalized)](https://ai.google.dev/gemini-api/docs/image-understanding)
- [Gemini API — Structured Outputs](https://ai.google.dev/gemini-api/docs/structured-output)
- [Gemini API — Embeddings (task types, dimensions)](https://ai.google.dev/gemini-api/docs/embeddings)

### Python ecosystem (HIGH confidence)
- [FastAPI release notes — 0.115 series, Pydantic v2 only](https://fastapi.tiangolo.com/release-notes/)
- [FastAPI lifespan events docs](https://fastapi.tiangolo.com/advanced/events/)
- [python-telegram-bot v22.7 docs](https://docs.python-telegram-bot.org/en/stable/)
- [python-telegram-bot ConversationHandler](https://docs.python-telegram-bot.org/en/stable/telegram.ext.conversationhandler.html)
- [APScheduler version history — 4.x is alpha](https://apscheduler.readthedocs.io/en/master/versionhistory.html)
- [pgvector-python README — SQLAlchemy + async](https://github.com/pgvector/pgvector-python)
- [pgvector Docker image (pg17)](https://hub.docker.com/r/pgvector/pgvector)
- [SQLAlchemy 2 async docs](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)

### Tooling (MEDIUM confidence — secondary sources)
- [SearXNG self-host + JSON API enable docs (community guides, multiple agreeing)](https://nolowiz.com/how-to-use-searxng-as-a-private-search-api-step-by-step-guide/)
- [Firecrawl SELF_HOST.md (official)](https://github.com/firecrawl/firecrawl/blob/main/SELF_HOST.md)
- [firecrawl-simple alternative](https://github.com/devflowinc/firecrawl-simple)
- [pgvector HNSW vs IVFFlat 2026 guidance](https://medium.com/@philmcc/pgvector-index-selection-ivfflat-vs-hnsw-for-postgresql-vector-search-6eff26aaa90c)

### iOS (MEDIUM confidence — Apple docs are sparse on exact trigger semantics)
- [iOS Shortcuts personal automation intro](https://support.apple.com/guide/shortcuts/intro-to-personal-automation-apd690170742/ios)
- [iOS Shortcuts — request your first API](https://support.apple.com/guide/shortcuts/request-your-first-api-apd58d46713f/ios)

---

*Stack research for: self-hosted single-user multimodal meal-tracking pipeline*
*Researched: 2026-05-24*
