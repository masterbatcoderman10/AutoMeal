import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload
from telegram import Update
from telegram.ext import ContextTypes

from app.config import get_settings
from app.models import DiaryEntry, InterviewMessage, InterviewSession, MealLog
from app.services import interview_service
from app.services import correction_service

from bot.messages import format_fix_confirmation_message, format_interview_confirmation_message, format_start_message


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
resolve_fix_target = correction_service.resolve_fix_target
parse_fix_patch = correction_service.parse_fix_patch


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    del context
    if update.message is None:
        return
    if await _reject_unpinned_update(update):
        return

    await update.message.reply_text(format_start_message())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    del context
    if update.message is None:
        return
    if await _reject_unpinned_update(update):
        return

    await update.message.reply_text(
        "Send a meal photo via the iOS Shortcut. I'll process it and tell you what I found."
    )


async def fix_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    if await _reject_unpinned_update(update):
        return
    text = getattr(update.message, "text", "") or "/fix"
    recent_entries = context.bot_data.get("recent_entries", []) if hasattr(context, "bot_data") else []
    target = correction_service.resolve_fix_target(text, recent_entries=recent_entries)
    if target["mode"] == "none":
        await update.message.reply_text("No recent entries available to fix.")
        return
    context.bot_data["pending_fix"] = {"entry_id": target["entry_id"]}
    await update.message.reply_text(f"Fix target: {target['entry_id']}. Send the correction or cancel.")


def _make_session_factory(settings):
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
    )
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _chat_id_from_update(update: Update) -> str | None:
    chat = None
    if update.message is not None:
        chat = update.message.chat
    elif update.callback_query is not None and update.callback_query.message is not None:
        chat = update.callback_query.message.chat
    return str(getattr(chat, "id", "")) if chat is not None else None


async def _reject_unpinned_update(update: Update) -> bool:
    chat_id = _chat_id_from_update(update)
    if chat_id is None:
        return True
    if chat_id == str(get_settings().TELEGRAM_CHAT_ID):
        return False
    callback_query = getattr(update, "callback_query", None)
    if callback_query is not None:
        await callback_query.answer("Unauthorized chat.", show_alert=True)
    return True


async def _load_active_interview(session, *, chat_id: str, meal_id: str | None = None):
    statement = (
        select(InterviewSession)
        .where(
            InterviewSession.chat_id == chat_id,
            InterviewSession.is_active.is_(True),
        )
        .order_by(InterviewSession.updated_at.desc())
        .limit(1)
    )
    if meal_id is not None:
        statement = statement.where(InterviewSession.meal_log_id == meal_id)
    result = await session.execute(statement)
    return result.scalar_one_or_none()


def _confirmation_items_from_state(state: dict) -> list[dict]:
    items: list[dict] = []
    for message in state.get("interview_messages") or []:
        payload = message.get("payload") if isinstance(message, dict) else None
        if isinstance(payload, dict):
            items.append(interview_service.answer_to_confirmation_item(payload))
    return items


def _update_confirmation_state(state: dict, confirmation_items: list[dict]) -> dict:
    updated = dict(state)
    updated["roadmap_step"] = "CONFIRMATION"
    updated["current_target_index"] = len(updated.get("pending_targets") or [])
    updated["interview_messages"] = [
        {"role": "user", "payload": dict(item)}
        for item in confirmation_items
    ]
    return updated


async def _finalize_interview_confirmation(*, session, interview: InterviewSession) -> dict | None:
    meal_result = await session.execute(
        select(MealLog)
        .options(selectinload(MealLog.segments))
        .where(MealLog.id == interview.meal_log_id)
        .limit(1)
    )
    meal = meal_result.scalar_one_or_none()
    if meal is None:
        return None
    state = dict(interview.current_prompt_payload or {})
    confirmation_items = _confirmation_items_from_state(state)
    result = await interview_service.finalize_confirmed_interview(
        session=session,
        meal=meal,
        confirmation_items=confirmation_items,
        segments=list(meal.segments),
    )
    return {
        "meal": meal,
        "result": result,
        "confirmation_items": confirmation_items,
    }


