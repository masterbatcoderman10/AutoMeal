from __future__ import annotations

import json
import inspect
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
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


def _group_candidate(
    *,
    candidate_id: str,
    label: str,
    identity_confidence: float,
    missing_evidence: list[str] | None = None,
) -> dict[str, Any]:
    return {
        **_candidate_payload(),
        "candidate_id": candidate_id,
        "label": label,
        "identity_confidence": identity_confidence,
        "match_consistency_confidence": identity_confidence,
        "missing_evidence": list(missing_evidence or []),
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

        meal = type(
            "Meal",
            (),
            {"id": "meal-1", "processing_status": "REASONING", "reasoning_state_json": None},
        )()
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
        self.assertEqual(segments[0].ai_reasoning["trace_id"], "trace-flow-1")
        self.assertEqual(segments[1].ai_reasoning["group_state"], "READY_TO_WRITE")
        self.assertEqual(segments[1].ai_reasoning["group_id"], "group-1")
        self.assertEqual(meal.reasoning_state_json["meal_reasoning"]["trace_id"], "trace-flow-1")
        self.assertTrue(meal.reasoning_state_json["ready_for_final_write"])

    async def test_final_write_waits_for_all_segment_reasoning_records(self) -> None:
        from app.services import reasoning_service

        meal = type(
            "Meal",
            (),
            {"id": "meal-2", "processing_status": "REASONING", "reasoning_state_json": None},
        )()
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
        self.assertEqual(segments[0].ai_reasoning["trace_id"], "trace-flow-2")
        self.assertEqual(segments[0].ai_reasoning["group_state"], "PENDING_INTERVIEW")
        self.assertEqual(meal.reasoning_state_json["meal_reasoning"]["meal_state"], "PENDING_INTERVIEW")
        self.assertFalse(meal.reasoning_state_json["ready_for_final_write"])

    async def test_persists_compact_group_snapshots_without_copying_meal_candidates(self) -> None:
        from app.services import reasoning_service

        meal = type(
            "Meal",
            (),
            {"id": "meal-grouped", "processing_status": "REASONING", "reasoning_state_json": None},
        )()
        segments = [
            type(
                "MealSegment",
                (),
                {"id": "segment-bread-1", "cropped_image_url": "/tmp/bread-1.jpg", "ai_reasoning": None},
            )(),
            type(
                "MealSegment",
                (),
                {"id": "segment-bread-2", "cropped_image_url": "/tmp/bread-2.jpg", "ai_reasoning": None},
            )(),
            type(
                "MealSegment",
                (),
                {"id": "segment-curry", "cropped_image_url": "/tmp/curry.jpg", "ai_reasoning": None},
            )(),
        ]
        payload = {
            "action": "AUTO_CONFIRM",
            "meal_state": "READY_TO_WRITE",
            "trace_id": "trace-grouped-persist",
            "decision_rationale": "bread and curry groups are resolved independently",
            "gate_reason": "",
            "segment_count": 3,
            "food_group_count": 2,
            "food_groups": [
                {
                    "group_id": "group-bread",
                    "group_label": "pita bread",
                    "group_action": "AUTO_CONFIRM",
                    "group_state": "READY_TO_WRITE",
                    "primary_segment_id": "segment-bread-1",
                    "segment_ids": ["segment-bread-1", "segment-bread-2"],
                    "selected_candidate_id": "candidate-pita",
                    "top_3": [
                        _group_candidate(
                            candidate_id="candidate-pita",
                            label="pita bread",
                            identity_confidence=0.99,
                        ),
                        _group_candidate(
                            candidate_id="candidate-naan",
                            label="naan bread",
                            identity_confidence=0.75,
                        ),
                        _group_candidate(
                            candidate_id="candidate-roti",
                            label="roti bread",
                            identity_confidence=0.72,
                        ),
                    ],
                },
                {
                    "group_id": "group-curry",
                    "group_label": "egg curry",
                    "group_action": "AUTO_CONFIRM",
                    "group_state": "READY_TO_WRITE",
                    "primary_segment_id": "segment-curry",
                    "segment_ids": ["segment-curry"],
                    "selected_candidate_id": "candidate-egg-curry",
                    "top_3": [
                        _group_candidate(
                            candidate_id="candidate-egg-curry",
                            label="egg curry",
                            identity_confidence=0.95,
                        ),
                        _group_candidate(
                            candidate_id="candidate-chicken-curry",
                            label="chicken curry",
                            identity_confidence=0.77,
                        ),
                        _group_candidate(
                            candidate_id="candidate-mixed-curry",
                            label="mixed curry",
                            identity_confidence=0.71,
                        ),
                    ],
                },
            ],
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

        meal_reasoning = meal.reasoning_state_json["meal_reasoning"]
        self.assertIn("food_groups", meal_reasoning)
        self.assertEqual(meal_reasoning["food_group_count"], 2)
        self.assertEqual(segments[0].ai_reasoning["group_id"], "group-bread")
        self.assertEqual(segments[0].ai_reasoning["primary_segment_id"], "segment-bread-1")
        self.assertEqual(
            segments[0].ai_reasoning["group_segment_ids"],
            ["segment-bread-1", "segment-bread-2"],
        )
        self.assertEqual(
            segments[0].ai_reasoning["candidate_ids"],
            ["candidate-pita", "candidate-naan", "candidate-roti"],
        )
        self.assertNotIn("top_3", segments[0].ai_reasoning)
        self.assertEqual(segments[2].ai_reasoning["group_id"], "group-curry")
        self.assertEqual(result["meal_reasoning"]["food_group_count"], 2)

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

    async def test_run_reasoning_request_adds_deterministic_clarification_schema_for_reviewable_groups(self) -> None:
        from app.services import reasoning_service

        meal = type("Meal", (), {"id": "meal-clarify", "image_url": None})()
        segment = type(
            "MealSegment",
            (),
            {
                "id": "segment-wrap",
                "label": "wrapped flatbread",
                "bounding_box": [0.1, 0.2, 0.5, 0.7],
                "cropped_image_url": None,
            },
        )()
        candidate = _candidate_payload()
        candidate["label"] = "restaurant wrap flatbread"
        candidate["candidate_id"] = "candidate-wrap"
        candidate["identity_confidence"] = 0.74
        candidate["missing_evidence"] = ["bread type"]
        response_payload = {
            "action": "AUTO_CONFIRM",
            "meal_state": "READY_TO_WRITE",
            "trace_id": "trace-clarify-run",
            "food_group_count": 1,
            "segment_count": 1,
            "food_groups": [
                {
                    "group_id": "group-wrap",
                    "group_label": "restaurant wrap",
                    "group_action": "ASK_CHOICE",
                    "group_state": "PENDING_INTERVIEW",
                    "primary_segment_id": "segment-wrap",
                    "segment_ids": ["segment-wrap"],
                    "selected_candidate_id": "candidate-wrap",
                    "question_kind": "SOURCE_ORIGIN",
                    "question_focus": "Where did this food come from?",
                    "question_examples": ["home cooked", "packaged", "restaurant"],
                    "visual_evidence": ["visible wrapper"],
                    "missing_evidence": ["source channel"],
                    "decision_rationale": "source ambiguity impacts grounding path",
                    "gate_reason": "material source origin ambiguity",
                    "top_3": [_candidate_payload()],
                }
            ],
            "decision_rationale": "source ambiguity remains",
            "gate_reason": "needs source clarification",
        }
        llm_client = type("LLM", (), {})()
        llm_client.chat_completion = AsyncMock(return_value={"choices": [{"message": {"content": json.dumps(response_payload)}}]})
        settings = type(
            "Settings",
            (),
            {
                "REASONING_MODEL": "reasoning-primary",
                "REASONING_FALLBACK_MODEL": "reasoning-fallback",
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

        self.assertEqual(result["meal_state"], "PENDING_INTERVIEW")
        self.assertIn("clarification_schema", result)
        self.assertIsInstance(result["clarification_schema"], list)
        self.assertGreaterEqual(len(result["clarification_schema"]), 1)
        source_origin_questions = [
            question
            for question in result["clarification_schema"]
            if question["question_kind"] == "SOURCE_ORIGIN"
        ]
        self.assertEqual(len(source_origin_questions), 1)
        self.assertEqual(source_origin_questions[0]["group_id"], "group-wrap")

    async def test_run_reasoning_request_persists_group_owned_clarification_actions_before_telegram_mapping(self) -> None:
        from app.services import reasoning_service

        meal = type("Meal", (), {"id": "meal-group-contract", "image_url": None})()
        segment = type(
            "MealSegment",
            (),
            {
                "id": "segment-bread",
                "label": "packaged flatbread",
                "bounding_box": [0.1, 0.2, 0.5, 0.7],
                "cropped_image_url": None,
            },
        )()
        candidate = _candidate_payload()
        candidate["label"] = "Packaged wrap flatbread"
        candidate["candidate_id"] = "candidate-wrap"
        candidate["identity_confidence"] = 0.99
        candidate["source"] = "visual_reasoning"
        candidate["missing_evidence"] = []
        response_payload = {
            "action": "AUTO_CONFIRM",
            "meal_state": "READY_TO_WRITE",
            "trace_id": "trace-group-contract-run",
            "food_group_count": 1,
            "segment_count": 1,
            "food_groups": [
                {
                    "group_id": "group-wrap",
                    "group_label": "Packaged Flatbread",
                    "group_action": "AUTO_CONFIRM",
                    "group_state": "READY_TO_WRITE",
                    "primary_segment_id": "segment-bread",
                    "segment_ids": ["segment-bread"],
                    "selected_candidate_id": "candidate-wrap",
                    "question_kind": "none",
                    "question_focus": "none",
                    "question_examples": [],
                    "visual_evidence": ["visible wrapper"],
                    "missing_evidence": [],
                    "decision_rationale": "identity is visually strong but still needs affirmation and source",
                    "gate_reason": "",
                    "top_3": [candidate, _candidate_payload(), _candidate_payload()],
                }
            ],
            "decision_rationale": "preserve the full contract before Telegram mapping",
            "gate_reason": "",
        }
        llm_client = type("LLM", (), {})()
        llm_client.chat_completion = AsyncMock(
            return_value={"choices": [{"message": {"content": json.dumps(response_payload)}}]}
        )
        settings = type(
            "Settings",
            (),
            {
                "REASONING_MODEL": "reasoning-primary",
                "REASONING_FALLBACK_MODEL": "reasoning-fallback",
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

        group = result["food_groups"][0]
        self.assertIn("clarification_needed", group)
        self.assertTrue(group["clarification_needed"])
        self.assertEqual(
            [action["type"] for action in group["clarification_actions"]],
            ["AFFIRMATION", "SOURCE_ORIGIN"],
        )
        self.assertEqual(group["clarification"]["type"], "AFFIRMATION")
        self.assertIn("user_prompt", group["clarification_actions"][0])
        self.assertIn("validation_hints", group["clarification_actions"][0])
        self.assertEqual(group["clarification_actions"][1]["type"], "SOURCE_ORIGIN")

    async def test_reasoning_trace_captures_exact_model_input_and_output(self) -> None:
        from app.services import reasoning_service

        meal = type("Meal", (), {"id": "meal-trace", "image_url": None})()
        segment = type("MealSegment", (), {"id": "segment-trace"})()
        candidate = _candidate_payload()
        response_payload = {
            "action": "AUTO_CONFIRM",
            "meal_state": "READY_TO_WRITE",
            "top_3": [candidate],
            "decision_rationale": "ready to auto-confirm",
            "gate_reason": "",
            "segment_count": 1,
            "trace_id": "trace-from-model",
        }
        llm_client = type("LLM", (), {})()
        raw_response = {"choices": [{"message": {"content": json.dumps(response_payload)}}]}
        llm_client.chat_completion = AsyncMock(return_value=raw_response)
        settings = type(
            "Settings",
            (),
            {
                "REASONING_MODEL": "reasoning-primary",
                "REASONING_FALLBACK_MODEL": "reasoning-fallback",
                "REASONING_PARSER_MODEL": "parser-model",
                "REASONING_PARSER_FALLBACK_MODEL": "parser-fallback-model",
                "REASONING_MATCH_THRESHOLD": 0.9,
            },
        )()

        class FakeTrace:
            def __init__(self) -> None:
                self.ended: list[dict[str, Any]] = []

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                return None

            def end(self, output=None, error=None) -> None:
                self.ended.append({"output": output, "error": error})

        fake_trace = FakeTrace()
        with patch.object(reasoning_service.tracing_service, "maybe_start_trace", return_value=fake_trace) as start_trace:
            result, _trace = await reasoning_service.run_reasoning_request(
                llm_client=llm_client,
                meal_id=meal.id,
                meal=meal,
                match_results=[(segment, type("Result", (), {"top_candidates": [candidate]})())],
                settings=settings,
            )

        trace_input = start_trace.call_args.kwargs["input"]
        self.assertEqual(trace_input["meal_id"], "meal-trace")
        self.assertEqual(trace_input["models"], ["reasoning-primary", "reasoning-fallback"])
        self.assertEqual(
            trace_input["extra_body"],
            {
                "parallel_tool_calls": False,
                "reasoning": {
                    "max_tokens": 512,
                    "exclude": True,
                },
            },
        )
        self.assertEqual(trace_input["messages"], llm_client.chat_completion.await_args.kwargs["messages"])
        self.assertEqual(trace_input["response_format"], llm_client.chat_completion.await_args.kwargs["response_format"])
        self.assertEqual(fake_trace.ended[0]["output"]["raw_response"], raw_response)
        self.assertEqual(fake_trace.ended[0]["output"]["parsed_response"]["meal_state"], "READY_TO_WRITE")
        self.assertEqual(result["trace_id"], "trace-from-model")

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
        self.assertTrue(
            llm_client.chat_completion.await_args_list[0].kwargs["response_format"]["json_schema"]["strict"]
        )
        self.assertEqual(
            llm_client.chat_completion.await_args_list[0].kwargs["response_format"]["json_schema"]["name"],
            "reasoning_contract_v1",
        )
        self.assertEqual(repaired["trace_id"], "trace-parser-fallback")

    def test_parser_fallback_default_matches_phase_contract(self) -> None:
        from app.config import Settings

        self.assertEqual(
            Settings.model_fields["REASONING_PARSER_MODEL"].default,
            "google/gemini-3.1-flash-lite",
        )
        self.assertEqual(
            Settings.model_fields["REASONING_PARSER_FALLBACK_MODEL"].default,
            "google/gemini-3.5-flash",
        )

    def test_reasoning_prompt_includes_meal_image_crops_and_phase_context(self) -> None:
        from app.services import reasoning_service

        with tempfile.TemporaryDirectory() as tmp_dir:
            meal_image = Path(tmp_dir) / "meal.jpg"
            crop_image = Path(tmp_dir) / "segment.jpg"
            meal_image.write_bytes(b"meal image bytes")
            crop_image.write_bytes(b"segment image bytes")

            meal = type("Meal", (), {"id": "meal-images", "image_url": str(meal_image)})()
            segment = type(
                "MealSegment",
                (),
                {
                    "id": "seg-egg-curry",
                    "label": "egg curry",
                    "bounding_box": [0.1, 0.2, 0.4, 0.5],
                    "cropped_image_url": str(crop_image),
                },
            )()
            candidate = {
                **_candidate_payload(),
                "label": "egg and bottle gourd curry",
                "nutrition_impact": 0.45,
            }

            messages = reasoning_service._build_reasoning_prompt(
                meal=meal,
                match_results=[(segment, type("Result", (), {"top_candidates": [candidate]})())],
            )

        system_text = messages[0]["content"]
        user_content = messages[1]["content"]
        text_blocks = "\n".join(
            block["text"]
            for block in user_content
            if block.get("type") == "text"
        )
        image_urls = [
            block["image_url"]["url"]
            for block in user_content
            if block.get("type") == "image_url"
        ]

        self.assertIn("Asian-cuisine", system_text)
        self.assertIn("Food groups must be isolated foods", system_text)
        self.assertIn("Do not group bread with curry", system_text)
        self.assertIn("chapatti", system_text)
        self.assertIn("parota", system_text)
        self.assertIn("khubz", system_text)
        self.assertIn("pita", system_text)
        self.assertIn("AUTO_CONFIRM", system_text)
        self.assertIn("ASK_CHOICE", system_text)
        self.assertIn("INTERVIEW", system_text)
        self.assertIn("Example 1", system_text)
        self.assertIn("Example 2", system_text)
        self.assertIn("strict JSON", system_text)
        self.assertIn("whole_meal_image", text_blocks)
        self.assertIn("segment_1", text_blocks)
        self.assertIn("seg-egg-curry", text_blocks)
        self.assertIn("egg curry", text_blocks)
        self.assertIn("egg and bottle gourd curry", text_blocks)
        self.assertIn("bounding_box", text_blocks)
        self.assertIn("top_3_candidates", text_blocks)
        self.assertEqual(len(image_urls), 2)
        self.assertTrue(all(url.startswith("data:image/jpeg;base64,") for url in image_urls))
        self.assertIn("bWVhbCBpbWFnZSBieXRlcw==", image_urls[0])
        self.assertIn("c2VnbWVudCBpbWFnZSBieXRlcw==", image_urls[1])

    def test_reasoning_prompt_marks_empty_vector_context_without_fake_candidates(self) -> None:
        from app.services import reasoning_service

        meal = type("Meal", (), {"id": "meal-empty-vector", "image_url": None})()
        segment = type(
            "MealSegment",
            (),
            {
                "id": "seg-empty-vector",
                "label": "detector bread hint",
                "bounding_box": [0.1, 0.2, 0.4, 0.5],
                "cropped_image_url": None,
            },
        )()
        match_result = type(
            "Result",
            (),
            {
                "top_candidates": [],
                "similarity": None,
                "is_match": False,
                "is_below_threshold": True,
            },
        )()

        messages = reasoning_service._build_reasoning_prompt(
            meal=meal,
            match_results=[(segment, match_result)],
        )

        text_blocks = "\n".join(
            block["text"]
            for block in messages[1]["content"]
            if block.get("type") == "text"
        )

        self.assertIn('"vector_match_status":"NO_VECTOR_CANDIDATES"', text_blocks)
        self.assertIn('"top_3_candidates":[]', text_blocks)
        self.assertIn("No vector candidates were available", text_blocks)
        self.assertNotIn("candidate-0", text_blocks)
        self.assertNotIn("unlabeled food", text_blocks)
