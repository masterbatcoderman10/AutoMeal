from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch


class FixEntryResolutionTests(unittest.TestCase):
    def test_fix_command_supports_direct_entry_id(self) -> None:
        from app.services import correction_service

        resolved = correction_service.resolve_fix_target(
            "/fix b23d9c6e",
            recent_entries=[
                {"id": "recent-1"},
                {"id": "recent-2"},
            ],
        )

        self.assertEqual(resolved["mode"], "direct")
        self.assertEqual(resolved["entry_id"], "b23d9c6e")

    def test_fix_command_falls_back_to_most_recent(self) -> None:
        from app.services import correction_service

        resolved = correction_service.resolve_fix_target(
            "/fix",
            recent_entries=[
                {"id": "recent-1"},
                {"id": "recent-2"},
            ],
        )

        self.assertEqual(resolved["mode"], "recent")
        self.assertEqual(resolved["entry_id"], "recent-1")

    def test_fix_command_supports_recent_short_id_selection(self) -> None:
        from app.services import correction_service

        resolved = correction_service.resolve_fix_target(
            "/fix abcd1234",
            recent_entries=[
                {"id": "abcd1234-1111", "short_id": "abcd1234"},
                {"id": "efgh5678-2222", "short_id": "efgh5678"},
            ],
        )

        self.assertEqual(resolved["mode"], "recent")
        self.assertEqual(resolved["entry_id"], "abcd1234-1111")

    def test_fix_command_supports_recent_numeric_selection(self) -> None:
        from app.services import correction_service

        resolved = correction_service.resolve_fix_target(
            "/fix 2",
            recent_entries=[
                {"id": "recent-1", "short_id": "recent-1"},
                {"id": "recent-2", "short_id": "recent-2"},
            ],
        )

        self.assertEqual(resolved["mode"], "recent")
        self.assertEqual(resolved["entry_id"], "recent-2")

    def test_fix_diff_preview_shows_before_and_after_state(self) -> None:
        from app.services import correction_service

        before = {
            "food_name": "Chicken Curry",
            "quantity": "1 cup",
            "source_type": "restaurant",
            "source_name": "Old Name",
        }
        after = {
            "food_name": "Chicken Biryani",
            "quantity": "2 cups",
            "source_type": "homemade",
            "source_name": "Home",
        }

        diff = correction_service.build_fix_diff(before=before, after=after)

        self.assertEqual(diff["before"]["food_name"], "Chicken Curry")
        self.assertEqual(diff["after"]["food_name"], "Chicken Biryani")
        self.assertIn("quantity", diff["before"])
        self.assertIn("quantity", diff["after"])

    def test_fix_is_confirm_or_cancel(self) -> None:
        from app.services import correction_service

        result = correction_service.apply_fix(
            entry={"id": "entry-1", "food_name": "Old Item"},
            patch={"food_name": "New Item"},
            confirm=False,
        )

        self.assertFalse(result["applied"])
        self.assertEqual(result["reason"], "cancelled")
        self.assertEqual(result["entry"]["food_name"], "Old Item")


class FixMutationTests(unittest.TestCase):
    def test_identity_fix_invalidates_only_linked_visual(self) -> None:
        from app.services import correction_service

        current = {
            "id": "entry-1",
            "food_name": "Chicken Curry",
            "food_visual_id": "visual-a",
            "linked_visuals": ["visual-a", "visual-b"],
        }

        updated = correction_service.apply_fix(
            entry=current,
            patch={"food_name": "Chicken Biryani"},
            confirm=True,
        )

        self.assertTrue(updated["applied"])
        self.assertEqual(updated["invalidated_visual_ids"], ["visual-a"])
        self.assertNotIn("visual-b", updated["invalidated_visual_ids"])

    def test_quantity_only_fix_does_not_invalidate_visual(self) -> None:
        from app.services import correction_service

        current = {
            "id": "entry-2",
            "food_name": "Dal",
            "portion_bucket": "SMALL",
            "food_visual_id": "visual-c",
            "linked_visuals": ["visual-c", "visual-d"],
        }

        updated = correction_service.apply_fix(
            entry=current,
            patch={"portion_bucket": "LARGE"},
            confirm=True,
        )

        self.assertTrue(updated["applied"])
        self.assertEqual(updated["invalidated_visual_ids"], [])

    def test_correction_event_append_tracks_before_after_metadata(self) -> None:
        from app.services import correction_service

        history = []
        event = correction_service.build_correction_history_entry(
            previous={"food_name": "Dal", "portion_bucket": "SMALL"},
            updated={"food_name": "Masoor Dal", "portion_bucket": "LARGE"},
            trace_id="trace-123",
            side_effects={"invalidated_visuals": ["visual-1"]},
            reason="manual fix",
        )
        history.append(event)

        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["previous"]["food_name"], "Dal")
        self.assertEqual(history[0]["updated"]["food_name"], "Masoor Dal")
        self.assertEqual(history[0]["trace_id"], "trace-123")
        self.assertEqual(history[0]["reason"], "manual fix")

    def test_quantity_fix_triggers_nutrition_recompute_without_visual_learning(self) -> None:
        from app.services import correction_service

        current = {
            "id": "entry-3",
            "food_name": "Rice",
            "portion_bucket": "SMALL",
            "nutrition": {"calories": 180},
            "visual_learning_eligible": False,
            "food_visual_id": "visual-e",
        }

        updated = correction_service.apply_fix(
            entry=current,
            patch={"portion_bucket": "STANDARD"},
            confirm=True,
        )

        self.assertTrue(updated["applied"])
        self.assertFalse(updated["write_visual_back"])
        self.assertTrue(updated["recompute_nutrition"])

    def test_visual_learning_eligible_gate_controls_fix_backwrite(self) -> None:
        from app.services import correction_service

        ineligible = {"id": "entry-4", "visual_learning_eligible": False}
        self.assertFalse(correction_service.visual_learning_eligible_for_relearn(ineligible))

        eligible = {"id": "entry-5", "visual_learning_eligible": True}
        self.assertTrue(correction_service.visual_learning_eligible_for_relearn(eligible))


