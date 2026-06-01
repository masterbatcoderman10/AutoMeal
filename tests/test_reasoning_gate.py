from __future__ import annotations

import unittest
from typing import Any


INTERVIEW_STATES = {"PENDING_INTERVIEW", "PENDING_CHOICE", "INTERVIEWING", "PARTIAL_RESOLVED_WAITING"}


def _candidate_payload(
    *,
    candidate_id: str,
    similarity: float,
    label: str = "plate of rice and curry",
    missing: list[str] | None = None,
    nutrition_impact: float = 0.1,
) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "label": label,
        "identity_confidence": similarity,
        "quantity_confidence": 0.78,
        "match_consistency_confidence": similarity,
        "visual_evidence": ["segment_1: rice mound and curry gravy"],
        "missing_evidence": missing or [],
        "specificity": "high",
        "nutrition_relevance": "medium",
        "source": "vector_match",
        "decision_rationale": "high-level visual alignment",
        "nutrition_impact": nutrition_impact,
    }


def _resolve_gate_function(module) -> Any:
    for name in (
        "evaluate_reasoning_gate",
        "reasoning_gate",
        "resolve_reasoning_gate",
    ):
        fn = getattr(module, name, None)
        if callable(fn):
            return fn
    raise AssertionError(
        "No reasoning gate function found. Expected one of "
        "evaluate_reasoning_gate, reasoning_gate, resolve_reasoning_gate."
    )


def _run_gate(payload: dict[str, Any]) -> dict[str, Any]:
    from app.services import reasoning_service

    fn = _resolve_gate_function(reasoning_service)
    return fn(reasoning_payload=payload)


