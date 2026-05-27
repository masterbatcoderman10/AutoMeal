from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.services.llm_client import get_llm_client
from app.models import MealSegment, MealLog, MealProcessingStatus
from app.services.image_service import save_segment_crop
from app.services.vision_service import (
    WEAK_SEGMENT_CONFIDENCE_THRESHOLD,
    dedupe_overlapping_segments,
    detect_food_photo,
    label_food_segment,
    segment_food_photo_with_retry,
)
from bot.messages import format_ack_message, format_result_sentence, format_soft_failure_message

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
                        meal.processing_status = MealProcessingStatus.DETECTING
                        await session.commit()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error in poll_and_acknowledge")

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

                    meal.processing_status = MealProcessingStatus.COMPLETED
                    await session.commit()
                    weak_labels = {
                        segment_row.label
                        for segment_row, segment in zip(segment_rows, segments, strict=False)
                        if segment_row.label
                        and segment.confidence is not None
                        and segment.confidence < WEAK_SEGMENT_CONFIDENCE_THRESHOLD
                    }

                    try:
                        await bot.send_message(
                            chat_id=settings.TELEGRAM_CHAT_ID,
                            text=format_result_sentence(
                                [segment.label for segment in segment_rows if segment.label],
                                weak_labels=weak_labels,
                            ),
                        )
                    except Exception:
                        logger.exception("Error sending segment result message")
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
