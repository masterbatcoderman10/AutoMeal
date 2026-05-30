import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload
from telegram import Update
from telegram.ext import ContextTypes

from app.config import get_settings
from app.models import DiaryEntry, InterviewMessage, InterviewSession, MealLog
from app.services import interview_service, interview_turn_manager
from app.services import correction_service

from bot.messages import (
    format_fix_confirmation_message,
    format_grounding_pending_message,
    format_interview_confirmation_message,
    format_recent_fix_targets,
    format_start_message,
)


get_interview_roadmap = interview_service.get_interview_roadmap
is_pinned_chat_update = interview_service.is_pinned_chat_update
current_target_question = interview_service.current_target_question
complete_target_question = interview_service.complete_target_question
confirmation_items_from_state = interview_service.confirmation_items_from_state
parse_interview_text = interview_service.parse_interview_text
should_send_single_reminder = interview_service.should_send_single_reminder
build_best_effort_closeout = interview_service.build_best_effort_closeout
apply_confirmation_edits = interview_service.apply_confirmation_edits
parse_confirmation_bulk_text = interview_service.parse_confirmation_bulk_text
build_confirmation_message = interview_service.build_confirmation_message
build_all_wrong_prompt = interview_service.build_all_wrong_prompt
prepare_fix_interview_session = interview_service.prepare_fix_interview_session
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
    chat_id = _chat_id_from_update(update)
    if chat_id is None:
        return

    settings = get_settings()
    engine, session_factory = _make_session_factory(settings)
    try:
        async with session_factory() as session:
            entry = await session.get(DiaryEntry, target["entry_id"])
            if entry is None:
                await update.message.reply_text("I could not find that entry to fix.")
                return
            entry_context = await correction_service.build_entry_correction_context(session=session, entry=entry)
            interview = await interview_service.prepare_fix_interview_session(
                session=session,
                entry=entry,
                entry_context=entry_context,
                chat_id=chat_id,
            )
            await session.commit()
            await update.message.reply_text(interview_service.current_target_question(interview.current_prompt_payload or {})["prompt"])
    finally:
        await engine.dispose()


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
    return interview_service.confirmation_items_from_state(state)


def _update_confirmation_state(state: dict, confirmation_items: list[dict]) -> dict:
    updated = dict(state)
    updated["roadmap_step"] = "CONFIRMATION"
    updated["current_target_index"] = len(updated.get("pending_targets") or [])
    updated["answers_by_segment"] = [dict(item) for item in confirmation_items]
    updated["confirmation_items"] = [dict(item) for item in confirmation_items]
    return updated


async def _finalize_interview_confirmation(*, session, interview: InterviewSession) -> dict | None:
    state = dict(interview.current_prompt_payload or {})
    confirmation_items = _confirmation_items_from_state(state)
    if str(state.get("session_mode") or interview_service.SESSION_MODE_MEAL) == interview_service.SESSION_MODE_FIX:
        entry_id = state.get("fix_entry_id")
        entry = await session.get(DiaryEntry, entry_id) if entry_id else None
        if entry is None:
            return None
        entry_context = await correction_service.build_entry_correction_context(session=session, entry=entry)
        patch = _build_fix_patch(entry_context=entry_context, confirmation_items=confirmation_items)
        if not patch:
            return {
                "mode": interview_service.SESSION_MODE_FIX,
                "entry": entry,
                "result": {"applied": False, "reason": "no_changes"},
                "confirmation_items": confirmation_items,
            }
        result = await correction_service.apply_confirmed_entry_correction(
            session=session,
            entry=entry,
            patch=patch,
            reason="telegram /fix",
        )
        return {
            "mode": interview_service.SESSION_MODE_FIX,
            "entry": entry,
            "result": result,
            "confirmation_items": confirmation_items,
        }

    meal_result = await session.execute(
        select(MealLog)
        .options(selectinload(MealLog.segments))
        .where(MealLog.id == interview.meal_log_id)
        .limit(1)
    )
    meal = meal_result.scalar_one_or_none()
    if meal is None:
        return None
    result = await interview_service.finalize_confirmed_interview(
        session=session,
        meal=meal,
        confirmation_items=confirmation_items,
        segments=list(meal.segments),
    )
    return {
        "mode": interview_service.SESSION_MODE_MEAL,
        "meal": meal,
        "result": result,
        "confirmation_items": confirmation_items,
    }


