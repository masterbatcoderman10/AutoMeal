from __future__ import annotations

from dataclasses import dataclass


def format_ack_message(meal_id: str) -> str:
    return f"📸 Received, processing… (ID: {meal_id[:8]})"


def format_start_message() -> str:
    return "MealTracker bot is active. Snap a photo and I'll log your meal."


def format_error_message() -> str:
    return "⚠️ Something went wrong processing your meal. I'll retry shortly."


def format_soft_failure_message() -> str:
    return "⚠️ I couldn't confidently segment that meal photo. Please try another photo."


def format_unresolved_match_message(meal_id: str) -> str:
    return (
        f"I see your meal (ID: {meal_id[:8]}), but I don't yet recognize it. "
        "I flagged it for follow-up identification."
    )


@dataclass(frozen=True)
class CompletionItem:
    food_name: str
    portion_bucket: str
    identification_method: str
    is_verified: bool
    calories: float | None = None
    protein_g: float | None = None
    carbs_g: float | None = None
    fat_g: float | None = None


def format_result_sentence(labels: list[str], weak_labels: set[str] | None = None) -> str:
    cleaned: list[str] = []
    seen: set[str] = set()
    weak = {label.strip() for label in weak_labels or set() if label and label.strip()}
    for raw_label in labels:
        if not raw_label:
            continue
        label = raw_label.strip()
        if not label:
            continue
        normalized = label.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        cleaned.append(f"maybe {label}" if label in weak else label)

    item_count = len(cleaned)
    if item_count == 0:
        return "I see your meal."
    return f"I see {item_count} items: {', '.join(cleaned)}."


def _normalize_portion(portion_bucket: str) -> str:
    return portion_bucket.replace("PortionBucket.", "") if portion_bucket else "unknown"


def _format_number(value: float) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    if float(value).is_integer():
        return str(int(value))
    return f"{float(value):.2f}".rstrip("0").rstrip(".")


def _format_item_nutrition(item: CompletionItem) -> str:
    lines: list[str] = []
    if item.calories is not None:
        lines.append(f"Calories: { _format_number(item.calories)} kcal")
    if item.protein_g is not None:
        lines.append(f"Protein: {_format_number(item.protein_g)} g")
    if item.carbs_g is not None:
        lines.append(f"Carbs: {_format_number(item.carbs_g)} g")
    if item.fat_g is not None:
        lines.append(f"Fat: {_format_number(item.fat_g)} g")

    if not lines:
        return "Nutrition: unavailable"
    return " | ".join(lines)


def _sum_known_totals(items: list[CompletionItem]) -> list[str]:
    calories_total = 0.0
    protein_total = 0.0
    carbs_total = 0.0
    fat_total = 0.0
    has_known = {
        "calories": False,
        "protein": False,
        "carbs": False,
        "fat": False,
    }

    for item in items:
        if item.calories is not None:
            calories_total += float(item.calories)
            has_known["calories"] = True
        if item.protein_g is not None:
            protein_total += float(item.protein_g)
            has_known["protein"] = True
        if item.carbs_g is not None:
            carbs_total += float(item.carbs_g)
            has_known["carbs"] = True
        if item.fat_g is not None:
            fat_total += float(item.fat_g)
            has_known["fat"] = True

    totals: list[str] = []
    if has_known["calories"]:
        totals.append(f"Calories: {_format_number(calories_total)} kcal")
    if has_known["protein"]:
        totals.append(f"Protein: {_format_number(protein_total)} g")
    if has_known["carbs"]:
        totals.append(f"Carbs: {_format_number(carbs_total)} g")
    if has_known["fat"]:
        totals.append(f"Fat: {_format_number(fat_total)} g")
    return totals


def format_match_completion_message(items: list[CompletionItem]) -> str:
    if not items:
        return "Meal completed and logged."

    lines: list[str] = []
    for item in items:
        lines.append(
            f"{item.food_name} | portion={_normalize_portion(item.portion_bucket)} | "
            f"method={item.identification_method} | verified={str(item.is_verified).lower()}"
        )
        lines.append(_format_item_nutrition(item))

    totals = _sum_known_totals(items)
    if totals:
        lines.append(f"Total | {' | '.join(totals)}")

    return "\n".join(lines)


__all__ = [
    "CompletionItem",
    "format_ack_message",
    "format_error_message",
    "format_match_completion_message",
    "format_result_sentence",
    "format_soft_failure_message",
    "format_start_message",
    "format_unresolved_match_message",
]
