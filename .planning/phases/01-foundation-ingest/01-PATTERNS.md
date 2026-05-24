# Phase 1: Foundation & Ingest - Pattern Map

**Mapped:** 2026-05-24
**Files analyzed:** 18 new files (greenfield project)
**Analogs found:** 0 / 18 from codebase (no Python source exists yet)

> **Greenfield note:** The repository contains only two read-only TypeScript reference files
> (`MealTracker_Schema_Types.ts`, `MealTracker_Schema.mermaid`). All patterns below are
> sourced from RESEARCH.md, which contains the authoritative code patterns for this stack.
> The planner should treat these excerpts as the copy-from source — they are the patterns
> the executor will replicate file by file.

---

## File Classification

| New File | Role | Data Flow | Closest Analog | Match Quality |
|----------|------|-----------|----------------|---------------|
| `app/main.py` | entrypoint | request-response | RESEARCH.md §1 lifespan pattern | research-only |
| `app/config.py` | config | — | RESEARCH.md §5 Settings pattern | research-only |
| `app/database.py` | utility | CRUD | RESEARCH.md §1 engine/session pattern | research-only |
| `app/models/base.py` | model | — | RESEARCH.md §2 DeclarativeBase | research-only |
| `app/models/meal_log.py` | model | CRUD | RESEARCH.md §2 MealLog model | research-only |
| `app/models/meal_segment.py` | model | CRUD | RESEARCH.md §2 MealSegment model | research-only |
| `app/models/food_item.py` | model | CRUD | RESEARCH.md §2 FoodItem model | research-only |
| `app/models/food_visual.py` | model | CRUD | RESEARCH.md §2 FoodVisual + HNSW index | research-only |
| `app/models/diary_entry.py` | model | CRUD | RESEARCH.md §2 DiaryEntry model | research-only |
| `app/models/__init__.py` | config | — | barrel re-export pattern | research-only |
| `app/routers/ingest.py` | router | request-response | RESEARCH.md §3 endpoint pattern | research-only |
| `app/routers/health.py` | router | request-response | simple health-check pattern | research-only |
| `app/services/image_service.py` | service | file-I/O | RESEARCH.md §3 transcode/save/hash | research-only |
| `app/services/llm_client.py` | service | request-response | RESEARCH.md §6 OpenRouterClient | research-only |
| `app/schemas/responses.py` | utility | — | Pydantic response model pattern | research-only |
| `bot/main.py` | entrypoint | event-driven | RESEARCH.md §4 PTB Application | research-only |
| `bot/polling.py` | service | CRUD | RESEARCH.md §4 poll_and_acknowledge | research-only |
| `migrations/versions/001_initial.py` | migration | — | RESEARCH.md §2 Alembic pattern | research-only |

---

## Pattern Assignments

### `app/main.py` (entrypoint, request-response)

**Source:** RESEARCH.md §1 — FastAPI + SQLAlchemy 2 Async

**Imports pattern:**
```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.config import get_settings
from app.database import create_engine, get_engine
from app.routers import ingest, health
```

**Lifespan pattern (CRITICAL — do NOT use `@app.on_event`):**
```python
scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    create_engine(settings.DATABASE_URL)
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)
    await get_engine().dispose()

app = FastAPI(lifespan=lifespan, default_response_class=ORJSONResponse)
app.include_router(ingest.router)
app.include_router(health.router)
```

**Critical constraints:**
- Run with exactly `--workers 1` — APScheduler in-process requires a single worker.
- Use `ORJSONResponse` as `default_response_class` (3–5x faster than JSONResponse).
- Router registration goes after `app = FastAPI(...)`.

---

### `app/config.py` (config)

**Source:** RESEARCH.md §5 — Config Pattern

**Full pattern:**
```python
from pathlib import Path
from functools import lru_cache
from pydantic import ConfigDict
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Database
    DATABASE_URL: str

    # Auth
    INGEST_SECRET: str

    # Telegram
    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_CHAT_ID: str

    # OpenRouter
    OPENROUTER_API_KEY: str
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"

    # Paths
    UPLOADS_DIR: Path = Path("/data/uploads")

    # Polling
    BOT_POLL_INTERVAL: float = 3.0

    # Dedup
    DEDUP_WINDOW_SECONDS: int = 60

    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

@lru_cache
def get_settings() -> Settings:
    return Settings()
```

