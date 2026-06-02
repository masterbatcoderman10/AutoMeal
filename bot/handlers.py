from collections.abc import Mapping
import uuid
from datetime import UTC, datetime
from inspect import isawaitable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.config import get_settings
from app.models import DiaryEntry, InterviewMessage, InterviewSession, MealLog
from app.services import interview_service, interview_turn_manager
from app.services import correction_service

from bot.callback_data import (
    OTHER_CHOICE_ID,
    OTHER_CHOICE_LABEL,
    allows_other_choice,
    build_interview_callback_data,
    callback_token,
    resolve_callback_token,
)
from bot.messages import (
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
has_deterministic_question_state = interview_service.has_deterministic_question_state
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
        meal_id = str(meal_id).strip()
        if len(meal_id) >= 36:
            statement = statement.where(InterviewSession.meal_log_id == meal_id)
        else:
            statement = statement.where(InterviewSession.meal_log_id.startswith(meal_id))
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def _load_active_interviews(session, *, chat_id: str) -> list[InterviewSession]:
    statement = (
        select(InterviewSession)
        .options(selectinload(InterviewSession.interview_messages))
        .where(
            InterviewSession.chat_id == chat_id,
            InterviewSession.is_active.is_(True),
        )
        .order_by(InterviewSession.updated_at.desc())
    )
    result = await session.execute(statement)
    scalars_getter = getattr(result, "scalars", None)
    if callable(scalars_getter):
        scalars = scalars_getter()
        if not isawaitable(scalars):
            all_getter = getattr(scalars, "all", None)
            if callable(all_getter):
                rows = all_getter()
                if isinstance(rows, list):
                    return list(rows)
                if isinstance(rows, tuple):
                    return list(rows)
    scalar_one_or_none = getattr(result, "scalar_one_or_none", None)
    if callable(scalar_one_or_none):
        interview = scalar_one_or_none()
        if interview is not None:
            return [interview]
    return []


def _interview_state(interview: InterviewSession) -> dict:
    return dict(interview.current_prompt_payload or {})


def _session_mode_for_interview(interview: InterviewSession) -> str:
    return str(_interview_state(interview).get("session_mode") or interview_service.SESSION_MODE_MEAL)


def _reply_to_message_id(update: Update) -> int | None:
    message = getattr(update, "message", None)
    reply_to_message = getattr(message, "reply_to_message", None)
    message_id = getattr(reply_to_message, "message_id", None)
    return message_id if isinstance(message_id, int) else None


def _latest_bot_interview_message_id(interview: InterviewSession) -> int | None:
    latest_message_id: int | None = None
    for message in getattr(interview, "interview_messages", []) or []:
        if getattr(message, "role", None) != "bot":
            continue
        message_id = getattr(message, "message_id", None)
        if isinstance(message_id, int):
            latest_message_id = message_id
    if latest_message_id is not None:
        return latest_message_id
    for item in _interview_state(interview).get("interview_messages") or []:
        if not isinstance(item, dict):
            continue
        if item.get("role") != "bot":
            continue
        message_id = item.get("message_id")
        if isinstance(message_id, int):
            latest_message_id = message_id
    return latest_message_id


def _match_interview_by_prompt_message(
    interviews: list[InterviewSession],
    *,
    reply_message_id: int,
) -> InterviewSession | None:
    for interview in interviews:
        if getattr(interview, "last_bot_message_id", None) == reply_message_id:
            return interview
    for interview in interviews:
        if _latest_bot_interview_message_id(interview) == reply_message_id:
            return interview
    return None


async def _resolve_active_interview_for_text(
    session,
    *,
    chat_id: str,
    update: Update,
) -> tuple[InterviewSession | None, str | None]:
    interviews = await _load_active_interviews(session, chat_id=chat_id)
    if not interviews:
        return None, None

    reply_message_id = _reply_to_message_id(update)
    if reply_message_id is not None:
        matched = _match_interview_by_prompt_message(interviews, reply_message_id=reply_message_id)
        if matched is not None:
            return matched, None

    meal_interviews = [
        interview for interview in interviews
        if _session_mode_for_interview(interview) == interview_service.SESSION_MODE_MEAL
    ]
    fix_interviews = [
        interview for interview in interviews
        if _session_mode_for_interview(interview) == interview_service.SESSION_MODE_FIX
    ]

    if len(meal_interviews) == 1 and not fix_interviews:
        return meal_interviews[0], None
    if len(fix_interviews) == 1 and not meal_interviews:
        return fix_interviews[0], None
    if len(meal_interviews) > 1:
        return None, "Please reply to the specific meal prompt so I know which meal to update."
    return None, "Please reply to the specific prompt so I know what to update."


def _confirmation_items_from_state(state: dict) -> list[dict]:
    return interview_service.confirmation_items_from_state(state)


def _update_confirmation_state(state: dict, confirmation_items: list[dict]) -> dict:
    updated = dict(state)
    updated["roadmap_step"] = "CONFIRMATION"
    updated["current_target_index"] = len(updated.get("pending_targets") or [])
    updated["answers_by_segment"] = [dict(item) for item in confirmation_items]
    updated["confirmation_items"] = [dict(item) for item in confirmation_items]
    return updated


def _finalized_grounding_required(finalized: dict) -> bool:
    result = finalized.get("result")
    return isinstance(result, Mapping) and bool(result.get("grounding_required"))


def _finalized_meal_entries(finalized: dict) -> list:
    result = finalized.get("result")
    if isinstance(result, Mapping):
        return list(result.get("meal_entries", []))
    return list(getattr(result, "meal_entries", []) or [])


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
        interview_state=state,
    )
    return {
        "mode": interview_service.SESSION_MODE_MEAL,
        "meal": meal,
        "result": result,
        "confirmation_items": confirmation_items,
    }


