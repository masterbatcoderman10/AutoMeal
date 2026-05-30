from __future__ import annotations

import json
import base64
import mimetypes
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping
from inspect import isawaitable

from app.config import get_settings
from app.models import MealLog, MealSegment, MealProcessingStatus
from app.services import image_service, tracing_service
from app.services.meal_resolution_service import (
    FinalSegmentResolution,
    ResolvedFoodInput,
    apply_final_meal_resolution,
    build_grouped_final_segment_resolutions,
)
from app.services.reasoning_schema import coerce_reasoning_response, reasoning_response_format
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


def _normalized_group_result(
    *,
    group: Mapping[str, Any],
    group_action: str,
    group_state: str,
    gate_reason: str,
    decision_rationale: str,
) -> dict[str, Any]:
    top_three = [
        dict(candidate)
        for candidate in list(group.get("top_3", []))
        if isinstance(candidate, Mapping)
    ][:3]
    selected_candidate_id = _coerce_str(group.get("selected_candidate_id"), "selected_candidate_id")
    if not selected_candidate_id and top_three:
        selected_candidate_id = str(top_three[0].get("candidate_id") or "")
    return {
        "group_id": _coerce_str(group.get("group_id"), "group_id") or "group-unknown",
        "group_label": _coerce_str(group.get("group_label"), "group_label")
        or _coerce_str(group.get("label"), "label")
        or "unlabeled food group",
        "group_action": group_action,
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
        "question_kind": _coerce_str(group.get("question_kind"), "question_kind"),
        "question_focus": _coerce_str(group.get("question_focus"), "question_focus"),
        "question_examples": _coerce_string_list(group.get("question_examples")),
        "top_3": top_three,
    }


def _evaluate_group_gate(group: Mapping[str, Any]) -> dict[str, Any]:
    top_three = [
        dict(candidate)
        for candidate in list(group.get("top_3", []))
        if isinstance(candidate, Mapping)
    ][:3]
    top_one = top_three[0] if top_three else {}
    top_two = top_three[1] if len(top_three) > 1 else {}
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

    if group_action in {"ASK_QUANTITY", "ASK_CHOICE", "INTERVIEW"}:
        return _normalized_group_result(
            group=group,
            group_action=group_action,
            group_state=group_state if group_state in _INTERVIEW_STATES else _INTERVIEW_STATE_FROM_OUTPUT,
            gate_reason=gate_reason or "Interview required",
            decision_rationale=decision_rationale,
        )

    if group_action == _READY_TO_WRITE_STATE:
        group_action = "AUTO_CONFIRM"

    reasons: list[str] = []
    threshold = _reasoning_match_threshold()
    top_identity = _candidate_score(top_one if isinstance(top_one, Mapping) else {})
    fallback_identity = _candidate_score(top_two if isinstance(top_two, Mapping) else {})
    margin = top_identity - fallback_identity
    missing_evidence = _coerce_string_list(top_one.get("missing_evidence") if isinstance(top_one, Mapping) else None)
    if not missing_evidence:
        missing_evidence = _coerce_string_list(group.get("missing_evidence"))
    nutrition_impact = _coerce_float(top_one.get("nutrition_impact"), default=0.0) if isinstance(top_one, Mapping) else 0.0

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
        followup_action = "ASK_QUANTITY" if _should_ask_quantity(missing_evidence) else "ASK_CHOICE"
        return _normalized_group_result(
            group=group,
            group_action=followup_action,
            group_state=_INTERVIEW_STATE_FROM_OUTPUT,
            gate_reason="; ".join(reasons),
            decision_rationale=decision_rationale or "Needs user confirmation",
        )

    resolved_action = group_action if group_action in {"AUTO_CONFIRM", "AUTO_CONFIRM_WITH_TRACE"} else "AUTO_CONFIRM"
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
    )


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
            "top_3": [],
        }

    if any(group["group_state"] == _REVIEW_STATE for group in food_groups):
        meal_action = _REVIEW_STATE
        meal_state = _REVIEW_STATE
    else:
        unresolved_groups = [group for group in food_groups if group["group_state"] != _READY_TO_WRITE_STATE]
        if not unresolved_groups:
            meal_action = "AUTO_CONFIRM"
            meal_state = _READY_TO_WRITE_STATE
        elif len(unresolved_groups) == len(food_groups):
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
        "top_3": list(food_groups[0].get("top_3", [])),
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


