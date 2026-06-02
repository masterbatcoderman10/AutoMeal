from __future__ import annotations

import asyncio
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Mapping

from sqlalchemy import select

from app.config import get_settings
from app.models import DiaryEntry, InterviewMessage, InterviewSession, MealLog, MealProcessingStatus, MealSegment
from app.services.grounding_stub import build_grounding_prep, normalize_source_type
from app.services.interview_schema import (
    FinalizedGroupResult,
    group_finalizer_response_format,
    parse_group_finalizer_response_payload,
)
from app.services.llm_client import get_llm_client
from app.services.meal_resolution_service import (
    FinalSegmentResolution,
    ResolvedFoodInput,
    apply_final_meal_resolution,
)


INTERVIEW_ROADMAP = (
    "INITIAL_QUESTION",
    "FOOD_NAME",
    "SOURCE_TYPE",
    "BRAND_NAME",
    "RESTAURANT_NAME",
    "PORTION_CONTEXT",
    "CONFIRMATION",
)

SESSION_MODE_MEAL = "MEAL_INTERVIEW"
SESSION_MODE_FIX = "ENTRY_FIX"
FINALIZER_MAX_ATTEMPTS = 2
FINALIZER_MAX_TOKENS = 1200


@dataclass(frozen=True)
class InterviewAnswer:
    segment_id: str | None
    name: str
    source_type: str = "HOME"
    portion_bucket: str = "STANDARD"
    quantity_display: str | None = None
    brand_name: str | None = None
    restaurant_name: str | None = None
    food_item_id: str | None = None
    evidence: str | None = None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "InterviewAnswer":
        return cls(
            segment_id=_optional_text(payload.get("segment_id")),
            name=_text(payload.get("name") or payload.get("canonical_name") or payload.get("value"), default="Unknown food"),
            source_type=normalize_source_type(payload.get("source_type")),
            portion_bucket=_portion_bucket(payload.get("portion_bucket")),
            quantity_display=_optional_text(payload.get("quantity_display") or payload.get("quantity_text")),
            brand_name=_optional_text(payload.get("brand_name")),
            restaurant_name=_optional_text(payload.get("restaurant_name")),
            food_item_id=_optional_text(payload.get("food_item_id")),
            evidence=_optional_text(payload.get("evidence")),
        )


@dataclass(frozen=True)
class GroupFinalizerInput:
    group_id: str
    primary_segment_id: str
    segment_ids: list[str]
    confirmation_item: dict[str, Any]
    group_state: dict[str, Any]
    clarification_answers: list[dict[str, Any]]
    segment: MealSegment | None
    segment_ref: dict[str, Any]
    trace_id: str | None = None


@dataclass(frozen=True)
class GroupFinalizerOutcome:
    group_id: str
    final_resolution: FinalSegmentResolution
    finalized_confirmation_item: dict[str, Any]
    audit_state: dict[str, Any]


def get_interview_roadmap() -> list[str]:
    return list(INTERVIEW_ROADMAP)


def is_pinned_chat_update(callback: object, session: object) -> bool:
    chat = getattr(getattr(callback, "message", None), "chat", None)
    return str(getattr(chat, "id", "")) == str(getattr(session, "chat_id", ""))


def current_target_question(state: Mapping[str, Any]) -> dict[str, Any]:
    if has_deterministic_question_state(state):
        question = _current_clarification_question(state)
        if question is None:
            return {
                "roadmap_step": "CONFIRMATION",
                "prompt": "Confirm or correct the identified meal items.",
                "invalid_prompt": "Confirm or correct the identified meal items.",
                "session_mode": str(state.get("session_mode") or SESSION_MODE_MEAL),
            }
        prompt, invalid_prompt = _render_clarification_question(question)
        prompt_payload = dict(question)
        prompt_payload.update(
            {
                "segment_id": _optional_text(question.get("primary_segment_id")) or _first_segment_id(question.get("segment_ids")),
                "roadmap_step": "QUESTION_BATCH",
                "prompt": prompt,
                "invalid_prompt": invalid_prompt,
                "session_mode": str(state.get("session_mode") or SESSION_MODE_MEAL),
                "pending_question_ids": list(state.get("pending_question_ids") or []),
                "remaining_required_question_ids": list(state.get("remaining_required_question_ids") or []),
            }
        )
        return prompt_payload

    target = _current_target(state)
    step = str(state.get("roadmap_step") or "INITIAL_QUESTION")
    answer = _answer_record_for_state(state, target)
    label = _optional_text(answer.get("name")) or _optional_text(target.get("label")) or "this item"
    mode = str(state.get("session_mode") or SESSION_MODE_MEAL)

    prompt, invalid_prompt = _render_initial_question(
        target=target,
        label=label,
    )

    if step == "FOOD_NAME":
        current_name = _optional_text(answer.get("name"))
        if mode == SESSION_MODE_FIX and current_name:
            prompt = (
                f"What exact name should I log for {label}? "
                "You can include the style, filling, bread type, or main ingredient if that helps. "
                f"Reply with the corrected name, or `same` to keep `{current_name}`."
            )
        else:
            prompt = (
                f"What should I call {label}? "
                "You can include the style, filling, bread type, or main ingredient if that helps. "
                "Examples: `egg curry with bottle gourd`, `pita bread`, `chicken leg curry`."
            )
        invalid_prompt = prompt
    elif step == "SOURCE_TYPE":
        current_source = normalize_source_type(answer.get("source_type"))
        prompt = "Was it homemade, packaged, or from a restaurant?"
        if mode == SESSION_MODE_FIX:
            prompt = (
                f"{prompt} Reply `same` to keep `{current_source.lower()}`."
            )
        invalid_prompt = "Reply with `home`, `packaged`, or `restaurant`."
    elif step == "BRAND_NAME":
        current_brand = _optional_text(answer.get("brand_name"))
        prompt = f"What brand should I attach to {label}? Say `unknown` if you don't know."
        if mode == SESSION_MODE_FIX and current_brand:
            prompt = (
                f"{prompt} Reply `same` to keep `{current_brand}`."
            )
        invalid_prompt = prompt
    elif step == "RESTAURANT_NAME":
        current_restaurant = _optional_text(answer.get("restaurant_name"))
        prompt = f"What restaurant should I attach to {label}? Say `unknown` if you don't know."
        if mode == SESSION_MODE_FIX and current_restaurant:
            prompt = (
                f"{prompt} Reply `same` to keep `{current_restaurant}`."
            )
        invalid_prompt = prompt
    elif step == "PORTION_CONTEXT":
        current_bucket = _portion_bucket(answer.get("portion_bucket"))
        quantity_hint = _optional_text(answer.get("quantity_display"))
        prompt = (
            "Was it a small, standard, or large portion? Add the most natural short unit if helpful, "
            "for example `small bowl`, `2 pieces`, `half plate`, or `1 cup`."
        )
        if mode == SESSION_MODE_FIX:
            kept = quantity_hint or current_bucket.lower()
            prompt = f"{prompt} Reply `same` to keep `{kept}`."
        invalid_prompt = "Reply with `small`, `standard`, or `large`, plus any short context if useful."

    prompt_payload = dict(target)
    prompt_payload.update(
        {
            "segment_id": _target_segment_id(target),
            "roadmap_step": step,
            "prompt": prompt,
            "invalid_prompt": invalid_prompt,
            "current_name": _optional_text(answer.get("name")),
            "current_source_type": normalize_source_type(answer.get("source_type")),
            "current_brand_name": _optional_text(answer.get("brand_name")),
            "current_restaurant_name": _optional_text(answer.get("restaurant_name")),
            "current_portion_bucket": _portion_bucket(answer.get("portion_bucket")),
            "current_quantity_display": _optional_text(answer.get("quantity_display")),
            "session_mode": mode,
        }
    )
    return prompt_payload


def complete_target_question(state: Mapping[str, Any], answer: Mapping[str, Any]) -> dict[str, Any]:
    if has_deterministic_question_state(state):
        return _apply_clarification_answer(state, answer)

    updated = dict(state)
    messages = list(updated.get("interview_messages") or [])
    messages.append({"role": "user", "payload": dict(answer)})
    updated["interview_messages"] = messages

    target = _current_target(updated)
    segment_id = str(answer.get("segment_id") or _target_segment_id(target) or "")
    answers = [dict(item) for item in updated.get("answers_by_segment") or []]
    record = _answer_record_for_state(updated, target)
    record["segment_id"] = segment_id or record.get("segment_id")
    record["label"] = _optional_text(record.get("label")) or _optional_text(target.get("label"))

    step = str(answer.get("roadmap_step") or updated.get("roadmap_step") or "INITIAL_QUESTION")
    if step in {"INITIAL_QUESTION", "FOOD_NAME"}:
        record["name"] = _text(answer.get("name"), default=_text(record.get("name"), default="Unknown food"))
    elif step == "SOURCE_TYPE":
        record["source_type"] = normalize_source_type(answer.get("source_type"))
    elif step == "BRAND_NAME":
        record["brand_name"] = _optional_text(answer.get("brand_name"))
    elif step == "RESTAURANT_NAME":
        record["restaurant_name"] = _optional_text(answer.get("restaurant_name"))
    elif step == "PORTION_CONTEXT":
        record["portion_bucket"] = _portion_bucket(answer.get("portion_bucket"))
        record["quantity_display"] = _optional_text(answer.get("quantity_display"))

    answers = [item for item in answers if not _answer_matches_target(item, target)]
    answers.append(record)
    updated["answers_by_segment"] = answers

    current_index = _safe_int(updated.get("current_target_index"), default=0)
    targets = list(updated.get("pending_targets") or [])
    next_step = _next_roadmap_step(record=record, step=step)
    if next_step is None:
        next_index = current_index + 1
        if next_index >= len(targets):
            updated["current_target_index"] = len(targets)
            updated["roadmap_step"] = "CONFIRMATION"
            updated["confirmation_items"] = confirmation_items_from_state(updated)
        else:
            updated["current_target_index"] = next_index
            updated["roadmap_step"] = _initial_roadmap_step_for_target(targets[next_index])
    else:
        updated["roadmap_step"] = next_step
    return updated


def parse_interview_text(*, text: str, context: Mapping[str, Any]) -> dict[str, Any]:
    if _optional_text(context.get("question_id")):
        return _parse_clarification_text(text=text, context=context)

    cleaned = _clean_identity_text(text)
    step = str(context.get("roadmap_step") or "INITIAL_QUESTION")
    payload: dict[str, Any] = {
        "segment_id": context.get("segment_id"),
        "roadmap_step": step,
        "value": cleaned,
        "fallback": True,
        "raw_text": str(text or "").strip(),
    }
    if step in {"INITIAL_QUESTION", "FOOD_NAME"}:
        payload["name"] = _keep_or_clean_name(cleaned, context=context)
        return payload
    if step == "SOURCE_TYPE":
        if _is_keep_current_text(cleaned):
            payload["source_type"] = normalize_source_type(context.get("current_source_type"))
            return payload
        source_type = _parse_source_type(text)
        if source_type is None:
            payload["invalid"] = True
            return payload
        payload["source_type"] = source_type
        return payload
    if step == "BRAND_NAME":
        payload["brand_name"] = _keep_or_optional_text(cleaned, current=context.get("current_brand_name"))
        return payload
    if step == "RESTAURANT_NAME":
        payload["restaurant_name"] = _keep_or_optional_text(cleaned, current=context.get("current_restaurant_name"))
        return payload
    if step == "PORTION_CONTEXT":
        if _is_keep_current_text(cleaned):
            payload["portion_bucket"] = _portion_bucket(context.get("current_portion_bucket"))
            payload["quantity_display"] = _optional_text(context.get("current_quantity_display"))
            return payload
        payload["portion_bucket"] = _infer_portion_bucket(text)
        payload["quantity_display"] = _optional_text(str(text or "").strip())
        return payload
    return payload


