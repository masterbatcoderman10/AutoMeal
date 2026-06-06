import asyncio
import hashlib
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from pathlib import Path

from app.models.meal_log import MealProcessingStatus
from app.services.interview_schema import InterviewTurnResult, InterviewTurnValidationError


def _test_callback_token(value: str) -> str:
    return hashlib.blake2s(value.encode("utf-8"), digest_size=4).hexdigest()


class _ActiveInterviewQueryResult:
    def __init__(self, interviews):
        self._interviews = list(interviews)

    def scalar_one_or_none(self):
        return self._interviews[0] if self._interviews else None

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._interviews))


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
                    quantity_label="0.63x",
                    calories=None,
                    protein_g=12.0,
                    carbs_g=None,
                    fat_g=6.0,
                ),
            ]
        )

        expected = [
            "Daal Chawal | ~standard portion | method=SIMILARITY | verified=true",
            "Calories: 420 kcal | Protein: 16 g | Carbs: 68 g | Fat: 12 g",
            "Chicken Curry | ~standard portion | method=SIMILARITY | verified=false",
            "Protein: 12 g | Fat: 6 g",
            "Total | Calories: 420 kcal | Protein: 28 g | Carbs: 68 g | Fat: 18 g",
        ]

        self.assertEqual(message.splitlines(), expected)
        self.assertNotIn("default", message.lower())
        self.assertNotIn("assume", message.lower())
        self.assertNotIn("score", message.lower())
        self.assertNotIn("0.63x", message)

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

    def test_match_completion_message_flags_degraded_save_without_nutrition(self) -> None:
        from bot.messages import CompletionItem, format_match_completion_message

        message = format_match_completion_message(
            [
                CompletionItem(
                    food_name="Chicken Karahi",
                    portion_bucket="STANDARD",
                    identification_method="INTERVIEW",
                    is_verified=False,
                ),
                CompletionItem(
                    food_name="Bran Flatbread",
                    portion_bucket="STANDARD",
                    identification_method="INTERVIEW",
                    is_verified=False,
                ),
            ]
        )

        lines = message.splitlines()
        self.assertEqual(
            lines[0],
            "Meal saved, but I couldn't finalize nutrition yet. I logged the items without nutrition and marked them unverified.",
        )
        self.assertEqual(lines[2], "Chicken Karahi | ~standard portion | method=INTERVIEW | verified=false")
        self.assertEqual(lines[3], "Nutrition: unavailable")
        self.assertNotIn("Total |", message)

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
            patch("bot.handlers._resolve_active_interview_for_text", AsyncMock(return_value=(interview, None))),
            patch("bot.handlers.interview_service.finalize_confirmed_interview", AsyncMock(return_value={"grounding_required": False})) as finalize,
        ):
            await interview_text(update, context)

        finalize.assert_awaited_once()
        self.assertFalse(interview.is_active)
        reply_text.assert_awaited_once_with("Meal confirmation saved.")
        session.commit.assert_awaited_once()
        engine.dispose.assert_awaited_once()

    async def test_interview_text_confirm_finalizes_deterministic_confirmation_state(self) -> None:
        from bot.handlers import interview_text

        interview = SimpleNamespace(
            id="interview-deterministic-confirm",
            meal_log_id="meal-deterministic-confirm",
            is_active=True,
            state_key="CONFIRMATION",
            current_prompt_payload={
                "meal_id": "meal-deterministic-confirm",
                "session_mode": "MEAL_INTERVIEW",
                "roadmap_step": "CONFIRMATION",
                "question_order": ["group_1:identity"],
                "questions_by_id": {
                    "group_1:identity": {
                        "question_id": "group_1:identity",
                        "group_id": "group_1",
                        "primary_segment_id": "seg-1",
                        "segment_ids": ["seg-1"],
                        "question_kind": "IDENTITY",
                        "answer_type": "single_choice",
                        "required": True,
                        "label": "Vegetable and Egg Curry",
                        "choices": [{"choice_id": "bottle_gourd_lauki", "label": "bottle gourd (lauki)"}],
                    }
                },
                "answers_by_question_id": {
                    "group_1:identity": {
                        "question_id": "group_1:identity",
                        "group_id": "group_1",
                        "primary_segment_id": "seg-1",
                        "segment_ids": ["seg-1"],
                        "question_kind": "IDENTITY",
                        "answer_type": "single_choice",
                        "required": True,
                        "name": "Egg curry with bottle gourd",
                    }
                },
                "pending_question_ids": [],
                "remaining_required_question_ids": [],
                "confirmation_items": [
                    {
                        "group_id": "group_1",
                        "segment_id": "seg-1",
                        "primary_segment_id": "seg-1",
                        "segment_ids": ["seg-1"],
                        "name": "Egg curry with bottle gourd",
                        "source_type": "HOME",
                        "portion_bucket": "STANDARD",
                    }
                ],
            },
        )
        meal = SimpleNamespace(id="meal-deterministic-confirm", segments=[SimpleNamespace(id="seg-1")])
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
            patch("bot.handlers._resolve_active_interview_for_text", AsyncMock(return_value=(interview, None))),
            patch("bot.handlers.interview_service.finalize_confirmed_interview", AsyncMock(return_value={"grounding_required": False})) as finalize,
        ):
            await interview_text(update, context)

        finalize.assert_awaited_once()
        self.assertFalse(interview.is_active)
        reply_text.assert_awaited_once_with("Meal confirmation saved.")
        session.commit.assert_awaited_once()
        engine.dispose.assert_awaited_once()

    async def test_interview_text_confirm_replaces_visible_fix_targets_with_current_meal(self) -> None:
        from bot.handlers import interview_text

        interview = SimpleNamespace(
            id="interview-confirm-fix-targets",
            meal_log_id="meal-confirm-fix-targets",
            is_active=True,
            state_key="CONFIRMATION",
            current_prompt_payload={
                "roadmap_step": "CONFIRMATION",
                "confirmation_items": [
                    {
                        "group_id": "group-1",
                        "segment_id": "seg-1",
                        "primary_segment_id": "seg-1",
                        "segment_ids": ["seg-1"],
                        "name": "Dal",
                        "source_type": "HOME",
                        "portion_bucket": "STANDARD",
                    }
                ],
                "interview_messages": [],
            },
        )
        meal = SimpleNamespace(id="meal-confirm-fix-targets", segments=[SimpleNamespace(id="seg-1")])
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
        context = SimpleNamespace(
            bot_data={
                "recent_entries": [
                    {
                        "id": "old-entry",
                        "short_id": "old-entry",
                        "food_name": "Older meal item",
                        "quantity_display": "1 bowl",
                        "meal_id": "older-meal",
                    }
                ]
            }
        )

        with (
            patch("bot.handlers.get_settings", return_value=SimpleNamespace(TELEGRAM_CHAT_ID="999", DATABASE_URL="postgresql://db")),
            patch("bot.handlers._make_session_factory", return_value=(engine, Mock(return_value=SessionContext()))),
            patch("bot.handlers._resolve_active_interview_for_text", AsyncMock(return_value=(interview, None))),
            patch(
                "bot.handlers.interview_service.finalize_confirmed_interview",
                AsyncMock(
                    return_value={
                        "grounding_required": False,
                        "meal_entries": [
                            SimpleNamespace(
                                id="entry-new",
                                segment_id="seg-1",
                                quantity_display="1 bowl",
                            )
                        ],
                    }
                ),
            ),
        ):
            await interview_text(update, context)

        sent_text = reply_text.await_args.args[0]
        self.assertIn("Meal confirmation saved.", sent_text)
        self.assertIn("Fix targets:", sent_text)
        self.assertIn("1. entry-ne Dal (1 bowl)", sent_text)
        self.assertNotIn("Older meal item", sent_text)
        self.assertEqual(
            context.bot_data["recent_entries"],
            [
                {
                    "id": "entry-new",
                    "short_id": "entry-ne",
                    "food_name": "Dal",
                    "quantity_display": "1 bowl",
                    "meal_id": "meal-confirm-fix-targets",
                }
            ],
        )

    def test_recent_entries_from_confirmation_prefers_written_food_item_names_over_segment_names(self) -> None:
        from bot.handlers import _recent_entries_from_confirmation

        meal_entries = [
            SimpleNamespace(
                id="f6359c02-aaaa-bbbb-cccc-000000000001",
                segment_id="seg-shared",
                quantity_display=None,
                food_item=SimpleNamespace(name="Homemade Basmati Rice"),
            ),
            SimpleNamespace(
                id="9c87a427-aaaa-bbbb-cccc-000000000002",
                segment_id="seg-shared",
                quantity_display=None,
                food_item=SimpleNamespace(name="Chicken Curry"),
            ),
            SimpleNamespace(
                id="753d7b82-aaaa-bbbb-cccc-000000000003",
                segment_id="seg-kebab",
                quantity_display=None,
                food_item=SimpleNamespace(name="Chicken Shami Kebab"),
            ),
        ]
        confirmation_items = [
            {
                "group_id": "group-rice",
                "segment_id": "seg-shared",
                "name": "Chicken Curry",
            },
            {
                "group_id": "group-curry",
                "segment_id": "seg-shared",
                "name": "Chicken Curry",
            },
            {
                "group_id": "group-kebab",
                "segment_id": "seg-kebab",
                "name": "Chicken",
            },
        ]

        recent_entries = _recent_entries_from_confirmation(
            meal_id="meal-confirm-fix-targets",
            meal_entries=meal_entries,
            confirmation_items=confirmation_items,
        )

        self.assertEqual(
            recent_entries,
            [
                {
                    "id": "f6359c02-aaaa-bbbb-cccc-000000000001",
                    "short_id": "f6359c02",
                    "food_name": "Homemade Basmati Rice",
                    "quantity_display": None,
                    "meal_id": "meal-confirm-fix-targets",
                },
                {
                    "id": "9c87a427-aaaa-bbbb-cccc-000000000002",
                    "short_id": "9c87a427",
                    "food_name": "Chicken Curry",
                    "quantity_display": None,
                    "meal_id": "meal-confirm-fix-targets",
                },
                {
                    "id": "753d7b82-aaaa-bbbb-cccc-000000000003",
                    "short_id": "753d7b82",
                    "food_name": "Chicken Shami Kebab",
                    "quantity_display": None,
                    "meal_id": "meal-confirm-fix-targets",
                },
            ],
        )

    async def test_interview_text_confirm_closes_session_after_inline_grounding_finalize(self) -> None:
        from bot.handlers import interview_text

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
        meal = SimpleNamespace(id="meal-2", segments=[SimpleNamespace(id="seg-1")], reasoning_state_json={})
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
            patch("bot.handlers._resolve_active_interview_for_text", AsyncMock(return_value=(interview, None))),
            patch(
                "bot.handlers.interview_service.finalize_confirmed_interview",
                AsyncMock(
                    return_value={
                        "grounding_required": False,
                        "meal": meal,
                        "meal_entries": [],
                        "confirmation_items": [{"segment_id": "seg-1", "name": "Protein Bar"}],
                    }
                ),
            ),
        ):
            await interview_text(update, context)

        self.assertFalse(interview.is_active)
        reply_text.assert_awaited_once()
        self.assertIn("Meal confirmation saved.", reply_text.await_args.args[0])
        session.commit.assert_awaited_once()
        engine.dispose.assert_awaited_once()

    async def test_start_meal_interview_turn_renders_persisted_clarification_without_llm(self) -> None:
        from bot import polling

        start_turn = getattr(polling, "_start_meal_interview_turn", None)
        self.assertTrue(
            callable(start_turn),
            "bot.polling must expose a kickoff helper that renders the first deterministic clarification question.",
        )
        if not callable(start_turn):
            return

        session = AsyncMock()
        session.add = Mock()
        bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=321)))
        interview = SimpleNamespace(
            id="interview-kickoff",
            chat_id="999",
            state_key="QUESTION_BATCH",
            last_bot_message_id=None,
            current_prompt_payload={
                "meal_id": "meal-ui-1",
                "session_mode": "MEAL_INTERVIEW",
                "question_order": ["q-confirm-pita", "q-detail-curry"],
                "questions_by_id": {
                    "q-confirm-pita": {
                        "question_id": "q-confirm-pita",
                        "group_id": "group-pita",
                        "primary_segment_id": "seg-pita-1",
                        "segment_ids": ["seg-pita-1"],
                        "question_kind": "APPROVAL",
                        "answer_type": "confirm",
                        "required": False,
                        "label": "pita bread",
                        "choices": [
                            {"choice_id": "approve", "label": "Yes"},
                            {"choice_id": "correct", "label": "No"},
                        ],
                    },
                    "q-detail-curry": {
                        "question_id": "q-detail-curry",
                        "group_id": "group-egg",
                        "primary_segment_id": "seg-egg-1",
                        "segment_ids": ["seg-egg-1", "seg-egg-2"],
                        "question_kind": "DETAIL",
                        "answer_type": "free_text",
                        "required": True,
                        "label": "egg curry",
                        "question_focus": "vegetable inside egg curry",
                        "question_examples": [
                            "egg curry with bottle gourd",
                            "egg curry with zucchini",
                        ],
                    },
                },
                "answers_by_question_id": {},
                "pending_question_ids": ["q-confirm-pita", "q-detail-curry"],
                "remaining_required_question_ids": ["q-detail-curry"],
                "interview_messages": [],
            },
        )
        with patch("bot.polling.interview_turn_manager.run_interview_turn", AsyncMock()) as run_turn:
            await start_turn(
                bot=bot,
                session=session,
                interview=interview,
                settings=SimpleNamespace(),
            )

        run_turn.assert_not_awaited()
        bot.send_message.assert_awaited_once()
        sent_text = bot.send_message.await_args.kwargs["text"]
        self.assertIn("egg curry", sent_text.lower())
        self.assertNotIn("chicken curry", sent_text.lower())
        self.assertEqual(interview.last_bot_message_id, 321)
        self.assertEqual(interview.current_prompt_payload["interview_messages"][-1]["content"], sent_text)
        self.assertEqual(interview.current_prompt_payload["interview_messages"][-1]["message_id"], 321)
        self.assertEqual(interview.current_prompt_payload["current_question"]["question_id"], "q-detail-curry")
        self.assertEqual(session.add.call_args_list[-1].args[0].message_id, 321)
        session.commit.assert_awaited()

    async def test_start_meal_interview_turn_uses_telegram_safe_compact_callbacks(self) -> None:
        from bot import polling

        session = AsyncMock()
        session.add = Mock()
        bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=322)))
        meal_id = "64051be1-ea01-4919-b885-e2f60e418b49"
        question_id = "fg_bread:identity"
        choice_id = "whole_wheat_khubz"
        interview = SimpleNamespace(
            id="interview-kickoff-compact",
            chat_id="999",
            state_key="QUESTION_BATCH",
            last_bot_message_id=None,
            meal_log_id=meal_id,
            current_prompt_payload={
                "meal_id": meal_id,
                "session_mode": "MEAL_INTERVIEW",
                "question_order": [question_id],
                "questions_by_id": {
                    question_id: {
                        "question_id": question_id,
                        "group_id": "fg_bread",
                        "primary_segment_id": "seg-bread-1",
                        "segment_ids": ["seg-bread-1"],
                        "question_kind": "IDENTITY",
                        "answer_type": "single_choice",
                        "required": True,
                        "label": "Khubz / Flatbread",
                        "prompt": "Which bread_type best matches the Khubz / Flatbread?",
                        "choices": [
                            {"choice_id": choice_id, "label": "Whole-wheat Khubz"},
                        ],
                    },
                },
                "answers_by_question_id": {},
                "pending_question_ids": [question_id],
                "remaining_required_question_ids": [question_id],
                "interview_messages": [],
            },
        )

        await polling._start_meal_interview_turn(
            bot=bot,
            session=session,
            interview=interview,
            settings=SimpleNamespace(),
        )

        reply_markup = bot.send_message.await_args.kwargs["reply_markup"]
        callback_data = reply_markup.inline_keyboard[0][0].callback_data
        self.assertLessEqual(len(callback_data.encode("utf-8")), 64)
        self.assertEqual(
            callback_data,
            f"interview:64051be1:{_test_callback_token(question_id)}:{_test_callback_token(choice_id)}",
        )

    async def test_start_meal_interview_turn_adds_other_button_for_single_choice_identity(self) -> None:
        from bot import polling

        session = AsyncMock()
        session.add = Mock()
        bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=323)))
        meal_id = "923cd810-c507-432a-be37-cc856760914d"
        question_id = "group_1:identity"
        interview = SimpleNamespace(
            id="interview-kickoff-other",
            chat_id="999",
            state_key="QUESTION_BATCH",
            last_bot_message_id=None,
            meal_log_id=meal_id,
            current_prompt_payload={
                "meal_id": meal_id,
                "session_mode": "MEAL_INTERVIEW",
                "question_order": [question_id],
                "questions_by_id": {
                    question_id: {
                        "question_id": question_id,
                        "group_id": "group_1",
                        "primary_segment_id": "seg-curry-1",
                        "segment_ids": ["seg-curry-1"],
                        "question_kind": "IDENTITY",
                        "answer_type": "single_choice",
                        "required": True,
                        "label": "Vegetable and Egg Curry",
                        "prompt": "Which vegetable inside curry best matches the Vegetable and Egg Curry?",
                        "choices": [
                            {"choice_id": "ridge_gourd", "label": "ridge gourd"},
                            {"choice_id": "bottle_gourd_lauki", "label": "bottle gourd (lauki)"},
                        ],
                    },
                },
                "answers_by_question_id": {},
                "pending_question_ids": [question_id],
                "remaining_required_question_ids": [question_id],
                "interview_messages": [],
            },
        )

        await polling._start_meal_interview_turn(
            bot=bot,
            session=session,
            interview=interview,
            settings=SimpleNamespace(),
        )

        reply_markup = bot.send_message.await_args.kwargs["reply_markup"]
        other_button = reply_markup.inline_keyboard[-1][0]
        self.assertEqual(other_button.text, "Other")
        self.assertEqual(
            other_button.callback_data,
            f"interview:923cd810:{_test_callback_token(question_id)}:{_test_callback_token('__other__')}",
        )

    async def test_start_meal_interview_turn_keeps_source_origin_without_other_button(self) -> None:
        from bot import polling

        session = AsyncMock()
        session.add = Mock()
        bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=324)))
        meal_id = "923cd810-c507-432a-be37-cc856760914d"
        question_id = "group_1:source_origin"
        interview = SimpleNamespace(
            id="interview-kickoff-source",
            chat_id="999",
            state_key="QUESTION_BATCH",
            last_bot_message_id=None,
            meal_log_id=meal_id,
            current_prompt_payload={
                "meal_id": meal_id,
                "session_mode": "MEAL_INTERVIEW",
                "question_order": [question_id],
                "questions_by_id": {
                    question_id: {
                        "question_id": question_id,
                        "group_id": "group_1",
                        "primary_segment_id": "seg-bar-1",
                        "segment_ids": ["seg-bar-1"],
                        "question_kind": "SOURCE_ORIGIN",
                        "answer_type": "single_choice",
                        "required": True,
                        "label": "protein bar",
                        "prompt": "How should I treat the protein bar for nutrition?",
                        "choices": [
                            {"choice_id": "HOME_COOKED", "label": "homemade"},
                            {"choice_id": "PACKAGED_BRANDED", "label": "packaged"},
                        ],
                    },
                },
                "answers_by_question_id": {},
                "pending_question_ids": [question_id],
                "remaining_required_question_ids": [question_id],
                "interview_messages": [],
            },
        )

        await polling._start_meal_interview_turn(
            bot=bot,
            session=session,
            interview=interview,
            settings=SimpleNamespace(),
        )

        reply_markup = bot.send_message.await_args.kwargs["reply_markup"]
        button_texts = [button.text for row in reply_markup.inline_keyboard for button in row]
        self.assertEqual(button_texts, ["homemade", "packaged"])

    async def test_start_meal_interview_turn_sends_fallback_when_llm_turn_is_invalid(self) -> None:
        from bot import polling

        session = AsyncMock()
        session.add = Mock()
        bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=654)))
        interview = SimpleNamespace(
            id="interview-kickoff-invalid",
            chat_id="999",
            state_key="INITIAL_QUESTION",
            last_bot_message_id=None,
            current_prompt_payload={
                "meal_id": "meal-thread-invalid",
                "session_mode": "MEAL_INTERVIEW",
                "roadmap_step": "INITIAL_QUESTION",
                "current_question": {
                    "prompt": "What vegetable is in the egg curry?",
                    "invalid_prompt": "What vegetable is in the egg curry?",
                },
                "unresolved_targets": [
                    {
                        "group_id": "group-egg",
                        "primary_segment_id": "seg-egg-1",
                        "segment_ids": ["seg-egg-1", "seg-egg-2"],
                        "label": "egg curry",
                    }
                ],
                "approval_candidates": [],
                "interview_messages": [],
            },
        )

        with patch(
            "bot.polling.interview_turn_manager.run_interview_turn",
            AsyncMock(side_effect=InterviewTurnValidationError("confirmation coverage mismatch")),
        ) as run_turn:
            result = await polling._start_meal_interview_turn(
                bot=bot,
                session=session,
                interview=interview,
                settings=SimpleNamespace(),
            )

        run_turn.assert_awaited_once()
        self.assertIsNone(result)
        bot.send_message.assert_awaited_once_with(
            chat_id="999",
            text=(
                "I couldn't safely generate the first interview prompt. "
                "Please answer this meal question: What vegetable is in the egg curry?"
            ),
        )
        self.assertEqual(interview.last_bot_message_id, 654)
        self.assertEqual(interview.current_prompt_payload["last_turn_error"], "confirmation coverage mismatch")
        self.assertEqual(interview.current_prompt_payload["interview_messages"][-1]["message_id"], 654)
        self.assertEqual(session.add.call_args_list[-1].args[0].payload["type"], "validation_retry")
        session.commit.assert_awaited_once()

    async def test_interview_callback_maps_choice_to_stable_question_id_and_rerenders_remaining_required_question(self) -> None:
        from bot.handlers import interview_callback

        interview = SimpleNamespace(
            id="interview-choice",
            meal_log_id="meal-choice",
            is_active=True,
            state_key="QUESTION_BATCH",
            current_prompt_payload={
                "meal_id": "meal-choice",
                "session_mode": "MEAL_INTERVIEW",
                "question_order": ["q-confirm-pita", "q-detail-curry"],
                "questions_by_id": {
                    "q-confirm-pita": {
                        "question_id": "q-confirm-pita",
                        "group_id": "group-pita",
                        "primary_segment_id": "seg-pita-1",
                        "segment_ids": ["seg-pita-1"],
                        "question_kind": "APPROVAL",
                        "answer_type": "confirm",
                        "required": False,
                        "label": "pita bread",
                        "choices": [
                            {"choice_id": "approve", "label": "Yes"},
                            {"choice_id": "correct", "label": "No"},
                        ],
                    },
                    "q-detail-curry": {
                        "question_id": "q-detail-curry",
                        "group_id": "group-egg",
                        "primary_segment_id": "seg-egg-1",
                        "segment_ids": ["seg-egg-1", "seg-egg-2"],
                        "question_kind": "DETAIL",
                        "answer_type": "free_text",
                        "required": True,
                        "label": "egg curry",
                        "question_focus": "vegetable inside egg curry",
                        "question_examples": ["egg curry with bottle gourd"],
                    },
                },
                "answers_by_question_id": {},
                "pending_question_ids": ["q-confirm-pita", "q-detail-curry"],
                "remaining_required_question_ids": ["q-detail-curry"],
                "interview_messages": [],
            },
        )
        session = AsyncMock()
        session.add = Mock()
        engine = SimpleNamespace(dispose=AsyncMock())

        class SessionContext:
            async def __aenter__(self):
                return session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        callback_query = SimpleNamespace(
            data="interview:meal-choice:q-confirm-pita:approve",
            answer=AsyncMock(),
            message=SimpleNamespace(chat=SimpleNamespace(id="999"), reply_text=AsyncMock()),
        )
        update = SimpleNamespace(callback_query=callback_query, message=None)
        context = SimpleNamespace(bot_data={})

        with (
            patch("bot.handlers.get_settings", return_value=SimpleNamespace(TELEGRAM_CHAT_ID="999", DATABASE_URL="postgresql://db")),
            patch("bot.handlers._make_session_factory", return_value=(engine, Mock(return_value=SessionContext()))),
            patch("bot.handlers._load_active_interview", AsyncMock(return_value=interview)),
            patch("bot.handlers.interview_service.persist_interview_step", AsyncMock()) as persist,
        ):
            await interview_callback(update, context)

        persist.assert_awaited_once()
        persisted_state = persist.await_args.kwargs["state"]
        self.assertEqual(persist.await_args.kwargs["user_payload"]["question_id"], "q-confirm-pita")
        self.assertEqual(persist.await_args.kwargs["user_payload"]["choice_id"], "approve")
        self.assertEqual(persisted_state["answers_by_question_id"]["q-confirm-pita"]["choice_id"], "approve")
        self.assertEqual(persisted_state["remaining_required_question_ids"], ["q-detail-curry"])
        callback_query.message.reply_text.assert_awaited_once()
        engine.dispose.assert_awaited_once()

    async def test_interview_callback_rerenders_pending_optional_confirm_after_required_choice(self) -> None:
        from bot.handlers import interview_callback

        interview = SimpleNamespace(
            id="interview-required-then-confirm",
            meal_log_id="meal-choice",
            is_active=True,
            state_key="QUESTION_BATCH",
            current_prompt_payload={
                "meal_id": "meal-choice",
                "session_mode": "MEAL_INTERVIEW",
                "question_order": ["q-detail-veg", "q-confirm-chicken"],
                "questions_by_id": {
                    "q-detail-veg": {
                        "question_id": "q-detail-veg",
                        "group_id": "group-veg",
                        "primary_segment_id": "seg-veg-1",
                        "segment_ids": ["seg-veg-1"],
                        "question_kind": "CHOICE",
                        "answer_type": "single_choice",
                        "required": True,
                        "label": "mixed vegetables",
                        "choices": [
                            {"choice_id": "steamed_veg", "label": "Steamed vegetables"},
                        ],
                    },
                    "q-confirm-chicken": {
                        "question_id": "q-confirm-chicken",
                        "group_id": "group-chicken",
                        "primary_segment_id": "seg-chicken-1",
                        "segment_ids": ["seg-chicken-1"],
                        "question_kind": "APPROVAL",
                        "answer_type": "confirm",
                        "required": False,
                        "label": "Chicken Curry with Drumstick",
                        "choices": [
                            {"choice_id": "approve", "label": "Yes"},
                            {"choice_id": "correct", "label": "No"},
                        ],
                    },
                },
                "answers_by_question_id": {},
                "pending_question_ids": ["q-detail-veg", "q-confirm-chicken"],
                "remaining_required_question_ids": ["q-detail-veg"],
                "interview_messages": [],
            },
        )
        session = AsyncMock()
        session.add = Mock()
        engine = SimpleNamespace(dispose=AsyncMock())

        class SessionContext:
            async def __aenter__(self):
                return session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        callback_query = SimpleNamespace(
            data="interview:meal-choice:q-detail-veg:steamed_veg",
            answer=AsyncMock(),
            message=SimpleNamespace(
                chat=SimpleNamespace(id="999"),
                reply_text=AsyncMock(return_value=SimpleNamespace(message_id=456)),
            ),
        )
        update = SimpleNamespace(callback_query=callback_query, message=None)
        context = SimpleNamespace(bot_data={})

        with (
            patch("bot.handlers.get_settings", return_value=SimpleNamespace(TELEGRAM_CHAT_ID="999", DATABASE_URL="postgresql://db")),
            patch("bot.handlers._make_session_factory", return_value=(engine, Mock(return_value=SessionContext()))),
            patch("bot.handlers._load_active_interview", AsyncMock(return_value=interview)),
            patch("bot.handlers._resolve_deterministic_confirmation", AsyncMock()) as resolve,
            patch("bot.handlers.interview_service.persist_interview_step", AsyncMock()) as persist,
        ):
            await interview_callback(update, context)

        resolve.assert_not_awaited()
        persist.assert_awaited_once()
        persisted_state = persist.await_args.kwargs["state"]
        self.assertEqual(persisted_state["pending_question_ids"], ["q-confirm-chicken"])
        self.assertEqual(persisted_state["remaining_required_question_ids"], [])
        callback_query.message.reply_text.assert_awaited_once()
        self.assertIn("Chicken Curry with Drumstick", callback_query.message.reply_text.await_args.args[0])
        reply_markup = callback_query.message.reply_text.await_args.kwargs["reply_markup"]
        self.assertEqual(reply_markup.inline_keyboard[0][0].text, "Yes")
        self.assertEqual(reply_markup.inline_keyboard[1][0].text, "No")
        engine.dispose.assert_awaited_once()

    async def test_interview_callback_identity_choice_rerenders_inserted_source_affirmation(self) -> None:
        from bot.handlers import interview_callback

        interview = SimpleNamespace(
            id="interview-source-affirmation",
            meal_log_id="meal-source-affirmation",
            is_active=True,
            state_key="QUESTION_BATCH",
            current_prompt_payload={
                "meal_id": "meal-source-affirmation",
                "session_mode": "MEAL_INTERVIEW",
                "question_order": ["q-identity", "q-quantity"],
                "questions_by_id": {
                    "q-identity": {
                        "question_id": "q-identity",
                        "group_id": "group-bread",
                        "primary_segment_id": "seg-bread-1",
                        "segment_ids": ["seg-bread-1", "seg-bread-2"],
                        "question_kind": "IDENTITY",
                        "answer_type": "single_choice",
                        "required": True,
                        "label": "flatbread",
                        "source_question_policy": "ask_affirmation",
                        "learned_source_distribution": [
                            {
                                "source_type": "PACKAGED",
                                "source_origin_state": "PACKAGED_BRANDED",
                                "brand_name": "Acme",
                                "count": 7,
                                "share": 0.9,
                            }
                        ],
                        "choices": [
                            {
                                "choice_id": "candidate-khubz",
                                "label": "White Khubz",
                                "value": "White Khubz",
                            }
                        ],
                    },
                    "q-quantity": {
                        "question_id": "q-quantity",
                        "group_id": "group-bread",
                        "primary_segment_id": "seg-bread-1",
                        "segment_ids": ["seg-bread-1", "seg-bread-2"],
                        "question_kind": "QUANTITY",
                        "answer_type": "free_text",
                        "required": True,
                        "label": "flatbread",
                    },
                },
                "answers_by_question_id": {},
                "pending_question_ids": ["q-identity", "q-quantity"],
                "remaining_required_question_ids": ["q-identity", "q-quantity"],
                "interview_messages": [],
            },
        )
        session = AsyncMock()
        session.add = Mock()
        engine = SimpleNamespace(dispose=AsyncMock())

        class SessionContext:
            async def __aenter__(self):
                return session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        callback_query = SimpleNamespace(
            data="interview:meal-source-affirmation:q-identity:candidate-khubz",
            answer=AsyncMock(),
            message=SimpleNamespace(
                chat=SimpleNamespace(id="999"),
                reply_text=AsyncMock(return_value=SimpleNamespace(message_id=777)),
            ),
        )
        update = SimpleNamespace(callback_query=callback_query, message=None)
        context = SimpleNamespace(bot_data={})

        with (
            patch("bot.handlers.get_settings", return_value=SimpleNamespace(TELEGRAM_CHAT_ID="999", DATABASE_URL="postgresql://db")),
            patch("bot.handlers._make_session_factory", return_value=(engine, Mock(return_value=SessionContext()))),
            patch("bot.handlers._load_active_interview", AsyncMock(return_value=interview)),
            patch("bot.handlers._resolve_deterministic_confirmation", AsyncMock()) as resolve,
            patch("bot.handlers.interview_service.persist_interview_step", AsyncMock()) as persist,
        ):
            await interview_callback(update, context)

        resolve.assert_not_awaited()
        persist.assert_awaited_once()
        next_prompt = persist.await_args.kwargs["next_prompt"]
        self.assertEqual(next_prompt["question_id"], "group-bread:source_affirmation")
        self.assertEqual(next_prompt["answer_type"], "confirm")
        self.assertIn("Acme", next_prompt["prompt"])
        reply_markup = callback_query.message.reply_text.await_args.kwargs["reply_markup"]
        self.assertEqual(reply_markup.inline_keyboard[0][0].text, "Yes")
        self.assertEqual(reply_markup.inline_keyboard[1][0].text, "No")
        engine.dispose.assert_awaited_once()

    async def test_interview_callback_no_affirmation_prompts_same_group_free_text_correction(self) -> None:
        from bot.handlers import interview_callback

        interview = SimpleNamespace(
            id="interview-affirmation-no",
            meal_log_id="meal-affirmation-no",
            is_active=True,
            state_key="QUESTION_BATCH",
            current_prompt_payload={
                "meal_id": "meal-affirmation-no",
                "session_mode": "MEAL_INTERVIEW",
                "question_order": ["q-affirm-chicken"],
                "questions_by_id": {
                    "q-affirm-chicken": {
                        "question_id": "q-affirm-chicken",
                        "group_id": "group-chicken",
                        "primary_segment_id": "seg-chicken-1",
                        "segment_ids": ["seg-chicken-1"],
                        "question_kind": "AFFIRMATION",
                        "answer_type": "confirm",
                        "required": True,
                        "label": "Chicken Curry with Drumstick",
                        "type": "AFFIRMATION",
                        "user_prompt": "Does Chicken Curry with Drumstick look right for this part of the meal?",
                        "choices": [
                            {"choice_id": "approve", "label": "Yes"},
                            {"choice_id": "correct", "label": "No"},
                        ],
                    }
                },
                "answers_by_question_id": {},
                "pending_question_ids": ["q-affirm-chicken"],
                "remaining_required_question_ids": ["q-affirm-chicken"],
                "interview_messages": [],
            },
        )
        session = AsyncMock()
        session.add = Mock()
        engine = SimpleNamespace(dispose=AsyncMock())

        class SessionContext:
            async def __aenter__(self):
                return session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        callback_query = SimpleNamespace(
            data="interview:meal-affirmation-no:q-affirm-chicken:correct",
            answer=AsyncMock(),
            message=SimpleNamespace(
                chat=SimpleNamespace(id="999"),
                reply_text=AsyncMock(return_value=SimpleNamespace(message_id=654)),
            ),
        )
        update = SimpleNamespace(callback_query=callback_query, message=None)
        context = SimpleNamespace(bot_data={})

        with (
            patch("bot.handlers.get_settings", return_value=SimpleNamespace(TELEGRAM_CHAT_ID="999", DATABASE_URL="postgresql://db")),
            patch("bot.handlers._make_session_factory", return_value=(engine, Mock(return_value=SessionContext()))),
            patch("bot.handlers._load_active_interview", AsyncMock(return_value=interview)),
            patch("bot.handlers._resolve_deterministic_confirmation", AsyncMock()) as resolve,
            patch("bot.handlers.interview_service.persist_interview_step", AsyncMock()) as persist,
        ):
            await interview_callback(update, context)

        resolve.assert_not_awaited()
        persist.assert_awaited_once()
        persisted_state = persist.await_args.kwargs["state"]
        next_prompt = persist.await_args.kwargs["next_prompt"]
        self.assertEqual(next_prompt["group_id"], "group-chicken")
        self.assertEqual(next_prompt["answer_type"], "free_text")
        self.assertEqual(persisted_state["current_question"]["group_id"], "group-chicken")
        self.assertEqual(persisted_state["current_question"]["answer_type"], "free_text")
        self.assertIn("what should i call", callback_query.message.reply_text.await_args.args[0].lower())
        engine.dispose.assert_awaited_once()

    async def test_interview_callback_rejects_answered_identity_after_dynamic_source_insertion(self) -> None:
        from bot.handlers import interview_callback

        interview = SimpleNamespace(
            id="interview-answered-identity",
            meal_log_id="meal-answered-identity",
            is_active=True,
            state_key="QUESTION_BATCH",
            current_prompt_payload={
                "meal_id": "meal-answered-identity",
                "session_mode": "MEAL_INTERVIEW",
                "question_order": ["q-identity", "group-bread:source_affirmation", "q-quantity"],
                "questions_by_id": {
                    "q-identity": {
                        "question_id": "q-identity",
                        "group_id": "group-bread",
                        "primary_segment_id": "seg-bread-1",
                        "segment_ids": ["seg-bread-1"],
                        "question_kind": "IDENTITY",
                        "answer_type": "single_choice",
                        "required": True,
                        "label": "flatbread",
                        "choices": [
                            {"choice_id": "candidate-khubz", "label": "White Khubz"},
                        ],
                    },
                    "group-bread:source_affirmation": {
                        "question_id": "group-bread:source_affirmation",
                        "group_id": "group-bread",
                        "primary_segment_id": "seg-bread-1",
                        "segment_ids": ["seg-bread-1"],
                        "question_kind": "AFFIRMATION",
                        "answer_type": "confirm",
                        "required": True,
                        "label": "White Khubz",
                        "source_affirmation": True,
                        "choices": [
                            {"choice_id": "approve", "label": "Yes"},
                            {"choice_id": "correct", "label": "No"},
                        ],
                    },
                    "q-quantity": {
                        "question_id": "q-quantity",
                        "group_id": "group-bread",
                        "primary_segment_id": "seg-bread-1",
                        "segment_ids": ["seg-bread-1"],
                        "question_kind": "QUANTITY",
                        "answer_type": "free_text",
                        "required": True,
                        "label": "flatbread",
                    },
                },
                "answers_by_question_id": {
                    "q-identity": {
                        "question_id": "q-identity",
                        "group_id": "group-bread",
                        "question_kind": "IDENTITY",
                        "choice_id": "candidate-khubz",
                        "name": "White Khubz",
                    }
                },
                "pending_question_ids": ["group-bread:source_affirmation", "q-quantity"],
                "remaining_required_question_ids": ["group-bread:source_affirmation", "q-quantity"],
                "interview_messages": [],
            },
        )
        session = AsyncMock()
        session.add = Mock()
        engine = SimpleNamespace(dispose=AsyncMock())

        class SessionContext:
            async def __aenter__(self):
                return session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        callback_query = SimpleNamespace(
            data="interview:meal-answered-identity:q-identity:candidate-khubz",
            answer=AsyncMock(),
            message=SimpleNamespace(chat=SimpleNamespace(id="999"), reply_text=AsyncMock()),
        )
        update = SimpleNamespace(callback_query=callback_query, message=None)
        context = SimpleNamespace(bot_data={})

        with (
            patch("bot.handlers.get_settings", return_value=SimpleNamespace(TELEGRAM_CHAT_ID="999", DATABASE_URL="postgresql://db")),
            patch("bot.handlers._make_session_factory", return_value=(engine, Mock(return_value=SessionContext()))),
            patch("bot.handlers._load_active_interview", AsyncMock(return_value=interview)),
            patch("bot.handlers.interview_service.persist_interview_step", AsyncMock()) as persist,
        ):
            await interview_callback(update, context)

        callback_query.answer.assert_awaited_once_with("That question is already answered.", show_alert=True)
        persist.assert_not_awaited()
        callback_query.message.reply_text.assert_not_awaited()
        engine.dispose.assert_awaited_once()

    async def test_interview_callback_resolves_compact_tokens_for_colon_question_ids(self) -> None:
        from bot.handlers import interview_callback

        meal_id = "64051be1-ea01-4919-b885-e2f60e418b49"
        question_id = "fg_bread:identity"
        choice_id = "whole_wheat_khubz"
        interview = SimpleNamespace(
            id="interview-choice-compact",
            meal_log_id=meal_id,
            is_active=True,
            state_key="QUESTION_BATCH",
            current_prompt_payload={
                "meal_id": meal_id,
                "session_mode": "MEAL_INTERVIEW",
                "question_order": [question_id],
                "questions_by_id": {
                    question_id: {
                        "question_id": question_id,
                        "group_id": "fg_bread",
                        "primary_segment_id": "seg-bread-1",
                        "segment_ids": ["seg-bread-1"],
                        "question_kind": "IDENTITY",
                        "answer_type": "single_choice",
                        "required": True,
                        "label": "Khubz / Flatbread",
                        "choices": [
                            {"choice_id": choice_id, "label": "Whole-wheat Khubz"},
                        ],
                    },
                },
                "answers_by_question_id": {},
                "pending_question_ids": [question_id],
                "remaining_required_question_ids": [question_id],
                "interview_messages": [],
            },
        )
        session = AsyncMock()
        session.add = Mock()
        engine = SimpleNamespace(dispose=AsyncMock())

        class SessionContext:
            async def __aenter__(self):
                return session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        callback_query = SimpleNamespace(
            data=f"interview:64051be1:{_test_callback_token(question_id)}:{_test_callback_token(choice_id)}",
            answer=AsyncMock(),
            message=SimpleNamespace(chat=SimpleNamespace(id="999"), reply_text=AsyncMock()),
        )
        update = SimpleNamespace(callback_query=callback_query, message=None)
        context = SimpleNamespace(bot_data={})

        with (
            patch("bot.handlers.get_settings", return_value=SimpleNamespace(TELEGRAM_CHAT_ID="999", DATABASE_URL="postgresql://db")),
            patch("bot.handlers._make_session_factory", return_value=(engine, Mock(return_value=SessionContext()))),
            patch("bot.handlers._load_active_interview", AsyncMock(return_value=interview)) as load_interview,
            patch("bot.handlers._resolve_deterministic_confirmation", AsyncMock()) as resolve,
            patch("bot.handlers.interview_service.persist_interview_step", AsyncMock()) as persist,
        ):
            await interview_callback(update, context)

        load_interview.assert_awaited_once()
        self.assertEqual(load_interview.await_args.kwargs["meal_id"], "64051be1")
        resolve.assert_awaited_once()
        self.assertEqual(resolve.await_args.kwargs["user_payload"]["question_id"], question_id)
        self.assertEqual(resolve.await_args.kwargs["user_payload"]["choice_id"], choice_id)
        persist.assert_not_awaited()
        engine.dispose.assert_awaited_once()

    async def test_interview_callback_other_prompts_for_free_text_on_same_question(self) -> None:
        from bot.handlers import interview_callback

        meal_id = "923cd810-c507-432a-be37-cc856760914d"
        question_id = "group_1:identity"
        interview = SimpleNamespace(
            id="interview-other",
            meal_log_id=meal_id,
            is_active=True,
            state_key="QUESTION_BATCH",
            current_prompt_payload={
                "meal_id": meal_id,
                "session_mode": "MEAL_INTERVIEW",
                "question_order": [question_id],
                "questions_by_id": {
                    question_id: {
                        "question_id": question_id,
                        "group_id": "group_1",
                        "primary_segment_id": "seg-curry-1",
                        "segment_ids": ["seg-curry-1"],
                        "question_kind": "IDENTITY",
                        "answer_type": "single_choice",
                        "required": True,
                        "label": "Vegetable and Egg Curry",
                        "question_focus": "vegetable inside curry",
                        "choices": [
                            {"choice_id": "ridge_gourd", "label": "ridge gourd"},
                        ],
                    },
                },
                "answers_by_question_id": {},
                "pending_question_ids": [question_id],
                "remaining_required_question_ids": [question_id],
                "interview_messages": [],
            },
        )
        session = AsyncMock()
        session.add = Mock()
        engine = SimpleNamespace(dispose=AsyncMock())

        class SessionContext:
            async def __aenter__(self):
                return session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        callback_query = SimpleNamespace(
            data=f"interview:923cd810:{_test_callback_token(question_id)}:{_test_callback_token('__other__')}",
            answer=AsyncMock(),
            message=SimpleNamespace(
                chat=SimpleNamespace(id="999"),
                reply_text=AsyncMock(return_value=SimpleNamespace(message_id=456)),
            ),
        )
        update = SimpleNamespace(callback_query=callback_query, message=None)
        context = SimpleNamespace(bot_data={})

        with (
            patch("bot.handlers.get_settings", return_value=SimpleNamespace(TELEGRAM_CHAT_ID="999", DATABASE_URL="postgresql://db")),
            patch("bot.handlers._make_session_factory", return_value=(engine, Mock(return_value=SessionContext()))),
            patch("bot.handlers._load_active_interview", AsyncMock(return_value=interview)),
            patch("bot.handlers._resolve_deterministic_confirmation", AsyncMock()) as resolve,
            patch("bot.handlers.interview_service.persist_interview_step", AsyncMock()) as persist,
        ):
            await interview_callback(update, context)

        resolve.assert_not_awaited()
        callback_query.answer.assert_awaited_once()
        callback_query.message.reply_text.assert_awaited_once()
        self.assertIn("type your answer", callback_query.message.reply_text.await_args.args[0].lower())
        persisted_state = persist.await_args.kwargs["state"]
        self.assertEqual(persisted_state["awaiting_other_question_id"], question_id)
        self.assertEqual(persisted_state["current_question"]["question_id"], question_id)
        self.assertEqual(persisted_state["current_question"]["answer_type"], "free_text")
        self.assertEqual(persist.await_args.kwargs["user_payload"]["choice_id"], "__other__")
        engine.dispose.assert_awaited_once()

    async def test_meal_interview_text_after_other_records_custom_answer_for_original_question(self) -> None:
        from bot import handlers

        question_id = "group_1:identity"
        interview = SimpleNamespace(
            id="interview-other-text",
            meal_log_id="meal-other-text",
            is_active=True,
            state_key="QUESTION_BATCH",
            current_prompt_payload={},
        )
        state = {
            "meal_id": "meal-other-text",
            "session_mode": "MEAL_INTERVIEW",
            "question_order": [question_id],
            "questions_by_id": {
                question_id: {
                    "question_id": question_id,
                    "group_id": "group_1",
                    "primary_segment_id": "seg-curry-1",
                    "segment_ids": ["seg-curry-1"],
                    "question_kind": "IDENTITY",
                    "answer_type": "single_choice",
                    "required": True,
                    "label": "Vegetable and Egg Curry",
                    "choices": [{"choice_id": "ridge_gourd", "label": "ridge gourd"}],
                }
            },
            "answers_by_question_id": {},
            "pending_question_ids": [question_id],
            "remaining_required_question_ids": [question_id],
            "awaiting_other_question_id": question_id,
            "current_question": {
                "question_id": question_id,
                "prompt": "Please type your answer for Vegetable and Egg Curry.",
                "answer_type": "free_text",
            },
            "interview_messages": [],
        }
        session = AsyncMock()
        session.add = Mock()
        reply_text = AsyncMock()
        update = SimpleNamespace(
            message=SimpleNamespace(
                chat=SimpleNamespace(id="999"),
                text="egg curry with bottle gourd",
                message_id=457,
                reply_text=reply_text,
            )
        )

        with patch("bot.handlers._resolve_deterministic_confirmation", AsyncMock()) as resolve:
            await handlers._handle_deterministic_meal_text(
                session=session,
                interview=interview,
                state=state,
                text="egg curry with bottle gourd",
                update=update,
                settings=SimpleNamespace(),
            )

        resolve.assert_awaited_once()
        resolved_state = resolve.await_args.kwargs["state"]
        user_payload = resolve.await_args.kwargs["user_payload"]
        self.assertNotIn("awaiting_other_question_id", resolved_state)
        self.assertEqual(user_payload["question_id"], question_id)
        self.assertEqual(user_payload["name"], "egg curry with bottle gourd")
        self.assertEqual(
            resolved_state["answers_by_question_id"][question_id]["name"],
            "egg curry with bottle gourd",
        )

    async def test_meal_interview_text_after_detail_other_rerenders_canonical_source_question(self) -> None:
        from bot import handlers

        question_id = "group_bread:detail"
        interview = SimpleNamespace(
            id="interview-bread-other-source",
            meal_log_id="meal-bread-other-source",
            is_active=True,
            state_key="QUESTION_BATCH",
            current_prompt_payload={},
        )
        state = {
            "meal_id": "meal-bread-other-source",
            "session_mode": "MEAL_INTERVIEW",
            "question_order": [question_id, "group_bread:quantity"],
            "questions_by_id": {
                question_id: {
                    "question_id": question_id,
                    "group_id": "group_bread",
                    "primary_segment_id": "seg-bread-1",
                    "segment_ids": ["seg-bread-1", "seg-bread-2"],
                    "question_kind": "DETAIL",
                    "answer_type": "free_text",
                    "required": True,
                    "label": "flatbread",
                    "source_question_policy": "ask_generic",
                    "source_trigger_reason": "Bread source is still required after detail clarification.",
                },
                "group_bread:quantity": {
                    "question_id": "group_bread:quantity",
                    "group_id": "group_bread",
                    "primary_segment_id": "seg-bread-1",
                    "segment_ids": ["seg-bread-1", "seg-bread-2"],
                    "question_kind": "QUANTITY",
                    "answer_type": "free_text",
                    "required": True,
                    "label": "flatbread",
                },
            },
            "answers_by_question_id": {},
            "pending_question_ids": [question_id, "group_bread:quantity"],
            "remaining_required_question_ids": [question_id, "group_bread:quantity"],
            "awaiting_other_question_id": question_id,
            "current_question": {
                "question_id": question_id,
                "prompt": "Please type your answer for flatbread.",
                "answer_type": "free_text",
            },
            "interview_messages": [],
        }
        session = AsyncMock()
        session.add = Mock()
        reply_text = AsyncMock()
        update = SimpleNamespace(
            message=SimpleNamespace(
                chat=SimpleNamespace(id="999"),
                text="Bran and whole wheat",
                message_id=458,
                reply_text=reply_text,
            )
        )

        with patch("bot.handlers._persist_and_reply_with_prompt", AsyncMock()) as persist_and_reply:
            await handlers._handle_deterministic_meal_text(
                session=session,
                interview=interview,
                state=state,
                text="Bran and whole wheat",
                update=update,
                settings=SimpleNamespace(),
            )

        persist_and_reply.assert_awaited_once()
        resolved_state = persist_and_reply.await_args.kwargs["state"]
        next_prompt = persist_and_reply.await_args.kwargs["prompt"]
        self.assertEqual(next_prompt["question_id"], "group_bread:source_origin")
        self.assertEqual(next_prompt["answer_type"], "single_choice")
        self.assertFalse(resolved_state["questions_by_id"]["group_bread:source_origin"]["allow_other"])
        self.assertEqual(
            [choice["label"] for choice in resolved_state["questions_by_id"]["group_bread:source_origin"]["choices"]],
            ["homemade", "store bought", "packaged", "restaurant", "not sure"],
        )

    async def test_meal_interview_text_uses_resolver_after_last_required_answer(self) -> None:
        from bot.handlers import interview_text

        interview = SimpleNamespace(
            id="interview-partial",
            meal_log_id="meal-partial",
            is_active=True,
            state_key="QUESTION_BATCH",
            current_prompt_payload={
                "meal_id": "meal-partial",
                "session_mode": "MEAL_INTERVIEW",
                "question_order": ["q-confirm-pita", "q-detail-curry"],
                "questions_by_id": {
                    "q-confirm-pita": {
                        "question_id": "q-confirm-pita",
                        "group_id": "group-pita",
                        "primary_segment_id": "seg-pita-1",
                        "segment_ids": ["seg-pita-1"],
                        "question_kind": "APPROVAL",
                        "answer_type": "confirm",
                        "required": False,
                        "label": "pita bread",
                    },
                    "q-detail-curry": {
                        "question_id": "q-detail-curry",
                        "group_id": "group-egg",
                        "primary_segment_id": "seg-egg-1",
                        "segment_ids": ["seg-egg-1", "seg-egg-2"],
                        "question_kind": "DETAIL",
                        "answer_type": "free_text",
                        "required": True,
                        "label": "egg curry",
                        "question_focus": "vegetable inside egg curry",
                        "question_examples": ["egg curry with bottle gourd"],
                    },
                },
                "answers_by_question_id": {
                    "q-confirm-pita": {
                        "question_id": "q-confirm-pita",
                        "choice_id": "approve",
                        "value": True,
                    }
                },
                "pending_question_ids": ["q-confirm-pita", "q-detail-curry"],
                "remaining_required_question_ids": ["q-detail-curry"],
                "interview_messages": [],
            },
        )
        meal = SimpleNamespace(
            id="meal-partial",
            segments=[
                SimpleNamespace(id="seg-pita-1"),
                SimpleNamespace(id="seg-egg-1"),
                SimpleNamespace(id="seg-egg-2"),
            ],
        )
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
            message=SimpleNamespace(
                chat=SimpleNamespace(id="999"),
                text="egg curry with bottle gourd",
                message_id=444,
                reply_to_message=SimpleNamespace(message_id=321),
                reply_text=reply_text,
            ),
            callback_query=None,
        )
        context = SimpleNamespace(bot_data={})
        turn = SimpleNamespace(
            turn_action="ready_to_confirm",
            clarification_reason=None,
            conversation_summary="Resolved the last required clarification answer.",
            confirmation_items=[
                {
                    "group_id": "group-pita",
                    "primary_segment_id": "seg-pita-1",
                    "segment_id": "seg-pita-1",
                    "segment_ids": ["seg-pita-1"],
                    "name": "pita bread",
                    "source_type": "HOME",
                    "portion_bucket": "STANDARD",
                    "approval_status": "APPROVED",
                },
                {
                    "group_id": "group-egg",
                    "primary_segment_id": "seg-egg-1",
                    "segment_id": "seg-egg-1",
                    "segment_ids": ["seg-egg-1", "seg-egg-2"],
                    "name": "egg curry with bottle gourd",
                    "source_type": "HOME",
                    "portion_bucket": "STANDARD",
                    "approval_status": "CORRECTED",
                },
            ],
        )

        with (
            patch("bot.handlers.get_settings", return_value=SimpleNamespace(TELEGRAM_CHAT_ID="999", DATABASE_URL="postgresql://db")),
            patch("bot.handlers._make_session_factory", return_value=(engine, Mock(return_value=SessionContext()))),
            patch("bot.handlers._resolve_active_interview_for_text", AsyncMock(return_value=(interview, None))),
            patch("bot.handlers._run_meal_interview_turn", AsyncMock(return_value=turn), create=True) as run_turn,
            patch("bot.handlers.interview_service.persist_interview_step", AsyncMock()) as persist,
            patch("bot.handlers.interview_service.finalize_confirmed_interview", AsyncMock()) as finalize,
        ):
            await interview_text(update, context)

        run_turn.assert_awaited_once()
        finalize.assert_not_awaited()
        persist.assert_awaited_once()
        persisted_state = persist.await_args.kwargs["state"]
        self.assertEqual(persist.await_args.kwargs["user_payload"]["question_id"], "q-detail-curry")
        self.assertEqual(
            persisted_state["answers_by_question_id"]["q-detail-curry"]["name"],
            "egg curry with bottle gourd",
        )
        self.assertEqual(persisted_state["remaining_required_question_ids"], [])
        self.assertEqual(
            [item["name"] for item in persisted_state["confirmation_items"]],
            ["pita bread", "egg curry with bottle gourd"],
        )
        reply_text.assert_awaited_once()
        engine.dispose.assert_awaited_once()

    async def test_deterministic_confirmation_falls_back_to_structured_answers_when_resolver_fails(self) -> None:
        from bot import handlers

        interview = SimpleNamespace(
            id="interview-resolver-fallback",
            meal_log_id="meal-resolver-fallback",
            is_active=True,
            state_key="CONFIRMATION",
            current_prompt_payload={},
        )
        state = {
            "meal_id": "meal-resolver-fallback",
            "session_mode": "MEAL_INTERVIEW",
            "roadmap_step": "CONFIRMATION",
            "pending_question_ids": [],
            "remaining_required_question_ids": [],
            "current_question_id": "group-veg:source_origin",
            "current_question": {
                "question_id": "group-veg:source_origin",
                "prompt": "How should I treat the mixed vegetables for nutrition?",
            },
            "confirmation_items": [
                {
                    "group_id": "group-veg",
                    "segment_id": "seg-veg-1",
                    "primary_segment_id": "seg-veg-1",
                    "segment_ids": ["seg-veg-1"],
                    "name": "mixed vegetables",
                    "source_type": "HOME",
                    "portion_bucket": "STANDARD",
                    "approval_status": "CORRECTED",
                }
            ],
            "interview_messages": [],
        }
        session = AsyncMock()
        session.add = Mock()
        reply_text = AsyncMock()

        with (
            patch(
                "bot.handlers._run_meal_interview_turn",
                AsyncMock(side_effect=InterviewTurnValidationError("invalid resolver json")),
            ) as run_turn,
            patch("bot.handlers.interview_service.persist_interview_step", AsyncMock()) as persist,
        ):
            await handlers._resolve_deterministic_confirmation(
                session=session,
                interview=interview,
                state=state,
                user_payload={"question_id": "group-veg:source_origin", "value": "homemade"},
                latest_user_text="homemade",
                reply_callable=reply_text,
                settings=SimpleNamespace(),
            )

        run_turn.assert_awaited_once()
        persist.assert_awaited_once()
        persisted_state = persist.await_args.kwargs["state"]
        self.assertEqual(persisted_state["roadmap_step"], "CONFIRMATION")
        self.assertNotIn("current_question_id", persisted_state)
        self.assertEqual(persisted_state["current_question"]["roadmap_step"], "CONFIRMATION")
        self.assertEqual(persisted_state["last_turn_error"], "invalid resolver json")
        self.assertEqual(
            persisted_state["resolver_payload"]["turn_action"],
            "ready_to_confirm_fallback",
        )
        reply_text.assert_awaited_once()
        reply = reply_text.await_args.args[0]
        self.assertIn("Confirm before I write:", reply)
        self.assertIn("mixed vegetables", reply)
        self.assertNotIn("couldn't safely apply", reply.lower())

    async def test_meal_interview_text_handles_continue_interview_turns(self) -> None:
        from bot.handlers import interview_text

        interview = SimpleNamespace(
            id="interview-continue",
            meal_log_id="meal-clarify",
            is_active=True,
            state_key="INITIAL_QUESTION",
            current_prompt_payload={
                "meal_id": "meal-clarify",
                "session_mode": "MEAL_INTERVIEW",
                "roadmap_step": "INITIAL_QUESTION",
                "current_question": {"prompt": "What vegetable is in the egg curry?"},
                "unresolved_targets": [
                    {
                        "group_id": "group-egg",
                        "primary_segment_id": "seg-egg-1",
                        "segment_ids": ["seg-egg-1", "seg-egg-2"],
                        "label": "egg curry",
                    }
                ],
                "approval_candidates": [
                    {
                        "group_id": "group-pita",
                        "primary_segment_id": "seg-pita-1",
                        "segment_id": "seg-pita-1",
                        "proposed_name": "pita bread",
                    }
                ],
                "interview_messages": [],
            },
        )
        session = AsyncMock()
        session.add = Mock()
        engine = SimpleNamespace(dispose=AsyncMock())

        class SessionContext:
            async def __aenter__(self):
                return session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        reply_text = AsyncMock()
        update = SimpleNamespace(
            message=SimpleNamespace(chat=SimpleNamespace(id="999"), text="bottle gourd", reply_text=reply_text),
            callback_query=None,
        )
        context = SimpleNamespace(bot_data={})
        turn = InterviewTurnResult.model_validate(
            {
                "turn_action": "continue_interview",
                "assistant_prompt": "Do you mean egg curry with bottle gourd?",
                "clarification_reason": None,
                "conversation_summary": "Follow up on the curry vegetable.",
                "confirmation_items": [],
            }
        )

        with (
            patch("bot.handlers.get_settings", return_value=SimpleNamespace(TELEGRAM_CHAT_ID="999", DATABASE_URL="postgresql://db")),
            patch("bot.handlers._make_session_factory", return_value=(engine, Mock(return_value=SessionContext()))),
            patch("bot.handlers._resolve_active_interview_for_text", AsyncMock(return_value=(interview, None))),
            patch("bot.handlers._run_meal_interview_turn", AsyncMock(return_value=turn), create=True) as run_turn,
            patch("bot.handlers.interview_service.finalize_confirmed_interview", AsyncMock()) as finalize,
        ):
            await interview_text(update, context)

        run_turn.assert_awaited_once()
        finalize.assert_not_awaited()
        self.assertTrue(interview.is_active)
        self.assertEqual(interview.current_prompt_payload["conversation_summary"], "Follow up on the curry vegetable.")
        self.assertEqual(interview.current_prompt_payload["interview_messages"][-2]["content"], "bottle gourd")
        self.assertEqual(interview.current_prompt_payload["interview_messages"][-1]["content"], "Do you mean egg curry with bottle gourd?")
        reply_text.assert_awaited_once_with("Do you mean egg curry with bottle gourd?")
        session.commit.assert_awaited()
        engine.dispose.assert_awaited_once()

    async def test_meal_interview_text_handles_need_clarification_turns(self) -> None:
        from bot.handlers import interview_text

        interview = SimpleNamespace(
            id="interview-clarification",
            meal_log_id="meal-clarify",
            is_active=True,
            state_key="INITIAL_QUESTION",
            current_prompt_payload={
                "meal_id": "meal-clarify",
                "session_mode": "MEAL_INTERVIEW",
                "roadmap_step": "INITIAL_QUESTION",
                "current_question": {"prompt": "What vegetable is in the egg curry?"},
                "unresolved_targets": [
                    {
                        "group_id": "group-egg",
                        "primary_segment_id": "seg-egg-1",
                        "segment_ids": ["seg-egg-1", "seg-egg-2"],
                        "label": "egg curry",
                    }
                ],
                "approval_candidates": [
                    {
                        "group_id": "group-pita",
                        "primary_segment_id": "seg-pita-1",
                        "segment_id": "seg-pita-1",
                        "proposed_name": "pita bread",
                    }
                ],
                "interview_messages": [],
            },
        )
        session = AsyncMock()
        session.add = Mock()
        engine = SimpleNamespace(dispose=AsyncMock())

        class SessionContext:
            async def __aenter__(self):
                return session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        reply_text = AsyncMock()
        update = SimpleNamespace(
            message=SimpleNamespace(chat=SimpleNamespace(id="999"), text="bottle gourd", reply_text=reply_text),
            callback_query=None,
        )
        context = SimpleNamespace(bot_data={})
        turn = InterviewTurnResult.model_validate(
            {
                "turn_action": "need_clarification",
                "assistant_prompt": "Please answer just the bread type: pita bread or something else?",
                "clarification_reason": "Need a scoped bread answer.",
                "conversation_summary": "Need clarification about the bread type.",
                "confirmation_items": [],
            }
        )

        with (
            patch("bot.handlers.get_settings", return_value=SimpleNamespace(TELEGRAM_CHAT_ID="999", DATABASE_URL="postgresql://db")),
            patch("bot.handlers._make_session_factory", return_value=(engine, Mock(return_value=SessionContext()))),
            patch("bot.handlers._resolve_active_interview_for_text", AsyncMock(return_value=(interview, None))),
            patch("bot.handlers._run_meal_interview_turn", AsyncMock(return_value=turn), create=True) as run_turn,
            patch("bot.handlers.interview_service.finalize_confirmed_interview", AsyncMock()) as finalize,
        ):
            await interview_text(update, context)

        run_turn.assert_awaited_once()
        finalize.assert_not_awaited()
        self.assertTrue(interview.is_active)
        self.assertEqual(interview.current_prompt_payload["conversation_summary"], "Need clarification about the bread type.")
        self.assertEqual(interview.current_prompt_payload["interview_messages"][-2]["content"], "bottle gourd")
        self.assertEqual(
            interview.current_prompt_payload["interview_messages"][-1]["content"],
            "Please answer just the bread type: pita bread or something else?",
        )
        reply_text.assert_awaited_once_with("Please answer just the bread type: pita bread or something else?")
        session.commit.assert_awaited()
        engine.dispose.assert_awaited_once()

    async def test_meal_interview_text_routes_reply_to_matching_prompt_message_id(self) -> None:
        from bot.handlers import interview_text

        newest = SimpleNamespace(
            id="interview-newest",
            meal_log_id="meal-newest",
            is_active=True,
            last_bot_message_id=333,
            current_prompt_payload={
                "meal_id": "meal-newest",
                "session_mode": "MEAL_INTERVIEW",
                "roadmap_step": "INITIAL_QUESTION",
                "current_question": {"prompt": "What bread is this?"},
                "interview_messages": [],
            },
        )
        intended = SimpleNamespace(
            id="interview-intended",
            meal_log_id="meal-intended",
            is_active=True,
            last_bot_message_id=222,
            current_prompt_payload={
                "meal_id": "meal-intended",
                "session_mode": "MEAL_INTERVIEW",
                "roadmap_step": "INITIAL_QUESTION",
                "current_question": {"prompt": "What vegetable is in the egg curry?"},
                "interview_messages": [],
            },
        )
        session = AsyncMock()
        session.add = Mock()
        session.execute = AsyncMock(return_value=_ActiveInterviewQueryResult([newest, intended]))
        engine = SimpleNamespace(dispose=AsyncMock())

        class SessionContext:
            async def __aenter__(self):
                return session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        reply_text = AsyncMock()
        update = SimpleNamespace(
            message=SimpleNamespace(
                chat=SimpleNamespace(id="999"),
                text="bottle gourd",
                message_id=901,
                reply_to_message=SimpleNamespace(message_id=222),
                reply_text=reply_text,
            ),
            callback_query=None,
        )
        context = SimpleNamespace(bot_data={})
        turn = InterviewTurnResult.model_validate(
            {
                "turn_action": "continue_interview",
                "assistant_prompt": "Do you mean egg curry with bottle gourd?",
                "clarification_reason": None,
                "conversation_summary": "Follow up on the curry vegetable.",
                "confirmation_items": [],
            }
        )

        with (
            patch("bot.handlers.get_settings", return_value=SimpleNamespace(TELEGRAM_CHAT_ID="999", DATABASE_URL="postgresql://db")),
            patch("bot.handlers._make_session_factory", return_value=(engine, Mock(return_value=SessionContext()))),
            patch("bot.handlers._run_meal_interview_turn", AsyncMock(return_value=turn), create=True) as run_turn,
        ):
            await interview_text(update, context)

        self.assertEqual(run_turn.await_args.kwargs["state"]["meal_id"], "meal-intended")
        reply_text.assert_awaited_once_with("Do you mean egg curry with bottle gourd?")
        engine.dispose.assert_awaited_once()

    async def test_meal_interview_text_fails_closed_when_multiple_meal_sessions_are_ambiguous(self) -> None:
        from bot.handlers import interview_text

        newest = SimpleNamespace(
            id="interview-newest",
            meal_log_id="meal-newest",
            is_active=True,
            last_bot_message_id=333,
            current_prompt_payload={
                "meal_id": "meal-newest",
                "session_mode": "MEAL_INTERVIEW",
                "roadmap_step": "INITIAL_QUESTION",
                "current_question": {"prompt": "What bread is this?"},
                "interview_messages": [],
            },
        )
        older = SimpleNamespace(
            id="interview-older",
            meal_log_id="meal-older",
            is_active=True,
            last_bot_message_id=222,
            current_prompt_payload={
                "meal_id": "meal-older",
                "session_mode": "MEAL_INTERVIEW",
                "roadmap_step": "INITIAL_QUESTION",
                "current_question": {"prompt": "What sauce is on the pasta?"},
                "interview_messages": [],
            },
        )
        session = AsyncMock()
        session.add = Mock()
        session.execute = AsyncMock(return_value=_ActiveInterviewQueryResult([newest, older]))
        engine = SimpleNamespace(dispose=AsyncMock())

        class SessionContext:
            async def __aenter__(self):
                return session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        reply_text = AsyncMock()
        update = SimpleNamespace(
            message=SimpleNamespace(
                chat=SimpleNamespace(id="999"),
                text="yes",
                message_id=902,
                reply_to_message=None,
                reply_text=reply_text,
            ),
            callback_query=None,
        )
        context = SimpleNamespace(bot_data={})
        turn = InterviewTurnResult.model_validate(
            {
                "turn_action": "continue_interview",
                "assistant_prompt": "Which meal do you mean?",
                "clarification_reason": None,
                "conversation_summary": "This should not run when the reply is ambiguous.",
                "confirmation_items": [],
            }
        )

        with (
            patch("bot.handlers.get_settings", return_value=SimpleNamespace(TELEGRAM_CHAT_ID="999", DATABASE_URL="postgresql://db")),
            patch("bot.handlers._make_session_factory", return_value=(engine, Mock(return_value=SessionContext()))),
            patch("bot.handlers._run_meal_interview_turn", AsyncMock(return_value=turn), create=True) as run_turn,
        ):
            await interview_text(update, context)

        run_turn.assert_not_awaited()
        reply_text.assert_awaited_once_with(
            "Please reply to the specific meal prompt so I know which meal to update."
        )
        session.commit.assert_not_awaited()
        engine.dispose.assert_awaited_once()

    async def test_meal_interview_text_routes_ready_to_confirm_through_finalizer_with_approval_statuses(self) -> None:
        from bot.handlers import interview_text

        interview = SimpleNamespace(
            id="interview-ready",
            meal_log_id="meal-ready",
            is_active=True,
            state_key="INITIAL_QUESTION",
            current_prompt_payload={
                "meal_id": "meal-ready",
                "session_mode": "MEAL_INTERVIEW",
                "roadmap_step": "INITIAL_QUESTION",
                "current_question": {"prompt": "What vegetable is in the egg curry?"},
                "unresolved_targets": [
                    {
                        "group_id": "group-egg",
                        "primary_segment_id": "seg-egg-1",
                        "segment_ids": ["seg-egg-1", "seg-egg-2"],
                        "label": "egg curry",
                    }
                ],
                "approval_candidates": [
                    {
                        "group_id": "group-pita",
                        "primary_segment_id": "seg-pita-1",
                        "segment_id": "seg-pita-1",
                        "proposed_name": "pita bread",
                    },
                    {
                        "group_id": "group-chicken",
                        "primary_segment_id": "seg-chicken-1",
                        "segment_id": "seg-chicken-1",
                        "proposed_name": "chicken curry",
                    },
                ],
                "interview_messages": [],
            },
        )
        meal = SimpleNamespace(
            id="meal-ready",
            segments=[
                SimpleNamespace(id="seg-egg-1"),
                SimpleNamespace(id="seg-pita-1"),
                SimpleNamespace(id="seg-chicken-1"),
            ],
        )
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
            message=SimpleNamespace(
                chat=SimpleNamespace(id="999"),
                text="bottle gourd, pita is right, and chicken leg curry",
                reply_text=reply_text,
            ),
            callback_query=None,
        )
        context = SimpleNamespace(bot_data={})
        turn = InterviewTurnResult.model_validate(
            {
                "turn_action": "ready_to_confirm",
                "assistant_prompt": "Thanks, I have enough to log this meal.",
                "clarification_reason": None,
                "conversation_summary": "Resolved the curry detail, kept pita, and corrected the chicken curry label.",
                "confirmation_items": [
                    {
                        "group_id": "group-egg",
                        "primary_segment_id": "seg-egg-1",
                        "segment_id": "seg-egg-1",
                        "name": "egg curry with bottle gourd",
                        "source_type": "HOME",
                        "portion_bucket": "STANDARD",
                        "approval_status": "CORRECTED",
                    },
                    {
                        "group_id": "group-pita",
                        "primary_segment_id": "seg-pita-1",
                        "segment_id": "seg-pita-1",
                        "name": "pita bread",
                        "source_type": "HOME",
                        "portion_bucket": "STANDARD",
                        "approval_status": "APPROVED",
                    },
                    {
                        "group_id": "group-chicken",
                        "primary_segment_id": "seg-chicken-1",
                        "segment_id": "seg-chicken-1",
                        "name": "chicken leg curry",
                        "source_type": "HOME",
                        "portion_bucket": "STANDARD",
                        "approval_status": "CORRECTED",
                    },
                ],
            }
        )

        with (
            patch("bot.handlers.get_settings", return_value=SimpleNamespace(TELEGRAM_CHAT_ID="999", DATABASE_URL="postgresql://db")),
            patch("bot.handlers._make_session_factory", return_value=(engine, Mock(return_value=SessionContext()))),
            patch("bot.handlers._resolve_active_interview_for_text", AsyncMock(return_value=(interview, None))),
            patch("bot.handlers._run_meal_interview_turn", AsyncMock(return_value=turn), create=True) as run_turn,
            patch("bot.handlers.interview_service.finalize_confirmed_interview", AsyncMock(return_value=SimpleNamespace(meal_entries=[]))) as finalize,
        ):
            await interview_text(update, context)

        run_turn.assert_awaited_once()
        finalize.assert_awaited_once()
        confirmation_items = finalize.await_args.kwargs["confirmation_items"]
        self.assertEqual(
            [item["name"] for item in confirmation_items],
            ["egg curry with bottle gourd", "pita bread", "chicken leg curry"],
        )
        self.assertEqual(
            [item["approval_status"] for item in confirmation_items],
            ["CORRECTED", "APPROVED", "CORRECTED"],
        )
        self.assertFalse(interview.is_active)
        reply_text.assert_awaited_once_with("Meal confirmation saved.")
        session.commit.assert_awaited()
        engine.dispose.assert_awaited_once()

    async def test_meal_interview_text_fails_closed_after_turn_validation_error(self) -> None:
        from bot.handlers import interview_text

        original_confirmation = [
            {
                "group_id": "group-pita",
                "primary_segment_id": "seg-pita-1",
                "segment_id": "seg-pita-1",
                "name": "pita bread",
                "source_type": "HOME",
                "portion_bucket": "STANDARD",
                "approval_status": "APPROVED",
            }
        ]
        interview = SimpleNamespace(
            id="interview-invalid",
            meal_log_id="meal-invalid",
            is_active=True,
            state_key="INITIAL_QUESTION",
            current_prompt_payload={
                "meal_id": "meal-invalid",
                "session_mode": "MEAL_INTERVIEW",
                "roadmap_step": "INITIAL_QUESTION",
                "current_question": {"prompt": "What vegetable is in the egg curry?"},
                "confirmation_items": list(original_confirmation),
                "unresolved_targets": [
                    {
                        "group_id": "group-egg",
                        "primary_segment_id": "seg-egg-1",
                        "segment_ids": ["seg-egg-1", "seg-egg-2"],
                        "label": "egg curry",
                    }
                ],
                "approval_candidates": [
                    {
                        "group_id": "group-pita",
                        "primary_segment_id": "seg-pita-1",
                        "segment_id": "seg-pita-1",
                        "proposed_name": "pita bread",
                    }
                ],
                "interview_messages": [],
            },
        )
        session = AsyncMock()
        session.add = Mock()
        engine = SimpleNamespace(dispose=AsyncMock())

        class SessionContext:
            async def __aenter__(self):
                return session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        reply_text = AsyncMock()
        update = SimpleNamespace(
            message=SimpleNamespace(chat=SimpleNamespace(id="999"), text="bottle gourd", reply_text=reply_text),
            callback_query=None,
        )
        context = SimpleNamespace(bot_data={})

        with (
            patch("bot.handlers.get_settings", return_value=SimpleNamespace(TELEGRAM_CHAT_ID="999", DATABASE_URL="postgresql://db")),
            patch("bot.handlers._make_session_factory", return_value=(engine, Mock(return_value=SessionContext()))),
            patch("bot.handlers._resolve_active_interview_for_text", AsyncMock(return_value=(interview, None))),
            patch("bot.handlers._run_meal_interview_turn", AsyncMock(side_effect=InterviewTurnValidationError("coverage mismatch")), create=True) as run_turn,
            patch("bot.handlers.interview_service.finalize_confirmed_interview", AsyncMock()) as finalize,
        ):
            await interview_text(update, context)

        run_turn.assert_awaited_once()
        finalize.assert_not_awaited()
        self.assertTrue(interview.is_active)
        self.assertEqual(interview.current_prompt_payload["confirmation_items"], original_confirmation)
        reply_text.assert_awaited_once_with(
            "I couldn't safely apply that answer yet. Please answer the same meal question again: What vegetable is in the egg curry?"
        )
        session.commit.assert_awaited()
        engine.dispose.assert_awaited_once()


