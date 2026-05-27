# Phase 1: Foundation & Ingest — Technical Research

**Researched:** 2026-05-24
**Status:** Complete

This document answers the technical questions needed to plan Phase 1 implementation. It covers patterns for FastAPI + SQLAlchemy 2 async, Postgres + pgvector schema, image ingestion, Telegram bot integration, project layout, OpenRouter client skeleton, docker-compose, and validation architecture.

---

## 1. FastAPI + SQLAlchemy 2 Async

### App Structure & Engine Setup

The FastAPI app uses SQLAlchemy 2's async engine with `asyncpg` as the driver. The engine is created once at module level and torn down on app shutdown via the lifespan context manager.

```python
# app/database.py
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine, async_sessionmaker
from contextlib import asynccontextmanager

_engine: AsyncEngine | None = None

def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        raise RuntimeError("Engine not initialized")
    return _engine

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

async_session_factory = async_sessionmaker(
    bind=get_engine(),
    expire_on_commit=False,
    autoflush=False,
    class_=AsyncSession,
)
```

Connection URL format: `postgresql+asyncpg://user:pass@host:5432/dbname`

### Lifespan Context Manager

Use `contextlib.asynccontextmanager` — NOT `@app.on_event`. APScheduler's `AsyncIOScheduler` is started here too, sharing the same event loop.

```python
# app/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.config import get_settings

scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    
    # 1. Initialize DB engine
    from app.database import create_engine
    create_engine(settings.database_url)
    
    # 2. Run any startup migrations (optional — see section 2)
    # await run_migrations()
    
    # 3. Start APScheduler (shares event loop automatically)
    scheduler.start()
    
    yield  # app runs here
    
    # Shutdown
    scheduler.shutdown(wait=False)
    from app.database import engine
    await engine.dispose()

app = FastAPI(lifespan=lifespan)
```

**Critical:** Run Uvicorn with exactly 1 worker (`uvicorn app.main:app --workers 1`). Multiple workers would start multiple schedulers.

### Async Session Dependency

Endpoints get a session via FastAPI's dependency injection. Use a generator pattern so the session is always properly closed.

```python
# app/database.py
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session

# app/dependencies.py
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

async def session() -> AsyncSession:
    async with async_session_factory() as s:
        yield s

# Usage in endpoints:
@router.post("/ingest")
async def ingest_photo(session: AsyncSession = Depends(get_session)):
    ...
```

The key is `expire_on_commit=False` on the session maker — it prevents detached instance errors when accessing relationships after commit in async contexts.

---

## 2. Postgres + pgvector Schema

### SQLAlchemy 2 Declarative Models with Vector Columns

The `pgvector` Python package provides `pgvector.sqlalchemy.Vector` which maps to Postgres `vector` type. For `vector(1536)`:

