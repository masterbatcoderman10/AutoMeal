from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

from app.config import get_settings
from app.services import tracing_service
from app.services.interview_schema import (
    InterviewTurnResult,
    InterviewTurnValidationError,
    interview_turn_response_format,
    parse_interview_turn_response_payload,
)
from app.services.llm_client import get_llm_client


def _fallback_settings() -> SimpleNamespace:
    return SimpleNamespace(
        INTERVIEW_MODEL="google/gemini-3.1-flash-lite",
        INTERVIEW_FALLBACK_MODEL="google/gemini-3-flash-preview",
    )


def _resolve_settings(settings: Any | None) -> Any:
    if settings is not None:
        return settings
    try:
        return get_settings()
    except Exception:
        return _fallback_settings()


async def run_interview_turn(
    *,
    authoritative_state: Mapping[str, Any],
    transcript: Sequence[Mapping[str, Any]],
    latest_user_text: str,
    settings: Any | None = None,
    llm_client: Any | None = None,
) -> InterviewTurnResult:
    app_settings = _resolve_settings(settings)
    llm = llm_client or get_llm_client()
    active_group_ids = _active_group_ids(authoritative_state)
    models_to_try = _models_to_try(app_settings)
    bounded_transcript = list(transcript[-6:])
    messages = _build_turn_messages(
        authoritative_state=authoritative_state,
        transcript=transcript,
        latest_user_text=latest_user_text,
    )

    with tracing_service.maybe_start_trace(
        name="interview_turn",
        input={
            "meal_id": authoritative_state.get("meal_id"),
            "models": models_to_try,
            "authoritative_state": authoritative_state,
            "transcript": bounded_transcript,
            "latest_user_text": latest_user_text,
            "active_group_ids": active_group_ids,
            "messages": messages,
            "response_format": interview_turn_response_format(),
        },
        metadata={
            "meal_id": authoritative_state.get("meal_id"),
            "active_group_ids": active_group_ids,
            "models": models_to_try,
        },
        span_name="interview_turn",
    ) as trace:
        response, selected_model = await _run_chat_completion(
            llm=llm,
            models=models_to_try,
            messages=messages,
        )
        try:
            result = parse_interview_turn_response_payload(
                response,
                active_group_ids=active_group_ids,
            )
            normalized = _with_authoritative_segment_ids(result, authoritative_state)
            _end_trace(
                trace,
                output={
                    "selected_model": selected_model,
                    "raw_response": response,
                    "repair_model": None,
                    "repair_response": None,
                    "parsed_response": normalized.model_dump(mode="json"),
                },
            )
            return normalized
        except InterviewTurnValidationError as exc:
            repair_response, repair_model = await _run_repair_completion(
                llm=llm,
                models=models_to_try,
                authoritative_state=authoritative_state,
                transcript=transcript,
                latest_user_text=latest_user_text,
                raw_response=response,
                validation_error=exc,
            )
            try:
                repaired = parse_interview_turn_response_payload(
                    repair_response,
                    active_group_ids=active_group_ids,
                )
                normalized = _with_authoritative_segment_ids(repaired, authoritative_state)
                _end_trace(
                    trace,
                    output={
                        "selected_model": selected_model,
                        "raw_response": response,
                        "repair_model": repair_model,
                        "repair_response": repair_response,
                        "parsed_response": normalized.model_dump(mode="json"),
                    },
                )
                return normalized
            except InterviewTurnValidationError as repair_exc:
                _end_trace(
                    trace,
                    output={
                        "selected_model": selected_model,
                        "raw_response": response,
                        "repair_model": repair_model,
                        "repair_response": repair_response,
                        "parsed_response": None,
                        "validation_error": str(exc),
                        "repair_validation_error": str(repair_exc),
                    },
                )
                raise


async def _run_chat_completion(
    *,
    llm: Any,
    models: Sequence[str],
    messages: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], str]:
    last_error: Exception | None = None
    for index, model in enumerate(models):
        try:
            response = await llm.chat_completion(
                model=model,
                messages=[dict(message) for message in messages],
                response_format=interview_turn_response_format(),
                extra_body={
                    "parallel_tool_calls": False,
                    "reasoning": {
                        "max_tokens": 256,
                        "exclude": True,
                    },
                },
                max_tokens=1600,
            )
            return response, model
        except Exception as exc:
            last_error = exc
            if index == len(models) - 1:
                raise
    raise RuntimeError("interview model did not return a response") from last_error


