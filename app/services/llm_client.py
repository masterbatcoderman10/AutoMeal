from __future__ import annotations

from typing import Any

import httpx
from openai import AsyncOpenAI

from app.config import get_settings


class OpenRouterClient:
    """OpenRouter client with SDK chat/tool path and raw httpx embedding path."""

    def __init__(self, api_key: str, base_url: str = "https://openrouter.ai/api/v1") -> None:
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY is required")

        self.base_url = base_url.rstrip("/")
        headers = {
            "HTTP-Referer": "MealTracker",
            "X-Title": "MealTracker",
        }
        self._chat_client = AsyncOpenAI(
            api_key=api_key,
            base_url=self.base_url,
            max_retries=2,
            timeout=60.0,
            default_headers=headers,
        )
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=60.0,
            headers={
                "Authorization": f"Bearer {api_key}",
                **headers,
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
        content: list[dict[str, Any]],
        output_dimensionality: int = 1536,
        task_type: str = "RETRIEVAL_DOCUMENT",
    ) -> list[float]:
        response = await self._http.post(
            "/embeddings",
            json={
                "model": model,
                "input": [{"content": content}],
                "dimensions": output_dimensionality,
                "task_type": task_type,
            },
        )
        response.raise_for_status()
        payload = response.json()
        return payload["data"][0]["embedding"]

    async def aclose(self) -> None:
        await self._http.aclose()


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