```python
# app/models/meal_log.py
from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import (
    Column, String, DateTime, Enum, Text, Boolean,
    ForeignKey, UniqueConstraint, Index
)
from sqlalchemy.orm import DeclarativeBase, relationship, Mapped, mapped_column
from sqlalchemy.dialects.postgresql import TIMESTAMPTZ
from pgvector.sqlalchemy import Vector

class MealProcessingStatus(PyEnum):
    PENDING = "PENDING"
    DETECTING = "DETECTING"
    SEGMENTING = "SEGMENTING"
    EMBEDDING = "EMBEDDING"
    MATCHING = "MATCHING"
    REASONING = "REASONING"
    INTERVIEWING = "INTERVIEWING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class Base(DeclarativeBase):
    pass

class MealLog(Base):
    __tablename__ = "meal_logs"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    image_url: Mapped[str] = mapped_column(String(512), nullable=False)
    image_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # SHA-256 hex
    processing_status: Mapped[MealProcessingStatus] = mapped_column(
        Enum(MealProcessingStatus, name="meal_processing_status", create_type=True),
        nullable=False,
        default=MealProcessingStatus.PENDING,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    
    segments: Mapped[List["MealSegment"]] = relationship(back_populates="meal_log")

class MealSegment(Base):
    __tablename__ = "meal_segments"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    meal_log_id: Mapped[str] = mapped_column(ForeignKey("meal_logs.id"), nullable=False)
    label: Mapped[str | None] = mapped_column(String(256), nullable=True)
    bounding_box: Mapped[List[float] | None] = mapped_column(JSON, nullable=True)
    embedding: Mapped[List[float] | None] = mapped_column(Vector(1536), nullable=True)
    ai_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    portion_bucket: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ(timezone=True), nullable=False)
    
    meal_log: Mapped["MealLog"] = relationship(back_populates="segments")
    diary_entry: Mapped["DiaryEntry | None"] = relationship(back_populates="segment")

class FoodItem(Base):
    __tablename__ = "food_items"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    source_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    brand_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    restaurant_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    serving_size_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    calories: Mapped[float | None] = mapped_column(Float, nullable=True)
    protein_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    carbs_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    fat_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ(timezone=True), nullable=False)
    
    visuals: Mapped[List["FoodVisual"]] = relationship(back_populates="food_item")
    diary_entries: Mapped[List["DiaryEntry"]] = relationship(back_populates="food_item")

class FoodVisual(Base):
    __tablename__ = "food_visuals"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    food_item_id: Mapped[str] = mapped_column(ForeignKey("food_items.id"), nullable=False)
    cropped_image_url: Mapped[str] = mapped_column(String(512), nullable=False)
    embedding: Mapped[List[float]] = mapped_column(Vector(1536), nullable=False)
    is_invalidated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ(timezone=True), nullable=False)
    
    food_item: Mapped["FoodItem"] = relationship(back_populates="visuals")
    
    __table_args__ = (
        Index(
            "ix_food_visuals_embedding",
            embedding,
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"}
        ),
    )

class DiaryEntry(Base):
    __tablename__ = "diary_entries"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    meal_log_id: Mapped[str] = mapped_column(ForeignKey("meal_logs.id"), nullable=False)
    food_item_id: Mapped[str] = mapped_column(ForeignKey("food_items.id"), nullable=False)
    segment_id: Mapped[str | None] = mapped_column(ForeignKey("meal_segments.id"), nullable=True)
    portion_bucket: Mapped[str] = mapped_column(String(32), nullable=False)
    identification_method: Mapped[str] = mapped_column(String(32), nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ(timezone=True), nullable=False)
    
    meal_log: Mapped["MealLog"] = relationship(back_populates="diary_entry")
    food_item: Mapped["FoodItem"] = relationship(back_populates="diary_entries")
    segment: Mapped["MealSegment"] = relationship(back_populates="diary_entry")

# Index for dedup lookups (INGEST-05)
Index("ix_meal_logs_image_hash_created", "image_hash", "created_at")
```

### Alembic Migrations

Alembic handles pgvector extension + vector columns correctly. First migration creates the extension:

```python
# migrations/versions/001_initial.py
def upgrade() -> None:
    # Create pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    
    # The enum is created by SQLAlchemy when create_type=True on the column
    # Alternatively, create it explicitly:
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE meal_processing_status AS ENUM (
                'PENDING', 'DETECTING', 'SEGMENTING', 'EMBEDDING',
                'MATCHING', 'REASONING', 'INTERVIEWING', 'COMPLETED', 'FAILED'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    # Create vector columns
    op.add_column("food_visuals", 
        sa.Column("embedding", Vector(1536), nullable=False, default=[])
    )
    
    # HNSW index on food_visuals.embedding
    op.execute("""
        CREATE INDEX ix_food_visuals_embedding 
        ON food_visuals 
        USING hnsw (embedding vector_cosine_ops) 
        WITH (m=16, ef_construction=64)
    """)
```

### TIMESTAMPTZ in SQLAlchemy 2

