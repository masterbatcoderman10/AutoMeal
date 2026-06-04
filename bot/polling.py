from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

import httpx
from openai import APIConnectionError, APIStatusError, AuthenticationError, RateLimitError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.models import InterviewMessage, InterviewSession, MealSegment, MealLog, MealProcessingStatus
from app.services.llm_client import get_llm_client
from app.services import correction_service, interview_service, interview_turn_manager, matching_service, meal_resolution_service
from app.services.image_service import save_segment_crop
from app.services.vision_service import (
    dedupe_overlapping_segments,
    detect_food_photo,
    segment_food_photo_with_retry,
    segment_debug_label,
)
from app.services import reasoning_service
from bot.callback_data import (
    OTHER_CHOICE_ID,
    OTHER_CHOICE_LABEL,
    allows_other_choice,
    build_interview_callback_data,
)
from bot.messages import (
    CompletionItem,
    format_ack_message,
    format_interview_reminder_message,
    format_match_completion_message,
    format_recent_fix_targets,
    format_soft_failure_message,
)

logger = logging.getLogger(__name__)
MEAL_INTERVIEW_KICKOFF_TEXT = (
    "Start the meal interview for this meal. Ask the most useful first question and mention any clear approval candidates "
    "the user can confirm or correct in the same reply."
)
_MACHINE_STAGE_STATUSES = {
    MealProcessingStatus.DETECTING,
    MealProcessingStatus.SEGMENTING,
    MealProcessingStatus.EMBEDDING,
    MealProcessingStatus.MATCHING,
    MealProcessingStatus.REASONING,
}


async def _poll_sleep(delay: float) -> None:
    await asyncio.sleep(delay)


def _normalize_portion_bucket(value: str | None) -> str:
    if not isinstance(value, str):
        return "STANDARD"
    normalized = value.strip().upper()
    if normalized in {"SMALL", "STANDARD", "LARGE"}:
        return normalized
    return "STANDARD"
async def _run_reasoning_pipeline(
    *,
    llm_client,
    meal: MealLog,
    match_results: list[tuple[MealSegment, Any]],
    segments: list[MealSegment],
    session: AsyncSession,
    settings,
) -> tuple[dict[str, Any], dict[str, Any]]:
    reasoning_result, _trace = await reasoning_service.run_reasoning_request(
        llm_client=llm_client,
        meal_id=meal.id,
        meal=meal,
        match_results=match_results,
        settings=settings,
        propagate_errors=True,
    )
    finalization = await reasoning_service.finalize_meal_from_reasoning(
        session=session,
        meal=meal,
        segments=segments,
        match_results=match_results,
        reasoning_payload=reasoning_result,
    )
    return reasoning_result, finalization

def _transition_meal_status(meal: MealLog, status: MealProcessingStatus) -> None:
    meal.processing_status = status
    meal.recovery_attempt_count = int(getattr(meal, "recovery_attempt_count", 0) or 0)
    meal.last_stage_started_at = datetime.now(UTC) if status in _MACHINE_STAGE_STATUSES else None


async def poll_and_acknowledge(bot, settings, poll_interval: float | None = None) -> None:
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
    )
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    interval = poll_interval or settings.BOT_POLL_INTERVAL

    try:
        while True:
            meal: MealLog | None = None
            ack_sent = False
            try:
                async with session_factory() as session:
                    statement = (
                        select(MealLog)
                        .where(MealLog.ack_sent_at.is_(None))
                        .order_by(MealLog.created_at.asc())
                        .limit(1)
                        .with_for_update(skip_locked=True)
                    )
                    result = await session.execute(statement)
                    meal = result.scalar_one_or_none()

                    if meal is not None:
                        await bot.send_message(
                            chat_id=settings.TELEGRAM_CHAT_ID,
                            text=format_ack_message(meal.id),
                        )
                        ack_sent = True
                        meal.ack_sent_at = datetime.now(UTC)
                        if meal.processing_status == MealProcessingStatus.PENDING:
                            _transition_meal_status(meal, MealProcessingStatus.DETECTING)
                        await session.commit()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error in poll_and_acknowledge")
                if ack_sent and meal is not None:
                    try:
                        async with session_factory() as recovery_session:
                            meal.ack_sent_at = datetime.now(UTC)
                            if meal.processing_status == MealProcessingStatus.PENDING:
                                _transition_meal_status(meal, MealProcessingStatus.DETECTING)
                            await recovery_session.merge(meal)
                            await recovery_session.commit()
                    except Exception:
                        logger.exception("Error recovering acknowledged meal state")

            await _poll_sleep(interval)
    finally:
        await engine.dispose()


