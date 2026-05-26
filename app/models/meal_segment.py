from __future__ import annotations

from datetime import datetime
from enum import Enum as PyEnum
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import Enum, ForeignKey, JSON, String, Text, func
from sqlalchemy.dialects.postgresql import TIMESTAMPTZ
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.meal_log import MealLog


class PortionBucket(PyEnum):
    SMALL = "SMALL"
    STANDARD = "STANDARD"
    LARGE = "LARGE"


class MealSegment(Base):
    __tablename__ = "meal_segments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    meal_log_id: Mapped[str] = mapped_column(ForeignKey("meal_logs.id"), nullable=False)
    label: Mapped[str | None] = mapped_column(String(256), nullable=True)
    bounding_box: Mapped[list | None] = mapped_column(JSON, nullable=True)
    cropped_image_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    ai_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    portion_bucket: Mapped[PortionBucket | None] = mapped_column(
        Enum(PortionBucket, name="portion_bucket", create_type=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    meal_log: Mapped["MealLog"] = relationship(back_populates="segments")