Use `sqlalchemy.dialects.postgresql.TIMESTAMPTZ`. In models, prefer:
```python
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import TIMESTAMPTZ

created_at: Mapped[datetime] = mapped_column(
    TIMESTAMPTZ(timezone=True), 
    nullable=False, 
    server_default=func.now()
)
```

`server_default=func.now()` sets the default at the Postgres side — important for `created_at`. `onupdate=func.now()` on `updated_at` handles auto-update.

### Adding FAILED to ENUM in a Migration

```python
def upgrade() -> None:
    op.execute("ALTER TYPE meal_processing_status ADD VALUE IF NOT EXISTS 'FAILED'")
```

Postgres 14+ supports `ADD VALUE IF NOT EXISTS`. For older versions, use a `DO` block to handle the exception.

---

## 3. Image Ingestion Endpoint

### Endpoint Signature

```python
# app/routers/ingest.py
from fastapi import APIRouter, UploadFile, HTTPException, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/ingest", tags=["ingest"])

@router.post("/photo")
async def ingest_photo(
    photo: UploadFile,
    x_ingest_secret: str = Header(..., alias="X-Ingest-Secret"),
    session: AsyncSession = Depends(get_session),
):
    settings = get_settings()
    
    # INGEST-02: Auth check
    if x_ingest_secret != settings.INGEST_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    # INGEST-01: Accept multipart/form-data with field name "picture"
    # (iOS Shortcut sends "picture" field)
    ...
```

### HEIC → JPEG Transcoding

Uses `pillow-heif` (or `heif` Python binding) + Pillow. Process in memory to avoid temp files:

```python
import hashlib
import uuid
from io import BytesIO
from pathlib import Path

# pip install pillow-heif pillow

async def transcode_heic_to_jpeg(raw_bytes: bytes) -> bytes:
    from pillow_heif import open_heif_to_bytes
    # open_heif_to_bytes returns a Pillow Image in JPEG format
    image_bytes = open_heif_to_bytes(raw_bytes, format="JPEG", quality=85)
    return image_bytes

async def save_upload(photo: UploadFile, dest_path: Path) -> bytes:
    raw_bytes = await photo.read()
    content_type = photo.content_type or ""
    
    if content_type in ("image/heic", "image/heif", "image/heic+heif"):
        # Transcode
        jpeg_bytes = await transcode_heic_to_jpeg(raw_bytes)
    elif content_type.startswith("image/"):
        # Already JPEG — just use as-is
        jpeg_bytes = raw_bytes
    else:
        raise HTTPException(400, f"Unsupported content type: {content_type}")
    
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(jpeg_bytes)
    return jpeg_bytes
```

Note: `pillow-heif`'s `open_heif_to_bytes` accepts raw bytes and outputs JPEG bytes directly — no need to open as Image, convert, then get bytes.

### File Storage & Dedup

Path convention from D-06: `/data/uploads/meals/{meal_id}.jpg`

```python
# Deduplication logic (INGEST-05)
import hashlib

async def ingest_photo(...) 
    raw_bytes = await photo.read()
    image_hash = hashlib.sha256(raw_bytes).hexdigest()  # SHA-256 of raw bytes
    
    # Check for existing meal within 60s window
    from datetime import datetime, timedelta, timezone
    window_start = datetime.now(timezone.utc) - timedelta(seconds=60)
    
    existing = await session.execute(
        select(MealLog).where(
            MealLog.image_hash == image_hash,
            MealLog.created_at >= window_start,
        ).order_by(MealLog.created_at.desc()).limit(1)
    )
    existing = existing.scalar_one_or_none()
    
    if existing:
        return JSONResponse(
            status_code=200,
            content={"meal_log_id": existing.id, "deduplicated": True}
        )
    
    # Create new meal
    meal_id = str(uuid.uuid4())
    dest_path = Path(f"/data/uploads/meals/{meal_id}.jpg")
    await save_upload(photo, dest_path, raw_bytes)
    
    meal = MealLog(
        id=meal_id,
        image_url=str(dest_path),  # absolute path inside container
        image_hash=image_hash,
        processing_status=MealProcessingStatus.PENDING,
    )
    session.add(meal)
    await session.commit()
    
    return JSONResponse(status_code=202, content={"meal_log_id": meal_id})
```