def _kickoff_validation_fallback_prompt(state: Mapping[str, Any]) -> str:
    question = dict(state.get("current_question") or {})
    prompt = str(question.get("prompt") or "").strip()
    if prompt:
        return f"I couldn't safely generate the first interview prompt. Please answer this meal question: {prompt}"
    return "I couldn't safely generate the first interview prompt. Please tell me what this meal should be called."


def _kickoff_reply_markup(prompt: Mapping[str, Any], *, meal_id: str | None) -> InlineKeyboardMarkup | None:
    answer_type = str(prompt.get("answer_type") or "").strip().lower()
    question_id = str(prompt.get("question_id") or "").strip()
    if answer_type not in {"confirm", "single_choice"} or not meal_id or not question_id:
        return None
    choices = prompt.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    rows = []
    for choice in choices:
        if not isinstance(choice, Mapping):
            continue
        label = str(choice.get("label") or "").strip()
        choice_id = str(choice.get("choice_id") or "").strip()
        if not label or not choice_id:
            continue
        rows.append(
            [
                InlineKeyboardButton(
                    label,
                    callback_data=build_interview_callback_data(
                        meal_id=meal_id,
                        question_id=question_id,
                        choice_id=choice_id,
                    ),
                )
            ]
        )
    if allows_other_choice(prompt):
        rows.append(
            [
                InlineKeyboardButton(
                    OTHER_CHOICE_LABEL,
                    callback_data=build_interview_callback_data(
                        meal_id=meal_id,
                        question_id=question_id,
                        choice_id=OTHER_CHOICE_ID,
                    ),
                )
            ]
        )
    return InlineKeyboardMarkup(rows) if rows else None


