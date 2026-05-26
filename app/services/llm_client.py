from __future__ import annotations

from typing import Any

import httpx
from openai import AsyncOpenAI

from app.config import get_settings

OPENROUTER_HEADERS = {
    "HTTP-Referer": "MealTracker",
    "X-Title": "MealTracker",
}

_client: "OpenRouterClient | None" = None


class OpenRouterClient:
    def __init__(self, api_key: str, base_url: str = "https://openrouter.ai/api/v1") -> None:
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
    ) -> dict[str, Any]:
        response = await self._chat_client.chat.completions.create(
            model=model,
            messages=messages,
            response_format=response_format,
            tools=tools,
        )
        return response.model_dump()

    async def embed_multimodal(
        self,
        model: str,
        content: dict[str, Any],
        output_dimensionality=1536,
        task_type: str = "RETRIEVE_DOCUMENT",
    ) -> list[float]:
        payload = {
            "model": model,
            "input": [
                {
                    "content": content,
                }
            ],
            "dimensions": output_dimensionality,
            "task_type": task_type,
        }
        response = await self._http.post("/embeddings", json=payload)
        response.raise_for_status()
        data = response.json()
        return data["data"][0]["embedding"]

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


__all__ = ["OpenRouterClient", "get_llm_client"]
