from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import TIMESTAMPTZ
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.food_item import FoodItem


class FoodVisual(Base):
    __tablename__ = "food_visuals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    food_item_id: Mapped[str] = mapped_column(ForeignKey("food_items.id"), nullable=False)
    cropped_image_url: Mapped[str] = mapped_column(String(512), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(1536), nullable=False)
    is_invalidated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    food_item: Mapped["FoodItem"] = relationship(back_populates="visuals")

    __table_args__ = (
        Index(
            "ix_food_visuals_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_with={"m": 16, "ef_construction": 64},
        ),
    )
