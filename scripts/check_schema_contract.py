from pathlib import Path
import re
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import Boolean, Enum, String

from app.config import Settings
from app.models import (
    Base,
    FoodVisual,
    MealLog,
    MealProcessingStatus,
    MealSegment,
    PortionBucket,
)


REQUIRED_SETTINGS = {
    "DATABASE_URL",
    "INGEST_SECRET",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "OPENROUTER_API_KEY",
    "OPENROUTER_BASE_URL",
    "UPLOADS_DIR",
    "BOT_POLL_INTERVAL",
    "DEDUP_WINDOW_SECONDS",
}


def assert_settings_contract() -> None:
    fields = set(Settings.model_fields)
    missing = REQUIRED_SETTINGS - fields
    assert not missing, f"missing Settings fields: {sorted(missing)}"
    assert Settings.model_config["env_file"] == ".env"
    assert Settings.model_config["case_sensitive"] is True
    assert Settings.model_fields["OPENROUTER_BASE_URL"].default == (
        "https://openrouter.ai/api/v1"
    )
    assert Settings.model_fields["UPLOADS_DIR"].default == Path("/data/uploads")
    assert Settings.model_fields["BOT_POLL_INTERVAL"].default == 3.0
    assert Settings.model_fields["DEDUP_WINDOW_SECONDS"].default == 60


def assert_timestamp(column_name: str, table_name: str) -> None:
    column = Base.metadata.tables[table_name].c[column_name]
    assert getattr(column.type, "timezone", None) is True, (
        f"{table_name}.{column_name} must be TIMESTAMPTZ(timezone=True)"
    )
    assert column.server_default is not None, (
        f"{table_name}.{column_name} must have server_default"
    )


def assert_model_contract() -> None:
    assert MealProcessingStatus.FAILED.value == "FAILED"
    assert {bucket.value for bucket in PortionBucket} == {
        "SMALL",
        "STANDARD",
        "LARGE",
    }

    meal_logs = MealLog.__table__
    assert isinstance(meal_logs.c.image_hash.type, String)
    assert meal_logs.c.image_hash.type.length == 64
    assert "ix_meal_logs_image_hash_created" in {
        index.name for index in meal_logs.indexes
    }

    meal_segments = MealSegment.__table__
    assert getattr(meal_segments.c.embedding.type, "dim", None) == 1536
    assert isinstance(meal_segments.c.portion_bucket.type, Enum)
    assert "quantity_multiplier" not in meal_segments.c

    food_visuals = FoodVisual.__table__
    assert getattr(food_visuals.c.embedding.type, "dim", None) == 1536
    assert isinstance(food_visuals.c.is_invalidated.type, Boolean)
    hnsw_index = next(
        index
        for index in food_visuals.indexes
        if index.name == "ix_food_visuals_embedding"
    )
    pg_options = hnsw_index.dialect_options["postgresql"]
    assert pg_options["using"] == "hnsw"
    assert pg_options["ops"] == {"embedding": "vector_cosine_ops"}
    assert pg_options["with"] == {"m": 16, "ef_construction": 64}

    for table_name in (
        "meal_logs",
        "meal_segments",
        "food_items",
        "food_visuals",
        "diary_entries",
    ):
        assert_timestamp("created_at", table_name)
    assert_timestamp("updated_at", "meal_logs")
    assert_timestamp("updated_at", "food_items")


def assert_migration_contract() -> None:
    migration_path = Path("migrations/versions/001_initial_schema.py")
    text = migration_path.read_text()

    extension_pos = text.index("CREATE EXTENSION IF NOT EXISTS vector")
    vector_positions = [
        pos for pos in (text.find("Vector(1536)"), text.find("vector(1536)")) if pos >= 0
    ]
    assert vector_positions, "migration must declare vector(1536)"
    assert extension_pos < min(vector_positions)
    assert "FAILED" in text
    assert "USING hnsw" in text
    assert "USING ivfflat" not in text.lower()
    assert "m=16" in text
    assert "ef_construction=64" in text
    assert "portion_bucket" in text
    assert "image_hash" in text
    assert "is_invalidated" in text
    def create_table_position(table_name: str) -> int:
        match = re.search(rf"op\.create_table\(\s*[\"']{table_name}[\"']", text)
        assert match is not None, f"missing create_table for {table_name}"
        return match.start()

    assert create_table_position("food_items") < create_table_position("food_visuals")
    assert create_table_position("meal_logs") < create_table_position("meal_segments")


def main() -> None:
    assert_settings_contract()
    assert_model_contract()
    assert_migration_contract()
    print("schema contract ok")


if __name__ == "__main__":
    main()
