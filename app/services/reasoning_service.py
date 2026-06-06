from __future__ import annotations

import base64
import json
import mimetypes
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping
from inspect import isawaitable

from app.config import get_settings
from app.models import MealLog, MealSegment, MealProcessingStatus
from app.services import image_service, tracing_service
from app.services.interview_service import (
    _all_finalizer_groups_degraded,
    _build_group_finalizer_inputs,
    _run_group_finalizers,
    final_resolution_from_confirmation,
)
from app.services.llm_client import get_llm_client
from app.services.meal_resolution_service import (
    FinalSegmentResolution,
    ResolvedFoodInput,
    apply_final_meal_resolution,
)
from app.services.reasoning_schema import (
    coerce_reasoning_response,
    normalize_source_question_policy,
    reasoning_response_format,
)
from app.services.taxonomy_service import load_reasoning_taxonomy

_REVIEW_STATE = "NEEDS_SCHEMA_REVIEW"
_FAILED_UNCLEAR_STATE = "FAILED_UNCLEAR"
_READY_TO_WRITE_STATE = "READY_TO_WRITE"
_INTERVIEW_STATES = {
    "PENDING_INTERVIEW",
    "PENDING_CHOICE",
    "INTERVIEWING",
    "PARTIAL_RESOLVED_WAITING",
}
_INTERVIEW_STATE_FROM_OUTPUT = "PENDING_INTERVIEW"
_CONFIDENCE_MARGIN = 0.05
_NUTRITION_IMPACT_THRESHOLD = 0.40
_REASONING_VECTOR_CANDIDATE_MIN_SIMILARITY = 0.92
_SOURCE_ORIGIN_CHOICES = (
    "HOME_COOKED",
    "STORE_BOUGHT_PREPARED",
    "PACKAGED_BRANDED",
    "RESTAURANT",
    "UNKNOWN",
)
_SOURCE_ORIGIN_LABELS = {
    "HOME_COOKED": "homemade",
    "STORE_BOUGHT_PREPARED": "store bought",
    "PACKAGED_BRANDED": "packaged",
    "RESTAURANT": "restaurant",
    "UNKNOWN": "not sure",
}
_SOURCE_ORIGIN_TOKENS = {
    "wrap",
    "bakery",
    "packaged",
    "restaurant",
    "branded",
    "label",
    "dessert",
    "sauce",
    "pizza",
    "burger",
    "takeout",
}
_SOURCE_POLICY_NONE = ""
_SOURCE_POLICY_ASK_GENERIC = "ask_generic"
_SOURCE_POLICY_ASK_AFFIRMATION = "ask_affirmation"
_SOURCE_POLICY_DEFER_UNTIL_IDENTITY = "defer_until_identity"
_MIN_LEARNED_MATCHES_FOR_SOURCE_CONSENSUS = 5
_SOURCE_DOMINANCE_MIN_SHARE = 0.8
_SOURCE_DOMINANCE_MIN_GAP = 0.4

_GROUP_ACTION_ORDER = (
    _REVIEW_STATE,
    _FAILED_UNCLEAR_STATE,
    "IDENTITY_CLARIFICATION_REQUIRED",
    "AFFIRMATION_REQUIRED",
    "ASK_QUANTITY",
    "ASK_SOURCE_ORIGIN",
    "AUTO_CONFIRM_LEARNED",
    "AUTO_CONFIRM_WITH_TRACE",
    "AUTO_CONFIRM",
)


def _primary_group_action(group_actions: list[str]) -> str:
    for action in _GROUP_ACTION_ORDER:
        if action in group_actions:
            return action
    return _REVIEW_STATE


def _group_actions_for_result(
    *,
    group: Mapping[str, Any],
    group_action: str,
    clarification_actions: list[dict[str, Any]],
) -> list[str]:
    raw_actions = group.get("group_actions")
    actions = [
        str(action).strip().upper()
        for action in raw_actions
        if isinstance(action, str) and str(action).strip()
    ] if isinstance(raw_actions, list) else []
    actions.append(group_action)
    for action in clarification_actions:
        action_type = (_coerce_str(action.get("type"), "type") or "").upper()
        action_kind = (_coerce_str(action.get("kind"), "kind") or "").upper()
        if action_type == "SOURCE_ORIGIN" or action_kind == "SOURCE_ORIGIN":
            actions.append("ASK_SOURCE_ORIGIN")
        elif action_type == "QUANTITY" or action_kind == "QUANTITY":
            actions.append("ASK_QUANTITY")
        elif action_type == "AFFIRMATION" or action_kind == "AFFIRMATION":
            actions.append("AFFIRMATION_REQUIRED")
        elif action_type in {"CHOICE", "FREE_TEXT"} or action_kind in {"IDENTITY", "DETAIL", "CHOICE", "FREE_TEXT"}:
            actions.append("IDENTITY_CLARIFICATION_REQUIRED")

    deduped: list[str] = []
    for action in actions:
        if action not in _GROUP_ACTION_ORDER or action in deduped:
            continue
        deduped.append(action)

    if _FAILED_UNCLEAR_STATE in deduped:
        return [_FAILED_UNCLEAR_STATE]
    if _REVIEW_STATE in deduped:
        return [_REVIEW_STATE]
    if "IDENTITY_CLARIFICATION_REQUIRED" in deduped and "AFFIRMATION_REQUIRED" in deduped:
        deduped = [action for action in deduped if action != "AFFIRMATION_REQUIRED"]
    if any(action in {"IDENTITY_CLARIFICATION_REQUIRED", "AFFIRMATION_REQUIRED", "ASK_QUANTITY", "ASK_SOURCE_ORIGIN"} for action in deduped):
        deduped = [
            action
            for action in deduped
            if action not in {"AUTO_CONFIRM", "AUTO_CONFIRM_LEARNED", "AUTO_CONFIRM_WITH_TRACE"}
        ]
    return deduped or ["AUTO_CONFIRM"]


def _coerce_float(value: object, *, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value)


def _reasoning_match_threshold(default: float = 0.90) -> float:
    try:
        value = get_settings().REASONING_MATCH_THRESHOLD
    except Exception:
        return default
    return _coerce_float(value, default=default)


def _reasoning_vector_candidate_min_similarity(
    default: float = _REASONING_VECTOR_CANDIDATE_MIN_SIMILARITY,
) -> float:
    return default


def _result_similarity(result: object) -> float | None:
    raw_value = result.get("similarity") if isinstance(result, Mapping) else getattr(result, "similarity", None)
    if raw_value is None or isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        return None
    return float(raw_value)


def _vector_candidates_allowed_for_reasoning(result: object) -> bool:
    similarity = _result_similarity(result)
    if similarity is None:
        return False
    return similarity > _reasoning_vector_candidate_min_similarity()


def _coerce_str(value: object, field: str) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        if text:
            return text
    return None


def _coerce_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if text:
            normalized.append(text)
    return normalized


def _coerce_segment_ids(value: object, *, primary_segment_id: str, fallback: str) -> list[str]:
    segment_ids = _coerce_string_list(value)
    if primary_segment_id and primary_segment_id not in segment_ids:
        segment_ids.insert(0, primary_segment_id)
    deduped: list[str] = []
    seen: set[str] = set()
    for segment_id in segment_ids:
        if segment_id in seen:
            continue
        seen.add(segment_id)
        deduped.append(segment_id)
    if deduped:
        return deduped
    return [primary_segment_id or fallback]


def _coerce_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _coerce_quantity_payload(payload: object) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {}

    result: dict[str, Any] = {}
    raw_label = payload.get("quantity_label")
    if isinstance(raw_label, str):
        label = raw_label.strip()
        if label:
            result["quantity_label"] = label

    raw_display = payload.get("display") or payload.get("label")
    if isinstance(raw_display, str):
        display = raw_display.strip()
        if display:
            result["display"] = display

    portion_bucket = payload.get("portion_bucket")
    if isinstance(portion_bucket, str) and portion_bucket.strip():
        result["portion_bucket"] = portion_bucket.strip().upper()

    quantity = payload.get("quantity")
    if isinstance(quantity, (int, float)) and not isinstance(quantity, bool):
        result["quantity"] = float(quantity)
    elif isinstance(quantity, str):
        q = quantity.strip()
        if q:
            result["quantity"] = q

    unit = payload.get("unit")
    if isinstance(unit, str):
        normalized = unit.strip()
        if normalized:
            result["unit"] = normalized

    confidence = payload.get("quantity_confidence")
    if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
        result["quantity_confidence"] = float(confidence)

    return result


def _normalize_portion_bucket(value: object) -> str:
    bucket = _coerce_str(value, "portion_bucket") or "STANDARD"
    bucket_upper = bucket.upper()
    if bucket_upper in {"SMALL", "STANDARD", "LARGE"}:
        return bucket_upper
    return "STANDARD"


def _normalize_trace_id_from_payload(
    payload: Mapping[str, object] | None,
    metadata: Mapping[str, object | None] | None,
) -> str | None:
    if payload is None:
        payload_id = None
    else:
        payload_id = _coerce_str(payload.get("trace_id"), "trace_id")
    if payload_id:
        return payload_id
    if metadata is None:
        return None
    value = metadata.get("trace_id")
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, (int, float)):
        return str(value)
    return None


def _candidate_score(candidate: Mapping[str, Any] | dict[str, Any] | Any) -> float:
    if not isinstance(candidate, Mapping):
        return 0.0
    return _coerce_float(candidate.get("identity_confidence"), default=0.0)


def _is_placeholder_candidate(candidate: Mapping[str, Any]) -> bool:
    label = (_coerce_str(candidate.get("label"), "label") or "").casefold()
    if label != "unlabeled food":
        return False
    has_identity = bool(_coerce_str(candidate.get("food_item_id"), "food_item_id"))
    has_evidence = bool(_coerce_string_list(candidate.get("visual_evidence"))) or bool(
        _coerce_string_list(candidate.get("missing_evidence"))
    )
    score = _candidate_score(candidate)
    return not has_identity and not has_evidence and score <= 0.0


