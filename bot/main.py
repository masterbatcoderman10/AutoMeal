from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from app.config import get_settings
from app.services import tracing_service
from bot.handlers import fix_command, start
from bot.handlers import interview_callback, interview_text
from bot.polling import (
    poll_and_acknowledge,
    poll_and_detect_food,
    poll_and_embed_food_segments,
    poll_grounding_handoffs,
    poll_and_match_food_segments,
    poll_post_interview_grounding,
    poll_interview_reminders,
    poll_and_segment_food,
)


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
    application.bot_data["embed_task"] = asyncio.create_task(
        poll_and_embed_food_segments(
            application.bot,
            settings,
            settings.BOT_POLL_INTERVAL,
        )
    )
    application.bot_data["match_task"] = asyncio.create_task(
        poll_and_match_food_segments(
            application.bot,
            settings,
            settings.BOT_POLL_INTERVAL,
            application.bot_data,
        )
    )
    application.bot_data["interview_reminder_task"] = asyncio.create_task(
        poll_interview_reminders(
            application.bot,
            settings,
            settings.BOT_POLL_INTERVAL,
        )
    )
    application.bot_data["grounding_handoff_task"] = asyncio.create_task(
        poll_grounding_handoffs(
            application.bot,
            settings,
            settings.BOT_POLL_INTERVAL,
        )
    )
    application.bot_data["post_interview_grounding_task"] = asyncio.create_task(
        poll_post_interview_grounding(
            application.bot,
            settings,
            settings.BOT_POLL_INTERVAL,
            application.bot_data,
        )
    )


async def post_shutdown(application: Application) -> None:
    for task in [
        application.bot_data.get("poll_task"),
        application.bot_data.get("detect_task"),
        application.bot_data.get("segment_task"),
        application.bot_data.get("embed_task"),
        application.bot_data.get("match_task"),
        application.bot_data.get("interview_reminder_task"),
        application.bot_data.get("grounding_handoff_task"),
        application.bot_data.get("post_interview_grounding_task"),
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
    tracing_service.validate_langfuse_required()
    application = (
        Application.builder()
        .token(settings.TELEGRAM_BOT_TOKEN)
        .concurrent_updates(False)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("fix", fix_command))
    application.add_handler(CallbackQueryHandler(interview_callback, pattern=r"^(interview|confirm|edit|all_wrong):"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, interview_text))
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
