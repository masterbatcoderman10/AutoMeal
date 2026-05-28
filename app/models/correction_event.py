from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, JSON, String, Text, func
from sqlalchemy.dialects.postgresql import TIMESTAMP as TIMESTAMPTZ
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.diary_entry import DiaryEntry
    from app.models.food_visual import FoodVisual
    from app.models.meal_log import MealLog


class CorrectionEvent(Base):
    __tablename__ = "correction_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    meal_log_id: Mapped[str] = mapped_column(ForeignKey("meal_logs.id"), nullable=False)
    diary_entry_id: Mapped[str] = mapped_column(
        ForeignKey("diary_entries.id"), nullable=False
    )
    before_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    after_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    visual_learning_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    food_visual_id: Mapped[str | None] = mapped_column(
        ForeignKey("food_visuals.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    meal_log: Mapped["MealLog"] = relationship()
    diary_entry: Mapped["DiaryEntry"] = relationship()
    food_visual: Mapped["FoodVisual | None"] = relationship()