async def _run_repair_completion(
    *,
    llm: Any,
    models: Sequence[str],
    authoritative_state: Mapping[str, Any],
    transcript: Sequence[Mapping[str, Any]],
    latest_user_text: str,
    raw_response: Mapping[str, Any],
    validation_error: Exception,
) -> tuple[Mapping[str, Any], str]:
    repair_messages = [
        {
            "role": "system",
            "content": (
                "Repair this interview turn into strict JSON. "
                "Choose exactly one turn_action: continue_interview, need_clarification, or ready_to_confirm. "
                "If you choose ready_to_confirm, include one confirmation item for every active group id in the authoritative state. "
                "Each confirmation item must include segment_ids copied from that active group. "
                "Do not invent nutrition facts or mutate state. Return JSON only."
            ),
        },
        {
            "role": "system",
            "content": "AUTHORITATIVE_STATE_JSON:\n"
            + json.dumps(authoritative_state, ensure_ascii=True, separators=(",", ":"), default=str),
        },
        {
            "role": "system",
            "content": "RECENT_TRANSCRIPT_JSON:\n"
            + json.dumps(list(transcript[-6:]), ensure_ascii=True, separators=(",", ":"), default=str),
        },
        {"role": "system", "content": f"LATEST_USER_TEXT:\n{latest_user_text.strip()}"},
        {"role": "system", "content": f"VALIDATION_ERROR:\n{validation_error}"},
        {"role": "assistant", "content": json.dumps(raw_response, ensure_ascii=True, separators=(",", ":"), default=str)},
    ]
    return await _run_chat_completion(
        llm=llm,
        models=models,
        messages=repair_messages,
    )


def _end_trace(trace: Any, *, output: Mapping[str, Any] | dict[str, Any]) -> None:
    end = getattr(trace, "end", None)
    if callable(end):
        end(output=dict(output))


def _models_to_try(app_settings: Any) -> list[str]:
    primary = str(getattr(app_settings, "INTERVIEW_MODEL", "google/gemini-3.1-flash-lite"))
    fallback = str(getattr(app_settings, "INTERVIEW_FALLBACK_MODEL", primary))
    models = [primary]
    if fallback and fallback != primary:
        models.append(fallback)
    return models


def _active_group_ids(authoritative_state: Mapping[str, Any]) -> list[str]:
    group_ids: list[str] = []
    for key in ("unresolved_targets", "approval_candidates"):
        for item in authoritative_state.get(key) or []:
            if not isinstance(item, Mapping):
                continue
            group_id = str(item.get("group_id") or "").strip()
            if group_id and group_id not in group_ids:
                group_ids.append(group_id)
    return group_ids


def _active_group_segment_ids(authoritative_state: Mapping[str, Any]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for key in ("unresolved_targets", "approval_candidates"):
        for item in authoritative_state.get(key) or []:
            if not isinstance(item, Mapping):
                continue
            group_id = str(item.get("group_id") or "").strip()
            if not group_id:
                continue
            segment_ids: list[str] = []
            raw_segment_ids = item.get("segment_ids")
            if isinstance(raw_segment_ids, list):
                for raw_segment_id in raw_segment_ids:
                    segment_id = str(raw_segment_id or "").strip()
                    if segment_id and segment_id not in segment_ids:
                        segment_ids.append(segment_id)
            for field_name in ("primary_segment_id", "segment_id"):
                segment_id = str(item.get(field_name) or "").strip()
                if segment_id and segment_id not in segment_ids:
                    segment_ids.append(segment_id)
            if segment_ids:
                current = groups.setdefault(group_id, [])
                for segment_id in segment_ids:
                    if segment_id not in current:
                        current.append(segment_id)
    return groups


def _with_authoritative_segment_ids(
    result: InterviewTurnResult,
    authoritative_state: Mapping[str, Any],
) -> InterviewTurnResult:
    if result.turn_action != "ready_to_confirm":
        return result
    group_segment_ids = _active_group_segment_ids(authoritative_state)
    if not group_segment_ids:
        return result

    confirmation_items = []
    for item in result.confirmation_items:
        segment_ids = list(item.segment_ids)
        for segment_id in group_segment_ids.get(item.group_id, []):
            if segment_id not in segment_ids:
                segment_ids.append(segment_id)
        confirmation_items.append(item.model_copy(update={"segment_ids": segment_ids}))
    return result.model_copy(update={"confirmation_items": confirmation_items})


def _build_turn_messages(
    *,
    authoritative_state: Mapping[str, Any],
    transcript: Sequence[Mapping[str, Any]],
    latest_user_text: str,
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "You are MealTracker's interview turn manager. "
                "Use the authoritative meal state to resolve natural-language food clarification replies. "
                "Return strict JSON only. Ask concise follow-ups. "
                "Do not invent nutrition facts. Do not write database state. "
                "Fail closed instead of guessing when the user's reply is insufficient. "
                "For ready_to_confirm, copy each active group's segment_ids into its confirmation item."
            ),
        },
        {
            "role": "system",
            "content": "AUTHORITATIVE_STATE_JSON:\n"
            + json.dumps(authoritative_state, ensure_ascii=True, separators=(",", ":"), default=str),
        },
    ]
    for message in list(transcript)[-6:]:
        role = str(message.get("role") or "").strip()
        content = message.get("content")
        if role not in {"system", "user", "assistant"}:
            continue
        if not isinstance(content, str) or not content.strip():
            continue
        messages.append({"role": role, "content": content.strip()})
    messages.append({"role": "user", "content": latest_user_text.strip()})
    return messages


__all__ = ["InterviewTurnValidationError", "run_interview_turn"]