async def _start_meal_interview_turn(*, bot, session, interview: InterviewSession, settings) -> interview_turn_manager.InterviewTurnResult | None:
    state = dict(interview.current_prompt_payload or {})
    if interview_service.has_deterministic_question_state(state):
        prompt = interview_service.current_target_question(state)
        sent = await bot.send_message(
            chat_id=interview.chat_id,
            text=prompt["prompt"],
            reply_markup=_kickoff_reply_markup(prompt, meal_id=str(state.get("meal_id") or interview.meal_log_id or "")),
        )
        updated_state = interview_service.append_interview_transcript_entry(
            state,
            role="bot",
            content=prompt["prompt"],
            payload={
                "type": "prompt",
                "prompt": dict(prompt),
            },
            message_id=getattr(sent, "message_id", None),
        )
        updated_state["current_question"] = dict(prompt)
        updated_state["current_question_id"] = prompt.get("question_id")
        updated_state["last_prompted_at"] = datetime.now(UTC)
        interview.current_prompt_payload = interview_service.json_safe_payload(updated_state)
        if isinstance(getattr(sent, "message_id", None), int):
            interview.last_bot_message_id = sent.message_id
        session.add(interview)
        session.add(
            InterviewMessage(
                id=str(uuid.uuid4()),
                session_id=interview.id,
                role="bot",
                payload={
                    "type": "prompt",
                    "prompt": dict(prompt),
                },
                message_id=getattr(sent, "message_id", None) if isinstance(getattr(sent, "message_id", None), int) else None,
            )
        )
        await session.commit()
        return None

    try:
        turn = await interview_turn_manager.run_interview_turn(
            authoritative_state=state,
            transcript=interview_service.interview_transcript_from_state(state),
            latest_user_text=MEAL_INTERVIEW_KICKOFF_TEXT,
            settings=settings,
        )
    except interview_turn_manager.InterviewTurnValidationError as exc:
        fallback_prompt = _kickoff_validation_fallback_prompt(state)
        sent = await bot.send_message(
            chat_id=interview.chat_id,
            text=fallback_prompt,
        )
        failure_state = interview_service.append_interview_transcript_entry(
            state,
            role="bot",
            content=fallback_prompt,
            payload={
                "type": "validation_retry",
                "prompt": fallback_prompt,
                "error": str(exc),
            },
            message_id=getattr(sent, "message_id", None),
        )
        failure_state["last_turn_error"] = str(exc)
        failure_state["last_prompted_at"] = datetime.now(UTC)
        interview.current_prompt_payload = interview_service.json_safe_payload(failure_state)
        if isinstance(getattr(sent, "message_id", None), int):
            interview.last_bot_message_id = sent.message_id
        session.add(interview)
        session.add(
            InterviewMessage(
                id=str(uuid.uuid4()),
                session_id=interview.id,
                role="bot",
                payload={
                    "type": "validation_retry",
                    "prompt": fallback_prompt,
                    "error": str(exc),
                },
                message_id=getattr(sent, "message_id", None) if isinstance(getattr(sent, "message_id", None), int) else None,
            )
        )
        await session.commit()
        return None
    sent = await bot.send_message(
        chat_id=interview.chat_id,
        text=turn.assistant_prompt,
    )
    updated_state = interview_service.apply_interview_turn_result(
        state,
        turn_action=turn.turn_action,
        assistant_prompt=turn.assistant_prompt,
        clarification_reason=turn.clarification_reason,
        conversation_summary=turn.conversation_summary,
        confirmation_items=[item.model_dump(mode="json") for item in turn.confirmation_items],
    )
    updated_state = interview_service.append_interview_transcript_entry(
        updated_state,
        role="bot",
        content=turn.assistant_prompt,
        payload={
            "type": "meal_turn",
            "prompt": turn.assistant_prompt,
            "turn_action": turn.turn_action,
            "clarification_reason": turn.clarification_reason,
        },
        message_id=getattr(sent, "message_id", None),
    )
    updated_state["last_prompted_at"] = datetime.now(UTC)
    interview.current_prompt_payload = interview_service.json_safe_payload(updated_state)
    if isinstance(getattr(sent, "message_id", None), int):
        interview.last_bot_message_id = sent.message_id
    session.add(interview)
    session.add(
        InterviewMessage(
            id=str(uuid.uuid4()),
            session_id=interview.id,
            role="bot",
            payload={
                "type": "meal_turn",
                "prompt": turn.assistant_prompt,
                "turn_action": turn.turn_action,
                "clarification_reason": turn.clarification_reason,
            },
            message_id=getattr(sent, "message_id", None) if isinstance(getattr(sent, "message_id", None), int) else None,
        )
    )
    await session.commit()
    return turn


async def poll_interview_reminders(bot, settings, poll_interval: float | None = None) -> None:
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
    )
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    interval = poll_interval or settings.BOT_POLL_INTERVAL
    delay_seconds = int(getattr(settings, "INTERVIEW_REMINDER_DELAY_SECONDS", 600))

    try:
        while True:
            try:
                async with session_factory() as session:
                    cutoff = datetime.now(UTC) - timedelta(seconds=delay_seconds)
                    statement = (
                        select(InterviewSession)
                        .where(
                            InterviewSession.is_active.is_(True),
                            InterviewSession.last_reminder_at.is_(None),
                            InterviewSession.updated_at <= cutoff,
                        )
                        .order_by(InterviewSession.updated_at.asc())
                        .limit(1)
                        .with_for_update(skip_locked=True)
                    )
                    result = await session.execute(statement)
                    interview = result.scalar_one_or_none()
                    if interview is None:
                        await session.rollback()
                        await _poll_sleep(interval)
                        continue

                    await session.commit()
                    reminder_sent_at = datetime.now(UTC)
                    try:
                        await bot.send_message(
                            chat_id=interview.chat_id,
                            text=format_interview_reminder_message(interview.meal_log_id),
                        )
                    except Exception:
                        logger.exception("Error sending interview reminder")
                    interview.last_reminder_at = reminder_sent_at
                    interview.reminder_count = int(interview.reminder_count or 0) + 1
                    await session.commit()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error in poll_interview_reminders")
            await _poll_sleep(interval)
    finally:
        await engine.dispose()


