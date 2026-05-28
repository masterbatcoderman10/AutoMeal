from __future__ import annotations

import unittest
from types import SimpleNamespace


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
