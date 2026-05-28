from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.models import MealProcessingStatus


async def _noop_sleep(*_args, **_kwargs) -> None:
    return None


class EmbedWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_poll_and_embed_moves_meal_to_matching_and_persists_segment_vector(self) -> None:
        from bot import polling
        from app.services import matching_service

        meal = SimpleNamespace(
            id="12345678-abcd-efgh",
            processing_status=MealProcessingStatus.EMBEDDING,
        )
        segment_one = SimpleNamespace(
            id="segment-1",
            cropped_image_url="/data/uploads/crops/seg-1.jpg",
            embedding=None,
        )
        segment_two = SimpleNamespace(
            id="segment-2",
            cropped_image_url="/data/uploads/crops/seg-2.jpg",
            embedding=None,
        )
        session = AsyncMock()
        session_claim = Mock(scalar_one_or_none=Mock(return_value=meal))
        session_segments = Mock(
            scalars=Mock(
                return_value=Mock(
                    all=Mock(return_value=[segment_one, segment_two]),
                )
            )
        )
        session.execute.side_effect = [session_claim, session_segments, asyncio.CancelledError]
        engine = SimpleNamespace(dispose=AsyncMock())

        class SessionContext:
            async def __aenter__(self):
                return session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        session_factory = Mock(return_value=SessionContext())
        bot = SimpleNamespace(send_message=AsyncMock())
        settings = SimpleNamespace(
            DATABASE_URL="postgresql+asyncpg://meal:pw@db:5432/meal",
            BOT_POLL_INTERVAL=3.0,
        )

        with (
            patch.object(polling, "create_async_engine", return_value=engine),
            patch.object(polling, "async_sessionmaker", return_value=session_factory),
            patch.object(
                polling,
                "get_llm_client",
                return_value=SimpleNamespace(embed_multimodal=AsyncMock()),
            ),
            patch.object(
                polling.matching_service,
                "embed_segment_query_embedding",
                side_effect=[
                    [0.1] * matching_service.EMBEDDING_DIMENSION,
                    [0.2] * matching_service.EMBEDDING_DIMENSION,
                ],
            ),
            patch.object(polling.asyncio, "sleep", new=_noop_sleep),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await polling.poll_and_embed_food_segments(bot, settings, poll_interval=0.01)

        self.assertEqual(segment_one.embedding, [0.1] * matching_service.EMBEDDING_DIMENSION)
        self.assertEqual(segment_two.embedding, [0.2] * matching_service.EMBEDDING_DIMENSION)
        self.assertEqual(meal.processing_status, MealProcessingStatus.MATCHING)
        session.commit.assert_awaited_once()

    async def test_poll_and_embed_marks_empty_segment_meal_failed_without_reasoning_handoff(self) -> None:
        from bot import polling

        meal = SimpleNamespace(
            id="12345678-abcd-efgh",
            processing_status=MealProcessingStatus.EMBEDDING,
        )
        session = AsyncMock()
        session_claim = Mock(scalar_one_or_none=Mock(return_value=meal))
        session_segments = Mock(scalars=Mock(return_value=Mock(all=Mock(return_value=[]))))
        session.execute.side_effect = [session_claim, session_segments, asyncio.CancelledError]
        engine = SimpleNamespace(dispose=AsyncMock())

        class SessionContext:
            async def __aenter__(self):
                return session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        session_factory = Mock(return_value=SessionContext())
        bot = SimpleNamespace(send_message=AsyncMock())
        settings = SimpleNamespace(
            DATABASE_URL="postgresql+asyncpg://meal:pw@db:5432/meal",
            BOT_POLL_INTERVAL=3.0,
        )

        with (
            patch.object(polling, "create_async_engine", return_value=engine),
            patch.object(polling, "async_sessionmaker", return_value=session_factory),
            patch.object(
                polling,
                "get_llm_client",
                return_value=SimpleNamespace(embed_multimodal=AsyncMock()),
            ),
            patch.object(
                polling.matching_service,
                "embed_segment_query_embedding",
                AsyncMock(),
            ) as embed_segment_query_embedding,
            patch.object(polling.asyncio, "sleep", new=_noop_sleep),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await polling.poll_and_embed_food_segments(bot, settings, poll_interval=0.01)

        self.assertEqual(meal.processing_status, MealProcessingStatus.FAILED)
        self.assertNotEqual(meal.processing_status, MealProcessingStatus.REASONING)
        embed_segment_query_embedding.assert_not_awaited()
        session.commit.assert_awaited_once()
