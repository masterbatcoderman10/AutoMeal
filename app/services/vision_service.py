from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence

from app.services.llm_client import OpenRouterClient

DETECT_CONFIDENCE_THRESHOLD = 0.75
SEGMENT_SCALE = 1000.0
SEGMENT_MIN_AREA = 0.01


@dataclass(frozen=True)
class DetectDecision:
    is_food: bool
    confidence: float
    next_action: Literal["skip", "segment"]


@dataclass(frozen=True)
class SegmentDecision:
    box_2d: list[float]
    label_hint: str | None
    confidence: float | None


def detect_prompt(image_url: str) -> list[dict[str, Any]]:
    return [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "Classify this image as food or not-food and return a strict JSON object with keys "
                        "is_food (boolean) and confidence (0..1). "
                        "If any meal is clearly present anywhere in the frame, continue to segment and return is_food true even if clutter "
                        "like utensils, packaging, tables, receipts, or background noise is present."
                    ),
                },
                {
                    "type": "image_url",
                    "image_url": {"url": image_url},
                },
            ],
        }
    ]


def detect_response_format() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "detect_stage",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["is_food", "confidence"],
                "properties": {
                    "is_food": {"type": "boolean"},
                    "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                },
            },
        },
    }


def segment_prompt(image_url: str) -> list[dict[str, Any]]:
    return [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "You are an image-segmentation assistant for meal photos. "
                        "Return food-related regions only. "
                        "Represent each distinct visible food region or container as one box, "
                        "grouping obvious same-food clusters that belong together. "
                        "Create separate boxes only when the same food appears in clearly separate locations. "
                        "Ignore tiny garnish, condiment drops, sauces, and minor crumbs unless they are "
                        "substantial enough to be read as a meaningful side. "
                        "Return a strict JSON object with one key: segments. "
                        "Each segment must include box_2d as [ymin, xmin, ymax, xmax] in 0..1000 coordinates, "
                        "and an optional confidence score."
                    ),
                },
                {
                    "type": "image_url",
                    "image_url": {"url": image_url},
                },
            ],
        }
    ]


def segment_response_format() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "segment_stage",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["segments"],
                "properties": {
                    "segments": {
                        "type": "array",
                        "maxItems": 16,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["box_2d"],
                            "properties": {
                                "box_2d": {
                                    "type": "array",
                                    "minItems": 4,
                                    "maxItems": 4,
                                    "items": {"type": "number"},
                                },
                                "label_hint": {"type": "string"},
                                "confidence": {"type": "number"},
                            },
                        },
                    },
                },
            },
        },
    }


def label_prompt(image_url: str) -> list[dict[str, Any]]:
    return [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "Describe this food crop as one short, human-readable label only. "
                        "Use dish-level labels for mixed dishes (for example, 'chicken curry'), "
                        "and ingredient-level labels only when a single simple food item is clearly isolated. "
                        "Do not return garnish, tiny sauce, or crumbs unless substantial."
                    ),
                },
                {
                    "type": "image_url",
                    "image_url": {"url": image_url},
                },
            ],
        }
    ]


def label_response_format() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "label_stage",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["label"],
                "properties": {
                    "label": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 128,
                    },
                },
            },
        },
    }


def _extract_message_content(response: Mapping[str, Any]) -> Any:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first_choice = choices[0]
    if not isinstance(first_choice, Mapping):
        return None
    message = first_choice.get("message")
    if not isinstance(message, Mapping):
        return None
    return message.get("content")


def _parse_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    is_food = payload.get("is_food")
    confidence = payload.get("confidence")

    if type(is_food) is not bool:
        raise ValueError("is_food must be boolean")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ValueError("confidence must be a numeric score")
    if confidence < 0 or confidence > 1:
        raise ValueError("confidence must be in [0,1]")

    return {
        "is_food": is_food,
        "confidence": float(confidence),
    }


def _fallback_skip(confidence: float = 0.0) -> dict[str, Any]:
    return {
        "is_food": False,
        "confidence": confidence,
        "next_action": "skip",
    }


def _coerce_detect_decision(payload: Mapping[str, Any], threshold: float = DETECT_CONFIDENCE_THRESHOLD) -> dict[str, Any]:
    try:
        parsed = _parse_payload(payload)
    except (TypeError, ValueError):
        return _fallback_skip()

    if not parsed["is_food"] or parsed["confidence"] < threshold:
        return {
            "is_food": False,
            "confidence": parsed["confidence"],
            "next_action": "skip",
        }

    return {
        "is_food": True,
        "confidence": parsed["confidence"],
        "next_action": "segment",
    }