async def poll_and_detect_food(bot, settings, poll_interval: float | None = None) -> None:
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
    )
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    interval = poll_interval or settings.BOT_POLL_INTERVAL
    llm_client = get_llm_client()

    try:
        while True:
            try:
                async with session_factory() as session:
                    statement = (
                        select(MealLog)
                        .where(MealLog.processing_status == MealProcessingStatus.DETECTING)
                        .order_by(MealLog.created_at.asc())
                        .limit(1)
                        .with_for_update(skip_locked=True)
                    )
                    result = await session.execute(statement)
                    meal = result.scalar_one_or_none()

                    if meal is not None:
                        await session.commit()
                        decision = await detect_food_photo(
                            meal.image_url,
                            llm_client=llm_client,
                            model=settings.DETECT_MODEL,
                        )
                        if decision["next_action"] == "segment":
                            _transition_meal_status(meal, MealProcessingStatus.SEGMENTING)
                        else:
                            _transition_meal_status(meal, MealProcessingStatus.COMPLETED)
                        await session.commit()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error in poll_and_detect_food")

            await asyncio.sleep(interval)
    finally:
        await engine.dispose()


async def poll_and_segment_food(bot, settings, poll_interval: float | None = None) -> None:
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
    )
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    interval = poll_interval or settings.BOT_POLL_INTERVAL
    llm_client = get_llm_client()

    try:
        while True:
            meal: MealLog | None = None
            created_crop_paths: list[Path] = []
            try:
                async with session_factory() as session:
                    statement = (
                        select(MealLog)
                        .where(MealLog.processing_status == MealProcessingStatus.SEGMENTING)
                        .order_by(MealLog.created_at.asc())
                        .limit(1)
                        .with_for_update(skip_locked=True)
                    )
                    result = await session.execute(statement)
                    meal = result.scalar_one_or_none()

                    if meal is None:
                        await session.rollback()
                        await _poll_sleep(interval)
                        continue

                    await session.commit()
                    segments = await segment_food_photo_with_retry(
                        meal.image_url,
                        llm_client=llm_client,
                        model=settings.SEGMENT_MODEL,
                        retry_model=settings.SEGMENT_RETRY_MODEL,
                        max_segments=settings.VISION_MAX_SEGMENTS,
                    )
                    segments = dedupe_overlapping_segments(segments)
                    if not segments:
                        _transition_meal_status(meal, MealProcessingStatus.FAILED)
                        await session.commit()
                        try:
                            await bot.send_message(
                                chat_id=settings.TELEGRAM_CHAT_ID,
                                text=format_soft_failure_message(),
                            )
                        except Exception:
                            logger.exception("Error sending segmentation soft-failure message")
                        continue

                    segment_rows = []
                    for segment in segments:
                        segment_id = str(uuid.uuid4())
                        crop_path = save_segment_crop(
                            source_image_path=Path(meal.image_url),
                            segment_id=segment_id,
                            normalized_box=segment.box_2d,
                            uploads_dir=settings.UPLOADS_DIR,
                        )
                        created_crop_paths.append(crop_path)
                        segment_rows.append(
                            MealSegment(
                                id=segment_id,
                                meal_log_id=meal.id,
                                label=segment_debug_label(segment),
                                bounding_box=segment.box_2d,
                                cropped_image_url=str(crop_path),
                            )
                        )

                    session.add_all(segment_rows)

                    _transition_meal_status(meal, MealProcessingStatus.EMBEDDING)
                    await session.commit()

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error in poll_and_segment_food")
                try:
                    async with session_factory() as session:
                        await session.rollback()
                        if meal is not None:
                            _transition_meal_status(meal, MealProcessingStatus.FAILED)
                            await session.merge(meal)
                            await session.commit()
                except Exception:
                    logger.exception("Error while marking meal as FAILED in segmentation")
                for crop_path in created_crop_paths:
                    try:
                        crop_path.unlink(missing_ok=True)
                    except Exception:
                        logger.exception("Error while deleting failed segment crop", extra={"path": str(crop_path)})
            await _poll_sleep(interval)
    finally:
        await engine.dispose()


