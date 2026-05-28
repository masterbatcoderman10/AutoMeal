from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Mapping

from app.models import MealLog, MealProcessingStatus, MealSegment
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
    targets = list(state.get("pending_targets") or [])
    index = _safe_int(state.get("current_target_index"), default=0)
    if not targets:
        return {"segment_id": None, "prompt": "What is this item?"}
    index = min(max(index, 0), len(targets) - 1)
    target = dict(targets[index])
    label = _optional_text(target.get("label")) or "this item"
    target["prompt"] = f"What is {label}?"
    return target


def complete_target_question(state: Mapping[str, Any], answer: Mapping[str, Any]) -> dict[str, Any]:
    updated = dict(state)
    messages = list(updated.get("interview_messages") or [])
    messages.append({"role": "user", "payload": dict(answer)})
    updated["interview_messages"] = messages
    index = _safe_int(updated.get("current_target_index"), default=0)
    updated["current_target_index"] = index + 1
    targets = list(updated.get("pending_targets") or [])
    if updated["current_target_index"] >= len(targets):
        updated["roadmap_step"] = "CONFIRMATION"
    return updated


def parse_interview_text(*, text: str, context: Mapping[str, Any]) -> dict[str, Any]:
    cleaned = _clean_identity_text(text)
    return {
        "segment_id": context.get("segment_id"),
        "roadmap_step": context.get("roadmap_step"),
        "value": cleaned,
        "fallback": True,
    }


def should_send_single_reminder(
    interview_state: Mapping[str, Any],
    *,
    now: datetime,
    reminder_delay_minutes: int,
) -> bool:
    if interview_state.get("last_reminder_at") is not None:
        return False
    prompted_at = interview_state.get("last_prompted_at")
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
        "segment_id": parsed.segment_id,
        "name": parsed.name,
        "source_type": parsed.source_type,
        "portion_bucket": parsed.portion_bucket,
        "quantity_display": parsed.quantity_display,
        "brand_name": parsed.brand_name,
        "restaurant_name": parsed.restaurant_name,
        "food_item_id": parsed.food_item_id,
        "grounding_prep": build_grounding_prep(dict(answer)),
    }
    return {key: value for key, value in item.items() if value is not None}


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


__all__ = [
    "INTERVIEW_ROADMAP",
    "answer_to_confirmation_item",
    "apply_confirmation_edits",
    "build_all_wrong_prompt",
    "build_best_effort_closeout",
    "build_confirmation_message",
    "complete_target_question",
    "current_target_question",
    "final_resolution_from_confirmation",
    "finalize_confirmed_interview",
    "get_interview_roadmap",
    "is_pinned_chat_update",
    "parse_confirmation_bulk_text",
    "parse_interview_text",
    "should_send_single_reminder",
]
