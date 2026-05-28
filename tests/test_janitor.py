from __future__ import annotations

import importlib
import importlib.util
import unittest
from datetime import UTC, datetime, timedelta
from typing import Any

from app.models import MealProcessingStatus


def _recovery_service():
    spec = importlib.util.find_spec("app.services.recovery_service")
    if spec is None:
        return None
    return importlib.import_module("app.services.recovery_service")


def _plan_stale_recovery(
    meal: dict[str, Any],
    *,
    segments: list[dict[str, Any]] | None = None,
    interview_session: dict[str, Any] | None = None,
    now: datetime | None = None,
    stale_minutes: int = 5,
    max_recoveries: int = 3,
) -> dict[str, Any]:
    service = _recovery_service()
    if service is None or not hasattr(service, "plan_stale_meal_recovery"):
        return {}
    return service.plan_stale_meal_recovery(
        meal,
        segments=segments,
        interview_session=interview_session,
        now=now,
        stale_minutes=stale_minutes,
        max_recoveries=max_recoveries,
    )


def _enqueue_notification(meal: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    service = _recovery_service()
    if service is None or not hasattr(service, "enqueue_recovery_notification"):
        return dict(meal)
    return service.enqueue_recovery_notification(meal, now=now)


class JanitorTests(unittest.TestCase):
    def test_stale_reasoning_resumes_from_last_safe_artifact_stage(self) -> None:
        now = datetime(2026, 5, 28, 12, 5, tzinfo=UTC)
        meal = {
            "meal_id": "meal-1",
            "processing_status": MealProcessingStatus.REASONING.value,
            "last_stage_started_at": now - timedelta(minutes=6),
            "updated_at": now - timedelta(minutes=6),
            "recovery_attempt_count": 1,
            "reasoning_state_json": {
                "meal_reasoning": {
                    "meal_state": "FAILED_UNCLEAR",
                }
            },
        }
        segments = [
            {
                "segment_id": "segment-1",
                "cropped_image_url": "/tmp/seg-1.jpg",
                "embedding": [0.12, 0.34],
                "match_candidates_json": {
                    "top_3": [{"candidate_id": "visual-1", "label": "rice bowl"}],
                    "candidate_count": 1,
                },
            }
        ]

        plan = _plan_stale_recovery(meal, segments=segments, now=now)

        self.assertEqual(plan.get("recovery_status"), MealProcessingStatus.MATCHING.value)
        self.assertEqual(plan.get("resume_basis"), "candidate_snapshots")
        self.assertEqual(plan.get("recovery_attempt_count"), 2)
        self.assertEqual(plan.get("failed_reason"), None)
        self.assertFalse(plan.get("notify_user", False))

    def test_failed_after_three_recoveries_notifies_once(self) -> None:
        now = datetime(2026, 5, 28, 12, 5, tzinfo=UTC)
        meal = {
            "meal_id": "meal-2",
            "processing_status": MealProcessingStatus.MATCHING.value,
            "last_stage_started_at": now - timedelta(minutes=6),
            "updated_at": now - timedelta(minutes=6),
            "recovery_attempt_count": 3,
            "last_recovery_notified_at": None,
        }

        failed = _plan_stale_recovery(meal, now=now)
        delivered = {**failed, "last_recovery_notified_at": now}
        second_pass = _enqueue_notification(delivered, now=now + timedelta(minutes=1))

        self.assertEqual(failed.get("recovery_status"), MealProcessingStatus.FAILED.value)
        self.assertEqual(failed.get("failed_reason"), "janitor_stale_retries_exhausted")
        self.assertTrue(failed.get("notify_user"))
        self.assertIsNone(failed.get("last_recovery_notified_at"))
        self.assertFalse(second_pass.get("notify_user"))
        self.assertEqual(
            second_pass.get("last_recovery_notified_at"),
            delivered.get("last_recovery_notified_at"),
        )

    def test_interviewing_and_terminal_states_are_excluded(self) -> None:
        now = datetime(2026, 5, 28, 12, 5, tzinfo=UTC)
        for status in (
            MealProcessingStatus.INTERVIEWING.value,
            MealProcessingStatus.COMPLETED.value,
            MealProcessingStatus.FAILED.value,
        ):
            with self.subTest(status=status):
                plan = _plan_stale_recovery(
                    {
                        "meal_id": f"meal-{status.lower()}",
                        "processing_status": status,
                        "last_stage_started_at": now - timedelta(minutes=8),
                        "updated_at": now - timedelta(minutes=8),
                        "recovery_attempt_count": 0,
                    },
                    now=now,
                )

                self.assertEqual(plan.get("action"), "skip")
                self.assertEqual(plan.get("reason"), "non_recoverable_status")

    def test_embeddings_without_candidates_resume_at_matching(self) -> None:
        now = datetime(2026, 5, 28, 12, 5, tzinfo=UTC)
        meal = {
            "meal_id": "meal-3",
            "processing_status": MealProcessingStatus.REASONING.value,
            "last_stage_started_at": now - timedelta(minutes=7),
            "updated_at": now - timedelta(minutes=7),
            "recovery_attempt_count": 0,
        }
        segments = [
            {
                "segment_id": "segment-2",
                "cropped_image_url": "/tmp/seg-2.jpg",
                "embedding": [0.45, 0.67],
                "match_candidates_json": None,
            }
        ]

        plan = _plan_stale_recovery(meal, segments=segments, now=now)

        self.assertEqual(plan.get("recovery_status"), MealProcessingStatus.MATCHING.value)
        self.assertEqual(plan.get("resume_basis"), "embeddings")


if __name__ == "__main__":
    unittest.main()