class OpenRouterContractTests(unittest.IsolatedAsyncioTestCase):
    def test_openrouter_client_uses_langfuse_openai_wrapper(self) -> None:
        from app.services import llm_client

        self.assertEqual(llm_client.OPENAI_CLIENT_WRAPPER, "langfuse.openai.AsyncOpenAI")

    async def test_chat_completion_forwards_multimodal_payload_and_extra_body(self) -> None:
        from app.config import get_settings
        from app.services import llm_client

        get_settings.cache_clear()
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
            patch.dict(
                os.environ,
                {
                    "DATABASE_URL": "postgresql+asyncpg://meal:pw@db:5432/meal",
                    "INGEST_SECRET": "secret",
                    "TELEGRAM_BOT_TOKEN": "token",
                    "TELEGRAM_CHAT_ID": "999",
                    "OPENROUTER_API_KEY": "router-key",
                    "LANGFUSE_PUBLIC_KEY": "pk-lf-test",
                    "LANGFUSE_SECRET_KEY": "sk-lf-test",
                    "LANGFUSE_BASE_URL": "https://cloud.langfuse.com",
                },
                clear=True,
            ),
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
        get_settings.cache_clear()

        self.assertEqual(result, {"ok": True})
        create_call.assert_awaited_once_with(
            model="google/gemma-4-31b-it",
            messages=messages,
            response_format=response_format,
            extra_body=extra_body,
            temperature=0.3,
        )


