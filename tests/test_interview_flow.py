from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.models import MealProcessingStatus


class InterviewRoadmapTests(unittest.TestCase):
    def test_interview_roadmap_is_pinned_and_hybrid(self) -> None:
        from bot import handlers

        roadmap = handlers.get_interview_roadmap()

        self.assertEqual(roadmap[0], "INITIAL_QUESTION")
        self.assertEqual(roadmap[-1], "CONFIRMATION")
        self.assertIn("SOURCE_TYPE", roadmap)
        self.assertTrue(
            any(step in roadmap for step in ["RESTAURANT_NAME", "BRAND_NAME"]),
            "Roadmap must include restaurant/brand context branch",
        )

    def test_interview_callback_only_works_for_pinned_chat(self) -> None:
        from bot import handlers

        callback = SimpleNamespace(
            data="confirm:meal-1",
            message=SimpleNamespace(
                chat=SimpleNamespace(id="chat-not-pinned"),
            ),
        )
        session = SimpleNamespace(meal_id="meal-1", chat_id="chat-pinned")

        self.assertFalse(
            handlers.is_pinned_chat_update(callback, session),
            "Unpinned callbacks must be rejected",
        )
        callback.message.chat.id = "chat-pinned"
        self.assertTrue(
            handlers.is_pinned_chat_update(callback, session),
            "Pinned chat callback must be accepted",
        )


class Phase042PreflightHarnessTests(unittest.TestCase):
    def test_preflight_accepts_python_313_runtime(self) -> None:
        import scripts.assert_phase_04_2_preflight as preflight

        completed = SimpleNamespace(stdout='{"major": 3, "minor": 13}\n')

        with patch.object(preflight, "_run", return_value=completed):
            preflight._assert_python_version()


