from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal, Mapping

from app.services.llm_client import OpenRouterClient

DETECT_CONFIDENCE_THRESHOLD = 0.75


@dataclass(frozen=True)
class DetectDecision:
    is_food: bool
    confidence: float
    next_action: Literal["skip", "segment"]


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


__all__ = [
    "DETECT_CONFIDENCE_THRESHOLD",
    "detect_prompt",
    "detect_response_format",
    "detect_food_photo",
    "DetectDecision",
]
