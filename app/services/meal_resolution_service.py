from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
import copy
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CorrectionEvent,
    DiaryEntry,
    FoodItem,
    FoodVisual,
    MealLog,
    MealProcessingStatus,
    PortionBucket,
)

from app.services.matching_service import EMBEDDING_DIMENSION


class MealResolutionError(ValueError):
    """Raised when a shared final-write request is malformed."""


@dataclass(frozen=True)
class ResolvedFoodInput:
    canonical_name: str
    food_item_id: str | None = None
    aliases: list[str] | None = None
    source_type: str | None = None
    brand_name: str | None = None
    restaurant_name: str | None = None
    serving_size_g: float | None = None
    calories: float | None = None
    protein_g: float | None = None
    carbs_g: float | None = None
    fat_g: float | None = None
    fiber_g: float | None = None
    llm_reasoning: str | None = None
    times_confirmed: int | None = None
    is_verified: bool = False
    needs_grounding: bool = False


@dataclass(frozen=True)
class FinalSegmentResolution:
    food: ResolvedFoodInput
    segment_id: str | None = None
    segment_cropped_image_url: str | None = None
    segment_embedding: list[float] | None = None
    portion_bucket: str | PortionBucket = PortionBucket.STANDARD
    identification_method: str = "AUTO_CONFIRM"
    quantity_json: dict[str, Any] | None = None
    quantity_display: str | None = None
    create_food_visual: bool = True
    prior_food_visual_id_to_invalidate: str | None = None
    visual_learning_eligible: bool = False
    existing_diary_entry_id: str | None = None
    entry_is_verified: bool | None = None
    correction_reason: str | None = None
    trace_id: str | None = None


@dataclass(frozen=True)
class MealResolutionResult:
    meal: MealLog
    meal_entries: list[DiaryEntry]
    food_visuals: list[FoodVisual]
    correction_events: list[CorrectionEvent]


def _candidate_mapping(value: object | None) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _group_top_candidates(group: dict[str, Any]) -> list[dict[str, Any]]:
    raw_candidates = group.get("top_3")
    if not isinstance(raw_candidates, list):
        return []
    return [dict(candidate) for candidate in raw_candidates if isinstance(candidate, dict)]


def _selected_group_candidate(group: dict[str, Any]) -> dict[str, Any]:
    selected_candidate_id = _normalize_text(group.get("selected_candidate_id"))
    candidates = _group_top_candidates(group)
    if selected_candidate_id is not None:
        for candidate in candidates:
            if _normalize_text(candidate.get("candidate_id")) == selected_candidate_id:
                return candidate
    return candidates[0] if candidates else {}


def build_grouped_final_segment_resolutions(
    *,
    food_groups: list[dict[str, Any]],
    segments: list[Any],
    match_results: list[tuple[Any, Any]],
    trace_id: str | None = None,
) -> list[FinalSegmentResolution]:
    if not isinstance(food_groups, list):
        raise MealResolutionError("food_groups must be a list")

    segments_by_id = {
        str(getattr(segment, "id", "")): segment
        for segment in segments
        if getattr(segment, "id", None) is not None
    }
    match_results_by_segment = {
        str(getattr(segment, "id", "")): result
        for segment, result in match_results
        if getattr(segment, "id", None) is not None
    }

    resolutions: list[FinalSegmentResolution] = []
    for group in food_groups:
        if not isinstance(group, dict):
            continue
        primary_segment_id = _normalize_text(group.get("primary_segment_id"))
        if primary_segment_id is None:
            raise MealResolutionError("group primary_segment_id is required")
        primary_segment = segments_by_id.get(primary_segment_id)
        if primary_segment is None:
            raise MealResolutionError(f"primary segment not found: {primary_segment_id}")

        selected_candidate = _selected_group_candidate(group)
        match_result = match_results_by_segment.get(primary_segment_id)
        canonical_name = (
            _normalize_text(selected_candidate.get("label"))
            or _normalize_text(group.get("group_label"))
            or "unlabeled food"
        )
        portion_bucket = _normalize_text(selected_candidate.get("portion_bucket")) or "STANDARD"
        quantity_payload = _candidate_mapping(selected_candidate.get("quantity_payload"))
        quantity_display = (
            _normalize_text(quantity_payload.get("quantity_label"))
            or _normalize_text(quantity_payload.get("display"))
            or portion_bucket.title()
        )
        quantity_json = {"portion_bucket": portion_bucket}
        if "quantity" in quantity_payload:
            quantity_json["quantity"] = quantity_payload["quantity"]
        if "unit" in quantity_payload:
            quantity_json["unit"] = quantity_payload["unit"]
        if "quantity_confidence" in quantity_payload:
            quantity_json["quantity_confidence"] = quantity_payload["quantity_confidence"]

        result_food_item_id = getattr(match_result, "food_item_id", None) if match_result is not None else None
        group_trace_id = _normalize_text(group.get("trace_id")) or trace_id

        resolutions.append(
            FinalSegmentResolution(
                food=ResolvedFoodInput(
                    canonical_name=canonical_name,
                    food_item_id=_normalize_text(selected_candidate.get("food_item_id")) or result_food_item_id,
                    aliases=[canonical_name],
                    source_type=_normalize_text(selected_candidate.get("source_type"))
                    or _normalize_text(selected_candidate.get("source"))
                    or "vector_match",
                    brand_name=_normalize_text(selected_candidate.get("brand_name")),
                    restaurant_name=_normalize_text(selected_candidate.get("restaurant_name")),
                    llm_reasoning=_normalize_text(group.get("decision_rationale"))
                    or _normalize_text(group.get("gate_reason")),
                    times_confirmed=1,
                    is_verified=True,
                ),
                segment_id=primary_segment_id,
                segment_cropped_image_url=getattr(primary_segment, "cropped_image_url", None),
                segment_embedding=(
                    list(getattr(primary_segment, "embedding", []))
                    if isinstance(getattr(primary_segment, "embedding", None), list)
                    else None
                ),
                portion_bucket=portion_bucket,
                identification_method="AUTO_CONFIRM",
                quantity_json=quantity_json,
                quantity_display=quantity_display,
                create_food_visual=True,
                prior_food_visual_id_to_invalidate=None,
                visual_learning_eligible=True,
                correction_reason=None,
                trace_id=group_trace_id,
            )
        )

    return resolutions


