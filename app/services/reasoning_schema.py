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
    "clarification_needed",
    "clarification_actions",
    "clarification",
    "question_kind",
    "question_focus",
    "question_examples",
    "top_3",
)

_CLARIFICATION_REQUIRED_FIELDS = (
    "question_id",
    "group_id",
    "group_label",
    "question_kind",
    "question_focus",
    "answer_type",
    "required",
    "segment_ids",
    "primary_segment_id",
    "validation_hints",
    "choices",
)

_ALLOWED_ANSWER_TYPES = ("single_choice", "multi_choice", "free_text", "confirm")
_ALLOWED_CLARIFICATION_ACTION_TYPES = (
    "AFFIRMATION",
    "CHOICE",
    "SOURCE_ORIGIN",
    "QUANTITY",
    "FREE_TEXT",
)
_ALLOWED_GROUP_ACTIONS = {
    "AUTO_CONFIRM",
    "AUTO_CONFIRM_LEARNED",
    "AUTO_CONFIRM_WITH_TRACE",
    "AFFIRMATION_REQUIRED",
    "IDENTITY_CLARIFICATION_REQUIRED",
    "READY_TO_WRITE",
    "ASK_QUANTITY",
    "ASK_CHOICE",
    "INTERVIEW",
    "FAILED_UNCLEAR",
    "NEEDS_SCHEMA_REVIEW",
}
_SOURCE_ORIGIN_STATES = (
    "HOME_COOKED",
    "STORE_BOUGHT_PREPARED",
    "PACKAGED_BRANDED",
    "RESTAURANT",
    "UNKNOWN",
)
_MEAL_STATES = {
    "READY_TO_WRITE",
    "PENDING_CHOICE",
    "PENDING_INTERVIEW",
    "PARTIAL_RESOLVED_WAITING",
    "FAILED_UNCLEAR",
    "NEEDS_SCHEMA_REVIEW",
}
_GROUP_ACTIONS = (
    "AUTO_CONFIRM",
    "AUTO_CONFIRM_LEARNED",
    "AUTO_CONFIRM_WITH_TRACE",
    "AFFIRMATION_REQUIRED",
    "IDENTITY_CLARIFICATION_REQUIRED",
    "ASK_QUANTITY",
    "ASK_CHOICE",
    "INTERVIEW",
    "READY_TO_WRITE",
    "FAILED_UNCLEAR",
    "NEEDS_SCHEMA_REVIEW",
)


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
        "food_item_id": {"type": "string"},
        "source_type": {"type": "string"},
        "brand_name": {"type": "string"},
        "restaurant_name": {"type": "string"},
        "portion_bucket": {"type": "string"},
    }
    legacy_clarification_properties = {
        "question_id": {"type": "string"},
        "group_id": {"type": "string"},
        "group_label": {"type": "string"},
        "question_kind": {"type": "string"},
        "question_focus": {"type": "string"},
        "answer_type": {
            "type": "string",
            "enum": list(_ALLOWED_ANSWER_TYPES),
        },
        "required": {"type": "boolean"},
        "segment_ids": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
        },
        "primary_segment_id": {"type": "string"},
        "choices": {
            "type": "array",
            "items": {"type": "string"},
        },
        "validation_hints": {
            "type": "object",
            "additionalProperties": False,
            "required": ["required"],
            "properties": {
                "required": {"type": "boolean"},
                "min_choices": {"type": "integer"},
                "max_choices": {"type": "integer"},
                "min_length": {"type": "integer"},
                "max_length": {"type": "integer"},
            },
        },
    }
    clarification_choice_properties = {
        "value": {"type": "string"},
        "label": {"type": "string"},
        "quick_prompt": {"type": "string"},
    }
    clarification_validation_hints_properties = {
        "required": {"type": "boolean"},
        "min_choices": {"type": "integer"},
        "max_choices": {"type": "integer"},
        "min_length": {"type": "integer"},
        "max_length": {"type": "integer"},
    }
    clarification_action_properties = {
        "type": {"type": "string", "enum": list(_ALLOWED_CLARIFICATION_ACTION_TYPES)},
        "kind": {"type": "string"},
        "user_prompt": {"type": "string"},
        "answer_type": {
            "type": "string",
            "enum": list(_ALLOWED_ANSWER_TYPES),
        },
        "choices": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["value", "label", "quick_prompt"],
                "properties": clarification_choice_properties,
            },
        },
        "allow_other": {"type": "boolean"},
        "other_label": {"type": "string"},
        "required": {"type": "boolean"},
        "reason": {"type": "string"},
        "validation_hints": {
            "type": "object",
            "additionalProperties": False,
            "required": ["required"],
            "properties": clarification_validation_hints_properties,
        },
        "question_id": {"type": "string"},
        "group_id": {"type": "string"},
        "group_label": {"type": "string"},
        "question_focus": {"type": "string"},
    }
    clarification_alias_properties = {
        "type": {"type": "string", "enum": list(_ALLOWED_CLARIFICATION_ACTION_TYPES)},
        "kind": {"type": "string"},
        "user_prompt": {"type": "string"},
        "answer_type": {
            "type": "string",
            "enum": list(_ALLOWED_ANSWER_TYPES),
        },
        "choices": {
            "type": "array",
            "items": clarification_choice_properties,
        },
        "allow_other": {"type": "boolean"},
        "other_label": {"type": "string"},
        "required": {"type": "boolean"},
        "reason": {"type": "string"},
        "validation_hints": {
            "type": "object",
            "additionalProperties": False,
            "required": ["required"],
            "properties": clarification_validation_hints_properties,
        },
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
        "clarification_needed": {"type": "boolean"},
        "clarification_actions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "type",
                    "kind",
                    "user_prompt",
                    "answer_type",
                    "choices",
                    "allow_other",
                    "other_label",
                    "required",
                    "reason",
                    "validation_hints",
                ],
                "properties": clarification_action_properties,
            },
            "minItems": 0,
        },
        "clarification": {
            "anyOf": [
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "type",
                        "kind",
                        "user_prompt",
                        "answer_type",
                        "choices",
                        "allow_other",
                        "other_label",
                        "required",
                        "reason",
                        "validation_hints",
                    ],
                    "properties": clarification_alias_properties,
                },
                {"type": "null"},
            ]
        },
        "question_kind": {"type": "string"},
        "question_focus": {"type": "string"},
        "question_examples": {
            "type": "array",
            "items": {"type": "string"},
        },
        "top_3": {
            "type": "array",
            "minItems": 3,
            "maxItems": 3,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": list(candidate_properties),
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
                    "clarification_schema",
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
                    "clarification_schema": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": list(_CLARIFICATION_REQUIRED_FIELDS),
                            "properties": legacy_clarification_properties,
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
    if value is None:
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


def _coerce_bool(value: object, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off"}:
            return False
    raise TypeError(f"{field} must be a boolean")


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


def _coerce_candidate_payload(candidate: Mapping[str, object], idx: int) -> dict[str, Any]:
    normalized: dict[str, Any] = {
        "candidate_id": _coerce_str(candidate.get("candidate_id"), "candidate_id")
        or f"candidate-{idx}",
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
        "nutrition_relevance": _coerce_str(candidate.get("nutrition_relevance"), "nutrition_relevance")
        or "medium",
        "source": _coerce_str(candidate.get("source"), "source") or "vector_match",
        "decision_rationale": _coerce_str(candidate.get("decision_rationale"), "decision_rationale")
        or "No candidate rationale provided",
        "nutrition_impact": _coerce_number(candidate.get("nutrition_impact"), "nutrition_impact"),
        "food_item_id": _coerce_str(candidate.get("food_item_id"), "food_item_id"),
        "source_type": _coerce_str(candidate.get("source_type"), "source_type"),
        "brand_name": _coerce_str(candidate.get("brand_name"), "brand_name"),
        "restaurant_name": _coerce_str(candidate.get("restaurant_name"), "restaurant_name"),
        "portion_bucket": _coerce_str(candidate.get("portion_bucket"), "portion_bucket"),
    }

    quantity_payload = candidate.get("quantity_payload")
    if isinstance(quantity_payload, Mapping):
        normalized["quantity_payload"] = {
            key: value
            for key, value in quantity_payload.items()
            if isinstance(key, str)
            and isinstance(value, (str, int, float))
            and not isinstance(value, bool)
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
        "food_item_id": "",
        "source_type": "",
        "brand_name": "",
        "restaurant_name": "",
        "portion_bucket": "",
    }


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


def _coerce_validation_hints(value: object, *, required: bool) -> dict[str, int | bool]:
    if not isinstance(value, Mapping):
        value = {}
    hints: dict[str, int | bool] = {"required": required}
    for field in ("min_choices", "max_choices", "min_length", "max_length"):
        raw_value = value.get(field)
        if raw_value is None:
            continue
        if isinstance(raw_value, bool) or not isinstance(raw_value, int):
            raise TypeError(f"{field} must be an integer")
        hints[field] = raw_value
    return hints


def _coerce_choice_option(value: object, idx: int) -> dict[str, Any]:
    if isinstance(value, Mapping):
        candidate_value = _coerce_str(value.get("value"), "value")
        label = _coerce_str(value.get("label"), "label")
        quick_prompt = _coerce_str(value.get("quick_prompt"), "quick_prompt")
        if not candidate_value:
            candidate_value = label or f"choice-{idx + 1}"
        if not label:
            label = candidate_value
        if not quick_prompt:
            quick_prompt = label
        return {
            "value": candidate_value,
            "label": label,
            "quick_prompt": quick_prompt,
        }

    if not isinstance(value, str):
        raise TypeError("clarification choice must be text")
    text = value.strip()
    if not text:
        raise TypeError("clarification choice must be non-empty text")
    return {
        "value": text,
        "label": text,
        "quick_prompt": text,
    }


def _coerce_clarification_choice_list(value: object, field: str, *, required: bool) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        if required:
            return []
        return []
    choices: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if item is None:
            continue
        if isinstance(item, Mapping) and set(item.keys()) <= {"value", "label", "quick_prompt"}:
            choices.append(_coerce_choice_option(item, index))
        elif isinstance(item, str):
            choices.append(_coerce_choice_option(item, index))
        else:
            # Preserve unknown legacy shape by normalizing via string coercion when possible.
            choice = _coerce_str(item, "choice")
            if choice:
                choices.append(_coerce_choice_option(choice, index))
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for choice in choices:
        choice_key = choice["value"].strip().casefold()
        if choice_key in seen:
            continue
        seen.add(choice_key)
        deduped.append(choice)
    return deduped


def _coerce_clarification_action(
    action: Mapping[str, object],
    idx: int,
) -> dict[str, Any]:
    action_type = _coerce_str(action.get("type"), "type").upper() or "CHOICE"
    if action_type not in _ALLOWED_CLARIFICATION_ACTION_TYPES:
        action_type = "CHOICE"

    answer_type = _coerce_str(action.get("answer_type"), "answer_type") or "single_choice"
    if answer_type not in _ALLOWED_ANSWER_TYPES:
        answer_type = "single_choice"

    required = _coerce_bool(action.get("required"), "required")
    choices = _coerce_clarification_choice_list(
        action.get("choices"),
        "choices",
        required=required,
    )
    validation_hints = _coerce_validation_hints(action.get("validation_hints"), required=required)

    return {
        "type": action_type,
        "kind": _coerce_str(action.get("kind"), "kind") or action_type,
        "user_prompt": _coerce_str(action.get("user_prompt"), "user_prompt")
        or _coerce_str(action.get("prompt"), "prompt")
        or f"Group {idx + 1} requires confirmation",
        "answer_type": answer_type,
        "choices": choices,
        "allow_other": _coerce_bool(action.get("allow_other"), "allow_other") if action.get("allow_other") is not None else True,
        "other_label": _coerce_str(action.get("other_label"), "other_label") or "Other",
        "required": required,
        "reason": _coerce_str(action.get("reason"), "reason") or "Model-requested clarification",
        "validation_hints": validation_hints,
        "question_id": _coerce_str(action.get("question_id"), "question_id") or f"group_{idx}_clarification",
        "group_id": _coerce_str(action.get("group_id"), "group_id") or f"group-{idx + 1}",
        "group_label": _coerce_str(action.get("group_label"), "group_label") or f"group-{idx + 1}",
        "question_focus": _coerce_str(action.get("question_focus"), "question_focus"),
    }


def _coerce_clarification_actions(value: object, *, group_id: str, group_label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            continue
        try:
            normalized.append(
                {
                    **_coerce_clarification_action(item, index),
                    "group_id": _coerce_str(item.get("group_id"), "group_id") or group_id,
                    "group_label": _coerce_str(item.get("group_label"), "group_label") or group_label,
                }
            )
        except TypeError:
            continue
    return normalized


def _coerce_group_legacy_action(group: Mapping[str, object], idx: int) -> list[dict[str, Any]]:
    question_kind = _coerce_str(group.get("question_kind"), "question_kind").upper()
    if not question_kind:
        return []

    answer_type = _coerce_str(group.get("answer_type"), "answer_type") or "free_text"
    if answer_type not in _ALLOWED_ANSWER_TYPES:
        answer_type = "free_text"
    group_id = _coerce_str(group.get("group_id"), "group_id") or f"group-{idx + 1}"
    group_label = _coerce_str(group.get("group_label"), "group_label") or group_id
    primary_segment_id = (
        _coerce_str(group.get("primary_segment_id"), "primary_segment_id") or f"segment-{idx + 1}"
    )
    required = True
    validation_hints = _coerce_validation_hints(
        {"min_choices": 1, "max_choices": 1} if answer_type == "single_choice" else {},
        required=required,
    )
    raw_choices = _coerce_list_of_text(group.get("question_examples"), "question_examples")
    choices = _coerce_clarification_choice_list(raw_choices, "question_examples", required=required)

    action_type = "CHOICE"
    if question_kind == "SOURCE_ORIGIN":
        action_type = "SOURCE_ORIGIN"
    elif question_kind == "QUANTITY":
        action_type = "QUANTITY"

    return [
        _coerce_clarification_action(
            {
                "type": action_type,
                "kind": question_kind or action_type,
                "user_prompt": _coerce_str(group.get("question_focus"), "question_focus")
                or f"Please clarify {group_label}",
                "answer_type": answer_type,
                "required": required,
                "choices": choices,
                "allow_other": question_kind == "CHOICE",
                "other_label": "Other",
                "reason": "Legacy question compatibility",
                "validation_hints": validation_hints,
                "group_id": group_id,
                "group_label": group_label,
                "question_id": f"{group_id}:legacy",
                "question_focus": _coerce_str(group.get("question_focus"), "question_focus"),
            },
            idx,
        )
    ]


def _coerce_clarification_schema(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            continue
        try:
            normalized.append(_coerce_clarification_action(item, index))
        except TypeError:
            continue
    return normalized


def _attach_root_clarification_actions(
    food_groups: list[dict[str, Any]],
    clarification_schema: list[dict[str, Any]],
) -> None:
    if not clarification_schema:
        return

    actions_by_group: dict[str, list[dict[str, Any]]] = {}
    for action in clarification_schema:
        if not isinstance(action, Mapping):
            continue
        group_id = _coerce_str(action.get("group_id"), "group_id")
        if not group_id:
            continue
        actions_by_group.setdefault(group_id, []).append(dict(action))

    for group in food_groups:
        group_id = _coerce_str(group.get("group_id"), "group_id")
        if not group_id:
            continue
        if group.get("clarification_actions"):
            continue
        migrated = actions_by_group.get(group_id, [])
        if not migrated:
            continue
        group["clarification_actions"] = migrated
        group["clarification"] = migrated[0]
        group["clarification_needed"] = True


def _normalize_group_state(action: str, state: str) -> str:
    if state in _MEAL_STATES:
        return state
    if action in {
        "ASK_QUANTITY",
        "ASK_CHOICE",
        "INTERVIEW",
        "AFFIRMATION_REQUIRED",
        "IDENTITY_CLARIFICATION_REQUIRED",
    }:
        return "PENDING_INTERVIEW"
    if action in {"AUTO_CONFIRM", "AUTO_CONFIRM_WITH_TRACE", "AUTO_CONFIRM_LEARNED", "READY_TO_WRITE"}:
        return "READY_TO_WRITE"
    if action == "FAILED_UNCLEAR":
        return "FAILED_UNCLEAR"
    return "NEEDS_SCHEMA_REVIEW"


def _coerce_group_payload(group: Mapping[str, object], idx: int) -> dict[str, Any]:
    action_raw = _coerce_str(group.get("group_action") or group.get("action"), "group_action")
    if not action_raw:
        action = "AUTO_CONFIRM"
    elif action_raw in _ALLOWED_GROUP_ACTIONS:
        action = action_raw
    elif action_raw in {"AUTO_CONFIRM", "AUTO_CONFIRM_WITH_TRACE", "ASK_QUANTITY", "ASK_CHOICE", "INTERVIEW", "READY_TO_WRITE"}:
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

    question_kind = _coerce_str(group.get("question_kind"), "question_kind")
    question_focus = _coerce_str(group.get("question_focus"), "question_focus")
    question_examples = _coerce_list_of_text(group.get("question_examples"), "question_examples")

    clarification_actions = _coerce_clarification_actions(
        group.get("clarification_actions"),
        group_id=group_id,
        group_label=group_label or str(top_candidate.get("label") or f"group {idx + 1}"),
    )
    if not clarification_actions:
        clarification_legacy = group.get("clarification")
        if isinstance(clarification_legacy, Mapping):
            clarification_actions = _coerce_clarification_actions(
                [clarification_legacy],
                group_id=group_id,
                group_label=group_label or str(top_candidate.get("label") or f"group {idx + 1}"),
            )
        elif question_kind:
            clarification_actions = _coerce_group_legacy_action(group, idx)

    clarification_needed = _coerce_bool(group.get("clarification_needed"), "clarification_needed")
    if not clarification_needed:
        clarification_needed = bool(clarification_actions)

    if group.get("clarification") is None:
        clarification_alias: dict[str, Any] | None = clarification_actions[0] if clarification_actions else None
    else:
        clarification_alias = clarification_actions[0] if isinstance(group.get("clarification"), Mapping) else None

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
        "clarification_needed": clarification_needed,
        "clarification_actions": clarification_actions,
        "clarification": clarification_alias,
        "question_kind": question_kind,
        "question_focus": question_focus,
        "question_examples": question_examples,
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
        "group_label": _coerce_str(payload.get("group_label"), "group_label")
        or str(top_3[0].get("label") or "unlabeled food"),
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
        "clarification_needed": False,
        "clarification_actions": _coerce_clarification_schema(payload.get("clarification_schema")),
        "top_3": top_3,
        "question_kind": _coerce_str(payload.get("question_kind"), "question_kind"),
        "question_focus": _coerce_str(payload.get("question_focus"), "question_focus"),
        "question_examples": _coerce_list_of_text(payload.get("question_examples"), "question_examples"),
    }
    if not group["clarification_actions"]:
        legacy_question = _coerce_group_legacy_action(group, 0)
        group["clarification_actions"] = legacy_question
        group["clarification"] = legacy_question[0] if legacy_question else None
        group["clarification_needed"] = bool(group["clarification_actions"])

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

    clarification_schema = _coerce_clarification_schema(payload.get("clarification_schema"))
    _attach_root_clarification_actions(food_groups, clarification_schema)

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
            "clarification_schema": [],
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
        reported_food_group_count = (
            int(raw_food_group_count)
            if raw_food_group_count is not None
            else food_group_count
        )
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
        "clarification_schema": clarification_schema,
        "top_3": top_3,
    }


__all__ = ["reasoning_response_format", "coerce_reasoning_response"]
