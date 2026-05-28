from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String, func
from sqlalchemy.dialects.postgresql import TIMESTAMP as TIMESTAMPTZ
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.interview_message import InterviewMessage
    from app.models.meal_log import MealLog


class InterviewSession(Base):
    __tablename__ = "interview_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    meal_log_id: Mapped[str] = mapped_column(
        ForeignKey("meal_logs.id"), nullable=False
    )
    chat_id: Mapped[str] = mapped_column(String(64), nullable=False)
    state_key: Mapped[str] = mapped_column(String(64), nullable=False)
    current_prompt_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_bot_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reminder_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_reminder_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMPTZ(timezone=True), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    meal_log: Mapped["MealLog"] = relationship()
    interview_messages: Mapped[list["InterviewMessage"]] = relationship(
        back_populates="session"
    )