def should_send_single_reminder(
    interview_state: Mapping[str, Any],
    *,
    now: datetime,
    reminder_delay_minutes: int,
) -> bool:
    if interview_state.get("last_reminder_at") is not None:
        return False
    prompted_at = _coerce_datetime(interview_state.get("last_prompted_at"))
    if not isinstance(prompted_at, datetime):
        return False
    return now - prompted_at >= timedelta(minutes=reminder_delay_minutes)


def build_best_effort_closeout(unresolved: Mapping[str, Any]) -> dict[str, Any]:
    unresolved_items = list(unresolved.get("unresolved_items") or [])
    return {
        "meal_id": unresolved.get("meal_id"),
        "best_effort": True,
        "unresolved_count": len(unresolved_items),
        "items": unresolved_items,
        "processing_status": "INTERVIEWING",
        "is_verified": False,
    }


def apply_confirmation_edits(
    confirmation_items: list[Mapping[str, Any]],
    edit_payload: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    edits_by_segment = {
        str(edit.get("segment_id")): dict(edit)
        for edit in edit_payload
        if edit.get("segment_id") is not None
    }
    updated: list[dict[str, Any]] = []
    for item in confirmation_items:
        next_item = dict(item)
        original_name = next_item.get("name")
        edit = edits_by_segment.get(str(next_item.get("segment_id")))
        if edit:
            next_item.update({key: value for key, value in edit.items() if value is not None})
            if original_name and next_item.get("name") != original_name:
                next_item["previous_name"] = original_name
        updated.append(next_item)
    return updated


def parse_confirmation_bulk_text(
    *,
    text: str,
    confirmation_items: list[Mapping[str, Any]],
) -> dict[str, Any]:
    if not _looks_like_confirmation_edit(text=text, confirmation_count=len(confirmation_items)):
        return {"applied_bulk": False, "updates": []}

    parts = re.split(r"\s*,\s*|\s+and\s+|\s+second\s+is\s+", text, flags=re.IGNORECASE)
    cleaned_parts = [_clean_identity_text(part) for part in parts if _clean_identity_text(part)]
    if len(cleaned_parts) < len(confirmation_items) and "second is" in text.lower():
        first, second = re.split(r"\bsecond\s+is\b", text, maxsplit=1, flags=re.IGNORECASE)
        cleaned_parts = [_clean_identity_text(first), _clean_identity_text(second)]

    updates: list[dict[str, Any]] = []
    for item, name in zip(confirmation_items, cleaned_parts, strict=False):
        updates.append({"segment_id": item.get("segment_id"), "name": name})
    return {"applied_bulk": bool(updates), "updates": updates}


def _looks_like_confirmation_edit(*, text: str, confirmation_count: int) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    if re.search(
        r"\b(first|second|third|fourth|fifth|sixth|item\s*\d+|\d+(?:st|nd|rd|th)?)\s+(?:is|=|:)\b",
        normalized,
        flags=re.IGNORECASE,
    ):
        return True
    parts = [
        _clean_identity_text(part)
        for part in re.split(r"\s*,\s*|\s+and\s+", normalized, flags=re.IGNORECASE)
    ]
    meaningful_parts = [part for part in parts if part]
    return confirmation_count > 1 and len(meaningful_parts) == confirmation_count


def build_confirmation_message(confirmation_items: list[Mapping[str, Any]]) -> str:
    lines = ["Updated confirmation:"]
    for item in confirmation_items:
        segment_id = item.get("segment_id")
        name = item.get("name") or "Unknown food"
        previous = item.get("previous_name")
        if previous and previous != name:
            lines.append(f"{segment_id}: {previous} -> {name}")
        else:
            lines.append(f"{segment_id}: {name}")
    lines.append("Confirm or edit before I log this.")
    return "\n".join(lines)


def build_all_wrong_prompt(*, segment: Mapping[str, Any], evidence: str | None = None) -> str:
    segment_id = segment.get("segment_id") or segment.get("id") or "this item"
    label = segment.get("label") or "unknown item"
    prefix = f"{segment_id}: I had this as {label}."
    if evidence:
        evidence_text = str(evidence).strip()
        if evidence_text.lower().startswith(("i see", "i only see")):
            prefix += f" {evidence_text}."
        else:
            prefix += f" I see {evidence_text}."
    return f"{prefix} What should I call it instead?"


def answer_to_confirmation_item(answer: Mapping[str, Any]) -> dict[str, Any]:
    parsed = InterviewAnswer.from_mapping(answer)
    item = {
        "group_id": _optional_text(answer.get("group_id")),
        "primary_segment_id": _optional_text(answer.get("primary_segment_id")),
        "segment_ids": list(answer.get("segment_ids") or []) if isinstance(answer.get("segment_ids"), list) else None,
        "segment_id": parsed.segment_id,
        "entry_id": _optional_text(answer.get("entry_id")),
        "name": parsed.name,
        "source_type": parsed.source_type,
        "portion_bucket": parsed.portion_bucket,
        "quantity_display": parsed.quantity_display,
        "brand_name": parsed.brand_name,
        "restaurant_name": parsed.restaurant_name,
        "food_item_id": parsed.food_item_id,
        "original_name": _optional_text(answer.get("original_name")),
        "grounding_prep": build_grounding_prep(dict(answer)),
    }
    return {key: value for key, value in item.items() if value is not None}


def confirmation_items_from_state(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    explicit_items = state.get("confirmation_items")
    if isinstance(explicit_items, list) and explicit_items:
        return [dict(item) for item in explicit_items if isinstance(item, Mapping)]

    if has_deterministic_question_state(state):
        items = _confirmation_items_from_clarification_answers(state)
        if items:
            return items

    items: list[dict[str, Any]] = []
    for target in list(state.get("pending_targets") or []):
        answer = _answer_for_target(state, target)
        if answer is None:
            continue
        items.append(answer_to_confirmation_item(answer))
    if items:
        return items

    legacy_items: list[dict[str, Any]] = []
    for message in state.get("interview_messages") or []:
        payload = message.get("payload") if isinstance(message, dict) else None
        if isinstance(payload, dict):
            legacy_items.append(answer_to_confirmation_item(payload))
    return legacy_items


def interview_transcript_from_state(state: Mapping[str, Any]) -> list[dict[str, str]]:
    transcript: list[dict[str, str]] = []
    for message in state.get("interview_messages") or []:
        if not isinstance(message, Mapping):
            continue
        role = _transcript_role(message.get("role"))
        if role is None:
            continue
        content = _optional_text(message.get("content")) or _transcript_content_from_payload(
            role=role,
            payload=message.get("payload"),
        )
        if not content:
            continue
        transcript.append({"role": role, "content": content})
    return transcript


def append_interview_transcript_entry(
    state: Mapping[str, Any],
    *,
    role: str,
    content: str,
    payload: Mapping[str, Any] | None = None,
    message_id: int | None = None,
) -> dict[str, Any]:
    updated = dict(state)
    messages = [dict(item) for item in updated.get("interview_messages") or [] if isinstance(item, Mapping)]
    entry: dict[str, Any] = {
        "role": role,
        "content": content.strip(),
        "payload": dict(payload or {}),
    }
    if message_id is not None:
        entry["message_id"] = message_id
    messages.append(entry)
    updated["interview_messages"] = messages
    return updated


def apply_interview_turn_result(
    state: Mapping[str, Any],
    *,
    turn_action: str,
    assistant_prompt: str,
    clarification_reason: str | None = None,
    conversation_summary: str | None = None,
    confirmation_items: list[Mapping[str, Any]] | None = None,
    resolver_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    updated = dict(state)
    if conversation_summary:
        updated["conversation_summary"] = conversation_summary
    updated["last_turn_action"] = turn_action

    if turn_action == "ready_to_confirm":
        items = [dict(item) for item in confirmation_items or [] if isinstance(item, Mapping)]
        updated["roadmap_step"] = "CONFIRMATION"
        updated["current_target_index"] = len(list(updated.get("pending_targets") or []))
        updated["confirmation_items"] = items
        updated["answers_by_segment"] = [dict(item) for item in items]
        if isinstance(resolver_payload, Mapping):
            updated["resolver_payload"] = {
                str(key): _json_safe_payload(value)
                for key, value in resolver_payload.items()
            }
    else:
        question = dict(updated.get("current_question") or {})
        question["prompt"] = assistant_prompt
        question["invalid_prompt"] = assistant_prompt
        question["session_mode"] = str(updated.get("session_mode") or SESSION_MODE_MEAL)
        question["roadmap_step"] = str(updated.get("roadmap_step") or "INITIAL_QUESTION")
        if clarification_reason:
            question["clarification_reason"] = clarification_reason
        updated["current_question"] = question

    return updated


def build_neutral_retry_prompt(state: Mapping[str, Any]) -> str:
    question = dict(state.get("current_question") or {})
    prompt = _optional_text(question.get("prompt"))
    if prompt:
        return (
            "I couldn't safely apply that answer yet. "
            f"Please answer the same meal question again: {prompt}"
        )
    return "I couldn't safely apply that answer yet. Please answer the same meal question again."


def json_safe_payload(value: object) -> Any:
    return _json_safe_payload(value)


def build_interview_turn_state(
    *,
    meal: MealLog,
    segments: list[MealSegment],
    prior_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    state = dict(prior_state or {})
    unresolved_targets, approval_candidates = _targets_from_reasoning_state(
        getattr(meal, "reasoning_state_json", None),
    )
    if not unresolved_targets and not approval_candidates:
        unresolved_targets = [
            {
                "segment_id": segment.id,
                "primary_segment_id": segment.id,
                "segment_ids": [segment.id],
                "label": getattr(segment, "label", None) or "this item",
                "question_kind": "IDENTITY",
                "candidate_choices": [],
                "missing_evidence": [],
            }
            for segment in segments
        ]

    pending_targets = [dict(target) for target in unresolved_targets]
    roadmap_step = _initial_roadmap_step_for_target(pending_targets[0]) if pending_targets else "CONFIRMATION"
    state.update(
        {
            "meal_id": meal.id,
            "session_mode": str(state.get("session_mode") or SESSION_MODE_MEAL),
            "roadmap_step": roadmap_step,
            "pending_targets": pending_targets,
            "unresolved_targets": [dict(target) for target in unresolved_targets],
            "approval_candidates": [dict(candidate) for candidate in approval_candidates],
            "current_target_index": 0,
            "answers_by_segment": list(state.get("answers_by_segment") or []),
            "interview_messages": list(state.get("interview_messages") or []),
            "segment_refs": _segment_refs(segments),
            "reasoning_summary": _reasoning_summary(getattr(meal, "reasoning_state_json", None)),
        }
    )
    question_state = _build_clarification_question_state(
        reasoning_state=getattr(meal, "reasoning_state_json", None),
        approval_candidates=approval_candidates,
    )
    if question_state:
        state.update(question_state)
        state["roadmap_step"] = "QUESTION_BATCH" if state.get("pending_question_ids") else "CONFIRMATION"
        state["current_question"] = current_target_question(state)
        return state

    current_question = current_target_question(state) if pending_targets else {
        "segment_id": None,
        "roadmap_step": "CONFIRMATION",
        "prompt": "Confirm or correct the identified meal items.",
        "invalid_prompt": "Confirm or correct the identified meal items.",
        "session_mode": str(state.get("session_mode") or SESSION_MODE_MEAL),
    }
    state["current_question"] = _question_with_approval_candidates(
        current_question,
        approval_candidates=approval_candidates,
    )
    return state


async def prepare_interview_session(
    *,
    session,
    meal: MealLog,
    segments: list[MealSegment],
    chat_id: str,
) -> InterviewSession:
    existing_result = await session.execute(
        select(InterviewSession)
        .where(
            InterviewSession.meal_log_id == meal.id,
            InterviewSession.is_active.is_(True),
        )
        .order_by(InterviewSession.updated_at.desc())
        .limit(1)
    )
    existing = existing_result.scalar_one_or_none()
    if existing is not None:
        return existing

    prompt_payload = build_interview_turn_state(
        meal=meal,
        segments=segments,
    )
    prompt_payload["last_prompted_at"] = datetime.now(UTC)
    prompt_payload = _json_safe_payload(prompt_payload)
    interview = InterviewSession(
        id=str(uuid.uuid4()),
        meal_log_id=meal.id,
        chat_id=str(chat_id),
        state_key=str(prompt_payload.get("roadmap_step") or "CONFIRMATION"),
        current_prompt_payload=prompt_payload,
        reminder_count=0,
        is_active=True,
    )
    session.add(interview)
    return interview


async def prepare_fix_interview_session(
    *,
    session,
    entry: DiaryEntry,
    entry_context: Mapping[str, Any],
    chat_id: str,
) -> InterviewSession:
    existing_result = await session.execute(
        select(InterviewSession)
        .where(
            InterviewSession.meal_log_id == entry.meal_log_id,
            InterviewSession.chat_id == str(chat_id),
            InterviewSession.is_active.is_(True),
        )
        .order_by(InterviewSession.updated_at.desc())
        .limit(1)
    )
    existing = existing_result.scalar_one_or_none()
    if existing is not None:
        payload = dict(existing.current_prompt_payload or {})
        if (
            payload.get("session_mode") == SESSION_MODE_FIX
            and str(payload.get("fix_entry_id") or "") == str(entry.id)
        ):
            return existing

    food_name = _optional_text(entry_context.get("food_name")) or "this item"
    target = {
        "segment_id": _optional_text(getattr(entry, "segment_id", None)) or f"entry:{entry.id}",
        "label": food_name,
        "entry_id": entry.id,
        "food_item_id": entry.food_item_id,
        "food_name": food_name,
        "original_name": food_name,
        "source_type": normalize_source_type(entry_context.get("source_type")),
        "brand_name": _optional_text(entry_context.get("brand_name")),
        "restaurant_name": _optional_text(entry_context.get("restaurant_name")),
        "portion_bucket": _portion_bucket(entry_context.get("portion_bucket")),
        "quantity_display": _optional_text(entry_context.get("quantity_display")),
    }
    prompt_payload = _json_safe_payload({
        "meal_id": entry.meal_log_id,
        "session_mode": SESSION_MODE_FIX,
        "fix_entry_id": entry.id,
        "roadmap_step": "FOOD_NAME",
        "pending_targets": [target],
        "current_target_index": 0,
        "answers_by_segment": [dict(target)],
        "interview_messages": [],
        "last_prompted_at": datetime.now(UTC),
    })
    interview = InterviewSession(
        id=str(uuid.uuid4()),
        meal_log_id=entry.meal_log_id,
        chat_id=str(chat_id),
        state_key="FOOD_NAME",
        current_prompt_payload=prompt_payload,
        reminder_count=0,
        is_active=True,
    )
    session.add(interview)
    session.add(
        InterviewMessage(
            id=str(uuid.uuid4()),
            session_id=interview.id,
            role="bot",
            payload={
                "type": "prompt",
                "prompt": current_target_question(prompt_payload),
            },
        )
    )
    return interview


async def persist_interview_step(
    *,
    session,
    interview: InterviewSession,
    state: Mapping[str, Any],
    user_payload: Mapping[str, Any],
    next_prompt: Mapping[str, Any] | None = None,
    user_message_id: int | None = None,
    next_prompt_message_id: int | None = None,
) -> InterviewSession:
    persisted_state = _json_safe_payload(state)
    interview.current_prompt_payload = persisted_state
    interview.state_key = str(persisted_state.get("roadmap_step") or interview.state_key)
    if isinstance(next_prompt_message_id, int):
        interview.last_bot_message_id = next_prompt_message_id
    session.add(interview)
    session.add(
        InterviewMessage(
            id=str(uuid.uuid4()),
            session_id=interview.id,
            role="user",
            payload=dict(user_payload),
            message_id=user_message_id if isinstance(user_message_id, int) else None,
        )
    )
    if next_prompt is not None:
        session.add(
            InterviewMessage(
                id=str(uuid.uuid4()),
                session_id=interview.id,
                role="bot",
                payload={
                    "type": "prompt",
                    "prompt": dict(next_prompt),
                },
                message_id=next_prompt_message_id if isinstance(next_prompt_message_id, int) else None,
            )
        )
    if hasattr(session, "commit"):
        maybe = session.commit()
        if hasattr(maybe, "__await__"):
            await maybe
    return interview


def final_resolution_from_confirmation(
    *,
    item: Mapping[str, Any],
    segment: MealSegment | None = None,
    best_effort: bool = False,
    aliases: list[str] | None = None,
    correction_reason: str | None = None,
    skip_grounding_handoff: bool = False,
) -> FinalSegmentResolution:
    parsed = InterviewAnswer.from_mapping(item)
    grounding_prep = build_grounding_prep(item)
    needs_grounding = grounding_prep is not None or best_effort
    reasoning = "NEEDS_GROUNDING" if needs_grounding else parsed.evidence
    segment_id = parsed.segment_id or (getattr(segment, "id", None) if segment is not None else None)
    embedding = getattr(segment, "embedding", None) if segment is not None else None
    segment_embedding = _embedding_payload(embedding)
    can_preserve_visual_learning = (
        segment is not None
        and getattr(segment, "cropped_image_url", None) is not None
        and segment_embedding is not None
    )
    quantity_json = _build_resolution_quantity_json(
        item=item,
        portion_bucket=parsed.portion_bucket,
        grounding_prep=grounding_prep,
    )
    return FinalSegmentResolution(
        food=ResolvedFoodInput(
            canonical_name=parsed.name,
            food_item_id=parsed.food_item_id,
            aliases=_dedupe_texts(aliases or [parsed.name]),
            source_type=parsed.source_type,
            brand_name=parsed.brand_name,
            restaurant_name=parsed.restaurant_name,
            llm_reasoning=reasoning,
            is_verified=not best_effort and not needs_grounding,
            times_confirmed=1,
            needs_grounding=needs_grounding,
        ),
        segment_id=segment_id,
        segment_cropped_image_url=getattr(segment, "cropped_image_url", None) if segment is not None else None,
        segment_embedding=segment_embedding,
        portion_bucket=parsed.portion_bucket,
        identification_method="INTERVIEW_BEST_EFFORT" if best_effort else "INTERVIEW",
        quantity_json=quantity_json,
        quantity_display=parsed.quantity_display,
        create_food_visual=(not best_effort) or can_preserve_visual_learning,
        visual_learning_eligible=(not best_effort) or can_preserve_visual_learning,
        skip_grounding_handoff=skip_grounding_handoff,
        correction_reason=_optional_text(correction_reason),
    )


def _embedding_payload(value: object) -> list[float] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        converted = tolist()
        if isinstance(converted, list):
            return converted
    return None


def build_grounding_reasoning_state(
    *,
    confirmation_items: list[Mapping[str, Any]],
    status: str,
    prior_state: Mapping[str, Any] | None = None,
    updated_at: datetime | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    state = dict(prior_state or {})
    state.update(
        {
            "completed_by": "interview_service",
            "grounding_required": True,
            "post_interview_grounding": True,
            "grounding_status": status,
            "confirmation_items": [dict(item) for item in confirmation_items],
            "updated_at": (updated_at or datetime.now(UTC)).isoformat(),
        }
    )
    if extra:
        state.update({key: value for key, value in extra.items() if value is not None})
    return state


async def finalize_confirmed_interview(
    *,
    session,
    meal: MealLog,
    confirmation_items: list[Mapping[str, Any]],
    segments: list[MealSegment] | None = None,
    best_effort: bool = False,
    interview_state: Mapping[str, Any] | None = None,
    force_degraded_save: bool = False,
    degraded_grounding_failure: Mapping[str, Any] | None = None,
):
    finalized_confirmation_items = [dict(item) for item in confirmation_items]
    finalizer_groups: list[dict[str, Any]] = []
    finalizer_inputs = _build_group_finalizer_inputs(
        meal=meal,
        confirmation_items=confirmation_items,
        interview_state=interview_state,
        segments=segments or [],
    )

    if finalizer_inputs:
        settings = get_settings()
        llm_client = get_llm_client()
        finalizer_outcomes = await _run_group_finalizers(
            group_inputs=finalizer_inputs,
            llm_client=llm_client,
            settings=settings,
        )
        finalized_confirmation_items = [
            dict(outcome.finalized_confirmation_item)
            for outcome in finalizer_outcomes
        ]
        finalizer_groups = [
            dict(outcome.audit_state)
            for outcome in finalizer_outcomes
        ]
        final_segments = [outcome.final_resolution for outcome in finalizer_outcomes]
    else:
        segments_by_id = {segment.id: segment for segment in segments or []}
        final_segments = [
            final_resolution_from_confirmation(
                item=item,
                segment=segments_by_id.get(str(item.get("segment_id"))),
                best_effort=best_effort,
            )
            for item in confirmation_items
        ]

    if any(
        resolution.food.needs_grounding and not resolution.skip_grounding_handoff
        for resolution in final_segments
    ) and not force_degraded_save:
        meal.processing_status = MealProcessingStatus.INTERVIEWING
        meal.reasoning_state_json = build_grounding_reasoning_state(
            confirmation_items=finalized_confirmation_items,
            status="PENDING_HANDOFF",
            prior_state=getattr(meal, "reasoning_state_json", None),
            extra={
                "handoff_target": "poll_post_interview_grounding",
                "finalizer_groups": finalizer_groups or None,
            },
        )
        if hasattr(meal, "last_stage_started_at"):
            meal.last_stage_started_at = None
        session.add(meal)
        if hasattr(session, "commit"):
            maybe = session.commit()
            if hasattr(maybe, "__await__"):
                await maybe
        return {
            "meal": meal,
            "meal_entries": [],
            "food_visuals": [],
            "correction_events": [],
            "grounding_required": True,
        }

    result = await apply_final_meal_resolution(
        session=session,
        meal=meal,
        final_segments=final_segments,
        meal_status=MealProcessingStatus.COMPLETED,
        reasoning_state_json=_build_finalization_reasoning_state(
            meal=meal,
            confirmation_items=finalized_confirmation_items,
            best_effort=best_effort,
            interview_state=interview_state,
            finalizer_groups=finalizer_groups,
            grounding_status=(
                "DEGRADED_SAVED"
                if force_degraded_save and degraded_grounding_failure is not None
                else None
            ),
            grounding_failure=degraded_grounding_failure,
        ),
    )
    if hasattr(session, "commit"):
        maybe = session.commit()
        if hasattr(maybe, "__await__"):
            await maybe
    return result


def _build_finalization_reasoning_state(
    *,
    meal: MealLog,
    confirmation_items: list[Mapping[str, Any]],
    best_effort: bool,
    interview_state: Mapping[str, Any] | None,
    finalizer_groups: list[Mapping[str, Any]] | None = None,
    grounding_status: str | None = None,
    grounding_failure: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    state = dict(getattr(meal, "reasoning_state_json", None) or {})
    interview_payload = dict(interview_state or {})
    completed_at = datetime.now(UTC).isoformat()

    state.update(
        {
            "completed_by": "interview_service",
            "best_effort": best_effort,
            "confirmation_items": [dict(item) for item in confirmation_items],
            "completed_at": completed_at,
        }
    )
    if grounding_status:
        state["grounding_required"] = True
        state["post_interview_grounding"] = True
        state["grounding_status"] = grounding_status
    if isinstance(grounding_failure, Mapping):
        state["grounding_failure"] = {
            str(key): _json_safe_payload(value)
            for key, value in grounding_failure.items()
        }
    if finalizer_groups:
        state["finalizer_groups"] = [
            {
                str(key): _json_safe_payload(value)
                for key, value in dict(group).items()
            }
            for group in finalizer_groups
            if isinstance(group, Mapping)
        ]

    clarification_answers = interview_payload.get("answers_by_question_id")
    if isinstance(clarification_answers, Mapping):
        state["answers_by_question_id"] = {
            str(key): dict(value)
            for key, value in clarification_answers.items()
            if isinstance(value, Mapping)
        }
    elif isinstance(state.get("answers_by_question_id"), Mapping):
        state["answers_by_question_id"] = {
            str(key): dict(value)
            for key, value in dict(state.get("answers_by_question_id") or {}).items()
            if isinstance(value, Mapping)
        }

    resolver_payload = interview_payload.get("resolver_payload")
    if isinstance(resolver_payload, Mapping):
        state["resolver_payload"] = {
            str(key): _json_safe_payload(value)
            for key, value in resolver_payload.items()
        }
    else:
        state["resolver_payload"] = {
            "turn_action": "ready_to_confirm",
            "confirmation_items": [dict(item) for item in confirmation_items],
            "remaining_required_question_ids": list(
                interview_payload.get("remaining_required_question_ids") or []
            ),
            "conversation_summary": _optional_text(interview_payload.get("conversation_summary")),
            "completed_at": completed_at,
        }

    return state


def _build_group_finalizer_inputs(
    *,
    meal: MealLog,
    confirmation_items: list[Mapping[str, Any]],
    interview_state: Mapping[str, Any] | None,
    segments: list[MealSegment],
) -> list[GroupFinalizerInput]:
    reasoning_state = dict(getattr(meal, "reasoning_state_json", None) or {})
    groups_by_id = {
        _optional_text(group.get("group_id")) or f"group-{index}": dict(group)
        for index, group in enumerate(_food_groups_from_reasoning_state(reasoning_state), start=1)
    }
    answers_by_question_id = _merged_answers_by_question_id(
        reasoning_state=reasoning_state,
        interview_state=interview_state,
    )
    segments_by_id = {
        str(getattr(segment, "id", "")): segment
        for segment in segments
        if getattr(segment, "id", None) is not None
    }

    group_inputs: list[GroupFinalizerInput] = []
    for index, item in enumerate(confirmation_items, start=1):
        if not isinstance(item, Mapping):
            continue
        confirmation_item = dict(item)
        group_id = _optional_text(confirmation_item.get("group_id")) or f"group-{index}"
        segment_ids = _normalized_segment_ids(confirmation_item)
        primary_segment_id = (
            _optional_text(confirmation_item.get("primary_segment_id"))
            or _optional_text(confirmation_item.get("segment_id"))
            or (segment_ids[0] if segment_ids else None)
            or f"segment-{index}"
        )
        if primary_segment_id not in segment_ids:
            segment_ids.append(primary_segment_id)
        group_state = dict(groups_by_id.get(group_id) or {})
        segment = segments_by_id.get(primary_segment_id)
        group_inputs.append(
            GroupFinalizerInput(
                group_id=group_id,
                primary_segment_id=primary_segment_id,
                segment_ids=segment_ids,
                confirmation_item=confirmation_item,
                group_state=group_state,
                clarification_answers=_clarification_answers_for_group(
                    answers_by_question_id=answers_by_question_id,
                    group_id=group_id,
                    primary_segment_id=primary_segment_id,
                    segment_ids=segment_ids,
                ),
                segment=segment,
                segment_ref=_segment_ref_payload(segment=segment, segment_ids=segment_ids),
                trace_id=_group_trace_id(reasoning_state=reasoning_state, group_state=group_state),
            )
        )
    return group_inputs


async def _run_group_finalizers(
    *,
    group_inputs: list[GroupFinalizerInput],
    llm_client: Any,
    settings: Any,
) -> list[GroupFinalizerOutcome]:
    if not group_inputs:
        return []
    max_parallelism = max(1, int(getattr(settings, "FINALIZER_GROUP_PARALLELISM", 1)))
    semaphore = asyncio.Semaphore(max_parallelism)

    async def _run_one(group_input: GroupFinalizerInput) -> GroupFinalizerOutcome:
        async with semaphore:
            return await _finalize_group_input(
                group_input=group_input,
                llm_client=llm_client,
                settings=settings,
            )

    return await asyncio.gather(*(_run_one(group_input) for group_input in group_inputs))


async def _finalize_group_input(
    *,
    group_input: GroupFinalizerInput,
    llm_client: Any,
    settings: Any,
) -> GroupFinalizerOutcome:
    attempts: list[dict[str, Any]] = []
    model_name = str(getattr(settings, "FINALIZER_MODEL", "google/gemini-3.1-flash-lite"))
    last_error: Exception | None = None

    for attempt in range(1, FINALIZER_MAX_ATTEMPTS + 1):
        try:
            response = await llm_client.chat_completion(
                model=model_name,
                messages=_group_finalizer_messages(group_input),
                response_format=group_finalizer_response_format(),
                extra_body={
                    "parallel_tool_calls": False,
                    "reasoning": {
                        "max_tokens": 128,
                        "exclude": True,
                    },
                },
                max_tokens=FINALIZER_MAX_TOKENS,
            )
            parsed = parse_group_finalizer_response_payload(
                response,
                expected_group_id=group_input.group_id,
            )
            attempts.append(
                {
                    "attempt": attempt,
                    "model": model_name,
                    "status": "SUCCEEDED",
                }
            )
            return _successful_group_finalizer_outcome(
                group_input=group_input,
                parsed=parsed,
                attempts=attempts,
            )
        except Exception as exc:
            last_error = exc
            attempts.append(
                {
                    "attempt": attempt,
                    "model": model_name,
                    "status": "FAILED",
                    "error": str(exc),
                }
            )

    return _degraded_group_finalizer_outcome(
        group_input=group_input,
        attempts=attempts,
        last_error=last_error,
    )


def _successful_group_finalizer_outcome(
    *,
    group_input: GroupFinalizerInput,
    parsed: FinalizedGroupResult,
    attempts: list[dict[str, Any]],
) -> GroupFinalizerOutcome:
    finalized_confirmation_item = _finalized_confirmation_item(
        original_item=group_input.confirmation_item,
        parsed=parsed,
    )
    final_resolution = final_resolution_from_confirmation(
        item=finalized_confirmation_item,
        segment=group_input.segment,
        aliases=[parsed.final_name, *parsed.aliases],
        correction_reason=parsed.correction_note,
    )
    handoff_action = (
        "poll_post_interview_grounding"
        if final_resolution.food.needs_grounding and not final_resolution.skip_grounding_handoff
        else "apply_final_meal_resolution"
    )
    return GroupFinalizerOutcome(
        group_id=group_input.group_id,
        final_resolution=final_resolution,
        finalized_confirmation_item=finalized_confirmation_item,
        audit_state={
            "group_id": group_input.group_id,
            "status": "SUCCEEDED",
            "attempt_count": len(attempts),
            "attempts": attempts,
            "final_name": parsed.final_name,
            "source_type": parsed.source_type,
            "handoff_action": handoff_action,
        },
    )


def _degraded_group_finalizer_outcome(
    *,
    group_input: GroupFinalizerInput,
    attempts: list[dict[str, Any]],
    last_error: Exception | None,
) -> GroupFinalizerOutcome:
    fallback_item = dict(group_input.confirmation_item)
    fallback_item["name"] = _best_effort_final_name(group_input)
    final_resolution = final_resolution_from_confirmation(
        item=fallback_item,
        segment=group_input.segment,
        best_effort=True,
        skip_grounding_handoff=True,
    )
    finalized_confirmation_item = dict(fallback_item)
    return GroupFinalizerOutcome(
        group_id=group_input.group_id,
        final_resolution=final_resolution,
        finalized_confirmation_item=finalized_confirmation_item,
        audit_state={
            "group_id": group_input.group_id,
            "status": "DEGRADED",
            "attempt_count": len(attempts),
            "attempts": attempts,
            "final_name": fallback_item["name"],
            "source_type": final_resolution.food.source_type,
            "handoff_action": "apply_final_meal_resolution",
            "error": str(last_error) if last_error is not None else "unknown finalizer failure",
        },
    )


def _finalized_confirmation_item(
    *,
    original_item: Mapping[str, Any],
    parsed: FinalizedGroupResult,
) -> dict[str, Any]:
    item = dict(original_item)
    item.update(
        {
            "group_id": parsed.group_id,
            "primary_segment_id": parsed.primary_segment_id,
            "segment_id": _optional_text(item.get("segment_id")) or parsed.primary_segment_id,
            "segment_ids": list(parsed.segment_ids),
            "name": parsed.final_name,
            "source_type": parsed.source_type,
            "portion_bucket": parsed.portion_bucket,
            "quantity_display": parsed.quantity_display,
            "food_item_id": parsed.food_item_id,
            "brand_name": parsed.brand_name,
            "restaurant_name": parsed.restaurant_name,
            "correction_note": parsed.correction_note,
            "aliases": list(parsed.aliases),
            "supporting_details": list(parsed.supporting_details),
        }
    )
    if parsed.quantity_json is not None:
        item["quantity_json"] = parsed.quantity_json.model_dump(mode="json", exclude_none=True)
    return {key: value for key, value in item.items() if value is not None}


def _group_finalizer_messages(group_input: GroupFinalizerInput) -> list[dict[str, str]]:
    payload = {
        "group_id": group_input.group_id,
        "primary_segment_id": group_input.primary_segment_id,
        "segment_ids": list(group_input.segment_ids),
        "reasoning_group": dict(group_input.group_state),
        "confirmation_item": dict(group_input.confirmation_item),
        "clarification_answers": [dict(answer) for answer in group_input.clarification_answers],
        "segment_ref": dict(group_input.segment_ref),
    }
    return [
        {
            "role": "system",
            "content": (
                "You finalize one food group into strict save-ready metadata. "
                "Do not ask any follow-up questions. Do not invent nutrition facts. "
                "Preserve clarification answers that materially affect persistence, including identity, source/origin, and quantity. "
                "The final_name must be a dish-level identity, not a raw fragment answer. "
                "Return JSON only."
            ),
        },
        {
            "role": "user",
            "content": "GROUP_FINALIZER_INPUT_JSON:\n"
            + json.dumps(payload, ensure_ascii=True, separators=(",", ":"), default=str),
        },
    ]


def _build_resolution_quantity_json(
    *,
    item: Mapping[str, Any],
    portion_bucket: str,
    grounding_prep: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    quantity_json = (
        dict(item.get("quantity_json"))
        if isinstance(item.get("quantity_json"), Mapping)
        else {}
    )
    if quantity_json or _optional_text(item.get("quantity_display")) or grounding_prep is not None:
        quantity_json.setdefault("portion_bucket", portion_bucket)
    source_origin_state = _optional_text(item.get("source_origin_state"))
    if source_origin_state:
        quantity_json["source_origin_state"] = source_origin_state
    if grounding_prep is not None:
        quantity_json["grounding_prep"] = dict(grounding_prep)
    return quantity_json or None


def _best_effort_final_name(group_input: GroupFinalizerInput) -> str:
    confirmation_name = _optional_text(group_input.confirmation_item.get("name"))
    if confirmation_name:
        if _group_uses_detail_clarification(group_input) and (base_name := _best_effort_base_name(group_input)):
            if base_name.casefold() not in confirmation_name.casefold():
                return f"{base_name} ({confirmation_name})"
        return confirmation_name
    return _best_effort_base_name(group_input) or "Unknown food"


def _best_effort_base_name(group_input: GroupFinalizerInput) -> str | None:
    candidate_name = _selected_group_name(group_input.group_state)
    group_label = _optional_text(
        group_input.group_state.get("group_label") or group_input.group_state.get("label")
    )
    return candidate_name or group_label


def _group_uses_detail_clarification(group_input: GroupFinalizerInput) -> bool:
    question_kind = _question_kind(group_input.group_state.get("question_kind"))
    if question_kind == "DETAIL" or _optional_text(group_input.group_state.get("question_focus")):
        return True
    for answer in group_input.clarification_answers:
        if _question_kind(answer.get("question_kind")) == "DETAIL":
            return True
    return False


def _food_groups_from_reasoning_state(reasoning_state: object) -> list[dict[str, Any]]:
    if not isinstance(reasoning_state, Mapping):
        return []
    groups = reasoning_state.get("food_groups")
    if not isinstance(groups, list):
        meal_reasoning = reasoning_state.get("meal_reasoning")
        groups = meal_reasoning.get("food_groups") if isinstance(meal_reasoning, Mapping) else None
    if not isinstance(groups, list):
        return []
    return [dict(group) for group in groups if isinstance(group, Mapping)]


def _merged_answers_by_question_id(
    *,
    reasoning_state: Mapping[str, Any],
    interview_state: Mapping[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for source in (
        reasoning_state.get("answers_by_question_id"),
        dict(interview_state or {}).get("answers_by_question_id"),
    ):
        if not isinstance(source, Mapping):
            continue
        for key, value in source.items():
            if isinstance(value, Mapping):
                merged[str(key)] = dict(value)
    return merged


def _clarification_answers_for_group(
    *,
    answers_by_question_id: Mapping[str, Mapping[str, Any]],
    group_id: str,
    primary_segment_id: str,
    segment_ids: list[str],
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    segment_id_set = {segment_id for segment_id in segment_ids if segment_id}
    for answer in answers_by_question_id.values():
        answer_group_id = _optional_text(answer.get("group_id"))
        answer_primary_segment_id = _optional_text(
            answer.get("primary_segment_id") or answer.get("segment_id")
        )
        answer_segment_ids = {
            str(segment_id)
            for segment_id in answer.get("segment_ids") or []
            if segment_id is not None
        }
        if answer_group_id == group_id:
            selected.append(dict(answer))
            continue
        if answer_primary_segment_id == primary_segment_id:
            selected.append(dict(answer))
            continue
        if answer_segment_ids & segment_id_set:
            selected.append(dict(answer))
    return selected


def _segment_ref_payload(
    *,
    segment: MealSegment | None,
    segment_ids: list[str],
) -> dict[str, Any]:
    if segment is None:
        return {"segment_ids": list(segment_ids)}
    return {
        "segment_ids": list(segment_ids),
        "segment_id": getattr(segment, "id", None),
        "label": getattr(segment, "label", None),
        "crop_path": getattr(segment, "cropped_image_url", None),
        "image_path": getattr(segment, "image_url", None),
    }


def _group_trace_id(
    *,
    reasoning_state: Mapping[str, Any],
    group_state: Mapping[str, Any],
) -> str | None:
    return (
        _optional_text(group_state.get("trace_id"))
        or _optional_text(reasoning_state.get("trace_id"))
        or _optional_text(
            dict(reasoning_state.get("meal_reasoning") or {}).get("trace_id")
        )
    )


def _normalized_segment_ids(payload: Mapping[str, Any]) -> list[str]:
    segment_ids: list[str] = []
    for key in ("segment_ids",):
        value = payload.get(key)
        if isinstance(value, list):
            for item in value:
                segment_id = str(item).strip()
                if segment_id and segment_id not in segment_ids:
                    segment_ids.append(segment_id)
    segment_id = _optional_text(payload.get("segment_id"))
    if segment_id and segment_id not in segment_ids:
        segment_ids.append(segment_id)
    primary_segment_id = _optional_text(payload.get("primary_segment_id"))
    if primary_segment_id and primary_segment_id not in segment_ids:
        segment_ids.append(primary_segment_id)
    return segment_ids


def _clean_identity_text(text: object) -> str:
    value = str(text or "").strip()
    value = re.sub(r"^(actually\s+)?(it'?s|its|first is|second is)\s+", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^(a|an|the)\s+", "", value, flags=re.IGNORECASE)
    value = value.strip(" .")
    return value or "Unknown food"


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _dedupe_texts(values: list[str] | None) -> list[str] | None:
    if values is None:
        return None
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _optional_text(value)
        if text is None:
            continue
        lowered = text.casefold()
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized.append(text)
    return normalized or None


def _text(value: object, *, default: str) -> str:
    return _optional_text(value) or default


def _portion_bucket(value: object) -> str:
    if not isinstance(value, str):
        return "STANDARD"
    normalized = value.strip().upper()
    return normalized if normalized in {"SMALL", "STANDARD", "LARGE"} else "STANDARD"


def _safe_int(value: object, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        normalized = value
        if normalized.endswith("Z"):
            normalized = f"{normalized[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed
    return None


def _json_safe_payload(value: object) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe_payload(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe_payload(item) for item in value]
    return value


def _transcript_role(value: object) -> str | None:
    role = str(value or "").strip().lower()
    if role == "bot":
        return "assistant"
    if role in {"assistant", "user", "system"}:
        return role
    return None


def _transcript_content_from_payload(*, role: str, payload: object) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    prompt_payload = payload.get("prompt")
    if isinstance(prompt_payload, Mapping):
        prompt = _optional_text(prompt_payload.get("prompt"))
        if prompt:
            return prompt
    prompt = _optional_text(payload.get("prompt"))
    if prompt:
        return prompt
    if role == "assistant":
        return _optional_text(payload.get("assistant_prompt"))
    return (
        _optional_text(payload.get("raw_text"))
        or _optional_text(payload.get("text"))
        or _optional_text(payload.get("name"))
        or _optional_text(payload.get("value"))
    )


def _current_target(state: Mapping[str, Any]) -> dict[str, Any]:
    targets = list(state.get("pending_targets") or [])
    index = _safe_int(state.get("current_target_index"), default=0)
    if not targets:
        return {"segment_id": None, "label": "this item"}
    index = min(max(index, 0), len(targets) - 1)
    return dict(targets[index])


def _answer_record_for_state(state: Mapping[str, Any], target: Mapping[str, Any]) -> dict[str, Any]:
    existing = _answer_for_target(state, target)
    if existing is not None:
        return dict(existing)
    seeded = {
        "group_id": _optional_text(target.get("group_id")),
        "primary_segment_id": _optional_text(target.get("primary_segment_id")),
        "segment_ids": list(target.get("segment_ids") or []) if isinstance(target.get("segment_ids"), list) else None,
        "segment_id": _target_segment_id(target),
        "label": target.get("label"),
        "entry_id": target.get("entry_id"),
        "food_item_id": target.get("food_item_id"),
        "name": _optional_text(target.get("food_name") or target.get("name")),
        "original_name": _optional_text(target.get("original_name") or target.get("food_name") or target.get("name")),
        "source_type": normalize_source_type(target.get("source_type")),
        "brand_name": _optional_text(target.get("brand_name")),
        "restaurant_name": _optional_text(target.get("restaurant_name")),
        "portion_bucket": _portion_bucket(target.get("portion_bucket")),
        "quantity_display": _optional_text(target.get("quantity_display")),
    }
    return {key: value for key, value in seeded.items() if value is not None}


def _answer_for_target(
    state: Mapping[str, Any],
    target: Mapping[str, Any],
) -> dict[str, Any] | None:
    for answer in state.get("answers_by_segment") or []:
        if _answer_matches_target(answer, target):
            return dict(answer)
    return None


def _answer_matches_target(answer: Mapping[str, Any], target: Mapping[str, Any]) -> bool:
    group_id = _optional_text(target.get("group_id"))
    if group_id and _optional_text(answer.get("group_id")) == group_id:
        return True
    return str(answer.get("segment_id") or "") == str(_target_segment_id(target) or "")


def _target_segment_id(target: Mapping[str, Any]) -> str | None:
    return _optional_text(target.get("segment_id")) or _optional_text(target.get("primary_segment_id"))


def _pending_targets_from_food_groups(reasoning_state: object) -> list[dict[str, Any]]:
    if not isinstance(reasoning_state, Mapping):
        return []
    groups = reasoning_state.get("food_groups")
    if not isinstance(groups, list):
        meal_reasoning = reasoning_state.get("meal_reasoning")
        groups = meal_reasoning.get("food_groups") if isinstance(meal_reasoning, Mapping) else None
    if not isinstance(groups, list):
        return []

    pending_targets: list[dict[str, Any]] = []
    for group in groups:
        if not isinstance(group, Mapping) or not _group_needs_interview(group):
            continue
        segment_ids = [
            str(segment_id)
            for segment_id in group.get("segment_ids") or []
            if segment_id is not None
        ]
        target = {
            "group_id": _optional_text(group.get("group_id")) or f"group-{len(pending_targets) + 1}",
            "primary_segment_id": _optional_text(group.get("primary_segment_id")) or (segment_ids[0] if segment_ids else None),
            "segment_ids": segment_ids,
            "label": _optional_text(group.get("group_label") or group.get("label")) or "this item",
            "question_kind": _question_kind(group.get("question_kind")),
            "question_focus": _optional_text(group.get("question_focus")),
            "question_examples": [
                str(example).strip()
                for example in group.get("question_examples") or []
                if str(example).strip()
            ],
            "candidate_choices": _candidate_choices(group.get("top_3")),
        }
        pending_targets.append({key: value for key, value in target.items() if value not in (None, [], "")})

    return sorted(pending_targets, key=_pending_target_sort_key)


def _targets_from_reasoning_state(reasoning_state: object) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(reasoning_state, Mapping):
        return [], []
    groups = reasoning_state.get("food_groups")
    if not isinstance(groups, list):
        meal_reasoning = reasoning_state.get("meal_reasoning")
        groups = meal_reasoning.get("food_groups") if isinstance(meal_reasoning, Mapping) else None
    if not isinstance(groups, list):
        return [], []

    pending_targets: list[dict[str, Any]] = []
    approval_candidates: list[dict[str, Any]] = []
    for group in groups:
        if not isinstance(group, Mapping):
            continue
        group_payload = _group_state_payload(
            group,
            ordinal=len(pending_targets) + len(approval_candidates) + 1,
        )
        if _group_needs_interview(group):
            pending_targets.append(group_payload)
        elif _group_is_approval_candidate(group):
            approval_candidates.append(
                {
                    **group_payload,
                    "proposed_name": _selected_group_name(group),
                }
            )

    return (
        sorted(pending_targets, key=_pending_target_sort_key),
        approval_candidates,
    )


def _group_state_payload(group: Mapping[str, Any], *, ordinal: int) -> dict[str, Any]:
    segment_ids = [
        str(segment_id)
        for segment_id in group.get("segment_ids") or []
        if segment_id is not None
    ]
    target = {
        "group_id": _optional_text(group.get("group_id")) or f"group-{ordinal}",
        "primary_segment_id": _optional_text(group.get("primary_segment_id")) or (segment_ids[0] if segment_ids else None),
        "segment_ids": segment_ids,
        "label": _optional_text(group.get("group_label") or group.get("label")) or "this item",
        "question_kind": _question_kind(group.get("question_kind")),
        "question_focus": _optional_text(group.get("question_focus")),
        "question_examples": [
            str(example).strip()
            for example in group.get("question_examples") or []
            if str(example).strip()
        ],
        "candidate_choices": _candidate_choices(group.get("top_3")),
        "missing_evidence": [
            str(item).strip()
            for item in group.get("missing_evidence") or []
            if str(item).strip()
        ],
        "decision_rationale": _optional_text(group.get("decision_rationale")),
    }
    return {key: value for key, value in target.items() if value not in (None, [], "")}


def _group_needs_interview(group: Mapping[str, Any]) -> bool:
    actions = _group_actions(group)
    action = str(group.get("group_action") or group.get("action") or "").upper()
    state = str(group.get("group_state") or group.get("state") or "").upper()
    return bool(
        actions
        & {
            "AFFIRMATION_REQUIRED",
            "IDENTITY_CLARIFICATION_REQUIRED",
            "ASK_SOURCE_ORIGIN",
            "ASK_QUANTITY",
            "INTERVIEW",
            "ASK_CHOICE",
        }
    ) or action in {"INTERVIEW", "ASK_CHOICE", "ASK_QUANTITY", "ASK_SOURCE_ORIGIN"} or state in {
        "UNRESOLVED",
        "PENDING_INTERVIEW",
        "PENDING_CHOICE",
        "PARTIAL_RESOLVED_WAITING",
        "INTERVIEWING",
    }


def _group_is_approval_candidate(group: Mapping[str, Any]) -> bool:
    if _group_needs_interview(group):
        return False
    actions = _group_actions(group)
    action = str(group.get("group_action") or group.get("action") or "").upper()
    state = str(group.get("group_state") or group.get("state") or "").upper()
    return bool(actions & {"AUTO_CONFIRM", "AUTO_CONFIRM_WITH_TRACE", "AUTO_CONFIRM_LEARNED"}) or action in {
        "AUTO_CONFIRM",
        "AUTO_CONFIRM_WITH_TRACE",
        "READY_TO_WRITE",
    } or state == "READY_TO_WRITE"


def _group_actions(group: Mapping[str, Any]) -> set[str]:
    raw_actions = group.get("group_actions")
    if not isinstance(raw_actions, list):
        return set()
    return {
        str(action).strip().upper()
        for action in raw_actions
        if isinstance(action, str) and str(action).strip()
    }


def _pending_target_sort_key(target: Mapping[str, Any]) -> tuple[int, str]:
    priority = {
        "DETAIL": 0,
        "IDENTITY": 0,
        "NAME": 0,
        "CHOICE": 1,
        "QUANTITY": 2,
    }
    return (
        priority.get(_question_kind(target.get("question_kind")), 1),
        str(target.get("label") or ""),
    )


def _question_kind(value: object) -> str:
    if not isinstance(value, str):
        return "IDENTITY"
    normalized = value.strip().upper()
    return normalized or "IDENTITY"


def _candidate_choices(top_candidates: object) -> list[str]:
    if not isinstance(top_candidates, list):
        return []
    choices: list[str] = []
    for candidate in top_candidates:
        if isinstance(candidate, Mapping):
            label = _optional_text(candidate.get("label") or candidate.get("candidate_name") or candidate.get("name"))
            if label:
                choices.append(label)
    return choices


def _selected_group_name(group: Mapping[str, Any]) -> str:
    selected_candidate_id = _optional_text(group.get("selected_candidate_id"))
    if isinstance(group.get("top_3"), list):
        for candidate in group.get("top_3") or []:
            if not isinstance(candidate, Mapping):
                continue
            candidate_id = _optional_text(candidate.get("candidate_id"))
            label = _optional_text(candidate.get("label") or candidate.get("candidate_name") or candidate.get("name"))
            if selected_candidate_id and candidate_id == selected_candidate_id and label:
                return label
    return _optional_text(group.get("group_label") or group.get("label")) or "this item"


def _segment_refs(segments: list[MealSegment]) -> dict[str, dict[str, Any]]:
    refs: dict[str, dict[str, Any]] = {}
    for segment in segments:
        refs[str(segment.id)] = {
            "label": getattr(segment, "label", None),
            "crop_path": getattr(segment, "cropped_image_url", None),
            "image_path": getattr(segment, "image_url", None),
        }
    return refs


def _reasoning_summary(reasoning_state: object) -> str:
    if not isinstance(reasoning_state, Mapping):
        return "No grouped reasoning summary available."
    meal_reasoning = reasoning_state.get("meal_reasoning")
    if not isinstance(meal_reasoning, Mapping):
        meal_reasoning = reasoning_state
    trace_id = _optional_text(meal_reasoning.get("trace_id"))
    rationale = _optional_text(meal_reasoning.get("decision_rationale")) or "No reasoning rationale recorded."
    if trace_id:
        return f"trace_id={trace_id}; {rationale}"
    return rationale


def has_deterministic_question_state(state: Mapping[str, Any]) -> bool:
    return isinstance(state.get("questions_by_id"), Mapping) and isinstance(state.get("question_order"), list)


def _food_groups_from_reasoning_state(reasoning_state: object) -> list[dict[str, Any]]:
    if not isinstance(reasoning_state, Mapping):
        return []
    groups = reasoning_state.get("food_groups")
    if not isinstance(groups, list):
        meal_reasoning = reasoning_state.get("meal_reasoning")
        groups = meal_reasoning.get("food_groups") if isinstance(meal_reasoning, Mapping) else None
    if not isinstance(groups, list):
        return []
    return [dict(group) for group in groups if isinstance(group, Mapping)]


def _clarification_questions_from_food_groups(reasoning_state: object) -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    for group in _food_groups_from_reasoning_state(reasoning_state):
        actions = group.get("clarification_actions")
        if not isinstance(actions, list) or not actions:
            continue
        group_id = _optional_text(group.get("group_id")) or f"group-{len(questions) + 1}"
        group_label = _optional_text(group.get("group_label") or group.get("label")) or "this item"
        segment_ids = [
            str(segment_id).strip()
            for segment_id in group.get("segment_ids") or []
            if str(segment_id).strip()
        ]
        primary_segment_id = _optional_text(group.get("primary_segment_id")) or _first_segment_id(segment_ids)
        for idx, action in enumerate(actions):
            if not isinstance(action, Mapping):
                continue
            action_payload = dict(action)
            action_type = _question_kind(
                action.get("type") or action.get("kind") or action.get("question_kind")
            )
            action_payload.setdefault(
                "question_id",
                f"{group_id}:{action_type.lower()}_{idx + 1}",
            )
            action_payload.setdefault("group_id", group_id)
            action_payload.setdefault("group_label", group_label)
            action_payload.setdefault("label", group_label)
            action_payload.setdefault("primary_segment_id", primary_segment_id)
            action_payload.setdefault("segment_ids", segment_ids)
            action_payload.setdefault(
                "question_kind",
                action.get("kind") or action.get("question_kind") or action.get("type"),
            )
            questions.append(_normalize_clarification_question(action_payload))
    return questions


def _build_clarification_question_state(
    *,
    reasoning_state: object,
    approval_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    clarification_questions = _clarification_questions_from_food_groups(reasoning_state)
    if not clarification_questions:
        return {}
    questions = list(clarification_questions)
    question_order = [question["question_id"] for question in questions if _optional_text(question.get("question_id"))]
    questions_by_id = {
        question["question_id"]: question
        for question in questions
        if _optional_text(question.get("question_id"))
    }
    pending_question_ids = list(question_order)
    return {
        "question_order": question_order,
        "questions_by_id": questions_by_id,
        "answers_by_question_id": {},
        "pending_question_ids": pending_question_ids,
        "remaining_required_question_ids": _remaining_required_question_ids(
            question_order=question_order,
            questions_by_id=questions_by_id,
            answers_by_question_id={},
        ),
    }


def _normalize_clarification_question(question: Mapping[str, Any]) -> dict[str, Any]:
    segment_ids = [
        str(segment_id).strip()
        for segment_id in question.get("segment_ids") or []
        if str(segment_id).strip()
    ]
    question_kind = _question_kind(
        question.get("question_kind") or question.get("kind") or question.get("type")
    )
    answer_type = _normalize_answer_type(question.get("answer_type"))
    choices = _normalize_question_choices(question.get("choices"))
    if answer_type == "confirm":
        choices = _normalize_confirm_choices(choices)
    allow_other = bool(question.get("allow_other"))
    if any(choice["choice_id"] == "__other__" for choice in choices):
        allow_other = True
        choices = [choice for choice in choices if choice["choice_id"] != "__other__"]
    required = bool(question.get("required"))
    if question_kind == "APPROVAL":
        required = False

    normalized = {
        "question_id": _optional_text(question.get("question_id")) or f"question-{len(segment_ids)}",
        "group_id": _optional_text(question.get("group_id")) or "group-unknown",
        "primary_segment_id": _optional_text(question.get("primary_segment_id")) or _first_segment_id(segment_ids),
        "segment_ids": segment_ids,
        "question_kind": question_kind,
        "type": _optional_text(question.get("type")) or question_kind,
        "question_focus": _optional_text(question.get("question_focus")),
        "answer_type": answer_type,
        "required": required,
        "label": _optional_text(question.get("group_label") or question.get("label")) or "this item",
        "user_prompt": _optional_text(question.get("user_prompt") or question.get("prompt")),
        "choices": choices,
        "allow_other": allow_other,
        "other_label": _optional_text(question.get("other_label")) or "Other",
        "reason": _optional_text(question.get("reason")),
        "validation_hints": dict(question.get("validation_hints") or {}) if isinstance(question.get("validation_hints"), Mapping) else {},
        "question_examples": _coerce_examples(question.get("question_examples")),
        "correction_for_question_id": _optional_text(question.get("correction_for_question_id")),
    }
    return normalized


def _approval_question_from_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    label = _optional_text(candidate.get("proposed_name") or candidate.get("label")) or "this item"
    group_id = _optional_text(candidate.get("group_id")) or "group-approval"
    return {
        "question_id": f"{group_id}:confirm",
        "group_id": group_id,
        "primary_segment_id": _optional_text(candidate.get("primary_segment_id")) or _optional_text(candidate.get("segment_id")),
        "segment_ids": [
            str(segment_id).strip()
            for segment_id in candidate.get("segment_ids") or [candidate.get("segment_id")]
            if str(segment_id or "").strip()
        ],
        "question_kind": "AFFIRMATION",
        "type": "AFFIRMATION",
        "question_focus": "confirm the detected food",
        "answer_type": "confirm",
        "required": False,
        "label": label,
        "user_prompt": f"I think this is {label}. Is that right?",
        "choices": [
            {"choice_id": "approve", "label": "Yes"},
            {"choice_id": "correct", "label": "No"},
        ],
        "validation_hints": {"required": False, "min_choices": 1, "max_choices": 1},
        "question_examples": [],
    }


def _normalize_answer_type(value: object) -> str:
    if not isinstance(value, str):
        return "free_text"
    normalized = value.strip().lower()
    if normalized in {"single_choice", "multi_choice", "free_text", "confirm"}:
        return normalized
    return "free_text"


def _normalize_question_choices(value: object) -> list[dict[str, Any]]:
    choices: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return choices
    for raw_choice in value:
        if isinstance(raw_choice, Mapping):
            resolved_value = _optional_text(raw_choice.get("label")) or _optional_text(raw_choice.get("value"))
            display_label = (
                _optional_text(raw_choice.get("quick_prompt"))
                or _optional_text(raw_choice.get("label"))
                or _optional_text(raw_choice.get("value"))
                or _optional_text(raw_choice.get("choice_id"))
            )
            if not display_label:
                continue
            raw_choice_id = _optional_text(raw_choice.get("choice_id")) or _optional_text(raw_choice.get("value"))
            choice_id = raw_choice_id or _slugify_choice_id(display_label)
            if choice_id.upper() == "OTHER":
                choice_id = "__other__"
            choice = {
                "choice_id": choice_id,
                "label": display_label,
                "value": resolved_value or display_label,
            }
            for key in ("food_item_id", "source_type", "brand_name", "restaurant_name"):
                extra_value = _optional_text(raw_choice.get(key))
                if extra_value:
                    choice[key] = extra_value
            choices.append(choice)
            continue
        label = _optional_text(raw_choice)
        if label:
            choices.append({"choice_id": _slugify_choice_id(label), "label": label, "value": label})
    return choices


def _normalize_confirm_choices(choices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    defaults = {
        "approve": {"choice_id": "approve", "label": "Yes", "value": "Yes"},
        "correct": {"choice_id": "correct", "label": "No", "value": "No"},
    }
    normalized: dict[str, dict[str, Any]] = {}
    for choice in choices:
        raw_id = str(choice.get("choice_id") or "").strip().lower()
        raw_value = str(choice.get("value") or "").strip().lower()
        raw_label = str(choice.get("label") or "").strip().lower()
        tokens = {raw_id, raw_value, raw_label}
        if tokens & {"approve", "approved", "yes", "y", "true"}:
            canonical = "approve"
        elif tokens & {"correct", "correction", "no", "n", "false", "edit"}:
            canonical = "correct"
        else:
            continue
        normalized.setdefault(
            canonical,
            {
                **defaults[canonical],
                "label": str(choice.get("label") or defaults[canonical]["label"]),
                "value": str(choice.get("value") or choice.get("label") or defaults[canonical]["value"]),
            },
        )
    return [normalized.get("approve", defaults["approve"]), normalized.get("correct", defaults["correct"])]


def _slugify_choice_id(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_") or "choice"


def _coerce_examples(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _first_segment_id(segment_ids: object) -> str | None:
    if not isinstance(segment_ids, list):
        return None
    for segment_id in segment_ids:
        normalized = _optional_text(segment_id)
        if normalized:
            return normalized
    return None


def _remaining_required_question_ids(
    *,
    question_order: list[str],
    questions_by_id: Mapping[str, Any],
    answers_by_question_id: Mapping[str, Any],
) -> list[str]:
    return [
        question_id
        for question_id in question_order
        if bool(dict(questions_by_id.get(question_id) or {}).get("required"))
        and question_id not in answers_by_question_id
    ]


def _current_clarification_question(state: Mapping[str, Any]) -> dict[str, Any] | None:
    question_id = _current_clarification_question_id(state)
    if not question_id:
        return None
    questions_by_id = state.get("questions_by_id") or {}
    question = questions_by_id.get(question_id)
    return dict(question) if isinstance(question, Mapping) else None


def _current_clarification_question_id(state: Mapping[str, Any]) -> str | None:
    remaining_required = [
        str(question_id)
        for question_id in state.get("remaining_required_question_ids") or []
        if str(question_id)
    ]
    if remaining_required:
        return remaining_required[0]
    pending = [
        str(question_id)
        for question_id in state.get("pending_question_ids") or []
        if str(question_id)
    ]
    if pending:
        return pending[0]
    return None


def _render_clarification_question(question: Mapping[str, Any]) -> tuple[str, str]:
    label = _optional_text(question.get("label")) or "this item"
    answer_type = _normalize_answer_type(question.get("answer_type"))
    question_kind = _question_kind(question.get("question_kind"))
    action_type = _question_kind(question.get("type") or question.get("question_kind"))
    user_prompt = _optional_text(question.get("user_prompt") or question.get("prompt"))
    choice_labels = [choice["label"] for choice in _normalize_question_choices(question.get("choices"))]
    if user_prompt:
        if answer_type == "confirm" or action_type == "AFFIRMATION" or question_kind == "AFFIRMATION":
            return user_prompt, "Tap Yes if that's right, or No if it needs correction."
        return user_prompt, user_prompt
    if answer_type == "confirm" or question_kind in {"APPROVAL", "AFFIRMATION"}:
        prompt = f"I likely have {label}. Is that right?"
        return prompt, "Tap Yes if that's right, or No if it needs correction."
    if question_kind == "SOURCE_ORIGIN":
        prompt = f"Was the {label} homemade, packaged, or from a restaurant?"
        return prompt, prompt
    if answer_type == "single_choice":
        question_focus = _optional_text(question.get("question_focus")) or "best match"
        prompt = f"Which {question_focus} best matches the {label}?"
        if choice_labels:
            prompt = f"{prompt} Options: {', '.join(choice_labels)}."
        return prompt, prompt
    return _render_initial_question(target=question, label=label)


def _parse_clarification_text(*, text: str, context: Mapping[str, Any]) -> dict[str, Any]:
    cleaned = _clean_identity_text(text)
    answer_type = _normalize_answer_type(context.get("answer_type"))
    payload: dict[str, Any] = {
        "question_id": context.get("question_id"),
        "group_id": context.get("group_id"),
        "primary_segment_id": context.get("primary_segment_id"),
        "segment_ids": list(context.get("segment_ids") or []),
        "question_kind": _question_kind(context.get("question_kind")),
        "answer_type": answer_type,
        "required": bool(context.get("required")),
        "raw_text": str(text or "").strip(),
        "value": cleaned,
    }
    if answer_type in {"confirm", "single_choice"}:
        matched_choice = _match_question_choice(cleaned=cleaned, context=context)
        if matched_choice is None:
            payload["invalid"] = True
            return payload
        payload["choice_id"] = matched_choice["choice_id"]
        payload["value"] = matched_choice.get("value") or matched_choice["label"]
        if payload["question_kind"] == "SOURCE_ORIGIN":
            source_origin_state = _source_origin_state_from_choice(
                matched_choice["choice_id"],
                matched_choice["label"],
            )
            payload["source_origin_state"] = source_origin_state
            payload["source_type"] = _source_type_from_source_origin_state(source_origin_state)
        elif answer_type == "confirm":
            payload["approval_status"] = _approval_status_from_choice_id(matched_choice["choice_id"])
        else:
            payload["name"] = matched_choice.get("value") or matched_choice["label"]
            payload["approval_status"] = "CORRECTED"
            for key in ("food_item_id", "source_type", "brand_name", "restaurant_name"):
                if matched_choice.get(key):
                    payload[key] = matched_choice[key]
        return payload
    if answer_type == "multi_choice":
        payload["values"] = [part.strip() for part in re.split(r"\s*,\s*", str(text or "").strip()) if part.strip()]
        return payload
    if payload["question_kind"] == "QUANTITY":
        payload["portion_bucket"] = _infer_portion_bucket(text)
        payload["quantity_display"] = _optional_text(str(text or "").strip())
        return payload
    payload["name"] = cleaned
    payload["approval_status"] = "CORRECTED"
    return payload


def _match_question_choice(*, cleaned: str, context: Mapping[str, Any]) -> dict[str, str] | None:
    choices = _normalize_question_choices(context.get("choices"))
    for choice in choices:
        choice_tokens = {
            str(choice.get("choice_id") or "").casefold(),
            str(choice.get("label") or "").casefold(),
            str(choice.get("value") or "").casefold(),
        }
        if cleaned.casefold() in choice_tokens:
            return choice
    if (
        _normalize_answer_type(context.get("answer_type")) == "confirm"
        or _question_kind(context.get("question_kind")) in {"APPROVAL", "AFFIRMATION"}
    ):
        lowered = cleaned.casefold()
        if lowered in {"yes", "y", "correct", "right", "approve"}:
            return {"choice_id": "approve", "label": "Yes", "value": "Yes"}
        if lowered in {"no", "n", "wrong", "incorrect", "change", "correct it"}:
            return {"choice_id": "correct", "label": "No", "value": "No"}
    return None


def _approval_status_from_choice_id(choice_id: str | None) -> str:
    normalized = str(choice_id or "").strip().upper()
    return "APPROVED" if normalized in {"APPROVE", "APPROVED", "YES", "Y"} else "CORRECTED"


def _source_origin_state_from_choice(choice_id: str, label: str) -> str:
    normalized_choice = str(choice_id or "").strip().upper()
    if normalized_choice in {
        "HOME_COOKED",
        "STORE_BOUGHT_PREPARED",
        "PACKAGED_BRANDED",
        "RESTAURANT",
        "UNKNOWN",
    }:
        return normalized_choice
    lowered = f"{choice_id} {label}".casefold()
    if "home" in lowered or "homemade" in lowered:
        return "HOME_COOKED"
    if "store" in lowered:
        return "STORE_BOUGHT_PREPARED"
    if "pack" in lowered or "brand" in lowered:
        return "PACKAGED_BRANDED"
    if "restaurant" in lowered or "takeout" in lowered:
        return "RESTAURANT"
    return "UNKNOWN"


def _source_type_from_source_origin_state(source_origin_state: str) -> str:
    if source_origin_state == "HOME_COOKED":
        return "HOME"
    if source_origin_state == "RESTAURANT":
        return "RESTAURANT"
    return "PACKAGED"


def _apply_clarification_answer(state: Mapping[str, Any], answer: Mapping[str, Any]) -> dict[str, Any]:
    updated = dict(state)
    question_id = _optional_text(answer.get("question_id"))
    questions_by_id = {
        str(key): dict(value)
        for key, value in dict(updated.get("questions_by_id") or {}).items()
        if isinstance(value, Mapping)
    }
    if not question_id or question_id not in questions_by_id:
        return updated

    answers_by_question_id = {
        str(key): dict(value)
        for key, value in dict(updated.get("answers_by_question_id") or {}).items()
        if isinstance(value, Mapping)
    }
    question = questions_by_id[question_id]
    answer_record = _answer_record_for_question(question=question, answer=answer)
    answers_by_question_id[question_id] = answer_record
    question_order = [str(item) for item in updated.get("question_order") or [] if str(item)]
    correction_question = _build_affirmation_correction_question(
        question=question,
        answer_record=answer_record,
    )
    if correction_question is not None:
        correction_question_id = correction_question["question_id"]
        questions_by_id[correction_question_id] = correction_question
        if correction_question_id not in question_order:
            insertion_index = question_order.index(question_id) + 1 if question_id in question_order else len(question_order)
            question_order.insert(insertion_index, correction_question_id)
    updated["questions_by_id"] = questions_by_id
    updated["question_order"] = question_order
    pending_question_ids = [question_id for question_id in question_order if question_id not in answers_by_question_id]
    remaining_required = _remaining_required_question_ids(
        question_order=question_order,
        questions_by_id=questions_by_id,
        answers_by_question_id=answers_by_question_id,
    )
    updated["answers_by_question_id"] = answers_by_question_id
    updated["pending_question_ids"] = pending_question_ids
    updated["remaining_required_question_ids"] = remaining_required
    updated["answers_by_segment"] = _answers_by_segment_from_clarification_answers(updated)
    messages = [dict(item) for item in updated.get("interview_messages") or [] if isinstance(item, Mapping)]
    messages.append({"role": "user", "payload": dict(answer_record)})
    updated["interview_messages"] = messages
    next_question_id = _current_clarification_question_id(updated)
    if next_question_id is None:
        updated["roadmap_step"] = "CONFIRMATION"
        updated["confirmation_items"] = _confirmation_items_from_clarification_answers(updated)
    else:
        updated["roadmap_step"] = "QUESTION_BATCH"
        updated["current_question_id"] = next_question_id
        updated["current_question"] = current_target_question(updated)
    return updated


def _answer_record_for_question(*, question: Mapping[str, Any], answer: Mapping[str, Any]) -> dict[str, Any]:
    record = {
        "question_id": _optional_text(answer.get("question_id")) or _optional_text(question.get("question_id")),
        "group_id": _optional_text(answer.get("group_id")) or _optional_text(question.get("group_id")),
        "primary_segment_id": _optional_text(answer.get("primary_segment_id")) or _optional_text(question.get("primary_segment_id")),
        "segment_ids": list(answer.get("segment_ids") or question.get("segment_ids") or []),
        "question_kind": _question_kind(answer.get("question_kind") or question.get("question_kind")),
        "answer_type": _normalize_answer_type(answer.get("answer_type") or question.get("answer_type")),
        "required": bool(answer.get("required") if "required" in answer else question.get("required")),
        "label": _optional_text(question.get("label")),
        "type": _optional_text(question.get("type")),
        "choice_id": _optional_text(answer.get("choice_id")),
        "value": answer.get("value"),
        "name": _optional_text(answer.get("name")),
        "food_item_id": _optional_text(answer.get("food_item_id")),
        "source_type": _optional_text(answer.get("source_type")),
        "source_origin_state": _optional_text(answer.get("source_origin_state")),
        "brand_name": _optional_text(answer.get("brand_name")),
        "restaurant_name": _optional_text(answer.get("restaurant_name")),
        "portion_bucket": _optional_text(answer.get("portion_bucket")),
        "quantity_display": _optional_text(answer.get("quantity_display")),
        "approval_status": _optional_text(answer.get("approval_status")),
        "raw_text": _optional_text(answer.get("raw_text")),
    }
    return {key: value for key, value in record.items() if value is not None}


def _build_affirmation_correction_question(
    *,
    question: Mapping[str, Any],
    answer_record: Mapping[str, Any],
) -> dict[str, Any] | None:
    if _approval_status_from_choice_id(_optional_text(answer_record.get("choice_id"))) != "CORRECTED":
        return None
    if _question_kind(question.get("question_kind")) not in {"APPROVAL", "AFFIRMATION"}:
        return None
    group_id = _optional_text(question.get("group_id")) or _optional_text(question.get("question_id")) or "group"
    label = _optional_text(question.get("label")) or "this item"
    correction_question_id = f"{group_id}:correction"
    return {
        "question_id": correction_question_id,
        "group_id": group_id,
        "primary_segment_id": _optional_text(question.get("primary_segment_id")),
        "segment_ids": list(question.get("segment_ids") or []),
        "question_kind": "FREE_TEXT",
        "type": "FREE_TEXT",
        "answer_type": "free_text",
        "required": True,
        "label": label,
        "user_prompt": f"What should I call {label} instead?",
        "validation_hints": {"required": True, "max_length": 220},
        "correction_for_question_id": _optional_text(question.get("question_id")),
    }


def _answers_by_segment_from_clarification_answers(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            key: value
            for key, value in item.items()
            if key not in {"approval_status", "question_id", "answer_type", "required", "choice_id", "value", "raw_text", "type"}
        }
        for item in _confirmation_items_from_clarification_answers(state)
    ]


def _confirmation_items_from_clarification_answers(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    questions_by_id = {
        str(key): dict(value)
        for key, value in dict(state.get("questions_by_id") or {}).items()
        if isinstance(value, Mapping)
    }
    answers_by_question_id = {
        str(key): dict(value)
        for key, value in dict(state.get("answers_by_question_id") or {}).items()
        if isinstance(value, Mapping)
    }
    groups: dict[str, dict[str, Any]] = {}

    for question in questions_by_id.values():
        group_id = _optional_text(question.get("group_id")) or _optional_text(question.get("question_id")) or "group"
        item = groups.setdefault(
            group_id,
            {
                "group_id": group_id,
                "primary_segment_id": _optional_text(question.get("primary_segment_id")),
                "segment_id": _optional_text(question.get("primary_segment_id")) or _first_segment_id(question.get("segment_ids")),
                "segment_ids": list(question.get("segment_ids") or []),
                "name": _optional_text(question.get("label")),
                "source_type": "HOME",
                "portion_bucket": "STANDARD",
            },
        )
        if _question_kind(question.get("question_kind")) in {"APPROVAL", "AFFIRMATION"} and item.get("approval_status") is None:
            item["approval_status"] = "APPROVED"

    for answer in answers_by_question_id.values():
        group_id = _optional_text(answer.get("group_id")) or _optional_text(answer.get("question_id")) or "group"
        item = groups.setdefault(group_id, {"group_id": group_id, "source_type": "HOME", "portion_bucket": "STANDARD"})
        if answer.get("primary_segment_id") and not item.get("primary_segment_id"):
            item["primary_segment_id"] = answer["primary_segment_id"]
        if answer.get("primary_segment_id") and not item.get("segment_id"):
            item["segment_id"] = answer["primary_segment_id"]
        if isinstance(answer.get("segment_ids"), list) and not item.get("segment_ids"):
            item["segment_ids"] = list(answer["segment_ids"])
        question_kind = _question_kind(answer.get("question_kind"))
        if question_kind == "SOURCE_ORIGIN" and answer.get("source_type"):
            item["source_type"] = answer["source_type"]
            if answer.get("source_origin_state"):
                item["source_origin_state"] = answer["source_origin_state"]
        elif question_kind == "QUANTITY":
            if answer.get("portion_bucket"):
                item["portion_bucket"] = answer["portion_bucket"]
            if answer.get("quantity_display"):
                item["quantity_display"] = answer["quantity_display"]
        elif answer.get("name"):
            item["name"] = answer["name"]
            for key in ("food_item_id", "source_type", "brand_name", "restaurant_name"):
                if answer.get(key):
                    item[key] = answer[key]
        if answer.get("approval_status"):
            item["approval_status"] = answer["approval_status"]

    return [
        {key: value for key, value in item.items() if value is not None}
        for _, item in sorted(groups.items())
        if item.get("segment_id") or item.get("primary_segment_id") or item.get("name")
    ]


def _question_with_approval_candidates(
    prompt_payload: Mapping[str, Any],
    *,
    approval_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    question = dict(prompt_payload)
    approvals = [
        _optional_text(candidate.get("proposed_name") or candidate.get("label"))
        for candidate in approval_candidates
    ]
    approvals = [name for name in approvals if name]
    if not approvals:
        return question

    approvals_text = _human_join(approvals)
    prompt = _text(question.get("prompt"), default="Tell me about this meal.")
    question["prompt"] = (
        f"{prompt} I also have {approvals_text} as likely matches. "
        "Confirm or correct those in the same reply if needed."
    )
    invalid_prompt = _text(question.get("invalid_prompt"), default=prompt)
    question["invalid_prompt"] = (
        f"{invalid_prompt} You can also confirm or correct {approvals_text} in the same reply."
    )
    return question


def _human_join(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{', '.join(items[:-1])}, and {items[-1]}"


def _initial_roadmap_step_for_target(target: Mapping[str, Any]) -> str:
    if _question_kind(target.get("question_kind")) == "QUANTITY":
        return "PORTION_CONTEXT"
    return "INITIAL_QUESTION"


def _render_initial_question(
    *,
    target: Mapping[str, Any],
    label: str,
) -> tuple[str, str]:
    question_kind = _question_kind(target.get("question_kind"))
    question_focus = _optional_text(target.get("question_focus")) or ""
    examples = [
        str(example).strip()
        for example in target.get("question_examples") or []
        if str(example).strip()
    ]
    normalized_label = label.lower()
    normalized_focus = question_focus.lower()

    if question_kind == "QUANTITY":
        prompt = (
            f"How much {label} was there? "
            "A short answer like `small bowl`, `2 pieces`, or `half plate` is enough."
        )
        return prompt, prompt

    if normalized_label == "egg curry" and normalized_focus == "vegetable inside egg curry":
        prompt = (
            "I can see the egg curry, but I can't tell which vegetable is in it. "
            "What should I call it? For example: egg curry with bottle gourd, "
            "egg curry with zucchini, or the name you normally use."
        )
        return prompt, prompt

    if question_kind == "DETAIL" and question_focus:
        prompt = f"I can see the {label}, but I can't tell the {question_focus}. What should I call it?"
        if examples:
            prompt = f"{prompt} For example: {', '.join(examples)}, or the name you normally use."
        return prompt, prompt

    prompt = f"What should I call the {label}?"
    if examples:
        prompt = f"{prompt} For example: {', '.join(examples)}, or the name you normally use."
    else:
        prompt = f"{prompt} If my label is off, just tell me the name you normally use."
    return prompt, prompt


def _next_roadmap_step(*, record: Mapping[str, Any], step: str) -> str | None:
    if step == "INITIAL_QUESTION":
        return "FOOD_NAME"
    if step == "FOOD_NAME":
        return "SOURCE_TYPE"
    if step == "SOURCE_TYPE":
        source_type = normalize_source_type(record.get("source_type"))
        if source_type == "PACKAGED":
            return "BRAND_NAME"
        if source_type == "RESTAURANT":
            return "RESTAURANT_NAME"
        return "PORTION_CONTEXT"
    if step in {"BRAND_NAME", "RESTAURANT_NAME"}:
        return "PORTION_CONTEXT"
    if step == "PORTION_CONTEXT":
        return None
    return None


def _keep_or_clean_name(cleaned: str, *, context: Mapping[str, Any]) -> str:
    if _is_keep_current_text(cleaned):
        return _text(context.get("current_name"), default="Unknown food")
    return cleaned


def _keep_or_optional_text(cleaned: str, *, current: object) -> str | None:
    if _is_keep_current_text(cleaned):
        return _optional_text(current)
    if cleaned.casefold() in {"unknown", "none", "no brand", "no restaurant"}:
        return None
    return _optional_text(cleaned)


def _is_keep_current_text(cleaned: str) -> bool:
    return cleaned.casefold() in {"same", "keep", "unchanged", "as is"}


def _parse_source_type(text: str) -> str | None:
    lowered = str(text or "").strip().casefold()
    if any(token in lowered for token in ("home", "homemade", "made at home", "house")):
        return "HOME"
    if any(token in lowered for token in ("packaged", "package", "packet", "brand", "store-bought", "store bought")):
        return "PACKAGED"
    if any(token in lowered for token in ("restaurant", "takeout", "take-away", "take away", "cafe", "café", "vendor")):
        return "RESTAURANT"
    return None


def _infer_portion_bucket(text: str) -> str:
    lowered = str(text or "").strip().casefold()
    if re.search(r"\b(small|half|snack|few bites)\b", lowered):
        return "SMALL"
    if re.search(r"\b(large|big|double|extra|full plate)\b", lowered):
        return "LARGE"
    if re.search(r"\b(standard|medium|regular|normal)\b", lowered):
        return "STANDARD"
    return "STANDARD"


__all__ = [
    "INTERVIEW_ROADMAP",
    "SESSION_MODE_FIX",
    "SESSION_MODE_MEAL",
    "answer_to_confirmation_item",
    "apply_confirmation_edits",
    "build_all_wrong_prompt",
    "build_best_effort_closeout",
    "build_neutral_retry_prompt",
    "build_confirmation_message",
    "build_grounding_reasoning_state",
    "build_interview_turn_state",
    "complete_target_question",
    "confirmation_items_from_state",
    "append_interview_transcript_entry",
    "current_target_question",
    "final_resolution_from_confirmation",
    "finalize_confirmed_interview",
    "get_interview_roadmap",
    "has_deterministic_question_state",
    "is_pinned_chat_update",
    "interview_transcript_from_state",
    "apply_interview_turn_result",
    "json_safe_payload",
    "parse_confirmation_bulk_text",
    "parse_interview_text",
    "persist_interview_step",
    "prepare_fix_interview_session",
    "prepare_interview_session",
    "should_send_single_reminder",
]
