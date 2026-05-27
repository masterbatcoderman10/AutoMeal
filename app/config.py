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
    VISION_MAX_SEGMENTS: int = 8
    UPLOADS_DIR: Path = Path("/data/uploads")
    BOT_POLL_INTERVAL: float = 3.0
    DEDUP_WINDOW_SECONDS: int = 60

    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