### 202 Acknowledgement Timing

The endpoint should return within 5 seconds (INGEST-03). Best practices:
- Do SHA-256 hash on raw bytes (fast — streaming not needed for typical HEIC size)
- Transcode inline — for small images (< 10MB) this is fast enough
- If you need to be extra safe, use aiofiles for non-blocking disk writes, but for Phase 1 synchronous writes are fine
- Never do async pipeline work in the request path — just enqueue and return 202

---

## 4. Telegram Bot Integration

### Bot Entry Point

The bot runs as a separate service with its own `Application.run_polling()` (D-03). It is NOT part of the FastAPI app — fault isolation.

```python
# bot/main.py
import asyncio
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, ContextTypes,
)
from app.config import get_settings

async def post_init(application: Application):
    """Called after bot starts — initialize chat ID, etc."""
    settings = get_settings()
    try:
        bot = await application.bot.get_me()
        # Store bot info for logging
        application.bot_data["username"] = bot.username
    except Exception:
        pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("MealTracker bot active.")

async def main():
    settings = get_settings()
    
    app = (
        Application.builder()
        .token(settings.TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )
    
    app.add_handler(CommandHandler("start", start))
    
    await app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
```

### DB Polling for PENDING Meals

The bot polls `meal_logs` every N seconds for new `PENDING` rows and sends an acknowledgement message (D-02).

```python
# bot/polling.py
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import async_session_factory
from app.models import MealLog, MealProcessingStatus
from datetime import datetime, timedelta, timezone

async def poll_and_acknowledge(bot, settings, poll_interval: float = 3.0):
    """Poll for PENDING meals and send Telegram acknowledgement."""
    while True:
        try:
            async with async_session_factory() as session:
                # Claim a PENDING meal (SELECT FOR UPDATE SKIP LOCKED pattern)
                result = await session.execute(
                    select(MealLog)
                    .where(MealLog.processing_status == MealProcessingStatus.PENDING)
                    .order_by(MealLog.created_at.asc())
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
                meal = result.scalar_one_or_none()
                
                if meal:
                    # Send acknowledgement
                    await bot.send_message(
                        chat_id=settings.TELEGRAM_CHAT_ID,
                        text=f"📸 Received, processing... (meal_id: {meal.id[:8]})",
                    )
                    # Optionally advance to next status
                    meal.processing_status = MealProcessingStatus.DETECTING
                    await session.commit()
                    
        except Exception as e:
            # Log and continue polling — don't crash the bot
            logger.exception(f"Polling error: {e}")
        
        await asyncio.sleep(poll_interval)
```

`skip_locked` prevents two bot instances from processing the same meal if the Docker setup ever scales.

### Integrating Polling into Bot Lifecycle

```python
# bot/main.py — integrate polling task
async def post_init(application: Application):
    settings = get_settings()
    application.bot_data["poll_task"] = asyncio.create_task(
        poll_and_acknowledge(application.bot, settings)
    )

async def post_shutdown(application: Application):
    poll_task = application.bot_data.get("poll_task")
    if poll_task:
        poll_task.cancel()
        try:
            await poll_task
        except asyncio.CancelledError:
            pass

app = Application.builder()...
app.post_init(post_init)
app.post_shutdown(post_shutdown)
```

---

## 5. Project Layout

