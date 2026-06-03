from pathlib import Path
import re
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import Boolean, Enum, JSON, Integer, String
from sqlalchemy.dialects.postgresql import TIMESTAMP as TIMESTAMPTZ

from app.config import Settings
from app.models import (
    Base,
    FoodVisual,
    InterviewMessage,
    InterviewSession,
    MealLog,
    MealProcessingStatus,
    CorrectionEvent,
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
    assert isinstance(meal_logs.c.reasoning_state_json.type, JSON)
    assert isinstance(meal_logs.c.last_stage_started_at.type, TIMESTAMPTZ)
    assert isinstance(meal_logs.c.last_recovery_notified_at.type, TIMESTAMPTZ)
    assert isinstance(meal_logs.c.recovery_attempt_count.type, Integer)
    assert meal_logs.c.recovery_attempt_count.default is not None

    meal_segments = MealSegment.__table__
    assert getattr(meal_segments.c.embedding.type, "dim", None) == 1536
    assert isinstance(meal_segments.c.portion_bucket.type, Enum)
    assert isinstance(meal_segments.c.ai_reasoning.type, JSON)
    assert isinstance(meal_segments.c.match_candidates_json.type, JSON)
    assert isinstance(meal_segments.c.reasoning_trace_id.type, String)
    assert meal_segments.c.reasoning_trace_id.type.length == 64
    assert "quantity_multiplier" not in meal_segments.c

    food_visuals = FoodVisual.__table__
    assert getattr(food_visuals.c.embedding.type, "dim", None) == 1536
    assert isinstance(food_visuals.c.is_invalidated.type, Boolean)
    assert isinstance(food_visuals.c.invalidated_at.type, TIMESTAMPTZ)
    assert isinstance(food_visuals.c.invalidation_reason.type, String)
    assert food_visuals.c.invalidation_reason.type.length == 1024
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
    assert isinstance(Base.metadata.tables["diary_entries"].c.quantity_json.type, JSON)
    assert isinstance(Base.metadata.tables["diary_entries"].c.quantity_display.type, String)
    assert Base.metadata.tables["diary_entries"].c.quantity_display.type.length == 128
    assert_timestamp("updated_at", "meal_logs")
    assert_timestamp("updated_at", "food_items")

    interview_sessions = InterviewSession.__table__
    assert isinstance(interview_sessions.c.chat_id.type, String)
    assert interview_sessions.c.chat_id.type.length == 64
    assert interview_sessions.c.state_key.type.length == 64
    assert isinstance(interview_sessions.c.current_prompt_payload.type, JSON)
    assert isinstance(interview_sessions.c.last_bot_message_id.type, Integer)
    assert interview_sessions.c.reminder_count.default is not None
    assert isinstance(interview_sessions.c.is_active.type, Boolean)
    assert isinstance(interview_sessions.c.last_reminder_at.type, TIMESTAMPTZ)

    interview_messages = InterviewMessage.__table__
    assert isinstance(interview_messages.c.role.type, String)
    assert interview_messages.c.role.type.length == 16
    assert isinstance(interview_messages.c.payload.type, JSON)
    assert isinstance(interview_messages.c.message_id.type, Integer)

    correction_events = CorrectionEvent.__table__
    assert isinstance(correction_events.c.before_json.type, JSON)
    assert isinstance(correction_events.c.after_json.type, JSON)
    assert isinstance(correction_events.c.visual_learning_eligible.type, Boolean)
    assert isinstance(correction_events.c.trace_id.type, String)
    assert correction_events.c.trace_id.type.length == 64


def assert_migration_contract() -> None:
    initial_migration = Path("migrations/versions/001_initial_schema.py").read_text()
    phase4_migration = Path(
        "migrations/versions/002_phase4_state_surfaces.py"
    ).read_text()

    extension_pos = initial_migration.index("CREATE EXTENSION IF NOT EXISTS vector")
    vector_positions = [
        pos
        for pos in (
            initial_migration.find("Vector(1536)"),
            initial_migration.find("vector(1536)"),
        )
        if pos >= 0
    ]
    assert vector_positions, "migration must declare vector(1536)"
    assert extension_pos < min(vector_positions)
    assert "FAILED" in initial_migration
    assert "USING hnsw" in initial_migration
    assert "USING ivfflat" not in initial_migration.lower()
    assert "m=16" in initial_migration
    assert "ef_construction=64" in initial_migration
    assert "portion_bucket" in initial_migration
    assert "image_hash" in initial_migration
    assert "is_invalidated" in initial_migration

    assert "reasoning_state_json" in phase4_migration
    assert "last_stage_started_at" in phase4_migration
    assert "recovery_attempt_count" in phase4_migration
    assert "last_recovery_notified_at" in phase4_migration
    assert "match_candidates_json" in phase4_migration
    assert "reasoning_trace_id" in phase4_migration
    assert "ai_reasoning" in phase4_migration and "alter_column" in phase4_migration
    assert "quantity_json" in phase4_migration
    assert "quantity_display" in phase4_migration
    assert "invalidated_at" in phase4_migration
    assert "invalidation_reason" in phase4_migration
    assert "interview_sessions" in phase4_migration
    assert "interview_messages" in phase4_migration
    assert "correction_events" in phase4_migration
    assert "current_prompt_payload" in phase4_migration
    assert "visual_learning_eligible" in phase4_migration
    def create_table_position(text: str, table_name: str) -> int:
        match = re.search(rf"op\.create_table\(\s*[\"']{table_name}[\"']", text)
        assert match is not None, f"missing create_table for {table_name}"
        return match.start()

    assert create_table_position(initial_migration, "food_items") < create_table_position(
        initial_migration, "food_visuals"
    )
    assert create_table_position(initial_migration, "meal_logs") < create_table_position(
        initial_migration, "meal_segments"
    )


def main() -> None:
    assert_settings_contract()
    assert_model_contract()
    assert_migration_contract()
    print("schema contract ok")


if __name__ == "__main__":
    main()
