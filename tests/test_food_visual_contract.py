from __future__ import annotations

import importlib
import unittest

from app.models.food_visual import FoodVisual


class FoodVisualContractTests(unittest.TestCase):
    def test_food_visual_embedding_uses_1536_dimensional_vector_with_hnsw_cosine_index(self) -> None:
        embedding_column = FoodVisual.__table__.c.embedding
        self.assertEqual(getattr(embedding_column.type, "dim", None), 1536)

        indexes = {
            index.name: index
            for index in FoodVisual.__table__.indexes
        }
        self.assertIn("ix_food_visuals_embedding", indexes)

        index = indexes["ix_food_visuals_embedding"]
        self.assertEqual([column.name for column in index.columns], ["embedding"])

        postgres_options = index.dialect_options["postgresql"]
        self.assertEqual(postgres_options.get("using"), "hnsw")
        self.assertEqual(
            postgres_options.get("ops"),
            {"embedding": "vector_cosine_ops"},
        )
        self.assertEqual(
            postgres_options.get("with"),
            {"m": 16, "ef_construction": 64},
        )

    def test_initial_schema_migration_creates_required_food_visual_embedding_index(self) -> None:
        migration = importlib.import_module("migrations.versions.001_initial_schema")

        executed_sql: list[str] = []
        original_execute = migration.op.execute
        original_create_table = migration.op.create_table
        original_create_index = migration.op.create_index

        migration.op.execute = lambda sql: executed_sql.append(sql)
        migration.op.create_table = lambda *args, **kwargs: None
        migration.op.create_index = lambda *args, **kwargs: None

        try:
            migration.upgrade()
        finally:
            migration.op.execute = original_execute
            migration.op.create_table = original_create_table
            migration.op.create_index = original_create_index

        index_sql = next(
            (
                sql
                for sql in executed_sql
                if "CREATE INDEX ix_food_visuals_embedding" in sql
            ),
            None,
        )

        self.assertIsNotNone(index_sql)
        assert index_sql is not None
        self.assertIn("USING hnsw", index_sql)
        self.assertIn("(embedding vector_cosine_ops)", index_sql)
        self.assertIn("WITH (m=16, ef_construction=64)", index_sql)


if __name__ == "__main__":
    unittest.main()
