from __future__ import annotations

import copy
import json
from typing import Any, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.services.grounding_stub import parse_authoritative_source_type


class ConfirmationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_id: str
    primary_segment_id: str
    segment_id: str
    segment_ids: list[str] = Field(default_factory=list)
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

    @field_validator("segment_ids", mode="before")
    @classmethod
    def _normalize_segment_ids(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("segment_ids must be a list")
        segment_ids: list[str] = []
        for item in value:
            if item is None:
                continue
            segment_id = str(item).strip()
            if segment_id and segment_id not in segment_ids:
                segment_ids.append(segment_id)
        return segment_ids

    @model_validator(mode="after")
    def _ensure_segment_membership(self) -> "ConfirmationItem":
        segment_ids = list(self.segment_ids)
        for segment_id in (self.primary_segment_id, self.segment_id):
            if segment_id and segment_id not in segment_ids:
                segment_ids.append(segment_id)
        self.segment_ids = segment_ids
        return self

    @field_validator("name")
    @classmethod
    def _require_name(cls, value: str | None) -> str:
        if not value:
            raise ValueError("name is required")
        return value

    @field_validator("source_type", mode="before")
    @classmethod
    def _normalize_source(cls, value: object) -> str:
        return parse_authoritative_source_type(value)

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


class FinalResolverResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_action: Literal["ready_to_confirm"]
    assistant_prompt: str
    clarification_reason: str | None
    conversation_summary: str | None
    confirmation_items: list[ConfirmationItem]

    @field_validator("assistant_prompt", mode="before")
    @classmethod
    def _require_prompt(cls, value: object) -> str:
        return InterviewTurnResult._require_prompt(value)

    @field_validator("clarification_reason", "conversation_summary", mode="before")
    @classmethod
    def _normalize_optional_text(cls, value: object) -> str | None:
        return InterviewTurnResult._normalize_optional_text(value)


class FinalizerQuantityPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantity: float | None
    unit: str | None
    portion_bucket: Literal["SMALL", "STANDARD", "LARGE"]

    @field_validator("quantity", mode="before")
    @classmethod
    def _normalize_quantity(cls, value: object) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError("quantity must be numeric or null")
        return float(value)

    @field_validator("unit", mode="before")
    @classmethod
    def _normalize_unit(cls, value: object) -> str | None:
        return InterviewTurnResult._normalize_optional_text(value)

    @field_validator("portion_bucket", mode="before")
    @classmethod
    def _normalize_portion_bucket(cls, value: object) -> str:
        normalized = str(value or "").strip().upper()
        if normalized not in {"SMALL", "STANDARD", "LARGE"}:
            raise ValueError("portion_bucket must be SMALL, STANDARD, or LARGE")
        return normalized


class GroundingTracePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    queries: list[str] = Field(default_factory=list)
    fetched_urls: list[str] = Field(default_factory=list)
    snippet_excerpts: list[str] = Field(default_factory=list)
    provenance: Literal["searched", "model_knowledge"] | None = None
    source_url: str | None = None
    stop_reason: str | None = None
    failure_category: str | None = None
    tool_calls_used: int | None = None
    duplicate_calls: int | None = None
    iteration_count: int | None = None

    @field_validator("queries", "fetched_urls", "snippet_excerpts", mode="before")
    @classmethod
    def _normalize_text_list(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("value must be a list")
        normalized: list[str] = []
        for item in value:
            text = ConfirmationItem._strip_text(item)
            if isinstance(text, str) and text and text not in normalized:
                normalized.append(text)
        return normalized

    @field_validator("provenance", "stop_reason", "failure_category", mode="before")
    @classmethod
    def _normalize_optional_text(cls, value: object) -> str | None:
        return InterviewTurnResult._normalize_optional_text(value)

    @field_validator("source_url", mode="before")
    @classmethod
    def _normalize_optional_url(cls, value: object) -> str | None:
        return InterviewTurnResult._normalize_optional_text(value)

    @field_validator("tool_calls_used", "duplicate_calls", "iteration_count", mode="before")
    @classmethod
    def _normalize_optional_int(cls, value: object) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("value must be an integer or null")
        if value < 0:
            raise ValueError("value must be >= 0")
        return value


class FinalizedGroupResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_id: str
    primary_segment_id: str
    segment_ids: list[str]
    final_name: str
    aliases: list[str]
    source_type: Literal["HOME", "PACKAGED", "RESTAURANT"]
    portion_bucket: Literal["SMALL", "STANDARD", "LARGE"]
    quantity_display: str | None
    quantity_json: FinalizerQuantityPayload | None
    food_item_id: str | None
    brand_name: str | None
    restaurant_name: str | None
    correction_note: str | None
    supporting_details: list[str]
    serving_size_g: float | None = None
    calories: float | None = None
    protein_g: float | None = None
    carbs_g: float | None = None
    fat_g: float | None = None
    fiber_g: float | None = None
    is_verified: bool = False
    provenance: Literal["searched", "model_knowledge"] | None = None
    source_url: str | None = None
    grounding_trace: GroundingTracePayload | None = None

    @field_validator(
        "group_id",
        "primary_segment_id",
        "final_name",
        "quantity_display",
        "food_item_id",
        "brand_name",
        "restaurant_name",
        "correction_note",
        "provenance",
        "source_url",
        mode="before",
    )
    @classmethod
    def _strip_text(cls, value: object) -> object:
        return ConfirmationItem._strip_text(value)

    @field_validator("aliases", "supporting_details", mode="before")
    @classmethod
    def _normalize_text_lists(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            raise ValueError("value must be a list")
        normalized: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError("list items must be strings")
            stripped = item.strip()
            if stripped and stripped not in normalized:
                normalized.append(stripped)
        return normalized

    @field_validator("segment_ids", mode="before")
    @classmethod
    def _normalize_segment_ids(cls, value: object) -> list[str]:
        return ConfirmationItem._normalize_segment_ids(value)

    @field_validator(
        "serving_size_g",
        "calories",
        "protein_g",
        "carbs_g",
        "fat_g",
        "fiber_g",
        mode="before",
    )
    @classmethod
    def _normalize_optional_float(cls, value: object) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError("value must be numeric or null")
        parsed = float(value)
        if parsed < 0:
            raise ValueError("value must be >= 0")
        return parsed

    @field_validator("final_name")
    @classmethod
    def _require_final_name(cls, value: str | None) -> str:
        if not value:
            raise ValueError("final_name is required")
        return value

    @field_validator("source_type", mode="before")
    @classmethod
    def _normalize_source_type(cls, value: object) -> str:
        return parse_authoritative_source_type(value)

    @field_validator("portion_bucket", mode="before")
    @classmethod
    def _normalize_portion_bucket(cls, value: object) -> str:
        return ConfirmationItem._normalize_portion_bucket(value)

    @model_validator(mode="after")
    def _validate_scope_and_metadata(self) -> "FinalizedGroupResult":
        if not self.segment_ids:
            raise ValueError("segment_ids must include at least one segment id")
        if self.primary_segment_id not in self.segment_ids:
            self.segment_ids = [*self.segment_ids, self.primary_segment_id]
        if self.quantity_json is not None and self.quantity_json.portion_bucket != self.portion_bucket:
            raise ValueError("quantity_json.portion_bucket must match portion_bucket")
        _validate_group_source_metadata(
            group_id=self.group_id,
            source_type=self.source_type,
            brand_name=self.brand_name,
            restaurant_name=self.restaurant_name,
        )
        return self


class InterviewTurnValidationError(ValueError):
    pass


def interview_turn_response_format() -> dict[str, Any]:
    return _response_format_for_model(FinalResolverResult, schema_name="interview_turn_contract_v1")


def group_finalizer_response_format() -> dict[str, Any]:
    return _response_format_for_model(FinalizedGroupResult, schema_name="group_finalizer_contract_v1")


def parse_interview_turn_result(
    payload: str | Mapping[str, Any],
    *,
    active_group_ids: Sequence[str],
    resolver_only: bool = False,
) -> InterviewTurnResult:
    try:
        if isinstance(payload, str):
            result = InterviewTurnResult.model_validate_json(payload)
        else:
            result = InterviewTurnResult.model_validate(payload)
    except ValidationError as exc:
        raise InterviewTurnValidationError(str(exc)) from exc

    _validate_turn_result(
        result,
        active_group_ids=active_group_ids,
        resolver_only=resolver_only,
    )
    return result


def parse_interview_turn_response_payload(
    response_payload: Mapping[str, Any],
    *,
    active_group_ids: Sequence[str],
    resolver_only: bool = False,
) -> InterviewTurnResult:
    return parse_interview_turn_result(
        _extract_message_content(response_payload),
        active_group_ids=active_group_ids,
        resolver_only=resolver_only,
    )


def parse_group_finalizer_result(
    payload: str | Mapping[str, Any],
    *,
    expected_group_id: str | None = None,
) -> FinalizedGroupResult:
    try:
        if isinstance(payload, str):
            result = FinalizedGroupResult.model_validate_json(payload)
        else:
            result = FinalizedGroupResult.model_validate(payload)
    except ValidationError as exc:
        raise InterviewTurnValidationError(str(exc)) from exc

    normalized_expected_group_id = str(expected_group_id or "").strip()
    if normalized_expected_group_id and result.group_id != normalized_expected_group_id:
        raise InterviewTurnValidationError(
            f"finalizer group mismatch; expected {normalized_expected_group_id}, got {result.group_id}"
        )
    return result


def parse_group_finalizer_response_payload(
    response_payload: Mapping[str, Any],
    *,
    expected_group_id: str | None = None,
) -> FinalizedGroupResult:
    return parse_group_finalizer_result(
        _extract_message_content(response_payload),
        expected_group_id=expected_group_id,
    )


def _validate_turn_result(
    result: InterviewTurnResult,
    *,
    active_group_ids: Sequence[str],
    resolver_only: bool = False,
) -> None:
    if resolver_only and result.turn_action != "ready_to_confirm":
        raise InterviewTurnValidationError("final resolver must emit ready_to_confirm")
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
    try:
        _validate_group_source_metadata(
            group_id=item.group_id,
            source_type=item.source_type,
            brand_name=item.brand_name,
            restaurant_name=item.restaurant_name,
        )
    except ValueError as exc:
        raise InterviewTurnValidationError(str(exc)) from exc


def _validate_group_source_metadata(
    *,
    group_id: str,
    source_type: str,
    brand_name: str | None,
    restaurant_name: str | None,
) -> None:
    if brand_name and restaurant_name:
        raise ValueError(f"group {group_id} cannot contain both brand_name and restaurant_name")
    if source_type == "HOME" and (brand_name or restaurant_name):
        raise ValueError(f"group {group_id} cannot include brand or restaurant metadata for HOME items")
    if source_type == "PACKAGED" and restaurant_name:
        raise ValueError(f"group {group_id} cannot include restaurant_name for PACKAGED items")
    if source_type == "RESTAURANT" and brand_name:
        raise ValueError(f"group {group_id} cannot include brand_name for RESTAURANT items")


def _response_format_for_model(model: type[BaseModel], *, schema_name: str) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": schema_name,
            "strict": True,
            "schema": _inline_schema_refs(model.model_json_schema()),
        },
    }


def _inline_schema_refs(schema: dict[str, Any]) -> dict[str, Any]:
    schema_copy = copy.deepcopy(schema)
    definitions = schema_copy.pop("$defs", {})
    return _resolve_schema_refs(schema_copy, definitions)


def _resolve_schema_refs(node: Any, definitions: Mapping[str, Any]) -> Any:
    if isinstance(node, list):
        return [_resolve_schema_refs(item, definitions) for item in node]
    if not isinstance(node, dict):
        return node

    if "$ref" in node:
        ref_name = str(node["$ref"]).rsplit("/", 1)[-1]
        resolved = copy.deepcopy(definitions.get(ref_name, {}))
        merged = {**resolved, **{key: value for key, value in node.items() if key != "$ref"}}
        return _resolve_schema_refs(merged, definitions)

    resolved_node = {
        key: _resolve_schema_refs(value, definitions)
        for key, value in node.items()
        if key != "$defs"
    }
    if "const" in resolved_node:
        resolved_node["enum"] = [resolved_node.pop("const")]
    return resolved_node


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
    "FinalizedGroupResult",
    "FinalizerQuantityPayload",
    "InterviewTurnResult",
    "InterviewTurnValidationError",
    "group_finalizer_response_format",
    "interview_turn_response_format",
    "parse_group_finalizer_response_payload",
    "parse_group_finalizer_result",
    "parse_interview_turn_response_payload",
    "parse_interview_turn_result",
]