**Critical constraints:**
- `case_sensitive=True` — env var names are uppercase throughout.
- `@lru_cache` on `get_settings()` — Settings object is constructed once and reused across the process (avoids re-reading `.env` on every call).
- Both `app/` and `bot/` import from `app.config` — shared config module.

---

### `app/database.py` (utility, CRUD)

**Source:** RESEARCH.md §1 — App Structure & Engine Setup

**Engine pattern:**
```python
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine, async_sessionmaker
from typing import AsyncGenerator

_engine: AsyncEngine | None = None

def create_engine(url: str, echo: bool = False) -> AsyncEngine:
    global _engine
    _engine = create_async_engine(
        url,
        echo=echo,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
    )
    return _engine

def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        raise RuntimeError("Engine not initialized — call create_engine() in lifespan first")
    return _engine
```

**Session factory pattern:**
```python
# NOTE: async_sessionmaker is bound lazily — call after create_engine()
def get_session_factory():
    return async_sessionmaker(
        bind=get_engine(),
        expire_on_commit=False,   # prevents DetachedInstanceError in async contexts
        autoflush=False,
        class_=AsyncSession,
    )

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with get_session_factory()() as session:
        yield session
```

**Critical constraints:**
- `expire_on_commit=False` is mandatory for async — prevents detached instance errors when accessing ORM objects after `await session.commit()`.
- `pool_pre_ping=True` — validates connections before use (avoids stale connection errors after container restart).
- Connection URL format: `postgresql+asyncpg://user:pass@host:5432/dbname`

---

### `app/models/base.py` (model)

**Source:** RESEARCH.md §2 — SQLAlchemy 2 Declarative Models

**Pattern:**
```python
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass
```

All model files import `Base` from here. Single definition point — never re-declare `DeclarativeBase` in individual model files.

---

### `app/models/meal_log.py` (model, CRUD)

**Source:** RESEARCH.md §2 — MealLog model

**Full pattern:**
```python
from datetime import datetime
from enum import Enum as PyEnum
from typing import TYPE_CHECKING, List
from sqlalchemy import String, Enum, Index, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import TIMESTAMPTZ
from app.models.base import Base

if TYPE_CHECKING:
    from app.models.meal_segment import MealSegment
    from app.models.diary_entry import DiaryEntry

class MealProcessingStatus(PyEnum):
    PENDING = "PENDING"
    DETECTING = "DETECTING"
    SEGMENTING = "SEGMENTING"
    EMBEDDING = "EMBEDDING"
    MATCHING = "MATCHING"
    REASONING = "REASONING"
    INTERVIEWING = "INTERVIEWING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"        # REQUIRED — do not omit (D-14 / Phase 1 SC #5)

class MealLog(Base):
    __tablename__ = "meal_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    image_url: Mapped[str] = mapped_column(String(512), nullable=False)
    image_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # SHA-256 hex (D-14)
    processing_status: Mapped[MealProcessingStatus] = mapped_column(
        Enum(MealProcessingStatus, name="meal_processing_status", create_type=True),
        nullable=False,
        default=MealProcessingStatus.PENDING,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now()
    )

    segments: Mapped[List["MealSegment"]] = relationship(back_populates="meal_log")

# Composite index for 60-second dedup lookups (INGEST-05)
Index("ix_meal_logs_image_hash_created", MealLog.image_hash, MealLog.created_at)
```

**Critical constraints:**
- `FAILED` MUST be in `MealProcessingStatus` — the pre-work `.ts` file omits it; the Python model must add it.
- `image_hash` column is required for dedup (D-14).
- `TIMESTAMPTZ(timezone=True)` — NOT `DateTime`. All timestamp columns require TIMESTAMPTZ (D-13).
- `server_default=func.now()` sets the default at the Postgres side, not application side.
- `create_type=True` on the Enum column — SQLAlchemy creates the Postgres type on `create_all()`.

---

### `app/models/meal_segment.py` (model, CRUD)

**Source:** RESEARCH.md §2 — MealSegment model

