import asyncio
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from pathlib import Path

from app.models.meal_log import MealProcessingStatus


class MessageTemplateTests(unittest.TestCase):
    def test_ack_message_truncates_meal_id(self) -> None:
        from bot.messages import format_ack_message

        self.assertEqual(
            format_ack_message("12345678-abcd-efgh"),
            "📸 Received, processing… (ID: 12345678)",
        )

    def test_start_message(self) -> None:
        from bot.messages import format_start_message

        self.assertEqual(
            format_start_message(),
            "MealTracker bot is active. Snap a photo and I'll log your meal.",
        )

    def test_error_message(self) -> None:
        from bot.messages import format_error_message

        self.assertEqual(
            format_error_message(),
            "⚠️ Something went wrong processing your meal. I'll retry shortly.",
        )

    def test_soft_failure_message(self) -> None:
        from bot.messages import format_soft_failure_message

        self.assertEqual(
            format_soft_failure_message(),
            "⚠️ I couldn't confidently segment that meal photo. Please try another photo.",
        )

    def test_result_sentence_is_single_sentence(self) -> None:
        from bot.messages import format_result_sentence

        self.assertEqual(
            format_result_sentence(
                ["Pita Bread", "Chicken Curry", "Chicken Curry"],
                weak_labels={"Chicken Curry"},
            ),
            "I see 2 items: Pita Bread, maybe Chicken Curry.",
        )

    def test_match_completion_message_has_two_lines_per_item_and_known_totals_only(self) -> None:
        from bot.messages import CompletionItem, format_match_completion_message

        message = format_match_completion_message(
            [
                CompletionItem(
                    food_name="Daal Chawal",
                    portion_bucket="STANDARD",
                    identification_method="SIMILARITY",
                    is_verified=True,
                    calories=420.0,
                    protein_g=16.0,
                    carbs_g=68.0,
                    fat_g=12.0,
                ),
                CompletionItem(
                    food_name="Chicken Curry",
                    portion_bucket="STANDARD",
                    identification_method="SIMILARITY",
                    is_verified=False,
                    calories=None,
                    protein_g=12.0,
                    carbs_g=None,
                    fat_g=6.0,
                ),
            ]
        )

        expected = [
            "Daal Chawal | portion=STANDARD | method=SIMILARITY | verified=true",
            "Calories: 420 kcal | Protein: 16 g | Carbs: 68 g | Fat: 12 g",
            "Chicken Curry | portion=STANDARD | method=SIMILARITY | verified=false",
            "Protein: 12 g | Fat: 6 g",
            "Total | Calories: 420 kcal | Protein: 28 g | Carbs: 68 g | Fat: 18 g",
        ]

        self.assertEqual(message.splitlines(), expected)
        self.assertNotIn("default", message.lower())
        self.assertNotIn("assume", message.lower())
        self.assertNotIn("score", message.lower())

    def test_match_completion_message_omits_internal_debug_fields(self) -> None:
        from bot.messages import CompletionItem, format_match_completion_message

        message = format_match_completion_message(
            [
                CompletionItem(
                    food_name="Sample Item",
                    portion_bucket="STANDARD",
                    identification_method="SIMILARITY",
                    is_verified=True,
                    calories=200.0,
                ),
            ]
        )

        self.assertNotIn("vector", message)
        self.assertNotIn("embedding", message)
        self.assertNotIn("cropped_image_url", message)

    def test_recent_fix_targets_message_exposes_shortcuts(self) -> None:
        from bot.messages import format_recent_fix_targets

        message = format_recent_fix_targets(
            [
                {"id": "entry-1", "short_id": "entry-1", "food_name": "Dal", "quantity_display": "1 bowl"},
                {"id": "entry-2", "short_id": "entry-2", "food_name": "Rice", "quantity_display": None},
            ]
        )

        self.assertIn("Fix targets:", message)
        self.assertIn("1. entry-1 Dal (1 bowl)", message)
        self.assertIn("Use /fix 1 or /fix <id>.", message)

    def test_grounding_pending_message_mentions_handoff(self) -> None:
        from bot.messages import format_grounding_pending_message

        message = format_grounding_pending_message("12345678-abcd")

        self.assertIn("12345678", message)
        self.assertIn("queued the next step", message)


class HandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_replies_with_start_message(self) -> None:
        from bot.handlers import start
        from bot.messages import format_start_message

        reply_text = AsyncMock()
        update = SimpleNamespace(message=SimpleNamespace(chat=SimpleNamespace(id="999"), reply_text=reply_text))

        with patch("bot.handlers.get_settings", return_value=SimpleNamespace(TELEGRAM_CHAT_ID="999")):
            await start(update, SimpleNamespace())

        reply_text.assert_awaited_once_with(format_start_message())

    async def test_start_ignores_unpinned_chat(self) -> None:
        from bot.handlers import start

        reply_text = AsyncMock()
        update = SimpleNamespace(message=SimpleNamespace(chat=SimpleNamespace(id="111"), reply_text=reply_text))

        with patch("bot.handlers.get_settings", return_value=SimpleNamespace(TELEGRAM_CHAT_ID="999")):
            await start(update, SimpleNamespace())

        reply_text.assert_not_awaited()

    async def test_help_replies_with_shortcut_hint(self) -> None:
        from bot.handlers import help_command

        reply_text = AsyncMock()
        update = SimpleNamespace(message=SimpleNamespace(chat=SimpleNamespace(id="999"), reply_text=reply_text))

        with patch("bot.handlers.get_settings", return_value=SimpleNamespace(TELEGRAM_CHAT_ID="999")):
            await help_command(update, SimpleNamespace())

        reply_text.assert_awaited_once_with(
            "Send a meal photo via the iOS Shortcut. I'll process it and tell you what I found."
        )

    async def test_interview_callback_rejects_unpinned_chat_before_mutation(self) -> None:
        from bot.handlers import interview_callback

        callback_query = SimpleNamespace(
            data="confirm:meal-1",
            answer=AsyncMock(),
            message=SimpleNamespace(chat=SimpleNamespace(id="111"), reply_text=AsyncMock()),
        )
        update = SimpleNamespace(callback_query=callback_query, message=None)

        with patch("bot.handlers.get_settings", return_value=SimpleNamespace(TELEGRAM_CHAT_ID="999")):
            await interview_callback(update, SimpleNamespace())

        callback_query.answer.assert_awaited_once_with("Unauthorized chat.", show_alert=True)

    async def test_interview_text_confirm_finishes_confirmation_state(self) -> None:
        from bot.handlers import interview_text

        interview = SimpleNamespace(
            id="interview-1",
            meal_log_id="meal-1",
            is_active=True,
            current_prompt_payload={
                "roadmap_step": "CONFIRMATION",
                "interview_messages": [
                    {"payload": {"segment_id": "seg-1", "name": "Dal"}}
                ],
            },
        )
        meal = SimpleNamespace(id="meal-1", segments=[SimpleNamespace(id="seg-1")])
        session = AsyncMock()
        session.add = Mock()
        session.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=meal))
        engine = SimpleNamespace(dispose=AsyncMock())

        class SessionContext:
            async def __aenter__(self):
                return session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        reply_text = AsyncMock()
        update = SimpleNamespace(
            message=SimpleNamespace(chat=SimpleNamespace(id="999"), text="confirm", reply_text=reply_text),
            callback_query=None,
        )
        context = SimpleNamespace(bot_data={})

        with (
            patch("bot.handlers.get_settings", return_value=SimpleNamespace(TELEGRAM_CHAT_ID="999", DATABASE_URL="postgresql://db")),
            patch("bot.handlers._make_session_factory", return_value=(engine, Mock(return_value=SessionContext()))),
            patch("bot.handlers._load_active_interview", AsyncMock(return_value=interview)),
            patch("bot.handlers.interview_service.finalize_confirmed_interview", AsyncMock(return_value={"grounding_required": False})) as finalize,
        ):
            await interview_text(update, context)

        finalize.assert_awaited_once()
        self.assertFalse(interview.is_active)
        reply_text.assert_awaited_once_with("Meal confirmation saved.")
        session.commit.assert_awaited_once()
        engine.dispose.assert_awaited_once()

    async def test_interview_text_confirm_queues_grounding_handoff(self) -> None:
        from bot.handlers import interview_text
        from bot.messages import format_grounding_pending_message

        interview = SimpleNamespace(
            id="interview-2",
            meal_log_id="meal-2",
            is_active=True,
            state_key="CONFIRMATION",
            current_prompt_payload={
                "roadmap_step": "CONFIRMATION",
                "interview_messages": [
                    {"payload": {"segment_id": "seg-1", "name": "Protein Bar", "source_type": "PACKAGED"}}
                ],
            },
        )
        meal = SimpleNamespace(id="meal-2", segments=[SimpleNamespace(id="seg-1")])
        session = AsyncMock()
        session.add = Mock()
        session.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=meal))
        engine = SimpleNamespace(dispose=AsyncMock())

        class SessionContext:
            async def __aenter__(self):
                return session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        reply_text = AsyncMock()
        update = SimpleNamespace(
            message=SimpleNamespace(chat=SimpleNamespace(id="999"), text="confirm", reply_text=reply_text),
            callback_query=None,
        )
        context = SimpleNamespace(bot_data={})

        with (
            patch("bot.handlers.get_settings", return_value=SimpleNamespace(TELEGRAM_CHAT_ID="999", DATABASE_URL="postgresql://db")),
            patch("bot.handlers._make_session_factory", return_value=(engine, Mock(return_value=SessionContext()))),
            patch("bot.handlers._load_active_interview", AsyncMock(return_value=interview)),
            patch("bot.handlers.interview_service.finalize_confirmed_interview", AsyncMock(return_value={"grounding_required": True, "meal_entries": []})),
        ):
            await interview_text(update, context)

        self.assertTrue(interview.is_active)
        self.assertEqual(interview.state_key, "GROUNDING_PENDING")
        self.assertTrue(interview.current_prompt_payload["grounding_handoff_pending"])
        self.assertEqual(interview.current_prompt_payload["grounding_status"], "PENDING_HANDOFF")
        reply_text.assert_awaited_once_with(format_grounding_pending_message("meal-2"))
        session.commit.assert_awaited_once()
        engine.dispose.assert_awaited_once()


class OpenRouterContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_completion_forwards_multimodal_payload_and_extra_body(self) -> None:
        from app.services import llm_client

        create_call = AsyncMock(return_value=SimpleNamespace(model_dump=lambda: {"ok": True}))

        class FakeAsyncOpenAI:
            def __init__(self, *args: object, **kwargs: object) -> None:
                self.chat = SimpleNamespace(completions=SimpleNamespace(create=create_call))

        class FakeAsyncClient:
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

            async def aclose(self) -> None:
                return None

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "check"},
                    {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,abc"}},
                ],
            },
        ]
        response_format = {
            "type": "json_schema",
            "json_schema": {"name": "detect", "strict": True, "schema": {}},
        }
        extra_body = {"provider": {"reasoning": {"effort": "low"}}}

        with (
            patch.object(llm_client, "AsyncOpenAI", FakeAsyncOpenAI),
            patch.object(llm_client.httpx, "AsyncClient", FakeAsyncClient),
        ):
            client = llm_client.OpenRouterClient(api_key="token", base_url="https://example.test")
            result = await client.chat_completion(
                model="google/gemma-4-31b-it",
                messages=messages,
                response_format=response_format,
                extra_body=extra_body,
            )

        self.assertEqual(result, {"ok": True})
        create_call.assert_awaited_once_with(
            model="google/gemma-4-31b-it",
            messages=messages,
            response_format=response_format,
            tools=None,
            extra_body=extra_body,
        )


