from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import InterviewSession, MealSegment, MealLog, MealProcessingStatus
from app.services.llm_client import get_llm_client
from app.services import matching_service
from app.services.image_service import save_segment_crop
from app.services.vision_service import (
    dedupe_overlapping_segments,
    detect_food_photo,
    label_food_segment,
    segment_food_photo_with_retry,
)
from app.services import reasoning_service
from bot.messages import (
    CompletionItem,
    format_ack_message,
    format_interview_reminder_message,
    format_match_completion_message,
    format_soft_failure_message,
    format_unresolved_match_message,
)

logger = logging.getLogger(__name__)
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
                        .where(MealLog.processing_status == MealProcessingStatus.PENDING)
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
                        _transition_meal_status(meal, MealProcessingStatus.DETECTING)
                        await session.commit()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error in poll_and_acknowledge")
                if ack_sent and meal is not None:
                    try:
                        async with session_factory() as recovery_session:
                            _transition_meal_status(meal, MealProcessingStatus.DETECTING)
                            await recovery_session.merge(meal)
                            await recovery_session.commit()
                    except Exception:
                        logger.exception("Error recovering acknowledged meal state")

            await _poll_sleep(interval)
    finally:
        await engine.dispose()


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
                        await _poll_sleep(interval)
                        continue

                    await bot.send_message(
                        chat_id=interview.chat_id,
                        text=format_interview_reminder_message(interview.meal_log_id),
                    )
                    interview.last_reminder_at = datetime.now(UTC)
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
                        await _poll_sleep(interval)
                        continue

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
                                bounding_box=segment.box_2d,
                                cropped_image_url=str(crop_path),
                            )
                        )

                    session.add_all(segment_rows)

                    for segment_row in segment_rows:
                        label = await label_food_segment(
                            segment_row.cropped_image_url,
                            llm_client=llm_client,
                            model=settings.LABEL_MODEL,
                        )
                        if label is None:
                            raise ValueError("segment label missing")
                        segment_row.label = label

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


def _completion_items_from_meal_resolution(
    *,
    match_results: list[tuple[MealSegment, matching_service.SegmentMatchResult]],
    meal_resolution: object,
) -> list[CompletionItem]:
    entries_by_segment = {
        getattr(entry, "segment_id", None): entry
        for entry in getattr(meal_resolution, "meal_entries", [])
    }

    completion_items: list[CompletionItem] = []
    for segment, result in match_results:
        food_item = result.food_visual.food_item if getattr(result, "food_visual", None) is not None else None
        entry = entries_by_segment.get(getattr(segment, "id", None))
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
                identification_method="AUTO_CONFIRM",
                is_verified=(
                    bool(food_item.is_verified)
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


async def poll_and_match_food_segments(bot, settings, poll_interval: float | None = None) -> None:
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

                    match_sem = asyncio.Semaphore(_resolve_match_parallelism(settings))
                    match_results = await asyncio.gather(
                        *[
                            _match_segment_with_limit(
                                segment=segment,
                                session=session,
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

                    reasoning_result, _trace = await reasoning_service.run_reasoning_request(
                        llm_client=llm_client or get_llm_client(),
                        meal_id=meal.id,
                        meal=meal,
                        match_results=match_results,
                        settings=settings,
                    )

                    finalization = await reasoning_service.finalize_meal_from_reasoning(
                        session=session,
                        meal=meal,
                        segments=segments,
                        match_results=match_results,
                        reasoning_payload=reasoning_result,
                    )

                    if finalization.get("finalized"):
                        _transition_meal_status(meal, MealProcessingStatus.COMPLETED)
                        await session.commit()
                        completion_items = _completion_items_from_meal_resolution(
                            match_results=match_results,
                            meal_resolution=finalization.get("meal_resolution"),
                        )
                    else:
                        _transition_meal_status(meal, MealProcessingStatus.INTERVIEWING)
                        await session.commit()

                    try:
                        if finalization.get("finalized"):
                            await bot.send_message(
                                chat_id=settings.TELEGRAM_CHAT_ID,
                                text=format_match_completion_message(completion_items),
                            )
                        else:
                            await bot.send_message(
                                chat_id=settings.TELEGRAM_CHAT_ID,
                                text=format_unresolved_match_message(meal.id),
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
