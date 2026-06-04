from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit

import httpx


class GroundingURLNotAllowedError(ValueError):
    pass


@dataclass(frozen=True)
class GroundingLoopBudget:
    max_tool_calls: int
    wall_clock_timeout_s: float
    tool_timeout_s: float


@dataclass
class GroundingLoopState:
    max_tool_calls: int
    wall_clock_timeout_s: float
    started_at: float = field(default_factory=time.monotonic)
    tool_calls_used: int = 0
    duplicate_calls: int = 0
    stop_reason: str | None = None
    _allowed_urls: set[str] = field(default_factory=set)
    _call_signatures: set[str] = field(default_factory=set)

    def allow_search_result_urls(self, urls: list[str]) -> None:
        for url in urls:
            normalized = normalize_allowlisted_url(url)
            if normalized:
                self._allowed_urls.add(normalized)

    def is_url_allowed(self, url: str) -> bool:
        normalized = normalize_allowlisted_url(url)
        return bool(normalized and normalized in self._allowed_urls)

    def record_tool_call(self, tool_name: str, payload: Mapping[str, Any]) -> bool:
        signature = build_tool_call_signature(tool_name, payload)
        if signature in self._call_signatures:
            self.duplicate_calls += 1
            self.stop_reason = self.stop_reason or "DUPLICATE_TOOL_CALL"
            return False
        if self.tool_calls_used >= self.max_tool_calls:
            self.stop_reason = "MAX_TOOL_CALLS"
            return False
        self._call_signatures.add(signature)
        self.tool_calls_used += 1
        return True

    def remaining_time_s(self) -> float:
        elapsed = time.monotonic() - self.started_at
        remaining = self.wall_clock_timeout_s - elapsed
        if remaining <= 0 and self.stop_reason is None:
            self.stop_reason = "WALL_CLOCK_TIMEOUT"
        return max(0.0, remaining)


def normalize_allowlisted_url(url: str | object) -> str:
    if not isinstance(url, str):
        return ""
    stripped = url.strip()
    if not stripped:
        return ""
    parsed = urlsplit(stripped)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    path = parsed.path or "/"
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, parsed.query, ""))


def build_tool_call_signature(tool_name: str, payload: Mapping[str, Any]) -> str:
    canonical_payload = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"))
    return f"{tool_name}:{canonical_payload}"


def build_grounding_loop_budget(settings: object) -> GroundingLoopBudget:
    return GroundingLoopBudget(
        max_tool_calls=int(getattr(settings, "GROUNDING_MAX_TOOL_CALLS", 6)),
        wall_clock_timeout_s=float(getattr(settings, "GROUNDING_WALL_CLOCK_TIMEOUT_S", 90.0)),
        tool_timeout_s=float(getattr(settings, "GROUNDING_TOOL_TIMEOUT_S", 12.5)),
    )


class GroundingService:
    def __init__(
        self,
        *,
        settings: object,
        http_client: httpx.AsyncClient | Any | None = None,
    ) -> None:
        self.settings = settings
        self.base_url = str(getattr(settings, "FIRECRAWL_BASE_URL", "http://firecrawl-api:3002")).rstrip("/")
        self.api_key = str(getattr(settings, "FIRECRAWL_API_KEY", "") or "").strip()
        self.search_limit = int(getattr(settings, "GROUNDING_SEARCH_LIMIT", 5))
        self.tool_timeout_s = float(getattr(settings, "GROUNDING_TOOL_TIMEOUT_S", 12.5))
        self.scrape_format = str(getattr(settings, "GROUNDING_SCRAPE_FORMAT", "markdown") or "markdown")
        self._owns_http_client = http_client is None
        self._http_client = http_client or httpx.AsyncClient(base_url=self.base_url)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def search(self, query: str) -> list[dict[str, Any]]:
        payload = {
            "query": query,
            "limit": self.search_limit,
        }
        response = await self._http_client.post(
            "/v1/search",
            json=payload,
            headers=self._headers(),
            timeout=self.tool_timeout_s,
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict):
            results = data.get("data") or data.get("results") or []
        else:
            results = data
        return [dict(item) for item in results if isinstance(item, Mapping)]

    async def scrape(
        self,
        url: str,
        *,
        loop_state: GroundingLoopState,
    ) -> dict[str, Any]:
        if not loop_state.is_url_allowed(url):
            raise GroundingURLNotAllowedError(f"URL is not allowlisted for this grounding loop: {url}")

        response = await self._http_client.post(
            "/v1/scrape",
            json={
                "url": url,
                "formats": [self.scrape_format],
            },
            headers=self._headers(),
            timeout=self.tool_timeout_s,
        )
        response.raise_for_status()
        data = response.json()
        return dict(data) if isinstance(data, Mapping) else {"data": data}

    async def aclose(self) -> None:
        if self._owns_http_client and hasattr(self._http_client, "aclose"):
            await self._http_client.aclose()


__all__ = [
    "GroundingLoopBudget",
    "GroundingLoopState",
    "GroundingService",
    "GroundingURLNotAllowedError",
    "build_grounding_loop_budget",
    "build_tool_call_signature",
    "normalize_allowlisted_url",
]
