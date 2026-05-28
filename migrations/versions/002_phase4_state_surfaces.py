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

    op.create_table(
        "interview_sessions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("meal_log_id", sa.String(length=36), nullable=False),
        sa.Column("chat_id", sa.String(length=64), nullable=False),
        sa.Column("state_key", sa.String(length=64), nullable=False),
        sa.Column("current_prompt_payload", sa.JSON(), nullable=True),
        sa.Column("last_bot_message_id", sa.Integer(), nullable=True),
        sa.Column("reminder_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_reminder_at", TIMESTAMPTZ(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            TIMESTAMPTZ(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            TIMESTAMPTZ(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["meal_log_id"], ["meal_logs.id"]),
    )
    op.create_table(
        "interview_messages",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("message_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            TIMESTAMPTZ(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["session_id"], ["interview_sessions.id"]),
    )
    op.create_table(
        "correction_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("meal_log_id", sa.String(length=36), nullable=False),
        sa.Column("diary_entry_id", sa.String(length=36), nullable=False),
        sa.Column("before_json", sa.JSON(), nullable=False),
        sa.Column("after_json", sa.JSON(), nullable=False),
        sa.Column(
            "visual_learning_eligible",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("food_visual_id", sa.String(length=36), nullable=True),
        sa.Column(
            "created_at",
            TIMESTAMPTZ(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["meal_log_id"], ["meal_logs.id"]),
        sa.ForeignKeyConstraint(["diary_entry_id"], ["diary_entries.id"]),
        sa.ForeignKeyConstraint(["food_visual_id"], ["food_visuals.id"]),
    )


def downgrade() -> None:
    op.drop_table("correction_events")
    op.drop_table("interview_messages")
    op.drop_table("interview_sessions")
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
