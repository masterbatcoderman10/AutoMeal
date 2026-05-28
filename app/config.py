from functools import lru_cache
from pathlib import Path

from pydantic import ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    INGEST_SECRET: str
    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_CHAT_ID: str
    OPENROUTER_API_KEY: str
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    DETECT_MODEL: str = "google/gemma-4-31b-it"
    SEGMENT_MODEL: str = "google/gemini-3-flash-preview"
    SEGMENT_RETRY_MODEL: str = "google/gemini-3.5-flash"
    LABEL_MODEL: str = "google/gemini-3-flash-preview"
    REASONING_MODEL: str = "google/gemini-3.5-flash"
    REASONING_FALLBACK_MODEL: str = "google/gemini-3-flash-preview"
    REASONING_PARSER_MODEL: str = "google/gemini-3.1-flash-lite"
    REASONING_PARSER_FALLBACK_MODEL: str = "google/gemini-3-flash-preview"
    REASONING_MATCH_THRESHOLD: float = 0.90
    REASONING_TOP_CANDIDATE_FLOOR: float = 0.65
    REASONING_SEGMENT_PARALLELISM: int = 4
    VISION_MAX_SEGMENTS: int = 8
    INTERVIEW_REMINDER_DELAY_SECONDS: int = 600
    JANITOR_INTERVAL_MINUTES: int = 2
    STALE_TIMEOUT_MINUTES: int = 5
    MAX_RECOVERY_ATTEMPTS: int = 3
    LANGFUSE_ENABLED: bool = False
    LANGFUSE_CAPTURE_IMAGES: bool = False
    LANGFUSE_PUBLIC_KEY: str | None = None
    LANGFUSE_SECRET_KEY: str | None = None
    LANGFUSE_HOST: str | None = None
    UPLOADS_DIR: Path = Path("/data/uploads")
    BOT_POLL_INTERVAL: float = 3.0
    DEDUP_WINDOW_SECONDS: int = 60

    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