def _recent_entries_from_confirmation(*, meal_id: str, meal_entries: list[DiaryEntry], confirmation_items: list[dict]) -> list[dict]:
    names_by_segment = {
        str(item.get("segment_id") or ""): item.get("name")
        for item in confirmation_items
    }
    return [
        correction_service.build_recent_entry_record(
            entry_id=entry.id,
            food_name=names_by_segment.get(str(getattr(entry, "segment_id", "") or "")),
            quantity_display=getattr(entry, "quantity_display", None),
            meal_id=meal_id,
        )
        for entry in meal_entries
        if getattr(entry, "id", None)
    ]


def _remember_recent_entry_context(bot_data: dict, new_entries: list[dict]) -> list[dict]:
    recent_entries = correction_service.remember_recent_entries(
        bot_data.get("recent_entries"),
        new_entries,
    )
    bot_data["recent_entries"] = recent_entries
    return recent_entries


def _mark_grounding_pending(interview: InterviewSession) -> None:
    payload = dict(interview.current_prompt_payload or {})
    payload["roadmap_step"] = "GROUNDING_PENDING"
    payload["grounding_handoff_pending"] = True
    payload["grounding_required"] = True
    payload["grounding_status"] = "PENDING_HANDOFF"
    interview.current_prompt_payload = payload
    interview.state_key = "GROUNDING_PENDING"
    interview.is_active = True


async def interview_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
            if finalized.get("mode") == interview_service.SESSION_MODE_FIX:
                interview.is_active = False
                session.add(interview)
                await session.commit()
                message = update.callback_query.message
                if message is not None:
                    result = dict(finalized.get("result") or {})
                    if result.get("reason") == "no_changes":
                        await message.reply_text("No changes detected, so I kept the existing entry.")
                    else:
                        await message.reply_text(correction_service.format_fix_summary(result))
                return
            if finalized["result"].get("grounding_required"):
                _mark_grounding_pending(interview)
                session.add(interview)
                await session.commit()
                message = update.callback_query.message
                if message is not None:
                    await message.reply_text(format_grounding_pending_message(finalized["meal"].id))
                return
            interview.is_active = False
            session.add(interview)
            await session.commit()
            message = update.callback_query.message
            if message is not None:
                recent_entries = _remember_recent_entry_context(
                    context.bot_data,
                    _recent_entries_from_confirmation(
                        meal_id=finalized["meal"].id,
                        meal_entries=list(finalized["result"].get("meal_entries", [])),
                        confirmation_items=list(finalized["confirmation_items"]),
                    ),
                )
                reply = "Meal confirmation saved."
                fix_targets = format_recent_fix_targets(recent_entries)
                if fix_targets:
                    reply = f"{reply}\n\n{fix_targets}"
                await message.reply_text(reply)
    finally:
        await engine.dispose()