def _fallback_food_groups_from_match_results(
    match_results: list[tuple[MealSegment, Any]],
) -> list[dict[str, Any]]:
    fallback_groups: list[dict[str, Any]] = []
    for index, (segment, result) in enumerate(match_results, start=1):
        top_three = _normalize_top_three(result)
        label = _coerce_str(getattr(segment, "label", None), "label")
        if not label and top_three:
            label = _coerce_str(top_three[0].get("label"), "label")
        segment_id = str(getattr(segment, "id", f"segment-{index}"))
        selected_candidate_id = _candidate_ids(top_three)[0] if _candidate_ids(top_three) else ""
        fallback_groups.append(
            {
                "group_id": f"group-{index}",
                "group_label": label or f"food group {index}",
                "group_action": "AUTO_CONFIRM",
                "group_state": "READY_TO_WRITE",
                "primary_segment_id": segment_id,
                "segment_ids": [segment_id],
                "selected_candidate_id": selected_candidate_id,
                "visual_evidence": [],
                "missing_evidence": [],
                "decision_rationale": "Synthesized from segment match candidates",
                "gate_reason": "",
                "top_3": top_three,
            }
        )
    return fallback_groups


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


def _reasoning_system_prompt() -> str:
    taxonomy = load_reasoning_taxonomy().raw
    return (
        "<CRITICAL_RULES>\n"
        "You are MealTracker's meal-level visual reasoning model. You must inspect the "
        "whole_meal_image and every indexed segment crop before trusting vector candidates. "
        "Base decisions only on the provided images, detector labels, boxes, and per-segment "
        "top_3 candidate context. First group distinct foods/components, then rank candidates "
        "inside each group only. Do not compare unrelated foods as if they are alternatives. "
        "Do not invent ingredients, brands, nutrition facts, or hidden details. Output strict "
        "JSON only.\n"
        "</CRITICAL_RULES>\n\n"
        "<SPECIFICITY_POLICY>\n"
        "Asian-cuisine specificity matters. For rice, noodles, breads, curries, wraps, "
        "meat pieces, sauces, and mixed dishes, capture visible nutrition-relevant detail: "
        "rice/prep type, noodle style, bread type, filling, protein or vegetable inside a "
        "curry, meat cut, oiliness, sauce load, and whether visible components should stay "
        "together or split. If a nutrition-relevant detail is not visible, mark it as "
        "missing_evidence instead of guessing.\n"
        "</SPECIFICITY_POLICY>\n\n"
        "<TAXONOMY_POLICY>\n"
        "Use this editable policy as guidance, not as a source of facts:\n"
        f"{_stable_json(taxonomy)}\n\n"
        "</TAXONOMY_POLICY>\n\n"
        "<ACTION_POLICY>\n"
        "- AUTO_CONFIRM only when every meaningful visible segment has image evidence "
        "supporting the top candidate, the top candidate is clearly separated from "
        "alternatives, and missing evidence would not materially change nutrition.\n"
        "- ASK_CHOICE when there are plausible named alternatives and the user can pick "
        "quickly from top candidates plus all-wrong.\n"
        "- INTERVIEW when the missing identity/detail is open-ended, especially hidden "
        "curry vegetables/proteins, sandwich or roll fillings, unclear meat cuts, or "
        "mixed-dish components.\n"
        "- ASK_QUANTITY only after identity/detail is good enough but visible portion "
        "evidence is weak and likely nutrition impact is high.\n"
        "- NEEDS_GROUNDING when packaged/restaurant nutrition data is needed; Phase 4 "
        "does not use web tools.\n"
        "- FAILED_UNCLEAR when the visual evidence is unusable even for a targeted "
        "question. NEEDS_SCHEMA_REVIEW is only for schema/contract problems.\n\n"
        "Ranking policy: return exactly three top_3 records inside every food group, ranked "
        "by visual specificity, DB/vector match signal, whole-meal context, nutrition-impact "
        "clarity, and uncertainty honesty. Generic fallback candidates are allowed only when "
        "labeled as uncertainty candidates with low confidence and clear missing_evidence.\n\n"
        "</ACTION_POLICY>\n\n"
        "<EXAMPLES>\n"
        "Example 1 - unclear curry detail: whole meal shows pita and a curry crop; "
        "candidate labels include chicken curry and egg curry with vegetables. Create a "
        "food_group for the curry and another for the bread. If the curry visibly contains "
        "egg but the vegetable inside is unclear and changes nutrition, set that group's "
        "group_action=INTERVIEW or ASK_CHOICE, group_state=PENDING_INTERVIEW, "
        "top_3[0].missing_evidence includes `vegetable inside curry`, and do not "
        "auto-confirm the curry group.\n"
        "Example 2 - clear simple side: whole meal and crop clearly show pita bread; "
        "the bread group's top-1 is pita bread with a strong margin, no hidden filling, "
        "and no meaningful missing detail. group_action=AUTO_CONFIRM is acceptable; "
        "visual_evidence should mention the crop and whole-meal support.\n"
        "Example 3 - portion only: identity is clear as rice, but depth/amount is unclear "
        "and likely changes calories. Use ASK_QUANTITY only if identity detail is already "
        "good enough; missing_evidence should name portion_unit or serving_size.\n"
        "</EXAMPLES>\n\n"
        "<OUTPUT_CONTRACT>\n"
        "Return only strict JSON matching reasoning_contract_v1. All declared fields are "
        "required, including trace_id, gate_reason, segment_count, food_group_count, and "
        "food_groups. Every food_group must include group_id, group_label, group_action, "
        "group_state, primary_segment_id, segment_ids, selected_candidate_id, visible "
        "evidence, missing evidence, gate reason, decision rationale, question_kind, "
        "question_focus, question_examples, and exactly three "
        "top_3 records with nutrition_impact on every candidate. meal_state must be exactly "
        "one of READY_TO_WRITE, PENDING_CHOICE, PENDING_INTERVIEW, PARTIAL_RESOLVED_WAITING, "
        "FAILED_UNCLEAR, or NEEDS_SCHEMA_REVIEW. Use READY_TO_WRITE only when every group is "
        "AUTO_CONFIRM. Use trace_id=\"\" if no provider trace is supplied. Do not expose "
        "hidden chain-of-thought.\n"
        "</OUTPUT_CONTRACT>"
    )


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
                f"Meal {meal.id}: perform one meal-level reasoning pass. "
                f"segment_count={len(match_results)}. "
                "The whole_meal_image follows first, then each indexed segment crop with "
                "its detector hint, bounding_box, and top_3_candidates. Return the "
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
        coerced_snapshot = coerce_reasoning_response(
            {
                "action": "AUTO_CONFIRM",
                "meal_state": "READY_TO_WRITE",
                "top_3": [payload for payload in getattr(match_result, "top_candidates", [])],
                "decision_rationale": "",
                "gate_reason": "",
                "segment_count": 1,
                "trace_id": "",
            }
        ).get("top_3", [])
        segment_snapshot = [
            dict(candidate)
            for candidate in coerced_snapshot
            if isinstance(candidate, Mapping)
        ][:3]
        segment_payload = {
            "segment_index": f"segment_{index}",
            "segment_id": getattr(segment, "id", "unknown"),
            "detector_label": getattr(segment, "label", None),
            "bounding_box": getattr(segment, "bounding_box", None),
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


async def _run_reasoning_parser_retry(
    *,
    llm_client,
    app_settings,
    response_payload: Mapping[str, Any] | dict[str, Any],
) -> dict[str, Any] | None:
    parser_model = getattr(app_settings, "REASONING_PARSER_MODEL", "google/gemini-3.1-flash-lite")
    fallback_model = getattr(app_settings, "REASONING_PARSER_FALLBACK_MODEL", parser_model)
    repair_messages = [
        {
            "role": "system",
            "content": (
                "Repair this model output into strict JSON matching the reasoning contract. "
                "The contract requires fields: action, meal_state, trace_id, decision_rationale, "
                "gate_reason, segment_count, food_group_count, and food_groups with exactly "
                "three top_3 candidates per group. Return only JSON."
            ),
        },
        {
            "role": "assistant",
            "content": json.dumps(response_payload),
        },
    ]

    models_to_try = [parser_model]
    if fallback_model and fallback_model != parser_model:
        models_to_try.append(fallback_model)

    for index, model in enumerate(models_to_try):
        try:
            repaired = await llm_client.chat_completion(
                model=model,
                messages=repair_messages,
                response_format=reasoning_response_format(),
                max_tokens=2200,
            )
        except Exception:
            if index == len(models_to_try) - 1:
                raise
            continue
        parsed = _parse_reasoning_message(repaired)
        if parsed is not None:
            return parsed
    return None


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
    reasoning_model = getattr(app_settings, "REASONING_MODEL", "google/gemini-3.5-flash")
    fallback_model = getattr(app_settings, "REASONING_FALLBACK_MODEL", reasoning_model)
    models_to_try = [reasoning_model]
    if fallback_model and fallback_model != reasoning_model:
        models_to_try.append(fallback_model)
    extra_body = {
        "parallel_tool_calls": False,
        "reasoning": {
            "max_tokens": 512,
            "exclude": True,
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
                    max_tokens=4096,
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
            normalized = coerce_reasoning_response(parsed)
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

        parsed_for_retry = _safe_parse_json(json.dumps(response, default=str))
        if parsed_for_retry is not None:
            repaired_payload = await _run_reasoning_parser_retry(
                llm_client=llm_client,
                app_settings=app_settings,
                response_payload=parsed_for_retry,
            )
            if isinstance(repaired_payload, Mapping):
                trace_id_from_repair, repair_cached_tokens = _extract_trace_metadata(repaired_payload)
                if trace_id_from_repair and not trace_metadata["trace_id"]:
                    trace_metadata["trace_id"] = trace_id_from_repair
                if repair_cached_tokens is not None and not trace_metadata["cached_tokens"]:
                    trace_metadata["cached_tokens"] = repair_cached_tokens
                normalized = coerce_reasoning_response(repaired_payload)
                normalized["trace_id"] = _normalize_trace_id_from_payload(
                    normalized,
                    trace_metadata,
                )
                _end_trace(
                    trace,
                    output={
                        "raw_response": response,
                        "repair_response": repaired_payload,
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
        parsed["food_groups"] = _fallback_food_groups_from_match_results(match_results)
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
    top_three = normalized.get("top_3", [])

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
            candidate_snapshot = list(owning_group.get("top_3", [])) if isinstance(owning_group, Mapping) else top_three
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
        and normalized.get("action") in {"AUTO_CONFIRM", "AUTO_CONFIRM_WITH_TRACE"}
        and all(group.get("group_state") == _READY_TO_WRITE_STATE for group in food_groups)
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
        "top_3": top_three,
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
        if group_label and top_three:
            top_three[0]["label"] = group_label
            normalized_group["top_3"] = top_three
        normalized_groups.append(normalized_group)
    return normalized_groups


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
    final_segments = build_grouped_final_segment_resolutions(
        food_groups=grouped_food_groups,
        segments=segments,
        match_results=match_results,
        trace_id=_coerce_str(result.get("trace_id"), "trace_id"),
    )
    if not final_segments:
        final_segments = []
        for segment in segments:
            result_match = next((match for seg, match in match_results if seg.id == segment.id), None)
            if result_match is None:
                result_match = result
            final_segments.append(_build_resolution_from_result(segment=segment, result=result_match))

    resolved = await apply_final_meal_resolution(
        session=session,
        meal=meal,
        final_segments=final_segments,
        meal_status=MealProcessingStatus.COMPLETED,
        reasoning_state_json=result.get("meal_reasoning"),
        now=datetime.now(UTC),
    )

    if hasattr(session, "add"):
        session.add(meal)
    if hasattr(session, "commit"):
        await _maybe_async(lambda: session.commit())

    return {
        **result,
        "meal_resolution": resolved,
        "finalized": True,
        "completed_by": "reasoning_service",
    }


__all__ = [
    "evaluate_reasoning_gate",
    "run_reasoning_request",
    "persist_reasoning_results",
    "finalize_meal_from_reasoning",
]
