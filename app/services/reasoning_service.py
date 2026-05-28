from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Mapping
from inspect import isawaitable

from app.config import get_settings
from app.models import MealLog, MealSegment, MealProcessingStatus
from app.services import tracing_service
from app.services.meal_resolution_service import (
    FinalSegmentResolution,
    ResolvedFoodInput,
    apply_final_meal_resolution,
)
from app.services.reasoning_schema import coerce_reasoning_response, reasoning_response_format

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


def _should_ask_quantity(missing_evidence: list[str]) -> bool:
    if not missing_evidence:
        return False
    needle = {"portion", "portion_unit", "serving_size", "serving_unit", "quantity"}
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


def evaluate_reasoning_gate(*, reasoning_payload: Mapping[str, Any] | dict[str, Any]) -> dict[str, Any]:
    normalized = coerce_reasoning_response(reasoning_payload)
    top_three = list(normalized.get("top_3", []))
    top_one = top_three[0] if top_three else {}
    top_two = top_three[1] if len(top_three) > 1 else {}
    action = str(normalized.get("action") or "")
    meal_state = str(normalized.get("meal_state") or "")
    decision_rationale = str(normalized.get("decision_rationale") or "")
    gate_reason = str(normalized.get("gate_reason") or "")
    segment_count = int(normalized.get("segment_count", 0))

    if action in {_REVIEW_STATE, _FAILED_UNCLEAR_STATE}:
        return {
            "action": action,
            "meal_state": action,
            "top_3": top_three,
            "trace_id": normalized.get("trace_id"),
            "decision_rationale": decision_rationale or "Schema review required",
            "gate_reason": gate_reason or "Schema review required",
            "segment_count": segment_count,
        }

    if action in {"ASK_QUANTITY", "ASK_CHOICE", "INTERVIEW"}:
        normalized_state = meal_state if meal_state in _INTERVIEW_STATES else _INTERVIEW_STATE_FROM_OUTPUT
        return {
            "action": action,
            "meal_state": normalized_state,
            "top_3": top_three,
            "trace_id": normalized.get("trace_id"),
            "decision_rationale": decision_rationale or "User follow-up requested",
            "gate_reason": gate_reason or "Interview required",
            "segment_count": segment_count,
        }

    if action == _READY_TO_WRITE_STATE:
        action = "AUTO_CONFIRM"

    reasons: list[str] = []
    threshold = _reasoning_match_threshold()
    top_identity = _candidate_score(top_one if isinstance(top_one, Mapping) else {})
    fallback_identity = _candidate_score(top_two if isinstance(top_two, Mapping) else {})
    margin = top_identity - fallback_identity
    missing_evidence = _coerce_string_list(top_one.get("missing_evidence") if isinstance(top_one, Mapping) else None)
    nutrition_impact = _coerce_float(top_one.get("nutrition_impact"), default=0.0) if isinstance(top_one, Mapping) else 0.0

    if top_identity < threshold:
        reasons.append(f"best similarity {top_identity:.3f} is below threshold {threshold:.3f}")
    if margin < _CONFIDENCE_MARGIN:
        reasons.append(f"candidate margin {margin:.3f} is too narrow")
    if missing_evidence:
        reasons.append("missing evidence: " + ", ".join(sorted(set(missing_evidence))))
    if nutrition_impact > _NUTRITION_IMPACT_THRESHOLD:
        reasons.append(f"nutrition impact {nutrition_impact:.3f} exceeds policy threshold")

    if reasons:
        followup_action = "ASK_QUANTITY" if _should_ask_quantity(missing_evidence) else "ASK_CHOICE"
        return {
            "action": followup_action,
            "meal_state": meal_state if meal_state in _INTERVIEW_STATES else _INTERVIEW_STATE_FROM_OUTPUT,
            "top_3": top_three,
            "trace_id": normalized.get("trace_id"),
            "decision_rationale": decision_rationale or "Needs user confirmation",
            "gate_reason": "; ".join(reasons),
            "segment_count": segment_count,
        }

    return {
        "action": action if action in {"AUTO_CONFIRM", "AUTO_CONFIRM_WITH_TRACE"} else "AUTO_CONFIRM",
        "meal_state": _READY_TO_WRITE_STATE,
        "top_3": top_three,
        "trace_id": normalized.get("trace_id"),
        "decision_rationale": (
            decision_rationale
            if "auto-confirm" in decision_rationale.lower()
            else f"Auto-confirm pass: {decision_rationale}"
        )
        if decision_rationale
        else "Auto-confirm pass",
        "gate_reason": gate_reason,
        "segment_count": segment_count,
    }