def _recent_entries_from_confirmation(*, meal_id: str, meal_entries: list[DiaryEntry], confirmation_items: list[dict]) -> list[dict]:
    finalized_items = [
        dict(item)
        for item in confirmation_items
        if isinstance(item, Mapping)
    ]
    names_by_segment = {
        str(item.get("segment_id") or ""): item.get("name")
        for item in finalized_items
    }
    recent_entries: list[dict] = []
    for index, entry in enumerate(meal_entries):
        if not getattr(entry, "id", None):
            continue
        food_item = getattr(entry, "food_item", None)
        food_name = getattr(food_item, "name", None)
        if not food_name and index < len(finalized_items):
            food_name = finalized_items[index].get("name")
        if not food_name:
            food_name = names_by_segment.get(str(getattr(entry, "segment_id", "") or ""))
        recent_entries.append(
            correction_service.build_recent_entry_record(
                entry_id=entry.id,
                food_name=food_name,
                quantity_display=getattr(entry, "quantity_display", None),
                meal_id=meal_id,
            )
        )
    return recent_entries


def _remember_recent_entry_context(
    bot_data: dict,
    new_entries: list[dict],
    *,
    merge: bool = True,
) -> list[dict]:
    recent_entries = (
        correction_service.remember_recent_entries(
            bot_data.get("recent_entries"),
            new_entries,
        )
        if merge
        else [dict(entry) for entry in list(new_entries or [])]
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


def _is_deterministic_meal_interview(state: Mapping[str, object]) -> bool:
    return (
        str(state.get("session_mode") or interview_service.SESSION_MODE_MEAL) == interview_service.SESSION_MODE_MEAL
        and has_deterministic_question_state(state)
    )


def _callback_markup_for_prompt(prompt: Mapping[str, object], *, meal_id: str | None) -> InlineKeyboardMarkup | None:
    answer_type = str(prompt.get("answer_type") or "").strip().lower()
    question_id = str(prompt.get("question_id") or "").strip()
    if answer_type not in {"confirm", "single_choice"} or not question_id or not meal_id:
        return None
    choices = prompt.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    rows = []
    for choice in choices:
        if not isinstance(choice, Mapping):
            continue
        label = str(choice.get("label") or "").strip()
        choice_id = str(choice.get("choice_id") or "").strip()
        if not label or not choice_id:
            continue
        rows.append(
            [
                InlineKeyboardButton(
                    label,
                    callback_data=build_interview_callback_data(
                        meal_id=meal_id,
                        question_id=question_id,
                        choice_id=choice_id,
                    ),
                )
            ]
        )
    if allows_other_choice(prompt):
        rows.append(
            [
                InlineKeyboardButton(
                    OTHER_CHOICE_LABEL,
                    callback_data=build_interview_callback_data(
                        meal_id=meal_id,
                        question_id=question_id,
                        choice_id=OTHER_CHOICE_ID,
                    ),
                )
            ]
        )
    return InlineKeyboardMarkup(rows) if rows else None


def _prompt_reply_kwargs(prompt: Mapping[str, object], *, meal_id: str | None) -> dict[str, object]:
    reply_markup = _callback_markup_for_prompt(prompt, meal_id=meal_id)
    return {"reply_markup": reply_markup} if reply_markup is not None else {}


def _has_pending_deterministic_questions(state: Mapping[str, object]) -> bool:
    return any(str(question_id).strip() for question_id in state.get("pending_question_ids") or [])


async def _persist_and_reply_with_prompt(
    *,
    session,
    interview: InterviewSession,
    state: dict,
    user_payload: Mapping[str, object],
    prompt: Mapping[str, object],
    reply_callable,
    meal_id: str | None,
    user_message_id: int | None = None,
) -> None:
    sent = await reply_callable(
        prompt["prompt"],
        **_prompt_reply_kwargs(prompt, meal_id=meal_id),
    )
    state["current_question"] = dict(prompt)
    state["current_question_id"] = prompt.get("question_id")
    state["last_prompted_at"] = datetime.now(UTC)
    await interview_service.persist_interview_step(
        session=session,
        interview=interview,
        state=state,
        user_payload=user_payload,
        next_prompt=prompt,
        user_message_id=user_message_id,
        next_prompt_message_id=getattr(sent, "message_id", None) if sent is not None else None,
    )


def _other_free_text_prompt(prompt: Mapping[str, object]) -> dict[str, object]:
    label = str(prompt.get("label") or "this item").strip() or "this item"
    free_prompt = dict(prompt)
    free_prompt["answer_type"] = "free_text"
    free_prompt["choices"] = []
    free_prompt["prompt"] = f"Type your answer for {label}."
    free_prompt["invalid_prompt"] = free_prompt["prompt"]
    free_prompt["other_for_question_id"] = prompt.get("question_id")
    return free_prompt


def _is_other_choice_token(choice_id: str) -> bool:
    return choice_id == OTHER_CHOICE_ID or choice_id == callback_token(OTHER_CHOICE_ID)


async def _handle_deterministic_meal_text(
    *,
    session,
    interview: InterviewSession,
    state: dict,
    text: str,
    update: Update,
    settings,
) -> None:
    awaiting_other_question_id = str(state.get("awaiting_other_question_id") or "").strip()
    if awaiting_other_question_id:
        question_lookup = {
            str(key): dict(value)
            for key, value in dict(state.get("questions_by_id") or {}).items()
            if isinstance(value, Mapping)
        }
        prompt = dict(question_lookup.get(awaiting_other_question_id) or interview_service.current_target_question(state))
        prompt["answer_type"] = "free_text"
        prompt["choices"] = []
        state = dict(state)
        state.pop("awaiting_other_question_id", None)
    else:
        prompt = interview_service.current_target_question(state)
    answer = interview_service.parse_interview_text(text=text, context=prompt)
    if answer.get("invalid"):
        await update.message.reply_text(str(prompt.get("invalid_prompt") or prompt.get("prompt") or "Please try again."))
        return
    updated_state = interview_service.complete_target_question(state, answer)
    if not _has_pending_deterministic_questions(updated_state):
        await _resolve_deterministic_confirmation(
            session=session,
            interview=interview,
            state=updated_state,
            user_payload=answer,
            latest_user_text=text,
            reply_callable=update.message.reply_text,
            settings=settings,
            user_message_id=getattr(update.message, "message_id", None),
        )
        return
    next_prompt = interview_service.current_target_question(updated_state)
    await _persist_and_reply_with_prompt(
        session=session,
        interview=interview,
        state=updated_state,
        user_payload=answer,
        prompt=next_prompt,
        reply_callable=update.message.reply_text,
        meal_id=str(state.get("meal_id") or interview.meal_log_id or ""),
        user_message_id=getattr(update.message, "message_id", None),
    )


async def _handle_deterministic_meal_callback(
    *,
    session,
    interview: InterviewSession,
    state: dict,
    callback_query,
    meal_id: str,
    question_id: str,
    choice_id: str,
    settings,
) -> None:
    if callback_query.message is None:
        return
    if isinstance(getattr(interview, "last_bot_message_id", None), int):
        message_id = getattr(callback_query.message, "message_id", None)
        if isinstance(message_id, int) and message_id != interview.last_bot_message_id:
            await callback_query.answer("That prompt is stale. Use the latest question.", show_alert=True)
            return
    question_lookup = {
        str(key): dict(value)
        for key, value in dict(state.get("questions_by_id") or {}).items()
        if isinstance(value, Mapping)
    }
    question_id = resolve_callback_token(question_lookup.keys(), question_id) or ""
    prompt = question_lookup.get(question_id)
    if prompt is None:
        await callback_query.answer("That question is no longer active.", show_alert=True)
        return
    unanswered_question_ids = {
        str(item)
        for item in state.get("pending_question_ids") or []
        if str(item)
    }
    if question_id not in unanswered_question_ids and question_id in {
        str(item) for item in dict(state.get("answers_by_question_id") or {}).keys()
    }:
        await callback_query.answer("That question is already answered.", show_alert=True)
        return
    choice_lookup = {
        str(choice.get("choice_id") or ""): dict(choice)
        for choice in prompt.get("choices") or []
        if isinstance(choice, Mapping) and str(choice.get("choice_id") or "")
    }
    if allows_other_choice(prompt) and _is_other_choice_token(choice_id):
        await callback_query.answer()
        next_prompt = _other_free_text_prompt(prompt)
        updated_state = dict(state)
        updated_state["awaiting_other_question_id"] = question_id
        updated_state["current_question"] = dict(next_prompt)
        updated_state["current_question_id"] = question_id
        updated_state["last_prompted_at"] = datetime.now(UTC)
        sent = await callback_query.message.reply_text(str(next_prompt["prompt"]))
        await interview_service.persist_interview_step(
            session=session,
            interview=interview,
            state=updated_state,
            user_payload={
                "question_id": question_id,
                "group_id": prompt.get("group_id"),
                "primary_segment_id": prompt.get("primary_segment_id"),
                "segment_ids": list(prompt.get("segment_ids") or []),
                "question_kind": prompt.get("question_kind"),
                "answer_type": prompt.get("answer_type"),
                "required": bool(prompt.get("required")),
                "choice_id": OTHER_CHOICE_ID,
                "value": OTHER_CHOICE_LABEL,
            },
            next_prompt=next_prompt,
            next_prompt_message_id=getattr(sent, "message_id", None) if sent is not None else None,
        )
        return
    choice_id = resolve_callback_token(choice_lookup.keys(), choice_id) or ""
    matched_choice = choice_lookup.get(choice_id)
    if matched_choice is None:
        await callback_query.answer("That option is not valid for this prompt.", show_alert=True)
        return
    await callback_query.answer()
    answer = {
        "question_id": question_id,
        "group_id": prompt.get("group_id"),
        "primary_segment_id": prompt.get("primary_segment_id"),
        "segment_ids": list(prompt.get("segment_ids") or []),
        "question_kind": prompt.get("question_kind"),
        "answer_type": prompt.get("answer_type"),
        "required": bool(prompt.get("required")),
        "choice_id": choice_id,
        "value": matched_choice.get("label"),
    }
    if str(prompt.get("answer_type") or "").strip().lower() == "confirm":
        answer["approval_status"] = "APPROVED" if choice_id == "approve" else "CORRECTED"
    elif str(prompt.get("question_kind") or "").strip().upper() == "SOURCE_ORIGIN":
        answer["source_type"] = interview_service.parse_interview_text(
            text=str(matched_choice.get("label") or ""),
            context=prompt,
        ).get("source_type")
    else:
        answer["name"] = matched_choice.get("label")
        answer["approval_status"] = "CORRECTED"

    updated_state = interview_service.complete_target_question(state, answer)
    if not _has_pending_deterministic_questions(updated_state):
        await _resolve_deterministic_confirmation(
            session=session,
            interview=interview,
            state=updated_state,
            user_payload=answer,
            latest_user_text=str(matched_choice.get("label") or ""),
            reply_callable=callback_query.message.reply_text,
            settings=settings,
        )
        return
    next_prompt = interview_service.current_target_question(updated_state)
    await _persist_and_reply_with_prompt(
        session=session,
        interview=interview,
        state=updated_state,
        user_payload=answer,
        prompt=next_prompt,
        reply_callable=callback_query.message.reply_text,
        meal_id=meal_id,
    )


async def interview_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    if await _reject_unpinned_update(update):
        return
    data = update.callback_query.data or ""
    if data.startswith("interview:"):
        parts = data.split(":")
        if len(parts) != 4:
            return
        _prefix, meal_id, question_id, choice_id = parts
        chat_id = _chat_id_from_update(update)
        if chat_id is None or not meal_id or not question_id or not choice_id:
            return
        settings = get_settings()
        engine, session_factory = _make_session_factory(settings)
        try:
            async with session_factory() as session:
                interview = await _load_active_interview(session, chat_id=chat_id, meal_id=meal_id)
                if interview is None:
                    return
                state = _interview_state(interview)
                if not _is_deterministic_meal_interview(state):
                    await update.callback_query.answer("That prompt is no longer active.", show_alert=True)
                    return
                await _handle_deterministic_meal_callback(
                    session=session,
                    interview=interview,
                    state=state,
                    callback_query=update.callback_query,
                    meal_id=meal_id,
                    question_id=question_id,
                    choice_id=choice_id,
                    settings=settings,
                )
            return
        finally:
            await engine.dispose()
    if not data.startswith("confirm:"):
        return
    await update.callback_query.answer()
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
            if _finalized_grounding_required(finalized):
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
                        meal_entries=_finalized_meal_entries(finalized),
                        confirmation_items=list(finalized["confirmation_items"]),
                    ),
                    merge=False,
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
            interview, retry_message = await _resolve_active_interview_for_text(
                session,
                chat_id=chat_id,
                update=update,
            )
            if interview is None:
                await update.message.reply_text(retry_message or "Got it. I'll update the meal confirmation.")
                return
            state = _interview_state(interview)
            if state.get("roadmap_step") == "GROUNDING_PENDING":
                await update.message.reply_text(format_grounding_pending_message(interview.meal_log_id))
                return
            mode = str(state.get("session_mode") or interview_service.SESSION_MODE_MEAL)
            if state.get("roadmap_step") != "CONFIRMATION" and _is_deterministic_meal_interview(state):
                await _handle_deterministic_meal_text(
                    session=session,
                    interview=interview,
                    state=state,
                    text=text,
                    update=update,
                    settings=settings,
                )
                return
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
                    if _finalized_grounding_required(finalized):
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
                            meal_entries=_finalized_meal_entries(finalized),
                            confirmation_items=list(finalized["confirmation_items"]),
                        ),
                        merge=False,
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
        if _finalized_grounding_required(finalized):
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
                meal_entries=_finalized_meal_entries(finalized),
                confirmation_items=list(finalized["confirmation_items"]),
            ),
            merge=False,
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


