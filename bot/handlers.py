from telegram import Update
from telegram.ext import ContextTypes

from bot.messages import format_start_message


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is not None:
        await update.message.reply_text(format_start_message())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is not None:
        await update.message.reply_text(
            "Send a meal photo via the iOS Shortcut. I'll process it and tell you what I found."
        )
