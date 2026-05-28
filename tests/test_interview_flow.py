from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace


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


class InterviewProgressionTests(unittest.TestCase):
    def test_interview_proceeds_one_target_at_a_time(self) -> None:
        from bot import handlers

        state = {
            "meal_id": "meal-1",
            "roadmap_step": "CONFIRMATION",
            "pending_targets": [
                {"segment_id": "seg-1", "label": "Dal"},
                {"segment_id": "seg-2", "label": "Chickpea Curry"},
            ],
            "current_target_index": 0,
            "interview_messages": [],
        }

        first = handlers.current_target_question(state)
        self.assertEqual(first["segment_id"], "seg-1")

        state = handlers.complete_target_question(
            state,
            {
                "segment_id": "seg-1",
                "value": {"confirmed": True, "quantity_text": "1 serving"},
            },
        )

        self.assertEqual(state["current_target_index"], 1)
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
        self.assertEqual(closeout["unresolved_count"], 2)


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
