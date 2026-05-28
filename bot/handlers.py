from telegram import Update
from telegram.ext import ContextTypes

from app.services import interview_service

from bot.messages import format_start_message


get_interview_roadmap = interview_service.get_interview_roadmap
is_pinned_chat_update = interview_service.is_pinned_chat_update
current_target_question = interview_service.current_target_question
complete_target_question = interview_service.complete_target_question
parse_interview_text = interview_service.parse_interview_text
should_send_single_reminder = interview_service.should_send_single_reminder
build_best_effort_closeout = interview_service.build_best_effort_closeout
apply_confirmation_edits = interview_service.apply_confirmation_edits
parse_confirmation_bulk_text = interview_service.parse_confirmation_bulk_text
build_confirmation_message = interview_service.build_confirmation_message
build_all_wrong_prompt = interview_service.build_all_wrong_prompt


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    del context
    if update.message is None:
        return

    await update.message.reply_text(format_start_message())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    del context
    if update.message is None:
        return

    await update.message.reply_text(
        "Send a meal photo via the iOS Shortcut. I'll process it and tell you what I found."
    )


async def interview_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    del context
    if update.callback_query is None:
        return
    await update.callback_query.answer()


async def interview_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    del context
    if update.message is None:
        return
    await update.message.reply_text("Got it. I'll update the meal confirmation.")


__all__ = [
    "apply_confirmation_edits",
    "build_all_wrong_prompt",
    "build_best_effort_closeout",
    "build_confirmation_message",
    "complete_target_question",
    "current_target_question",
    "get_interview_roadmap",
    "help_command",
    "interview_callback",
    "interview_text",
    "is_pinned_chat_update",
    "parse_confirmation_bulk_text",
    "parse_interview_text",
    "should_send_single_reminder",
    "start",
]
