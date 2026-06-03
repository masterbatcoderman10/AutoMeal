from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from app.models import MealProcessingStatus


async def _noop_sleep(*_args, **_kwargs) -> None:
    return None


def _fake_match_result(segment_id: str, is_below_threshold: bool = False) -> SimpleNamespace:
    food_item = SimpleNamespace(
        name="meal item",
        calories=320.0,
        protein_g=18.0,
        carbs_g=40.0,
        fat_g=10.0,
        is_verified=True,
    )
    return SimpleNamespace(
        food_visual_id=f"visual-{segment_id}",
        food_item_id=f"item-{segment_id}",
        similarity=0.93,
        is_match=True,
        is_below_threshold=is_below_threshold,
        match_threshold=0.90,
        query_embedding=[0.2] * 3,
        food_visual=SimpleNamespace(food_item=food_item),
        top_candidates=[
            {
                "candidate_id": f"visual-{segment_id}",
                "label": "meal item",
                "identity_confidence": 0.93,
                "quantity_confidence": 0.82,
                "match_consistency_confidence": 0.91,
                "visual_evidence": ["matching fake candidate"],
                "missing_evidence": [],
                "specificity": "high",
                "nutrition_relevance": "medium",
                "source": "test",
                "decision_rationale": "stable fake match",
                "nutrition_impact": 0.1,
            }
        ],
    )


class ParallelPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_slow_segment_does_not_block_siblings(self) -> None:
        from bot import polling

        meal = SimpleNamespace(
            id="12345678-abcd-efgh",
            processing_status=MealProcessingStatus.MATCHING,
        )
        segments = [
            SimpleNamespace(id="segment-slow", cropped_image_url="/data/uploads/crops/seg-slow.jpg"),
            SimpleNamespace(id="segment-fast-1", cropped_image_url="/data/uploads/crops/seg-fast-1.jpg"),
            SimpleNamespace(id="segment-fast-2", cropped_image_url="/data/uploads/crops/seg-fast-2.jpg"),
            SimpleNamespace(id="segment-fast-3", cropped_image_url="/data/uploads/crops/seg-fast-3.jpg"),
        ]

        session = AsyncMock()
        session_claim = Mock(scalar_one_or_none=Mock(return_value=meal))
        session_segments = Mock(
            scalars=Mock(return_value=Mock(all=Mock(return_value=segments)))
        )
        session.execute.side_effect = [session_claim, session_segments, asyncio.CancelledError]

        engine = SimpleNamespace(dispose=AsyncMock())

        class SessionContext:
            async def __aenter__(self):
                return session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        active_segments = 0
        max_active = 0
        slow_started = asyncio.Event()
        slow_done = asyncio.Event()
        siblings_started_while_slow = False

        async def slow_aware_match(segment, *_, **__) -> SimpleNamespace:
            nonlocal active_segments, max_active, siblings_started_while_slow
            active_segments += 1
            max_active = max(max_active, active_segments)

            if segment.id == "segment-slow":
                slow_started.set()
                await asyncio.sleep(0.02)
                slow_done.set()
                active_segments -= 1
                return _fake_match_result(segment.id)

            if slow_started.is_set() and not slow_done.is_set():
                siblings_started_while_slow = True

            await asyncio.sleep(0.002)
            active_segments -= 1
            return _fake_match_result(segment.id)

        session.add = Mock()
        session.add_all = Mock()
        session.commit = AsyncMock(side_effect=_noop_sleep)

        settings = SimpleNamespace(
            DATABASE_URL="postgresql+asyncpg://meal:pw@db:5432/meal",
            MATCHING_MODEL="google/gemini-embedding-2",
            SEGMENT_MATCH_PARALLELISM=2,
            TELEGRAM_CHAT_ID="999",
            BOT_POLL_INTERVAL=3.0,
        )
        bot = SimpleNamespace(send_message=AsyncMock())

        async def _write_message(*_args, **_kwargs) -> None:
            return None

        with (
            unittest.mock.patch.object(polling, "create_async_engine", return_value=engine),
            unittest.mock.patch.object(polling, "async_sessionmaker", return_value=Mock(return_value=SessionContext())),
            unittest.mock.patch.object(
                polling,
                "_is_rejection_threshold_reached",
                new=slow_aware_match,
            ),
            unittest.mock.patch.object(polling, "get_llm_client", return_value=object()),
            unittest.mock.patch.object(
                polling.matching_service,
                "persist_successful_match_rows",
                AsyncMock(),
            ),
            unittest.mock.patch.object(
                polling.reasoning_service,
                "run_reasoning_request",
                AsyncMock(return_value=({"action": "AUTO_CONFIRM", "meal_state": "READY_TO_WRITE"}, None)),
            ),
            unittest.mock.patch.object(
                polling.reasoning_service,
                "finalize_meal_from_reasoning",
                AsyncMock(return_value={"finalized": True, "meal_resolution": SimpleNamespace(meal_entries=[])}),
            ),
            unittest.mock.patch.object(
                polling,
                "format_match_completion_message",
                return_value="meal completed",
            ),
            unittest.mock.patch.object(polling, "_poll_sleep", side_effect=asyncio.CancelledError),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await polling.poll_and_match_food_segments(bot, settings, poll_interval=0.01)

        self.assertGreater(max_active, 1, "matching should allow siblings to run while one segment is slow")
        self.assertLessEqual(
            max_active,
            settings.SEGMENT_MATCH_PARALLELISM,
            "matching should not exceed configured per-meal fan-out",
        )
        self.assertTrue(
            siblings_started_while_slow,
            "fast sibling segment processing must start while slow segment is in-flight",
        )

    async def test_slow_group_finalizer_does_not_block_sibling_groups(self) -> None:
        from app.services import interview_service

        meal = SimpleNamespace(
            id="meal-finalizer-parallel",
            processing_status=MealProcessingStatus.INTERVIEWING,
            reasoning_state_json={
                "meal_reasoning": {
                    "food_groups": [
                        {
                            "group_id": "group-slow",
                            "group_label": "slow curry",
                            "primary_segment_id": "seg-slow",
                            "segment_ids": ["seg-slow"],
                        },
                        {
                            "group_id": "group-fast-1",
                            "group_label": "fast one",
                            "primary_segment_id": "seg-fast-1",
                            "segment_ids": ["seg-fast-1"],
                        },
                        {
                            "group_id": "group-fast-2",
                            "group_label": "fast two",
                            "primary_segment_id": "seg-fast-2",
                            "segment_ids": ["seg-fast-2"],
                        },
                    ]
                }
            },
            last_stage_started_at=None,
        )
        confirmation_items = [
            {
                "group_id": "group-slow",
                "primary_segment_id": "seg-slow",
                "segment_id": "seg-slow",
                "segment_ids": ["seg-slow"],
                "name": "slow curry",
                "source_type": "HOME",
                "portion_bucket": "STANDARD",
                "approval_status": "APPROVED",
            },
            {
                "group_id": "group-fast-1",
                "primary_segment_id": "seg-fast-1",
                "segment_id": "seg-fast-1",
                "segment_ids": ["seg-fast-1"],
                "name": "fast one",
                "source_type": "HOME",
                "portion_bucket": "STANDARD",
                "approval_status": "APPROVED",
            },
            {
                "group_id": "group-fast-2",
                "primary_segment_id": "seg-fast-2",
                "segment_id": "seg-fast-2",
                "segment_ids": ["seg-fast-2"],
                "name": "fast two",
                "source_type": "HOME",
                "portion_bucket": "STANDARD",
                "approval_status": "APPROVED",
            },
        ]
        segments = [
            SimpleNamespace(id="seg-slow", cropped_image_url="/data/uploads/crops/seg-slow.jpg", embedding=[0.1, 0.2, 0.3]),
            SimpleNamespace(id="seg-fast-1", cropped_image_url="/data/uploads/crops/seg-fast-1.jpg", embedding=[0.1, 0.2, 0.3]),
            SimpleNamespace(id="seg-fast-2", cropped_image_url="/data/uploads/crops/seg-fast-2.jpg", embedding=[0.1, 0.2, 0.3]),
        ]
        session = AsyncMock()
        session.add = Mock()

        active_groups = 0
        max_active = 0
        slow_started = asyncio.Event()
        slow_done = asyncio.Event()
        siblings_started_while_slow = False

        async def _slow_aware_finalize(*, group_input, **_kwargs):
            nonlocal active_groups, max_active, siblings_started_while_slow
            active_groups += 1
            max_active = max(max_active, active_groups)
            if group_input.group_id == "group-slow":
                slow_started.set()
                await asyncio.sleep(0.02)
                slow_done.set()
            else:
                if slow_started.is_set() and not slow_done.is_set():
                    siblings_started_while_slow = True
                await asyncio.sleep(0.002)
            active_groups -= 1
            return interview_service.GroupFinalizerOutcome(
                group_id=group_input.group_id,
                final_resolution=interview_service.final_resolution_from_confirmation(
                    item=group_input.confirmation_item,
                    segment=group_input.segment,
                ),
                finalized_confirmation_item=dict(group_input.confirmation_item),
                audit_state={"group_id": group_input.group_id, "status": "SUCCEEDED"},
            )

        with (
            unittest.mock.patch.object(
                interview_service,
                "get_settings",
                return_value=SimpleNamespace(
                    FINALIZER_GROUP_PARALLELISM=2,
                    FINALIZER_MODEL="google/gemini-3.1-flash-lite",
                ),
                create=True,
            ),
            unittest.mock.patch.object(
                interview_service,
                "_finalize_group_input",
                side_effect=_slow_aware_finalize,
                create=True,
            ),
            unittest.mock.patch.object(
                interview_service,
                "apply_final_meal_resolution",
                new=AsyncMock(return_value={"meal_entries": [], "food_visuals": [], "correction_events": []}),
            ),
        ):
            await interview_service.finalize_confirmed_interview(
                session=session,
                meal=meal,
                confirmation_items=confirmation_items,
                segments=segments,
            )

        self.assertGreater(max_active, 1)
        self.assertLessEqual(max_active, 2)
        self.assertTrue(siblings_started_while_slow)