def _normalize_payload(raw_content: Any) -> Mapping[str, Any] | None:
    if isinstance(raw_content, Mapping):
        return raw_content
    if not isinstance(raw_content, str):
        return None
    parsed = json.loads(raw_content)
    return parsed if isinstance(parsed, Mapping) else None


def _coerce_box_coordinate(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("segment box coordinate must be numeric")
    return float(value)


def normalize_segment_box(raw_box: Sequence[Any]) -> list[float]:
    if not isinstance(raw_box, Sequence) or isinstance(raw_box, (str, bytes, bytearray)):
        raise ValueError("segment box must be a 4-item sequence")
    if len(raw_box) != 4:
        raise ValueError("segment box must have exactly four coordinates")

    normalized = [
        _coerce_box_coordinate(value) / SEGMENT_SCALE for value in raw_box
    ]

    if any(not math.isfinite(value) for value in normalized):
        raise ValueError("segment box coordinates must be finite")

    y_min, x_min, y_max, x_max = normalized

    if not (0.0 <= y_min < y_max <= 1.0):
        raise ValueError("invalid segment y coordinates")
    if not (0.0 <= x_min < x_max <= 1.0):
        raise ValueError("invalid segment x coordinates")

    area = (y_max - y_min) * (x_max - x_min)
    if area <= SEGMENT_MIN_AREA:
        raise ValueError("segment area is too small")

    return [y_min, x_min, y_max, x_max]


def _coerce_segment_candidates(
    raw_payload: Mapping[str, Any],
    max_segments: int,
) -> list[SegmentDecision]:
    segments = raw_payload.get("segments")
    if segments is None:
        raise ValueError("segment response missing segments")
    if not isinstance(segments, list):
        raise ValueError("segment response must include a list")

    parsed_segments: list[SegmentDecision] = []
    limit = max(0, int(max_segments))
    for segment_payload in segments[:limit]:
        if not isinstance(segment_payload, Mapping):
            raise ValueError("each segment must be an object")

        raw_box = segment_payload.get("box_2d")
        normalized_box = normalize_segment_box(raw_box)

        raw_label_hint = segment_payload.get("label_hint")
        label_hint = None if raw_label_hint is None else str(raw_label_hint)
        raw_confidence = segment_payload.get("confidence")
        confidence = None
        if raw_confidence is not None:
            confidence = _coerce_box_coordinate(raw_confidence)

        parsed_segments.append(
            SegmentDecision(
                box_2d=normalized_box,
                label_hint=label_hint,
                confidence=confidence,
            )
        )

    return parsed_segments


async def detect_food_photo(
    image_url: str,
    *,
    llm_client: OpenRouterClient,
    model: str,
    confidence_threshold: float = DETECT_CONFIDENCE_THRESHOLD,
) -> dict[str, Any]:
    response = await llm_client.chat_completion(
        model=model,
        messages=detect_prompt(image_url),
        response_format=detect_response_format(),
    )
    content = _extract_message_content(response)
    payload = _normalize_payload(content)
    if payload is None:
        return _fallback_skip()
    return _coerce_detect_decision(payload, threshold=confidence_threshold)


async def segment_food_photo(
    image_url: str,
    *,
    llm_client: OpenRouterClient,
    model: str,
    max_segments: int,
) -> list[SegmentDecision]:
    response = await llm_client.chat_completion(
        model=model,
        messages=segment_prompt(image_url),
        response_format=segment_response_format(),
    )
    content = _extract_message_content(response)
    payload = _normalize_payload(content)
    if payload is None:
        return []

    try:
        return _coerce_segment_candidates(payload, max_segments=max_segments)
    except (TypeError, ValueError):
        return []


async def label_food_segment(
    image_url: str,
    *,
    llm_client: OpenRouterClient,
    model: str,
) -> str:
    response = await llm_client.chat_completion(
        model=model,
        messages=label_prompt(image_url),
        response_format=label_response_format(),
    )
    content = _extract_message_content(response)
    payload = _normalize_payload(content)
    if payload is None:
        return "food"

    label = payload.get("label")
    if not isinstance(label, str) or not label.strip():
        return "food"

    return label.strip()


__all__ = [
    "DETECT_CONFIDENCE_THRESHOLD",
    "SEGMENT_SCALE",
    "SEGMENT_MIN_AREA",
    "SegmentDecision",
    "segment_prompt",
    "segment_response_format",
    "segment_food_photo",
    "label_prompt",
    "label_response_format",
    "label_food_segment",
    "detect_prompt",
    "detect_response_format",
    "detect_food_photo",
    "normalize_segment_box",
    "DetectDecision",
]