**Key pattern:**
```python
from typing import TYPE_CHECKING, List
from sqlalchemy import String, Text, JSON, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import TIMESTAMPTZ
from pgvector.sqlalchemy import Vector
from app.models.base import Base

if TYPE_CHECKING:
    from app.models.meal_log import MealLog
    from app.models.diary_entry import DiaryEntry

class PortionBucket(PyEnum):
    SMALL = "SMALL"
    STANDARD = "STANDARD"
    LARGE = "LARGE"

class MealSegment(Base):
    __tablename__ = "meal_segments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    meal_log_id: Mapped[str] = mapped_column(ForeignKey("meal_logs.id"), nullable=False)
    label: Mapped[str | None] = mapped_column(String(256), nullable=True)
    bounding_box: Mapped[list | None] = mapped_column(JSON, nullable=True)
    cropped_image_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    embedding: Mapped[List[float] | None] = mapped_column(Vector(1536), nullable=True)
    ai_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    portion_bucket: Mapped[str | None] = mapped_column(
        Enum(PortionBucket, name="portion_bucket", create_type=True), nullable=True
    )   # D-14: replaces quantity_multiplier float from TS schema
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ(timezone=True), nullable=False, server_default=func.now()
    )

    meal_log: Mapped["MealLog"] = relationship(back_populates="segments")
```

**Critical constraints:**
- `Vector(1536)` — NOT `vector(1024)` from the TypeScript reference (MATCH-01).
- `portion_bucket` ENUM (`SMALL/STANDARD/LARGE`) replaces `quantity_multiplier: float` from the pre-work schema (D-14).
- `bounding_box` stored as JSON (list of 4 floats: `[ymin, xmin, ymax, xmax]` in 0–1000 coords from Gemini).

---

### `app/models/food_visual.py` (model, CRUD)

**Source:** RESEARCH.md §2 — FoodVisual model with HNSW index

**Full pattern (HNSW index is the critical piece):**
```python
from typing import TYPE_CHECKING, List
from sqlalchemy import String, Boolean, ForeignKey, Index, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import TIMESTAMPTZ
from pgvector.sqlalchemy import Vector
from app.models.base import Base

if TYPE_CHECKING:
    from app.models.food_item import FoodItem

class FoodVisual(Base):
    __tablename__ = "food_visuals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    food_item_id: Mapped[str] = mapped_column(ForeignKey("food_items.id"), nullable=False)
    cropped_image_url: Mapped[str] = mapped_column(String(512), nullable=False)
    embedding: Mapped[List[float]] = mapped_column(Vector(1536), nullable=False)
    is_invalidated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # D-14
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ(timezone=True), nullable=False, server_default=func.now()
    )

    food_item: Mapped["FoodItem"] = relationship(back_populates="visuals")

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

**Critical constraints:**
- `Vector(1536)` — NOT `vector(1024)`.
- `postgresql_using="hnsw"` — NOT IVFFlat. The pre-work schema uses IVFFlat; it is wrong (MATCH-01).
- HNSW params: `m=16, ef_construction=64` — must match exactly (MATCH-01).
- `postgresql_ops={"embedding": "vector_cosine_ops"}` — cosine distance for vector search.
- `is_invalidated` column added for USER_CORRECTED cascade (D-14).

---

### `app/models/food_item.py` (model, CRUD)

**Source:** RESEARCH.md §2 — FoodItem model

**Key pattern:**
```python
from sqlalchemy import String, Float, Text, JSON, Boolean, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import TIMESTAMPTZ
from app.models.base import Base

class FoodItem(Base):
    __tablename__ = "food_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    aliases: Mapped[list | None] = mapped_column(JSON, nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    brand_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    restaurant_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    serving_size_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    calories: Mapped[float | None] = mapped_column(Float, nullable=True)
    protein_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    carbs_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    fat_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    fiber_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    times_confirmed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    llm_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now()
    )

    visuals: Mapped[List["FoodVisual"]] = relationship(back_populates="food_item")
    diary_entries: Mapped[List["DiaryEntry"]] = relationship(back_populates="food_item")
```

---

### `app/models/diary_entry.py` (model, CRUD)

**Source:** RESEARCH.md §2 — DiaryEntry model

**Key pattern:**
```python
class DiaryEntry(Base):
    __tablename__ = "diary_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    meal_log_id: Mapped[str] = mapped_column(ForeignKey("meal_logs.id"), nullable=False)
    food_item_id: Mapped[str] = mapped_column(ForeignKey("food_items.id"), nullable=False)
    segment_id: Mapped[str | None] = mapped_column(ForeignKey("meal_segments.id"), nullable=True)
    portion_bucket: Mapped[str] = mapped_column(String(32), nullable=False)
    identification_method: Mapped[str] = mapped_column(String(32), nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ(timezone=True), nullable=False, server_default=func.now()
    )
