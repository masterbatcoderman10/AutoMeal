"""Add durable meal acknowledgement marker."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision: str = "003_ack_sent_marker"
down_revision: str = "002_phase4_state_surfaces"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "meal_logs",
        sa.Column("ack_sent_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.execute("UPDATE meal_logs SET ack_sent_at = COALESCE(updated_at, created_at, now())")


def downgrade() -> None:
    op.drop_column("meal_logs", "ack_sent_at")