class FixDiffPreviewTests(unittest.TestCase):
    def test_fix_confirmation_preview_includes_side_effect_diff(self) -> None:
        from app.services import correction_service

        preview = correction_service.build_fix_confirmation_payload(
            entry={
                "id": "entry-6",
                "food_name": "Old", 
                "source_name": "Old Cafe",
            },
            patch={
                "food_name": "New",
                "source_name": "Street Vendor",
            },
        )

        self.assertEqual(preview["status"], "pending_confirmation")
        self.assertEqual(preview["diff"]["before"]["source_name"], "Old Cafe")
        self.assertEqual(preview["diff"]["after"]["food_name"], "New")


class RecentEntryTrackingTests(unittest.TestCase):
    def test_recent_entries_are_prepended_and_deduplicated(self) -> None:
        from app.services import correction_service

        recent = correction_service.remember_recent_entries(
            existing=[
                {"id": "older-1", "short_id": "older-1"},
                {"id": "older-2", "short_id": "older-2"},
            ],
            new_entries=[
                {"id": "new-1", "short_id": "new-1"},
                {"id": "older-1", "short_id": "older-1"},
            ],
        )

        self.assertEqual([entry["id"] for entry in recent], ["new-1", "older-1", "older-2"])


class CorrectionContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_apply_confirmed_entry_correction_uses_stored_visual_context(self) -> None:
        from app.models import DiaryEntry
        from app.services import correction_service

        entry = DiaryEntry(
            id="entry-1",
            meal_log_id="meal-1",
            food_item_id="food-old",
            segment_id="segment-1",
            portion_bucket="STANDARD",
            identification_method="AUTO_CONFIRM",
            is_verified=True,
            quantity_json={"portion_bucket": "STANDARD"},
            quantity_display="1 bowl",
        )
        meal = SimpleNamespace(
            id="meal-1",
            processing_status="COMPLETED",
            reasoning_state_json={"existing": "state"},
        )
        correction_event = SimpleNamespace(id="event-1")
        session = SimpleNamespace(
            get=AsyncMock(return_value=meal),
            add=Mock(),
        )

        with (
            patch.object(
                correction_service,
                "build_entry_correction_context",
                AsyncMock(
                    return_value={
                        "id": entry.id,
                        "food_name": "Protein Bar",
                        "food_item_id": entry.food_item_id,
                        "portion_bucket": entry.portion_bucket,
                        "quantity_json": entry.quantity_json,
                        "quantity_display": entry.quantity_display,
                        "source_type": "PACKAGED",
                        "brand_name": "Acme",
                        "restaurant_name": None,
                        "food_visual_id": "visual-1",
                        "visual_learning_eligible": True,
                    }
                ),
            ),
            patch.object(
                correction_service,
                "apply_final_meal_resolution",
                AsyncMock(return_value=SimpleNamespace(correction_events=[correction_event])),
            ) as apply_resolution,
        ):
            result = await correction_service.apply_confirmed_entry_correction(
                session=session,
                entry=entry,
                patch={"food_name": "Better Protein Bar"},
                reason="manual fix",
            )

        self.assertEqual(result["invalidated_visual_ids"], ["visual-1"])
        self.assertTrue(result["write_visual_back"])
        self.assertEqual(result["correction_event"], correction_event)
        apply_resolution.assert_awaited_once()
        resolution = apply_resolution.await_args.kwargs["final_segments"][0]
        self.assertEqual(resolution.existing_diary_entry_id, "entry-1")
        self.assertEqual(resolution.prior_food_visual_id_to_invalidate, "visual-1")
        self.assertFalse(resolution.create_food_visual)
        self.assertTrue(resolution.visual_learning_eligible)
        self.assertTrue(resolution.entry_is_verified)
        self.assertEqual(resolution.food.source_type, "PACKAGED")
        self.assertEqual(resolution.food.brand_name, "Acme")


class FixInterviewFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_fix_command_starts_interview_session_instead_of_pending_patch_state(self) -> None:
        from bot.handlers import fix_command

        entry = SimpleNamespace(id="entry-1", meal_log_id="meal-1", food_item_id="food-1", segment_id="seg-1")
        interview = SimpleNamespace(
            current_prompt_payload={
                "session_mode": "ENTRY_FIX",
                "roadmap_step": "FOOD_NAME",
                "pending_targets": [{"segment_id": "seg-1", "label": "Protein Bar", "food_name": "Protein Bar"}],
                "answers_by_segment": [{"segment_id": "seg-1", "name": "Protein Bar"}],
            }
        )
        session = AsyncMock()
        session.get = AsyncMock(return_value=entry)
        session.add = Mock()
        engine = SimpleNamespace(dispose=AsyncMock())

        class SessionContext:
            async def __aenter__(self):
                return session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        reply_text = AsyncMock()
        update = SimpleNamespace(
            message=SimpleNamespace(chat=SimpleNamespace(id="999"), text="/fix 1", reply_text=reply_text),
            callback_query=None,
        )
        context = SimpleNamespace(bot_data={"recent_entries": [{"id": "entry-1", "short_id": "entry-1", "food_name": "Protein Bar"}]})

        with (
            patch("bot.handlers.get_settings", return_value=SimpleNamespace(TELEGRAM_CHAT_ID="999", DATABASE_URL="postgresql://db")),
            patch("bot.handlers._make_session_factory", return_value=(engine, Mock(return_value=SessionContext()))),
            patch("bot.handlers.correction_service.build_entry_correction_context", AsyncMock(return_value={"food_name": "Protein Bar"})),
            patch("bot.handlers.interview_service.prepare_fix_interview_session", AsyncMock(return_value=interview)) as prepare_fix,
        ):
            await fix_command(update, context)

        prepare_fix.assert_awaited_once()
        reply_text.assert_awaited_once()
        self.assertIn("What exact name should I log", reply_text.await_args.args[0])
        self.assertNotIn("pending_fix", context.bot_data)
        session.commit.assert_awaited_once()
        engine.dispose.assert_awaited_once()

    async def test_fix_confirmation_applies_correction_from_session_state(self) -> None:
        from bot.handlers import interview_text

        interview = SimpleNamespace(
            id="interview-fix-1",
            meal_log_id="meal-1",
            is_active=True,
            state_key="CONFIRMATION",
            current_prompt_payload={
                "session_mode": "ENTRY_FIX",
                "fix_entry_id": "entry-1",
                "roadmap_step": "CONFIRMATION",
                "pending_targets": [{"segment_id": "seg-1", "label": "Protein Bar"}],
                "answers_by_segment": [
                    {
                        "segment_id": "seg-1",
                        "entry_id": "entry-1",
                        "name": "Better Protein Bar",
                        "source_type": "PACKAGED",
                        "brand_name": "Acme",
                        "portion_bucket": "SMALL",
                        "quantity_display": "1 bar",
                    }
                ],
            },
        )
        entry = SimpleNamespace(id="entry-1")
        session = AsyncMock()
        session.get = AsyncMock(return_value=entry)
        session.add = Mock()
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
            patch(
                "bot.handlers.correction_service.build_entry_correction_context",
                AsyncMock(
                    return_value={
                        "food_name": "Protein Bar",
                        "source_type": "PACKAGED",
                        "brand_name": "Acme",
                        "restaurant_name": None,
                        "portion_bucket": "STANDARD",
                        "quantity_display": "1 bar",
                    }
                ),
            ),
            patch(
                "bot.handlers.correction_service.apply_confirmed_entry_correction",
                AsyncMock(
                    return_value={
                        "applied": True,
                        "entry": {"food_name": "Better Protein Bar"},
                        "invalidated_visual_ids": ["visual-1"],
                        "recompute_nutrition": False,
                    }
                ),
            ) as apply_fix,
        ):
            await interview_text(update, context)

        apply_fix.assert_awaited_once()
        self.assertFalse(interview.is_active)
        reply_text.assert_awaited_once_with("Updated Better Protein Bar. Invalidated 1 linked visual.")
        session.commit.assert_awaited_once()
        engine.dispose.assert_awaited_once()
