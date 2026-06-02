from functools import lru_cache
from pathlib import Path

from pydantic import ConfigDict, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    INGEST_SECRET: str
    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_CHAT_ID: str
    OPENROUTER_API_KEY: str
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    DETECT_MODEL: str = "google/gemini-3.1-flash-lite"
    SEGMENT_MODEL: str = "google/gemini-3-flash-preview"
    SEGMENT_RETRY_MODEL: str = "google/gemini-3.5-flash"
    LABEL_MODEL: str = "google/gemini-3-flash-preview"
    REASONING_MODEL: str = "google/gemini-3.5-flash"
    REASONING_FALLBACK_MODEL: str = "google/gemini-3-flash-preview"
    INTERVIEW_MODEL: str = "google/gemini-3.1-flash-lite"
    INTERVIEW_FALLBACK_MODEL: str = "google/gemini-3-flash-preview"
    FINALIZER_MODEL: str = "google/gemini-3.1-flash-lite"
    FINALIZER_GROUP_PARALLELISM: int = 4
    REASONING_MATCH_THRESHOLD: float = 0.90
    REASONING_TOP_CANDIDATE_FLOOR: float = 0.65
    REASONING_SEGMENT_PARALLELISM: int = 4
    VISION_MAX_SEGMENTS: int = 8
    INTERVIEW_REMINDER_DELAY_SECONDS: int = 600
    JANITOR_INTERVAL_MINUTES: int = 2
    STALE_TIMEOUT_MINUTES: int = 10
    MAX_RECOVERY_ATTEMPTS: int = 3
    LANGFUSE_CAPTURE_IMAGES: bool = False
    LANGFUSE_PUBLIC_KEY: str
    LANGFUSE_SECRET_KEY: str
    LANGFUSE_BASE_URL: str
    LANGFUSE_TRACING_ENVIRONMENT: str = "local"
    UPLOADS_DIR: Path = Path("/data/uploads")
    BOT_POLL_INTERVAL: float = 3.0
    DEDUP_WINDOW_SECONDS: int = 60

    @field_validator("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL")
    @classmethod
    def _required_langfuse_value(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Langfuse configuration is mandatory")
        return stripped

    @field_validator("FINALIZER_GROUP_PARALLELISM")
    @classmethod
    def _validate_finalizer_group_parallelism(cls, value: int) -> int:
        if value < 1:
            raise ValueError("FINALIZER_GROUP_PARALLELISM must be at least 1")
        return value

    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
