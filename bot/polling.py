from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.meal_log import MealLog, MealProcessingStatus
from bot.messages import format_ack_message

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