async def _handle_pending_fix(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> bool:
    pending = context.bot_data.get("pending_fix")
    if not isinstance(pending, dict):
        return False
    if update.message is None:
        return True

    if text.strip().lower() in {"cancel", "/cancel"}:
        context.bot_data.pop("pending_fix", None)
        await update.message.reply_text("Fix cancelled.")
        return True

    settings = get_settings()
    engine, session_factory = _make_session_factory(settings)
    try:
        async with session_factory() as session:
            entry = await session.get(DiaryEntry, pending["entry_id"])
            if entry is None:
                context.bot_data.pop("pending_fix", None)
                await update.message.reply_text("I could not find that entry to fix.")
                return True

            if text.strip().lower() == "confirm" and pending.get("patch"):
                result = await correction_service.apply_confirmed_entry_correction(
                    session=session,
                    entry=entry,
                    patch=pending["patch"],
                    reason="telegram /fix",
                )
                await session.commit()
                context.bot_data.pop("pending_fix", None)
                await update.message.reply_text(correction_service.format_fix_summary(result))
                return True

            patch = correction_service.parse_fix_patch(text)
            if not patch:
                await update.message.reply_text("Send the correction text, or cancel.")
                return True
            pending["patch"] = patch
            preview = correction_service.build_fix_confirmation_payload(
                entry={
                    "id": entry.id,
                    "food_item_id": entry.food_item_id,
                    "portion_bucket": entry.portion_bucket,
                    "quantity_json": entry.quantity_json,
                    "quantity_display": entry.quantity_display,
                },
                patch=patch,
            )
            await update.message.reply_text(format_fix_confirmation_message(preview))
            return True
    finally:
        await engine.dispose()


async def interview_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    del context
    if update.callback_query is None:
        return
    if await _reject_unpinned_update(update):
        return
    await update.callback_query.answer()
    data = update.callback_query.data or ""
    if not data.startswith("confirm:"):
        return
    meal_id = data.split(":", 1)[1]
    chat_id = _chat_id_from_update(update)
    if chat_id is None:
        return

    settings = get_settings()
    engine, session_factory = _make_session_factory(settings)
    try:
        async with session_factory() as session:
            interview = await _load_active_interview(session, chat_id=chat_id, meal_id=meal_id)
            if interview is None:
                return
            finalized = await _finalize_interview_confirmation(session=session, interview=interview)
            if finalized is None:
                return
            interview.is_active = False
            session.add(interview)
            await session.commit()
            message = update.callback_query.message
            if message is not None:
                await message.reply_text("Meal confirmation saved.")
    finally:
        await engine.dispose()


async def interview_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    if await _reject_unpinned_update(update):
        return
    text = update.message.text or ""
    if await _handle_pending_fix(update, context, text):
        return

    chat_id = _chat_id_from_update(update)
    if chat_id is None:
        return

    settings = get_settings()
    engine, session_factory = _make_session_factory(settings)
    try:
        async with session_factory() as session:
            interview = await _load_active_interview(session, chat_id=chat_id)
            if interview is None:
                await update.message.reply_text("Got it. I'll update the meal confirmation.")
                return
            state = dict(interview.current_prompt_payload or {})
            if state.get("roadmap_step") == "CONFIRMATION":
                lowered = text.strip().lower()
                if lowered == "confirm":
                    finalized = await _finalize_interview_confirmation(session=session, interview=interview)
                    if finalized is None:
                        await update.message.reply_text("I could not find that meal to confirm.")
                        return
                    interview.is_active = False
                    session.add(interview)
                    await session.commit()
                    await update.message.reply_text("Meal confirmation saved.")
                    return

                confirmation_items = _confirmation_items_from_state(state)
                edits = interview_service.parse_confirmation_bulk_text(
                    text=text,
                    confirmation_items=confirmation_items,
                )
                if edits.get("applied_bulk"):
                    updated_confirmation = interview_service.apply_confirmation_edits(
                        confirmation_items,
                        edits["updates"],
                    )
                    interview.current_prompt_payload = _update_confirmation_state(state, updated_confirmation)
                    session.add(interview)
                    session.add(
                        InterviewMessage(
                            id=str(uuid.uuid4()),
                            session_id=interview.id,
                            role="user",
                            payload={
                                "type": "confirmation_edit",
                                "text": text,
                                "updates": edits["updates"],
                            },
                        )
                    )
                    await session.commit()
                    await update.message.reply_text(interview_service.build_confirmation_message(updated_confirmation))
                    return

                await update.message.reply_text(format_interview_confirmation_message(confirmation_items))
                return
            target = interview_service.current_target_question(state)
            answer = interview_service.parse_interview_text(text=text, context=target)
            state = interview_service.complete_target_question(state, answer)
            interview.current_prompt_payload = state
            interview.state_key = str(state.get("roadmap_step") or interview.state_key)
            session.add(interview)
            session.add(
                InterviewMessage(
                    id=str(uuid.uuid4()),
                    session_id=interview.id,
                    role="user",
                    payload=answer,
                )
            )
            await session.commit()

            if state.get("roadmap_step") == "CONFIRMATION":
                await update.message.reply_text(
                    format_interview_confirmation_message(_confirmation_items_from_state(state))
                )
            else:
                await update.message.reply_text(interview_service.current_target_question(state)["prompt"])
    finally:
        await engine.dispose()


__all__ = [
    "apply_confirmation_edits",
    "build_all_wrong_prompt",
    "build_best_effort_closeout",
    "build_confirmation_message",
    "complete_target_question",
    "current_target_question",
    "fix_command",
    "get_interview_roadmap",
    "help_command",
    "interview_callback",
    "interview_text",
    "is_pinned_chat_update",
    "parse_confirmation_bulk_text",
    "parse_fix_patch",
    "parse_interview_text",
    "resolve_fix_target",
    "should_send_single_reminder",
    "start",
]
