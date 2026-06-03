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
    resolver_only = _resolver_only(authoritative_state)
    remaining_required_question_ids = _remaining_required_question_ids(authoritative_state)
    if resolver_only and remaining_required_question_ids:
        raise InterviewTurnValidationError(
            "final resolver cannot run before remaining required clarification questions are answered"
        )
    active_group_ids = _active_group_ids(authoritative_state)
    models_to_try = _models_to_try(app_settings)
    bounded_transcript = list(transcript[-6:])
    messages = _build_turn_messages(
        authoritative_state=authoritative_state,
        transcript=transcript,
        latest_user_text=latest_user_text,
        resolver_only=resolver_only,
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
            "resolver_only": resolver_only,
            "remaining_required_question_ids": remaining_required_question_ids,
            "clarification_answers": authoritative_state.get("answers_by_question_id") or {},
            "messages": messages,
            "response_format": interview_turn_response_format(),
        },
        metadata={
            "meal_id": authoritative_state.get("meal_id"),
            "active_group_ids": active_group_ids,
            "models": models_to_try,
            "resolver_only": resolver_only,
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
                resolver_only=resolver_only,
            )
            normalized = _with_authoritative_segment_ids(result, authoritative_state)
            _validate_ready_to_confirm_evidence(
                normalized,
                authoritative_state=authoritative_state,
                transcript=transcript,
                latest_user_text=latest_user_text,
            )
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
                    resolver_only=resolver_only,
                )
                normalized = _with_authoritative_segment_ids(repaired, authoritative_state)
                _validate_ready_to_confirm_evidence(
                    normalized,
                    authoritative_state=authoritative_state,
                    transcript=transcript,
                    latest_user_text=latest_user_text,
                )
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
                "Choose exactly one turn_action: ready_to_confirm. "
                "The deterministic clarification step is already complete, so you must not ask a follow-up question. "
                "Use the authoritative grouped reasoning, structured clarification answers, and prior confirmations "
                "to normalize the final meal into confirmation_items only. "
                "Include one confirmation item for every active group id in the authoritative state. "
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


_COMMON_EVIDENCE_WORDS = {
    "and",
    "are",
    "curry",
    "food",
    "for",
    "item",
    "meal",
    "the",
    "this",
    "with",
}


def _validate_ready_to_confirm_evidence(
    result: InterviewTurnResult,
    *,
    authoritative_state: Mapping[str, Any],
    transcript: Sequence[Mapping[str, Any]],
    latest_user_text: str,
) -> None:
    if result.turn_action != "ready_to_confirm":
        return

    user_evidence_text = _combined_user_evidence_text(
        authoritative_state=authoritative_state,
        transcript=transcript,
        latest_user_text=latest_user_text,
    )
    broad_confirmation = _has_broad_confirmation(user_evidence_text)
    items_by_group = {item.group_id: item for item in result.confirmation_items}
    answered_group_ids = _answered_group_ids(authoritative_state)

    for target in authoritative_state.get("unresolved_targets") or []:
        if not isinstance(target, Mapping):
            continue
        group_id = str(target.get("group_id") or "").strip()
        if not group_id:
            continue
        item = items_by_group.get(group_id)
        if item is None:
            continue
        if group_id in answered_group_ids:
            continue
        if not _item_has_user_evidence(item, target, user_evidence_text):
            raise InterviewTurnValidationError(
                f"ready_to_confirm lacks explicit user evidence for unresolved group {group_id}"
            )

    for candidate in authoritative_state.get("approval_candidates") or []:
        if not isinstance(candidate, Mapping):
            continue
        group_id = str(candidate.get("group_id") or "").strip()
        if not group_id:
            continue
        item = items_by_group.get(group_id)
        if item is None:
            continue
        if group_id in answered_group_ids:
            continue
        if item.approval_status == "APPROVED":
            if broad_confirmation or _mentions_candidate(candidate, user_evidence_text):
                continue
            raise InterviewTurnValidationError(
                f"ready_to_confirm approved group {group_id} without explicit user confirmation"
            )
        if item.approval_status == "CORRECTED" and not _item_has_user_evidence(item, candidate, user_evidence_text):
            raise InterviewTurnValidationError(
                f"ready_to_confirm corrected group {group_id} without explicit user evidence"
            )


def _answered_group_ids(authoritative_state: Mapping[str, Any]) -> set[str]:
    answers = authoritative_state.get("answers_by_question_id")
    if not isinstance(answers, Mapping):
        return set()
    group_ids: set[str] = set()
    for answer in answers.values():
        if not isinstance(answer, Mapping):
            continue
        group_id = str(answer.get("group_id") or "").strip()
        if group_id:
            group_ids.add(group_id)
    return group_ids