class ReasoningGateTests(unittest.TestCase):
    def test_disagreeing_signals_escalate_to_interview(self) -> None:
        payload = {
            "action": "AUTO_CONFIRM",
            "meal_state": "READY_TO_WRITE",
            "trace_id": "trace-disagree",
            "top_3": [
                _candidate_payload(
                    candidate_id="best",
                    similarity=0.96,
                    missing=["portion_unit"],
                    nutrition_impact=0.72,
                ),
                _candidate_payload(candidate_id="fallback_1", similarity=0.95),
                _candidate_payload(candidate_id="fallback_2", similarity=0.91),
            ],
            "decision_rationale": "candidate looks like chicken but portion unclear",
            "gate_reason": "",
            "segment_count": 2,
        }

        result = _run_gate(payload)

        self.assertIn(result["meal_state"], INTERVIEW_STATES)
        self.assertIn(result["action"], {"ASK_QUANTITY", "ASK_CHOICE", "INTERVIEW"})
        self.assertIn("missing", (result.get("gate_reason") or "").lower())

    def test_gate_matrix_rejects_self_confidence_only_logic(self) -> None:
        matrix = [
            {
                "label": "low similarity requires interview",
                "payload": {
                    "action": "AUTO_CONFIRM",
                    "meal_state": "READY_TO_WRITE",
                    "trace_id": "trace-low-sim",
                    "top_3": [
                        _candidate_payload(candidate_id="best", similarity=0.72),
                        _candidate_payload(candidate_id="fallback_1", similarity=0.68),
                        _candidate_payload(candidate_id="fallback_2", similarity=0.64),
                    ],
                    "decision_rationale": "overall uncertain",
                    "gate_reason": "",
                    "segment_count": 1,
                },
            },
            {
                "label": "low candidate margin requires interview",
                "payload": {
                    "action": "AUTO_CONFIRM",
                    "meal_state": "READY_TO_WRITE",
                    "trace_id": "trace-low-margin",
                    "top_3": [
                        _candidate_payload(candidate_id="best", similarity=0.92),
                        _candidate_payload(candidate_id="fallback_1", similarity=0.91),
                        _candidate_payload(candidate_id="fallback_2", similarity=0.9),
                    ],
                    "decision_rationale": "close runners",
                    "gate_reason": "",
                    "segment_count": 1,
                },
            },
            {
                "label": "missing evidence requires interview",
                "payload": {
                    "action": "AUTO_CONFIRM",
                    "meal_state": "READY_TO_WRITE",
                    "trace_id": "trace-missing-evidence",
                    "top_3": [
                        _candidate_payload(
                            candidate_id="best",
                            similarity=0.98,
                            missing=["serving_unit", "cooking_state"],
                        ),
                        _candidate_payload(candidate_id="fallback_1", similarity=0.78),
                        _candidate_payload(candidate_id="fallback_2", similarity=0.75),
                    ],
                    "decision_rationale": "detail is missing",
                    "gate_reason": "",
                    "segment_count": 1,
                },
            },
            {
                "label": "high nutrition impact alone does not require interview",
                "payload": {
                    "action": "AUTO_CONFIRM",
                    "meal_state": "READY_TO_WRITE",
                    "trace_id": "trace-high-nutrition",
                    "top_3": [
                        _candidate_payload(
                            candidate_id="best",
                            similarity=0.98,
                            nutrition_impact=0.55,
                        ),
                        _candidate_payload(candidate_id="fallback_1", similarity=0.8),
                        _candidate_payload(candidate_id="fallback_2", similarity=0.8),
                    ],
                    "decision_rationale": "large impact candidate",
                    "gate_reason": "",
                    "segment_count": 1,
                },
            },
        ]

        for row in matrix:
            with self.subTest(row["label"]):
                result = _run_gate(row["payload"])
                if row["label"] == "high nutrition impact alone does not require interview":
                    self.assertEqual(result["meal_state"], "READY_TO_WRITE")
                    self.assertIn(result["action"], {"AUTO_CONFIRM", "AUTO_CONFIRM_WITH_TRACE", "READY_TO_WRITE"})
                else:
                    self.assertIn(
                        result["meal_state"],
                        INTERVIEW_STATES,
                        msg=f"{row['label']} should route to interview",
                    )

    def test_gate_emits_deterministic_clarification_batch_for_interview_groups(self) -> None:
        payload = {
            "action": "AUTO_CONFIRM",
            "meal_state": "READY_TO_WRITE",
            "trace_id": "trace-deterministic-clarifications",
            "food_group_count": 2,
            "segment_count": 2,
            "decision_rationale": "bread and curry need user confirmation",
            "gate_reason": "",
            "food_groups": [
                {
                    "group_id": "group-1",
                    "group_label": "pita bread",
                    "group_action": "ASK_CHOICE",
                    "group_state": "PENDING_INTERVIEW",
                    "primary_segment_id": "segment-bread",
                    "segment_ids": ["segment-bread"],
                    "selected_candidate_id": "candidate-pita",
                    "visual_evidence": ["flatbread profile"],
                    "missing_evidence": [],
                    "decision_rationale": "bread type affects nutrition",
                    "gate_reason": "needs source-safe clarification",
                    "question_kind": "CHOICE",
                    "question_focus": "bread subtype",
                    "question_examples": ["pita", "naan", "roti"],
                    "top_3": [
                        _candidate_payload(candidate_id="candidate-pita", similarity=0.89),
                        _candidate_payload(candidate_id="candidate-naan", similarity=0.82, label="naan bread"),
                        _candidate_payload(candidate_id="candidate-roti", similarity=0.81, label="roti bread"),
                    ],
                },
                {
                    "group_id": "group-2",
                    "group_label": "egg curry",
                    "group_action": "ASK_QUANTITY",
                    "group_state": "PENDING_INTERVIEW",
                    "primary_segment_id": "segment-curry",
                    "segment_ids": ["segment-curry"],
                    "selected_candidate_id": "candidate-curry",
                    "visual_evidence": ["curry visible"],
                    "missing_evidence": ["portion_unit"],
                    "decision_rationale": "need portion for calorie estimate",
                    "gate_reason": "missing portion details",
                    "question_kind": "QUANTITY",
                    "question_focus": "portion estimate",
                    "question_examples": [],
                    "top_3": [
                        _candidate_payload(candidate_id="candidate-curry", similarity=0.95, label="egg curry"),
                        _candidate_payload(candidate_id="candidate-chicken", similarity=0.88, label="chicken curry"),
                        _candidate_payload(candidate_id="candidate-mixed", similarity=0.79, label="mixed curry"),
                    ],
                },
            ],
        }

        result = _run_gate(payload)

        self.assertEqual(result["meal_state"], "PARTIAL_RESOLVED_WAITING")
        clarification = result.get("clarification_schema")
        self.assertIsInstance(clarification, list)
        self.assertGreaterEqual(len(clarification), 2)

        question_ids = [question["question_id"] for question in clarification]
        self.assertEqual(question_ids, sorted(question_ids))
        self.assertEqual(len(set(question_ids)), len(question_ids))

        first_pass = _run_gate(payload)
        first_pass_ids = [question["question_id"] for question in first_pass["clarification_schema"]]
        self.assertEqual(question_ids, first_pass_ids)

    def test_source_origin_question_only_for_ambiguous_material_foods(self) -> None:
        payload = {
            "action": "AUTO_CONFIRM",
            "meal_state": "READY_TO_WRITE",
            "trace_id": "trace-source-origin",
            "food_group_count": 2,
            "segment_count": 2,
            "decision_rationale": "mixed foods in one frame",
            "gate_reason": "",
            "food_groups": [
                {
                    "group_id": "group-curry",
                    "group_label": "egg curry",
                    "group_action": "ASK_CHOICE",
                    "group_state": "PENDING_INTERVIEW",
                    "primary_segment_id": "segment-curry",
                    "segment_ids": ["segment-curry"],
                    "selected_candidate_id": "candidate-curry",
                    "visual_evidence": ["home-style curry"],
                    "missing_evidence": ["vegetable inside curry"],
                    "decision_rationale": "home-style curry needs confirmation",
                    "gate_reason": "missing hidden vegetable",
                    "question_kind": "DETAIL",
                    "question_focus": "ingredient detail",
                    "question_examples": ["egg curry", "chicken curry"],
                    "top_3": [
                        _candidate_payload(
                            candidate_id="candidate-curry",
                            similarity=0.89,
                            label="egg curry",
                        ),
                        _candidate_payload(
                            candidate_id="candidate-chicken-curry",
                            similarity=0.86,
                            label="chicken curry",
                        ),
                        _candidate_payload(
                            candidate_id="candidate-mixed-curry",
                            similarity=0.81,
                            label="mixed curry",
                        ),
                    ],
                },
                {
                    "group_id": "group-bread",
                    "group_label": "restaurant wrap flatbread",
                    "group_action": "ASK_CHOICE",
                    "group_state": "PENDING_INTERVIEW",
                    "primary_segment_id": "segment-bread",
                    "segment_ids": ["segment-bread"],
                    "selected_candidate_id": "candidate-wrap",
                    "visual_evidence": ["flatbread wrap in packaging"],
                    "missing_evidence": [],
                    "decision_rationale": "flatbread is ambiguous",
                    "gate_reason": "requires material source check",
                    "question_kind": "CHOICE",
                    "question_focus": "bread subtype",
                    "question_examples": ["naan", "pita", "wrap", "bakery bread"],
                    "top_3": [
                        _candidate_payload(candidate_id="candidate-wrap", similarity=0.9, label="restaurant wrap flatbread"),
                        _candidate_payload(candidate_id="candidate-khubz", similarity=0.86, label="khubz"),
                        _candidate_payload(candidate_id="candidate-pita", similarity=0.84, label="pita bread"),
                    ],
                },
            ],
        }

        result = _run_gate(payload)
        kinds = {question["question_kind"] for question in result.get("clarification_schema", [])}
        self.assertIn("SOURCE_ORIGIN", kinds)
        self.assertNotIn(
            "SOURCE_ORIGIN",
            {
                question["question_kind"]
                for question in result.get("clarification_schema", [])
                if question.get("group_id") == "group-curry"
            },
            "Home-style curry should not trigger source-origin clarification",
        )

    def test_high_nutrition_impact_supports_existing_uncertainty_signal(self) -> None:
        payload = {
            "action": "AUTO_CONFIRM",
            "meal_state": "READY_TO_WRITE",
            "trace_id": "trace-high-nutrition-supporting",
            "top_3": [
                _candidate_payload(
                    candidate_id="best",
                    similarity=0.98,
                    nutrition_impact=0.55,
                ),
                _candidate_payload(candidate_id="fallback_1", similarity=0.95),
                _candidate_payload(candidate_id="fallback_2", similarity=0.8),
            ],
            "decision_rationale": "best candidate is strong but close to fallback",
            "gate_reason": "",
            "segment_count": 1,
        }

        result = _run_gate(payload)

        self.assertIn(result["meal_state"], INTERVIEW_STATES)
        self.assertIn("nutrition impact", result.get("gate_reason") or "")

    def test_gate_prefers_ready_to_write_when_confidence_and_context_are_clean(self) -> None:
        payload = {
            "action": "AUTO_CONFIRM",
            "meal_state": "READY_TO_WRITE",
            "trace_id": "trace-clean",
            "top_3": [
                _candidate_payload(
                    candidate_id="best",
                    similarity=0.99,
                    missing=[],
                    nutrition_impact=0.02,
                ),
                _candidate_payload(candidate_id="fallback_1", similarity=0.82),
                _candidate_payload(candidate_id="fallback_2", similarity=0.78),
            ],
            "decision_rationale": "strong match and low nutrition ambiguity",
            "gate_reason": "",
            "segment_count": 1,
        }

        result = _run_gate(payload)

        self.assertEqual(result["meal_state"], "READY_TO_WRITE")
        self.assertIn(
            result["action"],
            {"AUTO_CONFIRM", "READY_TO_WRITE", "AUTO_CONFIRM_WITH_TRACE"},
        )
        self.assertIn("auto-confirm", (result.get("decision_rationale") or "").lower())

    def test_group_gate_keeps_unrelated_foods_in_separate_races(self) -> None:
        payload = {
            "action": "AUTO_CONFIRM",
            "meal_state": "READY_TO_WRITE",
            "trace_id": "trace-grouped-gate",
            "decision_rationale": "bread is obvious but curry details remain uncertain",
            "gate_reason": "",
            "segment_count": 3,
            "food_group_count": 2,
            "food_groups": [
                {
                    "group_id": "group-pita",
                    "group_label": "pita bread",
                    "primary_segment_id": "segment-bread-1",
                    "segment_ids": ["segment-bread-1", "segment-bread-2"],
                    "top_3": [
                        _candidate_payload(
                            candidate_id="candidate-pita",
                            label="pita bread",
                            similarity=0.99,
                            nutrition_impact=0.02,
                        ),
                        _candidate_payload(
                            candidate_id="candidate-naan",
                            label="naan bread",
                            similarity=0.73,
                            nutrition_impact=0.04,
                        ),
                        _candidate_payload(
                            candidate_id="candidate-roti",
                            label="roti bread",
                            similarity=0.7,
                            nutrition_impact=0.04,
                        ),
                    ],
                },
                {
                    "group_id": "group-curry",
                    "group_label": "egg curry",
                    "primary_segment_id": "segment-curry",
                    "segment_ids": ["segment-curry"],
                    "top_3": [
                        _candidate_payload(
                            candidate_id="candidate-egg-curry",
                            label="egg curry",
                            similarity=0.93,
                            missing=["vegetable inside curry"],
                            nutrition_impact=0.22,
                        ),
                        _candidate_payload(
                            candidate_id="candidate-chicken-curry",
                            label="chicken curry",
                            similarity=0.92,
                            nutrition_impact=0.23,
                        ),
                        _candidate_payload(
                            candidate_id="candidate-mixed-curry",
                            label="mixed curry",
                            similarity=0.88,
                            nutrition_impact=0.24,
                        ),
                    ],
                },
            ],
        }

        result = _run_gate(payload)

        self.assertEqual(result["meal_state"], "PARTIAL_RESOLVED_WAITING")
        self.assertIn("food_groups", result)
        groups = {group["group_id"]: group for group in result["food_groups"]}
        self.assertEqual(groups["group-pita"]["group_action"], "AUTO_CONFIRM")
        self.assertEqual(groups["group-pita"]["group_state"], "READY_TO_WRITE")
        self.assertIn(
            groups["group-curry"]["group_action"],
            {"ASK_CHOICE", "ASK_QUANTITY", "INTERVIEW"},
        )
        self.assertEqual(groups["group-curry"]["group_state"], "PENDING_INTERVIEW")
