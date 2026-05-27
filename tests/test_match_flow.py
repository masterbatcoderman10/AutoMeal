from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.models import MealProcessingStatus
from app.services.embedding_service import (
    EMBEDDING_DIMENSION,
    RETRIEVAL_DOCUMENT,
    RETRIEVAL_QUERY,
)


async def _noop_sleep(*_args, **_kwargs) -> None:
    return None


class MatchingServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_match_segment_uses_retrieval_query_embedding_and_sets_segment_vector(self) -> None:
        from app.services import matching_service

        query_embedding = [0.12] * EMBEDDING_DIMENSION
        segment = SimpleNamespace(id="segment-1", cropped_image_url="/data/uploads/crops/seg-1.jpg", embedding=None)
        food_visual = SimpleNamespace(id="fv-1", food_item_id="item-1")
        session = AsyncMock()
        session.execute.return_value = Mock(first=Mock(return_value=(food_visual, 0.05)))
        llm_client = AsyncMock()
        llm_client.embed_multimodal.return_value = query_embedding

        with (
            patch.object(matching_service.Path, "read_bytes", return_value=b"\xff\xd8\xff"),
            patch.object(matching_service, "_prepare_image_payload", return_value={"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,abc"}}),
        ):
            result = await matching_service.match_segment_against_visual_corpus(
                segment=segment,
                session=session,
                llm_client=llm_client,
                embedding_model="google/gemini-embedding-2-preview",
            )

        self.assertIsNotNone(result)
        self.assertEqual(result.food_visual_id, food_visual.id)
        self.assertAlmostEqual(result.similarity, 0.95)
        self.assertEqual(result.query_embedding, query_embedding)
        self.assertEqual(segment.embedding, query_embedding)
        self.assertEqual(result.match_threshold, matching_service.MATCH_THRESHOLD)
        llm_client.embed_multimodal.assert_awaited_once()
        kwargs = llm_client.embed_multimodal.await_args.kwargs
        self.assertEqual(kwargs["model"], "google/gemini-embedding-2-preview")
        self.assertEqual(kwargs["task_type"], RETRIEVAL_QUERY)

    async def test_match_segment_with_empty_corpus_returns_no_match(self) -> None:
        from app.services import matching_service

        segment = SimpleNamespace(id="segment-1", cropped_image_url="/data/uploads/crops/seg-1.jpg", embedding=None)
        session = AsyncMock()
        session.execute.return_value = Mock(first=Mock(return_value=None))
        llm_client = AsyncMock()
        llm_client.embed_multimodal.return_value = [0.21] * EMBEDDING_DIMENSION

        with patch.object(
            matching_service.Path,
            "read_bytes",
            return_value=b"\xff\xd8\xff",
        ):
            result = await matching_service.match_segment_against_visual_corpus(
                segment=segment,
                session=session,
                llm_client=llm_client,
                embedding_model="google/gemini-embedding-2-preview",
            )

        self.assertFalse(result.is_match)
        self.assertIsNone(result.food_visual_id)
        self.assertIsNone(result.similarity)


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
                polling.matching_service,
                "embed_segment_query_embedding",
                side_effect=[[0.1] * matching_service.EMBEDDING_DIMENSION, [0.2] * matching_service.EMBEDDING_DIMENSION],
            ),
            patch.object(polling.asyncio, "sleep", new=_noop_sleep),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await polling.poll_and_embed_food_segments(bot, settings, poll_interval=0.01)

        self.assertEqual(segment_one.embedding, [0.1] * matching_service.EMBEDDING_DIMENSION)
        self.assertEqual(segment_two.embedding, [0.2] * matching_service.EMBEDDING_DIMENSION)
        self.assertEqual(meal.processing_status, MealProcessingStatus.MATCHING)
        session.commit.assert_awaited_once()

    async def test_poll_and_embed_routes_meal_without_segments_to_reasoning(self) -> None:
        from bot import polling

        meal = SimpleNamespace(
            id="12345678-abcd-efgh",
            processing_status=MealProcessingStatus.EMBEDDING,
        )
        session = AsyncMock()
        session_claim = Mock(scalar_one_or_none=Mock(return_value=meal))
        session_segments = Mock(scalars=Mock(return_value=Mock(all=Mock(return_value=[]))) )
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
                polling.matching_service,
                "embed_segment_query_embedding",
                return_value=[0.1] * 1536,
            ),
            patch.object(polling.asyncio, "sleep", new=_noop_sleep),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await polling.poll_and_embed_food_segments(bot, settings, poll_interval=0.01)

        self.assertEqual(meal.processing_status, MealProcessingStatus.REASONING)
        session.commit.assert_awaited_once()


class MatchWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_poll_and_match_routes_to_reasoning_when_any_segment_is_unresolved(self) -> None:
        from bot import polling

        segment_one = SimpleNamespace(
            id="segment-1",
            cropped_image_url="/data/uploads/crops/seg-1.jpg",
            embedding=None,
            label="Pita Bread",
        )
        segment_two = SimpleNamespace(
            id="segment-2",
            cropped_image_url="/data/uploads/crops/seg-2.jpg",
            embedding=None,
            label="Chicken Curry",
        )
        meal = SimpleNamespace(
            id="12345678-abcd-efgh",
            image_url="/data/uploads/meals/12345678-abcd-efgh.jpg",
            processing_status=MealProcessingStatus.MATCHING,
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
        session.add = Mock()
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
            MATCHING_MODEL="google/gemini-embedding-2-preview",
            TELEGRAM_CHAT_ID="999",
            BOT_POLL_INTERVAL=3.0,
        )

        with (
            patch.object(polling, "create_async_engine", return_value=engine),
            patch.object(polling, "async_sessionmaker", return_value=session_factory),
            patch.object(
                polling.matching_service,
                "match_segment_against_visual_corpus",
                side_effect=[
                    SimpleNamespace(
                        food_visual_id="visual-1",
                        food_item_id="item-1",
                        similarity=0.92,
                        is_match=True,
                        is_below_threshold=False,
                        query_embedding=[0.1] * EMBEDDING_DIMENSION,
                    ),
                    SimpleNamespace(
                        food_visual_id=None,
                        food_item_id=None,
                        similarity=0.12,
                        is_match=False,
                        is_below_threshold=True,
                        query_embedding=[0.2] * EMBEDDING_DIMENSION,
                    ),
                ],
            ),
            patch.object(
                polling,
                "format_unresolved_match_message",
                return_value="I can see your meal, but I do not know it yet.",
            ),
            patch.object(polling.asyncio, "sleep", new=_noop_sleep),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await polling.poll_and_match_food_segments(bot, settings, poll_interval=0.01)

        self.assertEqual(meal.processing_status, MealProcessingStatus.REASONING)
        bot.send_message.assert_awaited_once_with(
            chat_id="999",
            text="I can see your meal, but I do not know it yet.",
        )
        session.add.assert_not_called()
        session.commit.assert_awaited_once()

    async def test_poll_and_match_writes_all_rows_only_when_all_segments_pass_threshold(self) -> None:
        from bot import polling
        from app.services import matching_service

        segment_one = SimpleNamespace(
            id="segment-1",
            cropped_image_url="/data/uploads/crops/seg-1.jpg",
            embedding=None,
            label="Pita Bread",
        )
        segment_two = SimpleNamespace(
            id="segment-2",
            cropped_image_url="/data/uploads/crops/seg-2.jpg",
            embedding=None,
            label="Chicken Curry",
        )
        meal = SimpleNamespace(
            id="12345678-abcd-efgh",
            processing_status=MealProcessingStatus.MATCHING,
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
        session.add = Mock()
        session.add_all = Mock()
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
            MATCHING_MODEL="google/gemini-embedding-2-preview",
            BOT_POLL_INTERVAL=3.0,
        )
        write_back_embeddings = [
            [0.101] * matching_service.EMBEDDING_DIMENSION,
            [0.202] * matching_service.EMBEDDING_DIMENSION,
        ]

        with (
            patch.object(polling, "create_async_engine", return_value=engine),
            patch.object(polling, "async_sessionmaker", return_value=session_factory),
            patch.object(
                polling.matching_service,
                "match_segment_against_visual_corpus",
                side_effect=[
                    SimpleNamespace(
                        food_visual_id="visual-1",
                        food_item_id="item-1",
                        similarity=0.92,
                        is_match=True,
                        is_below_threshold=False,
                        query_embedding=[0.1] * EMBEDDING_DIMENSION,
                    ),
                    SimpleNamespace(
                        food_visual_id="visual-2",
                        food_item_id="item-2",
                        similarity=0.9,
                        is_match=True,
                        is_below_threshold=False,
                        query_embedding=[0.2] * EMBEDDING_DIMENSION,
                    ),
                ],
            ),
            patch.object(
                polling.matching_service,
                "embed_segment_visual_embedding",
                side_effect=write_back_embeddings,
            ),
            patch.object(polling.asyncio, "sleep", new=_noop_sleep),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await polling.poll_and_match_food_segments(bot, settings, poll_interval=0.01)

        self.assertEqual(meal.processing_status, MealProcessingStatus.COMPLETED)
        self.assertEqual(len(session.add.call_args_list), 4)
        food_visual_rows = [
            call.args[0]
            for call in session.add.call_args_list
            if getattr(call.args[0], "cropped_image_url", None)
        ]
        self.assertEqual(
            len(food_visual_rows),
            2,
            "Expected one FoodVisual row per segment",
        )
        self.assertIn([0.101] * matching_service.EMBEDDING_DIMENSION, [row.embedding for row in food_visual_rows])
        self.assertIn([0.202] * matching_service.EMBEDDING_DIMENSION, [row.embedding for row in food_visual_rows])
        bot.send_message.assert_not_awaited()

    async def test_poll_and_match_reuses_new_retrieval_document_embedding_for_each_confirmation(self) -> None:
        from bot import polling
        from app.services import matching_service

        segment_one = SimpleNamespace(
            id="segment-1",
            cropped_image_url="/data/uploads/crops/seg-1.jpg",
            embedding=[0.11] * EMBEDDING_DIMENSION,
            label="Pita Bread",
        )
        meal = SimpleNamespace(
            id="12345678-abcd-efgh",
            processing_status=MealProcessingStatus.MATCHING,
        )
        session = AsyncMock()
        session_claim = Mock(scalar_one_or_none=Mock(return_value=meal))
        session_segments = Mock(
            scalars=Mock(
                return_value=Mock(
                    all=Mock(return_value=[segment_one]),
                )
            )
        )
        session.execute.side_effect = [
            session_claim,
            session_segments,
            asyncio.CancelledError,
            session_claim,
            session_segments,
            asyncio.CancelledError,
        ]
        session.add = Mock()
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
            MATCHING_MODEL="google/gemini-embedding-2-preview",
            BOT_POLL_INTERVAL=3.0,
        )

        first_run_embedding = [0.3] * EMBEDDING_DIMENSION
        second_run_embedding = [0.4] * EMBEDDING_DIMENSION

        with (
            patch.object(polling, "create_async_engine", return_value=engine),
            patch.object(polling, "async_sessionmaker", return_value=session_factory),
            patch.object(
                polling.matching_service,
                "match_segment_against_visual_corpus",
                return_value=SimpleNamespace(
                    food_visual_id="visual-1",
                    food_item_id="item-1",
                    similarity=0.91,
                    is_match=True,
                    is_below_threshold=False,
                    query_embedding=[0.11] * EMBEDDING_DIMENSION,
                ),
            ),
            patch.object(
                polling.matching_service,
                "embed_segment_visual_embedding",
                side_effect=[first_run_embedding, second_run_embedding],
            ),
            patch.object(polling.asyncio, "sleep", new=_noop_sleep),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await polling.poll_and_match_food_segments(bot, settings, poll_interval=0.01)
            with self.assertRaises(asyncio.CancelledError):
                await polling.poll_and_match_food_segments(bot, settings, poll_interval=0.01)

        food_visual_payloads = [
            call.args[0].embedding
            for call in session.add.call_args_list
            if getattr(call.args[0], "cropped_image_url", None)
        ]
        self.assertEqual(len(food_visual_payloads), 2)
        self.assertIn(first_run_embedding, food_visual_payloads)
        self.assertIn(second_run_embedding, food_visual_payloads)

        matching_service_args = polling.matching_service.embed_segment_visual_embedding.call_args_list
        self.assertEqual(len(matching_service_args), 2)
        self.assertEqual(matching_service_args[0].kwargs["task_type"], RETRIEVAL_DOCUMENT)
        self.assertEqual(matching_service_args[1].kwargs["task_type"], RETRIEVAL_DOCUMENT)
