from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, JSON, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import TIMESTAMP as TIMESTAMPTZ
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.food_item import FoodItem
    from app.models.meal_log import MealLog
    from app.models.meal_segment import MealSegment


class DiaryEntry(Base):
    __tablename__ = "diary_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    meal_log_id: Mapped[str] = mapped_column(ForeignKey("meal_logs.id"), nullable=False)
    food_item_id: Mapped[str] = mapped_column(ForeignKey("food_items.id"), nullable=False)
    segment_id: Mapped[str | None] = mapped_column(
        ForeignKey("meal_segments.id"),
        nullable=True,
    )
    portion_bucket: Mapped[str] = mapped_column(String(32), nullable=False)
    identification_method: Mapped[str] = mapped_column(String(32), nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    quantity_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    quantity_display: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    meal_log: Mapped["MealLog"] = relationship()
    food_item: Mapped["FoodItem"] = relationship(back_populates="diary_entries")
    segment: Mapped["MealSegment | None"] = relationship()