```

---

### `app/models/__init__.py` (barrel re-export)

**Pattern:** Import all model classes and the enum. This allows other modules to do `from app.models import MealLog, MealProcessingStatus` without knowing which submodule each lives in.

```python
from app.models.base import Base
from app.models.meal_log import MealLog, MealProcessingStatus
from app.models.meal_segment import MealSegment, PortionBucket
from app.models.food_item import FoodItem
from app.models.food_visual import FoodVisual
from app.models.diary_entry import DiaryEntry

__all__ = [
    "Base",
    "MealLog", "MealProcessingStatus",
    "MealSegment", "PortionBucket",
    "FoodItem",
    "FoodVisual",
    "DiaryEntry",
]
```

---

### `app/routers/ingest.py` (router, request-response)

**Source:** RESEARCH.md §3 — Image Ingestion Endpoint

**Imports pattern:**
```python
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Header
from fastapi.responses import ORJSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.config import get_settings
from app.database import get_session
from app.models import MealLog, MealProcessingStatus
from app.services.image_service import save_and_hash_upload
import uuid
from datetime import datetime, timedelta, timezone
```

**Auth pattern (shared-secret header):**
```python
router = APIRouter(prefix="/ingest", tags=["ingest"])

@router.post("/photo", status_code=202)
async def ingest_photo(
    picture: UploadFile = File(...),          # field name matches iOS Shortcut (D-10)
    x_ingest_secret: str = Header(..., alias="X-Ingest-Secret"),
    session: AsyncSession = Depends(get_session),
):
    settings = get_settings()
    if x_ingest_secret != settings.INGEST_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")
```

**Dedup pattern (INGEST-05):**
```python
    raw_bytes = await picture.read()
    image_hash = hashlib.sha256(raw_bytes).hexdigest()

    window_start = datetime.now(timezone.utc) - timedelta(seconds=settings.DEDUP_WINDOW_SECONDS)
    result = await session.execute(
        select(MealLog)
        .where(MealLog.image_hash == image_hash, MealLog.created_at >= window_start)
        .order_by(MealLog.created_at.desc())
        .limit(1)
    )
    existing = result.scalar_one_or_none()
    if existing:
        return ORJSONResponse(
            status_code=200,
            content={"meal_log_id": existing.id, "deduplicated": True}
        )
```

**Core CRUD + file-save pattern:**
```python
    meal_id = str(uuid.uuid4())
    dest_path = settings.UPLOADS_DIR / "meals" / f"{meal_id}.jpg"
    await save_and_hash_upload(raw_bytes, picture.content_type, dest_path)

    meal = MealLog(
        id=meal_id,
        image_url=str(dest_path),
        image_hash=image_hash,
        processing_status=MealProcessingStatus.PENDING,
    )
    session.add(meal)
    await session.commit()

    return ORJSONResponse(status_code=202, content={"meal_log_id": meal_id})
```

**Error handling pattern:**
```python
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error in ingest_photo")
        raise HTTPException(status_code=500, detail="Internal server error")
```

---

### `app/routers/health.py` (router, request-response)

**Pattern:** Minimal health-check router. Returns 200 with a JSON body so docker-compose healthcheck `curl -f http://localhost:8000/health` succeeds.

```python
from fastapi import APIRouter
from fastapi.responses import ORJSONResponse

router = APIRouter(tags=["health"])

@router.get("/health")
async def health():
    return ORJSONResponse({"status": "ok"})
```

---

### `app/services/image_service.py` (service, file-I/O)

**Source:** RESEARCH.md §3 — HEIC → JPEG Transcoding

**Full pattern:**
```python
from pathlib import Path
from io import BytesIO
from fastapi import HTTPException

HEIC_CONTENT_TYPES = {"image/heic", "image/heif", "image/heic+heif"}

def transcode_to_jpeg(raw_bytes: bytes, content_type: str) -> bytes:
    """Convert HEIC/HEIF or passthrough JPEG to JPEG bytes."""
    if content_type in HEIC_CONTENT_TYPES:
        import pillow_heif
        heif_file = pillow_heif.read_heif(raw_bytes)
        from PIL import Image
        image = Image.frombytes(
            heif_file.mode, heif_file.size, heif_file.data, "raw"
        )
        buf = BytesIO()
        image.save(buf, format="JPEG", quality=85)
        return buf.getvalue()
    elif content_type and content_type.startswith("image/"):
        return raw_bytes  # already JPEG
    else:
        raise HTTPException(400, f"Unsupported content type: {content_type}")

def save_upload(jpeg_bytes: bytes, dest_path: Path) -> None:
    """Write JPEG bytes to the named volume path."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(jpeg_bytes)
```

