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
_GROUP_REQUIRED_FIELDS = (
    "group_id",
    "group_label",
    "group_action",
    "group_state",
    "primary_segment_id",
    "segment_ids",
    "selected_candidate_id",
    "visual_evidence",
    "missing_evidence",
    "decision_rationale",
    "gate_reason",
    "top_3",
)
_INTERVIEW_STATES = {
    "PENDING_INTERVIEW",
    "PENDING_CHOICE",
    "INTERVIEWING",
    "PARTIAL_RESOLVED_WAITING",
}
_MEAL_STATES = {
    "READY_TO_WRITE",
    "PENDING_CHOICE",
    "PENDING_INTERVIEW",
    "PARTIAL_RESOLVED_WAITING",
    "FAILED_UNCLEAR",
    "NEEDS_SCHEMA_REVIEW",
}
_GROUP_ACTIONS = {
    "AUTO_CONFIRM",
    "AUTO_CONFIRM_WITH_TRACE",
    "READY_TO_WRITE",
    "ASK_QUANTITY",
    "ASK_CHOICE",
    "FAILED_UNCLEAR",
    "INTERVIEW",
    "NEEDS_SCHEMA_REVIEW",
}


def reasoning_response_format() -> dict[str, Any]:
    candidate_properties = {
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
        "nutrition_impact": {"type": "number"},
    }
    group_properties = {
        "group_id": {"type": "string"},
        "group_label": {"type": "string"},
        "group_action": {"type": "string"},
        "group_state": {
            "type": "string",
            "enum": sorted(_MEAL_STATES),
        },
        "primary_segment_id": {"type": "string"},
        "segment_ids": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
        },
        "selected_candidate_id": {"type": "string"},
        "visual_evidence": {
            "type": "array",
            "items": {"type": "string"},
        },
        "missing_evidence": {
            "type": "array",
            "items": {"type": "string"},
        },
        "decision_rationale": {"type": "string"},
        "gate_reason": {"type": "string"},
        "top_3": {
            "type": "array",
            "minItems": 3,
            "maxItems": 3,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [*list(_REASONING_TOP_FIELDS), "nutrition_impact"],
                "properties": candidate_properties,
            },
            "additionalItems": False,
        },
    }
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "reasoning_contract_v1",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "action",
                    "meal_state",
                    "trace_id",
                    "decision_rationale",
                    "gate_reason",
                    "segment_count",
                    "food_group_count",
                    "food_groups",
                ],
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Open-string routing action from the reasoning model",
                    },
                    "meal_state": {
                        "type": "string",
                        "enum": sorted(_MEAL_STATES),
                        "description": "Next meal-level pipeline state",
                    },
                    "trace_id": {"type": "string"},
                    "decision_rationale": {"type": "string"},
                    "gate_reason": {"type": "string"},
                    "segment_count": {"type": "integer"},
                    "food_group_count": {"type": "integer"},
                    "food_groups": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": list(_GROUP_REQUIRED_FIELDS),
                            "properties": group_properties,
                        },
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

    for passthrough_field in (
        "food_item_id",
        "source_type",
        "brand_name",
        "restaurant_name",
        "portion_bucket",
    ):
        value = _coerce_str(candidate.get(passthrough_field), passthrough_field)
        if value:
            normalized[passthrough_field] = value

    quantity_payload = candidate.get("quantity_payload")
    if isinstance(quantity_payload, Mapping):
        normalized["quantity_payload"] = {
            key: value
            for key, value in quantity_payload.items()
            if isinstance(key, str) and isinstance(value, (str, int, float)) and not isinstance(value, bool)
        }

    for numeric_field in (
        "identity_confidence",
        "quantity_confidence",
        "match_consistency_confidence",
        "nutrition_impact",
    ):
        normalized[numeric_field] = max(0.0, min(float(normalized[numeric_field]), 1.0))

    return normalized