async def interview_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    if await _reject_unpinned_update(update):
        return
    text = update.message.text or ""

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
            if state.get("roadmap_step") == "GROUNDING_PENDING":
                await update.message.reply_text(format_grounding_pending_message(interview.meal_log_id))
                return
            mode = str(state.get("session_mode") or interview_service.SESSION_MODE_MEAL)
            if mode == interview_service.SESSION_MODE_MEAL and state.get("roadmap_step") != "CONFIRMATION":
                await _handle_meal_interview_turn(
                    session=session,
                    interview=interview,
                    state=state,
                    text=text,
                    update=update,
                    context=context,
                    settings=settings,
                )
                return
            if state.get("roadmap_step") == "CONFIRMATION":
                lowered = text.strip().lower()
                if lowered in {"cancel", "/cancel"} and mode == interview_service.SESSION_MODE_FIX:
                    interview.is_active = False
                    session.add(interview)
                    await session.commit()
                    await update.message.reply_text("Fix cancelled.")
                    return
                if lowered == "confirm":
                    finalized = await _finalize_interview_confirmation(session=session, interview=interview)
                    if finalized is None:
                        await update.message.reply_text("I could not find that meal to confirm.")
                        return
                    if finalized.get("mode") == interview_service.SESSION_MODE_FIX:
                        interview.is_active = False
                        session.add(interview)
                        await session.commit()
                        result = dict(finalized.get("result") or {})
                        if result.get("reason") == "no_changes":
                            await update.message.reply_text("No changes detected, so I kept the existing entry.")
                        else:
                            await update.message.reply_text(correction_service.format_fix_summary(result))
                        return
                    if finalized["result"].get("grounding_required"):
                        _mark_grounding_pending(interview)
                        session.add(interview)
                        await session.commit()
                        await update.message.reply_text(format_grounding_pending_message(finalized["meal"].id))
                        return
                    interview.is_active = False
                    session.add(interview)
                    await session.commit()
                    recent_entries = _remember_recent_entry_context(
                        context.bot_data,
                        _recent_entries_from_confirmation(
                            meal_id=finalized["meal"].id,
                            meal_entries=list(finalized["result"].get("meal_entries", [])),
                            confirmation_items=list(finalized["confirmation_items"]),
                        ),
                    )
                    reply = "Meal confirmation saved."
                    fix_targets = format_recent_fix_targets(recent_entries)
                    if fix_targets:
                        reply = f"{reply}\n\n{fix_targets}"
                    await update.message.reply_text(reply)
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
                    await interview_service.persist_interview_step(
                        session=session,
                        interview=interview,
                        state=_update_confirmation_state(state, updated_confirmation),
                        user_payload={
                            "type": "confirmation_edit",
                            "text": text,
                            "updates": edits["updates"],
                        },
                    )
                    action = "apply this fix" if mode == interview_service.SESSION_MODE_FIX else "log it"
                    await update.message.reply_text(format_interview_confirmation_message(updated_confirmation, action=action))
                    return

                action = "apply this fix" if mode == interview_service.SESSION_MODE_FIX else "log it"
                await update.message.reply_text(format_interview_confirmation_message(confirmation_items, action=action))
                return
            target = interview_service.current_target_question(state)
            answer = interview_service.parse_interview_text(text=text, context=target)
            if answer.get("invalid"):
                await update.message.reply_text(str(target.get("invalid_prompt") or target["prompt"]))
                return
            state = interview_service.complete_target_question(state, answer)
            state["last_prompted_at"] = datetime.now(UTC)
            next_prompt = None
            if state.get("roadmap_step") != "CONFIRMATION":
                next_prompt = interview_service.current_target_question(state)
            await interview_service.persist_interview_step(
                session=session,
                interview=interview,
                state=state,
                user_payload=answer,
                next_prompt=next_prompt,
            )

            if state.get("roadmap_step") == "CONFIRMATION":
                action = (
                    "apply this fix"
                    if str(state.get("session_mode") or interview_service.SESSION_MODE_MEAL) == interview_service.SESSION_MODE_FIX
                    else "log it"
                )
                await update.message.reply_text(
                    format_interview_confirmation_message(_confirmation_items_from_state(state), action=action)
                )
            else:
                await update.message.reply_text(next_prompt["prompt"])
    finally:
        await engine.dispose()


