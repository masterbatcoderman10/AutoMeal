"""Phase 5 grounding quantity persistence cleanup.

Revision ID: 004_phase5_grounding_quantity
Revises: 003_ack_sent_marker
Create Date: 2026-06-04
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "004_phase5_grounding_quantity"
down_revision: str = "003_ack_sent_marker"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PORTION_BUCKET = postgresql.ENUM(
    "SMALL",
    "STANDARD",
    "LARGE",
    name="portion_bucket",
    create_type=False,
)


def upgrade() -> None:
    op.add_column("meal_segments", sa.Column("quantity_json", sa.JSON(), nullable=True))
    op.add_column("meal_segments", sa.Column("quantity_display", sa.String(length=128), nullable=True))
    op.execute(
        """
        UPDATE meal_segments
        SET quantity_json = jsonb_build_object('portion_bucket', portion_bucket::text)
        WHERE portion_bucket IS NOT NULL
        """
    )
    op.drop_column("meal_segments", "portion_bucket")
    op.execute("DROP TYPE IF EXISTS portion_bucket")


def downgrade() -> None:
    PORTION_BUCKET.create(op.get_bind(), checkfirst=True)
    op.add_column("meal_segments", sa.Column("portion_bucket", PORTION_BUCKET, nullable=True))
    op.execute(
        """
        UPDATE meal_segments
        SET portion_bucket = CASE UPPER(COALESCE(quantity_json->>'portion_bucket', ''))
            WHEN 'SMALL' THEN 'SMALL'::portion_bucket
            WHEN 'STANDARD' THEN 'STANDARD'::portion_bucket
            WHEN 'LARGE' THEN 'LARGE'::portion_bucket
            ELSE NULL
        END
        """
    )
    op.drop_column("meal_segments", "quantity_display")
    op.drop_column("meal_segments", "quantity_json")
