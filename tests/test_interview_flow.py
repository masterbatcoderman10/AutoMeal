from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch


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


class InterviewPersistencePrepTests(unittest.TestCase):
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
