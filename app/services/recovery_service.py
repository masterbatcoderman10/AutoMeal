from __future__ import annotations

import copy
import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload
from telegram import Bot

from app.models import InterviewSession, MealLog, MealProcessingStatus, MealSegment

logger = logging.getLogger(__name__)

MEAL_JANITOR_JOB_ID = "meal-janitor"
MEAL_JANITOR_MACHINE_STATUSES = frozenset(
    {
        MealProcessingStatus.DETECTING.value,
        MealProcessingStatus.SEGMENTING.value,
        MealProcessingStatus.EMBEDDING.value,
        MealProcessingStatus.MATCHING.value,
        MealProcessingStatus.REASONING.value,
    }
)
MEAL_JANITOR_MAX_RECOVERIES = 3
_WAITING_STATES = {"PENDING_CHOICE", "PENDING_INTERVIEW", "PARTIAL_RESOLVED_WAITING"}
_FAILED_REASON = "janitor_stale_retries_exhausted"


def _status_value(status: object) -> str | None:
    if isinstance(status, MealProcessingStatus):
        return status.value
    if isinstance(status, str):
        normalized = status.strip().upper()
        return normalized or None
    return None


def _coerce_attempt_count(value: object) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def _coerce_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return None


def is_recoverable_machine_status(status: object) -> bool:
    return _status_value(status) in MEAL_JANITOR_MACHINE_STATUSES


def is_stale_for_janitor(
    meal: Mapping[str, Any],
    *,
    now: datetime | None = None,
    stale_minutes: int = 5,
) -> bool:
    status = _status_value(meal.get("processing_status"))
    if not is_recoverable_machine_status(status):
        return False

    current_time = now or datetime.now(UTC)
    stale_after = timedelta(minutes=max(1, stale_minutes))
    started_at = _coerce_datetime(meal.get("last_stage_started_at")) or _coerce_datetime(meal.get("updated_at"))
    if started_at is None:
        return False
    return current_time - started_at >= stale_after


def can_retry_recovery(meal: Mapping[str, Any], *, max_recoveries: int = MEAL_JANITOR_MAX_RECOVERIES) -> bool:
    return _coerce_attempt_count(meal.get("recovery_attempt_count")) < max(1, max_recoveries)


def _active_interview_exists(interview_session: Mapping[str, Any] | None) -> bool:
    if not isinstance(interview_session, Mapping):
        return False
    return bool(interview_session.get("is_active"))


def _segment_has_candidate_snapshot(segment: Mapping[str, Any]) -> bool:
    snapshot = segment.get("match_candidates_json")
    return isinstance(snapshot, Mapping) and isinstance(snapshot.get("top_3"), list)


def _segment_has_embedding(segment: Mapping[str, Any]) -> bool:
    embedding = segment.get("embedding")
    return isinstance(embedding, Sequence) and not isinstance(embedding, (str, bytes, bytearray)) and len(embedding) > 0


def _segment_has_crop(segment: Mapping[str, Any]) -> bool:
    crop = segment.get("cropped_image_url")
    return isinstance(crop, str) and bool(crop.strip())


def _has_waiting_reasoning_state(meal: Mapping[str, Any]) -> bool:
    reasoning_state = meal.get("reasoning_state_json")
    if not isinstance(reasoning_state, Mapping):
        return False
    meal_reasoning = reasoning_state.get("meal_reasoning")
    if not isinstance(meal_reasoning, Mapping):
        return False
    return str(meal_reasoning.get("meal_state") or "").strip().upper() in _WAITING_STATES


