"""Phase 4 durable state surfaces.

Revision ID: 002_phase4_state_surfaces
Revises: 001_initial_schema
Create Date: 2026-05-28
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TIMESTAMP as TIMESTAMPTZ


revision: str = "002_phase4_state_surfaces"
down_revision: str = "001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "meal_logs",
        sa.Column(
            "reasoning_state_json",
            sa.JSON(),
            nullable=True,
        ),
    )
    op.add_column(
        "meal_logs",
        sa.Column(
            "last_stage_started_at",
            TIMESTAMPTZ(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "meal_logs",
        sa.Column(
            "recovery_attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "meal_logs",
        sa.Column(
            "last_recovery_notified_at",
            TIMESTAMPTZ(timezone=True),
            nullable=True,
        ),
    )

    op.add_column(
        "meal_segments",
        sa.Column("match_candidates_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "meal_segments",
        sa.Column("reasoning_trace_id", sa.String(length=64), nullable=True),
    )
    op.alter_column(
        "meal_segments",
        "ai_reasoning",
        type_=sa.JSON(),
        existing_type=sa.Text(),
        existing_nullable=True,
    )

    op.add_column(
        "diary_entries",
        sa.Column("quantity_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "diary_entries",
        sa.Column("quantity_display", sa.String(length=128), nullable=True),
    )

    op.add_column(
        "food_visuals",
        sa.Column(
            "invalidated_at",
            TIMESTAMPTZ(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "food_visuals",
        sa.Column("invalidation_reason", sa.String(length=1024), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("food_visuals", "invalidation_reason")
    op.drop_column("food_visuals", "invalidated_at")
    op.drop_column("diary_entries", "quantity_display")
    op.drop_column("diary_entries", "quantity_json")
    op.alter_column(
        "meal_segments",
        "ai_reasoning",
        type_=sa.Text(),
        existing_type=sa.JSON(),
        existing_nullable=True,
        postgresql_using="ai_reasoning::text",
    )
    op.drop_column("meal_segments", "reasoning_trace_id")
    op.drop_column("meal_segments", "match_candidates_json")
    op.drop_column("meal_logs", "last_recovery_notified_at")
    op.drop_column("meal_logs", "recovery_attempt_count")
    op.drop_column("meal_logs", "last_stage_started_at")
    op.drop_column("meal_logs", "reasoning_state_json")