```
mealttracker/
├── docker-compose.yml          # All services (api, bot, postgres, searxng, firecrawl)
├── Dockerfile.api              # FastAPI app container
├── Dockerfile.bot             # Telegram bot container
├── requirements.txt            # All Python deps (single file; uv compiles from it)
├── .env.example                # Template with all required env vars (no real secrets)
│
├── app/                        # FastAPI application (shared with bot via volume/mount)
│   ├── __init__.py
│   ├── main.py                 # FastAPI app, lifespan, router registration
│   ├── config.py               # pydantic-settings Settings class
│   ├── database.py             # SQLAlchemy engine, session factory, session dependency
│   ├── dependencies.py          # FastAPI dependency injectors (get_session, etc.)
│   │
│   ├── models/                 # SQLAlchemy declarative models (source of truth per D-12)
│   │   ├── __init__.py         # Re-exports all models
│   │   ├── base.py             # DeclarativeBase
│   │   ├── meal_log.py         # MealLog, MealProcessingStatus enum
│   │   ├── meal_segment.py      # MealSegment, portion_bucket enum
│   │   ├── food_item.py         # FoodItem
│   │   ├── food_visual.py       # FoodVisual (vector column, HNSW index)
│   │   └── diary_entry.py        # DiaryEntry
│   │
│   ├── routers/                # FastAPI route modules
│   │   ├── __init__.py
│   │   ├── ingest.py            # POST /ingest/photo (Phase 1)
│   │   └── health.py            # GET /health (Phase 1)
│   │
│   ├── services/               # Business logic
│   │   ├── image_service.py     # HEIC transcode, file save, hash
│   │   └── llm_client.py        # OpenRouter client skeleton (Phase 1 only)
│   │
│   └── schemas/                # Pydantic request/response models (not DB models)
│       └── responses.py
│
├── bot/                        # Telegram bot service
│   ├── __init__.py
│   ├── main.py                 # PTB Application, polling setup, command handlers
│   ├── polling.py              # DB polling task for PENDING meals
│   ├── handlers.py              # Command handlers (start, /today, /week, etc.)
│   └── messages.py             # Message template functions
│
├── shared/                     # Code shared between app and bot (also in app/ for now)
│   ├── __init__.py
│   └── config.py               # Same Settings class imported by both
│
├── migrations/                 # Alembic migrations
│   ├── alembic.ini
│   ├── env.py                  # Async migration environment
│   └── versions/
│       └── 001_initial.py
│
├── tests/                      # Phase 2+ test structure
│   ├── conftest.py             # Pytest fixtures (ephemeral DB, test client)
│   └── ...
│
└── .env                        # Actual env file (gitignored; user fills from .env.example)
```

**Key decision:** `app/` models are shared by both services. In Docker, mount `app/` as a volume into both `api` and `bot` containers, OR package `app/` as a pip-installable package (`app/` with `pyproject.toml`). The volume mount is simpler for Phase 1.

### Config Pattern (pydantic-settings)

```python
# app/config.py
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
```

---

## 6. OpenRouter Client Skeleton

### Two Paths: OpenAI SDK vs. httpx Wrapper

As documented in STACK.md, the OpenAI SDK's `client.embeddings.create()` only accepts string/list-of-strings input — not multimodal content. Multimodal embeddings require a thin `httpx` wrapper.

