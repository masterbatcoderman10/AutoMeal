from __future__ import annotations

import copy
import re
import uuid
from datetime import UTC, datetime
from typing import Any, Mapping

from sqlalchemy import select

from app.models import CorrectionEvent, DiaryEntry, FoodItem, FoodVisual, MealSegment
from app.services.grounding_stub import build_grounding_prep, normalize_source_type
from app.services.meal_resolution_service import ResolvedFoodInput, resolve_or_create_food_item


IDENTITY_FIELDS = {"food_name", "name", "canonical_name", "food_item_id", "source_type", "brand_name", "restaurant_name"}
QUANTITY_FIELDS = {"portion_bucket", "quantity", "quantity_json", "quantity_display", "serving_size_g"}
RECENT_ENTRY_LIMIT = 8


def short_entry_id(entry_id: object) -> str:
    return str(entry_id or "").strip()[:8]


def build_recent_entry_record(
    *,
    entry_id: str,
    food_name: str | None = None,
    quantity_display: str | None = None,
    meal_id: str | None = None,
) -> dict[str, Any]:
    return {
        "id": entry_id,
        "short_id": short_entry_id(entry_id),
        "food_name": food_name,
        "quantity_display": quantity_display,
        "meal_id": meal_id,
    }


def remember_recent_entries(
    existing: list[Mapping[str, Any]] | None,
    new_entries: list[Mapping[str, Any]] | None,
    *,
    limit: int = RECENT_ENTRY_LIMIT,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in (list(new_entries or []), list(existing or [])):
        for entry in source:
            entry_id = str(entry.get("id") or "").strip()
            if not entry_id or entry_id in seen:
                continue
            seen.add(entry_id)
            merged.append(dict(entry))
            if len(merged) >= limit:
                return merged
    return merged


def resolve_fix_target(command_text: str, *, recent_entries: list[Mapping[str, Any]]) -> dict[str, Any]:
    tokens = command_text.strip().split()
    if len(tokens) > 1 and tokens[1].strip():
        selector = tokens[1].strip()
        if selector.isdigit():
            index = int(selector) - 1
            if 0 <= index < len(recent_entries):
                choice = dict(recent_entries[index])
                return {"mode": "recent", "entry_id": choice.get("id"), "choices": list(recent_entries), "choice": choice}
        for entry in recent_entries:
            if selector in {str(entry.get("id") or ""), str(entry.get("short_id") or "")}:
                choice = dict(entry)
                return {"mode": "recent", "entry_id": choice.get("id"), "choices": list(recent_entries), "choice": choice}
        return {"mode": "direct", "entry_id": selector}
    if recent_entries:
        choice = dict(recent_entries[0])
        return {"mode": "recent", "entry_id": choice.get("id"), "choices": list(recent_entries), "choice": choice}
    return {"mode": "none", "entry_id": None, "choices": []}


def build_fix_diff(*, before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    keys = sorted(set(before.keys()) | set(after.keys()))
    return {
        "before": {key: before.get(key) for key in keys if key in before},
        "after": {key: after.get(key) for key in keys if key in after},
        "changed_fields": [key for key in keys if before.get(key) != after.get(key)],
    }


def is_identity_fix(patch: Mapping[str, Any]) -> bool:
    return any(key in IDENTITY_FIELDS for key in patch)


def is_quantity_only_fix(patch: Mapping[str, Any]) -> bool:
    return bool(patch) and not is_identity_fix(patch) and all(key in QUANTITY_FIELDS for key in patch)


def visual_learning_eligible_for_relearn(entry: Mapping[str, Any]) -> bool:
    return bool(entry.get("visual_learning_eligible"))


def apply_fix(*, entry: Mapping[str, Any], patch: Mapping[str, Any], confirm: bool) -> dict[str, Any]:
    original = copy.deepcopy(dict(entry))
    if not confirm:
        return {
            "applied": False,
            "reason": "cancelled",
            "entry": original,
            "invalidated_visual_ids": [],
            "write_visual_back": False,
            "recompute_nutrition": False,
        }

    updated_entry = {**original, **dict(patch)}
    identity_change = is_identity_fix(patch)
    invalidated: list[str] = []
    if identity_change and entry.get("food_visual_id"):
        invalidated.append(str(entry["food_visual_id"]))

    grounding_prep = build_grounding_prep(
        {
            "name": updated_entry.get("food_name") or updated_entry.get("name") or updated_entry.get("canonical_name"),
            "source_type": updated_entry.get("source_type"),
            "brand_name": updated_entry.get("brand_name"),
            "restaurant_name": updated_entry.get("restaurant_name"),
        }
    )
    if grounding_prep is not None:
        updated_entry["grounding_prep"] = grounding_prep
        updated_entry["llm_reasoning"] = "NEEDS_GROUNDING"

    quantity_change = any(key in QUANTITY_FIELDS for key in patch)
    return {
        "applied": True,
        "entry": updated_entry,
        "before": original,
        "after": updated_entry,
        "invalidated_visual_ids": invalidated,
        "write_visual_back": identity_change and visual_learning_eligible_for_relearn(entry),
        "recompute_nutrition": quantity_change,
        "grounding_prep": grounding_prep,
    }


def build_correction_history_entry(
    *,
    previous: Mapping[str, Any],
    updated: Mapping[str, Any],
    trace_id: str | None = None,
    side_effects: Mapping[str, Any] | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "previous": copy.deepcopy(dict(previous)),
        "updated": copy.deepcopy(dict(updated)),
        "trace_id": trace_id,
        "side_effects": copy.deepcopy(dict(side_effects or {})),
        "reason": reason,
        "created_at": datetime.now(UTC).isoformat(),
    }


def build_fix_confirmation_payload(*, entry: Mapping[str, Any], patch: Mapping[str, Any]) -> dict[str, Any]:
    applied_preview = apply_fix(entry=entry, patch=patch, confirm=True)
    side_effects = {
        "invalidated_visuals": applied_preview["invalidated_visual_ids"],
        "write_visual_back": applied_preview["write_visual_back"],
        "recompute_nutrition": applied_preview["recompute_nutrition"],
        "needs_grounding": applied_preview.get("grounding_prep") is not None,
    }
    return {
        "status": "pending_confirmation",
        "entry_id": entry.get("id"),
        "diff": build_fix_diff(before=entry, after=applied_preview["entry"]),
        "side_effects": side_effects,
    }


def parse_fix_patch(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if not cleaned:
        return {}
    portion_match = re.search(r"\b(small|standard|large)\b", cleaned, flags=re.IGNORECASE)
    if portion_match and not re.search(r"\bis\b", cleaned, flags=re.IGNORECASE):
        return {"portion_bucket": portion_match.group(1).upper()}
    name = re.sub(r"^(actually\s+)?(it'?s|its|should be|change to)\s+", "", cleaned, flags=re.IGNORECASE).strip(" .")
    return {"food_name": name} if name else {}


def format_fix_summary(result: Mapping[str, Any]) -> str:
    if not result.get("applied"):
        return "Fix cancelled."
    entry = result.get("entry") or {}
    name = entry.get("food_name") or entry.get("name") or "item"
    bits = [f"Updated {name}."]
    invalidated = result.get("invalidated_visual_ids") or []
    if invalidated:
        bits.append(f"Invalidated {len(invalidated)} linked visual.")
    if result.get("recompute_nutrition"):
        bits.append("Nutrition will be recomputed.")
    if result.get("grounding_prep"):
        bits.append("Needs grounding.")
    return " ".join(bits)


async def apply_confirmed_entry_correction(
    *,
    session,
    entry: DiaryEntry,
    patch: Mapping[str, Any],
    reason: str | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    entry_context = await build_entry_correction_context(session=session, entry=entry)
    before = {
        "food_item_id": entry.food_item_id,
        "portion_bucket": entry.portion_bucket,
        "quantity_json": copy.deepcopy(entry.quantity_json),
        "quantity_display": entry.quantity_display,
    }
    result = apply_fix(
        entry=entry_context,
        patch=patch,
        confirm=True,
    )

    if is_identity_fix(patch):
        updated_identity = {**entry_context, **dict(patch)}
        food = ResolvedFoodInput(
            canonical_name=str(
                updated_identity.get("food_name")
                or updated_identity.get("name")
                or updated_identity.get("canonical_name")
                or "Unknown food"
            ),
            food_item_id=updated_identity.get("food_item_id"),
            source_type=normalize_source_type(updated_identity.get("source_type")),
            brand_name=updated_identity.get("brand_name"),
            restaurant_name=updated_identity.get("restaurant_name"),
            is_verified=False,
            needs_grounding=result.get("grounding_prep") is not None,
            llm_reasoning="NEEDS_GROUNDING" if result.get("grounding_prep") else None,
        )
        resolved_food = await resolve_or_create_food_item(session=session, food=food)
        entry.food_item_id = resolved_food.id

    if "portion_bucket" in patch:
        entry.portion_bucket = str(patch["portion_bucket"]).strip().upper()
    if "quantity_json" in patch:
        entry.quantity_json = copy.deepcopy(patch["quantity_json"])
    if "quantity_display" in patch:
        entry.quantity_display = patch["quantity_display"]

    for visual_id in result["invalidated_visual_ids"]:
        visual = await session.get(FoodVisual, visual_id)
        if visual is not None:
            visual.is_invalidated = True
            visual.invalidated_at = datetime.now(UTC)
            visual.invalidation_reason = reason or "manual correction"

    after = {
        "food_item_id": entry.food_item_id,
        "portion_bucket": entry.portion_bucket,
        "quantity_json": copy.deepcopy(entry.quantity_json),
        "quantity_display": entry.quantity_display,
    }
    event = CorrectionEvent(
        id=str(uuid.uuid4()),
        meal_log_id=entry.meal_log_id,
        diary_entry_id=entry.id,
        before_json=before,
        after_json=after,
        visual_learning_eligible=bool(result["write_visual_back"]),
        trace_id=trace_id,
        reason=reason,
        food_visual_id=(result["invalidated_visual_ids"][0] if result["invalidated_visual_ids"] else None),
    )
    session.add(event)
    return {**result, "correction_event": event}


async def build_entry_correction_context(
    *,
    session,
    entry: DiaryEntry,
) -> dict[str, Any]:
    food_item = await session.get(FoodItem, entry.food_item_id)
    segment = await session.get(MealSegment, entry.segment_id) if entry.segment_id else None
    linked_visual = None
    if segment is not None and getattr(segment, "cropped_image_url", None):
        linked_visual_result = await session.execute(
            select(FoodVisual)
            .where(
                FoodVisual.food_item_id == entry.food_item_id,
                FoodVisual.cropped_image_url == segment.cropped_image_url,
                FoodVisual.is_invalidated.is_(False),
            )
            .order_by(FoodVisual.created_at.desc())
            .limit(1)
        )
        linked_visual = linked_visual_result.scalar_one_or_none()

    return {
        "id": entry.id,
        "food_name": getattr(food_item, "name", None),
        "food_item_id": entry.food_item_id,
        "portion_bucket": entry.portion_bucket,
        "quantity_json": copy.deepcopy(entry.quantity_json),
        "quantity_display": entry.quantity_display,
        "source_type": getattr(food_item, "source_type", None),
        "brand_name": getattr(food_item, "brand_name", None),
        "restaurant_name": getattr(food_item, "restaurant_name", None),
        "food_visual_id": getattr(linked_visual, "id", None),
        "visual_learning_eligible": linked_visual is not None,
    }


__all__ = [
    "apply_confirmed_entry_correction",
    "apply_fix",
    "build_entry_correction_context",
    "build_correction_history_entry",
    "build_fix_confirmation_payload",
    "build_fix_diff",
    "build_recent_entry_record",
    "format_fix_summary",
    "is_identity_fix",
    "is_quantity_only_fix",
    "parse_fix_patch",
    "remember_recent_entries",
    "resolve_fix_target",
    "short_entry_id",
    "visual_learning_eligible_for_relearn",
]