class SettingsContractTests(unittest.TestCase):
    def test_container_images_include_reasoning_taxonomy_config(self) -> None:
        from pathlib import Path

        api_dockerfile = Path("Dockerfile.api").read_text(encoding="utf-8")
        bot_dockerfile = Path("Dockerfile.bot").read_text(encoding="utf-8")

        self.assertIn("COPY config/ ./config/", api_dockerfile)
        self.assertIn("COPY config/ ./config/", bot_dockerfile)

    def test_settings_expose_explicit_finalizer_config(self) -> None:
        from app.config import Settings

        fields = Settings.model_fields

        self.assertIn("FINALIZER_MODEL", fields)
        self.assertIn("FINALIZER_GROUP_PARALLELISM", fields)
        self.assertEqual(fields["FINALIZER_MODEL"].default, "google/gemini-3-flash-preview")
        self.assertEqual(fields["FINALIZER_GROUP_PARALLELISM"].default, 4)

    def test_finalizer_group_parallelism_must_be_positive(self) -> None:
        from pydantic import ValidationError

        from app.config import Settings

        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql+asyncpg://meal:pw@db:5432/meal",
                "INGEST_SECRET": "secret",
                "TELEGRAM_BOT_TOKEN": "token",
                "TELEGRAM_CHAT_ID": "999",
                "OPENROUTER_API_KEY": "router-key",
                "LANGFUSE_PUBLIC_KEY": "pk-lf-test",
                "LANGFUSE_SECRET_KEY": "sk-lf-test",
                "LANGFUSE_BASE_URL": "https://cloud.langfuse.com",
                "FINALIZER_GROUP_PARALLELISM": "0",
            },
            clear=True,
        ):
            with self.assertRaises(ValidationError):
                Settings(_env_file=None)

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
                "LANGFUSE_PUBLIC_KEY": "pk-lf-test",
                "LANGFUSE_SECRET_KEY": "sk-lf-test",
                "LANGFUSE_BASE_URL": "https://cloud.langfuse.com",
                "POSTGRES_PASSWORD": "extra-value",
                "API_HOST_PORT": "18000",
            },
            clear=True,
        ):
            settings = Settings()

        self.assertEqual(settings.OPENROUTER_API_KEY, "router-key")
        self.assertEqual(settings.TELEGRAM_CHAT_ID, "999")
        self.assertEqual(settings.LANGFUSE_PUBLIC_KEY, "pk-lf-test")
        self.assertEqual(settings.LANGFUSE_BASE_URL, "https://cloud.langfuse.com")

    def test_langfuse_credentials_are_required(self) -> None:
        from pydantic import ValidationError

        from app.config import Settings

        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql+asyncpg://meal:pw@db:5432/meal",
                "INGEST_SECRET": "secret",
                "TELEGRAM_BOT_TOKEN": "token",
                "TELEGRAM_CHAT_ID": "999",
                "OPENROUTER_API_KEY": "router-key",
            },
            clear=True,
        ):
            with self.assertRaises(ValidationError):
                Settings(_env_file=None)


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
            ack_sent_at=None,
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
        self.assertIsNotNone(meal.ack_sent_at)

    async def test_poll_acknowledges_unacked_meal_that_already_advanced(self) -> None:
        from bot import polling

        meal = SimpleNamespace(
            id="advanced-meal",
            processing_status=MealProcessingStatus.MATCHING,
            ack_sent_at=None,
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

        bot = SimpleNamespace(send_message=AsyncMock())
        settings = SimpleNamespace(
            DATABASE_URL="postgresql+asyncpg://meal:pw@db:5432/meal",
            TELEGRAM_CHAT_ID="999",
            BOT_POLL_INTERVAL=3.0,
        )

        with (
            patch.object(polling, "create_async_engine", return_value=engine),
            patch.object(polling, "async_sessionmaker", return_value=Mock(return_value=SessionContext())),
            patch.object(polling.asyncio, "sleep", side_effect=asyncio.CancelledError),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await polling.poll_and_acknowledge(bot, settings, poll_interval=0.01)

        bot.send_message.assert_awaited_once_with(
            chat_id="999",
            text=polling.format_ack_message(meal.id),
        )
        session.commit.assert_awaited_once()
        engine.dispose.assert_awaited_once()
        self.assertEqual(meal.processing_status, MealProcessingStatus.MATCHING)
        self.assertIsNotNone(meal.ack_sent_at)

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

    def test_polling_module_removes_dead_grounding_worker_entry_points(self) -> None:
        from bot import polling

        source = Path(polling.__file__).read_text(encoding="utf-8")

        self.assertFalse(hasattr(polling, "poll_grounding_handoffs"))
        self.assertFalse(hasattr(polling, "poll_post_interview_grounding"))
        self.assertFalse(hasattr(polling, "_rebuild_grounding_match_results"))
        self.assertNotIn("async def poll_grounding_handoffs", source)
        self.assertNotIn("async def poll_post_interview_grounding", source)
        self.assertNotIn("def _rebuild_grounding_match_results", source)
        self.assertNotIn("GROUNDING_PENDING", source)
        self.assertNotIn("build_grounding_reasoning_state", source)

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

        self.assertEqual(session.commit.await_count, 1)
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

        self.assertEqual(session.commit.await_count, 1)
        self.assertEqual(meal.processing_status, MealProcessingStatus.SEGMENTING)
        bot.send_message.assert_not_awaited()

    async def test_poll_detect_keeps_single_worker_claim_while_detection_is_in_flight_d11_d12(self) -> None:
        from bot import polling

        meal = SimpleNamespace(
            id="meal-detect-claim",
            image_url="s3://bucket/photo.jpg",
            processing_status=MealProcessingStatus.DETECTING,
        )
        engine = SimpleNamespace(dispose=AsyncMock())
        detect_started = asyncio.Event()
        allow_detect_finish = asyncio.Event()
        duplicate_worker_entered = asyncio.Event()
        detect_call_count = 0
        claim_active = True

        class FakeSession:
            def __init__(self, worker_name: str) -> None:
                self.worker_name = worker_name
                self.execute_count = 0
                self.claimed_meal = False
                self.commit = AsyncMock(side_effect=self._commit)
                self.rollback = AsyncMock()
                self.merge = AsyncMock()

            async def _commit(self) -> None:
                nonlocal claim_active
                if self.claimed_meal:
                    claim_active = False

            async def execute(self, _statement):
                self.execute_count += 1
                if self.execute_count == 1:
                    if self.worker_name == "worker-1":
                        self.claimed_meal = True
                        return Mock(scalar_one_or_none=Mock(return_value=meal))
                    if meal.processing_status == MealProcessingStatus.DETECTING and not claim_active:
                        duplicate_worker_entered.set()
                        self.claimed_meal = True
                        return Mock(scalar_one_or_none=Mock(return_value=meal))
                    return Mock(scalar_one_or_none=Mock(return_value=None))
                raise asyncio.CancelledError

        class SessionContext:
            def __init__(self, session: FakeSession) -> None:
                self._session = session

            async def __aenter__(self):
                return self._session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        sessions = [FakeSession("worker-1"), FakeSession("worker-2")]
        session_factory = Mock(side_effect=[SessionContext(session) for session in sessions])
        bot = SimpleNamespace(send_message=AsyncMock())
        settings = SimpleNamespace(
            DATABASE_URL="postgresql+asyncpg://meal:pw@db:5432/meal",
            DETECT_MODEL="google/gemma-4-31b-it",
            BOT_POLL_INTERVAL=3.0,
        )

        async def _detect_food(*_args, **_kwargs):
            nonlocal detect_call_count
            detect_call_count += 1
            if detect_call_count > 1:
                duplicate_worker_entered.set()
            detect_started.set()
            await allow_detect_finish.wait()
            return {
                "next_action": "segment",
                "is_food": True,
                "confidence": 0.95,
            }

        async def _cancel_after_no_claim(_delay: float) -> None:
            raise asyncio.CancelledError

        with (
            patch.object(polling, "create_async_engine", return_value=engine),
            patch.object(polling, "async_sessionmaker", return_value=session_factory),
            patch.object(polling, "detect_food_photo", side_effect=_detect_food),
            patch.object(polling, "get_llm_client", return_value=object()),
            patch.object(polling, "_poll_sleep", side_effect=_cancel_after_no_claim),
        ):
            worker_one = asyncio.create_task(
                polling.poll_and_detect_food(bot, settings, poll_interval=0.01)
            )
            await detect_started.wait()
            worker_two = asyncio.create_task(
                polling.poll_and_detect_food(bot, settings, poll_interval=0.01)
            )
            await asyncio.sleep(0)
            allow_detect_finish.set()

            with self.assertRaises(asyncio.CancelledError):
                await worker_one
            with self.assertRaises(asyncio.CancelledError):
                await worker_two

        self.assertFalse(
            duplicate_worker_entered.is_set(),
            "second worker should not reacquire the same DETECTING meal while worker one still owns it",
        )
        self.assertEqual(detect_call_count, 1)
        self.assertEqual(meal.processing_status, MealProcessingStatus.SEGMENTING)

    async def test_poll_detect_marks_meal_failed_when_detection_raises(self) -> None:
        from bot import polling

        meal = SimpleNamespace(
            id="meal-detect-failure",
            image_url="s3://bucket/photo.jpg",
            processing_status=MealProcessingStatus.DETECTING,
        )
        session = AsyncMock()
        session.execute.return_value = Mock(
            scalar_one_or_none=Mock(return_value=meal),
        )
        recovery_session = AsyncMock()
        recovery_session.merge = AsyncMock()
        engine = SimpleNamespace(dispose=AsyncMock())

        class SessionContext:
            def __init__(self, current_session) -> None:
                self._session = current_session

            async def __aenter__(self):
                return self._session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        session_factory = Mock(
            side_effect=[
                SessionContext(session),
                SessionContext(recovery_session),
            ]
        )
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
                AsyncMock(side_effect=RuntimeError("detect failed")),
            ),
            patch.object(
                polling,
                "get_llm_client",
                return_value=SimpleNamespace(chat_completion=AsyncMock()),
            ),
            patch.object(
                polling.asyncio,
                "sleep",
                side_effect=asyncio.CancelledError,
            ),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await polling.poll_and_detect_food(bot, settings, poll_interval=0.01)

        self.assertEqual(meal.processing_status, MealProcessingStatus.FAILED)
        recovery_session.merge.assert_awaited_once()
        recovery_session.commit.assert_awaited_once()
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
                        SimpleNamespace(box_2d=[0.0, 0.0, 0.6, 0.6], confidence=0.9, label_hint="flatbread"),
                        SimpleNamespace(box_2d=[0.6, 0.6, 1.0, 1.0], confidence=0.9, label_hint="vegetable curry"),
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
        self.assertEqual(
            [segment.label for segment in session.add_all.call_args.args[0]],
            ["flatbread", "vegetable curry"],
        )
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
                AsyncMock(
                    return_value=[SimpleNamespace(box_2d=[0.0, 0.0, 0.6, 0.6], confidence=0.9, label_hint="pita bread")]
                ),
            ),
            patch.object(polling, "save_segment_crop", return_value=Path("/data/uploads/crops/aaa.jpg")),
            patch.object(
                polling,
                "get_llm_client",
                return_value=SimpleNamespace(chat_completion=AsyncMock()),
            ),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await polling.poll_and_segment_food(bot, settings, poll_interval=0.01)

        self.assertEqual(meal.processing_status, MealProcessingStatus.EMBEDDING)
        self.assertEqual(session.commit.await_count, 1)
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
            patch.object(polling, "format_soft_failure_message", return_value="soft fail"),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await polling.poll_and_segment_food(bot, settings, poll_interval=0.01)

        session.add_all.assert_not_called()
        self.assertEqual(session.commit.await_count, 1)
        self.assertEqual(meal.processing_status, MealProcessingStatus.FAILED)
        bot.send_message.assert_awaited_once_with(chat_id="999", text="soft fail")

    async def test_poll_segment_keeps_single_worker_claim_while_segmentation_and_crop_persistence_are_in_flight_d11_d12(self) -> None:
        from bot import polling

        meal = SimpleNamespace(
            id="meal-segment-claim",
            image_url="/data/uploads/meals/meal-segment-claim.jpg",
            processing_status=MealProcessingStatus.SEGMENTING,
        )
        engine = SimpleNamespace(dispose=AsyncMock())
        segment_started = asyncio.Event()
        allow_segment_finish = asyncio.Event()
        duplicate_worker_entered = asyncio.Event()
        segment_call_count = 0
        crop_call_count = 0
        claim_active = True

        class FakeSession:
            def __init__(self, worker_name: str) -> None:
                self.worker_name = worker_name
                self.execute_count = 0
                self.claimed_meal = False
                self.add = Mock()
                self.add_all = Mock()
                self.commit = AsyncMock(side_effect=self._commit)
                self.rollback = AsyncMock()
                self.merge = AsyncMock()

            async def _commit(self) -> None:
                nonlocal claim_active
                if self.claimed_meal:
                    claim_active = False

            async def execute(self, _statement):
                self.execute_count += 1
                if self.execute_count == 1:
                    if self.worker_name == "worker-1":
                        self.claimed_meal = True
                        return Mock(scalar_one_or_none=Mock(return_value=meal))
                    if meal.processing_status == MealProcessingStatus.SEGMENTING and not claim_active:
                        duplicate_worker_entered.set()
                        self.claimed_meal = True
                        return Mock(scalar_one_or_none=Mock(return_value=meal))
                    return Mock(scalar_one_or_none=Mock(return_value=None))
                raise asyncio.CancelledError

        class SessionContext:
            def __init__(self, session: FakeSession) -> None:
                self._session = session

            async def __aenter__(self):
                return self._session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        sessions = [FakeSession("worker-1"), FakeSession("worker-2")]
        session_factory = Mock(side_effect=[SessionContext(session) for session in sessions])
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

        async def _segment_food(*_args, **_kwargs):
            nonlocal segment_call_count
            segment_call_count += 1
            if segment_call_count > 1:
                duplicate_worker_entered.set()
            segment_started.set()
            await allow_segment_finish.wait()
            return [
                SimpleNamespace(box_2d=[0.0, 0.0, 1.0, 1.0], confidence=0.9, label_hint="protein bar")
            ]

        def _save_crop(*_args, **_kwargs):
            nonlocal crop_call_count
            crop_call_count += 1
            if crop_call_count > 1:
                duplicate_worker_entered.set()
            return Path("/data/uploads/crops/segment-claim.jpg")

        async def _cancel_after_no_claim(_delay: float) -> None:
            raise asyncio.CancelledError

        with (
            patch.object(polling, "create_async_engine", return_value=engine),
            patch.object(polling, "async_sessionmaker", return_value=session_factory),
            patch.object(polling, "segment_food_photo_with_retry", side_effect=_segment_food),
            patch.object(polling, "save_segment_crop", side_effect=_save_crop),
            patch.object(polling, "get_llm_client", return_value=object()),
            patch.object(polling, "_poll_sleep", side_effect=_cancel_after_no_claim),
        ):
            worker_one = asyncio.create_task(
                polling.poll_and_segment_food(bot, settings, poll_interval=0.01)
            )
            await segment_started.wait()
            worker_two = asyncio.create_task(
                polling.poll_and_segment_food(bot, settings, poll_interval=0.01)
            )
            await asyncio.sleep(0)
            allow_segment_finish.set()

            with self.assertRaises(asyncio.CancelledError):
                await worker_one
            with self.assertRaises(asyncio.CancelledError):
                await worker_two

        self.assertFalse(
            duplicate_worker_entered.is_set(),
            "second worker should not reacquire the same SEGMENTING meal while worker one still owns it",
        )
        self.assertEqual(segment_call_count, 1)
        self.assertEqual(crop_call_count, 1)
        self.assertEqual(meal.processing_status, MealProcessingStatus.EMBEDDING)

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
            MATCHING_MODEL="google/gemini-embedding-2",
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
            MATCHING_MODEL="google/gemini-embedding-2",
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

    async def test_poll_match_blocks_duplicate_reasoning_and_completion_side_effects_while_first_worker_runs_d11_d12(self) -> None:
        from bot import polling

        segment = SimpleNamespace(
            id="segment-1",
            cropped_image_url="/data/uploads/crops/seg-1.jpg",
            embedding=[0.2] * 1536,
            label="Daal Chawal",
        )
        meal = SimpleNamespace(
            id="meal-match-claim",
            processing_status=MealProcessingStatus.MATCHING,
        )
        engine = SimpleNamespace(dispose=AsyncMock())
        match_started = asyncio.Event()
        allow_match_finish = asyncio.Event()
        duplicate_worker_entered = asyncio.Event()
        pipeline_call_count = 0
        claim_active = True

        class FakeSession:
            def __init__(self, worker_name: str) -> None:
                self.worker_name = worker_name
                self.execute_count = 0
                self.claimed_meal = False
                self.add = Mock()
                self.add_all = Mock()
                self.commit = AsyncMock(side_effect=self._commit)
                self.rollback = AsyncMock()
                self.merge = AsyncMock()

            async def _commit(self) -> None:
                nonlocal claim_active
                if self.claimed_meal:
                    claim_active = False

            async def execute(self, _statement):
                self.execute_count += 1
                if self.execute_count == 1:
                    if self.worker_name == "worker-1":
                        self.claimed_meal = True
                        return Mock(scalar_one_or_none=Mock(return_value=meal))
                    if meal.processing_status == MealProcessingStatus.MATCHING and not claim_active:
                        duplicate_worker_entered.set()
                        self.claimed_meal = True
                        return Mock(scalar_one_or_none=Mock(return_value=meal))
                    return Mock(scalar_one_or_none=Mock(return_value=None))
                if self.execute_count == 2:
                    return Mock(
                        scalars=Mock(
                            return_value=Mock(
                                all=Mock(return_value=[segment]),
                            )
                        )
                    )
                raise asyncio.CancelledError

        class SessionContext:
            def __init__(self, session: FakeSession) -> None:
                self._session = session

            async def __aenter__(self):
                return self._session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        sessions = [FakeSession("worker-1"), FakeSession("worker-2")]
        session_factory = Mock(side_effect=[SessionContext(session) for session in sessions])
        bot = SimpleNamespace(send_message=AsyncMock())
        settings = SimpleNamespace(
            DATABASE_URL="postgresql+asyncpg://meal:pw@db:5432/meal",
            MATCHING_MODEL="google/gemini-embedding-2",
            TELEGRAM_CHAT_ID="999",
            BOT_POLL_INTERVAL=3.0,
        )

        async def _match_segment(**_kwargs):
            match_started.set()
            await allow_match_finish.wait()
            return (
                segment,
                SimpleNamespace(
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
                ),
            )

        async def _run_pipeline(**_kwargs):
            nonlocal pipeline_call_count
            pipeline_call_count += 1
            if pipeline_call_count > 1:
                duplicate_worker_entered.set()
            meal.processing_status = MealProcessingStatus.COMPLETED
            return (
                {"action": "AUTO_CONFIRM", "meal_state": "READY_TO_WRITE"},
                {
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
                },
            )

        async def _cancel_after_no_claim(_delay: float) -> None:
            raise asyncio.CancelledError

        with (
            patch.object(polling, "create_async_engine", return_value=engine),
            patch.object(polling, "async_sessionmaker", return_value=session_factory),
            patch.object(polling, "get_llm_client", return_value=object()),
            patch.object(polling, "_match_segment_with_isolated_session", side_effect=_match_segment),
            patch.object(polling, "_run_reasoning_pipeline", side_effect=_run_pipeline),
            patch.object(polling, "format_match_completion_message", return_value="meal completed"),
            patch.object(polling, "_poll_sleep", side_effect=_cancel_after_no_claim),
        ):
            worker_one = asyncio.create_task(
                polling.poll_and_match_food_segments(bot, settings, poll_interval=0.01)
            )
            await match_started.wait()
            worker_two = asyncio.create_task(
                polling.poll_and_match_food_segments(bot, settings, poll_interval=0.01)
            )
            await asyncio.sleep(0)
            allow_match_finish.set()

            with self.assertRaises(asyncio.CancelledError):
                await worker_one
            with self.assertRaises(asyncio.CancelledError):
                await worker_two

        self.assertFalse(
            duplicate_worker_entered.is_set(),
            "second worker should not rerun MATCHING/reasoning or send a duplicate completion notification",
        )
        self.assertEqual(pipeline_call_count, 1)
        bot.send_message.assert_awaited_once_with(chat_id="999", text="meal completed")

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
        bot_data: dict[str, object] = {
            "recent_entries": [
                {
                    "id": "older-entry",
                    "short_id": "older-en",
                    "food_name": "Older meal item",
                    "quantity_display": "1 bowl",
                    "meal_id": "older-meal",
                }
            ]
        }
        settings = SimpleNamespace(
            DATABASE_URL="postgresql+asyncpg://meal:pw@db:5432/meal",
            MATCHING_MODEL="google/gemini-embedding-2",
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

        self.assertEqual(bot_data["recent_entries"], [{"id": "entry-1", "short_id": "entry-1", "food_name": "Daal Chawal", "quantity_display": "1 bowl", "meal_id": "12345678-abcd-efgh"}])
        sent_text = bot.send_message.await_args.kwargs["text"]
        self.assertIn("Fix targets:", sent_text)
        self.assertIn("/fix 1", sent_text)
        self.assertIn("1. entry-1 Daal Chawal (1 bowl)", sent_text)
        self.assertNotIn("Older meal item", sent_text)

    def test_completion_items_use_written_diary_entry_food_item_when_match_result_has_no_visual(self) -> None:
        from bot import polling

        segment = SimpleNamespace(id="segment-pita")
        entry_food = SimpleNamespace(
            name="Whole Wheat Pita Bread",
            calories=None,
            protein_g=None,
            carbs_g=None,
            fat_g=None,
            is_verified=False,
        )
        meal_resolution = SimpleNamespace(
            meal_entries=[
                SimpleNamespace(
                    segment_id="segment-pita",
                    portion_bucket="STANDARD",
                    quantity_display="Standard",
                    food_item=entry_food,
                    identification_method="AUTO_CONFIRM",
                    is_verified=False,
                )
            ]
        )

        items = polling._completion_items_from_meal_resolution(
            match_results=[(segment, SimpleNamespace(food_visual=None))],
            meal_resolution=meal_resolution,
        )

        self.assertEqual(items[0].food_name, "Whole Wheat Pita Bread")
        self.assertEqual(items[0].quantity_label, "Standard")

    def test_recent_entries_use_written_diary_entry_food_item_when_match_result_has_no_visual(self) -> None:
        from bot import polling

        segment = SimpleNamespace(id="segment-pita")
        meal_resolution = SimpleNamespace(
            meal_entries=[
                SimpleNamespace(
                    id="entry-pita",
                    segment_id="segment-pita",
                    quantity_display="Standard",
                    food_item=SimpleNamespace(name="Whole Wheat Pita Bread"),
                )
            ]
        )

        entries = polling._recent_entries_from_meal_resolution(
            meal_id="meal-1",
            match_results=[(segment, SimpleNamespace(food_visual=None))],
            meal_resolution=meal_resolution,
        )

        self.assertEqual(entries[0]["food_name"], "Whole Wheat Pita Bread")

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
        poll_interview_reminders.assert_called_once_with(
            application.bot,
            settings,
            settings.BOT_POLL_INTERVAL,
        )
        create_task_mock.assert_called()
        self.assertEqual(len(created_coroutines), 6)
        self.assertIs(application.bot_data["poll_task"], fake_task)
        self.assertIs(application.bot_data["detect_task"], fake_task)
        self.assertIs(application.bot_data["segment_task"], fake_task)
        self.assertIs(application.bot_data["embed_task"], fake_task)
        self.assertIs(application.bot_data["match_task"], fake_task)
        self.assertIs(application.bot_data["interview_reminder_task"], fake_task)
        self.assertNotIn("grounding_handoff_task", application.bot_data)
        self.assertNotIn("post_interview_grounding_task", application.bot_data)

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
        application = SimpleNamespace(
            bot_data={
                "poll_task": poll_task,
                "detect_task": detect_task,
                "segment_task": segment_task,
            }
        )

        await bot_main.post_shutdown(application)

        poll_task.cancel.assert_called_once_with()
        self.assertTrue(poll_task.awaited)
        detect_task.cancel.assert_called_once_with()
        self.assertTrue(detect_task.awaited)
        segment_task.cancel.assert_called_once_with()
        self.assertTrue(segment_task.awaited)

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
            patch.object(bot_main.tracing_service, "validate_langfuse_required"),
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
