from __future__ import annotations

from typing import Any, Mapping


_REASONING_TOP_FIELDS = (
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
)


def reasoning_response_format() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "reasoning_contract_v1",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["action", "meal_state", "top_3", "decision_rationale"],
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Open-string routing action from the reasoning model",
                    },
                    "meal_state": {
                        "type": "string",
                        "description": "Next meal-level pipeline state",
                    },
                    "trace_id": {
                        "type": "string",
                    },
                    "decision_rationale": {
                        "type": "string",
                    },
                    "gate_reason": {
                        "type": "string",
                    },
                    "segment_count": {
                        "type": "integer",
                    },
                    "top_3": {
                        "type": "array",
                        "minItems": 3,
                        "maxItems": 3,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": list(_REASONING_TOP_FIELDS),
                            "properties": {
                                "candidate_id": {"type": "string"},
                                "label": {"type": "string"},
                                "identity_confidence": {"type": "number"},
                                "quantity_confidence": {"type": "number"},
                                "match_consistency_confidence": {"type": "number"},
                                "visual_evidence": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "missing_evidence": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "specificity": {"type": "string"},
                                "nutrition_relevance": {"type": "string"},
                                "source": {"type": "string"},
                                "decision_rationale": {"type": "string"},
                                "nutrition_impact": {
                                    "type": "number",
                                },
                            },
                        },
                        "additionalItems": False,
                    },
                },
            },
        },
    }


