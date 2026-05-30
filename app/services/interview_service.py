from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Mapping

from sqlalchemy import select

from app.models import DiaryEntry, InterviewMessage, InterviewSession, MealLog, MealProcessingStatus, MealSegment
from app.services.grounding_stub import build_grounding_prep, normalize_source_type
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


def get_interview_roadmap() -> list[str]:
    return list(INTERVIEW_ROADMAP)


def is_pinned_chat_update(callback: object, session: object) -> bool:
    chat = getattr(getattr(callback, "message", None), "chat", None)
    return str(getattr(chat, "id", "")) == str(getattr(session, "chat_id", ""))


def current_target_question(state: Mapping[str, Any]) -> dict[str, Any]:
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
    parts = re.split(r"\s*,\s*|\s+and\s+|\s+second\s+is\s+", text, flags=re.IGNORECASE)
    cleaned_parts = [_clean_identity_text(part) for part in parts if _clean_identity_text(part)]
    if len(cleaned_parts) < len(confirmation_items) and "second is" in text.lower():
        first, second = re.split(r"\bsecond\s+is\b", text, maxsplit=1, flags=re.IGNORECASE)
        cleaned_parts = [_clean_identity_text(first), _clean_identity_text(second)]

    updates: list[dict[str, Any]] = []
    for item, name in zip(confirmation_items, cleaned_parts, strict=False):
        updates.append({"segment_id": item.get("segment_id"), "name": name})
    return {"applied_bulk": bool(updates), "updates": updates}


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
    session.add(
        InterviewMessage(
            id=str(uuid.uuid4()),
            session_id=interview.id,
            role="bot",
            payload={
                "type": "prompt",
                "prompt": dict(prompt_payload.get("current_question") or current_target_question(prompt_payload)),
            },
        )
    )
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
) -> InterviewSession:
    persisted_state = _json_safe_payload(state)
    interview.current_prompt_payload = persisted_state
    interview.state_key = str(persisted_state.get("roadmap_step") or interview.state_key)
    session.add(interview)
    session.add(
        InterviewMessage(
            id=str(uuid.uuid4()),
            session_id=interview.id,
            role="user",
            payload=dict(user_payload),
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
) -> FinalSegmentResolution:
    parsed = InterviewAnswer.from_mapping(item)
    grounding_prep = build_grounding_prep(item)
    needs_grounding = grounding_prep is not None or best_effort
    reasoning = "NEEDS_GROUNDING" if needs_grounding else parsed.evidence
    segment_id = parsed.segment_id or (getattr(segment, "id", None) if segment is not None else None)
    embedding = getattr(segment, "embedding", None) if segment is not None else None
    return FinalSegmentResolution(
        food=ResolvedFoodInput(
            canonical_name=parsed.name,
            food_item_id=parsed.food_item_id,
            aliases=[parsed.name],
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
        segment_embedding=embedding if isinstance(embedding, list) else None,
        portion_bucket=parsed.portion_bucket,
        identification_method="INTERVIEW_BEST_EFFORT" if best_effort else "INTERVIEW",
        quantity_json={"grounding_prep": grounding_prep} if grounding_prep else None,
        quantity_display=parsed.quantity_display,
        create_food_visual=not best_effort,
        visual_learning_eligible=not best_effort,
    )


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
):
    segments_by_id = {segment.id: segment for segment in segments or []}
    final_segments = [
        final_resolution_from_confirmation(
            item=item,
            segment=segments_by_id.get(str(item.get("segment_id"))),
            best_effort=best_effort,
        )
        for item in confirmation_items
    ]
    if any(resolution.food.needs_grounding for resolution in final_segments):
        meal.processing_status = MealProcessingStatus.INTERVIEWING
        meal.reasoning_state_json = build_grounding_reasoning_state(
            confirmation_items=confirmation_items,
            status="PENDING_HANDOFF",
            extra={"handoff_target": "poll_post_interview_grounding"},
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
        reasoning_state_json={
            "completed_by": "interview_service",
            "best_effort": best_effort,
            "confirmation_items": [dict(item) for item in confirmation_items],
            "completed_at": datetime.now(UTC).isoformat(),
        },
    )
    if hasattr(session, "commit"):
        maybe = session.commit()
        if hasattr(maybe, "__await__"):
            await maybe
    return result


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
    action = str(group.get("group_action") or group.get("action") or "").upper()
    state = str(group.get("group_state") or group.get("state") or "").upper()
    return action in {"INTERVIEW", "ASK_CHOICE", "ASK_QUANTITY"} or state in {
        "UNRESOLVED",
        "PENDING_INTERVIEW",
        "PENDING_CHOICE",
        "PARTIAL_RESOLVED_WAITING",
        "INTERVIEWING",
    }


def _group_is_approval_candidate(group: Mapping[str, Any]) -> bool:
    if _group_needs_interview(group):
        return False
    action = str(group.get("group_action") or group.get("action") or "").upper()
    state = str(group.get("group_state") or group.get("state") or "").upper()
    return action in {"AUTO_CONFIRM", "AUTO_CONFIRM_WITH_TRACE", "READY_TO_WRITE"} or state == "READY_TO_WRITE"


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
    "build_confirmation_message",
    "build_grounding_reasoning_state",
    "build_interview_turn_state",
    "complete_target_question",
    "confirmation_items_from_state",
    "current_target_question",
    "final_resolution_from_confirmation",
    "finalize_confirmed_interview",
    "get_interview_roadmap",
    "is_pinned_chat_update",
    "parse_confirmation_bulk_text",
    "parse_interview_text",
    "persist_interview_step",
    "prepare_fix_interview_session",
    "prepare_interview_session",
    "should_send_single_reminder",
]
