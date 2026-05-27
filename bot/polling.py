from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import DiaryEntry, FoodVisual, MealSegment, MealLog, MealProcessingStatus
from app.services.llm_client import get_llm_client
from app.services import matching_service
from app.services.image_service import save_segment_crop
from app.services.vision_service import (
    dedupe_overlapping_segments,
    detect_food_photo,
    label_food_segment,
    segment_food_photo_with_retry,
)
from bot.messages import (
    format_ack_message,
    format_soft_failure_message,
    format_unresolved_match_message,
)

logger = logging.getLogger(__name__)


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
                        meal.processing_status = MealProcessingStatus.DETECTING
                        await session.commit()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error in poll_and_acknowledge")
                if ack_sent and meal is not None:
                    try:
                        async with session_factory() as recovery_session:
                            meal.processing_status = MealProcessingStatus.DETECTING
                            await recovery_session.merge(meal)
                            await recovery_session.commit()
                    except Exception:
                        logger.exception("Error recovering acknowledged meal state")

            await asyncio.sleep(interval)
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
                            meal.processing_status = MealProcessingStatus.SEGMENTING
                        else:
                            meal.processing_status = MealProcessingStatus.COMPLETED
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
                        await asyncio.sleep(interval)
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
                        meal.processing_status = MealProcessingStatus.FAILED
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

                    meal.processing_status = MealProcessingStatus.EMBEDDING
                    await session.commit()

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error in poll_and_segment_food")
                try:
                    async with session_factory() as session:
                        await session.rollback()
                        if meal is not None:
                            meal.processing_status = MealProcessingStatus.FAILED
                            await session.merge(meal)
                            await session.commit()
                except Exception:
                    logger.exception("Error while marking meal as FAILED in segmentation")
                for crop_path in created_crop_paths:
                    try:
                        crop_path.unlink(missing_ok=True)
                    except Exception:
                        logger.exception("Error while deleting failed segment crop", extra={"path": str(crop_path)})
            await asyncio.sleep(interval)
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
                        await asyncio.sleep(interval)
                        continue

                    segment_result = await session.execute(
                        select(MealSegment).where(MealSegment.meal_log_id == meal.id)
                    )
                    segments = list(segment_result.scalars().all())
                    if not segments:
                        meal.processing_status = MealProcessingStatus.REASONING
                        await session.commit()
                        continue

                    for segment in segments:
                        segment.embedding = await matching_service.embed_segment_query_embedding(
                            segment=segment,
                            llm_client=llm_client,
                            embedding_model=matching_service.MATCHING_EMBEDDING_MODEL,
                        )

                    meal.processing_status = MealProcessingStatus.MATCHING
                    await session.commit()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error in poll_and_embed_food_segments")
                try:
                    async with session_factory() as session:
                        await session.rollback()
                        if meal is not None:
                            meal.processing_status = MealProcessingStatus.FAILED
                            await session.merge(meal)
                            await session.commit()
                except Exception:
                    logger.exception("Error while marking meal as FAILED in embedding")
            await asyncio.sleep(interval)
    finally:
        await engine.dispose()


async def _is_rejection_threshold_reached(
    *,
    segment: MealSegment,
    session: AsyncSession,
    llm_client,
) -> matching_service.SegmentMatchResult:
    if segment.embedding is None:
        return await matching_service.match_segment_against_visual_corpus(
            segment=segment,
            session=session,
            llm_client=llm_client,
        )
    return await matching_service.match_segment_with_cached_embedding(segment=segment, session=session)


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
    llm_client = get_llm_client()

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
                        await asyncio.sleep(interval)
                        continue

                    segment_result = await session.execute(
                        select(MealSegment).where(MealSegment.meal_log_id == meal.id)
                    )
                    segments = list(segment_result.scalars().all())
                    if not segments:
                        meal.processing_status = MealProcessingStatus.REASONING
                        await session.commit()
                        continue

                    match_results: list[tuple[MealSegment, matching_service.SegmentMatchResult]] = []
                    unresolved_results = []
                    for segment in segments:
                        result = await _is_rejection_threshold_reached(
                            segment=segment,
                            session=session,
                            llm_client=llm_client,
                        )
                        match_results.append((segment, result))
                        if result.is_below_threshold or not result.is_match:
                            unresolved_results.append(result)

                    if unresolved_results:
                        meal.processing_status = MealProcessingStatus.REASONING
                        await session.commit()
                        try:
                            await bot.send_message(
                                chat_id=settings.TELEGRAM_CHAT_ID,
                                text=format_unresolved_match_message(meal.id),
                            )
                        except Exception:
                            logger.exception("Error sending unresolved match message")
                        continue

                    for segment, result in match_results:
                        if result.food_item_id is None:
                            raise matching_service.MatchingError(
                                f"resolved match for segment {segment.id} is missing food_item_id"
                            )

                        session.add(
                            DiaryEntry(
                                id=str(uuid.uuid4()),
                                meal_log_id=meal.id,
                                food_item_id=result.food_item_id,
                                segment_id=segment.id,
                                portion_bucket="STANDARD",
                                identification_method="SIMILARITY",
                                is_verified=False,
                            )
                        )
                        session.add(
                            FoodVisual(
                                id=str(uuid.uuid4()),
                                food_item_id=result.food_item_id,
                                cropped_image_url=segment.cropped_image_url or "",
                                embedding=result.query_embedding,
                                is_invalidated=False,
                            )
                        )

                    meal.processing_status = MealProcessingStatus.COMPLETED
                    await session.commit()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error in poll_and_match_food_segments")
                try:
                    async with session_factory() as session:
                        await session.rollback()
                        if meal is not None:
                            meal.processing_status = MealProcessingStatus.FAILED
                            await session.merge(meal)
                            await session.commit()
                except Exception:
                    logger.exception("Error while marking meal as FAILED in matching")
            await asyncio.sleep(interval)
    finally:
        await engine.dispose()