def _coerce_str(value: object, field: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        return ""
    stripped = value.strip()
    if not stripped:
        return ""
    return stripped


def _coerce_number(value: object, field: str) -> float:
    if value is None:
        return 0.0
    if isinstance(value, bool):
        raise TypeError(f"{field} must be numeric")
    if not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be numeric")
    return float(value)


def _coerce_list_of_text(value: object, field: str) -> list[str]:
    if not value:
        return []
    if not isinstance(value, list):
        raise TypeError(f"{field} must be a list")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise TypeError(f"{field} items must be text")
        text = item.strip()
        if text:
            normalized.append(text)
    return normalized


def _coerce_candidate_payload(candidate: Mapping[str, object], idx: int) -> dict[str, Any]:
    normalized: dict[str, Any] = {
        "candidate_id": _coerce_str(candidate.get("candidate_id"), "candidate_id") or f"candidate-{idx}",
        "label": _coerce_str(candidate.get("label"), "label") or "unlabeled food",
        "identity_confidence": _coerce_number(
            candidate.get("identity_confidence"),
            "identity_confidence",
        ),
        "quantity_confidence": _coerce_number(
            candidate.get("quantity_confidence"),
            "quantity_confidence",
        ),
        "match_consistency_confidence": _coerce_number(
            candidate.get("match_consistency_confidence"),
            "match_consistency_confidence",
        ),
        "visual_evidence": _coerce_list_of_text(candidate.get("visual_evidence"), "visual_evidence"),
        "missing_evidence": _coerce_list_of_text(candidate.get("missing_evidence"), "missing_evidence"),
        "specificity": _coerce_str(candidate.get("specificity"), "specificity") or "medium",
        "nutrition_relevance": _coerce_str(candidate.get("nutrition_relevance"), "nutrition_relevance") or "medium",
        "source": _coerce_str(candidate.get("source"), "source") or "vector_match",
        "decision_rationale": _coerce_str(candidate.get("decision_rationale"), "decision_rationale")
        or "No candidate rationale provided",
        "nutrition_impact": _coerce_number(candidate.get("nutrition_impact"), "nutrition_impact"),
    }

    if normalized["identity_confidence"] < 0.0:
        normalized["identity_confidence"] = 0.0
    if normalized["identity_confidence"] > 1.0:
        normalized["identity_confidence"] = 1.0
    if normalized["quantity_confidence"] < 0.0:
        normalized["quantity_confidence"] = 0.0
    if normalized["quantity_confidence"] > 1.0:
        normalized["quantity_confidence"] = 1.0
    if normalized["match_consistency_confidence"] < 0.0:
        normalized["match_consistency_confidence"] = 0.0
    if normalized["match_consistency_confidence"] > 1.0:
        normalized["match_consistency_confidence"] = 1.0

    if normalized["nutrition_impact"] < 0.0:
        normalized["nutrition_impact"] = 0.0
    if normalized["nutrition_impact"] > 1.0:
        normalized["nutrition_impact"] = 1.0

    return normalized


def _coerce_top_three(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        normalized = []
    else:
        normalized = value

    payloads: list[dict[str, Any]] = []
    for index in range(3):
        candidate = normalized[index] if index < len(normalized) else {}
        if not isinstance(candidate, Mapping):
            candidate = {}
        try:
            payloads.append(_coerce_candidate_payload(candidate, index))
        except TypeError:
            payloads.append(
                {
                    "candidate_id": f"candidate-{index}",
                    "label": "unlabeled food",
                    "identity_confidence": 0.0,
                    "quantity_confidence": 0.0,
                    "match_consistency_confidence": 0.0,
                    "visual_evidence": [],
                    "missing_evidence": [],
                    "specificity": "medium",
                    "nutrition_relevance": "medium",
                    "source": "vector_match",
                    "decision_rationale": "Invalid candidate payload",
                    "nutrition_impact": 0.0,
                }
            )

    return payloads


def coerce_reasoning_response(payload: Mapping[str, object] | object | None) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        payload = {}

    action_raw = _coerce_str(payload.get("action"), "action") if hasattr(payload, "get") else ""
    meal_state = _coerce_str(payload.get("meal_state"), "meal_state") if hasattr(payload, "get") else ""
    top_3 = _coerce_top_three(payload.get("top_3") if isinstance(payload, Mapping) else None)
    decision_rationale = _coerce_str(payload.get("decision_rationale"), "decision_rationale")
    gate_reason = _coerce_str(payload.get("gate_reason"), "gate_reason")
    trace_id = _coerce_str(payload.get("trace_id"), "trace_id")
    raw_segment_count = payload.get("segment_count") if isinstance(payload, Mapping) else None
    try:
        segment_count = int(raw_segment_count) if raw_segment_count is not None else len(top_3)
    except (TypeError, ValueError):
        segment_count = len(top_3)

    if segment_count < 0:
        segment_count = 0

    allowed_actions = {
        "AUTO_CONFIRM",
        "AUTO_CONFIRM_WITH_TRACE",
        "READY_TO_WRITE",
        "ASK_QUANTITY",
        "ASK_CHOICE",
        "FAILED_UNCLEAR",
        "INTERVIEW",
        "NEEDS_SCHEMA_REVIEW",
    }
    if not action_raw:
        action = "NEEDS_SCHEMA_REVIEW"
        meal_state = "NEEDS_SCHEMA_REVIEW"
        decision_rationale = "Missing action field"
    elif action_raw in allowed_actions:
        action = action_raw
    else:
        action = "NEEDS_SCHEMA_REVIEW"
        meal_state = "NEEDS_SCHEMA_REVIEW"
        decision_rationale = "Unknown action treated as schema review"
        if decision_rationale is not None:
            decision_rationale = f"{decision_rationale} (action={action_raw})"

    if not meal_state:
        meal_state = "NEEDS_SCHEMA_REVIEW"

    if action == "NEEDS_SCHEMA_REVIEW" and "schema review" not in decision_rationale.lower():
        decision_rationale = "Schema review required"

    return {
        "action": action,
        "meal_state": meal_state,
        "top_3": top_3,
        "trace_id": trace_id or None,
        "decision_rationale": decision_rationale or "No decision rationale provided",
        "gate_reason": gate_reason or "",
        "segment_count": segment_count,
    }


__all__ = ["reasoning_response_format", "coerce_reasoning_response"]