def _meaningful_top_candidates(group: Mapping[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for candidate in list(group.get("top_3", [])):
        if not isinstance(candidate, Mapping):
            continue
        if _is_placeholder_candidate(candidate):
            continue
        candidates.append(dict(candidate))
    return candidates[:3]


def _candidate_ids(candidates: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        candidate_id = _coerce_str(candidate.get("candidate_id"), "candidate_id")
        if candidate_id:
            ids.append(candidate_id)
    return ids


def _should_ask_quantity(missing_evidence: list[str]) -> bool:
    if not missing_evidence:
        return False
    needle = {"portion", "portion_unit", "serving_size", "serving_unit", "quantity"}
    for item in missing_evidence:
        normalized = item.casefold()
        if any(term in normalized for term in needle):
            return True
    return False


def _has_nutrition_relevant_missing_evidence(missing_evidence: list[str]) -> bool:
    if not missing_evidence:
        return False
    needle = {
        "portion",
        "portion_unit",
        "serving",
        "quantity",
        "ingredient",
        "vegetable",
        "protein",
        "meat",
        "bread",
        "rice",
        "sauce",
        "oil",
        "filling",
        "inside",
    }
    for item in missing_evidence:
        normalized = item.casefold()
        if any(term in normalized for term in needle):
            return True
    return False


def _safe_parse_json(value: str | bytes | bytearray | None) -> dict[str, Any] | None:
    if not isinstance(value, (str, bytes, bytearray)):
        return None
    try:
        loaded = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None
    if isinstance(loaded, dict):
        return loaded
    return None


def _extract_trace_metadata(response: object) -> tuple[str | None, int | None]:
    if not isinstance(response, Mapping):
        return None, None

    trace_values: list[str] = []
    cached_tokens: list[int] = []

    def walk(node: Any) -> None:
        if node is None:
            return
        if isinstance(node, Mapping):
            for key, value in node.items():
                lowered = str(key).lower()
                if lowered in {"trace_id", "trace-id", "traceid", "x-trace-id"}:
                    if isinstance(value, str) and value.strip():
                        trace_values.append(value.strip())
                    elif isinstance(value, (int, float)):
                        trace_values.append(str(value))
                if lowered == "cached_tokens" and isinstance(value, (int, float)):
                    cached_tokens.append(int(value))
                walk(value)
        elif isinstance(node, (list, tuple, set)):
            for item in node:
                walk(item)

    walk(response)
    return (trace_values[0] if trace_values else None, max(cached_tokens) if cached_tokens else None)


def _parse_reasoning_message(response: Any) -> dict[str, Any] | None:
    if not isinstance(response, Mapping):
        return None
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, Mapping):
        return None
    message = first.get("message")
    if not isinstance(message, Mapping):
        return None
    content = message.get("content")
    return _safe_parse_json(content)


def _end_trace(trace: Any, *, output: Mapping[str, Any] | dict[str, Any]) -> None:
    end = getattr(trace, "end", None)
    if callable(end):
        end(output=dict(output))


def append_grounding_trace(
    *,
    reasoning_payload: Mapping[str, Any],
    grounding_trace: Mapping[str, Any],
) -> dict[str, Any]:
    merged = dict(reasoning_payload)
    merged["grounding_trace"] = dict(grounding_trace)
    return merged


def _normalized_group_result(
    *,
    group: Mapping[str, Any],
    group_action: str,
    group_state: str,
    gate_reason: str,
    decision_rationale: str,
    clarification_actions: list[dict[str, Any]] | None = None,
    source_question_policy: str | None = None,
    source_trigger_reason: str | None = None,
    learned_source_distribution: list[dict[str, Any]] | None = None,
    selected_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    top_three = _meaningful_top_candidates(group)
    selected_candidate_id = _coerce_str(group.get("selected_candidate_id"), "selected_candidate_id")
    if not selected_candidate_id and top_three:
        selected_candidate_id = str(top_three[0].get("candidate_id") or "")
    normalized_actions = [dict(action) for action in clarification_actions or []]
    question_kind = _coerce_str(group.get("question_kind"), "question_kind")
    question_focus = _coerce_str(group.get("question_focus"), "question_focus")
    if normalized_actions and not question_kind:
        question_kind = _coerce_str(
            normalized_actions[0].get("kind") or normalized_actions[0].get("type"),
            "question_kind",
        )
    if normalized_actions and not question_focus:
        question_focus = _coerce_str(normalized_actions[0].get("question_focus"), "question_focus")
    group_actions = _group_actions_for_result(
        group=group,
        group_action=group_action,
        clarification_actions=normalized_actions,
    )
    group_action = _primary_group_action(group_actions)
    normalized_distribution = learned_source_distribution
    if normalized_distribution is None:
        normalized_distribution = _coerce_learned_source_distribution(group.get("learned_source_distribution"))
    normalized_selected_identity = _selected_identity_metadata(
        selected_identity if isinstance(selected_identity, Mapping) else group.get("selected_identity"),
        top_three[0] if top_three else {},
    )
    return {
        "group_id": _coerce_str(group.get("group_id"), "group_id") or "group-unknown",
        "group_label": _coerce_str(group.get("group_label"), "group_label")
        or _coerce_str(group.get("label"), "label")
        or "unlabeled food group",
        "group_action": group_action,
        "group_actions": group_actions,
        "group_state": group_state,
        "primary_segment_id": _coerce_str(group.get("primary_segment_id"), "primary_segment_id")
        or _coerce_str(group.get("segment_id"), "segment_id")
        or "segment-unknown",
        "segment_ids": _coerce_string_list(group.get("segment_ids")) or [
            _coerce_str(group.get("primary_segment_id"), "primary_segment_id")
            or "segment-unknown"
        ],
        "selected_candidate_id": selected_candidate_id,
        "visual_evidence": _coerce_string_list(group.get("visual_evidence"))
        or _coerce_string_list(top_three[0].get("visual_evidence") if top_three else None),
        "missing_evidence": _coerce_string_list(group.get("missing_evidence"))
        or _coerce_string_list(top_three[0].get("missing_evidence") if top_three else None),
        "decision_rationale": decision_rationale,
        "gate_reason": gate_reason,
        "clarification_needed": bool(normalized_actions),
        "clarification_actions": normalized_actions,
        "question_kind": question_kind,
        "question_focus": question_focus,
        "question_examples": _coerce_string_list(group.get("question_examples")),
        "source_question_policy": (
            normalize_source_question_policy(source_question_policy)
            if source_question_policy is not None
            else normalize_source_question_policy(group.get("source_question_policy"))
        ),
        "source_trigger_reason": source_trigger_reason
        if source_trigger_reason is not None
        else _coerce_str(group.get("source_trigger_reason"), "source_trigger_reason"),
        "learned_source_distribution": normalized_distribution,
        "selected_identity": normalized_selected_identity,
        "top_3": top_three,
    }


def _coerce_learned_source_distribution(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    distribution: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        candidate_id = _coerce_str(item.get("candidate_id"), "candidate_id")
        source = _coerce_str(item.get("source"), "source")
        count = _coerce_int(item.get("count"))
        share = _coerce_float(item.get("share"), default=-1.0)
        if not candidate_id or not source or count is None or count < 0 or share < 0.0:
            continue
        distribution.append(
            {
                "candidate_id": candidate_id,
                "source": source,
                "count": count,
                "share": max(0.0, min(share, 1.0)),
            }
        )
    return distribution


def _selected_identity_metadata(value: object, top_candidate: object) -> dict[str, str]:
    source = value if isinstance(value, Mapping) else {}
    fallback = top_candidate if isinstance(top_candidate, Mapping) else {}
    candidate_id = _coerce_str(source.get("candidate_id"), "candidate_id") or _coerce_str(
        fallback.get("candidate_id"),
        "candidate_id",
    )
    label = _coerce_str(source.get("label"), "label") or _coerce_str(fallback.get("label"), "label")
    food_item_id = _coerce_str(source.get("food_item_id"), "food_item_id") or _coerce_str(
        fallback.get("food_item_id"),
        "food_item_id",
    )
    return {
        "candidate_id": candidate_id,
        "label": label,
        "food_item_id": food_item_id,
    }


def _dominant_source_for_selected_identity(
    distribution: list[dict[str, Any]],
    *,
    candidate_id: str,
) -> dict[str, Any] | None:
    if not candidate_id:
        return None
    candidate_distribution = [
        entry
        for entry in distribution
        if _coerce_str(entry.get("candidate_id"), "candidate_id") == candidate_id
    ]
    if not candidate_distribution:
        return None
    ordered = sorted(
        candidate_distribution,
        key=lambda entry: (
            _coerce_float(entry.get("share"), default=0.0),
            _coerce_int(entry.get("count")) or 0,
        ),
        reverse=True,
    )
    top_entry = ordered[0]
    top_share = _coerce_float(top_entry.get("share"), default=0.0)
    top_count = _coerce_int(top_entry.get("count")) or 0
    next_share = _coerce_float(ordered[1].get("share"), default=0.0) if len(ordered) > 1 else 0.0
    if (
        top_count >= _MIN_LEARNED_MATCHES_FOR_SOURCE_CONSENSUS
        and top_share >= _SOURCE_DOMINANCE_MIN_SHARE
        and (top_share - next_share) >= _SOURCE_DOMINANCE_MIN_GAP
    ):
        return top_entry
    return None


def _learned_match_count(*, group: Mapping[str, Any], visual_only_without_learned: bool) -> int | None:
    explicit = _coerce_int(group.get("learned_match_count"))
    if explicit is not None:
        return max(0, explicit)
    top_candidates = group.get("top_3")
    if isinstance(top_candidates, list) and not top_candidates:
        return 0
    if visual_only_without_learned:
        return 0
    return None


def _contains_source_origin_token(*values: object) -> bool:
    haystack = " ".join(
        str(value).strip().casefold()
        for value in values
        if isinstance(value, str) and value.strip()
    )
    return any(token in haystack for token in _SOURCE_ORIGIN_TOKENS)


def _needs_source_origin_question(group: Mapping[str, Any]) -> bool:
    if normalize_source_question_policy(group.get("source_question_policy")) == _SOURCE_POLICY_ASK_GENERIC:
        return True
    if (_coerce_str(group.get("question_kind"), "question_kind") or "").upper() == "SOURCE_ORIGIN":
        return True
    if _contains_source_origin_token(
        group.get("group_label"),
        group.get("question_focus"),
        group.get("gate_reason"),
        group.get("decision_rationale"),
        *(_coerce_string_list(group.get("visual_evidence"))),
        *(_coerce_string_list(group.get("missing_evidence"))),
        *(_coerce_string_list(group.get("question_examples"))),
    ):
        return True
    for candidate in list(group.get("top_3", [])):
        if not isinstance(candidate, Mapping):
            continue
        if _contains_source_origin_token(
            candidate.get("label"),
            candidate.get("source"),
            *(_coerce_string_list(candidate.get("visual_evidence"))),
            *(_coerce_string_list(candidate.get("missing_evidence"))),
        ):
            return True
    return False


def _normalized_choice_payloads(choices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for choice in choices:
        value = _coerce_str(choice.get("value"), "value")
        label = _coerce_str(choice.get("label"), "label")
        quick_prompt = _coerce_str(choice.get("quick_prompt"), "quick_prompt")
        if not value or not label:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        payload = {
            "value": value,
            "label": label,
            "quick_prompt": quick_prompt or label,
        }
        for key in ("food_item_id", "source_type", "brand_name", "restaurant_name"):
            extra_value = _coerce_str(choice.get(key), key)
            if extra_value:
                payload[key] = extra_value
        deduped.append(payload)
    return deduped


def _identity_choice_payloads(group: Mapping[str, Any]) -> list[dict[str, Any]]:
    choices: list[dict[str, Any]] = []
    seen_candidate_ids: set[str] = set()
    seen_labels: set[str] = set()
    for candidate in _meaningful_top_candidates(group):
        candidate_id = _coerce_str(candidate.get("candidate_id"), "candidate_id")
        label = _coerce_str(candidate.get("label"), "label")
        label_key = label.casefold() if label else ""
        if not candidate_id or not label or candidate_id in seen_candidate_ids or label_key in seen_labels:
            continue
        seen_candidate_ids.add(candidate_id)
        seen_labels.add(label_key)
        choice = {
            "value": candidate_id,
            "label": label,
            "quick_prompt": label,
        }
        for key in ("food_item_id", "source_type", "brand_name", "restaurant_name"):
            extra_value = _coerce_str(candidate.get(key), key)
            if extra_value:
                choice[key] = extra_value
        choices.append(choice)
    choices.append({"value": "OTHER", "label": "Other", "quick_prompt": "Other"})
    return _normalized_choice_payloads(choices)


def _source_origin_choice_payloads() -> list[dict[str, str]]:
    return [
        {
            "value": value,
            "label": _SOURCE_ORIGIN_LABELS[value],
            "quick_prompt": _SOURCE_ORIGIN_LABELS[value],
        }
        for value in _SOURCE_ORIGIN_CHOICES
    ]


def _action_validation_hints(*, answer_type: str, allow_other: bool = False) -> dict[str, int | bool]:
    hints: dict[str, int | bool] = {"required": True}
    if answer_type in {"single_choice", "confirm"}:
        hints["min_choices"] = 1
        hints["max_choices"] = 1
    if answer_type == "free_text":
        hints["max_length"] = 220
    if allow_other:
        hints["min_choices"] = 1
        hints["max_choices"] = 1
    return hints


def _existing_group_action(
    group: Mapping[str, Any],
    *,
    action_type: str,
) -> Mapping[str, Any] | None:
    for action in list(group.get("clarification_actions", [])):
        if not isinstance(action, Mapping):
            continue
        raw_type = (_coerce_str(action.get("type"), "type") or "").upper()
        raw_kind = (_coerce_str(action.get("kind"), "kind") or "").upper()
        if raw_type == action_type or raw_kind == action_type:
            return action
    return None


def _group_prompt_subject(group: Mapping[str, Any]) -> str:
    return _coerce_str(group.get("group_label"), "group_label") or "this food"


def _build_group_action(
    *,
    group: Mapping[str, Any],
    action_type: str,
    kind: str,
    question_id: str,
    user_prompt: str,
    answer_type: str,
    choices: list[dict[str, str]],
    allow_other: bool,
    reason: str,
) -> dict[str, Any]:
    group_id = _coerce_str(group.get("group_id"), "group_id") or "group-unknown"
    group_label = _group_prompt_subject(group)
    existing = _existing_group_action(group, action_type=action_type)
    question_focus = (
        _coerce_str(existing.get("question_focus"), "question_focus")
        if isinstance(existing, Mapping)
        else None
    ) or _coerce_str(group.get("question_focus"), "question_focus")
    return {
        "type": action_type,
        "kind": kind,
        "user_prompt": user_prompt,
        "answer_type": answer_type,
        "choices": choices,
        "allow_other": allow_other,
        "other_label": "Other" if allow_other else "",
        "required": True,
        "reason": reason,
        "validation_hints": _action_validation_hints(answer_type=answer_type, allow_other=allow_other),
        "question_id": (
            _coerce_str(existing.get("question_id"), "question_id")
            if isinstance(existing, Mapping)
            else None
        )
        or question_id,
        "group_id": group_id,
        "group_label": group_label,
        "question_focus": question_focus or "",
    }


def _build_identity_action(group: Mapping[str, Any], *, reason: str) -> dict[str, Any]:
    group_id = _coerce_str(group.get("group_id"), "group_id") or "group-unknown"
    return _build_group_action(
        group=group,
        action_type="CHOICE",
        kind="IDENTITY",
        question_id=f"{group_id}:identity",
        user_prompt=f"Which option best matches the {_group_prompt_subject(group)}?",
        answer_type="single_choice",
        choices=_identity_choice_payloads(group),
        allow_other=True,
        reason=reason,
    )


def _build_affirmation_action(group: Mapping[str, Any], *, reason: str) -> dict[str, Any]:
    group_id = _coerce_str(group.get("group_id"), "group_id") or "group-unknown"
    top_label = None
    if isinstance(group.get("top_3"), list) and group["top_3"]:
        first_candidate = group["top_3"][0]
        if isinstance(first_candidate, Mapping):
            top_label = _coerce_str(first_candidate.get("label"), "label")
    prompt_subject = top_label or _group_prompt_subject(group)
    return _build_group_action(
        group=group,
        action_type="AFFIRMATION",
        kind="AFFIRMATION",
        question_id=f"{group_id}:affirmation",
        user_prompt=f"I think this is {prompt_subject}. Is that right?",
        answer_type="confirm",
        choices=[
            {"value": "YES", "label": "Yes", "quick_prompt": "Yes"},
            {"value": "NO", "label": "No", "quick_prompt": "No"},
        ],
        allow_other=False,
        reason=reason,
    )


def _build_source_origin_action(group: Mapping[str, Any], *, reason: str) -> dict[str, Any]:
    group_id = _coerce_str(group.get("group_id"), "group_id") or "group-unknown"
    return _build_group_action(
        group=group,
        action_type="SOURCE_ORIGIN",
        kind="SOURCE_ORIGIN",
        question_id=f"{group_id}:source_origin",
        user_prompt=(
            f"How should I treat the {_group_prompt_subject(group)} for nutrition: "
            "homemade, store bought, packaged, restaurant, or not sure?"
        ),
        answer_type="single_choice",
        choices=_source_origin_choice_payloads(),
        allow_other=False,
        reason=reason,
    )


def _build_quantity_action(group: Mapping[str, Any], *, reason: str) -> dict[str, Any]:
    group_id = _coerce_str(group.get("group_id"), "group_id") or "group-unknown"
    return _build_group_action(
        group=group,
        action_type="QUANTITY",
        kind="QUANTITY",
        question_id=f"{group_id}:quantity",
        user_prompt=f"How much {_group_prompt_subject(group)} is there?",
        answer_type="free_text",
        choices=[],
        allow_other=False,
        reason=reason,
    )


def _build_group_clarification_actions(
    group: Mapping[str, Any],
    *,
    group_action: str,
    gate_reason: str,
) -> list[dict[str, Any]]:
    source_origin_needed = _needs_source_origin_question(group)
    if group_action == "IDENTITY_CLARIFICATION_REQUIRED":
        actions = [_build_identity_action(group, reason=gate_reason)]
        if source_origin_needed or "ASK_SOURCE_ORIGIN" in _raw_group_actions(group):
            actions.append(_build_source_origin_action(group, reason=gate_reason))
        if "ASK_QUANTITY" in _raw_group_actions(group):
            actions.append(_build_quantity_action(group, reason=gate_reason))
        return actions
    if group_action == "AFFIRMATION_REQUIRED":
        actions = [_build_affirmation_action(group, reason=gate_reason)]
        if source_origin_needed or "ASK_SOURCE_ORIGIN" in _raw_group_actions(group):
            actions.append(_build_source_origin_action(group, reason=gate_reason))
        if "ASK_QUANTITY" in _raw_group_actions(group):
            actions.append(_build_quantity_action(group, reason=gate_reason))
        return actions
    if group_action == "ASK_QUANTITY":
        actions: list[dict[str, Any]] = []
        if source_origin_needed:
            actions.append(_build_source_origin_action(group, reason=gate_reason))
        actions.append(_build_quantity_action(group, reason=gate_reason))
        return actions
    if group_action == "ASK_SOURCE_ORIGIN":
        return [_build_source_origin_action(group, reason=gate_reason)]
    if group_action in {"ASK_CHOICE", "INTERVIEW"}:
        actions = [_build_identity_action(group, reason=gate_reason)]
        if source_origin_needed:
            actions.append(_build_source_origin_action(group, reason=gate_reason))
        return actions
    return []


def _raw_group_actions(group: Mapping[str, Any]) -> set[str]:
    raw_actions = group.get("group_actions")
    if not isinstance(raw_actions, list):
        return set()
    return {
        str(action).strip().upper()
        for action in raw_actions
        if isinstance(action, str) and str(action).strip()
    }


def _existing_actions_for_group_action(
    group: Mapping[str, Any],
    *,
    group_action: str,
    gate_reason: str,
) -> list[dict[str, Any]]:
    desired_by_action = {
        "AFFIRMATION_REQUIRED": {"AFFIRMATION"},
        "IDENTITY_CLARIFICATION_REQUIRED": {"CHOICE", "DETAIL", "FREE_TEXT", "IDENTITY"},
        "ASK_QUANTITY": {"QUANTITY"},
        "ASK_SOURCE_ORIGIN": {"SOURCE_ORIGIN"},
    }
    desired = set(desired_by_action.get(group_action, set()))
    group_actions = _raw_group_actions(group)
    if "ASK_SOURCE_ORIGIN" in group_actions:
        desired.add("SOURCE_ORIGIN")
    if "ASK_QUANTITY" in group_actions:
        desired.add("QUANTITY")
    if not desired:
        return []
    actions: list[dict[str, Any]] = []
    for action in list(group.get("clarification_actions", [])):
        if not isinstance(action, Mapping):
            continue
        action_type = (_coerce_str(action.get("type"), "type") or "").upper()
        action_kind = (_coerce_str(action.get("kind"), "kind") or "").upper()
        if action_type in desired or action_kind in desired:
            if action_type == "SOURCE_ORIGIN" or action_kind == "SOURCE_ORIGIN":
                actions.append(_build_source_origin_action(group, reason=gate_reason))
            else:
                actions.append(dict(action))
    return actions


def _clarification_actions_for_group_action(
    group: Mapping[str, Any],
    *,
    group_action: str,
    gate_reason: str,
) -> list[dict[str, Any]]:
    existing = _existing_actions_for_group_action(
        group,
        group_action=group_action,
        gate_reason=gate_reason,
    )
    if existing:
        existing_types = {
            (_coerce_str(action.get("type"), "type") or _coerce_str(action.get("kind"), "kind") or "").upper()
            for action in existing
            if isinstance(action, Mapping)
        }
        if _needs_source_origin_question(group) and "SOURCE_ORIGIN" not in existing_types:
            existing.append(_build_source_origin_action(group, reason=gate_reason))
        if "ASK_QUANTITY" in _raw_group_actions(group) and "QUANTITY" not in existing_types:
            existing.append(_build_quantity_action(group, reason=gate_reason))
        return existing
    return _build_group_clarification_actions(
        group,
        group_action=group_action,
        gate_reason=gate_reason,
    )


def _evaluate_group_gate(group: Mapping[str, Any]) -> dict[str, Any]:
    group = dict(group)
    top_three = _meaningful_top_candidates(group)
    group["top_3"] = top_three
    if not top_three:
        group["source_question_policy"] = _SOURCE_POLICY_ASK_GENERIC
        if not _coerce_str(group.get("source_trigger_reason"), "source_trigger_reason"):
            group["source_trigger_reason"] = "No embedding matches are available"
    top_one = top_three[0] if top_three else {}
    distinct_candidates = _distinct_identity_candidates(top_three)
    top_two = distinct_candidates[1] if len(distinct_candidates) > 1 else {}
    group_action = _coerce_str(group.get("group_action"), "group_action") or "NEEDS_SCHEMA_REVIEW"
    group_state = _coerce_str(group.get("group_state"), "group_state") or "NEEDS_SCHEMA_REVIEW"
    decision_rationale = _coerce_str(group.get("decision_rationale"), "decision_rationale") or "No group rationale provided"
    gate_reason = _coerce_str(group.get("gate_reason"), "gate_reason") or ""

    if group_action in {_REVIEW_STATE, _FAILED_UNCLEAR_STATE}:
        review_reason = gate_reason or "Schema review required"
        return _normalized_group_result(
            group=group,
            group_action=group_action,
            group_state=group_action,
            gate_reason=review_reason,
            decision_rationale=decision_rationale,
        )

    if group_action in {"ASK_QUANTITY", "ASK_SOURCE_ORIGIN", "ASK_CHOICE", "INTERVIEW"}:
        if group_action in {"ASK_QUANTITY", "ASK_SOURCE_ORIGIN"}:
            normalized_action = group_action
        else:
            normalized_action = "IDENTITY_CLARIFICATION_REQUIRED"
        normalized_reason = gate_reason or "Interview required"
        return _normalized_group_result(
            group=group,
            group_action=normalized_action,
            group_state=group_state if group_state in _INTERVIEW_STATES else _INTERVIEW_STATE_FROM_OUTPUT,
            gate_reason=normalized_reason,
            decision_rationale=decision_rationale,
            clarification_actions=_clarification_actions_for_group_action(
                group,
                group_action=normalized_action,
                gate_reason=normalized_reason,
            ),
        )

    if group_action == _READY_TO_WRITE_STATE:
        group_action = "AUTO_CONFIRM"

    if group_action in {"AFFIRMATION_REQUIRED", "IDENTITY_CLARIFICATION_REQUIRED"}:
        requested_reason = gate_reason or "Model requested clarification"
        return _normalized_group_result(
            group=group,
            group_action=group_action,
            group_state=_INTERVIEW_STATE_FROM_OUTPUT,
            gate_reason=requested_reason,
            decision_rationale=decision_rationale,
            clarification_actions=_clarification_actions_for_group_action(
                group,
                group_action=group_action,
                gate_reason=requested_reason,
            ),
        )

    if not top_three:
        fallback_action = (
            group_action
            if group_action in {
                "AFFIRMATION_REQUIRED",
                "IDENTITY_CLARIFICATION_REQUIRED",
                "ASK_QUANTITY",
                "ASK_SOURCE_ORIGIN",
            }
            else "AFFIRMATION_REQUIRED"
        )
        fallback_reason = gate_reason or "no usable candidate labels were available"
        return _normalized_group_result(
            group=group,
            group_action=fallback_action,
            group_state=_INTERVIEW_STATE_FROM_OUTPUT,
            gate_reason=fallback_reason,
            decision_rationale=decision_rationale,
            clarification_actions=_clarification_actions_for_group_action(
                group,
                group_action=fallback_action,
                gate_reason=fallback_reason,
            ),
        )

    reasons: list[str] = []
    threshold = _reasoning_match_threshold()
    top_identity = _candidate_score(top_one if isinstance(top_one, Mapping) else {})
    fallback_identity = _candidate_score(top_two if isinstance(top_two, Mapping) else {})
    margin = top_identity - fallback_identity
    missing_evidence = _coerce_string_list(top_one.get("missing_evidence") if isinstance(top_one, Mapping) else None)
    if not missing_evidence:
        missing_evidence = _coerce_string_list(group.get("missing_evidence"))
    nutrition_impact = _coerce_float(top_one.get("nutrition_impact"), default=0.0) if isinstance(top_one, Mapping) else 0.0
    candidate_source = (
        _coerce_str(top_one.get("source_type"), "source_type")
        or _coerce_str(top_one.get("source"), "source")
        or ""
    ).lower() if isinstance(top_one, Mapping) else ""
    food_item_id = _coerce_str(top_one.get("food_item_id"), "food_item_id") if isinstance(top_one, Mapping) else None
    learned_source_distribution = _coerce_learned_source_distribution(group.get("learned_source_distribution"))
    selected_identity = _selected_identity_metadata(group.get("selected_identity"), top_one)

    visual_only_without_learned = candidate_source in {"visual_reasoning", "user_needed"}
    learned_match_count = _learned_match_count(
        group=group,
        visual_only_without_learned=visual_only_without_learned,
    )
    dominant_source = _dominant_source_for_selected_identity(
        learned_source_distribution,
        candidate_id=selected_identity["candidate_id"],
    )

    def deterministic_source_policy(for_action: str) -> tuple[str, str]:
        if learned_match_count is not None and learned_match_count < _MIN_LEARNED_MATCHES_FOR_SOURCE_CONSENSUS:
            reason = (
                "No usable learned matches are available"
                if learned_match_count == 0
                else f"Fewer than 5 learned matches are available ({learned_match_count})"
            )
            return _SOURCE_POLICY_ASK_GENERIC, reason
        if dominant_source is not None:
            if for_action in {"IDENTITY_CLARIFICATION_REQUIRED", "ASK_CHOICE", "INTERVIEW"}:
                return (
                    _SOURCE_POLICY_DEFER_UNTIL_IDENTITY,
                    "Identity clarification must complete before applying learned source consensus",
                )
            if for_action in {"AFFIRMATION_REQUIRED", "ASK_QUANTITY"}:
                label = selected_identity["label"] or _group_prompt_subject(group)
                reason = (
                    f"Dominant learned source for {label} is "
                    f"{str(dominant_source.get('source') or '').lower()} "
                    f"({int(dominant_source.get('count') or 0)} of "
                    f"{learned_match_count or int(dominant_source.get('count') or 0)} matches)"
                )
                return _SOURCE_POLICY_ASK_AFFIRMATION, reason
        if (
            learned_match_count is not None
            and learned_match_count >= _MIN_LEARNED_MATCHES_FOR_SOURCE_CONSENSUS
            and learned_source_distribution
        ):
            return (
                _SOURCE_POLICY_ASK_GENERIC,
                f"Learned source history is ambiguous across {learned_match_count} matches",
            )
        return normalize_source_question_policy(group.get("source_question_policy")), _coerce_str(
            group.get("source_trigger_reason"),
            "source_trigger_reason",
        )

    if top_identity < threshold:
        reasons.append(f"best similarity {top_identity:.3f} is below threshold {threshold:.3f}")
    if margin < _CONFIDENCE_MARGIN:
        reasons.append(f"candidate margin {margin:.3f} is too narrow")
    if missing_evidence:
        reasons.append("missing evidence: " + ", ".join(sorted(set(missing_evidence))))
    if nutrition_impact > _NUTRITION_IMPACT_THRESHOLD and (
        reasons or _has_nutrition_relevant_missing_evidence(missing_evidence)
    ):
        reasons.append(f"nutrition impact {nutrition_impact:.3f} exceeds policy threshold")

    if reasons:
        followup_action = "ASK_QUANTITY" if _should_ask_quantity(missing_evidence) else "IDENTITY_CLARIFICATION_REQUIRED"
        followup_reason = "; ".join(reasons)
        source_question_policy, source_trigger_reason = deterministic_source_policy(followup_action)
        return _normalized_group_result(
            group=group,
            group_action=followup_action,
            group_state=_INTERVIEW_STATE_FROM_OUTPUT,
            gate_reason=followup_reason,
            decision_rationale=decision_rationale or "Needs user confirmation",
            clarification_actions=_clarification_actions_for_group_action(
                {
                    **group,
                    "source_question_policy": source_question_policy,
                },
                group_action=followup_action,
                gate_reason=followup_reason,
            ),
            source_question_policy=source_question_policy,
            source_trigger_reason=source_trigger_reason,
            learned_source_distribution=learned_source_distribution,
            selected_identity=selected_identity,
        )

    if visual_only_without_learned:
        visual_action = (
            group_action
            if group_action in {"IDENTITY_CLARIFICATION_REQUIRED", "AFFIRMATION_REQUIRED"}
            else "AFFIRMATION_REQUIRED"
        )
        if learned_match_count is not None and learned_match_count < _MIN_LEARNED_MATCHES_FOR_SOURCE_CONSENSUS:
            source_trigger_reason = (
                "No usable learned matches are available"
                if learned_match_count == 0
                else f"Fewer than 5 learned matches are available ({learned_match_count})"
            )
        else:
            source_trigger_reason = "visual-only candidate lacks learned confirmation"
        affirmation_reason = "visual-only candidate lacks learned confirmation"
        return _normalized_group_result(
            group=group,
            group_action=visual_action,
            group_state=_INTERVIEW_STATE_FROM_OUTPUT,
            gate_reason=affirmation_reason,
            decision_rationale=decision_rationale or "Needs explicit user affirmation",
            clarification_actions=_clarification_actions_for_group_action(
                {
                    **group,
                    "source_question_policy": _SOURCE_POLICY_ASK_GENERIC,
                },
                group_action=visual_action,
                gate_reason=affirmation_reason,
            ),
            source_question_policy=_SOURCE_POLICY_ASK_GENERIC,
            source_trigger_reason=source_trigger_reason,
            learned_source_distribution=learned_source_distribution,
            selected_identity=selected_identity,
        )

    if learned_match_count is not None and learned_match_count < _MIN_LEARNED_MATCHES_FOR_SOURCE_CONSENSUS:
        source_reason = (
            "No usable learned matches are available"
            if learned_match_count == 0
            else f"Fewer than 5 learned matches are available ({learned_match_count})"
        )
        return _normalized_group_result(
            group=group,
            group_action="ASK_SOURCE_ORIGIN",
            group_state=_INTERVIEW_STATE_FROM_OUTPUT,
            gate_reason=source_reason,
            decision_rationale=decision_rationale or "Needs source clarification before final write",
            clarification_actions=_clarification_actions_for_group_action(
                {
                    **group,
                    "source_question_policy": _SOURCE_POLICY_ASK_GENERIC,
                },
                group_action="ASK_SOURCE_ORIGIN",
                gate_reason=source_reason,
            ),
            source_question_policy=_SOURCE_POLICY_ASK_GENERIC,
            source_trigger_reason=source_reason,
            learned_source_distribution=learned_source_distribution,
            selected_identity=selected_identity,
        )

    if (
        learned_match_count is not None
        and learned_match_count >= _MIN_LEARNED_MATCHES_FOR_SOURCE_CONSENSUS
        and learned_source_distribution
        and dominant_source is None
    ):
        source_reason = f"Learned source history is ambiguous across {learned_match_count} matches"
        return _normalized_group_result(
            group=group,
            group_action="ASK_SOURCE_ORIGIN",
            group_state=_INTERVIEW_STATE_FROM_OUTPUT,
            gate_reason=source_reason,
            decision_rationale=decision_rationale or "Needs source clarification before final write",
            clarification_actions=_clarification_actions_for_group_action(
                {
                    **group,
                    "source_question_policy": _SOURCE_POLICY_ASK_GENERIC,
                },
                group_action="ASK_SOURCE_ORIGIN",
                gate_reason=source_reason,
            ),
            source_question_policy=_SOURCE_POLICY_ASK_GENERIC,
            source_trigger_reason=source_reason,
            learned_source_distribution=learned_source_distribution,
            selected_identity=selected_identity,
        )

    if dominant_source is not None:
        source_reason = (
            f"Dominant learned source for {selected_identity['label'] or _group_prompt_subject(group)} "
            f"is {str(dominant_source.get('source') or '').lower()} "
            f"({int(dominant_source.get('count') or 0)} of {learned_match_count or int(dominant_source.get('count') or 0)} matches)"
        )
        return _normalized_group_result(
            group=group,
            group_action="AUTO_CONFIRM_LEARNED" if food_item_id else "AUTO_CONFIRM",
            group_state=_READY_TO_WRITE_STATE,
            gate_reason=gate_reason,
            decision_rationale=decision_rationale
            if "auto-confirm" in decision_rationale.lower()
            else f"Auto-confirm pass: {decision_rationale}",
            source_question_policy=_SOURCE_POLICY_ASK_AFFIRMATION,
            source_trigger_reason=source_reason,
            learned_source_distribution=learned_source_distribution,
            selected_identity=selected_identity,
        )

    resolved_action = "AUTO_CONFIRM_LEARNED" if food_item_id else (
        group_action if group_action in {"AUTO_CONFIRM", "AUTO_CONFIRM_WITH_TRACE"} else "AUTO_CONFIRM"
    )
    resolved_rationale = (
        decision_rationale
        if "auto-confirm" in decision_rationale.lower()
        else f"Auto-confirm pass: {decision_rationale}"
    )
    return _normalized_group_result(
        group=group,
        group_action=resolved_action,
        group_state=_READY_TO_WRITE_STATE,
        gate_reason=gate_reason,
        decision_rationale=resolved_rationale,
        learned_source_distribution=learned_source_distribution,
        selected_identity=selected_identity,
    )


def _distinct_identity_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    distinct: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = _candidate_identity_key(candidate)
        if not key or key in seen:
            continue
        seen.add(key)
        distinct.append(candidate)
    return distinct


def _candidate_identity_key(candidate: Mapping[str, Any]) -> str:
    food_item_id = _coerce_str(candidate.get("food_item_id"), "food_item_id")
    if food_item_id:
        return f"food:{food_item_id}"
    label = _coerce_str(candidate.get("label"), "label")
    if label:
        return f"label:{label.casefold()}"
    candidate_id = _coerce_str(candidate.get("candidate_id"), "candidate_id")
    return f"candidate:{candidate_id}" if candidate_id else ""


def evaluate_reasoning_gate(*, reasoning_payload: Mapping[str, Any] | dict[str, Any]) -> dict[str, Any]:
    normalized = coerce_reasoning_response(reasoning_payload)
    food_groups = [
        _evaluate_group_gate(group)
        for group in list(normalized.get("food_groups", []))
        if isinstance(group, Mapping)
    ]
    segment_count = int(normalized.get("segment_count", 0))
    trace_id = normalized.get("trace_id")

    if not food_groups:
        return {
            "action": _REVIEW_STATE,
            "meal_state": _REVIEW_STATE,
            "trace_id": trace_id,
            "decision_rationale": str(normalized.get("decision_rationale") or "Missing food groups"),
            "gate_reason": str(normalized.get("gate_reason") or "Missing food groups"),
            "segment_count": segment_count,
            "food_group_count": 0,
            "food_groups": [],
        }

    if any(group["group_state"] == _FAILED_UNCLEAR_STATE for group in food_groups):
        meal_action = _FAILED_UNCLEAR_STATE
        meal_state = _FAILED_UNCLEAR_STATE
    elif any(group["group_state"] == _REVIEW_STATE for group in food_groups):
        meal_action = _REVIEW_STATE
        meal_state = _REVIEW_STATE
    else:
        unresolved_groups = [group for group in food_groups if group["group_state"] != _READY_TO_WRITE_STATE]
        if not unresolved_groups:
            meal_action = "AUTO_CONFIRM"
            meal_state = _READY_TO_WRITE_STATE
        elif len(food_groups) == 1:
            meal_action = unresolved_groups[0]["group_action"]
            meal_state = _INTERVIEW_STATE_FROM_OUTPUT
        else:
            meal_action = unresolved_groups[0]["group_action"]
            meal_state = "PARTIAL_RESOLVED_WAITING"

    meal_reasons = [
        f"{group['group_id']}: {group['gate_reason']}"
        for group in food_groups
        if group.get("gate_reason")
    ]
    meal_rationale = str(normalized.get("decision_rationale") or "")
    if not meal_rationale:
        meal_rationale = "; ".join(
            f"{group['group_id']}: {group['decision_rationale']}"
            for group in food_groups
            if group.get("decision_rationale")
        )
    if meal_action in {"AUTO_CONFIRM", "AUTO_CONFIRM_WITH_TRACE"} and "auto-confirm" not in meal_rationale.lower():
        meal_rationale = f"Auto-confirm pass: {meal_rationale}" if meal_rationale else "Auto-confirm pass"

    return {
        "action": meal_action,
        "meal_state": meal_state,
        "trace_id": trace_id,
        "decision_rationale": meal_rationale or "Grouped reasoning completed",
        "gate_reason": "; ".join(meal_reasons),
        "segment_count": segment_count,
        "food_group_count": len(food_groups),
        "food_groups": food_groups,
    }


def _normalize_top_three(result: object) -> list[dict[str, Any]]:
    if isinstance(result, Mapping):
        candidates = result.get("top_3")
    else:
        candidates = getattr(result, "top_candidates", None)
    if isinstance(candidates, list):
        return [
            dict(candidate) for candidate in candidates
            if isinstance(candidate, Mapping)
        ][:3]
    return []


def _segment_indexes_for_group(
    group: Mapping[str, Any],
    *,
    ordinal: int,
    match_results: list[tuple[MealSegment, Any]],
) -> list[int]:
    raw_indexes = group.get("segment_indexes")
    indexes: list[int] = []
    seen: set[int] = set()
    if isinstance(raw_indexes, list):
        for raw_index in raw_indexes:
            if isinstance(raw_index, bool) or not isinstance(raw_index, int):
                continue
            if raw_index < 1 or raw_index > len(match_results) or raw_index in seen:
                continue
            seen.add(raw_index)
            indexes.append(raw_index)
    if indexes:
        return indexes

    segment_ids = {
        str(segment_id).strip()
        for segment_id in list(group.get("segment_ids", []))
        if str(segment_id).strip()
    }
    primary_segment_id = _coerce_str(group.get("primary_segment_id"), "primary_segment_id")
    if primary_segment_id:
        segment_ids.add(primary_segment_id)
    if segment_ids:
        for index, (segment, _result) in enumerate(match_results, start=1):
            if str(getattr(segment, "id", f"segment-{index}")) in segment_ids:
                indexes.append(index)
        if indexes:
            return indexes

    if match_results:
        return [min(max(ordinal, 1), len(match_results))]
    return []


def _candidate_identity_key_for_snapshot(candidate: Mapping[str, Any]) -> str:
    candidate_id = _coerce_str(candidate.get("candidate_id"), "candidate_id")
    if candidate_id:
        return f"id:{candidate_id}"
    food_item_id = _coerce_str(candidate.get("food_item_id"), "food_item_id")
    if food_item_id:
        return f"food:{food_item_id}"
    label = _coerce_str(candidate.get("label"), "label")
    return f"label:{label.casefold()}" if label else ""


def _deterministic_candidates_for_indexes(
    indexes: list[int],
    match_results: list[tuple[MealSegment, Any]],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for segment_index in indexes:
        if segment_index < 1 or segment_index > len(match_results):
            continue
        _segment, result = match_results[segment_index - 1]
        if not _vector_candidates_allowed_for_reasoning(result):
            continue
        for candidate in _normalize_top_three(result):
            key = _candidate_identity_key_for_snapshot(candidate)
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            candidates.append(dict(candidate))
            if len(candidates) >= 3:
                return candidates
    return candidates[:3]


def _attach_deterministic_group_context(
    payload: Mapping[str, Any] | dict[str, Any],
    *,
    match_results: list[tuple[MealSegment, Any]],
) -> dict[str, Any]:
    normalized_payload = dict(payload)
    raw_groups = normalized_payload.get("food_groups")
    if not isinstance(raw_groups, list):
        return normalized_payload

    groups: list[dict[str, Any]] = []
    for ordinal, group in enumerate(raw_groups, start=1):
        if not isinstance(group, Mapping):
            continue
        group_payload = dict(group)
        segment_indexes = _segment_indexes_for_group(
            group_payload,
            ordinal=ordinal,
            match_results=match_results,
        )
        segment_ids = [
            str(getattr(match_results[index - 1][0], "id", f"segment-{index}"))
            for index in segment_indexes
            if 1 <= index <= len(match_results)
        ]
        if not segment_ids:
            segment_ids = [f"segment-{ordinal}"]
        top_three = _deterministic_candidates_for_indexes(segment_indexes, match_results)
        group_payload["group_id"] = f"group-{ordinal}"
        group_payload["primary_segment_id"] = segment_ids[0]
        group_payload["segment_ids"] = segment_ids
        group_payload["top_3"] = top_three
        group_payload["selected_candidate_id"] = (
            _coerce_str(top_three[0].get("candidate_id"), "candidate_id")
            if top_three
            else ""
        )
        group_payload.pop("segment_indexes", None)
        groups.append(group_payload)

    normalized_payload["food_groups"] = groups
    normalized_payload["food_group_count"] = len(groups)
    normalized_payload["segment_count"] = len(match_results)
    return normalized_payload


def _fallback_food_groups_from_match_results(
    match_results: list[tuple[MealSegment, Any]],
    *,
    meal_state: str | None = None,
    action: str | None = None,
) -> list[dict[str, Any]]:
    failure_state = (
        _FAILED_UNCLEAR_STATE
        if meal_state == _FAILED_UNCLEAR_STATE or action == _FAILED_UNCLEAR_STATE
        else _REVIEW_STATE
        if meal_state == _REVIEW_STATE or action == _REVIEW_STATE
        else None
    )
    fallback_groups: list[dict[str, Any]] = []
    for index, (segment, result) in enumerate(match_results, start=1):
        top_three = _normalize_top_three(result) if _vector_candidates_allowed_for_reasoning(result) else []
        label = _coerce_str(getattr(segment, "label", None), "label")
        if not label and top_three:
            label = _coerce_str(top_three[0].get("label"), "label")
        segment_id = str(getattr(segment, "id", f"segment-{index}"))
        selected_candidate_id = _candidate_ids(top_three)[0] if _candidate_ids(top_three) else ""
        fallback_groups.append(
            {
                "group_id": f"group-{index}",
                "group_label": label or f"food group {index}",
                "group_action": failure_state or "AUTO_CONFIRM",
                "group_state": failure_state or "READY_TO_WRITE",
                "primary_segment_id": segment_id,
                "segment_ids": [segment_id],
                "selected_candidate_id": selected_candidate_id,
                "visual_evidence": [],
                "missing_evidence": [],
                "decision_rationale": (
                    "Preserved vector candidates for review after reasoning failure"
                    if failure_state
                    else "Synthesized from segment match candidates"
                ),
                "gate_reason": (
                    "reasoning failure preserved cached candidates for review"
                    if failure_state
                    else ""
                ),
                "top_3": top_three,
            }
    )
    return fallback_groups


def _has_reasoning_eligible_match_candidates(
    match_results: list[tuple[MealSegment, Any]],
) -> bool:
    for _segment, result in match_results:
        if not _vector_candidates_allowed_for_reasoning(result):
            continue
        if _normalize_top_three(result):
            return True
    return False


def _segment_group_snapshot(
    *,
    segment_id: str,
    food_groups: list[dict[str, Any]],
    trace_id: str | None,
) -> dict[str, Any]:
    owning_group = next(
        (
            group
            for group in food_groups
            if segment_id in group.get("segment_ids", [])
            or group.get("primary_segment_id") == segment_id
        ),
        None,
    )
    if owning_group is None:
        return {
            "segment_id": segment_id,
            "group_id": None,
            "group_label": None,
            "group_action": _REVIEW_STATE,
            "group_state": _REVIEW_STATE,
            "primary_segment_id": None,
            "group_segment_ids": [],
            "selected_candidate_id": None,
            "candidate_ids": [],
            "trace_id": trace_id,
        }
    top_three = [
        dict(candidate)
        for candidate in list(owning_group.get("top_3", []))
        if isinstance(candidate, Mapping)
    ][:3]
    return {
        "segment_id": segment_id,
        "group_id": owning_group.get("group_id"),
        "group_label": owning_group.get("group_label"),
        "group_action": owning_group.get("group_action"),
        "group_state": owning_group.get("group_state"),
        "primary_segment_id": owning_group.get("primary_segment_id"),
        "group_segment_ids": list(owning_group.get("segment_ids", [])),
        "selected_candidate_id": owning_group.get("selected_candidate_id"),
        "candidate_ids": _candidate_ids(top_three),
        "trace_id": trace_id,
    }


def _resolve_image_reference(image_reference: object) -> str | None:
    if not isinstance(image_reference, str):
        return None
    reference = image_reference.strip()
    if not reference:
        return None
    if reference.startswith(("http://", "https://", "data:")):
        return reference

    image_path = Path(reference)
    if not image_path.exists() or not image_path.is_file():
        return None

    mime_type, _ = mimetypes.guess_type(image_path.name)
    raw_bytes = image_path.read_bytes()
    if mime_type in image_service.HEIC_CONTENT_TYPES:
        raw_bytes = image_service.transcode_to_jpeg(raw_bytes, mime_type or "image/heic")
        mime_type = "image/jpeg"

    encoded = base64.b64encode(raw_bytes).decode("ascii")
    return f"data:{mime_type or 'image/jpeg'};base64,{encoded}"


def _image_content_block(image_reference: object) -> dict[str, Any] | None:
    resolved = _resolve_image_reference(image_reference)
    if resolved is None:
        return None
    return {
        "type": "image_url",
        "image_url": {"url": resolved},
    }


def _stable_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))


def _candidate_prompt_snapshot(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in dict(candidate).items()
        if key
        not in {
            "candidate_id",
            "food_item_id",
            "prior_food_visual_id",
            "visual_id",
            "food_visual_id",
        }
    }


def _reasoning_system_prompt() -> str:
    taxonomy = load_reasoning_taxonomy().raw
    return f"""<role>
You are a meal-level visual nutrition reasoner for a fitness and nutrition-awareness app focused on Indo-Pak and Middle-Eastern home cooking. You receive the whole-meal photo, one cropped image per detected segment, and — when available — vector candidates from the user's learned history. Per food group you decide whether the evidence is sufficient to log nutrition or whether a short user clarification is required. Output only reasoning_contract_v1 JSON. Never expose chain-of-thought.
</role>

<taxonomy>
{_stable_json(taxonomy)}
</taxonomy>

<objective>
The downstream goal is an accurate per-group estimate of calories and macronutrients — carbohydrate, protein, fat and fiber. Resolve any uncertainty that would move those numbers; ignore uncertainty that would not. You are not naming dishes for their own sake — you are grounding nutrition. Carbohydrate and fat are the heaviest macro drivers: pin down the grain or flour grade of any staple, the identity of any starchy or look-alike vegetable, and the oil/fat richness of cooked dishes, since these dominate the calorie and macro estimate.
</objective>

<cold_start_principle>
NO_VECTOR_CANDIDATES — or only incompatible candidates (see candidate_relevance) — for a group means this food has no learned grounding. How much to ask then depends on what the food is:

- Prepared, cooked or composite items (curries, gravies, mixed dishes, cooked meat, breads, rice): visual identity alone does not ground nutrition, because calories, fat and portion swing widely with preparation. Resolve the nutrition axes below — identity and variety first, then composition and quantity wherever they are uncertain and nutrition-moving — and never AUTO_CONFIRM a visual-only, never-seen prepared dish. Under-asking on these is worse than one extra targeted question.

- Visually unambiguous whole foods (a whole fruit, a plain raw item): a "no vector" result does NOT require identity clarification. A single AFFIRMATION is enough — never offer a CHOICE here, and over-asking on obvious whole foods is needless friction. The exception is a look-alike whose nutrition differs materially — then use IDENTITY_CLARIFICATION with the nutritionally-distinct options. A choice is warranted when the alternatives differ enough in macros to matter (e.g. a starchy staple fruit vs a sugary dessert fruit, fresh vs canned/sweetened, ripe vs unripe where it shifts the sugar/starch balance). A choice is NOT warranted for minor cultivar, colour or size variants with near-identical nutrition — affirm and move on.
</cold_start_principle>

<candidate_relevance>
Vector candidates are suggestions, not ground truth — they can be stale, mismatched, or from an unrelated meal, and a high similarity score does not make an incompatible label correct. The runtime only passes vector candidates when the best similarity is strictly greater than 0.92; anything at or below 0.92 must be treated as absent learned grounding. Before using any candidate, check it is visually and categorically compatible with the crop. Discard any candidate that contradicts the visual evidence — a candidate label naming a different food category than what the crop shows is incompatible. Never present an incompatible candidate as a CHOICE option, and never ask the user to affirm a food that plainly is not what is shown. If every candidate for a group is incompatible, treat the group as having NO usable match and reason from the image alone, applying the cold_start_principle. Any ranked-candidate list (e.g. top_3) must contain only genuinely plausible candidates; if none qualify, leave it empty rather than padding it with mismatches.
</candidate_relevance>

<reasoning_axes>
Evaluate each group against these axes in order, and raise a clarification only for axes that are BOTH uncertain AND nutrition-moving:

1. IDENTITY — What is it? When two or more nutritionally-distinct foods are visually plausible for the same crop, use a CHOICE listing them by their common regional names. Typical ambiguities in this cuisine include look-alike vegetables that differ in starch and fiber, breads that differ in flour grade, and similar-looking dishes whose base or main ingredient differs. When the plausible identities span a large macro gap — for example a starchy item versus a watery low-carb one — never silently resolve to the higher-impact guess; guessing wrong here is costly, so raise the choice and keep that item as its own group rather than folding it into an adjacent staple where its identity can no longer be questioned. When the food is visually clear and only needs a yes/no, use an AFFIRMATION instead.

2. VARIETY / SUBTYPE — Once identity is known, resolve the within-item variety that changes density, macros or calories: grain type for a staple (long-grain vs short-grain vs parboiled vs wholegrain); flour grade for a bread (wholegrain vs refined); cut and leanness for a meat; fat level for a dairy item; oil or fat type when it clearly differs. Carry this under IDENTITY_CLARIFICATION_REQUIRED — there is no separate variety action — using type CHOICE / kind DETAIL. When the item's identity is obvious but its variety is the real macro driver, the variety question takes the identity slot.

3. PREPARATION — Cooking method and richness. Method materially changes fat and calories, so distinguish across the full spectrum when it is not visually obvious: deep-fried vs shallow-fried vs air-fried vs grilled vs baked/roasted vs steamed/boiled vs braised/stewed. Also capture dry vs gravy and light vs heavy oil. For any meat, always resolve cut and cooking method when they are unclear. Treat visible pooled oil or a fat sheen as a strong richness signal — let it raise a preparation or quantity question, never ignore it. A distinctly coloured or styled masala can be both an identity and a richness signal.

4. COMPOSITION — For mixed dishes (curries, gravies, mixed-veg, combination dishes) name the distinct components and flag any starchy or high-fat component, since its proportion shifts the calorie and macro balance. A seasoned, coloured or moist staple is itself ambiguous in composition: the colour and moisture may come from the staple cooked as a flavoured dish (oil and spices cooked in, e.g. a pulao or biryani style) OR from a plain staple combined at the plate with a separate curry, daal or gravy (e.g. daal-chawal or curry-rice). These differ nutritionally — the combined case hides an extra legume/curry/sauce component carrying its own oil and macros — so do not assume a single dry preparation; resolve which it is and account for any mixed-in component. Split a composite only when components are clearly distinguishable in the image.

5. QUANTITY / COUNT — Countable items (eggs, breads, fried patties, kababs or cutlets, pieces of meat, discrete portions) should have their count confirmed, and for calorie-dense items confirm it even when a count looks visible: one piece more or fewer is a large macro swing, and the photo may not show everything the user will eat. Do not skip the count just because two pieces happen to be in frame. Amorphous items (curry, gravy, rice) need a portion estimate; ask when the visible portion or scale is ambiguous. Quantity is additive (ASK_QUANTITY) and pairs with the identity action — it never replaces it.
</reasoning_axes>

<grouping>
Split distinct foods and components. Never merge bread+curry, rice+curry, sauce+bread, eggs+curry, or side-by-side dishes unless they are physically one integrated dish. Collapse multiple identical items (e.g. two of the same bread) into a single group and confirm the count there.
</grouping>

<frame_and_focus>
Log only the foods that are the subject of the shot — the items the user is presenting as this meal. The detector over-produces: it returns segments for things merely caught in frame (background clutter, a vessel from a different setting, leftovers, packaging, condiments). A detected segment is NOT a mandate to log it. Rejecting scenery is part of your job, and dropping such a segment is the correct, expected outcome — not a deviation you need to justify with a question.

Use focus and framing to decide membership. Treat a segment as out-of-scope when it is out of focus while the subject is sharp, sits at the extreme edge or is cut off by the frame, sits in a separate vessel pushed to a corner, or plainly belongs to a separate context.

Critical rule: NEVER emit a clarification question whose purpose is to find out whether an item belongs to the meal or to identify a peripheral item you cannot place. Uncertainty about membership resolves to EXCLUDE, not to ASK — asking the user "what is in that bowl in the corner?" is exactly the wrong move. If you find yourself unsure whether a segment is part of the meal, that doubt is itself the signal to drop it. To drop a segment, simply omit it from food_groups entirely: create no group, no clarification_action, and no question for it. Reserve questions for items you are confident are part of the meal.

If a peripheral segment looks like more of a dish you are already logging (e.g. a side bowl of the same curry), do not create a second mystery group for it and do not double-count — fold it into the existing dish or drop it.

Be conservative in both directions. A side dish that is fully in frame and in reasonable focus — even on a separate plate or in its own bowl — IS part of the meal; keep it. Sharpness and central framing decide membership, not plate count. If nothing is cleanly in focus, fall back to the most central, fully-framed item as the subject rather than returning no groups.
</frame_and_focus>

<decision_logic>
Per group, set group_actions from:
- AUTO_CONFIRM_LEARNED — only with a genuine learned vector/food match and no material missing evidence.
- AFFIRMATION_REQUIRED — identity visually clear, needs only Yes/No.
- IDENTITY_CLARIFICATION_REQUIRED — nutrition-relevant identity or variety/subtype alternatives exist; offer bounded label-only CHOICEs, or FREE_TEXT when open. Variety/subtype refinements ride under this action — they do not get their own action.
- AFFIRMATION_REQUIRED and IDENTITY_CLARIFICATION_REQUIRED are mutually exclusive.
- ASK_QUANTITY is additive; pair it with the identity action whenever portion or count is ungrounded per the axes above.
- FAILED_UNCLEAR — crop too poor to reason about.
</decision_logic>

<question_construction>
Each clarification_action carries the final user-facing Telegram copy. Make it one decision per question, short, plain, jargon-free, with common regional names in the choices. Set allow_other with a sensible other_label when the list may not be exhaustive. Give a one-line reason tied to nutrition.
Identity is the priority: any group whose identity is uncertain must always get its identity (or identity-equivalent variety) question first; only once identity is settled or visually clear should a quantity question follow. Order questions identity/variety -> preparation -> quantity.
Map axis to schema fields: identity choice = type CHOICE / kind IDENTITY; variety/subtype = type CHOICE / kind DETAIL; yes-no = type AFFIRMATION / kind AFFIRMATION; portion or count = type QUANTITY / kind QUANTITY; open answer = type FREE_TEXT / kind FREE_TEXT.
</question_construction>

<portion_defaults>
When a portion must be estimated, prefer the unit that fits the item: discrete units (piece, slice, serving, bowl) for countable or served items, and weight or volume for amorphous dishes. Anchor estimates to a typical home-served portion for the item type, and only raise a QUANTITY question when the visible amount or scale is genuinely ambiguous rather than inferable from the image. The taxonomy default_ranges give baseline portion priors per category.
</portion_defaults>

<output>
Return only reasoning_contract_v1 JSON matching the provided schema. Root fields only: action, meal_state, decision_rationale, gate_reason, segment_count, food_group_count, food_groups. Use the allowed action / state / type / kind enums exactly. No IDs, no fields outside the schema, no chain-of-thought.
</output>"""


def _build_reasoning_prompt(
    *,
    meal: MealLog,
    match_results: list[tuple[MealSegment, Any]],
) -> list[dict[str, Any]]:
    system_prompt = {
        "role": "system",
        "content": _reasoning_system_prompt(),
    }

    user_payload: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                "Perform one meal-level reasoning pass. "
                f"segment_count={len(match_results)}. "
                "The whole_meal_image follows first, then each indexed segment crop with "
                "its indexed vector-match context and label-only top_3_candidates. Return "
                "strict reasoning_contract_v1 JSON only."
            ),
        },
    ]

    meal_image_block = _image_content_block(getattr(meal, "image_url", None))
    if meal_image_block is not None:
        user_payload.append({"type": "text", "text": "whole_meal_image"})
        user_payload.append(meal_image_block)
    else:
        user_payload.append(
            {
                "type": "text",
                "text": f"whole_meal_image unavailable from image_url={getattr(meal, 'image_url', None)!r}",
            }
        )

    for index, (segment, match_result) in enumerate(match_results, start=1):
        raw_candidates = [
            payload
            for payload in list(getattr(match_result, "top_candidates", []) or [])
            if isinstance(payload, Mapping)
        ]
        similarity = _result_similarity(match_result)
        allow_vector_candidates = _vector_candidates_allowed_for_reasoning(match_result)
        if raw_candidates and allow_vector_candidates:
            coerced_snapshot = coerce_reasoning_response(
                {
                    "action": "AUTO_CONFIRM",
                    "meal_state": "READY_TO_WRITE",
                    "decision_rationale": "",
                    "gate_reason": "",
                    "segment_count": 1,
                    "food_group_count": 1,
                    "trace_id": "",
                    "food_groups": [
                        {
                            "group_id": f"segment-{index}-candidates",
                            "group_label": getattr(segment, "label", None) or "food",
                            "group_action": "AUTO_CONFIRM_LEARNED",
                            "group_state": "READY_TO_WRITE",
                            "primary_segment_id": str(getattr(segment, "id", f"segment-{index}")),
                            "segment_ids": [str(getattr(segment, "id", f"segment-{index}"))],
                            "selected_candidate_id": "",
                            "visual_evidence": [],
                            "missing_evidence": [],
                            "decision_rationale": "",
                            "gate_reason": "",
                            "clarification_needed": False,
                            "clarification_actions": [],
                            "question_kind": "",
                            "question_focus": "",
                            "question_examples": [],
                            "top_3": raw_candidates,
                        }
                    ],
                }
            ).get("food_groups", [{}])[0].get("top_3", [])
        else:
            coerced_snapshot = []
        segment_snapshot = [
            _candidate_prompt_snapshot(candidate)
            for candidate in coerced_snapshot
            if isinstance(candidate, Mapping)
        ][:3]
        if segment_snapshot:
            vector_match_status = "HAS_VECTOR_CANDIDATES"
            vector_match_note = "Vector candidates are available; weigh them against the image evidence."
        elif raw_candidates:
            vector_match_status = "LOW_CONFIDENCE_VECTOR_CANDIDATES_OMITTED"
            if similarity is None:
                vector_match_note = (
                    "Vector candidates existed but did not have a usable similarity score; "
                    "ignore them and reason from visual evidence."
                )
            else:
                vector_match_note = (
                    f"Vector candidates existed but best similarity {similarity:.3f} did not clear the "
                    f"reasoning gate {_reasoning_vector_candidate_min_similarity():.3f}; ignore them and "
                    "reason from visual evidence."
                )
        else:
            vector_match_status = "NO_VECTOR_CANDIDATES"
            vector_match_note = (
                "No vector candidates were available for this segment; name from visual reasoning or ask the user."
            )
        segment_payload = {
            "segment_index": f"segment_{index}",
            "vector_match_status": vector_match_status,
            "vector_match_note": vector_match_note,
            "similarity": similarity,
            "is_match": getattr(match_result, "is_match", None),
            "is_below_threshold": getattr(match_result, "is_below_threshold", None),
            "top_3_candidates": segment_snapshot,
        }
        user_payload.append(
            {
                "type": "text",
                "text": _stable_json(segment_payload),
            }
        )
        crop_block = _image_content_block(getattr(segment, "cropped_image_url", None))
        if crop_block is not None:
            user_payload.append({"type": "text", "text": f"segment_{index}_crop_image"})
            user_payload.append(crop_block)
        else:
            user_payload.append(
                {
                    "type": "text",
                    "text": (
                        f"segment_{index}_crop_image unavailable from "
                        f"cropped_image_url={getattr(segment, 'cropped_image_url', None)!r}"
                    ),
                }
            )

    return [
        system_prompt,
        {
            "role": "user",
            "content": user_payload,
        },
    ]


async def _maybe_async(value: Any) -> Any:
    result = value() if callable(value) else value
    if isawaitable(result):
        return await result
    return result


async def _run_reasoning_model(
    *,
    llm_client,
    meal: MealLog,
    match_results: list[tuple[MealSegment, Any]],
    app_settings,
) -> tuple[dict[str, Any], dict[str, int | str | None]]:
    response_format = reasoning_response_format()
    messages = _build_reasoning_prompt(meal=meal, match_results=match_results)
    trace_metadata: dict[str, int | str | None] = {"trace_id": None, "cached_tokens": None}
    reasoning_model = getattr(app_settings, "REASONING_MODEL", "google/gemini-3-flash-preview")
    fallback_model = getattr(app_settings, "REASONING_FALLBACK_MODEL", reasoning_model)
    models_to_try = [reasoning_model]
    if fallback_model and fallback_model != reasoning_model:
        models_to_try.append(fallback_model)
    extra_body = {
        "parallel_tool_calls": False,
        "reasoning": {
            "exclude": False,
        },
    }
    trace_input = {
        "meal_id": meal.id,
        "segment_count": len(match_results),
        "models": models_to_try,
        "messages": messages,
        "response_format": response_format,
        "extra_body": extra_body,
    }

    with tracing_service.maybe_start_trace(
        name="meal_reasoning",
        input=trace_input,
        metadata={"meal_id": meal.id, "models": models_to_try},
        span_name="meal_reasoning",
    ) as trace:
        last_error: Exception | None = None
        response = None
        for index, model in enumerate(models_to_try):
            try:
                response = await llm_client.chat_completion(
                    model=model,
                    messages=messages,
                    response_format=response_format,
                    extra_body=extra_body,
                )
                break
            except Exception as exc:
                last_error = exc
                if index == len(models_to_try) - 1:
                    raise
        if response is None:
            raise RuntimeError("reasoning model did not return a response") from last_error
        trace_id_from_api, cached_tokens = _extract_trace_metadata(response)
        if trace_id_from_api:
            trace_metadata["trace_id"] = trace_id_from_api
        if cached_tokens is not None:
            trace_metadata["cached_tokens"] = cached_tokens

        parsed = _parse_reasoning_message(response)
        if isinstance(parsed, Mapping):
            raw_action = _coerce_str(parsed.get("action"), "action")
            raw_meal_state = _coerce_str(parsed.get("meal_state"), "meal_state")
            deterministic_payload = _attach_deterministic_group_context(
                parsed,
                match_results=match_results,
            )
            normalized = coerce_reasoning_response(deterministic_payload)
            if not normalized.get("food_groups"):
                if raw_action:
                    normalized["_fallback_action"] = raw_action
                if raw_meal_state:
                    normalized["_fallback_meal_state"] = raw_meal_state
            normalized["trace_id"] = _normalize_trace_id_from_payload(
                normalized,
                trace_metadata,
            )
            _end_trace(
                trace,
                output={
                    "raw_response": response,
                    "parsed_response": normalized,
                }
            )
            return normalized, trace_metadata

    failed_payload = {
        "action": _FAILED_UNCLEAR_STATE,
        "meal_state": _FAILED_UNCLEAR_STATE,
        "trace_id": trace_metadata.get("trace_id"),
        "decision_rationale": "reasoning output unparseable",
        "gate_reason": "unparseable_reasoning_output",
        "segment_count": len(match_results),
        "food_group_count": 0,
        "food_groups": [],
    }
    return failed_payload, trace_metadata


async def run_reasoning_request(
    *,
    llm_client,
    meal_id: str,
    meal: MealLog,
    match_results: list[tuple[MealSegment, Any]],
    settings=None,
    propagate_errors: bool = False,
) -> tuple[dict[str, Any], dict[str, int | str | None] | None]:
    app_settings = settings or get_settings()
    try:
        parsed, trace_metadata = await _run_reasoning_model(
            llm_client=llm_client,
            meal=meal,
            match_results=match_results,
            app_settings=app_settings,
        )
    except Exception:
        if propagate_errors:
            raise
        parsed = {
            "action": _FAILED_UNCLEAR_STATE,
            "meal_state": _FAILED_UNCLEAR_STATE,
            "trace_id": None,
            "decision_rationale": "reasoning request failed",
            "gate_reason": "llm invocation error",
            "segment_count": len(match_results),
            "food_group_count": 0,
            "food_groups": [],
        }
        trace_metadata = {"trace_id": None, "cached_tokens": None}

    if not parsed.get("food_groups") and match_results:
        fallback_action = str(parsed.get("_fallback_action") or parsed.get("action") or "")
        fallback_meal_state = str(parsed.get("_fallback_meal_state") or parsed.get("meal_state") or "")
        if not _has_reasoning_eligible_match_candidates(match_results):
            fallback_action = ""
            fallback_meal_state = ""
        parsed["food_groups"] = _fallback_food_groups_from_match_results(
            match_results,
            meal_state=fallback_meal_state,
            action=fallback_action,
        )
        parsed["food_group_count"] = len(parsed["food_groups"])

    parsed = coerce_reasoning_response(parsed)
    parsed["trace_id"] = _normalize_trace_id_from_payload(
        parsed,
        trace_metadata,
    )

    decided = evaluate_reasoning_gate(reasoning_payload=parsed)
    return decided, trace_metadata


async def persist_reasoning_results(
    *,
    session,
    meal: MealLog,
    segments: list[Any],
    reasoning_payload: Mapping[str, Any] | dict[str, Any],
    persist_candidates: bool = True,
) -> dict[str, Any]:
    normalized = coerce_reasoning_response(reasoning_payload)
    food_groups = [
        dict(group)
        for group in list(normalized.get("food_groups", []))
        if isinstance(group, Mapping)
    ]

    meal_state = str(normalized.get("meal_state") or "")
    reason_state = (
        meal_state
        if meal_state == _READY_TO_WRITE_STATE or meal_state in _INTERVIEW_STATES or meal_state == _FAILED_UNCLEAR_STATE
        else _INTERVIEW_STATE_FROM_OUTPUT
        if meal_state
        else _REVIEW_STATE
    )
    if meal_state == _INTERVIEW_STATE_FROM_OUTPUT:
        reason_state = _INTERVIEW_STATE_FROM_OUTPUT

    segment_reasoning: list[dict[str, Any]] = []
    for segment in segments:
        segment_id = str(getattr(segment, "id", ""))
        segment_payload = _segment_group_snapshot(
            segment_id=segment_id,
            food_groups=food_groups,
            trace_id=_coerce_str(normalized.get("trace_id"), "trace_id"),
        )
        segment_reasoning.append(segment_payload)

        if hasattr(segment, "ai_reasoning"):
            segment.ai_reasoning = segment_payload
        if hasattr(segment, "reasoning_trace_id") and normalized.get("trace_id"):
            segment.reasoning_trace_id = normalized.get("trace_id")
        if (
            persist_candidates
            and hasattr(segment, "match_candidates_json")
            and getattr(segment, "match_candidates_json", None) is None
        ):
            owning_group = next(
                (
                    group
                    for group in food_groups
                    if segment_id in group.get("segment_ids", [])
                    or group.get("primary_segment_id") == segment_id
                ),
                None,
            )
            candidate_snapshot = list(owning_group.get("top_3", [])) if isinstance(owning_group, Mapping) else []
            segment.match_candidates_json = {
                "top_3": candidate_snapshot,
                "match_threshold": float(getattr(segment, "match_threshold", _reasoning_match_threshold())),
                "candidate_count": len(candidate_snapshot),
                "snapshot_version": 1,
            }

        if hasattr(session, "add"):
            session.add(segment)

    meal_reasoning = dict(normalized)
    meal_reasoning["meal_state"] = reason_state
    ready_for_final_write = (
        reason_state == _READY_TO_WRITE_STATE
        and normalized.get("action") in {"AUTO_CONFIRM", "AUTO_CONFIRM_WITH_TRACE", "AUTO_CONFIRM_LEARNED"}
        and all(group.get("group_state") == _READY_TO_WRITE_STATE for group in food_groups)
        and not any(normalize_source_question_policy(group.get("source_question_policy")) for group in food_groups)
    )
    if hasattr(meal, "reasoning_state_json"):
        meal.reasoning_state_json = {
            "meal_reasoning": meal_reasoning,
            "segment_reasoning": segment_reasoning,
            "ready_for_final_write": ready_for_final_write,
            "persisted_at": datetime.now(UTC).isoformat(),
        }

    if hasattr(meal, "processing_status"):
        meal.processing_status = meal.processing_status

    if hasattr(session, "add"):
        session.add(meal)
    if hasattr(session, "flush"):
        await _maybe_async(lambda: session.flush())
    if hasattr(session, "commit"):
        await _maybe_async(lambda: session.commit())

    return {
        "meal_reasoning": meal_reasoning,
        "segment_reasoning": segment_reasoning,
        "ready_for_final_write": ready_for_final_write,
        "food_groups": food_groups,
    }


def _coerce_terse_quantity_display(candidate: Mapping[str, object]) -> str:
    quantity_payload = _coerce_quantity_payload(candidate.get("quantity_payload"))
    label = _coerce_str(quantity_payload.get("quantity_label"), "quantity_label")
    if label:
        return label

    display = _coerce_str(quantity_payload.get("display"), "display")
    if display:
        return display

    portion_bucket = _normalize_portion_bucket(_coerce_str(candidate.get("portion_bucket"), "portion_bucket") or quantity_payload.get("portion_bucket"))
    return portion_bucket.title() if portion_bucket else "STANDARD"


def _coerce_quantity_json(candidate: Mapping[str, object]) -> dict[str, Any]:
    quantity_payload = _coerce_quantity_payload(candidate.get("quantity_payload"))
    quantity_json: dict[str, Any] = {
        "portion_bucket": _normalize_portion_bucket(_coerce_str(candidate.get("portion_bucket"), "portion_bucket") or quantity_payload.get("portion_bucket")),
        "quantity": _coerce_float(quantity_payload.get("quantity"), default=1.0),
        "unit": _coerce_str(quantity_payload.get("unit"), "unit"),
        "quantity_confidence": _coerce_float(candidate.get("quantity_confidence"), default=0.0),
        "identity_confidence": _coerce_float(candidate.get("identity_confidence"), default=0.0),
        "match_consistency_confidence": _coerce_float(candidate.get("match_consistency_confidence"), default=0.0),
    }
    return {key: value for key, value in quantity_json.items() if value is not None}


def _build_resolution_from_result(
    *,
    segment: MealSegment,
    result: Any,
) -> FinalSegmentResolution:
    top_one = _coerce_top_candidate(result)
    canonical_name = _coerce_str(top_one.get("label"), "label") or "unlabeled food"
    segment_embedding = getattr(segment, "embedding", None)
    food_item_id = getattr(result, "food_item_id", None) or _coerce_str(top_one.get("food_item_id"), "food_item_id")
    source_type = (
        _coerce_str(top_one.get("source_type"), "source_type")
        or _coerce_str(top_one.get("source"), "source")
        or "vector_match"
    )
    return FinalSegmentResolution(
        food=ResolvedFoodInput(
            canonical_name=canonical_name,
            food_item_id=food_item_id,
            aliases=[canonical_name],
            source_type=source_type,
            brand_name=_coerce_str(top_one.get("brand_name"), "brand_name"),
            restaurant_name=_coerce_str(top_one.get("restaurant_name"), "restaurant_name"),
            is_verified=True,
            times_confirmed=1,
        ),
        segment_id=getattr(segment, "id", None),
        segment_cropped_image_url=getattr(segment, "cropped_image_url", None),
        segment_embedding=segment_embedding if isinstance(segment_embedding, list) else None,
        portion_bucket=_normalize_portion_bucket(top_one.get("portion_bucket")),
        identification_method="AUTO_CONFIRM",
        quantity_json=_coerce_quantity_json(top_one),
        quantity_display=_coerce_terse_quantity_display(top_one),
        create_food_visual=True,
        prior_food_visual_id_to_invalidate=None,
        visual_learning_eligible=True,
        correction_reason=None,
        trace_id=_coerce_str(getattr(result, "trace_id", None), "trace_id"),
    )


def _coerce_top_candidate(result: Any) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        top_candidates = getattr(result, "top_candidates", None)
        if isinstance(top_candidates, list):
            result = {"top_3": top_candidates}
        else:
            return {}

    candidates = _normalize_top_three(result)
    if candidates:
        return candidates[0]
    return {}


def _prefer_reasoning_group_labels(food_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized_groups: list[dict[str, Any]] = []
    for group in food_groups:
        if not isinstance(group, Mapping):
            continue
        normalized_group = dict(group)
        group_label = _coerce_str(normalized_group.get("group_label"), "group_label")
        top_three = [
            dict(candidate)
            for candidate in list(normalized_group.get("top_3", []))
            if isinstance(candidate, Mapping)
        ]
        if group_label and top_three and _should_prefer_group_label(group_label, top_three[0]):
            top_three[0]["label"] = group_label
            normalized_group["top_3"] = top_three
        normalized_groups.append(normalized_group)
    return normalized_groups


def _should_prefer_group_label(group_label: str, candidate: Mapping[str, Any]) -> bool:
    candidate_label = _coerce_str(candidate.get("label"), "label")
    if not candidate_label:
        return True
    if _candidate_label_is_authoritative(candidate):
        return False
    if _word_count(candidate_label) > _word_count(group_label):
        return False
    return True


def _candidate_label_is_authoritative(candidate: Mapping[str, Any]) -> bool:
    source_type = (
        _coerce_str(candidate.get("source_type"), "source_type")
        or _coerce_str(candidate.get("source"), "source")
        or ""
    ).upper()
    if source_type not in {"HOME", "PACKAGED", "RESTAURANT"}:
        return False
    return (
        _coerce_float(candidate.get("identity_confidence")) >= 0.99
        and _coerce_float(candidate.get("match_consistency_confidence")) >= 0.99
    )


def _word_count(value: str) -> int:
    return len(re.findall(r"[A-Za-z0-9]+", value))


def _reasoning_confirmation_item(group: Mapping[str, Any]) -> dict[str, Any]:
    normalized_group = dict(group)
    top_one = _normalize_top_three(normalized_group)[0] if _normalize_top_three(normalized_group) else {}
    primary_segment_id = (
        _coerce_str(normalized_group.get("primary_segment_id"), "primary_segment_id")
        or _coerce_str(normalized_group.get("segment_id"), "segment_id")
        or "segment-unknown"
    )
    segment_ids = _coerce_string_list(normalized_group.get("segment_ids")) or [primary_segment_id]
    if primary_segment_id not in segment_ids:
        segment_ids.append(primary_segment_id)
    canonical_name = (
        _coerce_str(normalized_group.get("group_label"), "group_label")
        or _coerce_str(top_one.get("label"), "label")
        or "unlabeled food"
    )
    source_type = (
        _coerce_str(top_one.get("source_type"), "source_type")
        or _coerce_str(top_one.get("source"), "source")
        or ""
    ).upper()
    brand_name = _coerce_str(top_one.get("brand_name"), "brand_name")
    restaurant_name = _coerce_str(top_one.get("restaurant_name"), "restaurant_name")
    if source_type not in {"HOME", "PACKAGED", "RESTAURANT"}:
        if brand_name:
            source_type = "PACKAGED"
        elif restaurant_name:
            source_type = "RESTAURANT"
        else:
            source_type = "HOME"
    quantity_json = _coerce_quantity_json(top_one)
    return {
        "group_id": _coerce_str(normalized_group.get("group_id"), "group_id") or "group-unknown",
        "primary_segment_id": primary_segment_id,
        "segment_id": primary_segment_id,
        "segment_ids": segment_ids,
        "name": canonical_name,
        "source_type": source_type,
        "portion_bucket": _normalize_portion_bucket(top_one.get("portion_bucket")),
        "approval_status": "APPROVED",
        "quantity_display": _coerce_terse_quantity_display(top_one),
        "quantity_json": quantity_json,
        "food_item_id": _coerce_str(top_one.get("food_item_id"), "food_item_id"),
        "brand_name": brand_name,
        "restaurant_name": restaurant_name,
    }


async def finalize_meal_from_reasoning(
    *,
    session,
    meal: MealLog,
    segments: list[MealSegment],
    match_results: list[tuple[MealSegment, Any]],
    reasoning_payload: Mapping[str, Any] | dict[str, Any],
) -> dict[str, Any]:
    result = await persist_reasoning_results(
        session=session,
        meal=meal,
        segments=segments,
        reasoning_payload=reasoning_payload,
    )

    if not result.get("ready_for_final_write"):
        if hasattr(meal, "processing_status"):
            meal.processing_status = MealProcessingStatus.INTERVIEWING
        if hasattr(meal, "last_stage_started_at"):
            meal.last_stage_started_at = None
        if hasattr(session, "add"):
            session.add(meal)
        if hasattr(session, "commit"):
            await _maybe_async(lambda: session.commit())
        return {
            **result,
            "finalized": False,
            "completed_by": "reasoning_service",
        }

    grouped_food_groups = _prefer_reasoning_group_labels(
        [
            dict(group)
            for group in list(result.get("food_groups", []))
            if isinstance(group, Mapping)
        ]
    )
    confirmation_items = [_reasoning_confirmation_item(group) for group in grouped_food_groups]
    settings = get_settings()
    llm_client = get_llm_client()
    finalizer_inputs = _build_group_finalizer_inputs(
        meal=meal,
        confirmation_items=confirmation_items,
        interview_state=None,
        segments=segments,
    )
    finalizer_groups: list[dict[str, Any]] = []
    finalized_confirmation_items = [dict(item) for item in confirmation_items]
    if finalizer_inputs:
        finalizer_outcomes = await _run_group_finalizers(
            group_inputs=finalizer_inputs,
            llm_client=llm_client,
            settings=settings,
        )
        final_segments = [outcome.final_resolution for outcome in finalizer_outcomes]
        finalized_confirmation_items = [
            dict(outcome.finalized_confirmation_item)
            for outcome in finalizer_outcomes
        ]
        finalizer_groups = [dict(outcome.audit_state) for outcome in finalizer_outcomes]
    else:
        segments_by_id = {str(getattr(segment, "id", "")): segment for segment in segments}
        final_segments = [
            final_resolution_from_confirmation(
                item=item,
                segment=segments_by_id.get(str(item.get("segment_id"))),
                aliases=[str(item.get("name") or "unlabeled food")],
                trace_id=_coerce_str(result.get("trace_id"), "trace_id"),
            )
            for item in confirmation_items
        ]

    degraded_failure = next(
        (
            dict(group.get("grounding_failure") or {})
            for group in finalizer_groups
            if isinstance(group, Mapping) and isinstance(group.get("grounding_failure"), Mapping)
        ),
        {},
    )
    reasoning_state_json = dict(result.get("meal_reasoning") or {})
    reasoning_state_json["completed_by"] = "reasoning_service"
    reasoning_state_json["confirmation_items"] = finalized_confirmation_items
    reasoning_state_json["completed_at"] = datetime.now(UTC).isoformat()
    if finalizer_groups:
        reasoning_state_json["finalizer_groups"] = finalizer_groups
    all_finalizer_groups_degraded = _all_finalizer_groups_degraded(finalizer_groups)
    meal_status = MealProcessingStatus.COMPLETED
    final_segments_for_write = final_segments
    if all_finalizer_groups_degraded:
        meal_status = MealProcessingStatus.FAILED
        final_segments_for_write = []
        reasoning_state_json["grounding_status"] = "ALL_FINALIZER_GROUPS_DEGRADED"
        reasoning_state_json["grounding_failure"] = {
            **degraded_failure,
            "category": "all_finalizer_groups_degraded",
            "reason": "Every finalizer group degraded; no verified nutrition was saved.",
        }
    elif degraded_failure:
        reasoning_state_json["grounding_status"] = "DEGRADED_SAVED"
        reasoning_state_json["grounding_failure"] = degraded_failure

    resolved = await apply_final_meal_resolution(
        session=session,
        meal=meal,
        final_segments=final_segments_for_write,
        meal_status=meal_status,
        reasoning_state_json=reasoning_state_json,
        now=datetime.now(UTC),
    )

    if hasattr(session, "add"):
        session.add(meal)
    if hasattr(session, "commit"):
        await _maybe_async(lambda: session.commit())

    return {
        **result,
        "meal_reasoning": reasoning_state_json,
        "meal_resolution": resolved,
        "finalized": True,
        "completed_by": "reasoning_service",
    }


__all__ = [
    "evaluate_reasoning_gate",
    "run_reasoning_request",
    "persist_reasoning_results",
    "finalize_meal_from_reasoning",
    "append_grounding_trace",
]
