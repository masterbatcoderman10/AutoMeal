from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Float, Integer, JSON, String, Text, func
from sqlalchemy.dialects.postgresql import TIMESTAMP as TIMESTAMPTZ
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.diary_entry import DiaryEntry
    from app.models.food_visual import FoodVisual


class FoodItem(Base):
    __tablename__ = "food_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    aliases: Mapped[list | None] = mapped_column(JSON, nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    brand_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    restaurant_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    serving_size_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    calories: Mapped[float | None] = mapped_column(Float, nullable=True)
    protein_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    carbs_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    fat_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    fiber_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    times_confirmed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    llm_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
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

    visuals: Mapped[list["FoodVisual"]] = relationship(back_populates="food_item")
    diary_entries: Mapped[list["DiaryEntry"]] = relationship(back_populates="food_item")
