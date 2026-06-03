from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping


OTHER_CHOICE_ID = "__other__"
OTHER_CHOICE_LABEL = "Other"


def callback_token(value: str) -> str:
    return hashlib.blake2s(value.encode("utf-8"), digest_size=4).hexdigest()


def meal_callback_token(meal_id: str) -> str:
    return str(meal_id or "").strip()[:8]


def build_interview_callback_data(*, meal_id: str, question_id: str, choice_id: str) -> str:
    return (
        f"interview:{meal_callback_token(meal_id)}:"
        f"{callback_token(question_id)}:{callback_token(choice_id)}"
    )


def resolve_callback_token(values: Iterable[str], token: str) -> str | None:
    token = str(token or "").strip()
    candidates = [str(value) for value in values if str(value)]
    if token in candidates:
        return token
    matches = [value for value in candidates if callback_token(value) == token]
    return matches[0] if len(matches) == 1 else None


def allows_other_choice(prompt: Mapping[str, object]) -> bool:
    answer_type = str(prompt.get("answer_type") or "").strip().lower()
    question_kind = str(prompt.get("question_kind") or "").strip().upper()
    return answer_type == "single_choice" and question_kind != "SOURCE_ORIGIN"
