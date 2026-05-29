from __future__ import annotations

import unittest
from typing import Any


def _candidate_payload() -> dict[str, Any]:
    return {
        "candidate_id": "candidate-1",
        "label": "chicken curry",
        "identity_confidence": 0.94,
        "quantity_confidence": 0.84,
        "match_consistency_confidence": 0.9,
        "visual_evidence": ["segment_1: clear protein pieces"],
        "missing_evidence": [],
        "specificity": "high",
        "nutrition_relevance": "medium",
        "source": "vector_match",
        "decision_rationale": "Best visual match with stable rice/curry profile.",
    }


class ReasoningContractTests(unittest.TestCase):
    def test_reasoning_response_format_is_strict_and_action_is_open_string(self) -> None:
        from app.services.reasoning_schema import reasoning_response_format

        response_format = reasoning_response_format()
        schema = response_format["json_schema"]["schema"]

        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["type"], "object")
        self.assertIn("action", schema["required"])
        self.assertIn("meal_state", schema["required"])
        self.assertIn("food_groups", schema["required"])
        self.assertIn("food_group_count", schema["required"])

        food_group_schema = schema["properties"]["food_groups"]
        self.assertEqual(food_group_schema["type"], "array")
        group_schema = food_group_schema["items"]
        self.assertEqual(group_schema["type"], "object")
        self.assertFalse(group_schema["additionalProperties"])
        self.assertIn("group_id", group_schema["required"])
        self.assertIn("primary_segment_id", group_schema["required"])
        self.assertIn("segment_ids", group_schema["required"])
        self.assertIn("top_3", group_schema["required"])

        top_three_schema = group_schema["properties"]["top_3"]
        self.assertEqual(top_three_schema["type"], "array")
        self.assertEqual(top_three_schema["minItems"], 3)
        self.assertEqual(top_three_schema["maxItems"], 3)
        self.assertFalse(top_three_schema["additionalItems"])

        candidate_schema = top_three_schema["items"]
        self.assertEqual(candidate_schema["type"], "object")
        self.assertFalse(candidate_schema["additionalProperties"])
        self.assertIn("items", candidate_schema["properties"]["visual_evidence"])
        self.assertIn("items", candidate_schema["properties"]["missing_evidence"])
        self.assertEqual(
            candidate_schema["properties"]["visual_evidence"]["items"]["type"],
            "string",
        )
        self.assertEqual(
            candidate_schema["properties"]["missing_evidence"]["items"]["type"],
            "string",
        )

        action_schema = schema["properties"]["action"]
        self.assertEqual(action_schema["type"], "string")
        self.assertNotIn("enum", action_schema)
        self.assertNotIn("const", action_schema)

        meal_state_schema = schema["properties"]["meal_state"]
        self.assertEqual(
            set(meal_state_schema["enum"]),
            {
                "READY_TO_WRITE",
                "PENDING_CHOICE",
                "PENDING_INTERVIEW",
                "PARTIAL_RESOLVED_WAITING",
                "FAILED_UNCLEAR",
                "NEEDS_SCHEMA_REVIEW",
            },
        )

    def test_reasoning_response_format_requires_all_declared_fields_for_strict_mode(self) -> None:
        from app.services.reasoning_schema import reasoning_response_format

        response_format = reasoning_response_format()
        schema = response_format["json_schema"]["schema"]

        self.assertEqual(set(schema["required"]), set(schema["properties"]))

        group_schema = schema["properties"]["food_groups"]["items"]
        self.assertEqual(set(group_schema["required"]), set(group_schema["properties"]))

        candidate_schema = group_schema["properties"]["top_3"]["items"]
        self.assertEqual(set(candidate_schema["required"]), set(candidate_schema["properties"]))
        self.assertIn("nutrition_impact", candidate_schema["required"])

    def test_reasoning_contract_requires_evidence_and_rationale_fields(self) -> None:
        from app.services.reasoning_schema import reasoning_response_format

        response_format = reasoning_response_format()
        candidate_schema = response_format["json_schema"]["schema"]["properties"]["food_groups"]["items"]["properties"]["top_3"]["items"]
        required_fields = set(candidate_schema["required"])

        expected_fields = {
            "candidate_id",
            "label",
            "identity_confidence",
            "quantity_confidence",
            "match_consistency_confidence",
            "visual_evidence",
            "missing_evidence",
            "specificity",
            "nutrition_relevance",
            "source",
            "decision_rationale",
        }
        for field in expected_fields:
            self.assertIn(field, required_fields)

    def test_unknown_action_routes_to_needs_schema_review(self) -> None:
        from app.services.reasoning_schema import coerce_reasoning_response

        payload = {
            "action": "SUDDENLY_UNKNOWN_ACTION",
            "meal_state": "READY_TO_WRITE",
            "trace_id": "trace-abc-123",
            "decision_rationale": "model suggested an internal-only branch",
            "gate_reason": "self-confidence is high",
            "segment_count": 1,
            "food_group_count": 1,
            "food_groups": [
                {
                    "group_id": "group-curry",
                    "group_label": "chicken curry",
                    "group_action": "AUTO_CONFIRM",
                    "group_state": "READY_TO_WRITE",
                    "primary_segment_id": "segment-1",
                    "segment_ids": ["segment-1"],
                    "selected_candidate_id": "candidate-1",
                    "visual_evidence": ["segment_1: clear protein pieces"],
                    "missing_evidence": [],
                    "decision_rationale": "best candidate",
                    "gate_reason": "",
                    "top_3": [_candidate_payload(), _candidate_payload(), _candidate_payload()],
                }
            ],
        }

        coerced = coerce_reasoning_response(payload)

        self.assertEqual(coerced["action"], "NEEDS_SCHEMA_REVIEW")
        self.assertEqual(coerced["meal_state"], "NEEDS_SCHEMA_REVIEW")
        self.assertIn("action", coerced["decision_rationale"].lower())

    def test_top_three_payload_preserves_open_action_and_missing_evidence(self) -> None:
        from app.services.reasoning_schema import coerce_reasoning_response

        payload = {
            "action": "ASK_QUANTITY",
            "meal_state": "PENDING_INTERVIEW",
            "trace_id": "trace-321",
            "decision_rationale": "open quantity bucket requested",
            "gate_reason": "ask a question before final write",
            "segment_count": 3,
            "food_group_count": 1,
            "food_groups": [
                {
                    "group_id": "group-curry",
                    "group_label": "chicken curry",
                    "group_action": "ASK_QUANTITY",
                    "group_state": "PENDING_INTERVIEW",
                    "primary_segment_id": "segment-1",
                    "segment_ids": ["segment-1"],
                    "selected_candidate_id": "candidate-1",
                    "visual_evidence": ["segment_1: clear protein pieces"],
                    "missing_evidence": ["portion_unit"],
                    "decision_rationale": "open quantity bucket requested",
                    "gate_reason": "ask a question before final write",
                    "top_3": [
                        {
                            **_candidate_payload(),
                            "candidate_id": "candidate-1",
                        },
                        {
                            **_candidate_payload(),
                            "candidate_id": "candidate-2",
                            "missing_evidence": ["portion_unit", "serving_size"],
                            "visual_evidence": [],
                        },
                        {
                            **_candidate_payload(),
                            "candidate_id": "candidate-3",
                        },
                    ],
                }
            ],
        }

        normalized = coerce_reasoning_response(payload)
        self.assertEqual(normalized["action"], "ASK_QUANTITY")
        self.assertEqual(normalized["meal_state"], "PENDING_INTERVIEW")
        self.assertEqual(normalized["trace_id"], "trace-321")
        self.assertEqual(len(normalized["food_groups"][0]["top_3"]), 3)
        self.assertIn("portion_unit", normalized["food_groups"][0]["top_3"][1]["missing_evidence"])

    def test_grouped_reasoning_contract_requires_food_groups(self) -> None:
        from app.services.reasoning_schema import coerce_reasoning_response, reasoning_response_format

        schema = reasoning_response_format()["json_schema"]["schema"]

        self.assertIn("food_groups", schema["required"])
        self.assertIn("food_group_count", schema["required"])
        self.assertNotIn("top_3", schema["properties"])
        group_schema = schema["properties"]["food_groups"]["items"]
        self.assertIn("question_kind", group_schema["required"])
        self.assertIn("question_focus", group_schema["required"])
        self.assertIn("question_examples", group_schema["required"])

        grouped = coerce_reasoning_response(
            {
                "action": "AUTO_CONFIRM",
                "meal_state": "READY_TO_WRITE",
                "trace_id": "trace-grouped-contract",
                "decision_rationale": "grouped contract should reject missing food_groups",
                "gate_reason": "",
                "segment_count": 2,
            }
        )

        self.assertEqual(grouped["meal_state"], "NEEDS_SCHEMA_REVIEW")

    def test_grouped_reasoning_contract_preserves_question_metadata(self) -> None:
        from app.services.reasoning_schema import coerce_reasoning_response

        grouped = coerce_reasoning_response(
            {
                "action": "ASK_CHOICE",
                "meal_state": "PENDING_INTERVIEW",
                "trace_id": "trace-question",
                "decision_rationale": "hidden curry detail needs a follow-up",
                "gate_reason": "missing hidden vegetable",
                "segment_count": 1,
                "food_group_count": 1,
                "food_groups": [
                    {
                        "group_id": "group-egg-curry",
                        "group_label": "egg curry",
                        "group_action": "ASK_CHOICE",
                        "group_state": "PENDING_INTERVIEW",
                        "primary_segment_id": "seg-egg",
                        "segment_ids": ["seg-egg"],
                        "selected_candidate_id": "candidate-egg",
                        "visual_evidence": ["egg visible"],
                        "missing_evidence": ["vegetable inside curry"],
                        "decision_rationale": "egg visible but vegetable is hidden",
                        "gate_reason": "missing hidden vegetable",
                        "question_kind": "DETAIL",
                        "question_focus": "vegetable inside egg curry",
                        "question_examples": ["egg curry with bottle gourd"],
                        "top_3": [_candidate_payload(), _candidate_payload(), _candidate_payload()],
                    }
                ],
            }
        )

        group = grouped["food_groups"][0]
        self.assertEqual(group["question_kind"], "DETAIL")
        self.assertEqual(group["question_focus"], "vegetable inside egg curry")
        self.assertEqual(group["question_examples"], ["egg curry with bottle gourd"])
