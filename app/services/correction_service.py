from __future__ import annotations

import copy
import re
import uuid
from datetime import UTC, datetime
from typing import Any, Mapping

from app.models import CorrectionEvent, DiaryEntry, FoodVisual
from app.services.grounding_stub import build_grounding_prep, normalize_source_type
from app.services.meal_resolution_service import ResolvedFoodInput, resolve_or_create_food_item


IDENTITY_FIELDS = {"food_name", "name", "canonical_name", "food_item_id", "source_type", "brand_name", "restaurant_name"}
QUANTITY_FIELDS = {"portion_bucket", "quantity", "quantity_json", "quantity_display", "serving_size_g"}


def resolve_fix_target(command_text: str, *, recent_entries: list[Mapping[str, Any]]) -> dict[str, Any]:
    tokens = command_text.strip().split()
    if len(tokens) > 1 and tokens[1].strip():
        return {"mode": "direct", "entry_id": tokens[1].strip()}
    if recent_entries:
        return {"mode": "recent", "entry_id": recent_entries[0].get("id"), "choices": list(recent_entries)}
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
    before = {
        "food_item_id": entry.food_item_id,
        "portion_bucket": entry.portion_bucket,
        "quantity_json": copy.deepcopy(entry.quantity_json),
        "quantity_display": entry.quantity_display,
    }
    result = apply_fix(
        entry={
            "id": entry.id,
            "food_item_id": entry.food_item_id,
            "portion_bucket": entry.portion_bucket,
            "quantity_json": entry.quantity_json,
            "quantity_display": entry.quantity_display,
            "food_visual_id": patch.get("food_visual_id"),
            "visual_learning_eligible": patch.get("visual_learning_eligible", False),
        },
        patch=patch,
        confirm=True,
    )

    if is_identity_fix(patch):
        food = ResolvedFoodInput(
            canonical_name=str(patch.get("food_name") or patch.get("name") or patch.get("canonical_name") or "Unknown food"),
            food_item_id=patch.get("food_item_id"),
            source_type=normalize_source_type(patch.get("source_type")),
            brand_name=patch.get("brand_name"),
            restaurant_name=patch.get("restaurant_name"),
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


__all__ = [
    "apply_confirmed_entry_correction",
    "apply_fix",
    "build_correction_history_entry",
    "build_fix_confirmation_payload",
    "build_fix_diff",
    "format_fix_summary",
    "is_identity_fix",
    "is_quantity_only_fix",
    "parse_fix_patch",
    "resolve_fix_target",
    "visual_learning_eligible_for_relearn",
]