def select_recovery_target(
    meal: Mapping[str, Any],
    *,
    segments: Sequence[Mapping[str, Any]] | None = None,
    interview_session: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    segment_rows = list(segments or [])
    current_status = _status_value(meal.get("processing_status")) or MealProcessingStatus.DETECTING.value

    if _active_interview_exists(interview_session):
        return {
            "recovery_status": MealProcessingStatus.INTERVIEWING.value,
            "resume_basis": "interview_session",
        }

    if segment_rows and all(_segment_has_candidate_snapshot(segment) for segment in segment_rows):
        return {
            "recovery_status": MealProcessingStatus.MATCHING.value,
            "resume_basis": "candidate_snapshots",
        }

    if segment_rows and all(_segment_has_embedding(segment) for segment in segment_rows):
        return {
            "recovery_status": MealProcessingStatus.MATCHING.value,
            "resume_basis": "embeddings",
        }

    if segment_rows and all(_segment_has_crop(segment) for segment in segment_rows):
        return {
            "recovery_status": MealProcessingStatus.EMBEDDING.value,
            "resume_basis": "crops",
        }

    if current_status in {
        MealProcessingStatus.SEGMENTING.value,
        MealProcessingStatus.EMBEDDING.value,
        MealProcessingStatus.MATCHING.value,
        MealProcessingStatus.REASONING.value,
    }:
        return {
            "recovery_status": MealProcessingStatus.SEGMENTING.value,
            "resume_basis": "segment_rows" if segment_rows else "machine_stage",
        }

    return {
        "recovery_status": MealProcessingStatus.DETECTING.value,
        "resume_basis": "meal_status",
    }


def mark_recovery_exhausted(meal: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    current_time = now or datetime.now(UTC)
    exhausted = dict(meal)
    exhausted.update(
        {
            "action": "fail",
            "recovery_status": MealProcessingStatus.FAILED.value,
            "processing_status": MealProcessingStatus.FAILED.value,
            "failed_reason": _FAILED_REASON,
            "notify_user": False,
            "last_stage_started_at": None,
            "recovered_at": current_time,
        }
    )
    return exhausted


def enqueue_recovery_notification(meal: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    current_time = now or datetime.now(UTC)
    notification = dict(meal)
    if _coerce_datetime(notification.get("last_recovery_notified_at")) is not None:
        notification["notify_user"] = False
        return notification

    notification["notify_user"] = True
    notification["notification_ready_at"] = current_time
    return notification


def plan_post_recovery_actions(meal: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    if _status_value(meal.get("processing_status")) == MealProcessingStatus.FAILED.value:
        return enqueue_recovery_notification(meal, now=now)
    planned = dict(meal)
    planned["notify_user"] = False
    return planned


def plan_stale_meal_recovery(
    meal: Mapping[str, Any],
    *,
    segments: Sequence[Mapping[str, Any]] | None = None,
    interview_session: Mapping[str, Any] | None = None,
    now: datetime | None = None,
    stale_minutes: int = 5,
    max_recoveries: int = MEAL_JANITOR_MAX_RECOVERIES,
) -> dict[str, Any]:
    current_time = now or datetime.now(UTC)
    current_status = _status_value(meal.get("processing_status"))
    attempts = _coerce_attempt_count(meal.get("recovery_attempt_count"))

    if not is_recoverable_machine_status(current_status):
        return {
            "action": "skip",
            "reason": "non_recoverable_status",
            "recovery_status": current_status,
            "recovery_attempt_count": attempts,
        }

    if _has_waiting_reasoning_state(meal) and _active_interview_exists(interview_session):
        return {
            "action": "recover",
            "reason": "resume_waiting_interview",
            "recovery_status": MealProcessingStatus.INTERVIEWING.value,
            "processing_status": MealProcessingStatus.INTERVIEWING.value,
            "resume_basis": "interview_session",
            "recovery_attempt_count": attempts + 1,
            "last_stage_started_at": None,
            "notify_user": False,
            "failed_reason": None,
        }

    if not is_stale_for_janitor(meal, now=current_time, stale_minutes=stale_minutes):
        return {
            "action": "skip",
            "reason": "not_stale",
            "recovery_status": current_status,
            "recovery_attempt_count": attempts,
        }

    if not can_retry_recovery(meal, max_recoveries=max_recoveries):
        exhausted = mark_recovery_exhausted(
            {
                **meal,
                "recovery_attempt_count": attempts,
            },
            now=current_time,
        )
        return enqueue_recovery_notification(exhausted, now=current_time)

    target = select_recovery_target(
        meal,
        segments=segments,
        interview_session=interview_session,
    )
    target_status = _status_value(target.get("recovery_status")) or MealProcessingStatus.DETECTING.value
    return {
        **dict(meal),
        "action": "recover",
        "reason": "stale_machine_stage",
        "recovery_status": target_status,
        "processing_status": target_status,
        "resume_basis": target.get("resume_basis"),
        "recovery_attempt_count": attempts + 1,
        "last_stage_started_at": current_time if is_recoverable_machine_status(target_status) else None,
        "failed_reason": None,
        "notify_user": False,
    }


def _serialize_meal(meal: MealLog) -> dict[str, Any]:
    return {
        "meal_id": meal.id,
        "processing_status": meal.processing_status.value,
        "last_stage_started_at": meal.last_stage_started_at,
        "updated_at": meal.updated_at,
        "recovery_attempt_count": meal.recovery_attempt_count,
        "last_recovery_notified_at": meal.last_recovery_notified_at,
        "reasoning_state_json": copy.deepcopy(meal.reasoning_state_json),
    }


def _serialize_segment(segment: MealSegment) -> dict[str, Any]:
    return {
        "segment_id": segment.id,
        "cropped_image_url": segment.cropped_image_url,
        "embedding": list(segment.embedding) if isinstance(segment.embedding, list) else segment.embedding,
        "match_candidates_json": copy.deepcopy(segment.match_candidates_json),
    }


def _serialize_interview(session: InterviewSession | None) -> dict[str, Any] | None:
    if session is None:
        return None
    return {
        "session_id": session.id,
        "meal_log_id": session.meal_log_id,
        "is_active": session.is_active,
        "last_bot_message_id": session.last_bot_message_id,
        "current_prompt_payload": copy.deepcopy(session.current_prompt_payload),
        "updated_at": session.updated_at,
    }


def _merge_janitor_metadata(meal: MealLog, plan: Mapping[str, Any], *, now: datetime) -> dict[str, Any]:
    metadata = copy.deepcopy(meal.reasoning_state_json) if isinstance(meal.reasoning_state_json, Mapping) else {}
    janitor_metadata = {
        "action": plan.get("action"),
        "reason": plan.get("reason"),
        "resume_basis": plan.get("resume_basis"),
        "failed_reason": plan.get("failed_reason"),
        "recovery_attempt_count": plan.get("recovery_attempt_count"),
        "updated_at": now.isoformat(),
    }
    metadata["janitor"] = {key: value for key, value in janitor_metadata.items() if value is not None}
    return metadata


def _apply_recovery_plan(meal: MealLog, plan: Mapping[str, Any], *, now: datetime) -> None:
    meal.recovery_attempt_count = _coerce_attempt_count(plan.get("recovery_attempt_count"))
    meal.last_recovery_notified_at = _coerce_datetime(plan.get("last_recovery_notified_at"))
    meal.reasoning_state_json = _merge_janitor_metadata(meal, plan, now=now)

    next_status = _status_value(plan.get("processing_status") or plan.get("recovery_status"))
    if next_status is not None:
        meal.processing_status = MealProcessingStatus(next_status)
    meal.last_stage_started_at = _coerce_datetime(plan.get("last_stage_started_at"))


async def inspect_meal_recovery(
    session: AsyncSession,
    meal_id: str,
    *,
    now: datetime | None = None,
    stale_minutes: int = 5,
    max_recoveries: int = MEAL_JANITOR_MAX_RECOVERIES,
) -> dict[str, Any] | None:
    statement = (
        select(MealLog)
        .options(selectinload(MealLog.segments))
        .where(MealLog.id == meal_id)
        .limit(1)
    )
    result = await session.execute(statement)
    meal = result.scalar_one_or_none()
    if meal is None:
        return None

    interview_result = await session.execute(
        select(InterviewSession)
        .where(
            InterviewSession.meal_log_id == meal_id,
            InterviewSession.is_active.is_(True),
        )
        .order_by(InterviewSession.updated_at.desc())
        .limit(1)
    )
    interview = interview_result.scalar_one_or_none()
    plan = plan_stale_meal_recovery(
        _serialize_meal(meal),
        segments=[_serialize_segment(segment) for segment in meal.segments],
        interview_session=_serialize_interview(interview),
        now=now,
        stale_minutes=stale_minutes,
        max_recoveries=max_recoveries,
    )
    return {
        "meal": meal,
        "plan": plan,
        "interview_session": interview,
    }


def _janitor_failure_message(meal_id: str) -> str:
    return (
        f"⚠️ Meal {meal_id[:8]} got stuck too many times while I was processing it. "
        "I stopped retrying to avoid duplicate writes. Please resend the photo when ready."
    )


async def run_meal_janitor(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Any,
    bot: Bot | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    current_time = now or datetime.now(UTC)
    processed: list[dict[str, Any]] = []
    stale_minutes = int(getattr(settings, "STALE_TIMEOUT_MINUTES", 5))
    max_recoveries = int(getattr(settings, "MAX_RECOVERY_ATTEMPTS", MEAL_JANITOR_MAX_RECOVERIES))

    async with session_factory() as session:
        statement = (
            select(MealLog)
            .options(selectinload(MealLog.segments))
            .where(MealLog.processing_status.in_(tuple(MEAL_JANITOR_MACHINE_STATUSES)))
            .order_by(MealLog.last_stage_started_at.asc().nullsfirst(), MealLog.updated_at.asc())
            .with_for_update(skip_locked=True)
        )
        result = await session.execute(statement)
        meals = list(result.scalars().unique().all())

        for meal in meals:
            snapshot = await inspect_meal_recovery(
                session,
                meal.id,
                now=current_time,
                stale_minutes=stale_minutes,
                max_recoveries=max_recoveries,
            )
            if snapshot is None:
                continue
            plan = snapshot["plan"]
            if plan.get("action") == "skip":
                continue

            _apply_recovery_plan(meal, plan, now=current_time)
            session.add(meal)
            processed.append(
                {
                    "meal_id": meal.id,
                    "processing_status": meal.processing_status.value,
                    **plan,
                }
            )

        if processed:
            await session.commit()

    if bot is not None:
        for plan in processed:
            if not plan.get("notify_user"):
                continue
            try:
                await bot.send_message(
                    chat_id=getattr(settings, "TELEGRAM_CHAT_ID"),
                    text=_janitor_failure_message(str(plan["meal_id"])),
                )
                async with session_factory() as notify_session:
                    result = await notify_session.execute(
                        select(MealLog)
                        .where(MealLog.id == plan["meal_id"])
                        .limit(1)
                    )
                    notified_meal = result.scalar_one_or_none()
                    if notified_meal is not None:
                        notified_meal.last_recovery_notified_at = datetime.now(UTC)
                        notify_session.add(notified_meal)
                        await notify_session.commit()
            except Exception:
                logger.exception("Failed to send janitor recovery notification", extra={"meal_id": plan.get("meal_id")})

    return processed


__all__ = [
    "MEAL_JANITOR_JOB_ID",
    "MEAL_JANITOR_MACHINE_STATUSES",
    "MEAL_JANITOR_MAX_RECOVERIES",
    "can_retry_recovery",
    "enqueue_recovery_notification",
    "inspect_meal_recovery",
    "is_recoverable_machine_status",
    "is_stale_for_janitor",
    "mark_recovery_exhausted",
    "plan_post_recovery_actions",
    "plan_stale_meal_recovery",
    "run_meal_janitor",
    "select_recovery_target",
]
