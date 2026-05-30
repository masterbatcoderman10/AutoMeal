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
                    "unresolved_targets": [{"group_id": "group-egg-curry"}],
                    "approval_candidates": [{"group_id": "group-pita"}],
                },
                transcript=[{"role": "assistant", "content": "What is the curry?"}],
                latest_user_text="It's bottle gourd.",
            )

        self.assertEqual(result.turn_action, "ready_to_confirm")
        self.assertEqual(llm_client.chat_completion.await_count, 2)

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
