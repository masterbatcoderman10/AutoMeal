from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock


class MatchingThresholdTests(unittest.IsolatedAsyncioTestCase):
    async def test_cached_match_accepts_similarity_at_threshold(self) -> None:
        from app.services import matching_service

        segment = SimpleNamespace(
            id="segment-1",
            embedding=[0.12] * matching_service.EMBEDDING_DIMENSION,
        )
        food_visual = SimpleNamespace(id="fv-1", food_item_id="item-1")
        session = AsyncMock()
        session.execute.return_value = Mock(first=Mock(return_value=(food_visual, 0.10)))

        result = await matching_service.match_segment_with_cached_embedding(
            segment=segment,
            session=session,
        )

        self.assertTrue(result.is_match)
        self.assertFalse(result.is_below_threshold)
        self.assertTrue(result.resolved)
        self.assertEqual(result.food_visual_id, "fv-1")
        self.assertAlmostEqual(result.similarity or 0.0, matching_service.MATCH_THRESHOLD)

    async def test_cached_match_rejects_similarity_below_threshold(self) -> None:
        from app.services import matching_service

        segment = SimpleNamespace(
            id="segment-1",
            embedding=[0.12] * matching_service.EMBEDDING_DIMENSION,
        )
        food_visual = SimpleNamespace(id="fv-1", food_item_id="item-1")
        session = AsyncMock()
        session.execute.return_value = Mock(first=Mock(return_value=(food_visual, 0.1001)))

        result = await matching_service.match_segment_with_cached_embedding(
            segment=segment,
            session=session,
        )

        self.assertFalse(result.is_match)
        self.assertTrue(result.is_below_threshold)
        self.assertFalse(result.resolved)
        self.assertEqual(result.food_visual_id, "fv-1")
        self.assertLess(result.similarity or 0.0, matching_service.MATCH_THRESHOLD)
