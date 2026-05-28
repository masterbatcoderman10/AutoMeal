from __future__ import annotations

import inspect
import unittest
from typing import Any


def _candidate_payload() -> dict[str, Any]:
    return {
        "candidate_id": "candidate-1",
        "label": "chicken curry",
        "identity_confidence": 0.94,
        "quantity_confidence": 0.84,
        "match_consistency_confidence": 0.9,
        "visual_evidence": ["segment_1: visible proteins"],
        "missing_evidence": ["portion_unit"],
        "specificity": "high",
        "nutrition_relevance": "medium",
        "source": "vector_match",
        "decision_rationale": "best top candidate",
    }


def _resolve_reasoning_entrypoint(module):
    for name in (
        "persist_reasoning_results",
        "persist_reasoning_state",
        "save_reasoning_state",
    ):
        fn = getattr(module, name, None)
        if callable(fn):
            return name, fn
    raise AssertionError(
        "No reasoning persistence entrypoint found. Expected one of "
        "persist_reasoning_results/persist_reasoning_state/save_reasoning_state."
    )


def _invoke_reasoning_writer(
    fn,
    session,
    meal,
    segments: list[Any],
    reasoning_payload: dict[str, Any],
) -> Any:
    signature = inspect.signature(fn)
    params = signature.parameters
    kwargs: dict[str, Any] = {}
    if "session" in params:
        kwargs["session"] = session
    elif "db_session" in params:
        kwargs["db_session"] = session

    if "meal" in params:
        kwargs["meal"] = meal
    elif "meal_log" in params:
        kwargs["meal_log"] = meal

    if "segments" in params:
        kwargs["segments"] = segments
    elif "segment_rows" in params:
        kwargs["segment_rows"] = segments

    if "reasoning_payload" in params:
        kwargs["reasoning_payload"] = reasoning_payload
    elif "reasoning_decision" in params:
        kwargs["reasoning_decision"] = reasoning_payload
    elif "decision_payload" in params:
        kwargs["decision_payload"] = reasoning_payload
    elif "reasoning" in params:
        kwargs["reasoning"] = reasoning_payload

    return fn(**kwargs)


class ReasoningFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_persists_reasoning_before_final_write(self) -> None:
        from app.services import reasoning_service

        meal = type("Meal", (), {"id": "meal-1", "processing_status": "REASONING"})()
        segments = [
            type(
                "MealSegment",
                (),
                {"id": "segment-1", "cropped_image_url": "/tmp/seg1.jpg", "ai_reasoning": None},
            )(),
            type(
                "MealSegment",
                (),
                {"id": "segment-2", "cropped_image_url": "/tmp/seg2.jpg", "ai_reasoning": None},
            )(),
        ]
        payload = {
            "action": "AUTO_CONFIRM",
            "meal_state": "READY_TO_WRITE",
            "trace_id": "trace-flow-1",
            "top_3": [_candidate_payload(), _candidate_payload()],
            "decision_rationale": "matched and ready",
            "gate_reason": "",
            "segment_count": 2,
        }
        write_session = type("Session", (), {})()
        write_session.add = lambda _obj: None  # type: ignore[method-assign]
        write_session.flush = lambda: None  # type: ignore[method-assign]
        write_session.commit = lambda: None  # type: ignore[method-assign]

        name, writer = _resolve_reasoning_entrypoint(reasoning_service)
        result = _invoke_reasoning_writer(
            writer,
            session=write_session,
            meal=meal,
            segments=segments,
            reasoning_payload=payload,
        )
        if inspect.isawaitable(result):
            result = await result

        self.assertIn("segment_reasoning", result)
        self.assertIn("meal_reasoning", result)
        self.assertIn("ready_for_final_write", result)
        self.assertEqual(result["ready_for_final_write"], True, name)
        self.assertEqual(len(result["segment_reasoning"]), len(segments))
        self.assertEqual(result["meal_reasoning"]["trace_id"], "trace-flow-1")

    async def test_final_write_waits_for_all_segment_reasoning_records(self) -> None:
        from app.services import reasoning_service

        meal = type("Meal", (), {"id": "meal-2", "processing_status": "REASONING"})()
        segments = [
            type(
                "MealSegment",
                (),
                {"id": "segment-1", "cropped_image_url": "/tmp/seg1.jpg", "ai_reasoning": None},
            )(),
            type(
                "MealSegment",
                (),
                {"id": "segment-2", "cropped_image_url": "/tmp/seg2.jpg", "ai_reasoning": None},
            )(),
        ]
        payload = {
            "action": "ASK_QUANTITY",
            "meal_state": "PENDING_INTERVIEW",
            "trace_id": "trace-flow-2",
            "top_3": [_candidate_payload(), _candidate_payload()],
            "decision_rationale": "need explicit quantity before write",
            "gate_reason": "missing serving signal",
            "segment_count": 2,
        }
        write_session = type("Session", (), {})()
        write_session.add = lambda _obj: None  # type: ignore[method-assign]
        write_session.flush = lambda: None  # type: ignore[method-assign]
        write_session.commit = lambda: None  # type: ignore[method-assign]

        _, writer = _resolve_reasoning_entrypoint(reasoning_service)
        result = _invoke_reasoning_writer(
            writer,
            session=write_session,
            meal=meal,
            segments=segments,
            reasoning_payload=payload,
        )
        if inspect.isawaitable(result):
            result = await result

        self.assertIn("ready_for_final_write", result)
        self.assertFalse(result["ready_for_final_write"])
        self.assertIn("meal_reasoning", result)
        self.assertEqual(result["meal_reasoning"]["meal_state"], "PENDING_INTERVIEW")
