from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx
import numpy as np
from openai import RateLimitError

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
        session.execute.return_value = Mock(first=Mock(return_value=(food_visual, 0.10)))
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
        session.execute.return_value = Mock(first=Mock(return_value=(food_visual, 0.1001)))
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
            patch.object(polling, "get_llm_client", return_value=object()),
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
        self.assertEqual(session.commit.await_count, 2)

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
            patch.object(polling, "get_llm_client", return_value=object()),
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


class GroupedAutoConfirmWriteTests(unittest.IsolatedAsyncioTestCase):
    async def test_grouped_auto_confirm_collapses_to_one_final_write_item_per_food_group(self) -> None:
        from app.services import reasoning_service

        segment_one = SimpleNamespace(
            id="segment-bread-1",
            cropped_image_url="/data/uploads/crops/bread-1.jpg",
            embedding=[0.11] * EMBEDDING_DIMENSION,
        )
        segment_two = SimpleNamespace(
            id="segment-bread-2",
            cropped_image_url="/data/uploads/crops/bread-2.jpg",
            embedding=[0.22] * EMBEDDING_DIMENSION,
        )
        meal = SimpleNamespace(
            id="meal-grouped-final-write",
            processing_status=MealProcessingStatus.REASONING,
            reasoning_state_json=None,
            last_stage_started_at=None,
        )
        session = AsyncMock()
        session.add = Mock()

        candidate = {
            "candidate_id": "candidate-pita",
            "food_item_id": "food-item-pita",
            "label": "pita bread",
            "identity_confidence": 0.99,
            "quantity_confidence": 0.9,
            "match_consistency_confidence": 0.98,
            "missing_evidence": [],
            "nutrition_impact": 0.02,
            "portion_bucket": "STANDARD",
        }
        match_results = [
            (
                segment_one,
                SimpleNamespace(
                    food_item_id="food-item-pita",
                    trace_id="trace-grouped-final-write",
                    top_candidates=[candidate],
                ),
            ),
            (
                segment_two,
                SimpleNamespace(
                    food_item_id="food-item-pita",
                    trace_id="trace-grouped-final-write",
                    top_candidates=[candidate],
                ),
            ),
        ]
        reasoning_payload = {
            "action": "AUTO_CONFIRM",
            "meal_state": "READY_TO_WRITE",
            "trace_id": "trace-grouped-final-write",
            "decision_rationale": "two detector segments belong to one bread item",
            "gate_reason": "",
            "segment_count": 2,
            "food_group_count": 1,
            "food_groups": [
                {
                    "group_id": "group-bread",
                    "group_label": "pita bread",
                    "group_action": "AUTO_CONFIRM",
                    "group_state": "READY_TO_WRITE",
                    "primary_segment_id": "segment-bread-1",
                    "segment_ids": ["segment-bread-1", "segment-bread-2"],
                    "selected_candidate_id": "candidate-pita",
                    "top_3": [candidate, candidate, candidate],
                }
            ],
        }

        captured: dict[str, object] = {}

        async def _capture_apply_final_meal_resolution(**kwargs):
            captured.update(kwargs)
            return {"meal_entries": [], "food_visuals": [], "correction_events": []}

        with patch.object(
            reasoning_service,
            "apply_final_meal_resolution",
            new=AsyncMock(side_effect=_capture_apply_final_meal_resolution),
        ):
            result = await reasoning_service.finalize_meal_from_reasoning(
                session=session,
                meal=meal,
                segments=[segment_one, segment_two],
                match_results=match_results,
                reasoning_payload=reasoning_payload,
            )

        final_segments = captured["final_segments"]
        self.assertEqual(len(final_segments), 1)
        self.assertEqual(final_segments[0].segment_id, "segment-bread-1")
        self.assertEqual(final_segments[0].food.canonical_name, "pita bread")
        self.assertTrue(result["finalized"])

    async def test_grouped_auto_confirm_prefers_reasoning_group_label_over_generic_candidate_label(self) -> None:
        from app.services import reasoning_service

        segment = SimpleNamespace(
            id="segment-curry-1",
            label="curry",
            cropped_image_url="/data/uploads/crops/curry-1.jpg",
            embedding=[0.33] * EMBEDDING_DIMENSION,
        )
        meal = SimpleNamespace(
            id="meal-grouped-authority",
            processing_status=MealProcessingStatus.REASONING,
            reasoning_state_json=None,
            last_stage_started_at=None,
        )
        session = AsyncMock()
        session.add = Mock()

        candidate = {
            "candidate_id": "candidate-curry",
            "food_item_id": "food-item-curry",
            "label": "chicken curry",
            "identity_confidence": 0.95,
            "quantity_confidence": 0.88,
            "match_consistency_confidence": 0.93,
            "missing_evidence": [],
            "nutrition_impact": 0.02,
            "portion_bucket": "STANDARD",
        }
        match_results = [
            (
                segment,
                SimpleNamespace(
                    food_item_id="food-item-curry",
                    trace_id="trace-grouped-authority",
                    top_candidates=[candidate],
                ),
            ),
        ]
        reasoning_payload = {
            "action": "AUTO_CONFIRM",
            "meal_state": "READY_TO_WRITE",
            "trace_id": "trace-grouped-authority",
            "decision_rationale": "Whole-plate reasoning identified the green herb curry variant.",
            "gate_reason": "",
            "segment_count": 1,
            "food_group_count": 1,
            "food_groups": [
                {
                    "group_id": "group-curry",
                    "group_label": "green chicken curry",
                    "group_action": "AUTO_CONFIRM",
                    "group_state": "READY_TO_WRITE",
                    "primary_segment_id": "segment-curry-1",
                    "segment_ids": ["segment-curry-1"],
                    "selected_candidate_id": "candidate-curry",
                    "top_3": [candidate, candidate, candidate],
                }
            ],
        }

        captured: dict[str, object] = {}

        async def _capture_apply_final_meal_resolution(**kwargs):
            captured.update(kwargs)
            return {"meal_entries": [], "food_visuals": [], "correction_events": []}

        with patch.object(
            reasoning_service,
            "apply_final_meal_resolution",
            new=AsyncMock(side_effect=_capture_apply_final_meal_resolution),
        ):
            result = await reasoning_service.finalize_meal_from_reasoning(
                session=session,
                meal=meal,
                segments=[segment],
                match_results=match_results,
                reasoning_payload=reasoning_payload,
            )

        final_segments = captured["final_segments"]
        self.assertEqual(len(final_segments), 1)
        self.assertEqual(final_segments[0].food.canonical_name, "green chicken curry")
        self.assertTrue(result["finalized"])

    async def test_post_interview_grounding_keeps_authoritative_confirmed_candidate_names(self) -> None:
        from app.services import reasoning_service

        segment = SimpleNamespace(
            id="segment-bread-1",
            label="khubz bread",
            cropped_image_url="/data/uploads/crops/bread-1.jpg",
            embedding=[0.31] * EMBEDDING_DIMENSION,
        )
        meal = SimpleNamespace(
            id="meal-grounded-confirmed-name",
            processing_status=MealProcessingStatus.REASONING,
            reasoning_state_json=None,
            last_stage_started_at=None,
        )
        session = AsyncMock()
        session.add = Mock()
        confirmed_candidate = {
            "candidate_id": "segment-bread-1",
            "label": "White Khubz / Pita",
            "identity_confidence": 1.0,
            "quantity_confidence": 1.0,
            "match_consistency_confidence": 1.0,
            "missing_evidence": [],
            "nutrition_impact": 0.0,
            "portion_bucket": "STANDARD",
            "source": "PACKAGED",
        }
        reasoning_payload = {
            "action": "AUTO_CONFIRM",
            "meal_state": "READY_TO_WRITE",
            "trace_id": "trace-grounded-confirmed-name",
            "decision_rationale": "confirmed from interview candidates",
            "gate_reason": "",
            "segment_count": 1,
            "food_group_count": 1,
            "food_groups": [
                {
                    "group_id": "group_bread",
                    "group_label": "Khubz / Pita Bread",
                    "group_action": "AUTO_CONFIRM",
                    "group_state": "READY_TO_WRITE",
                    "primary_segment_id": "segment-bread-1",
                    "segment_ids": ["segment-bread-1"],
                    "selected_candidate_id": "segment-bread-1",
                    "top_3": [confirmed_candidate, confirmed_candidate, confirmed_candidate],
                }
            ],
        }
        captured: dict[str, object] = {}

        async def _capture_apply_final_meal_resolution(**kwargs):
            captured.update(kwargs)
            return {"meal_entries": [], "food_visuals": [], "correction_events": []}

        with patch.object(
            reasoning_service,
            "apply_final_meal_resolution",
            new=AsyncMock(side_effect=_capture_apply_final_meal_resolution),
        ):
            result = await reasoning_service.finalize_meal_from_reasoning(
                session=session,
                meal=meal,
                segments=[segment],
                match_results=[],
                reasoning_payload=reasoning_payload,
            )

        final_segments = captured["final_segments"]
        self.assertEqual(final_segments[0].food.canonical_name, "White Khubz / Pita")
        self.assertTrue(result["finalized"])

    async def test_grouped_auto_confirm_preserves_specific_vector_candidate_over_generic_group_label(self) -> None:
        from app.services import reasoning_service

        segment = SimpleNamespace(
            id="segment-egg-1",
            label="egg and vegetable curry",
            cropped_image_url="/data/uploads/crops/egg-1.jpg",
            embedding=[0.36] * EMBEDDING_DIMENSION,
        )
        meal = SimpleNamespace(
            id="meal-specific-vector-name",
            processing_status=MealProcessingStatus.REASONING,
            reasoning_state_json=None,
            last_stage_started_at=None,
        )
        session = AsyncMock()
        session.add = Mock()
        candidate = {
            "candidate_id": "visual-egg-lauki",
            "label": "Boiled Egg Curry with Bottle Gourd (Lauki)",
            "identity_confidence": 0.99,
            "quantity_confidence": 0.99,
            "match_consistency_confidence": 0.99,
            "missing_evidence": [],
            "nutrition_impact": 0.0,
            "portion_bucket": "STANDARD",
            "source": "vector_match",
        }
        reasoning_payload = {
            "action": "AUTO_CONFIRM",
            "meal_state": "READY_TO_WRITE",
            "trace_id": "trace-specific-vector-name",
            "decision_rationale": "vector match has exact confirmed identity",
            "gate_reason": "",
            "segment_count": 1,
            "food_group_count": 1,
            "food_groups": [
                {
                    "group_id": "group-egg",
                    "group_label": "egg and vegetable curry",
                    "group_action": "AUTO_CONFIRM",
                    "group_state": "READY_TO_WRITE",
                    "primary_segment_id": "segment-egg-1",
                    "segment_ids": ["segment-egg-1"],
                    "selected_candidate_id": "visual-egg-lauki",
                    "top_3": [candidate, candidate, candidate],
                }
            ],
        }
        captured: dict[str, object] = {}

        async def _capture_apply_final_meal_resolution(**kwargs):
            captured.update(kwargs)
            return {"meal_entries": [], "food_visuals": [], "correction_events": []}

        with patch.object(
            reasoning_service,
            "apply_final_meal_resolution",
            new=AsyncMock(side_effect=_capture_apply_final_meal_resolution),
        ):
            result = await reasoning_service.finalize_meal_from_reasoning(
                session=session,
                meal=meal,
                segments=[segment],
                match_results=[],
                reasoning_payload=reasoning_payload,
            )

        final_segments = captured["final_segments"]
        self.assertEqual(
            final_segments[0].food.canonical_name,
            "Boiled Egg Curry with Bottle Gourd (Lauki)",
        )
        self.assertTrue(result["finalized"])


