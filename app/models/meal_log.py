from __future__ import annotations

from datetime import datetime
from enum import Enum as PyEnum
from typing import TYPE_CHECKING

from sqlalchemy import Enum, Integer, Index, JSON, String, func
from sqlalchemy.dialects.postgresql import TIMESTAMP as TIMESTAMPTZ
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.meal_segment import MealSegment


class MealProcessingStatus(PyEnum):
    PENDING = "PENDING"
    DETECTING = "DETECTING"
    SEGMENTING = "SEGMENTING"
    EMBEDDING = "EMBEDDING"
    MATCHING = "MATCHING"
    REASONING = "REASONING"
    INTERVIEWING = "INTERVIEWING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class MealLog(Base):
    __tablename__ = "meal_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    image_url: Mapped[str] = mapped_column(String(512), nullable=False)
    image_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    processing_status: Mapped[MealProcessingStatus] = mapped_column(
        Enum(MealProcessingStatus, name="meal_processing_status", create_type=True),
        nullable=False,
        default=MealProcessingStatus.PENDING,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    reasoning_state_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_stage_started_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMPTZ(timezone=True),
        nullable=True,
    )
    recovery_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_recovery_notified_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMPTZ(timezone=True),
        nullable=True,
    )
    ack_sent_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMPTZ(timezone=True),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    segments: Mapped[list["MealSegment"]] = relationship(back_populates="meal_log")


Index("ix_meal_logs_image_hash_created", MealLog.image_hash, MealLog.created_at)
