from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import Application, CommandHandler

from app.config import get_settings
from bot.handlers import start
from bot.polling import poll_and_acknowledge


async def post_init(application: Application) -> None:
    settings = get_settings()
    application.bot_data["poll_task"] = asyncio.create_task(
        poll_and_acknowledge(
            application.bot,
            settings,
            settings.BOT_POLL_INTERVAL,
        )
    )


async def post_shutdown(application: Application) -> None:
    poll_task = application.bot_data.get("poll_task")
    if poll_task is None:
        return

    poll_task.cancel()
    try:
        await poll_task
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