async def _handle_meal_interview_turn(*, session, interview: InterviewSession, state: dict, text: str, update: Update, context, settings) -> None:
    user_message_id = getattr(update.message, "message_id", None)
    user_payload = {
        "type": "meal_reply",
        "text": text,
        "raw_text": text,
    }
    state = interview_service.append_interview_transcript_entry(
        state,
        role="user",
        content=text,
        payload=user_payload,
        message_id=user_message_id,
    )
    interview.current_prompt_payload = interview_service.json_safe_payload(state)
    session.add(interview)
    session.add(
        InterviewMessage(
            id=str(uuid.uuid4()),
            session_id=interview.id,
            role="user",
            payload=dict(user_payload),
            message_id=user_message_id if isinstance(user_message_id, int) else None,
        )
    )
    await session.commit()

    try:
        turn = await _run_meal_interview_turn(
            state=state,
            latest_user_text=text,
            settings=settings,
        )
    except interview_turn_manager.InterviewTurnValidationError as exc:
        retry_prompt = interview_service.build_neutral_retry_prompt(state)
        sent = await update.message.reply_text(retry_prompt)
        failure_state = interview_service.append_interview_transcript_entry(
            state,
            role="bot",
            content=retry_prompt,
            payload={
                "type": "validation_retry",
                "prompt": retry_prompt,
                "error": str(exc),
            },
            message_id=getattr(sent, "message_id", None),
        )
        failure_state["last_turn_error"] = str(exc)
        failure_state["last_prompted_at"] = datetime.now(UTC)
        interview.current_prompt_payload = interview_service.json_safe_payload(failure_state)
        if isinstance(getattr(sent, "message_id", None), int):
            interview.last_bot_message_id = sent.message_id
        session.add(interview)
        session.add(
            InterviewMessage(
                id=str(uuid.uuid4()),
                session_id=interview.id,
                role="bot",
                payload={
                    "type": "validation_retry",
                    "prompt": retry_prompt,
                    "error": str(exc),
                },
                message_id=getattr(sent, "message_id", None) if isinstance(getattr(sent, "message_id", None), int) else None,
            )
        )
        await session.commit()
        return

    updated_state = interview_service.apply_interview_turn_result(
        state,
        turn_action=turn.turn_action,
        assistant_prompt=turn.assistant_prompt,
        clarification_reason=turn.clarification_reason,
        conversation_summary=turn.conversation_summary,
        confirmation_items=[item.model_dump(mode="json") for item in turn.confirmation_items],
    )

    if turn.turn_action == "ready_to_confirm":
        updated_state["last_prompted_at"] = datetime.now(UTC)
        interview.current_prompt_payload = interview_service.json_safe_payload(updated_state)
        session.add(interview)
        finalized = await _finalize_interview_confirmation(session=session, interview=interview)
        if finalized is None:
            await update.message.reply_text("I could not find that meal to confirm.")
            return
        if finalized["result"].get("grounding_required"):
            _mark_grounding_pending(interview)
            session.add(interview)
            await session.commit()
            await update.message.reply_text(format_grounding_pending_message(finalized["meal"].id))
            return
        interview.is_active = False
        session.add(interview)
        await session.commit()
        recent_entries = _remember_recent_entry_context(
            context.bot_data,
            _recent_entries_from_confirmation(
                meal_id=finalized["meal"].id,
                meal_entries=list(finalized["result"].get("meal_entries", [])),
                confirmation_items=list(finalized["confirmation_items"]),
            ),
        )
        reply = "Meal confirmation saved."
        fix_targets = format_recent_fix_targets(recent_entries)
        if fix_targets:
            reply = f"{reply}\n\n{fix_targets}"
        await update.message.reply_text(reply)
        return

    sent = await update.message.reply_text(turn.assistant_prompt)
    updated_state = interview_service.append_interview_transcript_entry(
        updated_state,
        role="bot",
        content=turn.assistant_prompt,
        payload={
            "type": "meal_turn",
            "prompt": turn.assistant_prompt,
            "turn_action": turn.turn_action,
            "clarification_reason": turn.clarification_reason,
        },
        message_id=getattr(sent, "message_id", None),
    )
    updated_state["last_prompted_at"] = datetime.now(UTC)
    interview.current_prompt_payload = interview_service.json_safe_payload(updated_state)
    if isinstance(getattr(sent, "message_id", None), int):
        interview.last_bot_message_id = sent.message_id
    session.add(interview)
    session.add(
        InterviewMessage(
            id=str(uuid.uuid4()),
            session_id=interview.id,
            role="bot",
            payload={
                "type": "meal_turn",
                "prompt": turn.assistant_prompt,
                "turn_action": turn.turn_action,
                "clarification_reason": turn.clarification_reason,
            },
            message_id=getattr(sent, "message_id", None) if isinstance(getattr(sent, "message_id", None), int) else None,
        )
    )
    await session.commit()


async def _run_meal_interview_turn(*, state: dict, latest_user_text: str, settings) -> interview_turn_manager.InterviewTurnResult:
    return await interview_turn_manager.run_interview_turn(
        authoritative_state=state,
        transcript=interview_service.interview_transcript_from_state(state),
        latest_user_text=latest_user_text,
        settings=settings,
    )


def _build_fix_patch(*, entry_context: dict, confirmation_items: list[dict]) -> dict:
    if not confirmation_items:
        return {}
    item = dict(confirmation_items[0])
    patch: dict[str, object] = {}
    comparisons = {
        "food_name": (item.get("name"), entry_context.get("food_name")),
        "source_type": (item.get("source_type"), entry_context.get("source_type")),
        "brand_name": (item.get("brand_name"), entry_context.get("brand_name")),
        "restaurant_name": (item.get("restaurant_name"), entry_context.get("restaurant_name")),
        "portion_bucket": (item.get("portion_bucket"), entry_context.get("portion_bucket")),
        "quantity_display": (item.get("quantity_display"), entry_context.get("quantity_display")),
    }
    for field, (new_value, existing_value) in comparisons.items():
        if new_value != existing_value and new_value is not None:
            patch[field] = new_value
    return patch


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
