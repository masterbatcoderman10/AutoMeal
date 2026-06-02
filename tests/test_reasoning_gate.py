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
    source: str = "vector_match",
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
        "source": source,
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
    if "top_3" in payload and "food_groups" not in payload:
        payload = {
            **payload,
            "food_group_count": 1,
            "food_groups": [
                {
                    "group_id": "group-1",
                    "group_label": "food group",
                    "group_action": payload.get("action", "AUTO_CONFIRM"),
                    "group_state": payload.get("meal_state", "READY_TO_WRITE"),
                    "primary_segment_id": "segment-1",
                    "segment_ids": ["segment-1"],
                    "selected_candidate_id": "",
                    "visual_evidence": [],
                    "missing_evidence": [],
                    "decision_rationale": payload.get("decision_rationale", ""),
                    "gate_reason": payload.get("gate_reason", ""),
                    "question_kind": "",
                    "question_focus": "",
                    "question_examples": [],
                    "top_3": payload.get("top_3", []),
                }
            ],
        }
        payload.pop("top_3", None)
    return fn(reasoning_payload=payload)


def _actions_for_group(result: dict[str, Any], group_id: str | None = None) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for group in result.get("food_groups", []):
        if not isinstance(group, dict):
            continue
        if group_id is not None and group.get("group_id") != group_id:
            continue
        for action in group.get("clarification_actions", []):
            if isinstance(action, dict):
                actions.append(action)
    return actions


