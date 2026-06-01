from __future__ import annotations

import importlib
import importlib.util
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError


def _load_module_or_fail(testcase: unittest.TestCase, module_name: str):
    spec = importlib.util.find_spec(module_name)
    testcase.assertIsNotNone(spec, f"Missing module: {module_name}")
    if spec is None:
        return None
    return importlib.import_module(module_name)


class InterviewConfigContractTests(unittest.TestCase):
    def test_settings_expose_explicit_interview_models(self) -> None:
        from app.config import Settings

        fields = Settings.model_fields

        self.assertIn("INTERVIEW_MODEL", fields)
        self.assertIn("INTERVIEW_FALLBACK_MODEL", fields)
        self.assertEqual(fields["INTERVIEW_MODEL"].default, "google/gemini-3.1-flash-lite")
        self.assertEqual(fields["INTERVIEW_FALLBACK_MODEL"].default, "google/gemini-3-flash-preview")


class InterviewSchemaContractTests(unittest.TestCase):
    def test_schema_module_exposes_strict_contract_and_response_format(self) -> None:
        schema_module = _load_module_or_fail(self, "app.services.interview_schema")
        if schema_module is None:
            return

        confirmation_item = getattr(schema_module, "ConfirmationItem", None)
        interview_turn_result = getattr(schema_module, "InterviewTurnResult", None)
        response_format_helper = getattr(schema_module, "interview_turn_response_format", None)

        self.assertTrue(callable(response_format_helper))
        self.assertIsNotNone(confirmation_item)
        self.assertIsNotNone(interview_turn_result)

        response_format = response_format_helper()
        self.assertEqual(response_format["type"], "json_schema")
        self.assertTrue(response_format["json_schema"]["strict"])

        schema = response_format["json_schema"]["schema"]
        self.assertEqual(
            schema["properties"]["turn_action"]["enum"],
            ["continue_interview", "need_clarification", "ready_to_confirm"],
        )
        confirmation_items = schema["properties"]["confirmation_items"]
        item_properties = confirmation_items["items"]["properties"]
        self.assertIn("approval_status", item_properties)
        self.assertEqual(item_properties["approval_status"]["enum"], ["APPROVED", "CORRECTED"])
        self.assertIn("segment_ids", item_properties)

    def test_response_format_limits_final_resolver_to_ready_to_confirm(self) -> None:
        schema_module = _load_module_or_fail(self, "app.services.interview_schema")
        if schema_module is None:
            return

        response_format = schema_module.interview_turn_response_format()
        schema = response_format["json_schema"]["schema"]

        self.assertEqual(
            schema["properties"]["turn_action"]["enum"],
            ["ready_to_confirm"],
        )

    def test_confirmation_item_tracks_group_segment_membership(self) -> None:
        schema_module = _load_module_or_fail(self, "app.services.interview_schema")
        if schema_module is None:
            return

        confirmation_item = getattr(schema_module, "ConfirmationItem", None)
        self.assertIsNotNone(confirmation_item)
        if confirmation_item is None:
            return

        item = confirmation_item.model_validate(
            {
                "group_id": "group-egg-curry",
                "primary_segment_id": "seg-egg-1",
                "segment_id": "seg-egg-1",
                "segment_ids": ["seg-egg-2", "seg-egg-1", "seg-egg-2"],
                "name": "egg curry with bottle gourd",
                "source_type": "HOME",
                "portion_bucket": "STANDARD",
                "approval_status": "CORRECTED",
            }
        )

        self.assertEqual(item.segment_ids, ["seg-egg-2", "seg-egg-1"])

    def test_confirmation_item_requires_approval_status(self) -> None:
        schema_module = _load_module_or_fail(self, "app.services.interview_schema")
        if schema_module is None:
            return

        confirmation_item = getattr(schema_module, "ConfirmationItem", None)
        self.assertIsNotNone(confirmation_item)
        if confirmation_item is None:
            return

        with self.assertRaises(ValidationError):
            confirmation_item.model_validate(
                {
                    "group_id": "group-egg-curry",
                    "primary_segment_id": "seg-egg-1",
                    "segment_id": "seg-egg-1",
                    "name": "egg curry with bottle gourd",
                    "source_type": "HOME",
                    "portion_bucket": "STANDARD",
                }
            )


class InterviewTurnManagerContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_interview_trace_captures_model_context_and_outputs(self) -> None:
        manager_module = _load_module_or_fail(self, "app.services.interview_turn_manager")
        if manager_module is None:
            return

        run_interview_turn = getattr(manager_module, "run_interview_turn", None)
        self.assertTrue(callable(run_interview_turn))
        if not callable(run_interview_turn):
            return

        raw_response = {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"turn_action":"continue_interview","assistant_prompt":"What kind of curry is it?",'
                            '"clarification_reason":"Need the curry vegetable.","conversation_summary":"Asked curry detail.",'
                            '"confirmation_items":[]}'
                        )
                    }
                }
            ]
        }
        llm_client = SimpleNamespace(chat_completion=AsyncMock(return_value=raw_response))

        class FakeTrace:
            def __init__(self) -> None:
                self.ended = []

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                return None

            def end(self, *, output=None, error=None) -> None:
                self.ended.append({"output": output, "error": error})

        fake_trace = FakeTrace()
        settings = SimpleNamespace(
            INTERVIEW_MODEL="interview-primary",
            INTERVIEW_FALLBACK_MODEL="interview-fallback",
        )
        authoritative_state = {
            "meal_id": "meal-trace",
            "unresolved_targets": [{"group_id": "group-curry"}],
            "approval_candidates": [{"group_id": "group-pita"}],
        }
        transcript = [
            {"role": "assistant", "content": "Please clarify the curry."},
            {"role": "user", "content": "Maybe bottle gourd."},
        ]

        with patch.object(manager_module.tracing_service, "maybe_start_trace", return_value=fake_trace) as start_trace:
            result = await run_interview_turn(
                authoritative_state=authoritative_state,
                transcript=transcript,
                latest_user_text="It's bottle gourd.",
                settings=settings,
                llm_client=llm_client,
            )

        trace_input = start_trace.call_args.kwargs["input"]
        self.assertEqual(trace_input["meal_id"], "meal-trace")
        self.assertEqual(trace_input["models"], ["interview-primary", "interview-fallback"])
        self.assertEqual(trace_input["authoritative_state"], authoritative_state)
        self.assertEqual(trace_input["transcript"], transcript)
        self.assertEqual(trace_input["latest_user_text"], "It's bottle gourd.")
        self.assertEqual(fake_trace.ended[0]["output"]["raw_response"], raw_response)
        self.assertEqual(fake_trace.ended[0]["output"]["selected_model"], "interview-primary")
        self.assertEqual(fake_trace.ended[0]["output"]["parsed_response"]["turn_action"], "continue_interview")
        self.assertIsNone(fake_trace.ended[0]["output"]["repair_response"])
        self.assertEqual(result.turn_action, "continue_interview")

    async def test_single_repair_retry_recovers_malformed_first_pass(self) -> None:
        manager_module = _load_module_or_fail(self, "app.services.interview_turn_manager")
        if manager_module is None:
            return

        run_interview_turn = getattr(manager_module, "run_interview_turn", None)
        self.assertTrue(callable(run_interview_turn))
        if not callable(run_interview_turn):
            return

        llm_client = SimpleNamespace(
            chat_completion=AsyncMock(
                side_effect=[
                    {"choices": [{"message": {"content": "not-json"}}]},
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": (
                                        '{"turn_action":"ready_to_confirm","assistant_prompt":"Confirming all items.",'
                                        '"clarification_reason":null,"conversation_summary":"Resolved meal.",'
                                        '"confirmation_items":[{"group_id":"group-egg-curry","primary_segment_id":"seg-egg-1",'
                                        '"segment_id":"seg-egg-1","name":"egg curry with bottle gourd","source_type":"HOME",'
                                        '"portion_bucket":"STANDARD","approval_status":"CORRECTED"},'
                                        '{"group_id":"group-pita","primary_segment_id":"seg-bread-1","segment_id":"seg-bread-1",'
                                        '"name":"pita bread","source_type":"HOME","portion_bucket":"STANDARD",'
                                        '"approval_status":"APPROVED"}]}'
                                    )
                                }
                            }
                        ]
                    },
                ]
            )
        )

        with (
            patch.object(manager_module, "get_llm_client", return_value=llm_client),
            patch.object(manager_module.tracing_service, "maybe_start_trace"),
        ):
            result = await run_interview_turn(
                authoritative_state={
                    "meal_id": "meal-1",
                    "unresolved_targets": [
                        {
                            "group_id": "group-egg-curry",
                            "primary_segment_id": "seg-egg-1",
                            "segment_ids": ["seg-egg-1", "seg-egg-2"],
                        }
                    ],
                    "approval_candidates": [
                        {
                            "group_id": "group-pita",
                            "proposed_name": "pita bread",
                            "primary_segment_id": "seg-bread-1",
                            "segment_ids": ["seg-bread-1"],
                        }
                    ],
                },
                transcript=[{"role": "assistant", "content": "What is the curry?"}],
                latest_user_text="It's bottle gourd and pita is right.",
            )

        self.assertEqual(result.turn_action, "ready_to_confirm")
        self.assertEqual(result.confirmation_items[0].segment_ids, ["seg-egg-1", "seg-egg-2"])
        self.assertEqual(result.confirmation_items[1].segment_ids, ["seg-bread-1"])
        self.assertEqual(llm_client.chat_completion.await_count, 2)

    async def test_ready_to_confirm_without_approval_candidate_evidence_repairs_to_followup(self) -> None:
        manager_module = _load_module_or_fail(self, "app.services.interview_turn_manager")
        if manager_module is None:
            return

        run_interview_turn = getattr(manager_module, "run_interview_turn", None)
        self.assertTrue(callable(run_interview_turn))
        if not callable(run_interview_turn):
            return

        llm_client = SimpleNamespace(
            chat_completion=AsyncMock(
                side_effect=[
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": (
                                        '{"turn_action":"ready_to_confirm","assistant_prompt":"Ready to confirm.",'
                                        '"clarification_reason":null,"conversation_summary":"Resolved.",'
                                        '"confirmation_items":[{"group_id":"group-egg","primary_segment_id":"seg-egg",'
                                        '"segment_id":"seg-egg","name":"egg curry with bottle gourd","source_type":"HOME",'
                                        '"portion_bucket":"STANDARD","approval_status":"CORRECTED"},'
                                        '{"group_id":"group-pita","primary_segment_id":"seg-pita","segment_id":"seg-pita",'
                                        '"name":"white khubz bread","source_type":"HOME","portion_bucket":"STANDARD",'
                                        '"approval_status":"CORRECTED"},'
                                        '{"group_id":"group-chicken","primary_segment_id":"seg-chicken","segment_id":"seg-chicken",'
                                        '"name":"chicken drumstick curry","source_type":"HOME","portion_bucket":"STANDARD",'
                                        '"approval_status":"APPROVED"}]}'
                                    )
                                }
                            }
                        ]
                    },
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": (
                                        '{"turn_action":"continue_interview","assistant_prompt":"Got bottle gourd and white khubz. '
                                        'Please confirm or correct the chicken drumstick curry too.",'
                                        '"clarification_reason":"Chicken approval was not explicitly confirmed.",'
                                        '"conversation_summary":"Need chicken confirmation.","confirmation_items":[]}'
                                    )
                                }
                            }
                        ]
                    },
                ]
            )
        )

        with (
            patch.object(manager_module, "get_llm_client", return_value=llm_client),
            patch.object(manager_module.tracing_service, "maybe_start_trace"),
        ):
            result = await run_interview_turn(
                authoritative_state={
                    "meal_id": "meal-1",
                    "unresolved_targets": [
                        {
                            "group_id": "group-egg",
                            "label": "egg curry",
                            "primary_segment_id": "seg-egg",
                            "segment_ids": ["seg-egg"],
                        }
                    ],
                    "approval_candidates": [
                        {
                            "group_id": "group-pita",
                            "label": "pita bread",
                            "proposed_name": "brown pita bread",
                            "primary_segment_id": "seg-pita",
                            "segment_ids": ["seg-pita"],
                        },
                        {
                            "group_id": "group-chicken",
                            "label": "chicken curry",
                            "proposed_name": "chicken drumstick curry",
                            "primary_segment_id": "seg-chicken",
                            "segment_ids": ["seg-chicken"],
                        },
                    ],
                },
                transcript=[{"role": "assistant", "content": "What vegetable, and are pita and chicken correct?"}],
                latest_user_text="It's bottle gourd. It's actually white khubz bread.",
            )

        self.assertEqual(result.turn_action, "continue_interview")
        self.assertIn("chicken", result.assistant_prompt.lower())
        self.assertEqual(llm_client.chat_completion.await_count, 2)

    async def test_ready_to_confirm_accepts_prior_thread_confirmation_for_approval_candidates(self) -> None:
        manager_module = _load_module_or_fail(self, "app.services.interview_turn_manager")
        if manager_module is None:
            return

        run_interview_turn = getattr(manager_module, "run_interview_turn", None)
        self.assertTrue(callable(run_interview_turn))
        if not callable(run_interview_turn):
            return

        llm_client = SimpleNamespace(
            chat_completion=AsyncMock(
                return_value={
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    '{"turn_action":"ready_to_confirm","assistant_prompt":"Ready to save.",'
                                    '"clarification_reason":null,"conversation_summary":"Resolved.",'
                                    '"confirmation_items":[{"group_id":"group-flatbread","primary_segment_id":"seg-bread",'
                                    '"segment_id":"seg-bread","name":"white khubz","source_type":"HOME",'
                                    '"portion_bucket":"STANDARD","approval_status":"CORRECTED"},'
                                    '{"group_id":"group-chicken","primary_segment_id":"seg-chicken","segment_id":"seg-chicken",'
                                    '"name":"chicken phaal with drumstick","source_type":"HOME","portion_bucket":"STANDARD",'
                                    '"approval_status":"APPROVED"},'
                                    '{"group_id":"group-egg","primary_segment_id":"seg-egg","segment_id":"seg-egg",'
                                    '"name":"egg and bottle gourd curry","source_type":"HOME","portion_bucket":"STANDARD",'
                                    '"approval_status":"APPROVED"}]}'
                                )
                            }
                        }
                    ]
                }
            )
        )

        authoritative_state = {
            "meal_id": "meal-1",
            "unresolved_targets": [
                {
                    "group_id": "group-flatbread",
                    "label": "flatbread",
                    "primary_segment_id": "seg-bread",
                    "segment_ids": ["seg-bread"],
                }
            ],
            "approval_candidates": [
                {
                    "group_id": "group-chicken",
                    "label": "chicken curry",
                    "proposed_name": "chicken phaal with drumstick",
                    "primary_segment_id": "seg-chicken",
                    "segment_ids": ["seg-chicken"],
                },
                {
                    "group_id": "group-egg",
                    "label": "egg curry",
                    "proposed_name": "egg and bottle gourd curry",
                    "primary_segment_id": "seg-egg",
                    "segment_ids": ["seg-egg"],
                },
            ],
            "interview_messages": [
                {"role": "assistant", "content": "Pick the flatbread and confirm chicken and egg."},
                {"role": "user", "content": "Yes these are correct"},
                {"role": "assistant", "content": "Please pick the flatbread."},
            ],
        }

        with (
            patch.object(manager_module, "get_llm_client", return_value=llm_client),
            patch.object(manager_module.tracing_service, "maybe_start_trace"),
        ):
            result = await run_interview_turn(
                authoritative_state=authoritative_state,
                transcript=authoritative_state["interview_messages"],
                latest_user_text="I confirm the item is white khubz",
            )

        self.assertEqual(result.turn_action, "ready_to_confirm")
        self.assertEqual([item.group_id for item in result.confirmation_items], ["group-flatbread", "group-chicken", "group-egg"])
        self.assertEqual(llm_client.chat_completion.await_count, 1)

    async def test_invalid_ready_to_confirm_fails_closed_without_mutating_state(self) -> None:
        manager_module = _load_module_or_fail(self, "app.services.interview_turn_manager")
        if manager_module is None:
            return

        run_interview_turn = getattr(manager_module, "run_interview_turn", None)
        validation_error = getattr(manager_module, "InterviewTurnValidationError", Exception)
        self.assertTrue(callable(run_interview_turn))
        if not callable(run_interview_turn):
            return

        llm_client = SimpleNamespace(
            chat_completion=AsyncMock(
                side_effect=[
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": (
                                        '{"turn_action":"ready_to_confirm","assistant_prompt":"Looks good.",'
                                        '"clarification_reason":null,"conversation_summary":"Done.",'
                                        '"confirmation_items":[{"group_id":"group-egg-curry","primary_segment_id":"seg-egg-1",'
                                        '"segment_id":"seg-egg-1","name":"egg curry with bottle gourd","source_type":"HOME",'
                                        '"brand_name":"Acme","restaurant_name":"Cafe","portion_bucket":"STANDARD",'
                                        '"approval_status":"CORRECTED"}]}'
                                    )
                                }
                            }
                        ]
                    },
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": (
                                        '{"turn_action":"ready_to_confirm","assistant_prompt":"Still looks good.",'
                                        '"clarification_reason":null,"conversation_summary":"Done.",'
                                        '"confirmation_items":[{"group_id":"group-egg-curry","primary_segment_id":"seg-egg-1",'
                                        '"segment_id":"seg-egg-1","name":"egg curry with bottle gourd","source_type":"HOME",'
                                        '"brand_name":"Acme","restaurant_name":"Cafe","portion_bucket":"STANDARD",'
                                        '"approval_status":"CORRECTED"}]}'
                                    )
                                }
                            }
                        ]
                    },
                ]
            )
        )
        authoritative_state = {
            "meal_id": "meal-1",
            "unresolved_targets": [{"group_id": "group-egg-curry"}],
            "approval_candidates": [{"group_id": "group-pita"}],
        }

        with (
            patch.object(manager_module, "get_llm_client", return_value=llm_client),
            patch.object(manager_module.tracing_service, "maybe_start_trace"),
        ):
            with self.assertRaises(validation_error):
                await run_interview_turn(
                    authoritative_state=authoritative_state,
                    transcript=[{"role": "assistant", "content": "Confirm pita bread too."}],
                    latest_user_text="It's bottle gourd.",
                )

        self.assertEqual(
            authoritative_state,
            {
                "meal_id": "meal-1",
                "unresolved_targets": [{"group_id": "group-egg-curry"}],
                "approval_candidates": [{"group_id": "group-pita"}],
            },
        )
        self.assertEqual(llm_client.chat_completion.await_count, 2)
