from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from app.models import MealProcessingStatus


class JanitorRecoveryStateTests(unittest.TestCase):
    def test_janitor_uses_artifact_status_when_artifact_is_more_specific(self) -> None:
        from app.services import recovery_service

        meal_state = {
            "meal_id": "meal-1",
            "processing_status": MealProcessingStatus.REASONING.value,
            "updated_at": datetime(2026, 5, 28, 12, 0, 0),
            "reasoning_progress": {
                "status": MealProcessingStatus.EMBEDDING.value,
            },
        }
        artifact = {
            "status": MealProcessingStatus.SEGMENTING.value,
            "updated_at": datetime(2026, 5, 28, 11, 50, 0),
        }

        decision = recovery_service.select_recovery_target(meal_state, artifact=artifact)

        self.assertEqual(decision["recovery_status"], MealProcessingStatus.SEGMENTING.value)

    def test_janitor_only_recovers_machine_stage_statuses(self) -> None:
        from app.services import recovery_service

        self.assertTrue(recovery_service.is_recoverable_machine_status(MealProcessingStatus.DETECTING.value))
        self.assertTrue(recovery_service.is_recoverable_machine_status(MealProcessingStatus.SEGMENTING.value))
        self.assertTrue(recovery_service.is_recoverable_machine_status(MealProcessingStatus.EMBEDDING.value))
        self.assertTrue(recovery_service.is_recoverable_machine_status(MealProcessingStatus.MATCHING.value))
        self.assertTrue(recovery_service.is_recoverable_machine_status(MealProcessingStatus.REASONING.value))
        self.assertFalse(recovery_service.is_recoverable_machine_status(MealProcessingStatus.INTERVIEWING.value))
        self.assertFalse(recovery_service.is_recoverable_machine_status(MealProcessingStatus.PENDING.value))

    def test_janitor_honors_stale_threshold(self) -> None:
        from app.services import recovery_service

        now = datetime(2026, 5, 28, 12, 5, 0)
        fresh = {
            "processing_status": MealProcessingStatus.MATCHING.value,
            "updated_at": now - timedelta(minutes=2),
        }
        stale = {
            "processing_status": MealProcessingStatus.MATCHING.value,
            "updated_at": now - timedelta(minutes=6),
        }

        self.assertFalse(recovery_service.is_stale_for_janitor(fresh, now=now, stale_minutes=5))
        self.assertTrue(recovery_service.is_stale_for_janitor(stale, now=now, stale_minutes=5))


class JanitorAttemptBudgetTests(unittest.TestCase):
    def test_janitor_allows_exactly_three_recovery_attempts(self) -> None:
        from app.services import recovery_service

        self.assertTrue(recovery_service.can_retry_recovery({"recovery_attempt_count": 0}))
        self.assertTrue(recovery_service.can_retry_recovery({"recovery_attempt_count": 1}))
        self.assertTrue(recovery_service.can_retry_recovery({"recovery_attempt_count": 2}))
        self.assertFalse(recovery_service.can_retry_recovery({"recovery_attempt_count": 3}))

    def test_janitor_marks_failed_after_three_attempts(self) -> None:
        from app.services import recovery_service

        state = {
            "meal_id": "meal-2",
            "recovery_attempt_count": 3,
            "processing_status": MealProcessingStatus.REASONING.value,
        }
        marked = recovery_service.mark_recovery_exhausted(state)

        self.assertEqual(marked["processing_status"], MealProcessingStatus.FAILED.value)
        self.assertTrue(marked["failed_reason"])

    def test_janitor_notifies_user_once_on_failure(self) -> None:
        from app.services import recovery_service

        state = {
            "meal_id": "meal-3",
            "failed_reason": "janitor_stale_retries_exhausted",
            "user_notified": False,
        }

        first = recovery_service.enqueue_recovery_notification(state)
        second = recovery_service.enqueue_recovery_notification(first)

        self.assertTrue(first["notify_user"])
        self.assertFalse(second["notify_user"])
        self.assertTrue(first["user_notified"])


class JanitorArtifactTests(unittest.TestCase):
    def test_janitor_keeps_committed_artifacts_and_preserves_crop_metadata(self) -> None:
        from app.services import recovery_service

        meal = {
            "meal_id": "meal-4",
            "processing_status": MealProcessingStatus.EMBEDDING.value,
            "committed": ["embeddings", "matches"],
            "crop_paths": ["/tmp/seg-1.jpg", "/tmp/seg-2.jpg"],
            "orphan_crop_paths": ["/tmp/old-seg-3.jpg"],
        }

        cleanup = recovery_service.classify_janitor_artifacts(meal)

        self.assertIn("/tmp/old-seg-3.jpg", cleanup["delete_paths"])
        self.assertNotIn("/tmp/seg-1.jpg", cleanup["delete_paths"])
        self.assertNotIn("/tmp/seg-2.jpg", cleanup["delete_paths"])

    def test_janitor_drops_duplicate_notifications_across_runs(self) -> None:
        from app.services import recovery_service

        state = {
            "meal_id": "meal-5",
            "processing_status": MealProcessingStatus.EMBEDDING.value,
            "recovery_attempt_count": 3,
            "user_notified": False,
        }

        first_pass = recovery_service.plan_post_recovery_actions(state)
        second_pass = recovery_service.plan_post_recovery_actions(first_pass)

        self.assertTrue(first_pass["notify_user"])
        self.assertFalse(second_pass["notify_user"])
