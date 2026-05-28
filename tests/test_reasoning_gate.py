from __future__ import annotations

import unittest
from typing import Any


INTERVIEW_STATES = {"PENDING_INTERVIEW", "PENDING_CHOICE", "INTERVIEWING", "PARTIAL_RESOLVED_WAITING"}


def _candidate_payload(
    *,
    candidate_id: str,
    similarity: float,
    missing: list[str] | None = None,
    nutrition_impact: float = 0.1,
) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "label": "plate of rice and curry",
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
                "label": "high nutrition impact requires interview",
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
                self.assertIn(
                    result["meal_state"],
                    INTERVIEW_STATES,
                    msg=f"{row['label']} should route to interview",
                )

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
