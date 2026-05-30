from __future__ import annotations

import json
from typing import Any, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from app.services.grounding_stub import normalize_source_type


class ConfirmationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_id: str
    primary_segment_id: str
    segment_id: str
    name: str
    source_type: Literal["HOME", "PACKAGED", "RESTAURANT"]
    portion_bucket: Literal["SMALL", "STANDARD", "LARGE"]
    approval_status: Literal["APPROVED", "CORRECTED"]
    quantity_display: str | None = None
    brand_name: str | None = None
    restaurant_name: str | None = None
    food_item_id: str | None = None
    correction_note: str | None = None

    @field_validator(
        "group_id",
        "primary_segment_id",
        "segment_id",
        "name",
        "quantity_display",
        "brand_name",
        "restaurant_name",
        "food_item_id",
        "correction_note",
        mode="before",
    )
    @classmethod
    def _strip_text(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        return stripped or None

    @field_validator("name")
    @classmethod
    def _require_name(cls, value: str | None) -> str:
        if not value:
            raise ValueError("name is required")
        return value

    @field_validator("source_type", mode="before")
    @classmethod
    def _normalize_source(cls, value: object) -> str:
        return normalize_source_type(value)

    @field_validator("portion_bucket", mode="before")
    @classmethod
    def _normalize_portion_bucket(cls, value: object) -> str:
        normalized = str(value or "").strip().upper()
        return normalized or "STANDARD"


class InterviewTurnResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_action: Literal["continue_interview", "need_clarification", "ready_to_confirm"]
    assistant_prompt: str
    clarification_reason: str | None
    conversation_summary: str | None
    confirmation_items: list[ConfirmationItem]

    @field_validator("assistant_prompt", mode="before")
    @classmethod
    def _require_prompt(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("assistant_prompt must be a string")
        stripped = value.strip()
        if not stripped:
            raise ValueError("assistant_prompt must not be empty")
        return stripped

    @field_validator("clarification_reason", "conversation_summary", mode="before")
    @classmethod
    def _normalize_optional_text(cls, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("optional text fields must be strings or null")
        stripped = value.strip()
        return stripped or None


class InterviewTurnValidationError(ValueError):
    pass


def interview_turn_response_format() -> dict[str, Any]:
    schema = InterviewTurnResult.model_json_schema()
    definitions = schema.pop("$defs", {})
    confirmation_items = schema.get("properties", {}).get("confirmation_items")
    if isinstance(confirmation_items, dict):
        item_schema = confirmation_items.get("items")
        if isinstance(item_schema, dict) and "$ref" in item_schema:
            ref_name = str(item_schema["$ref"]).rsplit("/", 1)[-1]
            resolved = definitions.get(ref_name)
            if isinstance(resolved, dict):
                confirmation_items["items"] = resolved
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "interview_turn_contract_v1",
            "strict": True,
            "schema": schema,
        },
    }


def parse_interview_turn_result(
    payload: str | Mapping[str, Any],
    *,
    active_group_ids: Sequence[str],
) -> InterviewTurnResult:
    try:
        if isinstance(payload, str):
            result = InterviewTurnResult.model_validate_json(payload)
        else:
            result = InterviewTurnResult.model_validate(payload)
    except ValidationError as exc:
        raise InterviewTurnValidationError(str(exc)) from exc

    _validate_turn_result(result, active_group_ids=active_group_ids)
    return result


def parse_interview_turn_response_payload(
    response_payload: Mapping[str, Any],
    *,
    active_group_ids: Sequence[str],
) -> InterviewTurnResult:
    return parse_interview_turn_result(
        _extract_message_content(response_payload),
        active_group_ids=active_group_ids,
    )


def _validate_turn_result(
    result: InterviewTurnResult,
    *,
    active_group_ids: Sequence[str],
) -> None:
    if result.turn_action != "ready_to_confirm":
        if result.confirmation_items:
            raise InterviewTurnValidationError(
                f"{result.turn_action} must not include confirmation_items"
            )
        return

    if not result.confirmation_items:
        raise InterviewTurnValidationError("ready_to_confirm requires confirmation_items")

    expected_group_ids = [group_id.strip() for group_id in active_group_ids if isinstance(group_id, str) and group_id.strip()]
    seen_group_ids = [item.group_id for item in result.confirmation_items]

    duplicates = {group_id for group_id in seen_group_ids if seen_group_ids.count(group_id) > 1}
    if duplicates:
        raise InterviewTurnValidationError(f"duplicate confirmation items for groups: {sorted(duplicates)}")

    if set(seen_group_ids) != set(expected_group_ids):
        missing = sorted(set(expected_group_ids) - set(seen_group_ids))
        unexpected = sorted(set(seen_group_ids) - set(expected_group_ids))
        raise InterviewTurnValidationError(
            f"confirmation coverage mismatch; missing={missing} unexpected={unexpected}"
        )

    for item in result.confirmation_items:
        _validate_confirmation_item(item)


def _validate_confirmation_item(item: ConfirmationItem) -> None:
    if item.brand_name and item.restaurant_name:
        raise InterviewTurnValidationError(
            f"group {item.group_id} cannot contain both brand_name and restaurant_name"
        )
    if item.source_type == "HOME" and (item.brand_name or item.restaurant_name):
        raise InterviewTurnValidationError(
            f"group {item.group_id} cannot include brand or restaurant metadata for HOME items"
        )
    if item.source_type == "PACKAGED" and item.restaurant_name:
        raise InterviewTurnValidationError(
            f"group {item.group_id} cannot include restaurant_name for PACKAGED items"
        )
    if item.source_type == "RESTAURANT" and item.brand_name:
        raise InterviewTurnValidationError(
            f"group {item.group_id} cannot include brand_name for RESTAURANT items"
        )


def _extract_message_content(response_payload: Mapping[str, Any]) -> str:
    choices = response_payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise InterviewTurnValidationError("response payload is missing choices")
    first_choice = choices[0]
    message = first_choice.get("message") if isinstance(first_choice, Mapping) else None
    if not isinstance(message, Mapping):
        raise InterviewTurnValidationError("response payload is missing message content")
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, Mapping):
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        if parts:
            return "\n".join(parts)
    raise InterviewTurnValidationError(
        f"response payload did not include parseable text content: {json.dumps(response_payload, default=str)}"
    )


__all__ = [
    "ConfirmationItem",
    "InterviewTurnResult",
    "InterviewTurnValidationError",
    "interview_turn_response_format",
    "parse_interview_turn_response_payload",
    "parse_interview_turn_result",
]