class SettingsContractTests(unittest.TestCase):
    def test_settings_ignore_unrelated_env_keys(self) -> None:
        from app.config import Settings

        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql+asyncpg://meal:pw@db:5432/meal",
                "INGEST_SECRET": "secret",
                "TELEGRAM_BOT_TOKEN": "token",
                "TELEGRAM_CHAT_ID": "999",
                "OPENROUTER_API_KEY": "router-key",
                "POSTGRES_PASSWORD": "extra-value",
                "API_HOST_PORT": "18000",
            },
            clear=True,
        ):
            settings = Settings()

        self.assertEqual(settings.OPENROUTER_API_KEY, "router-key")
        self.assertEqual(settings.TELEGRAM_CHAT_ID, "999")


class ImageServiceContractTests(unittest.TestCase):
    def test_save_segment_crop_uses_configured_upload_root(self) -> None:
        from app.services.image_service import save_segment_crop
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_path = tmp_path / "meal.jpg"
            Image.new("RGB", (10, 10), color="white").save(source_path, format="JPEG")

            crop_path = save_segment_crop(
                source_image_path=source_path,
                segment_id="segment-1",
                normalized_box=[0.0, 0.0, 1.0, 1.0],
                uploads_dir=tmp_path / "uploads",
            )

        self.assertEqual(crop_path, Path(tmp_dir) / "uploads" / "crops" / "segment-1.jpg")