def _normalize_text(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized if normalized else None


def _normalize_identity(value: str | None) -> str | None:
    normalized = _normalize_text(value)
    return normalized.lower() if normalized is not None else None


def _normalize_aliases(aliases: list[str] | None) -> list[str] | None:
    if aliases is None:
        return None
    normalized: list[str] = []
    seen: set[str] = set()
    for alias in aliases:
        normalized_alias = _normalize_text(alias)
        if normalized_alias is None:
            continue
        lowered = normalized_alias.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized.append(normalized_alias)
    return normalized or None


def _coerce_float(value: object | None, *, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MealResolutionError(f"{field} must be numeric")
    parsed = float(value)
    if parsed < 0:
        raise MealResolutionError(f"{field} must be >= 0")
    return parsed


def _coerce_int(value: object | None, *, field: str, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise MealResolutionError(f"{field} must be an integer")
    if value < 0:
        raise MealResolutionError(f"{field} must be >= 0")
    return value


def _identity_condition(column: Any, value: str | None) -> Any:
    normalized = _normalize_identity(value)
    if normalized is None:
        return column.is_(None)
    return func.lower(column) == normalized


def _coerce_portion_bucket(bucket: str | PortionBucket) -> PortionBucket:
    if isinstance(bucket, PortionBucket):
        return bucket
    if not isinstance(bucket, str):
        raise MealResolutionError(f"portion_bucket must be a string, got {type(bucket).__name__}")
    try:
        return PortionBucket(bucket.strip().upper())
    except ValueError as exc:
        raise MealResolutionError(f"invalid portion_bucket: {bucket}") from exc


def _coerce_embedding(embedding: object | None) -> list[float] | None:
    if embedding is None:
        return None
    if isinstance(embedding, (str, bytes, bytearray)):
        raise MealResolutionError("embedding must be a numeric vector")
    if not isinstance(embedding, list):
        raise MealResolutionError("embedding must be a list of numbers")
    parsed: list[float] = []
    for value in embedding:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise MealResolutionError("embedding values must be numeric")
        parsed.append(float(value))
    if len(parsed) != EMBEDDING_DIMENSION:
        raise MealResolutionError(
            f"embedding length mismatch: expected {EMBEDDING_DIMENSION}, got {len(parsed)}"
        )
    return parsed


def _is_food_nutrition_complete(input_payload: ResolvedFoodInput) -> bool:
    nutritional_fields = (
        input_payload.serving_size_g,
        input_payload.calories,
        input_payload.protein_g,
        input_payload.carbs_g,
        input_payload.fat_g,
        input_payload.fiber_g,
    )
    return all(value is not None for value in nutritional_fields)


def _serialize_entry(entry: DiaryEntry) -> dict[str, Any]:
    return {
        "meal_log_id": entry.meal_log_id,
        "food_item_id": entry.food_item_id,
        "segment_id": entry.segment_id,
        "portion_bucket": entry.portion_bucket,
        "identification_method": entry.identification_method,
        "is_verified": entry.is_verified,
        "quantity_json": copy.deepcopy(entry.quantity_json),
        "quantity_display": entry.quantity_display,
    }


async def resolve_or_create_food_item(
    *,
    session: AsyncSession,
    food: ResolvedFoodInput,
) -> FoodItem:
    canonical_name = _normalize_text(food.canonical_name)
    if canonical_name is None:
        raise MealResolutionError("canonical_name is required")

    if food.food_item_id is not None:
        direct = await session.get(FoodItem, food.food_item_id)
        if direct is not None:
            return _apply_food_payload(direct, food)

    name_condition = func.lower(FoodItem.name) == canonical_name.lower()
    source_type_condition = _identity_condition(FoodItem.source_type, food.source_type)
    brand_condition = _identity_condition(FoodItem.brand_name, food.brand_name)
    restaurant_condition = _identity_condition(FoodItem.restaurant_name, food.restaurant_name)

    statement = (
        select(FoodItem)
        .where(
            name_condition,
            source_type_condition,
            brand_condition,
            restaurant_condition,
        )
        .limit(1)
    )
    result = await session.execute(statement)
    existing = result.scalar_one_or_none()
    if existing is not None:
        return _apply_food_payload(existing, food)

    nutrition_complete = _is_food_nutrition_complete(food)
    needs_grounding = bool(food.needs_grounding or not nutrition_complete)
    verified = bool(food.is_verified and not needs_grounding)

    reasoning = food.llm_reasoning
    if needs_grounding and not _normalize_text(reasoning):
        reasoning = "NEEDS_GROUNDING"

    item = FoodItem(
        id=str(uuid.uuid4()),
        name=canonical_name,
        aliases=_normalize_aliases(food.aliases),
        source_type=_normalize_text(food.source_type),
        brand_name=_normalize_text(food.brand_name),
        restaurant_name=_normalize_text(food.restaurant_name),
        serving_size_g=_coerce_float(food.serving_size_g, field="serving_size_g"),
        calories=_coerce_float(food.calories, field="calories"),
        protein_g=_coerce_float(food.protein_g, field="protein_g"),
        carbs_g=_coerce_float(food.carbs_g, field="carbs_g"),
        fat_g=_coerce_float(food.fat_g, field="fat_g"),
        fiber_g=_coerce_float(food.fiber_g, field="fiber_g"),
        times_confirmed=_coerce_int(food.times_confirmed, field="times_confirmed", default=0),
        is_verified=verified,
        llm_reasoning=_normalize_text(reasoning),
    )
    session.add(item)
    return item


def _apply_food_payload(item: FoodItem, payload: ResolvedFoodInput) -> FoodItem:
    if item.name != payload.canonical_name:
        item.name = _normalize_text(payload.canonical_name) or item.name
    normalized_aliases = _normalize_aliases(payload.aliases)
    if normalized_aliases is not None:
        item.aliases = normalized_aliases
    normalized_source_type = _normalize_text(payload.source_type)
    if normalized_source_type is not None:
        item.source_type = normalized_source_type
    normalized_brand = _normalize_text(payload.brand_name)
    if normalized_brand is not None:
        item.brand_name = normalized_brand
    normalized_restaurant = _normalize_text(payload.restaurant_name)
    if normalized_restaurant is not None:
        item.restaurant_name = normalized_restaurant

    serving_size = _coerce_float(payload.serving_size_g, field="serving_size_g")
    if serving_size is not None:
        item.serving_size_g = serving_size
    calories = _coerce_float(payload.calories, field="calories")
    if calories is not None:
        item.calories = calories
    protein = _coerce_float(payload.protein_g, field="protein_g")
    if protein is not None:
        item.protein_g = protein
    carbs = _coerce_float(payload.carbs_g, field="carbs_g")
    if carbs is not None:
        item.carbs_g = carbs
    fat = _coerce_float(payload.fat_g, field="fat_g")
    if fat is not None:
        item.fat_g = fat
    fiber = _coerce_float(payload.fiber_g, field="fiber_g")
    if fiber is not None:
        item.fiber_g = fiber

    if payload.llm_reasoning is not None:
        item.llm_reasoning = payload.llm_reasoning.strip()

    nutrition_complete = _is_food_nutrition_complete(payload)
    needs_grounding = bool(payload.needs_grounding or not nutrition_complete)
    if _normalize_int_override(item.times_confirmed, payload.times_confirmed):
        item.times_confirmed = payload.times_confirmed or item.times_confirmed
    item.is_verified = bool(payload.is_verified and not needs_grounding)
    if needs_grounding and not item.llm_reasoning:
        item.llm_reasoning = "NEEDS_GROUNDING"

    return item


def _normalize_int_override(existing: int, candidate: int | None) -> bool:
    return candidate is not None and candidate != existing and candidate > existing


async def apply_final_meal_resolution(
    *,
    session: AsyncSession,
    meal: MealLog,
    final_segments: list[FinalSegmentResolution],
    meal_status: MealProcessingStatus = MealProcessingStatus.COMPLETED,
    reasoning_state_json: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> MealResolutionResult:
    if not isinstance(final_segments, list):
        raise MealResolutionError("final_segments must be a list")

    if meal is None:
        raise MealResolutionError("meal is required")

    resolved_entries: list[DiaryEntry] = []
    resolved_visuals: list[FoodVisual] = []
    correction_events: list[CorrectionEvent] = []
    current_time = now or datetime.now(UTC)

    for resolution in final_segments:
        if not isinstance(resolution, FinalSegmentResolution):
            raise MealResolutionError("each final segment must be a FinalSegmentResolution")
        if not isinstance(resolution.food, ResolvedFoodInput):
            raise MealResolutionError("FinalSegmentResolution.food must be a ResolvedFoodInput")

        resolved_food = await resolve_or_create_food_item(
            session=session,
            food=resolution.food,
        )

        if resolution.existing_diary_entry_id is not None:
            existing = await session.get(DiaryEntry, resolution.existing_diary_entry_id)
            if existing is None:
                raise MealResolutionError(
                    f"existing_diary_entry_id not found: {resolution.existing_diary_entry_id}"
                )
            if existing.meal_log_id != meal.id:
                raise MealResolutionError("existing entry does not belong to this meal")

            before_json = _serialize_entry(existing)
            existing.food_item_id = resolved_food.id
            existing.segment_id = _normalize_text(resolution.segment_id)
            existing.portion_bucket = str(_coerce_portion_bucket(resolution.portion_bucket).value)
            existing.identification_method = _normalize_text(resolution.identification_method) or existing.identification_method
            existing.is_verified = (
                bool(resolution.entry_is_verified)
                if resolution.entry_is_verified is not None
                else bool(resolved_food.is_verified)
            )
            existing.quantity_json = copy.deepcopy(resolution.quantity_json)
            existing.quantity_display = _normalize_text(resolution.quantity_display)
            after_json = _serialize_entry(existing)

            resolved_entries.append(existing)
            if before_json != after_json:
                correction_events.append(
                    CorrectionEvent(
                        id=str(uuid.uuid4()),
                        meal_log_id=meal.id,
                        diary_entry_id=existing.id,
                        before_json=before_json,
                        after_json=after_json,
                        visual_learning_eligible=bool(resolution.visual_learning_eligible),
                        trace_id=resolution.trace_id,
                        reason=_normalize_text(resolution.correction_reason),
                    )
                )
        else:
            entry = DiaryEntry(
                id=str(uuid.uuid4()),
                meal_log_id=meal.id,
                food_item_id=resolved_food.id,
                segment_id=_normalize_text(resolution.segment_id),
                portion_bucket=str(_coerce_portion_bucket(resolution.portion_bucket).value),
                identification_method=_normalize_text(resolution.identification_method) or "AUTO_CONFIRM",
                is_verified=bool(resolved_food.is_verified),
                quantity_json=copy.deepcopy(resolution.quantity_json),
                quantity_display=_normalize_text(resolution.quantity_display),
            )
            session.add(entry)
            resolved_entries.append(entry)

        if resolution.prior_food_visual_id_to_invalidate is not None:
            prior_visual = await session.get(FoodVisual, resolution.prior_food_visual_id_to_invalidate)
            if prior_visual is not None:
                prior_visual.is_invalidated = True
                prior_visual.invalidated_at = current_time
                prior_visual.invalidation_reason = _normalize_text(
                    resolution.correction_reason
                ) or "identity correction"

        embedding = _coerce_embedding(resolution.segment_embedding)
        if resolution.create_food_visual and embedding is not None:
            if resolution.segment_cropped_image_url is None:
                raise MealResolutionError(
                    "segment_cropped_image_url is required when create_food_visual is true and embedding exists"
                )
            resolved_visuals.append(
                FoodVisual(
                    id=str(uuid.uuid4()),
                    food_item_id=resolved_food.id,
                    cropped_image_url=resolution.segment_cropped_image_url,
                    embedding=embedding,
                    is_invalidated=False,
                )
            )

    if resolved_visuals:
        session.add_all(resolved_visuals)
    if correction_events:
        session.add_all(correction_events)

    if reasoning_state_json is not None:
        meal.reasoning_state_json = copy.deepcopy(reasoning_state_json)
    meal.processing_status = meal_status
    if hasattr(meal, "last_stage_started_at"):
        meal.last_stage_started_at = None

    return MealResolutionResult(
        meal=meal,
        meal_entries=resolved_entries,
        food_visuals=resolved_visuals,
        correction_events=correction_events,
    )


__all__ = [
    "MealResolutionError",
    "ResolvedFoodInput",
    "FinalSegmentResolution",
    "MealResolutionResult",
    "build_grouped_final_segment_resolutions",
    "resolve_or_create_food_item",
    "apply_final_meal_resolution",
]
