from __future__ import annotations

import unittest


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


class _FakeHttpClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.response_payload = {"success": True, "data": []}

    async def post(self, url: str, json=None, headers=None, timeout=None):
        self.calls.append(
            {
                "url": url,
                "json": json,
                "headers": headers,
                "timeout": timeout,
            }
        )
        return _FakeResponse(self.response_payload)


class GroundingServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_firecrawl_search_uses_configured_limit_and_timeout(self) -> None:
        from app.services.grounding_service import GroundingService

        settings = type(
            "Settings",
            (),
            {
                "FIRECRAWL_BASE_URL": "http://firecrawl:3002",
                "FIRECRAWL_API_KEY": "fc-secret",
                "GROUNDING_SEARCH_LIMIT": 5,
                "GROUNDING_TOOL_TIMEOUT_S": 12.5,
                "GROUNDING_SCRAPE_FORMAT": "markdown",
            },
        )()
        http_client = _FakeHttpClient()
        service = GroundingService(settings=settings, http_client=http_client)

        await service.search("kfc chicken calories")

        self.assertEqual(len(http_client.calls), 1)
        self.assertEqual(http_client.calls[0]["url"], "/v1/search")
        self.assertEqual(
            http_client.calls[0]["json"],
            {"query": "kfc chicken calories", "limit": 5},
        )
        self.assertEqual(http_client.calls[0]["timeout"], 12.5)
        self.assertEqual(
            http_client.calls[0]["headers"]["Authorization"],
            "Bearer fc-secret",
        )

    async def test_firecrawl_scrape_rejects_urls_outside_group_allowlist(self) -> None:
        from app.services.grounding_service import (
            GroundingService,
            GroundingURLNotAllowedError,
            GroundingLoopState,
        )

        settings = type(
            "Settings",
            (),
            {
                "FIRECRAWL_BASE_URL": "http://firecrawl:3002",
                "FIRECRAWL_API_KEY": "fc-secret",
                "GROUNDING_SEARCH_LIMIT": 5,
                "GROUNDING_TOOL_TIMEOUT_S": 12.5,
                "GROUNDING_SCRAPE_FORMAT": "markdown",
            },
        )()
        http_client = _FakeHttpClient()
        service = GroundingService(settings=settings, http_client=http_client)
        loop_state = GroundingLoopState(max_tool_calls=6, wall_clock_timeout_s=90.0)
        loop_state.allow_search_result_urls(
            [
                "https://example.com/menu/chicken-curry",
                "https://example.com/nutrition/chicken-curry",
            ]
        )

        with self.assertRaises(GroundingURLNotAllowedError):
            await service.scrape(
                "https://attacker.example.com/not-allowed",
                loop_state=loop_state,
            )

        self.assertEqual(http_client.calls, [])

    def test_duplicate_tool_call_policy_suppresses_repeated_calls(self) -> None:
        from app.services.grounding_service import GroundingLoopState

        loop_state = GroundingLoopState(max_tool_calls=6, wall_clock_timeout_s=90.0)

        first = loop_state.record_tool_call(
            "firecrawl_search",
            {"query": "chicken shawarma nutrition"},
        )
        second = loop_state.record_tool_call(
            "firecrawl_search",
            {"query": "chicken shawarma nutrition"},
        )

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(loop_state.tool_calls_used, 1)
        self.assertEqual(loop_state.duplicate_calls, 1)

    def test_grounding_budget_comes_from_explicit_settings(self) -> None:
        from app.services.grounding_service import build_grounding_loop_budget

        settings = type(
            "Settings",
            (),
            {
                "GROUNDING_MAX_TOOL_CALLS": 6,
                "GROUNDING_WALL_CLOCK_TIMEOUT_S": 90.0,
                "GROUNDING_TOOL_TIMEOUT_S": 12.5,
            },
        )()

        budget = build_grounding_loop_budget(settings)

        self.assertEqual(budget.max_tool_calls, 6)
        self.assertEqual(budget.wall_clock_timeout_s, 90.0)
        self.assertEqual(budget.tool_timeout_s, 12.5)