```python
# app/services/llm_client.py
from openai import AsyncOpenAI
import httpx
from typing import List, Literal

class OpenRouterClient:
    """Skeleton client for Phase 1 — routes to SDK or httpx based on call type."""
    
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
            }
        )
        self._http = httpx.AsyncClient(
            base_url=base_url,
            timeout=60.0,
            headers={
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": "MealTracker",
                "X-Title": "MealTracker",
            }
        )
    
    # --- Path 1: Chat completions (OpenAI SDK handles auth, retries, timeouts)
    async def chat_completion(
        self,
        model: str,
        messages: List[dict],
        response_format: dict | None = None,
        tools: List[dict] | None = None,
        thinking: str | None = None,  # Gemini 3 Flash thinking budget
    ) -> dict:
        """Chat completion via OpenAI SDK. For vision + structured outputs + tool calling."""
        extra_kwargs = {}
        if response_format:
            extra_kwargs["response_format"] = response_format
        if tools:
            extra_kwargs["tools"] = tools
        if thinking:
            extra_kwargs["thinking"] = {"type": "enabled", "budget_tokens": 1024} if thinking else None
        
        response = await self._chat_client.chat.completions.create(
            model=model,
            messages=messages,
            **extra_kwargs
        )
        return response.model_dump()
    
    # --- Path 2: Multimodal embeddings (httpx wrapper, raw POST)
    async def embed_multimodal(
        self,
        model: str,
        content: List[dict],  # OpenRouter multimodal embedding content array
        output_dimensionality: int = 1536,
        task_type: str = "RETRIEVAL_DOCUMENT",
    ) -> List[float]:
        """
        Multimodal embedding via raw httpx POST.
        content = [{"type": "text", "text": "..."}] or [{"type": "image_url", "image_url": {"url": "data:..."}}]
        output_dimensionality: 1536 (MRL truncation point for this project)
        task_type: RETRIEVAL_DOCUMENT (writes) | RETRIEVAL_QUERY (searches)
        """
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

No actual LLM calls in Phase 1 — this is just the wiring. The skeleton will be exercised in Phase 2.

---

## 7. docker-compose Structure

```yaml
# docker-compose.yml
version: "3.9"

services:
  postgres:
    image: pgvector/pgvector:pg17
    container_name: mealttracker-postgres
    environment:
      POSTGRES_DB: mealttracker
      POSTGRES_USER: mealttracker
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U mealttracker -d mealttracker"]
      interval: 10s
      timeout: 5s
      retries: 5

  api:
    build:
      context: .
      dockerfile: Dockerfile.api
    container_name: mealttracker-api
    environment:
      DATABASE_URL: postgresql+asyncpg://mealttracker:${POSTGRES_PASSWORD}@postgres:5432/mealttracker
      INGEST_SECRET: ${INGEST_SECRET}
      TELEGRAM_BOT_TOKEN: ${TELEGRAM_BOT_TOKEN}
      TELEGRAM_CHAT_ID: ${TELEGRAM_CHAT_ID}
      OPENROUTER_API_KEY: ${OPENROUTER_API_KEY}
    volumes:
      - uploads:/data/uploads
    depends_on:
      postgres:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  bot:
    build:
      context: .
      dockerfile: Dockerfile.bot
    container_name: mealttracker-bot
    environment:
      DATABASE_URL: postgresql+asyncpg://mealttracker:${POSTGRES_PASSWORD}@postgres:5432/mealttracker
      TELEGRAM_BOT_TOKEN: ${TELEGRAM_BOT_TOKEN}
      TELEGRAM_CHAT_ID: ${TELEGRAM_CHAT_ID}
    volumes:
      - uploads:/data/uploads
    depends_on:
      postgres:
        condition: service_healthy

  searxng:
    image: searxng/searxng:latest
    container_name: mealttracker-searxng
    environment:
      SEARXNG_BASE_URL: http://searxng:8080/
    volumes:
      - ./searxng/settings.yml:/etc/searxng/settings.yml:ro

  firecrawl:
    image: devflowinc/firecrawl-simple:latest  # Lean alternative for Phase 1
    container_name: mealttracker-firecrawl
    environment:
      DATABASE_URL: postgresql://firecrawl:${FIRECRAWL_PASSWORD}@firecrawl-db:5432/firecrawl
    depends_on:
      - firecrawl-db
    profiles:
      - grounding  # Start with: docker compose --profile grounding up

  firecrawl-db:
    image: postgres:17
    profiles:
      - grounding
    environment:
      POSTGRES_DB: firecrawl
      POSTGRES_USER: firecrawl
      POSTGRES_PASSWORD: ${FIRECRAWL_PASSWORD}

volumes:
  postgres_data:
  uploads:
```

### Dockerfiles

```dockerfile
# Dockerfile.api
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY migrations/ ./migrations/