async def _resolve_deterministic_confirmation(
    *,
    session,
    interview: InterviewSession,
    state: dict,
    user_payload: Mapping[str, object],
    latest_user_text: str,
    reply_callable,
    settings,
    user_message_id: int | None = None,
) -> None:
    try:
        turn = await _run_meal_interview_turn(
            state=state,
            latest_user_text=latest_user_text,
            settings=settings,
        )
    except interview_turn_manager.InterviewTurnValidationError as exc:
        failure_state = dict(state)
        failure_state["last_turn_error"] = str(exc)
        failure_state["last_prompted_at"] = datetime.now(UTC)
        await interview_service.persist_interview_step(
            session=session,
            interview=interview,
            state=failure_state,
            user_payload=user_payload,
            user_message_id=user_message_id,
        )
        await reply_callable(interview_service.build_neutral_retry_prompt(state))
        return

    confirmation_items = _turn_confirmation_items_payload(turn.confirmation_items)
    resolver_payload = {
        "turn_action": getattr(turn, "turn_action", "ready_to_confirm"),
        "clarification_reason": getattr(turn, "clarification_reason", None),
        "conversation_summary": getattr(turn, "conversation_summary", None),
        "remaining_required_question_ids": list(state.get("remaining_required_question_ids") or []),
        "confirmation_items": confirmation_items,
    }
    resolved_state = interview_service.apply_interview_turn_result(
        state,
        turn_action="ready_to_confirm",
        assistant_prompt=str(getattr(turn, "assistant_prompt", "") or "Resolved meal confirmation."),
        clarification_reason=getattr(turn, "clarification_reason", None),
        conversation_summary=getattr(turn, "conversation_summary", None),
        confirmation_items=confirmation_items,
        resolver_payload=resolver_payload,
    )
    resolved_state["last_prompted_at"] = datetime.now(UTC)
    await interview_service.persist_interview_step(
        session=session,
        interview=interview,
        state=resolved_state,
        user_payload=user_payload,
        user_message_id=user_message_id,
    )
    await reply_callable(
        format_interview_confirmation_message(
            _confirmation_items_from_state(resolved_state),
            action="log it",
        )
    )


def _turn_confirmation_items_payload(items) -> list[dict]:
    payloads: list[dict] = []
    for item in items or []:
        if hasattr(item, "model_dump"):
            payloads.append(item.model_dump(mode="json"))
            continue
        if isinstance(item, Mapping):
            payloads.append(dict(item))
    return payloads


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
