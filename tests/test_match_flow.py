from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx
import numpy as np

from app.models import MealProcessingStatus
from app.services.embedding_service import (
    EMBEDDING_DIMENSION,
    RETRIEVAL_QUERY,
)


async def _noop_sleep(*_args, **_kwargs) -> None:
    return None


class MatchingServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_cached_match_accepts_pgvector_numpy_embeddings(self) -> None:
        from app.services import matching_service

        segment = SimpleNamespace(
            id="segment-1",
            embedding=np.array([0.12] * EMBEDDING_DIMENSION, dtype=np.float32),
        )
        food_visual = SimpleNamespace(id="fv-1", food_item_id="item-1")
        session = AsyncMock()
        session.execute.return_value = Mock(first=Mock(return_value=(food_visual, 0.05)))

        result = await matching_service.match_segment_with_cached_embedding(
            segment=segment,
            session=session,
        )

        self.assertEqual(result.food_visual_id, "fv-1")
        self.assertEqual(len(result.query_embedding), EMBEDDING_DIMENSION)
        self.assertIsInstance(segment.embedding, list)

    async def test_cached_match_query_eager_loads_food_item_relationship(self) -> None:
        from app.services import matching_service

        segment = SimpleNamespace(id="segment-1", embedding=[0.12] * EMBEDDING_DIMENSION)
        food_visual = SimpleNamespace(id="fv-1", food_item_id="item-1")
        session = AsyncMock()
        session.execute.return_value = Mock(first=Mock(return_value=(food_visual, 0.05)))

        await matching_service.match_segment_with_cached_embedding(
            segment=segment,
            session=session,
        )

        statement = session.execute.await_args.args[0]
        self.assertTrue(statement._with_options, "expected eager-loading options on match query")

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

    async def test_match_segment_accepts_similarity_exactly_at_threshold(self) -> None:
        from app.services import matching_service

        query_embedding = [0.12] * EMBEDDING_DIMENSION
        segment = SimpleNamespace(id="segment-1", cropped_image_url="/data/uploads/crops/seg-1.jpg", embedding=None)
        food_visual = SimpleNamespace(id="fv-1", food_item_id="item-1")
        session = AsyncMock()
        session.execute.return_value = Mock(first=Mock(return_value=(food_visual, 0.15)))
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

        self.assertTrue(result.is_match)
        self.assertFalse(result.is_below_threshold)
        self.assertTrue(result.resolved)
        self.assertEqual(result.food_visual_id, food_visual.id)
        self.assertAlmostEqual(result.similarity or 0.0, matching_service.MATCH_THRESHOLD)

    async def test_match_segment_rejects_similarity_just_below_threshold(self) -> None:
        from app.services import matching_service

        query_embedding = [0.12] * EMBEDDING_DIMENSION
        segment = SimpleNamespace(id="segment-1", cropped_image_url="/data/uploads/crops/seg-1.jpg", embedding=None)
        food_visual = SimpleNamespace(id="fv-1", food_item_id="item-1")
        session = AsyncMock()
        session.execute.return_value = Mock(first=Mock(return_value=(food_visual, 0.1501)))
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

        self.assertFalse(result.is_match)
        self.assertTrue(result.is_below_threshold)
        self.assertFalse(result.resolved)
        self.assertEqual(result.food_visual_id, food_visual.id)
        self.assertLess(result.similarity or 0.0, matching_service.MATCH_THRESHOLD)

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

    def test_prepare_query_content_preserves_remote_url_inputs(self) -> None:
        from app.services import matching_service

        content = matching_service._prepare_query_content("https://example.com/crop.jpg")
        self.assertEqual(content[1]["image_url"]["url"], "https://example.com/crop.jpg")

    async def test_embed_with_retry_retries_http_errors(self) -> None:
        from app.services import matching_service

        llm_client = SimpleNamespace(
            embed_multimodal=AsyncMock(
                side_effect=[
                    httpx.ConnectError("temporary failure"),
                    [0.33] * EMBEDDING_DIMENSION,
                ]
            )
        )

        result = await matching_service._embed_with_retry(
            llm_client=llm_client,
            model="google/gemini-embedding-2-preview",
            content=[{"type": "text", "text": "segment"}],
            task_type="RETRIEVAL_QUERY",
        )

        self.assertEqual(result, [0.33] * EMBEDDING_DIMENSION)
        self.assertEqual(llm_client.embed_multimodal.await_count, 2)

    async def test_embed_with_retry_does_not_retry_validation_failures(self) -> None:
        from app.services import matching_service

        llm_client = SimpleNamespace(
            embed_multimodal=AsyncMock(return_value=[0.33, 0.44])
        )

        with self.assertRaises(matching_service.MatchingError):
            await matching_service._embed_with_retry(
                llm_client=llm_client,
                model="google/gemini-embedding-2-preview",
                content=[{"type": "text", "text": "segment"}],
                task_type="RETRIEVAL_QUERY",
            )

        self.assertEqual(llm_client.embed_multimodal.await_count, 1)

    async def test_persist_successful_match_rows_does_not_mutate_confirmation_count(self) -> None:
        from app.services import matching_service

        food_item = SimpleNamespace(times_confirmed=1, is_verified=True)
        result = SimpleNamespace(
            food_item_id="item-1",
            food_visual=SimpleNamespace(food_item=food_item),
        )
        segment = SimpleNamespace(id="segment-1", cropped_image_url="/data/uploads/crops/seg-1.jpg")
        session = AsyncMock()
        session.add = Mock()

        with patch.object(
            matching_service,
            "embed_segment_visual_embedding",
            return_value=[0.5] * matching_service.EMBEDDING_DIMENSION,
        ):
            await matching_service.persist_successful_match_rows(
                session=session,
                meal=SimpleNamespace(id="meal-1"),
                match_results=[(segment, result)],
                llm_client=AsyncMock(),
            )

        self.assertEqual(food_item.times_confirmed, 1)
        self.assertEqual(session.add.call_count, 2)
        diary_entries = [
            call.args[0]
            for call in session.add.call_args_list
            if hasattr(call.args[0], "identification_method")
        ]
        self.assertEqual(len(diary_entries), 1)
        self.assertTrue(diary_entries[0].is_verified)


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

    async def test_poll_and_embed_marks_meal_without_segments_failed(self) -> None:
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

        self.assertEqual(meal.processing_status, MealProcessingStatus.FAILED)
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
            TELEGRAM_CHAT_ID="999",
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
                        food_visual=SimpleNamespace(
                            food_item=SimpleNamespace(
                                name="Pita Bread",
                                calories=180.0,
                                protein_g=6.0,
                                carbs_g=35.0,
                                fat_g=2.0,
                                is_verified=True,
                            )
                        ),
                        is_match=True,
                        is_below_threshold=False,
                        query_embedding=[0.1] * EMBEDDING_DIMENSION,
                    ),
                    SimpleNamespace(
                        food_visual_id="visual-2",
                        food_item_id="item-2",
                        similarity=0.9,
                        food_visual=SimpleNamespace(
                            food_item=SimpleNamespace(
                                name="Chicken Curry",
                                calories=320.0,
                                protein_g=24.0,
                                carbs_g=12.0,
                                fat_g=20.0,
                                is_verified=False,
                            )
                        ),
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
            patch.object(polling, "format_match_completion_message", return_value="meal completed"),
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
        bot.send_message.assert_awaited_once_with(chat_id="999", text="meal completed")

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
            TELEGRAM_CHAT_ID="999",
            BOT_POLL_INTERVAL=3.0,
        )

        first_run_embedding = [0.3] * EMBEDDING_DIMENSION
        second_run_embedding = [0.4] * EMBEDDING_DIMENSION

        with (
            patch.object(polling, "create_async_engine", return_value=engine),
            patch.object(polling, "async_sessionmaker", return_value=session_factory),
            patch.object(
                polling.matching_service,
                "match_segment_with_cached_embedding",
                return_value=SimpleNamespace(
                    food_visual_id="visual-1",
                    food_item_id="item-1",
                    similarity=0.91,
                    food_visual=SimpleNamespace(
                        id="visual-1",
                        food_item_id="item-1",
                        food_item=SimpleNamespace(
                            name="Pita Bread",
                            calories=180.0,
                            protein_g=6.0,
                            carbs_g=35.0,
                            fat_g=2.0,
                            is_verified=True,
                        ),
                    ),
                    is_match=True,
                    is_below_threshold=False,
                    query_embedding=[0.11] * EMBEDDING_DIMENSION,
                ),
            ),
            patch.object(
                polling.matching_service,
                "embed_segment_visual_embedding",
                side_effect=[first_run_embedding, second_run_embedding],
            ) as embed_segment_visual_embedding,
            patch.object(polling, "format_match_completion_message", return_value="meal completed"),
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

        matching_service_args = embed_segment_visual_embedding.call_args_list
        self.assertEqual(len(matching_service_args), 2)
        self.assertEqual(matching_service_args[0].kwargs["segment"], segment_one)
        self.assertEqual(matching_service_args[1].kwargs["segment"], segment_one)
        self.assertEqual(
            matching_service_args[0].kwargs["embedding_model"],
            matching_service.MATCHING_EMBEDDING_MODEL,
        )
        self.assertEqual(
            matching_service_args[1].kwargs["embedding_model"],
            matching_service.MATCHING_EMBEDDING_MODEL,
        )