async def poll_and_embed_food_segments(bot, settings, poll_interval: float | None = None) -> None:
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
    )
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    interval = poll_interval or settings.BOT_POLL_INTERVAL
    llm_client = get_llm_client()

    try:
        while True:
            meal: MealLog | None = None
            try:
                async with session_factory() as session:
                    statement = (
                        select(MealLog)
                        .where(MealLog.processing_status == MealProcessingStatus.EMBEDDING)
                        .order_by(MealLog.created_at.asc())
                        .limit(1)
                        .with_for_update(skip_locked=True)
                    )
                    result = await session.execute(statement)
                    meal = result.scalar_one_or_none()
                    if meal is None:
                        await session.rollback()
                        await _poll_sleep(interval)
                        continue

                    segment_result = await session.execute(
                        select(MealSegment).where(MealSegment.meal_log_id == meal.id)
                    )
                    segments = list(segment_result.scalars().all())
                    if not segments:
                        logger.error(
                            "Embedding worker found meal %s without segments; marking FAILED",
                            meal.id,
                        )
                        _transition_meal_status(meal, MealProcessingStatus.FAILED)
                        await session.commit()
                        continue

                    await session.commit()
                    for segment in segments:
                        segment.embedding = await matching_service.embed_segment_query_embedding(
                            segment=segment,
                            llm_client=llm_client,
                            embedding_model=matching_service.MATCHING_EMBEDDING_MODEL,
                        )

                    _transition_meal_status(meal, MealProcessingStatus.MATCHING)
                    await session.commit()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error in poll_and_embed_food_segments")
                try:
                    async with session_factory() as session:
                        await session.rollback()
                        if meal is not None:
                            _transition_meal_status(meal, MealProcessingStatus.FAILED)
                            await session.merge(meal)
                            await session.commit()
                except Exception:
                    logger.exception("Error while marking meal as FAILED in embedding")
            await _poll_sleep(interval)
    finally:
        await engine.dispose()


async def _is_rejection_threshold_reached(
    *,
    segment: MealSegment,
    session: AsyncSession,
    llm_client,
) -> matching_service.SegmentMatchResult:
    if segment.embedding is None:
        if llm_client is None:
            llm_client = get_llm_client()
        return await matching_service.match_segment_against_visual_corpus(
            segment=segment,
            session=session,
            llm_client=llm_client,
        )
    return await matching_service.match_segment_with_cached_embedding(segment=segment, session=session)


def _resolve_match_parallelism(settings: object) -> int:
    configured = getattr(settings, "REASONING_SEGMENT_PARALLELISM", None)
    if configured is None:
        configured = getattr(settings, "SEGMENT_MATCH_PARALLELISM", 4)
    try:
        value = int(configured)
    except (TypeError, ValueError):
        value = 4
    return max(1, value)


async def _match_segment_with_limit(
    *,
    segment: MealSegment,
    session: AsyncSession,
    llm_client,
    semaphore: asyncio.Semaphore,
) -> tuple[MealSegment, matching_service.SegmentMatchResult]:
    async with semaphore:
        result = await _is_rejection_threshold_reached(
            segment=segment,
            session=session,
            llm_client=llm_client,
        )
    return segment, result


