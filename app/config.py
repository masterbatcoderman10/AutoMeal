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
    REASONING_MODEL: str = "google/gemini-3-flash-preview"
    REASONING_FALLBACK_MODEL: str = "google/gemini-3-flash-preview"
    INTERVIEW_MODEL: str = "google/gemini-3.1-flash-lite"
    INTERVIEW_FALLBACK_MODEL: str = "google/gemini-3-flash-preview"
    FINALIZER_MODEL: str = "google/gemini-3-flash-preview"
    GROUNDING_MODEL: str = "google/gemini-3.1-flash-lite"
    GROUNDING_FALLBACK_MODEL: str = "google/gemini-3-flash-preview"
    FINALIZER_GROUP_PARALLELISM: int = 4
    FIRECRAWL_BASE_URL: str = "http://firecrawl-api:3002"
    FIRECRAWL_API_KEY: str = ""
    SEARXNG_BASE_URL: str = "http://searxng:8080"
    FIRECRAWL_SEARCH_ENGINES: str = "google,duckduckgo,bing,brave"
    FIRECRAWL_SEARCH_CATEGORIES: str = "general"
    FIRECRAWL_MAX_RAM: float = 0.8
    FIRECRAWL_MAX_CPU: float = 0.8
    GROUNDING_SEARCH_LIMIT: int = 5
    GROUNDING_MAX_TOOL_CALLS: int = 6
    GROUNDING_TOOL_TIMEOUT_S: float = 12.5
    GROUNDING_WALL_CLOCK_TIMEOUT_S: float = 90.0
    GROUNDING_SCRAPE_FORMAT: str = "markdown"
    GROUNDING_RUNTIME_FALLBACK: str = "direct_searxng_search_then_firecrawl_scrape"
    GROUNDING_SEQUENTIAL_SCRAPE_PROBE_COUNT: int = 5
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

    @field_validator("GROUNDING_SEARCH_LIMIT", "GROUNDING_MAX_TOOL_CALLS")
    @classmethod
    def _validate_grounding_positive_ints(cls, value: int, info) -> int:
        if value < 1:
            raise ValueError(f"{info.field_name} must be at least 1")
        return value

    @field_validator("GROUNDING_TOOL_TIMEOUT_S", "GROUNDING_WALL_CLOCK_TIMEOUT_S")
    @classmethod
    def _validate_grounding_positive_floats(cls, value: float, info) -> float:
        if value <= 0:
            raise ValueError(f"{info.field_name} must be greater than 0")
        return value

    @field_validator("FIRECRAWL_MAX_RAM", "FIRECRAWL_MAX_CPU")
    @classmethod
    def _validate_firecrawl_resource_caps(cls, value: float, info) -> float:
        if value <= 0 or value > 1:
            raise ValueError(f"{info.field_name} must be between 0 and 1")
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
