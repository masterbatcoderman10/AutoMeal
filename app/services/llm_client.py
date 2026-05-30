from __future__ import annotations

import os
from typing import Any

from math import isfinite

import httpx
from dotenv import load_dotenv

load_dotenv()
from langfuse.openai import AsyncOpenAI

from app.config import get_settings

OPENAI_CLIENT_WRAPPER = "langfuse.openai.AsyncOpenAI"

OPENROUTER_HEADERS = {
    "HTTP-Referer": "MealTracker",
    "X-Title": "MealTracker",
}

_client: "OpenRouterClient | None" = None


class OpenRouterClient:
    def __init__(self, api_key: str, base_url: str = "https://openrouter.ai/api/v1") -> None:
        settings = get_settings()
        os.environ["LANGFUSE_PUBLIC_KEY"] = settings.LANGFUSE_PUBLIC_KEY
        os.environ["LANGFUSE_SECRET_KEY"] = settings.LANGFUSE_SECRET_KEY
        os.environ["LANGFUSE_BASE_URL"] = settings.LANGFUSE_BASE_URL
        os.environ["LANGFUSE_TRACING_ENVIRONMENT"] = settings.LANGFUSE_TRACING_ENVIRONMENT
        self.base_url = base_url
        self._chat_client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            max_retries=2,
            timeout=60.0,
            default_headers=OPENROUTER_HEADERS,
        )
        self._http = httpx.AsyncClient(
            base_url=base_url,
            timeout=60.0,
            headers={
                "Authorization": f"Bearer {api_key}",
                **OPENROUTER_HEADERS,
            },
        )

    async def chat_completion(
        self,
        model: str,
        messages: list[dict[str, Any]],
        response_format: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        extra_body: dict[str, Any] | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "response_format": response_format,
            "tools": tools,
            "extra_body": extra_body,
        }
        if max_tokens is not None:
            request["max_tokens"] = max_tokens
        response = await self._chat_client.chat.completions.create(**request)
        return response.model_dump()

    async def embed_multimodal(
        self,
        model: str,
        content: list[dict[str, Any]] | dict[str, Any],
        output_dimensionality: int = 1536,
        task_type: str = "RETRIEVAL_DOCUMENT",
    ) -> list[float]:
        input_type = _map_embedding_task_type(task_type)
        payload = {
            "model": model,
            "input": [{"content": content}],
            "dimensions": output_dimensionality,
            "encoding_format": "float",
            "input_type": input_type,
        }
        response = await self._http.post("/embeddings", json=payload)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("embedding response must be a mapping")
        raw_data = data.get("data")
        if not isinstance(raw_data, list) or not raw_data:
            raise ValueError("embedding response missing data list")
        first = raw_data[0]
        if not isinstance(first, dict):
            raise ValueError("embedding response item must be a mapping")
        raw_embedding = first.get("embedding")
        if not isinstance(raw_embedding, list):
            raise ValueError("embedding response item must include embedding vector")
        if len(raw_embedding) != output_dimensionality:
            raise ValueError(
                "embedding length mismatch: expected "
                f"{output_dimensionality}, got {len(raw_embedding)}"
            )

        parsed: list[float] = []
        for value in raw_embedding:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("embedding values must be numeric")
            if not isfinite(float(value)):
                raise ValueError("embedding values must be finite")
            parsed.append(float(value))
        return parsed

    async def close(self) -> None:
        await self._http.aclose()


def get_llm_client() -> OpenRouterClient:
    global _client
    if _client is None:
        settings = get_settings()
        if not settings.OPENROUTER_API_KEY:
            raise RuntimeError("OPENROUTER_API_KEY must be set")
        _client = OpenRouterClient(
            api_key=settings.OPENROUTER_API_KEY,
            base_url=settings.OPENROUTER_BASE_URL,
        )
    return _client


def _map_embedding_task_type(task_type: str) -> str:
    normalized = task_type.strip().upper()
    if normalized == "RETRIEVAL_QUERY":
        return "search_query"
    if normalized == "RETRIEVAL_DOCUMENT":
        return "search_document"
    return normalized.casefold()


__all__ = ["OpenRouterClient", "get_llm_client"]