class InterviewProgressionTests(unittest.IsolatedAsyncioTestCase):
    def test_interview_proceeds_through_structured_steps_before_confirmation(self) -> None:
        from bot import handlers

        state = {
            "meal_id": "meal-1",
            "roadmap_step": "INITIAL_QUESTION",
            "pending_targets": [{"segment_id": "seg-1", "label": "Dal"}],
            "current_target_index": 0,
            "answers_by_segment": [],
            "interview_messages": [],
        }

        first = handlers.current_target_question(state)
        self.assertEqual(first["segment_id"], "seg-1")
        self.assertEqual(first["roadmap_step"], "INITIAL_QUESTION")

        state = handlers.complete_target_question(
            state,
            {
                "segment_id": "seg-1",
                "roadmap_step": "INITIAL_QUESTION",
                "name": "Dal Tadka",
            },
        )
        self.assertEqual(state["roadmap_step"], "FOOD_NAME")
        self.assertEqual(state["current_target_index"], 0)

        state = handlers.complete_target_question(
            state,
            {
                "segment_id": "seg-1",
                "roadmap_step": "FOOD_NAME",
                "name": "Dal Tadka",
            },
        )
        self.assertEqual(state["roadmap_step"], "SOURCE_TYPE")

        state = handlers.complete_target_question(
            state,
            {
                "segment_id": "seg-1",
                "roadmap_step": "SOURCE_TYPE",
                "source_type": "HOME",
            },
        )
        self.assertEqual(state["roadmap_step"], "PORTION_CONTEXT")

        state = handlers.complete_target_question(
            state,
            {
                "segment_id": "seg-1",
                "roadmap_step": "PORTION_CONTEXT",
                "portion_bucket": "SMALL",
                "quantity_display": "small bowl",
            },
        )
        self.assertEqual(state["roadmap_step"], "CONFIRMATION")
        self.assertEqual(state["confirmation_items"][0]["source_type"], "HOME")
        self.assertEqual(state["confirmation_items"][0]["portion_bucket"], "SMALL")

    def test_current_target_question_uses_locked_grouped_curry_detail_wording(self) -> None:
        from bot import handlers

        state = {
            "meal_id": "meal-1",
            "roadmap_step": "INITIAL_QUESTION",
            "pending_targets": [
                {
                    "group_id": "group-egg-curry",
                    "primary_segment_id": "seg-1",
                    "segment_ids": ["seg-1", "seg-2"],
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
            "interview_messages": [],
        }

        question = handlers.current_target_question(state)

        self.assertEqual(
            question["prompt"],
            "I can see the egg curry, but I can't tell which vegetable is in it. "
            "What should I call it? For example: egg curry with bottle gourd, "
            "egg curry with zucchini, or the name you normally use.",
        )
        self.assertEqual(question["group_id"], "group-egg-curry")
        self.assertEqual(question["primary_segment_id"], "seg-1")
        self.assertEqual(question["segment_ids"], ["seg-1", "seg-2"])
        lowered = question["prompt"].lower()
        self.assertNotIn("segment", lowered)
        self.assertNotIn("confidence", lowered)
        self.assertNotIn("nutrition-relevant detail", lowered)

    def test_current_target_question_prefers_first_remaining_required_clarification(self) -> None:
        from bot import handlers

        state = {
            "meal_id": "meal-question-state",
            "session_mode": "MEAL_INTERVIEW",
            "question_order": ["q-confirm-pita", "q-detail-curry", "q-source"],
            "questions_by_id": {
                "q-confirm-pita": {
                    "question_id": "q-confirm-pita",
                    "group_id": "group-pita",
                    "primary_segment_id": "seg-pita-1",
                    "segment_ids": ["seg-pita-1"],
                    "question_kind": "APPROVAL",
                    "answer_type": "confirm",
                    "required": False,
                    "prompt_summary": "Confirm the pita bread match.",
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
                "q-source": {
                    "question_id": "q-source",
                    "group_id": "group-egg",
                    "primary_segment_id": "seg-egg-1",
                    "segment_ids": ["seg-egg-1", "seg-egg-2"],
                    "question_kind": "SOURCE_ORIGIN",
                    "answer_type": "single_choice",
                    "required": True,
                    "label": "egg curry",
                    "choices": [
                        {"choice_id": "home", "label": "Homemade"},
                        {"choice_id": "restaurant", "label": "Restaurant"},
                    ],
                },
            },
            "answers_by_question_id": {
                "q-confirm-pita": {
                    "question_id": "q-confirm-pita",
                    "question_kind": "APPROVAL",
                    "choice_id": "approve",
                    "value": True,
                }
            },
            "pending_question_ids": ["q-confirm-pita", "q-detail-curry", "q-source"],
            "remaining_required_question_ids": ["q-detail-curry", "q-source"],
            "interview_messages": [],
        }

        prompt = handlers.current_target_question(state)

        self.assertIn("question_id", prompt)
        self.assertEqual(prompt.get("question_id"), "q-detail-curry")
        self.assertEqual(prompt.get("group_id"), "group-egg")
        self.assertEqual(prompt.get("answer_type"), "free_text")
        self.assertEqual(prompt.get("segment_ids"), ["seg-egg-1", "seg-egg-2"])
        prompt_text = str(prompt.get("prompt") or "").lower()
        self.assertIn("egg curry", prompt_text)
        self.assertNotIn("pita bread", prompt_text)

    def test_current_target_question_uses_contract_owned_user_prompt_for_affirmation_action(self) -> None:
        from bot import handlers

        state = {
            "meal_id": "meal-contract-owned-prompt",
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
        }

        prompt = handlers.current_target_question(state)

        self.assertEqual(
            prompt["prompt"],
            "Does Chicken Curry with Drumstick look right for this part of the meal?",
        )
        self.assertEqual(prompt["question_id"], "q-affirm-chicken")
        self.assertEqual(prompt["group_id"], "group-chicken")
        self.assertEqual(prompt["answer_type"], "confirm")
        self.assertEqual(prompt["question_kind"], "AFFIRMATION")

    def test_interview_moves_to_next_target_only_after_portion_context(self) -> None:
        from bot import handlers

        state = {
            "meal_id": "meal-1",
            "roadmap_step": "PORTION_CONTEXT",
            "pending_targets": [
                {"segment_id": "seg-1", "label": "Dal"},
                {"segment_id": "seg-2", "label": "Chickpea Curry"},
            ],
            "current_target_index": 0,
            "answers_by_segment": [
                {"segment_id": "seg-1", "name": "Dal", "source_type": "HOME"},
            ],
            "interview_messages": [],
        }

        state = handlers.complete_target_question(
            state,
            {
                "segment_id": "seg-1",
                "roadmap_step": "PORTION_CONTEXT",
                "portion_bucket": "STANDARD",
                "quantity_display": "1 bowl",
            },
        )

        self.assertEqual(state["current_target_index"], 1)
        self.assertEqual(state["roadmap_step"], "INITIAL_QUESTION")
        self.assertEqual(state["pending_targets"][state["current_target_index"]]["segment_id"], "seg-2")

    def test_free_text_parser_falls_back_before_failing(self) -> None:
        from bot import handlers

        parsed = handlers.parse_interview_text(
            text="actually it's a Chicken Biryani",
            context={"roadmap_step": "FOOD_NAME", "segment_id": "seg-1"},
        )

        self.assertEqual(parsed["segment_id"], "seg-1")
        self.assertEqual(parsed["value"], "Chicken Biryani")
        self.assertIn("fallback", parsed)
        self.assertTrue(parsed["fallback"])

    def test_reminder_is_issued_once_after_threshold(self) -> None:
        from bot import handlers

        base_time = datetime(2026, 5, 28, 10, 0, 0)
        interview_state = {
            "meal_id": "meal-1",
            "reminder_scheduled": False,
            "last_prompted_at": base_time - timedelta(minutes=10),
            "last_reminder_at": None,
        }

        self.assertTrue(
            handlers.should_send_single_reminder(
                interview_state,
                now=base_time,
                reminder_delay_minutes=5,
            )
        )

        interview_state["last_reminder_at"] = base_time
        self.assertFalse(
            handlers.should_send_single_reminder(
                interview_state,
                now=base_time,
                reminder_delay_minutes=5,
            )
        )

    def test_best_effort_unresolved_closeout_is_persisted(self) -> None:
        from bot import handlers

        unresolved = {
            "meal_id": "meal-1",
            "processing_status": "INTERVIEWING",
            "unresolved_items": [
                {"segment_id": "seg-1", "label": "Pita Bread"},
                {"segment_id": "seg-2", "label": "Unknown"},
            ],
        }

        closeout = handlers.build_best_effort_closeout(unresolved)

        self.assertEqual(closeout["meal_id"], "meal-1")
        self.assertTrue(closeout["best_effort"])  # D-43 through D-54
        self.assertFalse(closeout["is_verified"])
        self.assertEqual(closeout["unresolved_count"], 2)

    async def test_persist_interview_step_records_session_state_and_messages(self) -> None:
        from app.services import interview_service

        session = SimpleNamespace(add=Mock(), commit=AsyncMock())
        interview = SimpleNamespace(
            id="interview-1",
            state_key="INITIAL_QUESTION",
            current_prompt_payload={},
        )
        state = {
            "roadmap_step": "FOOD_NAME",
            "interview_messages": [],
        }
        answer = {
            "segment_id": "seg-1",
            "roadmap_step": "INITIAL_QUESTION",
            "name": "Dal",
        }
        next_prompt = {
            "segment_id": "seg-1",
            "roadmap_step": "FOOD_NAME",
            "prompt": "What exact name should I log?",
        }

        await interview_service.persist_interview_step(
            session=session,
            interview=interview,
            state=state,
            user_payload=answer,
            next_prompt=next_prompt,
        )

        self.assertEqual(interview.current_prompt_payload, state)
        self.assertEqual(interview.state_key, "FOOD_NAME")
        self.assertEqual(session.add.call_args_list[0].args[0], interview)
        added_messages = [call.args[0] for call in session.add.call_args_list[1:]]
        self.assertEqual(added_messages[0].role, "user")
        self.assertEqual(added_messages[0].payload["name"], "Dal")
        self.assertEqual(added_messages[1].role, "bot")
        self.assertEqual(added_messages[1].payload["prompt"]["roadmap_step"], "FOOD_NAME")
        session.commit.assert_awaited_once()

    async def test_prepare_interview_session_payload_is_json_serializable(self) -> None:
        from app.models import InterviewSession
        from app.services import interview_service

        class EmptyResult:
            def scalar_one_or_none(self):
                return None

        class FakeSession:
            def __init__(self) -> None:
                self.added = []

            async def execute(self, _statement):
                return EmptyResult()

            def add(self, item) -> None:
                self.added.append(item)

        session = FakeSession()

        interview = await interview_service.prepare_interview_session(
            session=session,
            meal=SimpleNamespace(id="meal-json"),
            segments=[SimpleNamespace(id="seg-json", label="mystery curry")],
            chat_id="chat-json",
        )

        self.assertIsInstance(interview, InterviewSession)
        json.dumps(interview.current_prompt_payload)
        self.assertIsInstance(interview.current_prompt_payload["last_prompted_at"], str)

    async def test_persist_interview_step_payload_is_json_serializable(self) -> None:
        from app.services import interview_service

        session = SimpleNamespace(add=Mock(), commit=AsyncMock())
        interview = SimpleNamespace(
            id="interview-json-step",
            state_key="INITIAL_QUESTION",
            current_prompt_payload={},
        )
        state = {
            "roadmap_step": "FOOD_NAME",
            "last_prompted_at": datetime.now(UTC),
            "interview_messages": [],
        }

        await interview_service.persist_interview_step(
            session=session,
            interview=interview,
            state=state,
            user_payload={"name": "Dal"},
        )

        json.dumps(interview.current_prompt_payload)
        self.assertIsInstance(interview.current_prompt_payload["last_prompted_at"], str)

    async def test_confirm_callback_requires_matching_persisted_interview_session(self) -> None:
        from bot.handlers import interview_callback

        callback = SimpleNamespace(
            data="confirm:meal-from-callback",
            message=SimpleNamespace(chat=SimpleNamespace(id="999"), reply_text=AsyncMock()),
            answer=AsyncMock(),
        )
        update = SimpleNamespace(message=None, callback_query=callback)
        context = SimpleNamespace(bot_data={})
        session = AsyncMock()
        engine = SimpleNamespace(dispose=AsyncMock())

        class SessionContext:
            async def __aenter__(self):
                return session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        with (
            patch("bot.handlers.get_settings", return_value=SimpleNamespace(TELEGRAM_CHAT_ID="999", DATABASE_URL="postgresql://db")),
            patch("bot.handlers._make_session_factory", return_value=(engine, Mock(return_value=SessionContext()))),
            patch("bot.handlers._load_active_interview", AsyncMock(return_value=None)) as load_interview,
            patch("bot.handlers._finalize_interview_confirmation", AsyncMock()) as finalize,
        ):
            await interview_callback(update, context)

        load_interview.assert_awaited_once()
        self.assertEqual(load_interview.await_args.kwargs["chat_id"], "999")
        self.assertEqual(load_interview.await_args.kwargs["meal_id"], "meal-from-callback")
        finalize.assert_not_awaited()
        callback.answer.assert_awaited_once()
        engine.dispose.assert_awaited_once()


class InterviewConfirmationEditTests(unittest.TestCase):
    def test_item_specific_confirmation_edit_updates_one_entry(self) -> None:
        from bot import handlers

        confirmation = [
            {"segment_id": "seg-1", "name": "Dal"},
            {"segment_id": "seg-2", "name": "Rice"},
        ]
        edit_payload = [
            {"segment_id": "seg-1", "name": "Split Lentil Curry"}
        ]

        after_edit = handlers.apply_confirmation_edits(confirmation, edit_payload)

        self.assertEqual(after_edit[0]["name"], "Split Lentil Curry")
        self.assertEqual(after_edit[1]["name"], "Rice")

    def test_free_text_bulk_correction_parses_multi_item_updates(self) -> None:
        from bot import handlers

        text = "first is paneer, second is lentil soup"
        parsed = handlers.parse_confirmation_bulk_text(
            text=text,
            confirmation_items=[{"segment_id": "seg-1"}, {"segment_id": "seg-2"}],
        )

        self.assertTrue(parsed["applied_bulk"])
        self.assertEqual(len(parsed["updates"]), 2)
        self.assertEqual(parsed["updates"][0]["segment_id"], "seg-1")
        self.assertEqual(parsed["updates"][1]["segment_id"], "seg-2")

    def test_plain_confirmation_text_does_not_edit_first_item(self) -> None:
        from bot import handlers

        parsed = handlers.parse_confirmation_bulk_text(
            text="Bottle gourd",
            confirmation_items=[
                {"segment_id": "seg-bread", "name": "White khubz"},
                {"segment_id": "seg-chicken", "name": "Chicken curry"},
                {"segment_id": "seg-egg", "name": "Egg and vegetable curry"},
            ],
        )

        self.assertFalse(parsed["applied_bulk"])
        self.assertEqual(parsed["updates"], [])

    def test_confirmation_is_replayed_after_edit(self) -> None:
        from bot import handlers

        edited_confirmation = handlers.apply_confirmation_edits(
            [
                {"segment_id": "seg-1", "name": "Dal"},
                {"segment_id": "seg-2", "name": "Rice"},
            ],
            [{"segment_id": "seg-1", "name": "Green Lentils"}],
        )
        message = handlers.build_confirmation_message(edited_confirmation)

        self.assertIn("Green Lentils", message)
        self.assertIn("Dal -> Green Lentils", message)
        self.assertIn("seg-2: Rice", message)

    def test_all_wrong_prompt_is_photo_aware(self) -> None:
        from bot import handlers

        prompt = handlers.build_all_wrong_prompt(
            segment={
                "segment_id": "seg-2",
                "index": 2,
                "label": "Chicken Curry",
            },
            evidence="I only see grilled chicken chunks and yellow sauce",
        )

        self.assertIn("seg-2", prompt)
        self.assertIn("Chicken Curry", prompt)
        self.assertIn("grilled chicken chunks", prompt)


class InterviewPersistencePrepTests(unittest.IsolatedAsyncioTestCase):
    async def test_prepare_interview_session_consumes_synthesized_source_actions_with_stable_segment_ids(self) -> None:
        from app.services import interview_service, reasoning_service

        class EmptyResult:
            def scalar_one_or_none(self):
                return None

        class FakeSession:
            async def execute(self, _statement):
                return EmptyResult()

            def add(self, _item) -> None:
                return None

        reasoning_payload = {
            "action": "AUTO_CONFIRM",
            "meal_state": "READY_TO_WRITE",
            "trace_id": "trace-interview-handoff-source",
            "food_group_count": 1,
            "segment_count": 1,
            "decision_rationale": "visual-only bread can be named but has no usable learned history",
            "gate_reason": "",
            "food_groups": [
                {
                    "group_id": "group-flatbread",
                    "group_label": "flatbread",
                    "group_action": "AUTO_CONFIRM",
                    "group_state": "READY_TO_WRITE",
                    "primary_segment_id": "seg-flatbread-1",
                    "segment_ids": ["seg-flatbread-1", "seg-flatbread-2"],
                    "selected_candidate_id": "candidate-khubz",
                    "visual_evidence": ["flatbread on plate"],
                    "missing_evidence": [],
                    "decision_rationale": "visual-only bread looks like khubz",
                    "gate_reason": "",
                    "question_kind": "NONE",
                    "question_focus": "",
                    "question_examples": [],
                    "learned_match_count": 0,
                    "top_3": [
                        {
                            "candidate_id": "candidate-khubz",
                            "label": "White Bread (Khubz)",
                            "identity_confidence": 0.98,
                            "quantity_confidence": 0.7,
                            "match_consistency_confidence": 0.98,
                            "visual_evidence": ["flatbread on plate"],
                            "missing_evidence": [],
                            "specificity": "high",
                            "nutrition_relevance": "medium",
                            "source": "visual_reasoning",
                            "decision_rationale": "best bread match",
                        },
                        {
                            "candidate_id": "candidate-pita",
                            "label": "Pita Bread",
                            "identity_confidence": 0.73,
                            "quantity_confidence": 0.7,
                            "match_consistency_confidence": 0.73,
                            "visual_evidence": ["flatbread on plate"],
                            "missing_evidence": [],
                            "specificity": "high",
                            "nutrition_relevance": "medium",
                            "source": "visual_reasoning",
                            "decision_rationale": "fallback bread match",
                        },
                    ],
                }
            ],
        }

        gated = reasoning_service.evaluate_reasoning_gate(reasoning_payload=reasoning_payload)
        meal = SimpleNamespace(id="meal-source-handoff", reasoning_state_json={"meal_reasoning": gated})
        interview = await interview_service.prepare_interview_session(
            session=FakeSession(),
            meal=meal,
            segments=[SimpleNamespace(id="seg-flatbread-1", label="flatbread")],
            chat_id="chat-source-handoff",
        )

        state = interview.current_prompt_payload
        self.assertEqual(
            state["question_order"],
            ["group-flatbread:affirmation", "group-flatbread:source_origin"],
        )
        self.assertEqual(state["current_question"]["question_id"], "group-flatbread:affirmation")
        self.assertEqual(
            state["questions_by_id"]["group-flatbread:source_origin"]["segment_ids"],
            ["seg-flatbread-1", "seg-flatbread-2"],
        )

    def test_build_interview_turn_state_includes_unresolved_and_approval_groups(self) -> None:
        from app.services import interview_service

        build_interview_turn_state = getattr(interview_service, "build_interview_turn_state", None)
        self.assertTrue(callable(build_interview_turn_state), "build_interview_turn_state() must exist for Phase 04.2")
        if not callable(build_interview_turn_state):
            return

        meal = SimpleNamespace(
            id="meal-threaded",
            reasoning_state_json={
                "meal_reasoning": {
                    "trace_id": "trace-interview-1",
                    "decision_rationale": "Need the curry vegetable but the bread and chicken look ready to approve.",
                    "food_groups": [
                        {
                            "group_id": "group-egg-curry",
                            "group_label": "egg curry",
                            "group_action": "INTERVIEW",
                            "group_state": "PENDING_INTERVIEW",
                            "primary_segment_id": "seg-egg-1",
                            "segment_ids": ["seg-egg-1", "seg-egg-2"],
                            "missing_evidence": ["vegetable inside curry"],
                            "question_kind": "DETAIL",
                            "question_focus": "vegetable inside egg curry",
                            "question_examples": [
                                "egg curry with bottle gourd",
                                "egg curry with zucchini",
                            ],
                            "top_3": [
                                {"label": "egg curry with bottle gourd"},
                                {"label": "egg curry with zucchini"},
                                {"label": "egg curry with spinach"},
                            ],
                        },
                        {
                            "group_id": "group-pita",
                            "group_label": "pita bread",
                            "group_action": "AUTO_CONFIRM_WITH_TRACE",
                            "group_state": "READY_TO_WRITE",
                            "primary_segment_id": "seg-bread-1",
                            "segment_ids": ["seg-bread-1"],
                            "missing_evidence": [],
                            "selected_candidate_id": "candidate-pita",
                            "decision_rationale": "Strong bread match.",
                            "top_3": [
                                {"candidate_id": "candidate-pita", "label": "pita bread"},
                                {"candidate_id": "candidate-naan", "label": "naan bread"},
                                {"candidate_id": "candidate-flatbread", "label": "flatbread"},
                            ],
                        },
                        {
                            "group_id": "group-chicken-curry",
                            "group_label": "chicken curry",
                            "group_action": "AUTO_CONFIRM",
                            "group_state": "READY_TO_WRITE",
                            "primary_segment_id": "seg-chicken-1",
                            "segment_ids": ["seg-chicken-1"],
                            "missing_evidence": [],
                            "selected_candidate_id": "candidate-chicken-curry",
                            "decision_rationale": "High-confidence curry match.",
                            "top_3": [
                                {"candidate_id": "candidate-chicken-curry", "label": "chicken curry"},
                                {"candidate_id": "candidate-chicken-leg-curry", "label": "chicken leg curry"},
                                {"candidate_id": "candidate-chicken-stew", "label": "chicken stew"},
                            ],
                        },
                    ],
                }
            },
        )
        segments = [
            SimpleNamespace(id="seg-egg-1", label="egg curry", cropped_image_url="/tmp/egg-1.jpg"),
            SimpleNamespace(id="seg-egg-2", label="egg vegetable curry", cropped_image_url="/tmp/egg-2.jpg"),
            SimpleNamespace(id="seg-bread-1", label="bread", cropped_image_url="/tmp/pita.jpg"),
            SimpleNamespace(id="seg-chicken-1", label="chicken curry", cropped_image_url="/tmp/chicken.jpg"),
        ]

        state = build_interview_turn_state(meal=meal, segments=segments)

        self.assertEqual(state["meal_id"], "meal-threaded")
        self.assertEqual([item["group_id"] for item in state["unresolved_targets"]], ["group-egg-curry"])
        self.assertEqual(
            [item["group_id"] for item in state["approval_candidates"]],
            ["group-pita", "group-chicken-curry"],
        )
        self.assertEqual(
            state["unresolved_targets"][0]["candidate_choices"],
            [
                "egg curry with bottle gourd",
                "egg curry with zucchini",
                "egg curry with spinach",
            ],
        )
        self.assertEqual(state["unresolved_targets"][0]["missing_evidence"], ["vegetable inside curry"])
        self.assertEqual(
            [item["proposed_name"] for item in state["approval_candidates"]],
            ["pita bread", "chicken curry"],
        )
        self.assertIn("trace-interview-1", state["reasoning_summary"])
        self.assertIn("seg-egg-1", state["segment_refs"])
        self.assertEqual(state["segment_refs"]["seg-bread-1"]["crop_path"], "/tmp/pita.jpg")
        self.assertIn("egg curry", state["current_question"]["prompt"].lower())
        self.assertIn("pita bread", state["current_question"]["prompt"].lower())
        self.assertIn("chicken curry", state["current_question"]["prompt"].lower())

    def test_prepare_interview_session_targets_unresolved_food_groups_before_quantity(self) -> None:
        import asyncio

        from app.services import interview_service

        class EmptyResult:
            def scalar_one_or_none(self):
                return None

        class FakeSession:
            def __init__(self) -> None:
                self.added = []

            async def execute(self, _statement):
                return EmptyResult()

            def add(self, item) -> None:
                self.added.append(item)

        session = FakeSession()
        meal = SimpleNamespace(
            id="meal-grouped",
            reasoning_state_json={
                "food_groups": [
                    {
                        "group_id": "group-egg-curry",
                        "label": "egg curry",
                        "action": "INTERVIEW",
                        "state": "UNRESOLVED",
                        "primary_segment_id": "seg-egg-1",
                        "segment_ids": ["seg-egg-1", "seg-egg-2"],
                        "question_kind": "DETAIL",
                        "question_focus": "vegetable inside egg curry",
                        "question_examples": [
                            "egg curry with bottle gourd",
                            "egg curry with zucchini",
                        ],
                    },
                    {
                        "group_id": "group-pita",
                        "label": "pita bread",
                        "action": "INTERVIEW",
                        "state": "UNRESOLVED",
                        "primary_segment_id": "seg-bread-1",
                        "segment_ids": ["seg-bread-1", "seg-bread-2"],
                        "question_kind": "QUANTITY",
                        "question_focus": "portion size",
                        "question_examples": ["1 pita", "2 small pieces"],
                    },
                ]
            },
        )
        segments = [
            SimpleNamespace(id="seg-egg-1", label="egg and vegetable curry"),
            SimpleNamespace(id="seg-egg-2", label="egg and zucchini curry"),
            SimpleNamespace(id="seg-bread-1", label="pita bread"),
            SimpleNamespace(id="seg-bread-2", label="bread"),
        ]

        interview = asyncio.run(
            interview_service.prepare_interview_session(
                session=session,
                meal=meal,
                segments=segments,
                chat_id="chat-grouped",
            )
        )

        pending_targets = interview.current_prompt_payload["pending_targets"]
        self.assertEqual(
            pending_targets,
            [
                {
                    "group_id": "group-egg-curry",
                    "primary_segment_id": "seg-egg-1",
                    "segment_ids": ["seg-egg-1", "seg-egg-2"],
                    "label": "egg curry",
                    "question_kind": "DETAIL",
                    "question_focus": "vegetable inside egg curry",
                    "question_examples": [
                        "egg curry with bottle gourd",
                        "egg curry with zucchini",
                    ],
                },
                {
                    "group_id": "group-pita",
                    "primary_segment_id": "seg-bread-1",
                    "segment_ids": ["seg-bread-1", "seg-bread-2"],
                    "label": "pita bread",
                    "question_kind": "QUANTITY",
                    "question_focus": "portion size",
                    "question_examples": ["1 pita", "2 small pieces"],
                },
            ],
        )
        self.assertEqual(
            interview.current_prompt_payload["pending_targets"][0],
            {
                "group_id": "group-egg-curry",
                "primary_segment_id": "seg-egg-1",
                "segment_ids": ["seg-egg-1", "seg-egg-2"],
                "label": "egg curry",
                "question_kind": "DETAIL",
                "question_focus": "vegetable inside egg curry",
                "question_examples": [
                    "egg curry with bottle gourd",
                    "egg curry with zucchini",
                ],
            },
        )
        self.assertEqual(
            interview.current_prompt_payload["pending_targets"][1].get("question_kind"),
            "QUANTITY",
        )

    def test_prepare_interview_session_reads_persisted_group_fields(self) -> None:
        import asyncio

        from app.services import interview_service

        class EmptyResult:
            def scalar_one_or_none(self):
                return None

        class FakeSession:
            async def execute(self, _statement):
                return EmptyResult()

            def add(self, _item) -> None:
                return None

        meal = SimpleNamespace(
            id="meal-nested-grouped",
            reasoning_state_json={
                "meal_reasoning": {
                    "food_groups": [
                        {
                            "group_id": "group-egg-curry",
                            "group_label": "egg curry",
                            "group_action": "ASK_CHOICE",
                            "group_state": "PENDING_INTERVIEW",
                            "primary_segment_id": "seg-egg-1",
                            "segment_ids": ["seg-egg-1", "seg-egg-2"],
                            "question_kind": "DETAIL",
                            "question_focus": "vegetable inside egg curry",
                            "question_examples": ["egg curry with bottle gourd"],
                        }
                    ]
                }
            },
        )

        interview = asyncio.run(
            interview_service.prepare_interview_session(
                session=FakeSession(),
                meal=meal,
                segments=[SimpleNamespace(id="seg-egg-1", label="raw egg segment")],
                chat_id="chat-nested",
            )
        )

        target = interview.current_prompt_payload["pending_targets"][0]
        self.assertEqual(target["group_id"], "group-egg-curry")
        self.assertEqual(target["label"], "egg curry")
        self.assertEqual(target["question_focus"], "vegetable inside egg curry")

    def test_prepare_interview_session_seeds_question_indexed_state_from_group_actions(self) -> None:
        import asyncio

        from app.services import interview_service

        class EmptyResult:
            def scalar_one_or_none(self):
                return None

        class FakeSession:
            async def execute(self, _statement):
                return EmptyResult()

            def add(self, _item) -> None:
                return None

        meal = SimpleNamespace(
            id="meal-schema-state",
            reasoning_state_json={
                "meal_reasoning": {
                    "food_groups": [
                        {
                            "group_id": "group-pita",
                            "group_label": "pita bread",
                            "primary_segment_id": "seg-pita-1",
                            "segment_ids": ["seg-pita-1"],
                            "clarification_actions": [
                                {
                                    "question_id": "q-confirm-pita",
                                    "type": "AFFIRMATION",
                                    "kind": "APPROVAL",
                                    "answer_type": "confirm",
                                    "required": False,
                                    "choices": [
                                        {"choice_id": "approve", "label": "Yes"},
                                        {"choice_id": "correct", "label": "No"},
                                    ],
                                }
                            ],
                        },
                        {
                            "group_id": "group-egg",
                            "group_label": "egg curry",
                            "primary_segment_id": "seg-egg-1",
                            "segment_ids": ["seg-egg-1", "seg-egg-2"],
                            "clarification_actions": [
                                {
                                    "question_id": "q-detail-curry",
                                    "type": "FREE_TEXT",
                                    "kind": "DETAIL",
                                    "answer_type": "free_text",
                                    "required": True,
                                    "question_focus": "vegetable inside egg curry",
                                }
                            ],
                        },
                    ]
                }
            },
        )

        interview = asyncio.run(
            interview_service.prepare_interview_session(
                session=FakeSession(),
                meal=meal,
                segments=[SimpleNamespace(id="seg-egg-1", label="egg curry")],
                chat_id="chat-schema",
            )
        )

        payload = interview.current_prompt_payload

        self.assertIn("question_order", payload)
        self.assertEqual(payload.get("question_order"), ["q-confirm-pita", "q-detail-curry"])
        self.assertEqual(payload.get("pending_question_ids"), ["q-confirm-pita", "q-detail-curry"])
        self.assertEqual(payload.get("remaining_required_question_ids"), ["q-detail-curry"])
        self.assertEqual(payload.get("answers_by_question_id"), {})
        questions_by_id = payload.get("questions_by_id") or {}
        self.assertIn("q-detail-curry", questions_by_id)
        self.assertEqual(questions_by_id.get("q-detail-curry", {}).get("answer_type"), "free_text")

    def test_affirmation_required_stays_required_and_renders_before_source_origin(self) -> None:
        from app.services import interview_service

        meal = SimpleNamespace(
            id="meal-affirm-first",
            reasoning_state_json={
                "meal_reasoning": {
                    "decision_rationale": "Need explicit confirmation for a new visual-only item.",
                    "food_groups": [
                        {
                            "group_id": "group-chicken",
                            "group_label": "Chicken curry",
                            "group_action": "AFFIRMATION_REQUIRED",
                            "group_state": "PENDING_INTERVIEW",
                            "primary_segment_id": "seg-chicken-1",
                            "segment_ids": ["seg-chicken-1"],
                            "clarification_actions": [
                                {
                                    "question_id": "q-affirm-chicken",
                                    "type": "AFFIRMATION",
                                    "kind": "AFFIRMATION",
                                    "answer_type": "confirm",
                                    "required": True,
                                    "user_prompt": "I think this is Chicken curry. Is that right?",
                                    "choices": [
                                        {"label": "Yes", "quick_prompt": "Yes"},
                                        {"label": "No", "quick_prompt": "No"},
                                    ],
                                },
                                {
                                    "question_id": "q-source-chicken",
                                    "type": "SOURCE_ORIGIN",
                                    "kind": "SOURCE_ORIGIN",
                                    "answer_type": "single_choice",
                                    "required": True,
                                    "user_prompt": "Was this homemade, packaged, or restaurant?",
                                    "choices": [
                                        {"label": "homemade", "quick_prompt": "homemade"},
                                        {"label": "restaurant", "quick_prompt": "restaurant"},
                                    ],
                                },
                            ],
                        }
                    ],
                }
            },
        )

        state = interview_service.build_interview_turn_state(
            meal=meal,
            segments=[SimpleNamespace(id="seg-chicken-1", label="chicken curry")],
        )

        self.assertEqual(state["question_order"], ["q-affirm-chicken", "q-source-chicken"])
        self.assertEqual(state["remaining_required_question_ids"][0], "q-affirm-chicken")
        self.assertEqual(state["current_question"]["question_id"], "q-affirm-chicken")
        self.assertTrue(state["questions_by_id"]["q-affirm-chicken"]["required"])
        self.assertEqual(
            [choice["choice_id"] for choice in state["questions_by_id"]["q-affirm-chicken"]["choices"]],
            ["approve", "correct"],
        )

    def test_identity_quantity_and_source_actions_render_for_one_group(self) -> None:
        from app.services import interview_service

        meal = SimpleNamespace(
            id="meal-composed-actions",
            reasoning_state_json={
                "meal_reasoning": {
                    "decision_rationale": "One item needs identity, quantity, and source before logging.",
                    "food_groups": [
                        {
                            "group_id": "group-flatbread",
                            "group_label": "Flatbread",
                            "group_actions": [
                                "IDENTITY_CLARIFICATION_REQUIRED",
                                "ASK_QUANTITY",
                                "ASK_SOURCE_ORIGIN",
                            ],
                            "group_state": "PENDING_INTERVIEW",
                            "primary_segment_id": "seg-flatbread-1",
                            "segment_ids": ["seg-flatbread-1"],
                            "clarification_actions": [
                                {
                                    "question_id": "q-flatbread-identity",
                                    "type": "CHOICE",
                                    "kind": "IDENTITY",
                                    "answer_type": "single_choice",
                                    "required": True,
                                    "user_prompt": "Which bread is this?",
                                    "choices": [
                                        {"label": "Khubz", "quick_prompt": "Khubz"},
                                        {"label": "Pita", "quick_prompt": "Pita"},
                                        {"label": "Roti", "quick_prompt": "Roti"},
                                    ],
                                },
                                {
                                    "question_id": "q-flatbread-quantity",
                                    "type": "QUANTITY",
                                    "kind": "QUANTITY",
                                    "answer_type": "free_text",
                                    "required": True,
                                    "user_prompt": "How many pieces of flatbread are there?",
                                    "choices": [],
                                },
                                {
                                    "question_id": "q-flatbread-source",
                                    "type": "SOURCE_ORIGIN",
                                    "kind": "SOURCE_ORIGIN",
                                    "answer_type": "single_choice",
                                    "required": True,
                                    "user_prompt": "Was this homemade, packaged, or restaurant?",
                                    "choices": [
                                        {"label": "homemade", "quick_prompt": "homemade"},
                                        {"label": "restaurant", "quick_prompt": "restaurant"},
                                    ],
                                },
                            ],
                        }
                    ],
                }
            },
        )

        state = interview_service.build_interview_turn_state(
            meal=meal,
            segments=[SimpleNamespace(id="seg-flatbread-1", label="flatbread")],
        )

        self.assertEqual(
            state["question_order"],
            ["q-flatbread-identity", "q-flatbread-quantity", "q-flatbread-source"],
        )
        self.assertEqual(
            state["remaining_required_question_ids"],
            ["q-flatbread-identity", "q-flatbread-quantity", "q-flatbread-source"],
        )
        self.assertEqual(state["current_question"]["question_id"], "q-flatbread-identity")
        self.assertEqual(
            [state["questions_by_id"][question_id]["question_kind"] for question_id in state["question_order"]],
            ["IDENTITY", "QUANTITY", "SOURCE_ORIGIN"],
        )

    def test_confirmation_items_are_built_from_structured_answers(self) -> None:
        from app.services import interview_service

        items = interview_service.confirmation_items_from_state(
            {
                "pending_targets": [{"segment_id": "seg-1", "label": "Bar"}],
                "answers_by_segment": [
                    {
                        "segment_id": "seg-1",
                        "name": "Protein Bar",
                        "source_type": "PACKAGED",
                        "brand_name": "Acme",
                        "portion_bucket": "SMALL",
                        "quantity_display": "1 bar",
                    }
                ],
            }
        )

        self.assertEqual(items[0]["name"], "Protein Bar")
        self.assertEqual(items[0]["brand_name"], "Acme")
        self.assertEqual(items[0]["portion_bucket"], "SMALL")

    def test_confirmation_items_from_state_preserve_explicit_approval_statuses(self) -> None:
        from app.services import interview_service

        state = {
            "pending_targets": [
                {"group_id": "group-egg", "segment_id": "seg-egg-1"},
                {"group_id": "group-pita", "segment_id": "seg-pita-1"},
            ],
            "answers_by_segment": [
                {
                    "group_id": "group-egg",
                    "primary_segment_id": "seg-egg-1",
                    "segment_id": "seg-egg-1",
                    "name": "egg curry with bottle gourd",
                    "source_type": "HOME",
                    "portion_bucket": "STANDARD",
                },
                {
                    "group_id": "group-pita",
                    "primary_segment_id": "seg-pita-1",
                    "segment_id": "seg-pita-1",
                    "name": "pita bread",
                    "source_type": "HOME",
                    "portion_bucket": "STANDARD",
                },
            ],
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
            ],
        }

        items = interview_service.confirmation_items_from_state(state)

        self.assertEqual(
            items,
            state["confirmation_items"],
            "Explicit ready_to_confirm items must survive unchanged, including approval_status coverage.",
        )

    def test_grounding_handoff_state_preserves_confirmation_context(self) -> None:
        from app.services import interview_service

        state = interview_service.build_grounding_reasoning_state(
            confirmation_items=[
                {
                    "segment_id": "seg-1",
                    "name": "Protein Bar",
                    "source_type": "PACKAGED",
                    "brand_name": "Acme",
                }
            ],
            status="PENDING_HANDOFF",
            prior_state={"existing": "keep"},
        )

        self.assertEqual(state["existing"], "keep")
        self.assertTrue(state["grounding_required"])
        self.assertTrue(state["post_interview_grounding"])
        self.assertEqual(state["grounding_status"], "PENDING_HANDOFF")
        self.assertEqual(state["confirmation_items"][0]["brand_name"], "Acme")

    def test_packaged_answer_creates_grounding_prep_resolution(self) -> None:
        from app.services import interview_service

        resolution = interview_service.final_resolution_from_confirmation(
            item={
                "segment_id": "seg-1",
                "name": "Protein Bar",
                "source_type": "PACKAGED",
                "brand_name": "Acme",
                "quantity_display": "1 bar",
            },
        )

        self.assertEqual(resolution.food.canonical_name, "Protein Bar")
        self.assertEqual(resolution.food.source_type, "PACKAGED")
        self.assertEqual(resolution.food.brand_name, "Acme")
        self.assertTrue(resolution.food.needs_grounding)
        self.assertEqual(resolution.food.llm_reasoning, "NEEDS_GROUNDING")
        self.assertEqual(resolution.quantity_json["grounding_prep"]["status"], "NEEDS_GROUNDING")

    async def test_finalize_confirmed_interview_keeps_packaged_grounding_handoff_with_finalized_metadata(self) -> None:
        from app.services import interview_service

        meal = SimpleNamespace(
            id="meal-packaged-handoff",
            processing_status=MealProcessingStatus.INTERVIEWING,
            reasoning_state_json={
                "meal_reasoning": {
                    "food_groups": [
                        {
                            "group_id": "group-bar",
                            "group_label": "protein bar",
                            "question_kind": "IDENTITY",
                            "group_actions": ["ASK_SOURCE_ORIGIN"],
                            "primary_segment_id": "seg-bar-1",
                            "segment_ids": ["seg-bar-1"],
                            "top_3": [
                                {
                                    "candidate_id": "candidate-bar",
                                    "label": "Protein Bar",
                                    "source_type": "PACKAGED",
                                }
                            ],
                        }
                    ]
                },
                "answers_by_question_id": {
                    "q-brand": {
                        "question_id": "q-brand",
                        "group_id": "group-bar",
                        "question_kind": "SOURCE_ORIGIN",
                        "value": "Acme",
                    }
                },
            },
            last_stage_started_at=None,
        )
        segment = SimpleNamespace(
            id="seg-bar-1",
            cropped_image_url="/data/uploads/crops/seg-bar-1.jpg",
            embedding=[0.5, 0.6, 0.7],
        )
        session = AsyncMock()
        session.add = Mock()
        confirmation_items = [
            {
                "group_id": "group-bar",
                "primary_segment_id": "seg-bar-1",
                "segment_id": "seg-bar-1",
                "segment_ids": ["seg-bar-1"],
                "name": "Acme",
                "source_type": "PACKAGED",
                "portion_bucket": "STANDARD",
                "approval_status": "CORRECTED",
                "brand_name": "Acme",
                "quantity_display": "1 bar",
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
                                        "group_id": "group-bar",
                                        "primary_segment_id": "seg-bar-1",
                                        "segment_ids": ["seg-bar-1"],
                                        "final_name": "Acme Protein Bar",
                                        "aliases": ["Protein Bar"],
                                        "source_type": "PACKAGED",
                                        "portion_bucket": "STANDARD",
                                        "quantity_display": "1 bar",
                                        "quantity_json": {
                                            "quantity": 1,
                                            "unit": "bar",
                                            "portion_bucket": "STANDARD",
                                        },
                                        "food_item_id": None,
                                        "brand_name": "Acme",
                                        "restaurant_name": None,
                                        "correction_note": None,
                                        "supporting_details": ["store-bought packaged item"],
                                    }
                                )
                            }
                        }
                    ]
                }
            )
        )

        with patch.object(interview_service, "get_llm_client", return_value=llm_client, create=True):
            result = await interview_service.finalize_confirmed_interview(
                session=session,
                meal=meal,
                confirmation_items=confirmation_items,
                segments=[segment],
            )

        self.assertTrue(result["grounding_required"])
        self.assertEqual(meal.processing_status, MealProcessingStatus.INTERVIEWING)
        self.assertTrue(meal.reasoning_state_json["grounding_required"])
        self.assertTrue(meal.reasoning_state_json["post_interview_grounding"])
        self.assertEqual(meal.reasoning_state_json["handoff_target"], "poll_post_interview_grounding")
        self.assertEqual(
            meal.reasoning_state_json["confirmation_items"][0]["name"],
            "Acme Protein Bar",
        )
        self.assertEqual(meal.reasoning_state_json["confirmation_items"][0]["brand_name"], "Acme")
        self.assertEqual(meal.reasoning_state_json["finalizer_groups"][0]["status"], "SUCCEEDED")

    async def test_finalize_confirmed_interview_degrades_malformed_finalizer_json_to_best_effort_save(self) -> None:
        from app.services import interview_service

        meal = SimpleNamespace(
            id="meal-finalizer-degraded",
            processing_status=MealProcessingStatus.INTERVIEWING,
            reasoning_state_json={
                "meal_reasoning": {
                    "food_groups": [
                        {
                            "group_id": "group-curry",
                            "group_label": "chicken curry",
                            "question_kind": "DETAIL",
                            "question_focus": "style of the curry",
                            "group_actions": ["IDENTITY_CLARIFICATION_REQUIRED"],
                            "primary_segment_id": "seg-curry-1",
                            "segment_ids": ["seg-curry-1"],
                        }
                    ]
                }
            },
            last_stage_started_at=None,
        )
        segment = SimpleNamespace(
            id="seg-curry-1",
            cropped_image_url="/data/uploads/crops/seg-curry-1.jpg",
            embedding=[0.11, 0.22, 0.33],
        )
        session = AsyncMock()
        session.add = Mock()
        confirmation_items = [
            {
                "group_id": "group-curry",
                "primary_segment_id": "seg-curry-1",
                "segment_id": "seg-curry-1",
                "segment_ids": ["seg-curry-1"],
                "name": "Green masala",
                "source_type": "HOME",
                "portion_bucket": "STANDARD",
                "approval_status": "CORRECTED",
                "quantity_display": "1 bowl",
            }
        ]
        llm_client = SimpleNamespace(
            chat_completion=AsyncMock(
                return_value={"choices": [{"message": {"content": "{\"bad\":true}"}}]}
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

        final_segment = captured["final_segments"][0]
        self.assertEqual(final_segment.identification_method, "INTERVIEW_BEST_EFFORT")
        self.assertEqual(final_segment.food.canonical_name, "chicken curry (Green masala)")
        self.assertTrue(final_segment.create_food_visual)
        self.assertEqual(captured["reasoning_state_json"]["finalizer_groups"][0]["status"], "DEGRADED")

    def test_source_origin_store_bought_preserves_state_and_requires_grounding(self) -> None:
        from app.services import interview_service

        state = {
            "question_order": ["q-source"],
            "questions_by_id": {
                "q-source": {
                    "question_id": "q-source",
                    "group_id": "group-flatbread",
                    "primary_segment_id": "seg-flatbread",
                    "segment_ids": ["seg-flatbread"],
                    "question_kind": "SOURCE_ORIGIN",
                    "answer_type": "single_choice",
                    "required": True,
                    "label": "flatbread",
                    "choices": [
                        {
                            "choice_id": "STORE_BOUGHT_PREPARED",
                            "label": "store bought",
                            "value": "STORE_BOUGHT_PREPARED",
                        }
                    ],
                }
            },
            "answers_by_question_id": {},
            "pending_question_ids": ["q-source"],
            "remaining_required_question_ids": ["q-source"],
            "interview_messages": [],
        }

        answer = interview_service._parse_clarification_text(  # noqa: SLF001
            text="store bought",
            context=state["questions_by_id"]["q-source"],
        )
        updated = interview_service._apply_clarification_answer(state, answer)  # noqa: SLF001
        self.assertEqual(updated["current_question"]["question_id"], "group-flatbread:brand_name")
        brand_answer = interview_service._parse_clarification_text(  # noqa: SLF001
            text="Acme",
            context=updated["questions_by_id"]["group-flatbread:brand_name"],
        )
        completed = interview_service._apply_clarification_answer(updated, brand_answer)  # noqa: SLF001
        item = completed["confirmation_items"][0]
        resolution = interview_service.final_resolution_from_confirmation(item=item)

        self.assertEqual(item["source_origin_state"], "STORE_BOUGHT_PREPARED")
        self.assertEqual(item["source_type"], "PACKAGED")
        self.assertEqual(item["brand_name"], "Acme")
        self.assertTrue(resolution.food.needs_grounding)
        self.assertFalse(resolution.food.is_verified)

    def test_identity_choice_preserves_selected_candidate_food_item_id(self) -> None:
        from app.services import interview_service

        state = {
            "question_order": ["q-choice"],
            "questions_by_id": {
                "q-choice": {
                    "question_id": "q-choice",
                    "group_id": "group-bread",
                    "primary_segment_id": "seg-bread",
                    "segment_ids": ["seg-bread"],
                    "question_kind": "IDENTITY",
                    "answer_type": "single_choice",
                    "required": True,
                    "label": "bread",
                    "choices": [
                        {
                            "choice_id": "candidate-khubz",
                            "label": "White Khubz",
                            "value": "White Khubz",
                            "food_item_id": "food-khubz",
                            "source_type": "HOME",
                        }
                    ],
                }
            },
            "answers_by_question_id": {},
            "pending_question_ids": ["q-choice"],
            "remaining_required_question_ids": ["q-choice"],
            "interview_messages": [],
        }

        answer = interview_service._parse_clarification_text(  # noqa: SLF001
            text="White Khubz",
            context=state["questions_by_id"]["q-choice"],
        )
        updated = interview_service._apply_clarification_answer(state, answer)  # noqa: SLF001
        item = updated["confirmation_items"][0]
        resolution = interview_service.final_resolution_from_confirmation(item=item)

        self.assertEqual(item["food_item_id"], "food-khubz")
        self.assertEqual(resolution.food.food_item_id, "food-khubz")

    def test_existing_food_item_id_is_preserved_for_resolution_reuse(self) -> None:
        from app.services import interview_service

        resolution = interview_service.final_resolution_from_confirmation(
            item={
                "segment_id": "seg-2",
                "food_item_id": "food-123",
                "name": "Dal",
                "source_type": "HOME",
                "portion_bucket": "large",
            },
        )

        self.assertEqual(resolution.food.food_item_id, "food-123")
        self.assertEqual(resolution.portion_bucket, "LARGE")
        self.assertEqual(resolution.identification_method, "INTERVIEW")

    def test_numpy_segment_embedding_is_preserved_for_visual_learning(self) -> None:
        import numpy as np

        from app.services import interview_service

        segment = SimpleNamespace(
            id="seg-visual",
            cropped_image_url="/data/uploads/crops/seg-visual.jpg",
            embedding=np.array([0.1, 0.2, 0.3], dtype=np.float32),
        )

        resolution = interview_service.final_resolution_from_confirmation(
            item={
                "segment_id": "seg-visual",
                "name": "Egg Curry with Bottle Gourd",
                "source_type": "HOME",
                "portion_bucket": "standard",
            },
            segment=segment,
        )

        self.assertEqual(len(resolution.segment_embedding or []), 3)
        self.assertAlmostEqual((resolution.segment_embedding or [])[0], 0.1)
        self.assertAlmostEqual((resolution.segment_embedding or [])[1], 0.2)
        self.assertAlmostEqual((resolution.segment_embedding or [])[2], 0.3)
        self.assertEqual(resolution.segment_cropped_image_url, "/data/uploads/crops/seg-visual.jpg")
        self.assertTrue(resolution.create_food_visual)

    def test_identity_answer_inserts_learned_source_affirmation_before_existing_follow_up(self) -> None:
        from app.services import interview_service

        state = {
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
                    "source_trigger_reason": "Strong packaged history exists for the selected identity.",
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
                            "food_item_id": "food-khubz",
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
        }

        answer = interview_service._parse_clarification_text(  # noqa: SLF001
            text="White Khubz",
            context=state["questions_by_id"]["q-identity"],
        )
        updated = interview_service._apply_clarification_answer(state, answer)  # noqa: SLF001

        self.assertEqual(
            updated["question_order"],
            ["q-identity", "group-bread:source_affirmation", "q-quantity"],
        )
        self.assertEqual(
            updated["remaining_required_question_ids"],
            ["group-bread:source_affirmation", "q-quantity"],
        )
        self.assertEqual(updated["current_question"]["question_id"], "group-bread:source_affirmation")
        self.assertEqual(updated["current_question"]["answer_type"], "confirm")
        self.assertIn("Acme", updated["current_question"]["prompt"])

    def test_identity_answer_inserts_generic_source_question_when_policy_requires_fallback(self) -> None:
        from app.services import interview_service

        state = {
            "question_order": ["q-identity", "q-quantity"],
            "questions_by_id": {
                "q-identity": {
                    "question_id": "q-identity",
                    "group_id": "group-wrap",
                    "primary_segment_id": "seg-wrap-1",
                    "segment_ids": ["seg-wrap-1"],
                    "question_kind": "IDENTITY",
                    "answer_type": "single_choice",
                    "required": True,
                    "label": "wrap",
                    "source_question_policy": "ask_generic",
                    "source_trigger_reason": "Few learned matches require a direct source question.",
                    "choices": [
                        {
                            "choice_id": "candidate-wrap",
                            "label": "Chicken Wrap",
                            "value": "Chicken Wrap",
                        }
                    ],
                },
                "q-quantity": {
                    "question_id": "q-quantity",
                    "group_id": "group-wrap",
                    "primary_segment_id": "seg-wrap-1",
                    "segment_ids": ["seg-wrap-1"],
                    "question_kind": "QUANTITY",
                    "answer_type": "free_text",
                    "required": True,
                    "label": "wrap",
                },
            },
            "answers_by_question_id": {},
            "pending_question_ids": ["q-identity", "q-quantity"],
            "remaining_required_question_ids": ["q-identity", "q-quantity"],
            "interview_messages": [],
        }

        answer = interview_service._parse_clarification_text(  # noqa: SLF001
            text="Chicken Wrap",
            context=state["questions_by_id"]["q-identity"],
        )
        updated = interview_service._apply_clarification_answer(state, answer)  # noqa: SLF001

        self.assertEqual(
            updated["question_order"],
            ["q-identity", "group-wrap:source_origin", "q-quantity"],
        )
        self.assertEqual(updated["current_question"]["question_id"], "group-wrap:source_origin")
        self.assertEqual(updated["current_question"]["question_kind"], "SOURCE_ORIGIN")
        self.assertFalse(updated["questions_by_id"]["group-wrap:source_origin"]["allow_other"])

    def test_rejected_source_affirmation_prompts_same_group_source_correction(self) -> None:
        from app.services import interview_service

        state = {
            "question_order": ["group-bread:source_affirmation"],
            "questions_by_id": {
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
                    "source_type": "PACKAGED",
                    "source_origin_state": "PACKAGED_BRANDED",
                    "brand_name": "Acme",
                    "user_prompt": "Was the White Khubz packaged from Acme?",
                    "choices": [
                        {"choice_id": "approve", "label": "Yes"},
                        {"choice_id": "correct", "label": "No"},
                    ],
                }
            },
            "answers_by_question_id": {},
            "pending_question_ids": ["group-bread:source_affirmation"],
            "remaining_required_question_ids": ["group-bread:source_affirmation"],
            "interview_messages": [],
        }

        answer = interview_service._parse_clarification_text(  # noqa: SLF001
            text="No",
            context=state["questions_by_id"]["group-bread:source_affirmation"],
        )
        updated = interview_service._apply_clarification_answer(state, answer)  # noqa: SLF001

        self.assertEqual(updated["current_question"]["group_id"], "group-bread")
        self.assertEqual(updated["current_question"]["answer_type"], "free_text")
        self.assertIn("source", updated["current_question"]["prompt"].lower())
        self.assertEqual(
            updated["current_question"]["correction_for_question_id"],
            "group-bread:source_affirmation",
        )

    def test_packaged_source_answer_inserts_brand_follow_up_and_preserves_segment_ids(self) -> None:
        from app.services import interview_service

        state = {
            "question_order": ["q-source"],
            "questions_by_id": {
                "q-source": {
                    "question_id": "q-source",
                    "group_id": "group-bar",
                    "primary_segment_id": "seg-bar-1",
                    "segment_ids": ["seg-bar-1", "seg-bar-2"],
                    "question_kind": "SOURCE_ORIGIN",
                    "answer_type": "single_choice",
                    "required": True,
                    "label": "protein bar",
                    "choices": [
                        {
                            "choice_id": "PACKAGED_BRANDED",
                            "label": "packaged",
                            "value": "PACKAGED_BRANDED",
                        }
                    ],
                }
            },
            "answers_by_question_id": {},
            "pending_question_ids": ["q-source"],
            "remaining_required_question_ids": ["q-source"],
            "interview_messages": [],
        }

        source_answer = interview_service._parse_clarification_text(  # noqa: SLF001
            text="packaged",
            context=state["questions_by_id"]["q-source"],
        )
        updated = interview_service._apply_clarification_answer(state, source_answer)  # noqa: SLF001

        self.assertEqual(updated["current_question"]["question_id"], "group-bar:brand_name")
        self.assertEqual(updated["current_question"]["question_kind"], "BRAND_NAME")

        brand_answer = interview_service._parse_clarification_text(  # noqa: SLF001
            text="Acme",
            context=updated["questions_by_id"]["group-bar:brand_name"],
        )
        completed = interview_service._apply_clarification_answer(updated, brand_answer)  # noqa: SLF001
        item = completed["confirmation_items"][0]

        self.assertEqual(item["segment_ids"], ["seg-bar-1", "seg-bar-2"])
        self.assertEqual(item["source_type"], "PACKAGED")
        self.assertEqual(item["source_origin_state"], "PACKAGED_BRANDED")
        self.assertEqual(item["brand_name"], "Acme")

    def test_restaurant_source_answer_inserts_restaurant_follow_up_and_preserves_segment_ids(self) -> None:
        from app.services import interview_service

        state = {
            "question_order": ["q-source"],
            "questions_by_id": {
                "q-source": {
                    "question_id": "q-source",
                    "group_id": "group-wrap",
                    "primary_segment_id": "seg-wrap-1",
                    "segment_ids": ["seg-wrap-1", "seg-wrap-2"],
                    "question_kind": "SOURCE_ORIGIN",
                    "answer_type": "single_choice",
                    "required": True,
                    "label": "shawarma wrap",
                    "choices": [
                        {
                            "choice_id": "RESTAURANT",
                            "label": "restaurant",
                            "value": "RESTAURANT",
                        }
                    ],
                }
            },
            "answers_by_question_id": {},
            "pending_question_ids": ["q-source"],
            "remaining_required_question_ids": ["q-source"],
            "interview_messages": [],
        }

        source_answer = interview_service._parse_clarification_text(  # noqa: SLF001
            text="restaurant",
            context=state["questions_by_id"]["q-source"],
        )
        updated = interview_service._apply_clarification_answer(state, source_answer)  # noqa: SLF001

        self.assertEqual(updated["current_question"]["question_id"], "group-wrap:restaurant_name")
        self.assertEqual(updated["current_question"]["question_kind"], "RESTAURANT_NAME")

        restaurant_answer = interview_service._parse_clarification_text(  # noqa: SLF001
            text="Shawarma House",
            context=updated["questions_by_id"]["group-wrap:restaurant_name"],
        )
        completed = interview_service._apply_clarification_answer(updated, restaurant_answer)  # noqa: SLF001
        item = completed["confirmation_items"][0]

        self.assertEqual(item["segment_ids"], ["seg-wrap-1", "seg-wrap-2"])
        self.assertEqual(item["source_type"], "RESTAURANT")
        self.assertEqual(item["source_origin_state"], "RESTAURANT")
        self.assertEqual(item["restaurant_name"], "Shawarma House")
