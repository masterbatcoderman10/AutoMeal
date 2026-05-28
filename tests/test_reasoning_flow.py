from __future__ import annotations

import json
import inspect
import unittest
from contextlib import nullcontext
from typing import Any
from unittest.mock import AsyncMock, patch


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

    async def test_run_reasoning_request_uses_fallback_model_after_primary_failure(self) -> None:
        from app.services import reasoning_service

        meal = type("Meal", (), {"id": "meal-fallback", "image_url": None})()
        segment = type("MealSegment", (), {"id": "segment-1"})()
        candidate = {
            "candidate_id": "candidate-1",
            "label": "chicken curry",
            "identity_confidence": 0.99,
            "quantity_confidence": 0.85,
            "match_consistency_confidence": 0.98,
            "missing_evidence": [],
            "nutrition_impact": 0.05,
            "source": "vector_match",
        }
        response_payload = {
            "action": "AUTO_CONFIRM",
            "meal_state": "READY_TO_WRITE",
            "top_3": [candidate],
            "decision_rationale": "ready to auto-confirm",
            "gate_reason": "",
            "segment_count": 1,
            "trace_id": "trace-fallback",
        }
        llm_client = type("LLM", (), {})()
        llm_client.chat_completion = AsyncMock(
            side_effect=[
                RuntimeError("provider down"),
                {"choices": [{"message": {"content": json.dumps(response_payload)}}]},
            ]
        )
        settings = type(
            "Settings",
            (),
            {
                "REASONING_MODEL": "primary-model",
                "REASONING_FALLBACK_MODEL": "fallback-model",
                "REASONING_PARSER_MODEL": "parser-model",
                "REASONING_PARSER_FALLBACK_MODEL": "parser-fallback-model",
                "REASONING_MATCH_THRESHOLD": 0.9,
            },
        )()

        with patch.object(reasoning_service.tracing_service, "maybe_start_trace", return_value=nullcontext(None)):
            result, _trace = await reasoning_service.run_reasoning_request(
                llm_client=llm_client,
                meal_id=meal.id,
                meal=meal,
                match_results=[(segment, type("Result", (), {"top_candidates": [candidate]})())],
                settings=settings,
            )

        self.assertEqual(llm_client.chat_completion.await_args_list[0].kwargs["model"], "primary-model")
        self.assertEqual(llm_client.chat_completion.await_args_list[1].kwargs["model"], "fallback-model")
        self.assertEqual(result["meal_state"], "READY_TO_WRITE")
        self.assertIn(result["action"], {"AUTO_CONFIRM", "AUTO_CONFIRM_WITH_TRACE"})

    async def test_parser_retry_uses_fallback_model_when_primary_repair_is_unusable(self) -> None:
        from app.services import reasoning_service

        llm_client = type("LLM", (), {})()
        llm_client.chat_completion = AsyncMock(
            side_effect=[
                {"choices": [{"message": {"content": "not json"}}]},
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "action": "ASK_CHOICE",
                                        "meal_state": "PENDING_INTERVIEW",
                                        "top_3": [],
                                        "decision_rationale": "need more detail",
                                        "gate_reason": "repair fallback",
                                        "segment_count": 1,
                                        "trace_id": "trace-parser-fallback",
                                    }
                                )
                            }
                        }
                    ]
                },
            ]
        )
        settings = type(
            "Settings",
            (),
            {
                "REASONING_PARSER_MODEL": "parser-primary",
                "REASONING_PARSER_FALLBACK_MODEL": "parser-fallback",
            },
        )()

        repaired = await reasoning_service._run_reasoning_parser_retry(
            llm_client=llm_client,
            app_settings=settings,
            response_payload={"raw": "payload"},
        )

        self.assertEqual(llm_client.chat_completion.await_args_list[0].kwargs["model"], "parser-primary")
        self.assertEqual(llm_client.chat_completion.await_args_list[1].kwargs["model"], "parser-fallback")
        self.assertEqual(repaired["trace_id"], "trace-parser-fallback")
