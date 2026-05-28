from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, JSON, Integer, String, func
from sqlalchemy.dialects.postgresql import TIMESTAMP as TIMESTAMPTZ
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.interview_session import InterviewSession


class InterviewMessage(Base):
    __tablename__ = "interview_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("interview_sessions.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    session: Mapped["InterviewSession"] = relationship(back_populates="interview_messages")