async def _match_segment_with_isolated_session(
    *,
    segment: MealSegment,
    session_factory,
    llm_client,
    semaphore: asyncio.Semaphore,
) -> tuple[MealSegment, matching_service.SegmentMatchResult]:
    async with semaphore:
        async with session_factory() as match_session:
            result = await _is_rejection_threshold_reached(
                segment=segment,
                session=match_session,
                llm_client=llm_client,
            )
    return segment, result


def _completion_items_from_meal_resolution(
    *,
    match_results: list[tuple[MealSegment, matching_service.SegmentMatchResult]],
    meal_resolution: object,
) -> list[CompletionItem]:
    meal_entries = list(getattr(meal_resolution, "meal_entries", []))
    entries_by_segment = {
        getattr(entry, "segment_id", None): entry
        for entry in meal_entries
    }

    completion_items: list[CompletionItem] = []
    for segment, result in match_results:
        entry = entries_by_segment.get(getattr(segment, "id", None))
        if meal_entries and entry is None:
            continue
        food_item = _food_item_from_entry_or_match(entry=entry, result=result)
        portion_bucket = (
            getattr(entry, "portion_bucket", None)
            if entry is not None
            else None
        )
        quantity_label = (
            getattr(entry, "quantity_display", None) if entry is not None else None
        )

        completion_items.append(
            CompletionItem(
                food_name=(
                    food_item.name
                    if food_item is not None and getattr(food_item, "name", None)
                    else "Unknown food"
                ),
                portion_bucket=(
                    _normalize_portion_bucket(
                        str(portion_bucket)
                        if portion_bucket is not None
                        else "STANDARD"
                    )
                ),
                identification_method=(
                    str(getattr(entry, "identification_method", None) or "AUTO_CONFIRM")
                    if entry is not None
                    else "AUTO_CONFIRM"
                ),
                is_verified=(
                    bool(getattr(entry, "is_verified", None))
                    if entry is not None and hasattr(entry, "is_verified")
                    else bool(food_item.is_verified)
                    if food_item is not None and hasattr(food_item, "is_verified")
                    else False
                ),
                calories=getattr(food_item, "calories", None),
                protein_g=getattr(food_item, "protein_g", None),
                carbs_g=getattr(food_item, "carbs_g", None),
                fat_g=getattr(food_item, "fat_g", None),
                quantity_label=(
                    quantity_label if isinstance(quantity_label, str) and quantity_label.strip() else None
                ),
            )
        )

    return completion_items


def _food_item_from_entry_or_match(*, entry: object | None, result: object) -> object | None:
    food_item = getattr(entry, "food_item", None) if entry is not None else None
    if food_item is not None:
        return food_item
    food_visual = getattr(result, "food_visual", None)
    return getattr(food_visual, "food_item", None) if food_visual is not None else None


def _recent_entries_from_meal_resolution(
    *,
    meal_id: str,
    match_results: list[tuple[MealSegment, matching_service.SegmentMatchResult]],
    meal_resolution: object,
) -> list[dict]:
    meal_entries = list(getattr(meal_resolution, "meal_entries", []))
    entries_by_segment = {
        getattr(entry, "segment_id", None): entry
        for entry in meal_entries
    }
    recent_entries: list[dict] = []
    for segment, result in match_results:
        entry = entries_by_segment.get(getattr(segment, "id", None))
        if meal_entries and entry is None:
            continue
        if entry is None or getattr(entry, "id", None) is None:
            continue
        food_item = _food_item_from_entry_or_match(entry=entry, result=result)
        recent_entries.append(
            correction_service.build_recent_entry_record(
                entry_id=entry.id,
                food_name=getattr(food_item, "name", None),
                quantity_display=getattr(entry, "quantity_display", None),
                meal_id=meal_id,
            )
        )
    return recent_entries