class InterviewFinalizationWriteTests(unittest.IsolatedAsyncioTestCase):
    async def test_vector_match_reuse_does_not_mutate_learned_food_item_identity(self) -> None:
        from app.services import meal_resolution_service

        existing_item = SimpleNamespace(
            id="food-egg-lauki",
            name="Boiled Egg Curry with Bottle Gourd (Lauki)",
            aliases=["Boiled Egg Curry with Bottle Gourd (Lauki)"],
            source_type="HOME",
            brand_name=None,
            restaurant_name=None,
            times_confirmed=1,
            is_verified=False,
            llm_reasoning=None,
        )
        session = AsyncMock()
        session.get.return_value = existing_item

        resolved = await meal_resolution_service.resolve_or_create_food_item(
            session=session,
            food=meal_resolution_service.ResolvedFoodInput(
                canonical_name="egg and vegetable curry",
                food_item_id="food-egg-lauki",
                aliases=["egg and vegetable curry"],
                source_type="vector_match",
                times_confirmed=2,
                is_verified=True,
            ),
        )

        self.assertIs(resolved, existing_item)
        self.assertEqual(existing_item.name, "Boiled Egg Curry with Bottle Gourd (Lauki)")
        self.assertEqual(existing_item.source_type, "HOME")

    async def test_finalize_confirmed_interview_keeps_resolver_payload_in_authoritative_write(self) -> None:
        from app.services import interview_service

        meal = SimpleNamespace(
            id="meal-finalize",
            processing_status=MealProcessingStatus.INTERVIEWING,
            reasoning_state_json={
                "meal_reasoning": {
                    "food_groups": [
                        {
                            "group_id": "group-egg",
                            "group_label": "egg curry",
                            "primary_segment_id": "seg-egg-1",
                            "segment_ids": ["seg-egg-1"],
                            "clarification_actions": [
                                {
                                    "question_id": "q-detail-curry",
                                    "type": "FREE_TEXT",
                                    "kind": "DETAIL",
                                    "required": True,
                                }
                            ],
                        }
                    ]
                },
                "answers_by_question_id": {
                    "q-detail-curry": {
                        "question_id": "q-detail-curry",
                        "group_id": "group-egg",
                        "name": "egg curry with bottle gourd",
                    }
                },
            },
        )
        segment = SimpleNamespace(
            id="seg-egg-1",
            cropped_image_url="/data/uploads/crops/seg-egg-1.jpg",
            embedding=[0.44] * EMBEDDING_DIMENSION,
        )
        session = AsyncMock()
        session.add = Mock()
        confirmation_items = [
            {
                "group_id": "group-egg",
                "primary_segment_id": "seg-egg-1",
                "segment_id": "seg-egg-1",
                "segment_ids": ["seg-egg-1"],
                "name": "egg curry with bottle gourd",
                "source_type": "HOME",
                "portion_bucket": "STANDARD",
                "approval_status": "CORRECTED",
            }
        ]

        captured: dict[str, object] = {}
        llm_client = SimpleNamespace(
            chat_completion=AsyncMock(
                return_value={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "group_id": "group-egg",
                                        "primary_segment_id": "seg-egg-1",
                                        "segment_ids": ["seg-egg-1"],
                                        "final_name": "egg curry with bottle gourd",
                                        "aliases": ["egg curry with bottle gourd"],
                                        "source_type": "HOME",
                                        "portion_bucket": "STANDARD",
                                        "quantity_display": None,
                                        "quantity_json": None,
                                        "food_item_id": None,
                                        "brand_name": None,
                                        "restaurant_name": None,
                                        "correction_note": None,
                                        "supporting_details": [],
                                    }
                                )
                            }
                        }
                    ]
                }
            )
        )

        async def _capture_apply_final_meal_resolution(**kwargs):
            captured.update(kwargs)
            return {"meal_entries": [], "food_visuals": [], "correction_events": []}

        with (
            patch.object(interview_service, "get_llm_client", return_value=llm_client, create=True),
            patch.object(
                interview_service,
                "apply_final_meal_resolution",
                new=AsyncMock(side_effect=_capture_apply_final_meal_resolution),
            ),
        ):
            await interview_service.finalize_confirmed_interview(
                session=session,
                meal=meal,
                confirmation_items=confirmation_items,
                segments=[segment],
            )

        reasoning_state_json = captured["reasoning_state_json"]
        self.assertIn("answers_by_question_id", reasoning_state_json)
        self.assertEqual(
            reasoning_state_json["answers_by_question_id"]["q-detail-curry"]["name"],
            "egg curry with bottle gourd",
        )
        self.assertIn("resolver_payload", reasoning_state_json)
        self.assertEqual(
            reasoning_state_json["resolver_payload"]["confirmation_items"][0]["name"],
            "egg curry with bottle gourd",
        )

    async def test_finalize_confirmed_interview_maps_group_finalizer_output_to_authoritative_write(self) -> None:
        from app.services import interview_service

        meal = SimpleNamespace(
            id="meal-finalizer-home",
            processing_status=MealProcessingStatus.INTERVIEWING,
            reasoning_state_json={
                "meal_reasoning": {
                    "trace_id": "trace-finalizer-home",
                    "food_groups": [
                        {
                            "group_id": "group-chicken",
                            "group_label": "chicken curry",
                            "question_kind": "DETAIL",
                            "question_focus": "style of the curry",
                            "group_actions": ["IDENTITY_CLARIFICATION_REQUIRED"],
                            "primary_segment_id": "seg-chicken-1",
                            "segment_ids": ["seg-chicken-1"],
                            "top_3": [
                                {
                                    "candidate_id": "candidate-chicken",
                                    "label": "Chicken curry",
                                    "source_type": "HOME",
                                }
                            ],
                        }
                    ]
                },
                "answers_by_question_id": {
                    "q-style": {
                        "question_id": "q-style",
                        "group_id": "group-chicken",
                        "question_kind": "DETAIL",
                        "value": "Green masala",
                    }
                },
            },
        )
        segment = SimpleNamespace(
            id="seg-chicken-1",
            cropped_image_url="/data/uploads/crops/seg-chicken-1.jpg",
            embedding=[0.44] * EMBEDDING_DIMENSION,
        )
        session = AsyncMock()
        session.add = Mock()
        confirmation_items = [
            {
                "group_id": "group-chicken",
                "primary_segment_id": "seg-chicken-1",
                "segment_id": "seg-chicken-1",
                "segment_ids": ["seg-chicken-1"],
                "name": "Green masala",
                "source_type": "HOME",
                "portion_bucket": "STANDARD",
                "approval_status": "CORRECTED",
                "quantity_display": "2 pieces",
            }
        ]
        llm_client = SimpleNamespace(
            chat_completion=AsyncMock(
                return_value={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "group_id": "group-chicken",
                                        "primary_segment_id": "seg-chicken-1",
                                        "segment_ids": ["seg-chicken-1"],
                                        "final_name": "Chicken curry (green masala)",
                                        "aliases": ["Green masala chicken curry"],
                                        "source_type": "HOME",
                                        "portion_bucket": "STANDARD",
                                        "quantity_display": "2 pieces",
                                        "quantity_json": {
                                            "quantity": 2,
                                            "unit": "pieces",
                                            "portion_bucket": "STANDARD",
                                        },
                                        "food_item_id": None,
                                        "brand_name": None,
                                        "restaurant_name": None,
                                        "correction_note": "Preserve clarified curry style.",
                                        "supporting_details": ["style clarified from interview"],
                                    }
                                )
                            }
                        }
                    ]
                }
            )
        )

        captured: dict[str, object] = {}

        async def _capture_apply_final_meal_resolution(**kwargs):
            captured.update(kwargs)
            return {"meal_entries": [], "food_visuals": [], "correction_events": []}

        with (
            patch.object(interview_service, "get_llm_client", return_value=llm_client, create=True),
            patch.object(
                interview_service,
                "apply_final_meal_resolution",
                new=AsyncMock(side_effect=_capture_apply_final_meal_resolution),
            ),
        ):
            await interview_service.finalize_confirmed_interview(
                session=session,
                meal=meal,
                confirmation_items=confirmation_items,
                segments=[segment],
            )

        final_segments = captured["final_segments"]
        self.assertEqual(len(final_segments), 1)
        self.assertEqual(final_segments[0].food.canonical_name, "Chicken curry (green masala)")
        self.assertIn("Green masala chicken curry", final_segments[0].food.aliases or [])
        self.assertEqual(final_segments[0].food.source_type, "HOME")
        self.assertEqual(final_segments[0].quantity_display, "2 pieces")
        self.assertEqual(
            final_segments[0].quantity_json,
            {
                "quantity": 2,
                "unit": "pieces",
                "portion_bucket": "STANDARD",
            },
        )
        self.assertEqual(final_segments[0].portion_bucket, "STANDARD")
        self.assertTrue(final_segments[0].create_food_visual)
        self.assertTrue(final_segments[0].visual_learning_eligible)
        reasoning_state_json = captured["reasoning_state_json"]
        self.assertEqual(reasoning_state_json["finalizer_groups"][0]["status"], "SUCCEEDED")
        self.assertEqual(
            reasoning_state_json["confirmation_items"][0]["name"],
            "Chicken curry (green masala)",
        )

    def test_best_effort_grounding_resolution_preserves_visual_learning_inputs(self) -> None:
        from app.services import interview_service

        segment = SimpleNamespace(
            id="seg-grounding-fallback",
            cropped_image_url="/data/uploads/crops/seg-grounding-fallback.jpg",
            embedding=[0.61] * EMBEDDING_DIMENSION,
        )

        resolution = interview_service.final_resolution_from_confirmation(
            item={
                "segment_id": "seg-grounding-fallback",
                "name": "Protein Bar",
                "source_type": "PACKAGED",
                "brand_name": "Acme",
                "quantity_display": "1 bar",
            },
            segment=segment,
            best_effort=True,
        )

        self.assertTrue(resolution.food.needs_grounding)
        self.assertFalse(resolution.food.is_verified)
        self.assertTrue(
            resolution.create_food_visual,
            "Degraded saves should still preserve FoodVisual creation when segment crops and embeddings exist.",
        )
        self.assertEqual(
            resolution.segment_cropped_image_url,
            "/data/uploads/crops/seg-grounding-fallback.jpg",
        )
        self.assertEqual(len(resolution.segment_embedding or []), EMBEDDING_DIMENSION)

    async def test_apply_final_meal_resolution_preserves_finalizer_write_metadata(self) -> None:
        from app.services import meal_resolution_service

        meal = SimpleNamespace(
            id="meal-write-preserve",
            processing_status=MealProcessingStatus.INTERVIEWING,
            reasoning_state_json={"existing": "keep"},
            last_stage_started_at=None,
        )
        from app.models import FoodItem

        resolved_food = FoodItem(
            id="food-packaged-1",
            name="Protein Bar Deluxe",
            source_type="PACKAGED",
            brand_name="Acme",
            is_verified=False,
            times_confirmed=1,
        )
        session = AsyncMock()
        session.add = Mock()
        session.add_all = Mock()

        final_segment = meal_resolution_service.FinalSegmentResolution(
            food=meal_resolution_service.ResolvedFoodInput(
                canonical_name="Protein Bar Deluxe",
                aliases=["Acme Protein Bar Deluxe"],
                source_type="PACKAGED",
                brand_name="Acme",
                is_verified=False,
                needs_grounding=True,
            ),
            segment_id="seg-packaged-1",
            segment_cropped_image_url="/data/uploads/crops/seg-packaged-1.jpg",
            segment_embedding=[0.2] * EMBEDDING_DIMENSION,
            portion_bucket="LARGE",
            identification_method="INTERVIEW",
            quantity_json={
                "quantity": 1,
                "unit": "bar",
                "portion_bucket": "LARGE",
                "grounding_prep": {
                    "status": "NEEDS_GROUNDING",
                    "source_type": "PACKAGED",
                    "canonical_name": "Protein Bar Deluxe",
                    "brand_name": "Acme",
                },
            },
            quantity_display="1 bar",
            create_food_visual=True,
            visual_learning_eligible=True,
        )

        with patch.object(
            meal_resolution_service,
            "resolve_or_create_food_item",
            new=AsyncMock(return_value=resolved_food),
        ) as resolve_food:
            result = await meal_resolution_service.apply_final_meal_resolution(
                session=session,
                meal=meal,
                final_segments=[final_segment],
                reasoning_state_json={"completed_by": "interview_service"},
            )

        resolve_food.assert_awaited_once()
        handoff = resolve_food.await_args.kwargs["food"]
        self.assertEqual(handoff.canonical_name, "Protein Bar Deluxe")
        self.assertEqual(handoff.source_type, "PACKAGED")
        self.assertEqual(handoff.brand_name, "Acme")
        entry = next(call.args[0] for call in session.add.call_args_list if hasattr(call.args[0], "meal_log_id"))
        self.assertEqual(entry.portion_bucket, "LARGE")
        self.assertEqual(entry.quantity_display, "1 bar")
        self.assertEqual(entry.quantity_json["quantity"], 1)
        self.assertEqual(entry.quantity_json["unit"], "bar")
        self.assertEqual(result.food_visuals[0].cropped_image_url, "/data/uploads/crops/seg-packaged-1.jpg")


class MatchWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_post_interview_grounding_quota_failure_surfaces_blocker_and_degraded_save(self) -> None:
        import httpx

        from bot import polling

        interview = SimpleNamespace(
            chat_id="999",
            meal_log_id="meal-grounding-quota",
            is_active=True,
            state_key="GROUNDING_PENDING",
            current_prompt_payload={
                "roadmap_step": "GROUNDING_PENDING",
                "grounding_handoff_pending": False,
                "grounding_status": "HANDOFF_ACKNOWLEDGED",
            },
            updated_at=object(),
        )
        meal = SimpleNamespace(
            id="meal-grounding-quota",
            processing_status=MealProcessingStatus.INTERVIEWING,
            reasoning_state_json={
                "grounding_required": True,
                "grounding_status": "HANDOFF_ACKNOWLEDGED",
                "confirmation_items": [
                    {
                        "segment_id": "seg-1",
                        "segment_ids": ["seg-1"],
                        "name": "Protein Bar",
                        "source_type": "PACKAGED",
                        "brand_name": "Acme",
                        "quantity_display": "1 bar",
                    }
                ],
            },
            recovery_attempt_count=0,
            last_stage_started_at=None,
        )
        segment = SimpleNamespace(
            id="seg-1",
            meal_log_id="meal-grounding-quota",
            label="bar",
            cropped_image_url="/data/uploads/crops/seg-1.jpg",
            embedding=[0.1] * 1536,
            match_candidates_json={
                "top_3": [
                    {
                        "candidate_id": "candidate-1",
                        "label": "Protein Bar",
                        "identity_confidence": 0.97,
                    }
                ],
                "match_threshold": 0.9,
            },
        )
        session = AsyncMock()
        session.add = Mock()
        session.execute.side_effect = [
            Mock(scalars=Mock(return_value=Mock(all=Mock(return_value=[interview])))),
            Mock(scalars=Mock(return_value=Mock(all=Mock(return_value=[segment])))),
        ]
        session.get = AsyncMock(return_value=meal)
        engine = SimpleNamespace(dispose=AsyncMock())

        class SessionContext:
            async def __aenter__(self):
                return session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        session_factory = Mock(return_value=SessionContext())
        settings = SimpleNamespace(
            DATABASE_URL="postgresql+asyncpg://meal:pw@db:5432/meal",
            TELEGRAM_CHAT_ID="999",
            BOT_POLL_INTERVAL=3.0,
        )
        quota_error = RateLimitError(
            "Error code: 403 - Key limit exceeded (total limit)",
            response=httpx.Response(
                429,
                request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"),
            ),
            body={"error": {"message": "Key limit exceeded"}},
        )
        bot = SimpleNamespace(send_message=AsyncMock())

        async def _capture_degraded_finalize(**_kwargs):
            meal.processing_status = MealProcessingStatus.COMPLETED
            meal.reasoning_state_json = {
                "grounding_status": "DEGRADED_SAVED",
                "grounding_failure": {"category": "provider_quota"},
            }
            return {"meal_entries": [], "food_visuals": [], "correction_events": []}

        reasoning_mock = AsyncMock(side_effect=quota_error)
        with (
            patch.object(polling, "create_async_engine", return_value=engine),
            patch.object(polling, "async_sessionmaker", return_value=session_factory),
            patch.object(polling, "get_llm_client", return_value=object()),
            patch.object(polling.reasoning_service, "run_reasoning_request", reasoning_mock),
            patch.object(polling.interview_service, "finalize_confirmed_interview", AsyncMock(side_effect=_capture_degraded_finalize)),
            patch.object(polling.asyncio, "sleep", side_effect=asyncio.CancelledError),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await polling.poll_post_interview_grounding(
                    bot,
                    settings,
                    poll_interval=0.01,
                    bot_data={},
                )

        self.assertEqual(meal.processing_status, MealProcessingStatus.COMPLETED)
        self.assertEqual(meal.reasoning_state_json["grounding_status"], "DEGRADED_SAVED")
        self.assertEqual(meal.reasoning_state_json["grounding_failure"]["category"], "provider_quota")
        self.assertFalse(interview.is_active)
        self.assertEqual(interview.current_prompt_payload["grounding_status"], "DEGRADED_SAVED")
        self.assertIn("quota", bot.send_message.await_args.kwargs["text"].lower())
        reasoning_mock.assert_awaited_once()
        self.assertTrue(
            reasoning_mock.await_args.kwargs["propagate_errors"],
        )
        engine.dispose.assert_awaited_once()

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
        prepared_interview = SimpleNamespace(
            id="interview-1",
            chat_id="999",
            current_prompt_payload={
                "roadmap_step": "INITIAL_QUESTION",
                "pending_targets": [
                    {
                        "group_id": "group-egg-curry",
                        "primary_segment_id": "segment-1",
                        "segment_ids": ["segment-1", "segment-2"],
                        "label": "egg curry",
                        "question_kind": "DETAIL",
                        "question_focus": "vegetable inside egg curry",
                        "question_examples": [
                            "egg curry with bottle gourd",
                            "egg curry with zucchini",
                        ],
                    }
                ],
                "current_target_index": 0,
                "answers_by_segment": [],
                "session_mode": "MEAL_INTERVIEW",
            },
        )

        async def _finalize_unresolved(**_kwargs):
            meal.processing_status = MealProcessingStatus.INTERVIEWING
            return {"finalized": False}

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
            patch.object(polling, "get_llm_client", return_value=object()),
            patch.object(
                polling.reasoning_service,
                "run_reasoning_request",
                AsyncMock(return_value=({"action": "ASK_CHOICE", "meal_state": "PENDING_INTERVIEW"}, None)),
            ),
            patch.object(
                polling.reasoning_service,
                "finalize_meal_from_reasoning",
                AsyncMock(side_effect=_finalize_unresolved),
            ),
            patch.object(
                polling.interview_service,
                "prepare_interview_session",
                AsyncMock(return_value=prepared_interview),
            ) as prepare_interview_session,
            patch.object(
                polling,
                "_start_meal_interview_turn",
                AsyncMock(return_value=SimpleNamespace(turn_action="continue_interview")),
            ) as start_meal_interview_turn,
            patch.object(polling.asyncio, "sleep", new=_noop_sleep),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await polling.poll_and_match_food_segments(bot, settings, poll_interval=0.01)

        self.assertEqual(meal.processing_status, MealProcessingStatus.INTERVIEWING)
        prepare_interview_session.assert_awaited_once_with(
            session=session,
            meal=meal,
            segments=[segment_one, segment_two],
            chat_id="999",
        )
        start_meal_interview_turn.assert_awaited_once_with(
            bot=bot,
            session=session,
            interview=prepared_interview,
            settings=settings,
        )
        session.add.assert_not_called()

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

        async def finalize_success(**kwargs):
            meal.processing_status = MealProcessingStatus.COMPLETED
            entries = [
                SimpleNamespace(segment_id="segment-1", portion_bucket="STANDARD", quantity_display="Standard"),
                SimpleNamespace(segment_id="segment-2", portion_bucket="STANDARD", quantity_display="Standard"),
            ]
            return {"finalized": True, "meal_resolution": SimpleNamespace(meal_entries=entries)}

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
            patch.object(polling, "get_llm_client", return_value=object()),
            patch.object(
                polling.reasoning_service,
                "run_reasoning_request",
                AsyncMock(return_value=({"action": "AUTO_CONFIRM", "meal_state": "READY_TO_WRITE"}, None)),
            ),
            patch.object(
                polling.reasoning_service,
                "finalize_meal_from_reasoning",
                AsyncMock(side_effect=finalize_success),
            ) as finalize_meal,
            patch.object(polling, "format_match_completion_message", return_value="meal completed"),
            patch.object(polling.asyncio, "sleep", new=_noop_sleep),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await polling.poll_and_match_food_segments(bot, settings, poll_interval=0.01)

        self.assertEqual(meal.processing_status, MealProcessingStatus.COMPLETED)
        finalize_meal.assert_awaited_once()
        bot.send_message.assert_awaited_once_with(chat_id="999", text="meal completed")

    async def test_poll_and_match_reuses_new_retrieval_document_embedding_for_each_confirmation(self) -> None:
        from bot import polling

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

        async def finalize_repeated(**kwargs):
            meal.processing_status = MealProcessingStatus.COMPLETED
            return {
                "finalized": True,
                "meal_resolution": SimpleNamespace(
                    meal_entries=[
                        SimpleNamespace(segment_id="segment-1", portion_bucket="STANDARD", quantity_display="Standard")
                    ]
                ),
            }

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
            patch.object(polling, "get_llm_client", return_value=object()),
            patch.object(
                polling.reasoning_service,
                "run_reasoning_request",
                AsyncMock(return_value=({"action": "AUTO_CONFIRM", "meal_state": "READY_TO_WRITE"}, None)),
            ),
            patch.object(
                polling.reasoning_service,
                "finalize_meal_from_reasoning",
                AsyncMock(side_effect=finalize_repeated),
            ) as finalize_meal,
            patch.object(polling, "format_match_completion_message", return_value="meal completed"),
            patch.object(polling.asyncio, "sleep", new=_noop_sleep),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await polling.poll_and_match_food_segments(bot, settings, poll_interval=0.01)
            with self.assertRaises(asyncio.CancelledError):
                await polling.poll_and_match_food_segments(bot, settings, poll_interval=0.01)

        self.assertEqual(finalize_meal.await_count, 2)
        embed_segment_visual_embedding.assert_not_called()