def _normalize_top_three(result: object) -> list[dict[str, Any]]:
    if isinstance(result, Mapping):
        candidates = result.get("top_3")
        if isinstance(candidates, list):
            return [
                candidate for candidate in candidates
                if isinstance(candidate, Mapping)
            ][:3]
    return []


def _build_reasoning_prompt(
    *,
    meal: MealLog,
    match_results: list[tuple[MealSegment, Any]],
) -> list[dict[str, Any]]:
    segment_lines: list[str] = []
    for segment, match_result in match_results:
        segment_snapshot = _normalize_top_three(
            coerce_reasoning_response(
                {
                    "action": "AUTO_CONFIRM",
                    "meal_state": "READY_TO_WRITE",
                    "top_3": [payload for payload in getattr(match_result, "top_candidates", [])],
                    "decision_rationale": "",
                    "gate_reason": "",
                    "segment_count": 1,
                    "trace_id": None,
                }
            ).get("top_3", [])
        )
        segment_lines.append(
            f"segment_id={getattr(segment, 'id', 'unknown')}; candidates={json.dumps(segment_snapshot, sort_keys=True)}"
        )

    system_prompt = {
        "role": "system",
        "content": (
            "You are a meal reasoning model for a personal meal tracker. "
            "Return strict JSON with keys action, meal_state, top_3, decision_rationale, gate_reason, "
            "segment_count and optional trace_id. Choose one meal-level action."
        ),
    }

    user_payload: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                f"Meal {meal.id}: perform meal-level reasoning from segment snapshots. "
                f"segment_count={len(match_results)}. "
                "Return auto-confirm only when top candidates are confident and complete. "
                "Ask follow-up when confidence or evidence is weak."
                "\nSegments:\n" + "\n".join(segment_lines)
            ),
        },
    ]

    if getattr(meal, "image_url", None):
        image_url = str(meal.image_url)
        if image_url.startswith(("http://", "https://", "data:")):
            user_payload.append(
                {
                    "type": "image_url",
                    "image_url": {"url": image_url},
                },
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
                "The contract requires fields: action, meal_state, top_3, decision_rationale, gate_reason, segment_count, "
                "and optional trace_id. Return only JSON."
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
                response_format={"type": "json_object"},
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

    with tracing_service.maybe_start_trace(
        name="meal_reasoning",
        input={"meal_id": meal.id, "segment_count": len(match_results)},
        metadata={"meal_id": meal.id},
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
                    extra_body={"parallel_tool_calls": False},
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
                return normalized, trace_metadata

    return {
        "action": _FAILED_UNCLEAR_STATE,
        "meal_state": _FAILED_UNCLEAR_STATE,
        "top_3": [],
        "trace_id": trace_metadata.get("trace_id"),
        "decision_rationale": "reasoning output unparseable",
        "gate_reason": "unparseable_reasoning_output",
        "segment_count": len(match_results),
    }, trace_metadata


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
            "top_3": [],
            "trace_id": None,
            "decision_rationale": "reasoning request failed",
            "gate_reason": "llm invocation error",
            "segment_count": len(match_results),
        }
        trace_metadata = {"trace_id": None, "cached_tokens": None}

    if not parsed.get("top_3") and match_results:
        first_result = match_results[0][1]
        parsed_top_three = _normalize_top_three(first_result)
        parsed["top_3"] = parsed_top_three[:3]

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
        segment_payload = {
            "segment_id": getattr(segment, "id", None),
            "action": normalized.get("action"),
            "meal_state": reason_state,
            "trace_id": normalized.get("trace_id"),
            "top_3": top_three,
            "decision_rationale": normalized.get("decision_rationale"),
            "gate_reason": normalized.get("gate_reason"),
            "segment_count": normalized.get("segment_count", 0),
        }
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
                segment.match_candidates_json = {
                    "top_3": top_three,
                    "match_threshold": float(
                    getattr(segment, "match_threshold", _reasoning_match_threshold())
                ),
                    "candidate_count": len(top_three),
                    "snapshot_version": 1,
                }

        if hasattr(session, "add"):
            session.add(segment)

    meal_reasoning = dict(normalized)
    meal_reasoning["meal_state"] = reason_state
    ready_for_final_write = (
        reason_state == _READY_TO_WRITE_STATE
        and normalized.get("action") in {"AUTO_CONFIRM", "AUTO_CONFIRM_WITH_TRACE"}
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

    final_segments: list[FinalSegmentResolution] = []
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