def _remember_recent_entry_context(
    bot_data: dict | None,
    new_entries: list[dict],
    *,
    merge: bool = True,
) -> list[dict]:
    if bot_data is None:
        return new_entries
    recent_entries = (
        correction_service.remember_recent_entries(
            bot_data.get("recent_entries"),
            new_entries,
        )
        if merge
        else [dict(entry) for entry in list(new_entries or [])]
    )
    bot_data["recent_entries"] = recent_entries
    return recent_entries


async def poll_and_match_food_segments(bot, settings, poll_interval: float | None = None, bot_data: dict | None = None) -> None:
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
    )
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    interval = poll_interval or settings.BOT_POLL_INTERVAL
    llm_client = None

    try:
        while True:
            meal: MealLog | None = None
            try:
                async with session_factory() as session:
                    statement = (
                        select(MealLog)
                        .where(MealLog.processing_status == MealProcessingStatus.MATCHING)
                        .order_by(MealLog.created_at.asc())
                        .limit(1)
                        .with_for_update(skip_locked=True)
                    )
                    result = await session.execute(statement)
                    meal = result.scalar_one_or_none()
                    if meal is None:
                        await session.rollback()
                        await _poll_sleep(interval)
                        continue

                    segment_result = await session.execute(
                        select(MealSegment).where(MealSegment.meal_log_id == meal.id)
                    )
                    segments = list(segment_result.scalars().all())
                    if not segments:
                        _transition_meal_status(meal, MealProcessingStatus.REASONING)
                        await session.commit()
                        continue

                    await session.commit()
                    match_sem = asyncio.Semaphore(_resolve_match_parallelism(settings))
                    match_results = await asyncio.gather(
                        *[
                            _match_segment_with_isolated_session(
                                segment=segment,
                                session_factory=session_factory,
                                llm_client=llm_client,
                                semaphore=match_sem,
                            )
                            for segment in segments
                        ]
                    )

                    for segment, result in match_results:
                        matching_service.persist_match_candidate_snapshot(
                            segment=segment,
                            result=result,
                        )

                    _transition_meal_status(meal, MealProcessingStatus.REASONING)
                    await session.commit()

                    reasoning_client = llm_client or get_llm_client()
                    _reasoning_result, finalization = await _run_reasoning_pipeline(
                        llm_client=reasoning_client,
                        meal=meal,
                        match_results=match_results,
                        segments=segments,
                        session=session,
                        settings=settings,
                    )

                    if finalization.get("finalized"):
                        completion_items = _completion_items_from_meal_resolution(
                            match_results=match_results,
                            meal_resolution=finalization.get("meal_resolution"),
                        )
                    else:
                        interview = await interview_service.prepare_interview_session(
                            session=session,
                            meal=meal,
                            segments=segments,
                            chat_id=str(settings.TELEGRAM_CHAT_ID),
                        )
                        await session.commit()

                    try:
                        if finalization.get("finalized"):
                            recent_entries = _remember_recent_entry_context(
                                bot_data,
                                _recent_entries_from_meal_resolution(
                                    meal_id=meal.id,
                                    match_results=match_results,
                                    meal_resolution=finalization.get("meal_resolution"),
                                ),
                                merge=False,
                            )
                            text = format_match_completion_message(completion_items)
                            fix_targets = format_recent_fix_targets(recent_entries)
                            if fix_targets:
                                text = f"{text}\n\n{fix_targets}"
                            await bot.send_message(
                                chat_id=settings.TELEGRAM_CHAT_ID,
                                text=text,
                            )
                        else:
                            await _start_meal_interview_turn(
                                bot=bot,
                                session=session,
                                interview=interview,
                                settings=settings,
                            )
                    except Exception:
                        logger.exception("Error sending completion match message")
                    continue
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error in poll_and_match_food_segments")
                try:
                    async with session_factory() as session:
                        await session.rollback()
                        if meal is not None:
                            _transition_meal_status(meal, MealProcessingStatus.FAILED)
                            await session.merge(meal)
                            await session.commit()
                except Exception:
                    logger.exception("Error while marking meal as FAILED in matching")
            await _poll_sleep(interval)
    finally:
        await engine.dispose()
