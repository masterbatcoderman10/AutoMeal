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

    with tracing_service.maybe_start_trace(
        name="interview_turn",
        input={
            "authoritative_state": authoritative_state,
            "transcript": list(transcript[-6:]),
            "latest_user_text": latest_user_text,
            "active_group_ids": active_group_ids,
        },
        metadata={"meal_id": authoritative_state.get("meal_id"), "active_group_ids": active_group_ids},
        span_name="interview_turn",
    ):
        response = await _run_chat_completion(
            llm=llm,
            models=_models_to_try(app_settings),
            messages=_build_turn_messages(
                authoritative_state=authoritative_state,
                transcript=transcript,
                latest_user_text=latest_user_text,
            ),
        )
        try:
            return parse_interview_turn_response_payload(
                response,
                active_group_ids=active_group_ids,
            )
        except InterviewTurnValidationError as exc:
            repair_response = await _run_repair_completion(
                llm=llm,
                models=_models_to_try(app_settings),
                authoritative_state=authoritative_state,
                transcript=transcript,
                latest_user_text=latest_user_text,
                raw_response=response,
                validation_error=exc,
            )
            return parse_interview_turn_response_payload(
                repair_response,
                active_group_ids=active_group_ids,
            )


async def _run_chat_completion(
    *,
    llm: Any,
    models: Sequence[str],
    messages: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    last_error: Exception | None = None
    for index, model in enumerate(models):
        try:
            return await llm.chat_completion(
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
) -> Mapping[str, Any]:
    repair_messages = [
        {
            "role": "system",
            "content": (
                "Repair this interview turn into strict JSON. "
                "Choose exactly one turn_action: continue_interview, need_clarification, or ready_to_confirm. "
                "If you choose ready_to_confirm, include one confirmation item for every active group id in the authoritative state. "
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
                "Fail closed instead of guessing when the user's reply is insufficient."
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
