"""Initial MealTracker schema.

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-05-26
"""

from collections.abc import Sequence

from alembic import op
from pgvector.sqlalchemy import Vector
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import TIMESTAMP as TIMESTAMPTZ


revision: str = "001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


MEAL_PROCESSING_STATUS = postgresql.ENUM(
    "PENDING",
    "DETECTING",
    "SEGMENTING",
    "EMBEDDING",
    "MATCHING",
    "REASONING",
    "INTERVIEWING",
    "COMPLETED",
    "FAILED",
    name="meal_processing_status",
    create_type=False,
)

PORTION_BUCKET = postgresql.ENUM(
    "SMALL",
    "STANDARD",
    "LARGE",
    name="portion_bucket",
    create_type=False,
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE meal_processing_status AS ENUM (
                'PENDING',
                'DETECTING',
                'SEGMENTING',
                'EMBEDDING',
                'MATCHING',
                'REASONING',
                'INTERVIEWING',
                'COMPLETED',
                'FAILED'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE portion_bucket AS ENUM (
                'SMALL',
                'STANDARD',
                'LARGE'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
        """
    )

    op.create_table(
        "food_items",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=True),
        sa.Column("source_type", sa.String(length=32), nullable=True),
        sa.Column("brand_name", sa.String(length=256), nullable=True),
        sa.Column("restaurant_name", sa.String(length=256), nullable=True),
        sa.Column("serving_size_g", sa.Float(), nullable=True),
        sa.Column("calories", sa.Float(), nullable=True),
        sa.Column("protein_g", sa.Float(), nullable=True),
        sa.Column("carbs_g", sa.Float(), nullable=True),
        sa.Column("fat_g", sa.Float(), nullable=True),
        sa.Column("fiber_g", sa.Float(), nullable=True),
        sa.Column("times_confirmed", sa.Integer(), nullable=False),
        sa.Column("is_verified", sa.Boolean(), nullable=False),
        sa.Column("llm_reasoning", sa.Text(), nullable=True),
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
        ),
    )

    op.create_table(
        "food_visuals",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("food_item_id", sa.String(length=36), nullable=False),
        sa.Column("cropped_image_url", sa.String(length=512), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column("is_invalidated", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            TIMESTAMPTZ(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["food_item_id"], ["food_items.id"]),
    )

    op.create_table(
        "meal_logs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("image_url", sa.String(length=512), nullable=False),
        sa.Column("image_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "processing_status",
            MEAL_PROCESSING_STATUS,
            nullable=False,
            server_default="PENDING",
        ),
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
        ),
    )

    op.create_table(
        "meal_segments",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("meal_log_id", sa.String(length=36), nullable=False),
        sa.Column("label", sa.String(length=256), nullable=True),
        sa.Column("bounding_box", sa.JSON(), nullable=True),
        sa.Column("cropped_image_url", sa.String(length=512), nullable=True),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("ai_reasoning", sa.Text(), nullable=True),
        sa.Column("portion_bucket", PORTION_BUCKET, nullable=True),
        sa.Column(
            "created_at",
            TIMESTAMPTZ(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["meal_log_id"], ["meal_logs.id"]),
    )

    op.create_table(
        "diary_entries",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("meal_log_id", sa.String(length=36), nullable=False),
        sa.Column("food_item_id", sa.String(length=36), nullable=False),
        sa.Column("segment_id", sa.String(length=36), nullable=True),
        sa.Column("portion_bucket", sa.String(length=32), nullable=False),
        sa.Column("identification_method", sa.String(length=32), nullable=False),
        sa.Column("is_verified", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            TIMESTAMPTZ(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["meal_log_id"], ["meal_logs.id"]),
        sa.ForeignKeyConstraint(["food_item_id"], ["food_items.id"]),
        sa.ForeignKeyConstraint(["segment_id"], ["meal_segments.id"]),
    )

    op.execute(
        """
        CREATE INDEX ix_food_visuals_embedding
        ON food_visuals
        USING hnsw (embedding vector_cosine_ops)
        WITH (m=16, ef_construction=64)
        """
    )
    op.create_index(
        "ix_meal_logs_image_hash_created",
        "meal_logs",
        ["image_hash", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_meal_logs_image_hash_created", table_name="meal_logs")
    op.drop_index("ix_food_visuals_embedding", table_name="food_visuals")
    op.drop_table("diary_entries")
    op.drop_table("meal_segments")
    op.drop_table("meal_logs")
    op.drop_table("food_visuals")
    op.drop_table("food_items")
    op.execute("DROP TYPE IF EXISTS portion_bucket")
    op.execute("DROP TYPE IF EXISTS meal_processing_status")
    op.execute("DROP EXTENSION IF EXISTS vector")