**Critical constraints:**
- Input field from iOS Shortcut is `picture` (D-10).
- HEIC transcoding happens before SHA-256 hash? No — hash the **raw bytes** before transcoding (INGEST-05 requires hash of original).
- Store JPEG at `/data/uploads/meals/{uuid}.jpg` — absolute container path (D-06, D-07).
- Quality 85 is a reasonable JPEG quality for visual embedding purposes.

---

### `app/services/llm_client.py` (service, request-response)

**Source:** RESEARCH.md §6 — OpenRouter Client Skeleton

**Full skeleton pattern:**
```python
from openai import AsyncOpenAI
import httpx
from typing import List
from app.config import get_settings

class OpenRouterClient:
    """Phase 1 skeleton — wires dual-path routing; no actual LLM calls yet."""

    def __init__(self, api_key: str, base_url: str = "https://openrouter.ai/api/v1"):
        self.base_url = base_url
        self._chat_client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            max_retries=2,
            timeout=60.0,
            default_headers={
                "HTTP-Referer": "MealTracker",
                "X-Title": "MealTracker",
            },
        )
        self._http = httpx.AsyncClient(
            base_url=base_url,
            timeout=60.0,
            headers={
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": "MealTracker",
                "X-Title": "MealTracker",
            },
        )

    # Path 1: Chat completions (OpenAI SDK — handles auth, retries, timeouts)
    async def chat_completion(
        self,
        model: str,
        messages: List[dict],
        response_format: dict | None = None,
        tools: List[dict] | None = None,
    ) -> dict:
        extra: dict = {}
        if response_format:
            extra["response_format"] = response_format
        if tools:
            extra["tools"] = tools
        response = await self._chat_client.chat.completions.create(
            model=model, messages=messages, **extra
        )
        return response.model_dump()

    # Path 2: Multimodal embeddings (raw httpx — SDK does not support multimodal input)
    async def embed_multimodal(
        self,
        model: str,
        content: List[dict],
        output_dimensionality: int = 1536,
        task_type: str = "RETRIEVAL_DOCUMENT",
    ) -> List[float]:
        payload = {
            "model": model,
            "input": [{"content": content}],
            "dimensions": output_dimensionality,
            "task_type": task_type,
        }
        response = await self._http.post("/embeddings", json=payload)
        response.raise_for_status()
        return response.json()["data"][0]["embedding"]

_client: OpenRouterClient | None = None

def get_llm_client() -> OpenRouterClient:
    global _client
    if _client is None:
        settings = get_settings()
        _client = OpenRouterClient(
            api_key=settings.OPENROUTER_API_KEY,
            base_url=settings.OPENROUTER_BASE_URL,
        )
    return _client
```

**Critical constraints:**
- Two paths are mandatory: SDK for chat/tools, httpx for multimodal embeddings.
- `output_dimensionality=1536` matches `Vector(1536)` in schema (MRL truncation point).
- No actual LLM calls made in Phase 1 — this is skeleton only.

---

### `app/schemas/responses.py` (utility)

**Pattern:** Pydantic v2 response models for the ingest endpoint. Separate from DB models.

```python
from pydantic import BaseModel

class IngestResponse(BaseModel):
    meal_log_id: str
    deduplicated: bool = False

class HealthResponse(BaseModel):
    status: str
```

---

### `bot/main.py` (entrypoint, event-driven)

**Source:** RESEARCH.md §4 — Bot Entry Point

**Full pattern:**
```python
import asyncio
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from app.config import get_settings
from bot.polling import poll_and_acknowledge

logger = logging.getLogger(__name__)

async def post_init(application: Application) -> None:
    settings = get_settings()
    application.bot_data["poll_task"] = asyncio.create_task(
        poll_and_acknowledge(application.bot, settings)
    )

async def post_shutdown(application: Application) -> None:
    poll_task = application.bot_data.get("poll_task")
    if poll_task:
        poll_task.cancel()
        try:
            await poll_task
        except asyncio.CancelledError:
            pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("MealTracker bot active.")

async def main() -> None:
    settings = get_settings()
    app = (
        Application.builder()
        .token(settings.TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    await app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
```