def _choice_labels(action: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    for choice in action.get("choices", []):
        if isinstance(choice, dict):
            labels.append(str(choice.get("label") or ""))
        else:
            labels.append(str(choice))
    return [label for label in labels if label]


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
                        _candidate_payload(candidate_id="best", similarity=0.92, label="chicken curry"),
                        _candidate_payload(candidate_id="fallback_1", similarity=0.91, label="beef curry"),
                        _candidate_payload(candidate_id="fallback_2", similarity=0.9, label="mutton curry"),
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

    def test_gate_ignores_duplicate_identity_candidates_for_margin(self) -> None:
        payload = {
            "action": "AUTO_CONFIRM",
            "meal_state": "READY_TO_WRITE",
            "trace_id": "trace-duplicate-identities",
            "food_group_count": 1,
            "segment_count": 1,
            "decision_rationale": "same learned item has multiple visual rows",
            "gate_reason": "",
            "food_groups": [
                {
                    "group_id": "group-egg",
                    "group_label": "Boiled egg and bottle gourd curry",
                    "group_action": "AUTO_CONFIRM",
                    "group_state": "READY_TO_WRITE",
                    "primary_segment_id": "segment-egg",
                    "segment_ids": ["segment-egg"],
                    "selected_candidate_id": "visual-egg-1",
                    "visual_evidence": ["eggs and bottle gourd"],
                    "missing_evidence": [],
                    "decision_rationale": "top two rows are duplicate visuals for the same food",
                    "gate_reason": "",
                    "question_kind": "none",
                    "question_focus": "none",
                    "question_examples": [],
                    "top_3": [
                        _candidate_payload(
                            candidate_id="visual-egg-1",
                            similarity=1.0,
                            label="Boiled Egg Curry with Bottle Gourd (Lauki)",
                        ),
                        _candidate_payload(
                            candidate_id="visual-egg-2",
                            similarity=0.99,
                            label="Boiled Egg Curry with Bottle Gourd (Lauki)",
                        ),
                        _candidate_payload(
                            candidate_id="visual-chicken",
                            similarity=0.3,
                            label="chicken drumstick in a curry called phaal",
                        ),
                    ],
                }
            ],
        }

        result = _run_gate(payload)

        self.assertEqual(result["meal_state"], "READY_TO_WRITE")
        self.assertEqual(result["food_groups"][0]["group_state"], "READY_TO_WRITE")
        self.assertNotIn("candidate margin", result["food_groups"][0]["gate_reason"])

    def test_clarification_choices_are_deduped(self) -> None:
        payload = {
            "action": "AUTO_CONFIRM",
            "meal_state": "READY_TO_WRITE",
            "trace_id": "trace-deduped-choices",
            "food_group_count": 1,
            "segment_count": 1,
            "decision_rationale": "requires choice",
            "gate_reason": "",
            "food_groups": [
                {
                    "group_id": "group-bread",
                    "group_label": "Flatbread",
                    "group_action": "ASK_CHOICE",
                    "group_state": "PENDING_INTERVIEW",
                    "primary_segment_id": "segment-bread",
                    "segment_ids": ["segment-bread"],
                    "selected_candidate_id": "visual-khubz-1",
                    "visual_evidence": ["flatbread"],
                    "missing_evidence": [],
                    "decision_rationale": "needs choice",
                    "gate_reason": "requires confirmation",
                    "question_kind": "CHOICE",
                    "question_focus": "best match",
                    "question_examples": [],
                    "top_3": [
                        _candidate_payload(
                            candidate_id="visual-khubz-1",
                            similarity=0.98,
                            label="White Bread (Khubz)",
                        ),
                        _candidate_payload(
                            candidate_id="visual-khubz-2",
                            similarity=0.97,
                            label="White Bread (Khubz)",
                        ),
                        _candidate_payload(
                            candidate_id="visual-egg",
                            similarity=0.2,
                            label="Boiled Egg Curry with Bottle Gourd (Lauki)",
                        ),
                    ],
                }
            ],
        }

        result = _run_gate(payload)
        action = _actions_for_group(result, "group-bread")[0]

        self.assertEqual(
            _choice_labels(action),
            ["White Bread (Khubz)", "Boiled Egg Curry with Bottle Gourd (Lauki)", "Other"],
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
        self.assertNotIn("clarification_schema", result)
        clarification = _actions_for_group(result)
        self.assertIsInstance(clarification, list)
        self.assertGreaterEqual(len(clarification), 2)

        question_ids = [question["question_id"] for question in clarification]
        self.assertEqual(len(set(question_ids)), len(question_ids))

        first_pass = _run_gate(payload)
        first_pass_ids = [question["question_id"] for question in _actions_for_group(first_pass)]
        self.assertEqual(question_ids, first_pass_ids)

    def test_gate_preserves_model_clarification_choices_over_question_examples(self) -> None:
        payload = {
            "action": "AUTO_CONFIRM_OR_INTERVIEW",
            "meal_state": "PENDING_INTERVIEW",
            "trace_id": "trace-model-choices",
            "food_group_count": 1,
            "segment_count": 1,
            "decision_rationale": "vegetable type needs confirmation",
            "gate_reason": "vegetable changes nutrition",
            "food_groups": [
                {
                    "group_id": "egg_gourd_curry_group",
                    "group_label": "Egg and Vegetable Curry",
                    "group_action": "INTERVIEW",
                    "group_state": "PENDING_INTERVIEW",
                    "primary_segment_id": "segment-curry",
                    "segment_ids": ["segment-curry"],
                    "selected_candidate_id": "candidate-curry",
                    "visual_evidence": ["eggs and sliced green vegetable"],
                    "missing_evidence": ["exact vegetable"],
                    "decision_rationale": "needs specific vegetable",
                    "gate_reason": "specific vegetable matters",
                    "question_kind": "single_choice",
                    "question_focus": "vegetable_type",
                    "question_examples": [
                        "What vegetable is cooked with the eggs? (e.g., pointed gourd, bottle gourd, cucumber, zucchini, or potato?)"
                    ],
                    "top_3": [
                        _candidate_payload(candidate_id="candidate-curry", similarity=0.9, label="Egg and Pointed Gourd Curry"),
                        _candidate_payload(candidate_id="candidate-potato", similarity=0.7, label="Egg Curry with Potatoes"),
                        _candidate_payload(candidate_id="candidate-generic", similarity=0.5, label="Egg Curry with Mixed Vegetables"),
                    ],
                },
            ],
            "clarification_schema": [
                {
                    "question_id": "egg_curry_vegetable_clarification",
                    "group_id": "egg_gourd_curry_group",
                    "group_label": "Egg and Vegetable Curry",
                    "question_kind": "single_choice",
                    "question_focus": "vegetable_type",
                    "answer_type": "single_choice",
                    "required": True,
                    "segment_ids": ["segment-curry"],
                    "primary_segment_id": "segment-curry",
                    "choices": [
                        "Pointed gourd (Parwal / Patol)",
                        "Bottle gourd (Lauki / Kaddu)",
                        "Potato (Aloo)",
                    ],
                    "validation_hints": {"required": True},
                }
            ],
        }

        result = _run_gate(payload)
        action = _actions_for_group(result, "egg_gourd_curry_group")[0]

        self.assertEqual(
            _choice_labels(action),
            [
                "Egg and Pointed Gourd Curry",
                "Egg Curry with Potatoes",
                "Egg Curry with Mixed Vegetables",
                "Other",
            ],
        )

    def test_gate_does_not_auto_confirm_visual_only_candidates_without_learned_match(self) -> None:
        payload = {
            "action": "AUTO_CONFIRM",
            "meal_state": "READY_TO_WRITE",
            "trace_id": "trace-visual-only",
            "food_group_count": 1,
            "segment_count": 1,
            "decision_rationale": "visual reasoning thinks this is pita",
            "gate_reason": "",
            "food_groups": [
                {
                    "group_id": "group-pita",
                    "group_label": "Pita Bread",
                    "group_action": "AUTO_CONFIRM",
                    "group_state": "READY_TO_WRITE",
                    "primary_segment_id": "segment-pita",
                    "segment_ids": ["segment-pita"],
                    "selected_candidate_id": "candidate-pita",
                    "visual_evidence": ["flatbread"],
                    "missing_evidence": [],
                    "decision_rationale": "looks like pita",
                    "gate_reason": "visual only",
                    "question_kind": "none",
                    "question_focus": "none",
                    "question_examples": [],
                    "top_3": [
                        _candidate_payload(
                            candidate_id="candidate-pita",
                            similarity=0.98,
                            label="Whole Wheat Pita Bread",
                            nutrition_impact=1.0,
                            source="visual_reasoning",
                        ),
                        _candidate_payload(
                            candidate_id="candidate-khubz",
                            similarity=0.7,
                            label="Khubz Bread",
                            nutrition_impact=0.8,
                            source="visual_reasoning",
                        ),
                        _candidate_payload(
                            candidate_id="candidate-flatbread",
                            similarity=0.5,
                            label="Flatbread",
                            nutrition_impact=0.5,
                            source="visual_reasoning",
                        ),
                    ],
                },
            ],
        }

        result = _run_gate(payload)

        self.assertIn(result["meal_state"], INTERVIEW_STATES)
        self.assertEqual(result["food_groups"][0]["group_action"], "AFFIRMATION_REQUIRED")
        self.assertIn("visual-only", result["food_groups"][0]["gate_reason"])

    def test_gate_adds_derived_question_when_source_schema_omits_gated_group(self) -> None:
        payload = {
            "action": "INTERVIEW",
            "meal_state": "PARTIAL_RESOLVED_WAITING",
            "trace_id": "trace-missing-question",
            "food_group_count": 2,
            "segment_count": 2,
            "decision_rationale": "model asked about bread but omitted chicken",
            "gate_reason": "",
            "food_groups": [
                {
                    "group_id": "group_bread",
                    "group_label": "Flatbread",
                    "group_action": "INTERVIEW",
                    "group_state": "PENDING_INTERVIEW",
                    "primary_segment_id": "segment-bread",
                    "segment_ids": ["segment-bread"],
                    "selected_candidate_id": "candidate-bread",
                    "visual_evidence": ["flatbread"],
                    "missing_evidence": ["bread type"],
                    "decision_rationale": "needs bread type",
                    "gate_reason": "bread type needed",
                    "question_kind": "identity",
                    "question_focus": "bread type",
                    "question_examples": ["khubz"],
                    "top_3": [
                        _candidate_payload(candidate_id="candidate-bread", similarity=0.8, label="Khubz"),
                        _candidate_payload(candidate_id="candidate-pita", similarity=0.7, label="Pita"),
                        _candidate_payload(candidate_id="candidate-flatbread", similarity=0.5, label="Flatbread"),
                    ],
                },
                {
                    "group_id": "group_chicken",
                    "group_label": "Chicken Leg Curry",
                    "group_action": "AUTO_CONFIRM",
                    "group_state": "READY_TO_WRITE",
                    "primary_segment_id": "segment-chicken",
                    "segment_ids": ["segment-chicken"],
                    "selected_candidate_id": "candidate-chicken",
                    "visual_evidence": ["chicken drumstick"],
                    "missing_evidence": [],
                    "decision_rationale": "looks clear",
                    "gate_reason": "",
                    "question_kind": "none",
                    "question_focus": "none",
                    "question_examples": [],
                    "top_3": [
                        _candidate_payload(
                            candidate_id="candidate-chicken",
                            similarity=0.96,
                            label="Chicken Drumstick Curry",
                            source="visual_reasoning",
                        ),
                        _candidate_payload(
                            candidate_id="candidate-bone-in",
                            similarity=0.7,
                            label="Bone-in Chicken Curry",
                            source="visual_reasoning",
                        ),
                        _candidate_payload(
                            candidate_id="candidate-green",
                            similarity=0.6,
                            label="Chicken Green Masala",
                            source="visual_reasoning",
                        ),
                    ],
                },
            ],
            "clarification_schema": [
                {
                    "question_id": "q_bread",
                    "group_id": "group_bread",
                    "group_label": "Flatbread",
                    "question_kind": "identity",
                    "question_focus": "bread type",
                    "answer_type": "single_choice",
                    "required": True,
                    "segment_ids": ["segment-bread"],
                    "primary_segment_id": "segment-bread",
                    "choices": ["Khubz", "Pita"],
                    "validation_hints": {"required": True},
                }
            ],
        }

        result = _run_gate(payload)
        self.assertNotIn("clarification_schema", result)
        questions = _actions_for_group(result)
        question_group_ids = {question["group_id"] for question in questions}

        self.assertIn("group_bread", question_group_ids)
        self.assertIn("group_chicken", question_group_ids)
        chicken_question = next(question for question in questions if question["group_id"] == "group_chicken")
        self.assertEqual(chicken_question["type"], "AFFIRMATION")
        self.assertEqual(_choice_labels(chicken_question), ["Yes", "No"])

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
        questions = _actions_for_group(result)
        kinds = {question["kind"] for question in questions}
        self.assertIn("SOURCE_ORIGIN", kinds)
        self.assertNotIn(
            "SOURCE_ORIGIN",
            {
                question["kind"]
                for question in questions
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
                    label="chicken curry",
                    nutrition_impact=0.55,
                ),
                _candidate_payload(candidate_id="fallback_1", similarity=0.95, label="beef curry"),
                _candidate_payload(candidate_id="fallback_2", similarity=0.8, label="mutton curry"),
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
            {"ASK_CHOICE", "ASK_QUANTITY", "INTERVIEW", "IDENTITY_CLARIFICATION_REQUIRED"},
        )
        self.assertEqual(groups["group-curry"]["group_state"], "PENDING_INTERVIEW")

    def test_identity_clarification_actions_use_ranked_top_three_and_contract_owned_other(self) -> None:
        payload = {
            "action": "AUTO_CONFIRM",
            "meal_state": "READY_TO_WRITE",
            "trace_id": "trace-identity-actions",
            "food_group_count": 1,
            "segment_count": 1,
            "decision_rationale": "bread candidates are visually close",
            "gate_reason": "",
            "food_groups": [
                {
                    "group_id": "group-bread",
                    "group_label": "Flatbread",
                    "group_action": "AUTO_CONFIRM",
                    "group_state": "READY_TO_WRITE",
                    "primary_segment_id": "segment-bread",
                    "segment_ids": ["segment-bread"],
                    "selected_candidate_id": "candidate-khubz",
                    "visual_evidence": ["round flatbread"],
                    "missing_evidence": [],
                    "decision_rationale": "needs ranked identity confirmation",
                    "gate_reason": "",
                    "question_kind": "identity",
                    "question_focus": "bread type",
                    "question_examples": [],
                    "top_3": [
                        _candidate_payload(candidate_id="candidate-khubz", similarity=0.94, label="Brown khubz"),
                        _candidate_payload(candidate_id="candidate-pita", similarity=0.93, label="Whole wheat pita bread"),
                        _candidate_payload(candidate_id="candidate-roti", similarity=0.92, label="Tandoori roti"),
                    ],
                }
            ],
        }

        result = _run_gate(payload)

        group = result["food_groups"][0]
        self.assertEqual(group["group_action"], "IDENTITY_CLARIFICATION_REQUIRED")
        self.assertTrue(group["clarification_needed"])
        self.assertEqual([action["type"] for action in group["clarification_actions"]], ["CHOICE"])
        self.assertEqual(
            [choice["value"] for choice in group["clarification_actions"][0]["choices"]],
            ["candidate-khubz", "candidate-pita", "candidate-roti", "OTHER"],
        )
        self.assertEqual(
            [choice["quick_prompt"] for choice in group["clarification_actions"][0]["choices"][:3]],
            ["Brown khubz", "Whole wheat pita bread", "Tandoori roti"],
        )

    def test_visual_only_high_confidence_requires_affirmation_but_learned_match_auto_confirms(self) -> None:
        payload = {
            "action": "AUTO_CONFIRM",
            "meal_state": "READY_TO_WRITE",
            "trace_id": "trace-affirmation-routing",
            "food_group_count": 2,
            "segment_count": 2,
            "decision_rationale": "split learned matches from visual-only confidence",
            "gate_reason": "",
            "food_groups": [
                {
                    "group_id": "group-bread",
                    "group_label": "Flatbread",
                    "group_action": "AUTO_CONFIRM",
                    "group_state": "READY_TO_WRITE",
                    "primary_segment_id": "segment-bread",
                    "segment_ids": ["segment-bread"],
                    "selected_candidate_id": "candidate-pita",
                    "visual_evidence": ["flatbread"],
                    "missing_evidence": [],
                    "decision_rationale": "visual-only top candidate looks like pita",
                    "gate_reason": "",
                    "question_kind": "none",
                    "question_focus": "none",
                    "question_examples": [],
                    "top_3": [
                        _candidate_payload(
                            candidate_id="candidate-pita",
                            similarity=0.99,
                            label="Whole wheat pita bread",
                            source="visual_reasoning",
                        ),
                        _candidate_payload(
                            candidate_id="candidate-khubz",
                            similarity=0.81,
                            label="Brown khubz",
                            source="visual_reasoning",
                        ),
                        _candidate_payload(
                            candidate_id="candidate-flatbread",
                            similarity=0.7,
                            label="Flatbread",
                            source="visual_reasoning",
                        ),
                    ],
                },
                {
                    "group_id": "group-curry",
                    "group_label": "Egg Curry",
                    "group_action": "AUTO_CONFIRM",
                    "group_state": "READY_TO_WRITE",
                    "primary_segment_id": "segment-curry",
                    "segment_ids": ["segment-curry"],
                    "selected_candidate_id": "candidate-egg-curry",
                    "visual_evidence": ["egg curry"],
                    "missing_evidence": [],
                    "decision_rationale": "learned match is strong",
                    "gate_reason": "",
                    "question_kind": "none",
                    "question_focus": "none",
                    "question_examples": [],
                    "top_3": [
                        {
                            **_candidate_payload(
                                candidate_id="candidate-egg-curry",
                                similarity=0.98,
                                label="Egg Curry with Bottle Gourd",
                                source="vector_match",
                            ),
                            "food_item_id": "food-item-egg-curry",
                        },
                        _candidate_payload(
                            candidate_id="candidate-chicken-curry",
                            similarity=0.7,
                            label="Chicken Curry",
                            source="vector_match",
                        ),
                        _candidate_payload(
                            candidate_id="candidate-mixed-curry",
                            similarity=0.6,
                            label="Mixed Curry",
                            source="vector_match",
                        ),
                    ],
                },
            ],
        }

        result = _run_gate(payload)
        groups = {group["group_id"]: group for group in result["food_groups"]}

        self.assertEqual(groups["group-bread"]["group_action"], "AFFIRMATION_REQUIRED")
        self.assertEqual(
            [action["type"] for action in groups["group-bread"]["clarification_actions"]],
            ["AFFIRMATION"],
        )
        self.assertEqual(groups["group-curry"]["group_action"], "AUTO_CONFIRM_LEARNED")
        self.assertFalse(groups["group-curry"]["clarification_needed"])
        self.assertEqual(groups["group-curry"]["clarification_actions"], [])

    def test_empty_candidate_fallback_does_not_render_unlabeled_food_choices(self) -> None:
        payload = {
            "action": "FAILED_UNCLEAR",
            "meal_state": "FAILED_UNCLEAR",
            "trace_id": "",
            "food_group_count": 1,
            "segment_count": 1,
            "decision_rationale": "reasoning output was truncated",
            "gate_reason": "fallback from segment detector label",
            "food_groups": [
                {
                    "group_id": "group-bread",
                    "group_label": "bread",
                    "group_action": "AUTO_CONFIRM",
                    "group_state": "READY_TO_WRITE",
                    "primary_segment_id": "segment-bread",
                    "segment_ids": ["segment-bread"],
                    "selected_candidate_id": "",
                    "visual_evidence": [],
                    "missing_evidence": [],
                    "decision_rationale": "Synthesized from segment match candidates",
                    "gate_reason": "",
                    "question_kind": "",
                    "question_focus": "",
                    "question_examples": [],
                    "top_3": [],
                }
            ],
        }

        result = _run_gate(payload)

        group = result["food_groups"][0]
        self.assertEqual(group["group_action"], "AFFIRMATION_REQUIRED")
        self.assertEqual(group["top_3"], [])
        self.assertEqual(
            [action["type"] for action in group["clarification_actions"]],
            ["AFFIRMATION"],
        )
        self.assertEqual(
            group["clarification_actions"][0]["user_prompt"],
            "I think this is bread. Is that right?",
        )
        self.assertNotIn(
            "unlabeled food",
            str(group["clarification_actions"]).lower(),
        )

    def test_no_vector_identity_question_is_preserved_with_additive_actions(self) -> None:
        payload = {
            "action": "IDENTITY_CLARIFICATION_REQUIRED",
            "meal_state": "PENDING_INTERVIEW",
            "trace_id": "",
            "food_group_count": 1,
            "segment_count": 1,
            "decision_rationale": "flatbread subtype affects carb estimate",
            "gate_reason": "bread subtype is ambiguous",
            "food_groups": [
                {
                    "group_id": "group-bread",
                    "group_label": "Flatbread",
                    "group_actions": [
                        "IDENTITY_CLARIFICATION_REQUIRED",
                        "ASK_QUANTITY",
                        "ASK_SOURCE_ORIGIN",
                    ],
                    "group_state": "PENDING_INTERVIEW",
                    "primary_segment_id": "segment-bread",
                    "segment_ids": ["segment-bread"],
                    "selected_candidate_id": "",
                    "visual_evidence": ["round brown flatbread"],
                    "missing_evidence": ["specific bread type", "quantity", "source origin"],
                    "decision_rationale": "could be khubz, pita, or roti",
                    "gate_reason": "bread subtype is ambiguous",
                    "clarification_needed": True,
                    "clarification_actions": [
                        {
                            "type": "CHOICE",
                            "kind": "IDENTITY",
                            "user_prompt": "Which bread is this?",
                            "answer_type": "single_choice",
                            "choices": [
                                {"label": "Khubz", "quick_prompt": "Khubz"},
                                {"label": "Pita", "quick_prompt": "Pita"},
                                {"label": "Roti", "quick_prompt": "Roti"},
                            ],
                            "allow_other": True,
                            "other_label": "Other",
                            "required": True,
                            "reason": "bread subtype is ambiguous",
                            "validation_hints": {"required": True},
                            "question_focus": "bread type",
                        },
                        {
                            "type": "SOURCE_ORIGIN",
                            "kind": "SOURCE_ORIGIN",
                            "user_prompt": "Was this homemade, packaged, or restaurant?",
                            "answer_type": "single_choice",
                            "choices": [
                                {"label": "homemade", "quick_prompt": "homemade"},
                                {"label": "restaurant", "quick_prompt": "restaurant"},
                            ],
                            "allow_other": False,
                            "other_label": "Other",
                            "required": True,
                            "reason": "source changes nutrition lookup",
                            "validation_hints": {"required": True},
                            "question_focus": "source origin",
                        },
                        {
                            "type": "QUANTITY",
                            "kind": "QUANTITY",
                            "user_prompt": "How many pieces of flatbread are there?",
                            "answer_type": "free_text",
                            "choices": [],
                            "allow_other": False,
                            "other_label": "",
                            "required": True,
                            "reason": "quantity changes carb estimate",
                            "validation_hints": {"required": True},
                            "question_focus": "flatbread quantity",
                        },
                    ],
                    "question_kind": "IDENTITY",
                    "question_focus": "bread type",
                    "question_examples": ["Khubz", "Pita", "Roti"],
                    "top_3": [],
                }
            ],
        }

        result = _run_gate(payload)

        group = result["food_groups"][0]
        self.assertEqual(group["group_action"], "IDENTITY_CLARIFICATION_REQUIRED")
        self.assertEqual(
            group["group_actions"],
            ["IDENTITY_CLARIFICATION_REQUIRED", "ASK_QUANTITY", "ASK_SOURCE_ORIGIN"],
        )
        self.assertEqual(
            [action["type"] for action in group["clarification_actions"]],
            ["CHOICE", "SOURCE_ORIGIN", "QUANTITY"],
        )
        self.assertEqual(
            [choice["label"] for choice in group["clarification_actions"][0]["choices"]],
            ["Khubz", "Pita", "Roti"],
        )

    def test_source_origin_is_reasoning_owned_and_ordered_after_affirmation(self) -> None:
        payload = {
            "action": "AUTO_CONFIRM",
            "meal_state": "READY_TO_WRITE",
            "trace_id": "trace-source-origin-actions",
            "food_group_count": 1,
            "segment_count": 1,
            "decision_rationale": "packaged-looking bread still needs source clarification",
            "gate_reason": "",
            "food_groups": [
                {
                    "group_id": "group-bread",
                    "group_label": "Packaged Flatbread",
                    "group_action": "AUTO_CONFIRM",
                    "group_state": "READY_TO_WRITE",
                    "primary_segment_id": "segment-bread",
                    "segment_ids": ["segment-bread"],
                    "selected_candidate_id": "candidate-wrap",
                    "visual_evidence": ["wrapped flatbread in branded sleeve"],
                    "missing_evidence": [],
                    "decision_rationale": "looks like a learned bread but source changes nutrition grounding",
                    "gate_reason": "",
                    "question_kind": "none",
                    "question_focus": "none",
                    "question_examples": [],
                    "top_3": [
                        _candidate_payload(
                            candidate_id="candidate-wrap",
                            similarity=0.99,
                            label="Packaged wrap flatbread",
                            source="visual_reasoning",
                        ),
                        _candidate_payload(
                            candidate_id="candidate-pita",
                            similarity=0.7,
                            label="Whole wheat pita bread",
                            source="visual_reasoning",
                        ),
                        _candidate_payload(
                            candidate_id="candidate-khubz",
                            similarity=0.65,
                            label="Brown khubz",
                            source="visual_reasoning",
                        ),
                    ],
                }
            ],
        }

        result = _run_gate(payload)

        group = result["food_groups"][0]
        self.assertEqual(group["group_action"], "AFFIRMATION_REQUIRED")
        self.assertEqual(
            [action["type"] for action in group["clarification_actions"]],
            ["AFFIRMATION", "SOURCE_ORIGIN"],
        )
        source_origin = group["clarification_actions"][1]
        self.assertEqual(
            [choice["value"] for choice in source_origin["choices"]],
            [
                "HOME_COOKED",
                "STORE_BOUGHT_PREPARED",
                "PACKAGED_BRANDED",
                "RESTAURANT",
                "UNKNOWN",
            ],
        )
        self.assertEqual(
            [choice["label"] for choice in source_origin["choices"]],
            ["homemade", "store bought", "packaged", "restaurant", "not sure"],
        )