class PollingTests(unittest.IsolatedAsyncioTestCase):
    async def test_poll_claims_pending_meal_and_acknowledges_it(self) -> None:
        from bot import polling

        meal = SimpleNamespace(
            id="12345678-abcd-efgh",
            processing_status=MealProcessingStatus.PENDING,
        )
        session = AsyncMock()
        session.execute.return_value = Mock(
            scalar_one_or_none=Mock(return_value=meal),
        )
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
            TELEGRAM_CHAT_ID="999",
            BOT_POLL_INTERVAL=3.0,
        )

        with (
            patch.object(polling, "create_async_engine", return_value=engine) as create_engine,
            patch.object(polling, "async_sessionmaker", return_value=session_factory) as sessionmaker,
            patch.object(polling, "format_ack_message", return_value="ack text") as format_ack_message,
            patch.object(
                polling.asyncio,
                "sleep",
                side_effect=asyncio.CancelledError,
            ),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await polling.poll_and_acknowledge(bot, settings, poll_interval=0.01)

        create_engine.assert_called_once_with(
            settings.DATABASE_URL,
            echo=False,
            pool_pre_ping=True,
        )
        sessionmaker.assert_called_once()
        bot.send_message.assert_awaited_once_with(chat_id="999", text="ack text")
        format_ack_message.assert_called_once_with(meal.id)
        session.commit.assert_awaited_once()
        engine.dispose.assert_awaited_once()
        self.assertEqual(meal.processing_status, MealProcessingStatus.DETECTING)

    async def test_poll_reraises_cancelled_error(self) -> None:
        from bot import polling

        session = AsyncMock()
        session.execute.side_effect = asyncio.CancelledError
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

        with (
            patch.object(polling, "create_async_engine", return_value=engine),
            patch.object(polling, "async_sessionmaker", return_value=session_factory),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await polling.poll_and_acknowledge(
                    SimpleNamespace(send_message=AsyncMock()),
                    settings,
                    poll_interval=0.01,
                )

        engine.dispose.assert_awaited_once()

    async def test_grounding_handoff_worker_acknowledges_without_closing_interview(self) -> None:
        from bot import polling
        from bot.messages import format_grounding_pending_message

        interview = SimpleNamespace(
            chat_id="999",
            meal_log_id="meal-1",
            is_active=True,
            state_key="GROUNDING_PENDING",
            current_prompt_payload={
                "roadmap_step": "GROUNDING_PENDING",
                "grounding_handoff_pending": True,
                "grounding_status": "PENDING_HANDOFF",
            },
            updated_at=object(),
        )
        meal = SimpleNamespace(
            id="meal-1",
            processing_status=MealProcessingStatus.INTERVIEWING,
            reasoning_state_json={
                "grounding_required": True,
                "grounding_status": "PENDING_HANDOFF",
                "confirmation_items": [{"segment_id": "seg-1", "name": "Protein Bar"}],
            },
        )
        session = AsyncMock()
        session.add = Mock()
        session.execute.return_value = Mock(
            scalars=Mock(return_value=Mock(all=Mock(return_value=[interview]))),
        )
        session.get = AsyncMock(return_value=meal)
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
            patch.object(polling.asyncio, "sleep", side_effect=asyncio.CancelledError),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await polling.poll_grounding_handoffs(bot, settings, poll_interval=0.01)

        bot.send_message.assert_awaited_once_with(
            chat_id="999",
            text=format_grounding_pending_message("meal-1"),
        )
        self.assertTrue(interview.is_active)
        self.assertFalse(interview.current_prompt_payload["grounding_handoff_pending"])
        self.assertEqual(interview.current_prompt_payload["grounding_status"], "HANDOFF_ACKNOWLEDGED")
        self.assertEqual(meal.processing_status, MealProcessingStatus.INTERVIEWING)
        self.assertEqual(meal.reasoning_state_json["grounding_status"], "HANDOFF_ACKNOWLEDGED")
        session.commit.assert_awaited_once()
        engine.dispose.assert_awaited_once()

    async def test_post_interview_grounding_worker_moves_meal_into_reasoning_stage(self) -> None:
        from bot import polling

        interview = SimpleNamespace(
            chat_id="999",
            meal_log_id="meal-1",
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
            id="meal-1",
            processing_status=MealProcessingStatus.INTERVIEWING,
            reasoning_state_json={
                "grounding_required": True,
                "grounding_status": "HANDOFF_ACKNOWLEDGED",
                "confirmation_items": [{"segment_id": "seg-1", "name": "Protein Bar"}],
            },
            recovery_attempt_count=0,
            last_stage_started_at=None,
        )
        session = AsyncMock()
        session.add = Mock()
        session.execute.return_value = Mock(
            scalars=Mock(return_value=Mock(all=Mock(return_value=[interview]))),
        )
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
            BOT_POLL_INTERVAL=3.0,
        )

        with (
            patch.object(polling, "create_async_engine", return_value=engine),
            patch.object(polling, "async_sessionmaker", return_value=session_factory),
            patch.object(polling.asyncio, "sleep", side_effect=asyncio.CancelledError),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await polling.poll_post_interview_grounding(
                    SimpleNamespace(),
                    settings,
                    poll_interval=0.01,
                )

        self.assertEqual(meal.processing_status, MealProcessingStatus.REASONING)
        self.assertEqual(meal.reasoning_state_json["grounding_status"], "AWAITING_GROUNDING")
        self.assertIsNotNone(meal.last_stage_started_at)
        self.assertTrue(interview.is_active)
        self.assertEqual(interview.current_prompt_payload["grounding_status"], "AWAITING_GROUNDING")
        self.assertEqual(interview.current_prompt_payload["grounding_consumer"], "poll_post_interview_grounding")
        session.commit.assert_awaited_once()
        engine.dispose.assert_awaited_once()

    async def test_poll_recovers_acknowledged_meal_state_after_commit_failure(self) -> None:
        from bot import polling

        meal = SimpleNamespace(
            id="12345678-abcd-efgh",
            processing_status=MealProcessingStatus.PENDING,
        )
        primary_session = AsyncMock()
        primary_session.execute.return_value = Mock(
            scalar_one_or_none=Mock(return_value=meal),
        )
        primary_session.commit.side_effect = RuntimeError("db down")

        recovery_session = AsyncMock()
        recovery_session.merge = AsyncMock()

        engine = SimpleNamespace(dispose=AsyncMock())

        class SessionContext:
            def __init__(self, session):
                self.session = session

            async def __aenter__(self):
                return self.session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        session_factory = Mock(side_effect=[SessionContext(primary_session), SessionContext(recovery_session)])
        bot = SimpleNamespace(send_message=AsyncMock())
        settings = SimpleNamespace(
            DATABASE_URL="postgresql+asyncpg://meal:pw@db:5432/meal",
            TELEGRAM_CHAT_ID="999",
            BOT_POLL_INTERVAL=3.0,
        )

        with (
            patch.object(polling, "create_async_engine", return_value=engine),
            patch.object(polling, "async_sessionmaker", return_value=session_factory),
            patch.object(
                polling.asyncio,
                "sleep",
                side_effect=asyncio.CancelledError,
            ),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await polling.poll_and_acknowledge(bot, settings, poll_interval=0.01)

        bot.send_message.assert_awaited_once_with(chat_id="999", text=polling.format_ack_message(meal.id))
        recovery_session.merge.assert_awaited_once()
        recovery_session.commit.assert_awaited_once()
        self.assertEqual(meal.processing_status, MealProcessingStatus.DETECTING)

    async def test_poll_detects_meal_and_marks_skipped_non_food_without_result_message(self) -> None:
        from bot import polling

        meal = SimpleNamespace(
            id="12345678-abcd-efgh",
            image_url="s3://bucket/photo.jpg",
            processing_status=MealProcessingStatus.DETECTING,
        )
        session = AsyncMock()
        session.execute.return_value = Mock(
            scalar_one_or_none=Mock(return_value=meal),
        )
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
            DETECT_MODEL="google/gemma-4-31b-it",
            BOT_POLL_INTERVAL=3.0,
        )

        with (
            patch.object(polling, "create_async_engine", return_value=engine),
            patch.object(polling, "async_sessionmaker", return_value=session_factory),
            patch.object(
                polling,
                "detect_food_photo",
                AsyncMock(
                    return_value={
                        "next_action": "skip",
                        "is_food": False,
                        "confidence": 0.91,
                    }
                ),
            ),
            patch.object(
                polling.asyncio,
                "sleep",
                side_effect=asyncio.CancelledError,
            ),
            patch.object(
                polling,
                "get_llm_client",
                return_value=SimpleNamespace(chat_completion=AsyncMock()),
            ),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await polling.poll_and_detect_food(bot, settings, poll_interval=0.01)

        session.commit.assert_awaited_once()
        self.assertEqual(meal.processing_status, MealProcessingStatus.COMPLETED)
        bot.send_message.assert_not_awaited()

    async def test_poll_detects_food_and_advances_to_segmenting(self) -> None:
        from bot import polling

        meal = SimpleNamespace(
            id="12345678-abcd-efgh",
            image_url="s3://bucket/photo.jpg",
            processing_status=MealProcessingStatus.DETECTING,
        )
        session = AsyncMock()
        session.execute.return_value = Mock(
            scalar_one_or_none=Mock(return_value=meal),
        )
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
            DETECT_MODEL="google/gemma-4-31b-it",
            BOT_POLL_INTERVAL=3.0,
        )

        with (
            patch.object(polling, "create_async_engine", return_value=engine),
            patch.object(polling, "async_sessionmaker", return_value=session_factory),
            patch.object(
                polling,
                "detect_food_photo",
                AsyncMock(
                    return_value={
                        "next_action": "segment",
                        "is_food": True,
                        "confidence": 0.95,
                    }
                ),
            ),
            patch.object(
                polling.asyncio,
                "sleep",
                side_effect=asyncio.CancelledError,
            ),
            patch.object(
                polling,
                "get_llm_client",
                return_value=SimpleNamespace(chat_completion=AsyncMock()),
            ),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await polling.poll_and_detect_food(bot, settings, poll_interval=0.01)

        session.commit.assert_awaited_once()
        self.assertEqual(meal.processing_status, MealProcessingStatus.SEGMENTING)
        bot.send_message.assert_not_awaited()

    async def test_poll_segments_creates_crops_and_labels_then_completes(self) -> None:
        from bot import polling

        meal = SimpleNamespace(
            id="12345678-abcd-efgh",
            image_url="/data/uploads/meals/12345678-abcd-efgh.jpg",
            processing_status=MealProcessingStatus.SEGMENTING,
        )
        session = AsyncMock()
        session.add_all = Mock()
        session.execute.return_value = Mock(
            scalar_one_or_none=Mock(return_value=meal),
        )
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
            SEGMENT_MODEL="google/gemini-3-flash-preview",
            SEGMENT_RETRY_MODEL="google/gemini-3.5-flash",
            LABEL_MODEL="google/gemini-3-flash-preview",
            VISION_MAX_SEGMENTS=8,
            UPLOADS_DIR=Path("/data/uploads"),
            TELEGRAM_CHAT_ID="999",
            BOT_POLL_INTERVAL=3.0,
        )

        with (
            patch.object(polling, "create_async_engine", return_value=engine),
            patch.object(polling, "async_sessionmaker", return_value=session_factory),
            patch.object(
                polling.asyncio,
                "sleep",
                side_effect=asyncio.CancelledError,
            ),
            patch.object(
                polling,
                "segment_food_photo_with_retry",
                AsyncMock(
                    return_value=[
                        SimpleNamespace(box_2d=[0.0, 0.0, 0.6, 0.6], confidence=0.9),
                        SimpleNamespace(box_2d=[0.6, 0.6, 1.0, 1.0], confidence=0.9),
                    ],
                ),
            ),
            patch.object(
                polling,
                "save_segment_crop",
                side_effect=[
                    Path("/data/uploads/crops/aaa.jpg"),
                    Path("/data/uploads/crops/bbb.jpg"),
                ],
            ),
            patch.object(
                polling,
                "label_food_segment",
                AsyncMock(side_effect=["pita bread", "mixed vegetables"]),
            ),
            patch.object(
                polling,
                "get_llm_client",
                return_value=SimpleNamespace(chat_completion=AsyncMock()),
            ),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await polling.poll_and_segment_food(bot, settings, poll_interval=0.01)

        session.add_all.assert_called_once()
        self.assertEqual(len(session.add_all.call_args.args[0]), 2)
        for segment in session.add_all.call_args.args[0]:
            self.assertTrue(segment.bounding_box)
            self.assertIn(segment.cropped_image_url, {"/data/uploads/crops/aaa.jpg", "/data/uploads/crops/bbb.jpg"})
            self.assertIsNotNone(segment.label)
        self.assertEqual(meal.processing_status, MealProcessingStatus.EMBEDDING)
        bot.send_message.assert_not_awaited()

    async def test_poll_segments_keeps_embedding_handoff_when_message_send_fails(self) -> None:
        from bot import polling

        meal = SimpleNamespace(
            id="12345678-abcd-efgh",
            image_url="/data/uploads/meals/12345678-abcd-efgh.jpg",
            processing_status=MealProcessingStatus.SEGMENTING,
        )
        session = AsyncMock()
        session.add_all = Mock()
        session.execute.return_value = Mock(
            scalar_one_or_none=Mock(return_value=meal),
        )
        engine = SimpleNamespace(dispose=AsyncMock())

        class SessionContext:
            async def __aenter__(self):
                return session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        session_factory = Mock(return_value=SessionContext())
        bot = SimpleNamespace(send_message=AsyncMock(side_effect=RuntimeError("telegram down")))
        settings = SimpleNamespace(
            DATABASE_URL="postgresql+asyncpg://meal:pw@db:5432/meal",
            SEGMENT_MODEL="google/gemini-3-flash-preview",
            SEGMENT_RETRY_MODEL="google/gemini-3.5-flash",
            LABEL_MODEL="google/gemini-3-flash-preview",
            VISION_MAX_SEGMENTS=8,
            UPLOADS_DIR=Path("/data/uploads"),
            TELEGRAM_CHAT_ID="999",
            BOT_POLL_INTERVAL=3.0,
        )

        with (
            patch.object(polling, "create_async_engine", return_value=engine),
            patch.object(polling, "async_sessionmaker", return_value=session_factory),
            patch.object(
                polling.asyncio,
                "sleep",
                side_effect=asyncio.CancelledError,
            ),
            patch.object(
                polling,
                "segment_food_photo_with_retry",
                AsyncMock(return_value=[SimpleNamespace(box_2d=[0.0, 0.0, 0.6, 0.6], confidence=0.9)]),
            ),
            patch.object(
                polling,
                "save_segment_crop",
                return_value=Path("/data/uploads/crops/aaa.jpg"),
            ),
            patch.object(
                polling,
                "label_food_segment",
                AsyncMock(return_value="pita bread"),
            ),
            patch.object(
                polling,
                "get_llm_client",
                return_value=SimpleNamespace(chat_completion=AsyncMock()),
            ),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await polling.poll_and_segment_food(bot, settings, poll_interval=0.01)

        self.assertEqual(meal.processing_status, MealProcessingStatus.EMBEDDING)
        session.commit.assert_awaited_once()
        bot.send_message.assert_not_awaited()

    async def test_poll_segments_rejects_empty_segments_with_no_result_message(self) -> None:
        from bot import polling

        meal = SimpleNamespace(
            id="12345678-abcd-efgh",
            image_url="/data/uploads/meals/12345678-abcd-efgh.jpg",
            processing_status=MealProcessingStatus.SEGMENTING,
        )
        session = AsyncMock()
        session.execute.return_value = Mock(
            scalar_one_or_none=Mock(
                side_effect=lambda: (
                    meal if meal.processing_status == MealProcessingStatus.SEGMENTING else None
                )
            ),
        )
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
            SEGMENT_MODEL="google/gemini-3-flash-preview",
            SEGMENT_RETRY_MODEL="google/gemini-3.5-flash",
            VISION_MAX_SEGMENTS=8,
            UPLOADS_DIR=Path("/data/uploads"),
            TELEGRAM_CHAT_ID="999",
            BOT_POLL_INTERVAL=3.0,
        )

        with (
            patch.object(polling, "create_async_engine", return_value=engine),
            patch.object(polling, "async_sessionmaker", return_value=session_factory),
            patch.object(
                polling.asyncio,
                "sleep",
                side_effect=asyncio.CancelledError,
            ),
            patch.object(
                polling,
                "segment_food_photo_with_retry",
                AsyncMock(return_value=[]),
            ),
            patch.object(
                polling,
                "get_llm_client",
                return_value=SimpleNamespace(chat_completion=AsyncMock()),
            ),
            patch.object(polling, "label_food_segment", AsyncMock()),
            patch.object(polling, "format_soft_failure_message", return_value="soft fail"),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await polling.poll_and_segment_food(bot, settings, poll_interval=0.01)

        session.add_all.assert_not_called()
        session.commit.assert_awaited_once()
        self.assertEqual(meal.processing_status, MealProcessingStatus.FAILED)
        bot.send_message.assert_awaited_once_with(chat_id="999", text="soft fail")

    async def test_poll_match_sends_completion_message_for_completed_meal_after_commit(self) -> None:
        from bot import polling

        segment = SimpleNamespace(
            id="segment-1",
            cropped_image_url="/data/uploads/crops/seg-1.jpg",
            embedding=[0.1] * 1536,
        )
        meal = SimpleNamespace(
            id="12345678-abcd-efgh",
            processing_status=MealProcessingStatus.MATCHING,
        )
        session = AsyncMock()
        meal_result = Mock(scalar_one_or_none=Mock(return_value=meal))
        segments_result = Mock(scalars=Mock(return_value=Mock(all=Mock(return_value=[segment]))))
        session.execute.side_effect = [meal_result, segments_result]
        session.add = Mock()
        session.add_all = Mock()

        order: list[str] = []

        async def _commit() -> None:
            order.append("commit")
        session.commit = AsyncMock(side_effect=_commit)

        async def _send_message(*, chat_id: str, text: str) -> None:
            order.append("send")

        bot = SimpleNamespace(send_message=AsyncMock(side_effect=_send_message))
        engine = SimpleNamespace(dispose=AsyncMock())
        settings = SimpleNamespace(
            DATABASE_URL="postgresql+asyncpg://meal:pw@db:5432/meal",
            MATCHING_MODEL="google/gemini-embedding-2-preview",
            TELEGRAM_CHAT_ID="999",
            BOT_POLL_INTERVAL=3.0,
        )

        match_result = SimpleNamespace(
            food_visual_id="visual-1",
            food_item_id="item-1",
            is_match=True,
            is_below_threshold=False,
            food_visual=SimpleNamespace(
                food_item=SimpleNamespace(
                    name="Daal Chawal",
                    calories=420.0,
                    protein_g=16.0,
                    carbs_g=68.0,
                    fat_g=12.0,
                    is_verified=True,
                )
            ),
            query_embedding=[0.1] * 1536,
            similarity=0.92,
        )

        class SessionContext:
            async def __aenter__(self):
                return session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        session_factory = Mock(return_value=SessionContext())

        async def _finalize_meal(**_kwargs):
            meal.processing_status = MealProcessingStatus.COMPLETED
            await session.commit()
            return {
                "finalized": True,
                "meal_resolution": SimpleNamespace(
                    meal_entries=[
                        SimpleNamespace(
                            segment_id="segment-1",
                            portion_bucket="STANDARD",
                            quantity_display=None,
                        )
                    ]
                ),
            }

        with (
            patch.object(polling, "create_async_engine", return_value=engine),
            patch.object(polling, "async_sessionmaker", return_value=session_factory),
            patch.object(
                polling,
                "_is_rejection_threshold_reached",
                new=AsyncMock(return_value=match_result),
            ),
            patch.object(
                polling.matching_service,
                "persist_successful_match_rows",
                AsyncMock(),
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
                AsyncMock(side_effect=_finalize_meal),
            ),
            patch.object(
                polling,
                "format_match_completion_message",
                return_value="meal completed",
            ) as formatter,
            patch.object(polling.asyncio, "sleep", side_effect=asyncio.CancelledError),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await polling.poll_and_match_food_segments(bot, settings, poll_interval=0.01)

        self.assertIn("commit", order)
        self.assertIn("send", order)
        self.assertLess(order.index("commit"), order.index("send"))
        self.assertEqual(meal.processing_status, MealProcessingStatus.COMPLETED)
        self.assertEqual(session.commit.await_count, 2)
        bot.send_message.assert_awaited_once_with(chat_id="999", text="meal completed")
        self.assertEqual(formatter.call_count, 1)
        completion_items = list(formatter.call_args[0][0]) if formatter.call_args else []
        self.assertEqual(len(completion_items), 1)
        first_item = completion_items[0]
        self.assertEqual(first_item.food_name, "Daal Chawal")
        self.assertEqual(first_item.identification_method, "AUTO_CONFIRM")
        self.assertTrue(first_item.is_verified)

    async def test_poll_match_send_failure_does_not_rollback_completed_transition(self) -> None:
        from bot import polling

        segment = SimpleNamespace(
            id="segment-1",
            cropped_image_url="/data/uploads/crops/seg-1.jpg",
            embedding=[0.2] * 1536,
        )
        meal = SimpleNamespace(
            id="12345678-abcd-efgh",
            processing_status=MealProcessingStatus.MATCHING,
        )
        session = AsyncMock()
        meal_result = Mock(scalar_one_or_none=Mock(return_value=meal))
        segments_result = Mock(scalars=Mock(return_value=Mock(all=Mock(return_value=[segment]))))
        session.execute.side_effect = [meal_result, segments_result]
        session.add = Mock()
        session.add_all = Mock()
        order: list[str] = []

        async def _commit() -> None:
            order.append("commit")
        session.commit = AsyncMock(side_effect=_commit)
        engine = SimpleNamespace(dispose=AsyncMock())

        async def _send_message(*, chat_id: str, text: str) -> None:
            order.append("send")
            raise RuntimeError("telegram down")

        bot = SimpleNamespace(send_message=AsyncMock(side_effect=_send_message))
        settings = SimpleNamespace(
            DATABASE_URL="postgresql+asyncpg://meal:pw@db:5432/meal",
            MATCHING_MODEL="google/gemini-embedding-2-preview",
            TELEGRAM_CHAT_ID="999",
            BOT_POLL_INTERVAL=3.0,
        )

        match_result = SimpleNamespace(
            food_visual_id="visual-1",
            food_item_id="item-1",
            is_match=True,
            is_below_threshold=False,
            food_visual=SimpleNamespace(
                food_item=SimpleNamespace(
                    name="Daal Chawal",
                    calories=420.0,
                    protein_g=16.0,
                    carbs_g=68.0,
                    fat_g=12.0,
                    is_verified=True,
                )
            ),
            query_embedding=[0.2] * 1536,
            similarity=0.95,
        )

        class SessionContext:
            async def __aenter__(self):
                return session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        session_factory = Mock(return_value=SessionContext())

        async def _finalize_meal(**_kwargs):
            meal.processing_status = MealProcessingStatus.COMPLETED
            await session.commit()
            return {
                "finalized": True,
                "meal_resolution": SimpleNamespace(
                    meal_entries=[
                        SimpleNamespace(
                            segment_id="segment-1",
                            portion_bucket="STANDARD",
                            quantity_display=None,
                        )
                    ]
                ),
            }

        with (
            patch.object(polling, "create_async_engine", return_value=engine),
            patch.object(polling, "async_sessionmaker", return_value=session_factory),
            patch.object(
                polling,
                "_is_rejection_threshold_reached",
                new=AsyncMock(return_value=match_result),
            ),
            patch.object(
                polling.matching_service,
                "persist_successful_match_rows",
                AsyncMock(),
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
                AsyncMock(side_effect=_finalize_meal),
            ),
            patch.object(polling, "format_match_completion_message", return_value="meal completed"),
            patch.object(polling.asyncio, "sleep", side_effect=asyncio.CancelledError),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await polling.poll_and_match_food_segments(bot, settings, poll_interval=0.01)

        self.assertEqual(meal.processing_status, MealProcessingStatus.COMPLETED)
        self.assertEqual(order, ["commit", "commit", "send"])
        self.assertEqual(session.commit.await_count, 2)

    async def test_poll_match_tracks_recent_entries_for_fix_followups(self) -> None:
        from bot import polling

        segment = SimpleNamespace(
            id="segment-1",
            cropped_image_url="/data/uploads/crops/seg-1.jpg",
            embedding=[0.1] * 1536,
        )
        meal = SimpleNamespace(
            id="12345678-abcd-efgh",
            processing_status=MealProcessingStatus.MATCHING,
        )
        session = AsyncMock()
        meal_result = Mock(scalar_one_or_none=Mock(return_value=meal))
        segments_result = Mock(scalars=Mock(return_value=Mock(all=Mock(return_value=[segment]))))
        session.execute.side_effect = [meal_result, segments_result]
        session.add = Mock()
        session.add_all = Mock()
        session.commit = AsyncMock()
        engine = SimpleNamespace(dispose=AsyncMock())

        class SessionContext:
            async def __aenter__(self):
                return session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        session_factory = Mock(return_value=SessionContext())
        bot = SimpleNamespace(send_message=AsyncMock())
        bot_data: dict[str, object] = {}
        settings = SimpleNamespace(
            DATABASE_URL="postgresql+asyncpg://meal:pw@db:5432/meal",
            MATCHING_MODEL="google/gemini-embedding-2-preview",
            TELEGRAM_CHAT_ID="999",
            BOT_POLL_INTERVAL=3.0,
        )

        match_result = SimpleNamespace(
            food_visual_id="visual-1",
            food_item_id="item-1",
            is_match=True,
            is_below_threshold=False,
            food_visual=SimpleNamespace(
                food_item=SimpleNamespace(
                    name="Daal Chawal",
                    calories=420.0,
                    protein_g=16.0,
                    carbs_g=68.0,
                    fat_g=12.0,
                    is_verified=True,
                )
            ),
            query_embedding=[0.1] * 1536,
            similarity=0.92,
        )

        async def _finalize_meal(**_kwargs):
            meal.processing_status = MealProcessingStatus.COMPLETED
            await session.commit()
            return {
                "finalized": True,
                "meal_resolution": SimpleNamespace(
                    meal_entries=[
                        SimpleNamespace(
                            id="entry-1",
                            segment_id="segment-1",
                            portion_bucket="STANDARD",
                            quantity_display="1 bowl",
                        )
                    ]
                ),
            }

        with (
            patch.object(polling, "create_async_engine", return_value=engine),
            patch.object(polling, "async_sessionmaker", return_value=session_factory),
            patch.object(
                polling,
                "_is_rejection_threshold_reached",
                new=AsyncMock(return_value=match_result),
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
                AsyncMock(side_effect=_finalize_meal),
            ),
            patch.object(polling.asyncio, "sleep", side_effect=asyncio.CancelledError),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await polling.poll_and_match_food_segments(bot, settings, poll_interval=0.01, bot_data=bot_data)

        self.assertEqual(bot_data["recent_entries"][0]["id"], "entry-1")
        sent_text = bot.send_message.await_args.kwargs["text"]
        self.assertIn("Fix targets:", sent_text)
        self.assertIn("/fix 1", sent_text)

class MainWiringTests(unittest.IsolatedAsyncioTestCase):
    async def test_post_init_starts_background_polling_task(self) -> None:
        from bot import main as bot_main

        application = SimpleNamespace(bot=object(), bot_data={})
        settings = SimpleNamespace(BOT_POLL_INTERVAL=3.0)
        fake_task = object()
        created_coroutines: list[object] = []

        def create_task(coroutine):
            created_coroutines.append(coroutine)
            coroutine.close()
            return fake_task

        with (
            patch.object(bot_main, "get_settings", return_value=settings),
            patch.object(bot_main, "poll_and_acknowledge", new=AsyncMock()) as poll_and_acknowledge,
            patch.object(bot_main, "poll_and_detect_food", new=AsyncMock()) as poll_and_detect_food,
            patch.object(bot_main, "poll_and_segment_food", new=AsyncMock()) as poll_and_segment_food,
            patch.object(bot_main, "poll_and_embed_food_segments", new=AsyncMock()) as poll_and_embed_food_segments,
            patch.object(bot_main, "poll_and_match_food_segments", new=AsyncMock()) as poll_and_match_food_segments,
            patch.object(bot_main, "poll_grounding_handoffs", new=AsyncMock()) as poll_grounding_handoffs,
            patch.object(bot_main, "poll_post_interview_grounding", new=AsyncMock()) as poll_post_interview_grounding,
            patch.object(bot_main, "poll_interview_reminders", new=AsyncMock()) as poll_interview_reminders,
            patch.object(bot_main.asyncio, "create_task", side_effect=create_task) as create_task_mock,
        ):
            await bot_main.post_init(application)

        poll_and_acknowledge.assert_called_once_with(
            application.bot,
            settings,
            settings.BOT_POLL_INTERVAL,
        )
        poll_and_detect_food.assert_called_once_with(
            application.bot,
            settings,
            settings.BOT_POLL_INTERVAL,
        )
        poll_and_segment_food.assert_called_once_with(
            application.bot,
            settings,
            settings.BOT_POLL_INTERVAL,
        )
        poll_and_embed_food_segments.assert_called_once_with(
            application.bot,
            settings,
            settings.BOT_POLL_INTERVAL,
        )
        poll_and_match_food_segments.assert_called_once_with(
            application.bot,
            settings,
            settings.BOT_POLL_INTERVAL,
            application.bot_data,
        )
        poll_grounding_handoffs.assert_called_once_with(
            application.bot,
            settings,
            settings.BOT_POLL_INTERVAL,
        )
        poll_post_interview_grounding.assert_called_once_with(
            application.bot,
            settings,
            settings.BOT_POLL_INTERVAL,
        )
        poll_interview_reminders.assert_called_once_with(
            application.bot,
            settings,
            settings.BOT_POLL_INTERVAL,
        )
        create_task_mock.assert_called()
        self.assertEqual(len(created_coroutines), 8)
        self.assertIs(application.bot_data["poll_task"], fake_task)
        self.assertIs(application.bot_data["detect_task"], fake_task)
        self.assertIs(application.bot_data["segment_task"], fake_task)
        self.assertIs(application.bot_data["embed_task"], fake_task)
        self.assertIs(application.bot_data["match_task"], fake_task)
        self.assertIs(application.bot_data["interview_reminder_task"], fake_task)
        self.assertIs(application.bot_data["grounding_handoff_task"], fake_task)
        self.assertIs(application.bot_data["post_interview_grounding_task"], fake_task)

    async def test_post_shutdown_cancels_background_tasks(self) -> None:
        from bot import main as bot_main

        class FakeTask:
            def __init__(self) -> None:
                self.cancel = Mock()
                self.awaited = False

            async def wait(self) -> None:
                self.awaited = True

            def __await__(self):
                return self.wait().__await__()

        poll_task = FakeTask()
        detect_task = FakeTask()
        segment_task = FakeTask()
        grounding_handoff_task = FakeTask()
        post_interview_grounding_task = FakeTask()
        application = SimpleNamespace(
            bot_data={
                "poll_task": poll_task,
                "detect_task": detect_task,
                "segment_task": segment_task,
                "grounding_handoff_task": grounding_handoff_task,
                "post_interview_grounding_task": post_interview_grounding_task,
            }
        )

        await bot_main.post_shutdown(application)

        poll_task.cancel.assert_called_once_with()
        self.assertTrue(poll_task.awaited)
        detect_task.cancel.assert_called_once_with()
        self.assertTrue(detect_task.awaited)
        segment_task.cancel.assert_called_once_with()
        self.assertTrue(segment_task.awaited)
        grounding_handoff_task.cancel.assert_called_once_with()
        self.assertTrue(grounding_handoff_task.awaited)
        post_interview_grounding_task.cancel.assert_called_once_with()
        self.assertTrue(post_interview_grounding_task.awaited)

    def test_main_builds_application_and_runs_polling(self) -> None:
        from bot import main as bot_main

        settings = SimpleNamespace(TELEGRAM_BOT_TOKEN="token")
        builder = Mock()
        application = Mock()

        builder.token.return_value = builder
        builder.concurrent_updates.return_value = builder
        builder.post_init.return_value = builder
        builder.post_shutdown.return_value = builder
        builder.build.return_value = application

        with (
            patch.object(bot_main, "get_settings", return_value=settings),
            patch.object(bot_main.Application, "builder", return_value=builder),
            patch.object(bot_main, "CommandHandler", side_effect=lambda name, fn: (name, fn)),
        ):
            bot_main.main()

        builder.token.assert_called_once_with("token")
        builder.concurrent_updates.assert_called_once_with(False)
        builder.post_init.assert_called_once_with(bot_main.post_init)
        builder.post_shutdown.assert_called_once_with(bot_main.post_shutdown)
        self.assertEqual(application.add_handler.call_count, 4)
        application.run_polling.assert_called_once_with(
            allowed_updates=bot_main.Update.ALL_TYPES,
            drop_pending_updates=True,
        )