**Critical constraints:**
- `run_polling()` (NOT webhook) — Mac mini behind Tailscale; no DDNS/ngrok needed.
- `drop_pending_updates=True` — clears any queued messages from when bot was offline.
- PTB manages its own event loop via `asyncio.run(main())` — do NOT create a loop manually.

---

### `bot/polling.py` (service, CRUD)

**Source:** RESEARCH.md §4 — DB Polling for PENDING Meals

**Full pattern:**
```python
import asyncio
import logging
from sqlalchemy import select
from app.database import get_session_factory
from app.models import MealLog, MealProcessingStatus

logger = logging.getLogger(__name__)

async def poll_and_acknowledge(bot, settings, poll_interval: float | None = None) -> None:
    """Continuously poll for PENDING MealLogs and send Telegram ack."""
    interval = poll_interval or settings.BOT_POLL_INTERVAL
    while True:
        try:
            async with get_session_factory()() as session:
                result = await session.execute(
                    select(MealLog)
                    .where(MealLog.processing_status == MealProcessingStatus.PENDING)
                    .order_by(MealLog.created_at.asc())
                    .limit(1)
                    .with_for_update(skip_locked=True)  # safe if ever multi-instance
                )
                meal = result.scalar_one_or_none()

                if meal:
                    await bot.send_message(
                        chat_id=settings.TELEGRAM_CHAT_ID,
                        text=f"Received photo, processing... (ID: {meal.id[:8]})",
                    )
                    meal.processing_status = MealProcessingStatus.DETECTING
                    await session.commit()

        except asyncio.CancelledError:
            raise  # let cancellation propagate cleanly
        except Exception:
            logger.exception("Error in poll_and_acknowledge")
            # continue polling — a single failure should not crash the bot

        await asyncio.sleep(interval)
```

**Critical constraints:**
- `.with_for_update(skip_locked=True)` — prevents double-processing if the bot ever runs in multiple instances.
- `asyncio.CancelledError` must be re-raised — it is how `post_shutdown` terminates the task.
- Advance status to `DETECTING` immediately after ack so the same meal is not re-acked on next poll.
- `get_session_factory()` is called inside the loop body (not at import time) — engine may not be initialized yet at module import.

---

### `migrations/versions/001_initial.py` (migration)

**Source:** RESEARCH.md §2 — Alembic Migrations

**Full pattern:**
```python
"""Initial schema

Revision ID: 001
Revises:
Create Date: 2026-05-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

def upgrade() -> None:
    # 1. pgvector extension (must come before any vector columns)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 2. Enums (create explicitly so Alembic tracks them)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE meal_processing_status AS ENUM (
                'PENDING','DETECTING','SEGMENTING','EMBEDDING',
                'MATCHING','REASONING','INTERVIEWING','COMPLETED','FAILED'
            );
        EXCEPTION WHEN duplicate_object THEN null; END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE portion_bucket AS ENUM ('SMALL','STANDARD','LARGE');
        EXCEPTION WHEN duplicate_object THEN null; END $$;
    """)

    # 3. Tables (order matters — FK targets first)
    op.create_table("food_items", ...)
    op.create_table("food_visuals", ...)
    op.create_table("meal_logs", ...)
    op.create_table("meal_segments", ...)
    op.create_table("diary_entries", ...)

    # 4. HNSW index — MUST use raw SQL (SQLAlchemy Index DDL doesn't support WITH params)
    op.execute("""
        CREATE INDEX ix_food_visuals_embedding
        ON food_visuals
        USING hnsw (embedding vector_cosine_ops)
        WITH (m=16, ef_construction=64)
    """)

    # 5. Dedup index
    op.create_index("ix_meal_logs_image_hash_created", "meal_logs",
                    ["image_hash", "created_at"])

def downgrade() -> None:
    op.drop_index("ix_food_visuals_embedding", table_name="food_visuals")
    op.drop_table("diary_entries")
    op.drop_table("meal_segments")
    op.drop_table("meal_logs")
    op.drop_table("food_visuals")
    op.drop_table("food_items")
    op.execute("DROP TYPE IF EXISTS meal_processing_status")
    op.execute("DROP TYPE IF EXISTS portion_bucket")
    op.execute("DROP EXTENSION IF EXISTS vector")
```

