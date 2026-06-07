from __future__ import annotations

from typing import Any, Mapping


GROUNDING_REQUIRED_SOURCES = {"PACKAGED", "RESTAURANT"}
AUTHORITATIVE_SOURCE_TYPES = {"HOME", "PACKAGED", "RESTAURANT"}


def normalize_source_type(value: object) -> str:
    if not isinstance(value, str):
        return "HOME"
    normalized = value.strip().upper()
    if normalized in AUTHORITATIVE_SOURCE_TYPES:
        return normalized
    return "HOME"


def parse_authoritative_source_type(value: object) -> str:
    normalized = normalize_source_type(value)
    raw_value = value if isinstance(value, str) else None
    if raw_value is None or normalized != raw_value.strip().upper():
        raise ValueError("source_type must be HOME, PACKAGED, or RESTAURANT")
    return normalized


def build_grounding_prep(answer: Mapping[str, Any], *, strict: bool = False) -> dict[str, Any] | None:
    source_type = (
        parse_authoritative_source_type(answer.get("source_type"))
        if strict
        else normalize_source_type(answer.get("source_type"))
    )
    if source_type not in GROUNDING_REQUIRED_SOURCES:
        return None

    payload = {
        "status": "NEEDS_GROUNDING",
        "source_type": source_type,
        "canonical_name": str(answer.get("name") or answer.get("canonical_name") or "").strip(),
        "brand_name": str(answer.get("brand_name") or "").strip() or None,
        "restaurant_name": str(answer.get("restaurant_name") or "").strip() or None,
        "package_text": str(answer.get("package_text") or "").strip() or None,
        "menu_context": str(answer.get("menu_context") or "").strip() or None,
    }
    return {key: value for key, value in payload.items() if value is not None}


__all__ = [
    "AUTHORITATIVE_SOURCE_TYPES",
    "GROUNDING_REQUIRED_SOURCES",
    "build_grounding_prep",
    "normalize_source_type",
    "parse_authoritative_source_type",
]