def _combined_user_evidence_text(
    *,
    authoritative_state: Mapping[str, Any],
    transcript: Sequence[Mapping[str, Any]],
    latest_user_text: str,
) -> str:
    pieces: list[str] = []
    for collection in (authoritative_state.get("interview_messages") or [], transcript):
        for message in collection:
            if not isinstance(message, Mapping):
                continue
            if str(message.get("role") or "").strip() != "user":
                continue
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                pieces.append(content.strip())
    if latest_user_text.strip():
        pieces.append(latest_user_text.strip())
    return "\n".join(pieces).casefold()


def _has_broad_confirmation(normalized_user_text: str) -> bool:
    return any(
        phrase in normalized_user_text
        for phrase in (
            "all good",
            "all correct",
            "all right",
            "both are right",
            "everything is correct",
            "everything is right",
            "everything else",
            "rest is correct",
            "rest is right",
            "the rest",
            "these are correct",
            "these are right",
            "they are right",
            "those are right",
            "yes to both",
            "yes for both",
            "yes these are correct",
            "yes those are correct",
        )
    )


def _item_has_user_evidence(
    item: Any,
    state_item: Mapping[str, Any],
    normalized_user_text: str,
) -> bool:
    item_tokens = _meaningful_tokens(getattr(item, "name", ""))
    prior_tokens = set()
    for key in ("label", "group_label", "proposed_name"):
        prior_tokens.update(_meaningful_tokens(state_item.get(key)))
    evidence_tokens = item_tokens - prior_tokens
    if not evidence_tokens:
        evidence_tokens = item_tokens
    return any(token in normalized_user_text for token in evidence_tokens)


def _mentions_candidate(candidate: Mapping[str, Any], normalized_user_text: str) -> bool:
    tokens = set()
    for key in ("proposed_name", "label", "group_label"):
        tokens.update(_meaningful_tokens(candidate.get(key)))
    for choice in candidate.get("candidate_choices") or []:
        tokens.update(_meaningful_tokens(choice))
    return any(token in normalized_user_text for token in tokens)


def _meaningful_tokens(value: object) -> set[str]:
    raw = str(value or "").casefold()
    tokens: set[str] = set()
    current = []
    for char in raw:
        if char.isalnum():
            current.append(char)
            continue
        if current:
            token = "".join(current)
            if len(token) >= 3 and token not in _COMMON_EVIDENCE_WORDS:
                tokens.add(token)
            current = []
    if current:
        token = "".join(current)
        if len(token) >= 3 and token not in _COMMON_EVIDENCE_WORDS:
            tokens.add(token)
    return tokens


def _build_turn_messages(
    *,
    authoritative_state: Mapping[str, Any],
    transcript: Sequence[Mapping[str, Any]],
    latest_user_text: str,
    resolver_only: bool,
) -> list[dict[str, Any]]:
    instruction = (
        "You are MealTracker's interview turn manager. "
        "Use the authoritative meal state to resolve natural-language food clarification replies. "
        "Return strict JSON only. Ask concise follow-ups. "
        "Do not invent nutrition facts. Do not write database state. "
        "Fail closed instead of guessing when the user's reply is insufficient. "
        "Use ready_to_confirm only when the user's replies explicitly answer each unresolved group "
        "and explicitly confirm or correct each approval candidate. Otherwise ask one concise follow-up. "
        "For ready_to_confirm, copy each active group's segment_ids into its confirmation item."
    )
    if resolver_only:
        instruction = (
            "You are MealTracker's final resolver. "
            "The deterministic clarification step is already complete. "
            "You must not ask user-facing follow-up questions or request more information. "
            "Use the authoritative grouped reasoning, structured clarification answers, and prior confirmations "
            "to emit strict JSON with turn_action=ready_to_confirm and one confirmation item per active group. "
            "Do not invent nutrition facts. Do not write database state. "
            "Copy each active group's segment_ids into its confirmation item."
        )
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": instruction,
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


def _resolver_only(authoritative_state: Mapping[str, Any]) -> bool:
    return isinstance(authoritative_state.get("questions_by_id"), Mapping) and isinstance(
        authoritative_state.get("question_order"),
        list,
    )


def _remaining_required_question_ids(authoritative_state: Mapping[str, Any]) -> list[str]:
    return [
        str(question_id)
        for question_id in authoritative_state.get("remaining_required_question_ids") or []
        if str(question_id).strip()
    ]


__all__ = ["InterviewTurnValidationError", "run_interview_turn"]