**Critical constraints:**
- `CREATE EXTENSION IF NOT EXISTS vector` MUST precede all vector column creation.
- HNSW index requires raw `op.execute()` SQL — the `WITH (m=..., ef_construction=...)` clause is not expressible via SQLAlchemy `Index()` DDL API.
- Enum creation uses `DO $$ ... EXCEPTION WHEN duplicate_object` guard for idempotency.

---

## Shared Patterns

### Shared Secret Authentication
**Apply to:** `app/routers/ingest.py` (and all future protected endpoints)
```python
from fastapi import Header, HTTPException
from app.config import get_settings

x_ingest_secret: str = Header(..., alias="X-Ingest-Secret")
if x_ingest_secret != get_settings().INGEST_SECRET:
    raise HTTPException(status_code=401, detail="Unauthorized")
```

### Async Session Dependency
**Apply to:** All router files that need DB access
```python
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_session

async def my_endpoint(session: AsyncSession = Depends(get_session)):
    ...
```

### TIMESTAMPTZ Column Pattern
**Apply to:** ALL model files — every timestamp column uses this, never `DateTime`
```python
from sqlalchemy.dialects.postgresql import TIMESTAMPTZ
from sqlalchemy import func

created_at: Mapped[datetime] = mapped_column(
    TIMESTAMPTZ(timezone=True), nullable=False, server_default=func.now()
)
```

### UUID Primary Key Pattern
**Apply to:** All model files
```python
import uuid
# At insert time:
id = str(uuid.uuid4())
# In model definition:
id: Mapped[str] = mapped_column(String(36), primary_key=True)
```

### Structured Logging
**Apply to:** All service and router files
```python
import structlog
logger = structlog.get_logger(__name__)
# Usage:
logger.info("meal_ingested", meal_id=meal_id, hash=image_hash[:8])
logger.exception("ingest_failed", meal_id=meal_id)
```

### ORJSONResponse
**Apply to:** All router response returns — never use plain `JSONResponse`
```python
from fastapi.responses import ORJSONResponse
return ORJSONResponse(status_code=202, content={"meal_log_id": meal_id})
```

### Settings Access Pattern
**Apply to:** All modules that need config — always call `get_settings()`, never instantiate `Settings()` directly
```python
from app.config import get_settings
settings = get_settings()  # cached by @lru_cache
```

---

## No Analog Found

All Phase 1 files are greenfield — no Python source exists in the repo yet. All patterns sourced from RESEARCH.md.

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| All 18 files | various | various | Blank repo — Phase 1 establishes all foundational patterns |

The TypeScript reference files (`MealTracker_Schema_Types.ts`, `MealTracker_Schema.mermaid`) are read-only references for entity shape only. Do NOT copy vector dimensions (wrong: `vector(1024)`) or index type (wrong: IVFFlat) from them.

---

## Schema Correction Quick Reference

The executor MUST apply these corrections vs. the pre-work TypeScript schema:

| Pre-work TypeScript | Correct Python Implementation |
|---------------------|-------------------------------|
| `vector(1024)` (FoodVisuals) | `Vector(1536)` |
| `vector(1024)` (MealSegments) | `Vector(1536)` |
| IVFFlat index | HNSW `m=16, ef_construction=64` |
| `FAILED` missing from enum | Add `FAILED = "FAILED"` |
| `quantity_multiplier: float` on MealSegments | `portion_bucket` ENUM (`SMALL/STANDARD/LARGE`) |
| No `image_hash` on MealLogs | Add `String(64)` SHA-256 column |
| No `is_invalidated` on FoodVisuals | Add `Boolean` column, default `False` |
| `DateTime` timestamps | `TIMESTAMPTZ(timezone=True)` |

---

## Metadata

**Analog search scope:** Entire project tree outside `.agent/` and `.planning/`
**Files scanned:** 2 source files (`MealTracker_Schema_Types.ts`, `MealTracker_Schema.mermaid`)
**Pattern extraction date:** 2026-05-24
**Pattern source:** RESEARCH.md (authoritative for greenfield Phase 1)