def _invalid_candidate_payload(idx: int) -> dict[str, Any]:
    return {
        "candidate_id": f"candidate-{idx}",
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


def _coerce_top_three(value: object) -> list[dict[str, Any]]:
    normalized = value if isinstance(value, list) else []
    payloads: list[dict[str, Any]] = []
    for index in range(3):
        candidate = normalized[index] if index < len(normalized) else {}
        if not isinstance(candidate, Mapping):
            candidate = {}
        try:
            payloads.append(_coerce_candidate_payload(candidate, index))
        except TypeError:
            payloads.append(_invalid_candidate_payload(index))
    return payloads


def _coerce_segment_ids(value: object, *, primary_segment_id: str, fallback: str) -> list[str]:
    ids = _coerce_list_of_text(value, "segment_ids") if isinstance(value, list) else []
    if primary_segment_id and primary_segment_id not in ids:
        ids.insert(0, primary_segment_id)
    unique_ids: list[str] = []
    seen: set[str] = set()
    for segment_id in ids:
        if segment_id in seen:
            continue
        seen.add(segment_id)
        unique_ids.append(segment_id)
    if unique_ids:
        return unique_ids
    return [primary_segment_id or fallback]


def _normalize_group_state(action: str, state: str) -> str:
    if state in _MEAL_STATES:
        return state
    if action in {"ASK_QUANTITY", "ASK_CHOICE", "INTERVIEW"}:
        return "PENDING_INTERVIEW"
    if action in {"AUTO_CONFIRM", "AUTO_CONFIRM_WITH_TRACE", "READY_TO_WRITE"}:
        return "READY_TO_WRITE"
    if action == "FAILED_UNCLEAR":
        return "FAILED_UNCLEAR"
    return "NEEDS_SCHEMA_REVIEW"


def _coerce_group_payload(group: Mapping[str, object], idx: int) -> dict[str, Any]:
    action_raw = _coerce_str(group.get("group_action") or group.get("action"), "group_action")
    if action_raw in _GROUP_ACTIONS:
        action = action_raw
    elif not action_raw:
        action = "AUTO_CONFIRM"
    else:
        action = "NEEDS_SCHEMA_REVIEW"
    group_id = _coerce_str(group.get("group_id"), "group_id") or f"group-{idx + 1}"
    group_label = _coerce_str(group.get("group_label") or group.get("label"), "group_label")
    top_3 = _coerce_top_three(group.get("top_3"))
    top_candidate = top_3[0] if top_3 else _invalid_candidate_payload(0)
    primary_segment_id = _coerce_str(group.get("primary_segment_id"), "primary_segment_id")
    if not primary_segment_id:
        primary_segment_id = _coerce_str(group.get("segment_id"), "segment_id") or f"segment-{idx + 1}"
    segment_ids = _coerce_segment_ids(
        group.get("segment_ids"),
        primary_segment_id=primary_segment_id,
        fallback=f"segment-{idx + 1}",
    )
    selected_candidate_id = (
        _coerce_str(group.get("selected_candidate_id"), "selected_candidate_id")
        or str(top_candidate.get("candidate_id") or f"candidate-{idx}")
    )
    decision_rationale = (
        _coerce_str(group.get("decision_rationale"), "decision_rationale")
        or str(top_candidate.get("decision_rationale") or "No candidate rationale provided")
    )
    visual_evidence = _coerce_list_of_text(group.get("visual_evidence"), "visual_evidence")
    if not visual_evidence:
        visual_evidence = list(top_candidate.get("visual_evidence", []))
    missing_evidence = _coerce_list_of_text(group.get("missing_evidence"), "missing_evidence")
    if not missing_evidence:
        missing_evidence = list(top_candidate.get("missing_evidence", []))
    group_state = _normalize_group_state(
        action,
        _coerce_str(group.get("group_state") or group.get("state"), "group_state"),
    )
    gate_reason = _coerce_str(group.get("gate_reason"), "gate_reason")

    return {
        "group_id": group_id,
        "group_label": group_label or str(top_candidate.get("label") or f"group {idx + 1}"),
        "group_action": action,
        "group_state": group_state,
        "primary_segment_id": primary_segment_id,
        "segment_ids": segment_ids,
        "selected_candidate_id": selected_candidate_id,
        "visual_evidence": visual_evidence,
        "missing_evidence": missing_evidence,
        "decision_rationale": decision_rationale,
        "gate_reason": gate_reason,
        "top_3": top_3,
    }


def _legacy_group_from_root(payload: Mapping[str, object]) -> list[dict[str, Any]]:
    if not isinstance(payload.get("top_3"), list):
        return []

    action_raw = _coerce_str(payload.get("action"), "action")
    meal_state = _coerce_str(payload.get("meal_state"), "meal_state")
    top_3 = _coerce_top_three(payload.get("top_3"))
    primary_segment_id = _coerce_str(payload.get("primary_segment_id"), "primary_segment_id") or "segment-1"
    raw_segment_count = payload.get("segment_count")
    try:
        segment_count = int(raw_segment_count) if raw_segment_count is not None else 1
    except (TypeError, ValueError):
        segment_count = 1
    if segment_count < 1:
        segment_count = 1
    segment_ids = payload.get("segment_ids") if isinstance(payload.get("segment_ids"), list) else [
        f"segment-{index}" for index in range(1, segment_count + 1)
    ]
    group = {
        "group_id": _coerce_str(payload.get("group_id"), "group_id") or "group-1",
        "group_label": _coerce_str(payload.get("group_label"), "group_label") or str(top_3[0].get("label") or "unlabeled food"),
        "group_action": action_raw or "NEEDS_SCHEMA_REVIEW",
        "group_state": meal_state or "NEEDS_SCHEMA_REVIEW",
        "primary_segment_id": primary_segment_id,
        "segment_ids": segment_ids,
        "selected_candidate_id": str(top_3[0].get("candidate_id") or "candidate-0"),
        "visual_evidence": list(top_3[0].get("visual_evidence", [])),
        "missing_evidence": list(top_3[0].get("missing_evidence", [])),
        "decision_rationale": _coerce_str(payload.get("decision_rationale"), "decision_rationale")
        or str(top_3[0].get("decision_rationale") or "No candidate rationale provided"),
        "gate_reason": _coerce_str(payload.get("gate_reason"), "gate_reason"),
        "top_3": top_3,
    }
    return [_coerce_group_payload(group, 0)]


def coerce_reasoning_response(payload: Mapping[str, object] | object | None) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        payload = {}

    action_raw = _coerce_str(payload.get("action"), "action")
    decision_rationale = _coerce_str(payload.get("decision_rationale"), "decision_rationale")
    gate_reason = _coerce_str(payload.get("gate_reason"), "gate_reason")
    trace_id = _coerce_str(payload.get("trace_id"), "trace_id")

    raw_groups = payload.get("food_groups") if isinstance(payload.get("food_groups"), list) else None
    if raw_groups:
        food_groups = [
            _coerce_group_payload(group, index)
            for index, group in enumerate(raw_groups)
            if isinstance(group, Mapping)
        ]
    else:
        food_groups = _legacy_group_from_root(payload)

    raw_segment_count = payload.get("segment_count")
    if raw_segment_count is not None:
        try:
            segment_count = int(raw_segment_count)
        except (TypeError, ValueError):
            segment_count = 0
    else:
        unique_segments = {
            segment_id
            for group in food_groups
            for segment_id in group.get("segment_ids", [])
        }
        segment_count = len(unique_segments)

    if segment_count < 0:
        segment_count = 0

    if not food_groups:
        return {
            "action": "NEEDS_SCHEMA_REVIEW",
            "meal_state": "NEEDS_SCHEMA_REVIEW",
            "trace_id": trace_id,
            "decision_rationale": decision_rationale or "Missing food_groups field",
            "gate_reason": gate_reason or "Missing food_groups field",
            "segment_count": segment_count,
            "food_group_count": 0,
            "food_groups": [],
            "top_3": [],
        }

    food_group_count = len(food_groups)
    top_3 = list(food_groups[0].get("top_3", []))
    state_raw = _coerce_str(payload.get("meal_state"), "meal_state")
    meal_state = state_raw if state_raw in _MEAL_STATES else _normalize_group_state(action_raw, state_raw)

    if not action_raw:
        action = "NEEDS_SCHEMA_REVIEW"
        meal_state = "NEEDS_SCHEMA_REVIEW"
        decision_rationale = decision_rationale or "Missing action field"
    elif action_raw in _GROUP_ACTIONS:
        action = action_raw
    else:
        action = "NEEDS_SCHEMA_REVIEW"
        meal_state = "NEEDS_SCHEMA_REVIEW"
        decision_rationale = f"Unsupported action field: {action_raw}"

    raw_food_group_count = payload.get("food_group_count")
    try:
        reported_food_group_count = int(raw_food_group_count) if raw_food_group_count is not None else food_group_count
    except (TypeError, ValueError):
        reported_food_group_count = food_group_count
    if reported_food_group_count != food_group_count:
        reported_food_group_count = food_group_count

    return {
        "action": action,
        "meal_state": meal_state,
        "trace_id": trace_id,
        "decision_rationale": decision_rationale or "No decision rationale provided",
        "gate_reason": gate_reason,
        "segment_count": segment_count,
        "food_group_count": reported_food_group_count,
        "food_groups": food_groups,
        "top_3": top_3,
    }


__all__ = ["reasoning_response_format", "coerce_reasoning_response"]
