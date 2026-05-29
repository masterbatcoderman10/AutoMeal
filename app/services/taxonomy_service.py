from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


class TaxonomyValidationError(ValueError):
    """Raised when the reasoning taxonomy file is malformed."""


def _as_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise TaxonomyValidationError(f"Expected boolean for {field}")
    return value


def _as_float(value: object, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TaxonomyValidationError(f"Expected numeric value for {field}")
    return float(value)


def _as_str(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TaxonomyValidationError(f"Expected non-empty string for {field}")
    return value.strip()


def _as_list(value: object, field: str, *, item_type: type = str) -> list[Any]:
    if not isinstance(value, list):
        raise TaxonomyValidationError(f"Expected list for {field}")
    converted: list[Any] = []
    for idx, item in enumerate(value):
        if not isinstance(item, item_type):
            raise TaxonomyValidationError(
                f"Invalid item type for {field}[{idx}]; expected {item_type.__name__}"
            )
        converted.append(item)
    return converted


def _as_dict(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TaxonomyValidationError(f"Expected mapping for {field}")
    return value


@dataclass(frozen=True)
class ReasoningTaxonomy:
    raw: dict[str, Any]

    @property
    def version(self) -> str:
        return self.raw["version"]

    @property
    def nutrition_impact(self) -> dict[str, Any]:
        return self.raw["nutrition_impact"]

    @property
    def quantity_unit_preferences(self) -> dict[str, Any]:
        return self.raw["quantity_unit_preferences"]

    @property
    def composite_food_handling(self) -> dict[str, Any]:
        return self.raw["composite_food_handling"]

    @property
    def question_budget(self) -> dict[str, Any]:
        return self.raw["question_budget"]


def _validate_taxonomy(payload: dict[str, Any]) -> dict[str, Any]:
    required_root = {
        "version",
        "nutrition_impact",
        "quantity_unit_preferences",
        "composite_food_handling",
        "question_budget",
    }
    present_root = set(payload)
    if present_root != required_root:
        missing = ", ".join(sorted(required_root - present_root))
        extra = ", ".join(sorted(present_root - required_root))
        if missing:
            raise TaxonomyValidationError(f"Missing root fields: {missing}")
        if extra:
            raise TaxonomyValidationError(f"Unexpected root fields: {extra}")
        raise TaxonomyValidationError(f"Invalid taxonomy root shape: {present_root}")

    payload["version"] = _as_str(payload["version"], "version")

    nutrition = _as_dict(payload["nutrition_impact"], "nutrition_impact")
    nutrition_rules = _as_list(
        nutrition.get("high_impact_rules"),
        "nutrition_impact.high_impact_rules",
        item_type=dict,
    )
    for index, rule in enumerate(nutrition_rules):
        rule_dict = _as_dict(rule, f"nutrition_impact.high_impact_rules[{index}]")
        _as_str(rule_dict.get("item_category"), f"nutrition_impact.high_impact_rules[{index}].item_category")
        _as_list(rule_dict.get("required_fields"), f"nutrition_impact.high_impact_rules[{index}].required_fields")
        _as_float(
            rule_dict.get("min_visible_fraction"),
            f"nutrition_impact.high_impact_rules[{index}].min_visible_fraction",
        )
        if not (0.0 <= rule_dict["min_visible_fraction"] <= 1.0):
            raise TaxonomyValidationError(
                f"nutrition_impact.high_impact_rules[{index}].min_visible_fraction must be in [0, 1]"
            )
    _as_float(nutrition.get("specificity_threshold"), "nutrition_impact.specificity_threshold")
    nutrition["specificity_threshold"] = float(nutrition["specificity_threshold"])
    _as_bool(nutrition.get("enabled"), "nutrition_impact.enabled")

    quantity = _as_dict(payload["quantity_unit_preferences"], "quantity_unit_preferences")
    _as_list(quantity.get("open_units"), "quantity_unit_preferences.open_units", item_type=str)
    _as_list(
        quantity.get("discrete_units"),
        "quantity_unit_preferences.discrete_units",
        item_type=str,
    )
    _as_dict(quantity.get("default_ranges"), "quantity_unit_preferences.default_ranges")
    for item, values in quantity["default_ranges"].items():
        values_dict = _as_dict(values, f"quantity_unit_preferences.default_ranges.{item}")
        _as_float(values_dict.get("min"), f"quantity_unit_preferences.default_ranges.{item}.min")
        _as_float(values_dict.get("max"), f"quantity_unit_preferences.default_ranges.{item}.max")
        _as_str(values_dict.get("unit"), f"quantity_unit_preferences.default_ranges.{item}.unit")
        if values_dict["min"] > values_dict["max"]:
            raise TaxonomyValidationError(
                f"quantity_unit_preferences.default_ranges.{item}.min must be <= max"
            )
    _as_list(
        quantity.get("question_budget_priority"),
        "quantity_unit_preferences.question_budget_priority",
        item_type=str,
    )

    composite = _as_dict(payload["composite_food_handling"], "composite_food_handling")
    _as_str(composite.get("default_strategy"), "composite_food_handling.default_strategy")
    split_trigger = _as_dict(composite.get("split_trigger"), "composite_food_handling.split_trigger")
    _as_float(split_trigger.get("min_confidence"), "composite_food_handling.split_trigger.min_confidence")
    _as_bool(
        split_trigger.get("requires_nutrition_impact"),
        "composite_food_handling.split_trigger.requires_nutrition_impact",
    )
    _as_dict(split_trigger, "composite_food_handling.split_trigger")
    if "min_visible_components" in split_trigger:
        min_components = split_trigger["min_visible_components"]
        if isinstance(min_components, bool) or not isinstance(min_components, int):
            raise TaxonomyValidationError(
                "composite_food_handling.split_trigger.min_visible_components must be an integer"
            )
        if min_components < 0:
            raise TaxonomyValidationError(
                "composite_food_handling.split_trigger.min_visible_components must be >= 0"
            )

    _ = _as_list(composite.get("components"), "composite_food_handling.components", item_type=str)
    fallback_behavior = _as_dict(composite.get("fallback_behavior"), "composite_food_handling.fallback_behavior")
    _as_str(
        fallback_behavior.get("unknown_components"),
        "composite_food_handling.fallback_behavior.unknown_components",
    )
    _as_str(
        fallback_behavior.get("all_components_visible"),
        "composite_food_handling.fallback_behavior.all_components_visible",
    )

    question_budget = _as_dict(payload["question_budget"], "question_budget")
    for key in ("per_segment", "per_meal", "max_revisions"):
        value = question_budget.get(key)
        if not isinstance(value, int) or value < 0:
            raise TaxonomyValidationError(f"question_budget.{key} must be a non-negative int")
    for key in ("identity_before_quantity", "high_impact_gate_only"):
        if not isinstance(question_budget.get(key), bool):
            raise TaxonomyValidationError(f"question_budget.{key} must be boolean")

    return payload


def _default_taxonomy_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "reasoning_taxonomy.json"


@lru_cache(maxsize=8)
def load_reasoning_taxonomy(*, path: str | Path | None = None) -> ReasoningTaxonomy:
    taxonomy_path = Path(path) if path is not None else _default_taxonomy_path()
    if not taxonomy_path.exists():
        raise TaxonomyValidationError(f"reasoning taxonomy file missing: {taxonomy_path}")
    if not taxonomy_path.is_file():
        raise TaxonomyValidationError(f"taxonomy path is not a file: {taxonomy_path}")

    try:
        raw_text = taxonomy_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise TaxonomyValidationError(f"unable to read taxonomy file: {exc}") from exc

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise TaxonomyValidationError(f"invalid JSON in taxonomy file: {exc}") from exc
    if not isinstance(payload, dict):
        raise TaxonomyValidationError("taxonomy top-level value must be an object")

    validated = _validate_taxonomy(payload)
    return ReasoningTaxonomy(raw=validated)