# Run migrations on startup
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"]
```

```dockerfile
# Dockerfile.bot
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY bot/ ./bot/

CMD ["python", "-m", "bot.main"]
```

### .env.example

```
# Database
POSTGRES_PASSWORD=change-me-in-prod

# Auth
INGEST_SECRET=your-ios-shortcut-shared-secret

# Telegram
TELEGRAM_BOT_TOKEN=your-telegram-bot-token
TELEGRAM_CHAT_ID=your-chat-id

# OpenRouter
OPENROUTER_API_KEY=your-openrouter-key

# Firecrawl (for grounding profile)
FIRECRAWL_PASSWORD=change-me-if-using-grounding
```

### Multi-arch Support

All key images (`pgvector/pgvector:pg17`, `searxng/searxng`, `python:3.12-slim`) are multi-arch. The `docker buildx` setup is handled by Docker Desktop on Mac mini — no extra configuration needed. The compose file doesn't need explicit platform flags.

---

## 8. Validation Architecture

Phase 1 validation focuses on the infrastructure working correctly. No test files are written in Phase 1, but the structure for Phase 2 testing is established.

### Success Criteria Validation Plan

| SC | What to verify | How to verify |
|----|---------------|---------------|
| 1 | Full stack starts on arm64 | `docker compose up -d && docker compose ps` → all containers running |
| 2 | Photo submission → 202 + Telegram ack | `curl -X POST -F picture=@test.jpg -H "X-Ingest-Secret:..." http://api:8000/ingest/photo` → 202; Telegram message appears |
| 3 | Dedup within 60s | Submit same photo twice → second returns 200 with existing meal_log_id |
| 4 | 401 on missing/wrong secret | `curl` without header → 401; with wrong value → 401 |
| 5 | Schema correctness | `psql` into postgres → `\d meal_logs`, `\d food_visuals` → `vector(1536)`, `TIMESTAMPTZ`, `FAILED` in enum; `\d ix_food_visuals_embedding` → HNSW |

### Testing Structure for Phase 2+

```python
# tests/conftest.py — Pytest fixtures
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

@pytest_asyncio.fixture
async def db_engine():
    """Ephemeral postgres via pytest-postgresql or testcontainers."""
    ...

@pytest_asyncio.fixture
async def session(db_engine):
    async with async_session_factory(bind=db_engine) as session:
        yield session

@pytest_asyncio.fixture
async def client():
    """Async test client for FastAPI endpoints."""
    from httpx import AsyncClient, ASGITransport
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as ac:
        yield ac

# Test files to create in Phase 2:
# tests/test_ingest.py       — INGEST-01..05
# tests/test_schema.py        — MATCH-01, enum, TIMESTAMPTZ
# tests/test_bot_polling.py   — Bot DB polling
# tests/test_llm_client.py    — Client routing skeleton
```

### Smoke Testing Phase 1 Without Full Docker

For rapid iteration during Phase 1 development:
```bash
# Run FastAPI locally against Docker postgres
uvicorn app.main:app --reload --app-dir .

# Run migrations
alembic upgrade head

# Test endpoint
curl -v -X POST http://localhost:8000/ingest/photo \
  -F "picture=@/path/to/test.jpg" \
  -H "X-Ingest-Secret: test-secret"
```

---

## RESEARCH COMPLETE

Phase 1 technical research is complete. All eight sections cover the patterns needed to implement the phase: FastAPI + SQLAlchemy 2 async with proper lifespan, Postgres + pgvector schema with `vector(1536)`, HNSW index, and TIMESTAMPTZ, image ingestion with HEIC transcoding and 60-second dedup, Telegram bot as a separate polling service, project layout with shared models, OpenRouter client skeleton with dual-path routing (SDK for chat, httpx for multimodal embeddings), docker-compose covering all services, and validation architecture for Phase 2+ testing.

Next step: proceed to 02-PLAN.md to synthesize these patterns into an implementation plan with a task list.