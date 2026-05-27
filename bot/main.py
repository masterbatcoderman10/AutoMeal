from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import Application, CommandHandler

from app.config import get_settings
from bot.handlers import start
from bot.polling import poll_and_acknowledge, poll_and_detect_food, poll_and_segment_food


async def post_init(application: Application) -> None:
    settings = get_settings()
    application.bot_data["poll_task"] = asyncio.create_task(
        poll_and_acknowledge(
            application.bot,
            settings,
            settings.BOT_POLL_INTERVAL,
        )
    )
    application.bot_data["detect_task"] = asyncio.create_task(
        poll_and_detect_food(
            application.bot,
            settings,
            settings.BOT_POLL_INTERVAL,
        )
    )
    application.bot_data["segment_task"] = asyncio.create_task(
        poll_and_segment_food(
            application.bot,
            settings,
            settings.BOT_POLL_INTERVAL,
        )
    )


async def post_shutdown(application: Application) -> None:
    for task in [
        application.bot_data.get("poll_task"),
        application.bot_data.get("detect_task"),
        application.bot_data.get("segment_task"),
    ]:
        if task is None:
            continue

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def main() -> None:
    logging.basicConfig(
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        level=logging.INFO,
    )
    settings = get_settings()
    application = (
        Application.builder()
        .token(settings.TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    application.add_handler(CommandHandler("start", start))
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
