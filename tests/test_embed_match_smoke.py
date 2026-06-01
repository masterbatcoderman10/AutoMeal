from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


def _load_smoke_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "embed_match_smoke.py"
    spec = importlib.util.spec_from_file_location("embed_match_smoke", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load embed_match_smoke module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


smoke = _load_smoke_module()


class SmokeHelperTests(unittest.TestCase):
    def test_make_smoke_id_stays_within_schema_limit(self) -> None:
        meal_id = smoke._make_smoke_id("smoke-repeat-0")
        food_item_id = smoke._make_smoke_id("probe-unresolved-item")
        food_visual_id = smoke._make_smoke_id("probe-unresolved-visual")

        self.assertLessEqual(len(meal_id), 36)
        self.assertLessEqual(len(food_item_id), 36)
        self.assertLessEqual(len(food_visual_id), 36)
        self.assertNotEqual(meal_id, food_item_id)

    def test_resolve_crop_path_rejects_non_crop_input(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            whole_photo = tmp_path / "sample_images" / "IMG_4583.HEIC"
            whole_photo.parent.mkdir(parents=True, exist_ok=True)
            whole_photo.write_bytes(b"whole-photo")

            with self.assertRaisesRegex(RuntimeError, "crop artifact"):
                smoke._resolve_crop_path(whole_photo, flag_name="--sample")

    def test_resolve_crop_path_accepts_existing_crop_artifact(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            crop_path = tmp_path / "uploads" / "crops" / "seg-1.jpg"
            crop_path.parent.mkdir(parents=True, exist_ok=True)
            crop_path.write_bytes(b"crop")

            resolved = smoke._resolve_crop_path(crop_path, flag_name="--sample")

            self.assertEqual(resolved, crop_path.resolve())

    def test_food_groups_from_reasoning_state_reads_nested_meal_reasoning(self) -> None:
        groups = smoke._food_groups_from_reasoning_state(
            {
                "meal_reasoning": {
                    "food_groups": [
                        {"group_id": "group-1", "group_label": "egg curry"},
                        {"group_id": "group-2", "group_label": "pita bread"},
                    ]
                }
            }
        )

        self.assertEqual(
            groups,
            [
                {"group_id": "group-1", "group_label": "egg curry"},
                {"group_id": "group-2", "group_label": "pita bread"},
            ],
        )


class SmokeUatHarnessContractTests(unittest.TestCase):
    def test_uat_harness_named_scenarios_map_to_phase_regression_samples(self) -> None:
        resolver = getattr(smoke, "_resolve_uat_harness_scenario", None)
        self.assertIsNotNone(resolver, "missing _resolve_uat_harness_scenario helper")

        partial_match = resolver("partial-match")
        no_match = resolver("no-match")

        self.assertEqual(partial_match["scenario"], "partial-match")
        self.assertEqual(Path(partial_match["sample"]).name, "IMG_4583.HEIC")
        self.assertEqual(no_match["scenario"], "no-match")
        self.assertEqual(Path(no_match["sample"]).name, "IMG_4641.HEIC")

    def test_uat_harness_rejects_default_database_for_destructive_clone(self) -> None:
        gate = getattr(smoke, "_assert_safe_uat_target_database", None)
        self.assertIsNotNone(gate, "missing _assert_safe_uat_target_database helper")

        with self.assertRaisesRegex(RuntimeError, "mealttracker"):
            gate(
                "mealttracker",
                checkpoint_database="mealttracker_uat_with_meal_embeddings",
            )

        gate(
            "mealttracker_043_harness",
            checkpoint_database="mealttracker_uat_with_meal_embeddings",
        )

    def test_uat_harness_report_contains_required_audit_sections(self) -> None:
        builder = getattr(smoke, "_build_uat_harness_report", None)
        self.assertIsNotNone(builder, "missing _build_uat_harness_report helper")

        report = builder(
            scenario={"scenario": "partial-match", "sample": "sample_images/IMG_4583.HEIC"},
            target_database="mealttracker_043_harness",
            checkpoint_database="mealttracker_uat_with_meal_embeddings",
            api_base_url="http://127.0.0.1:18043",
            report_path=Path("uploads/reports/04.3/partial-match.json"),
            dry_run=True,
            meal={
                "meal_id": "meal-123",
                "processing_status": "INTERVIEWING",
                "reasoning_state_json": {"trace_id": "trace-meal"},
            },
            interview={
                "session_id": "session-123",
                "state_key": "QUESTION_BATCH",
                "current_prompt_payload": {
                    "questions_by_id": {"group_1:identity": {"prompt": "Which curry?"}},
                    "answers_by_question_id": {},
                    "grounding_status": "NOT_STARTED",
                },
                "messages": [{"role": "bot", "payload": {"prompt": "Which curry?"}}],
            },
            diary_entries=[{"id": "entry-1", "food_item_id": "food-1"}],
            food_visuals=[{"id": "visual-1", "food_item_id": "food-1"}],
        )

        self.assertEqual(report["scenario"]["name"], "partial-match")
        self.assertEqual(report["database"]["target"], "mealttracker_043_harness")
        self.assertEqual(report["meal"]["status"], "INTERVIEWING")
        self.assertIn("reasoning", report)
        self.assertIn("interview", report)
        self.assertIn("diary_entries", report)
        self.assertIn("food_visuals", report)
        self.assertIn("grounding", report)
        self.assertIn("traces", report)


class SmokeCalibrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_calibrate_embeds_crop_artifacts(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            crop_dir = tmp_path / "uploads" / "crops"
            crop_dir.mkdir(parents=True, exist_ok=True)
            sample_path = crop_dir / "sample.jpg"
            peer_path = crop_dir / "peer.jpg"
            random_path = crop_dir / "random.jpg"
            sample_path.write_bytes(b"sample")
            peer_path.write_bytes(b"peer")
            random_path.write_bytes(b"random")

            args = SimpleNamespace(
                sample=str(sample_path),
                same_food_peer=str(peer_path),
                random_food=str(random_path),
                cross_modal_text="rice and lentils",
                visual_corpus_size=0,
            )

            with (
                patch.object(
                    smoke.embedding_service,
                    "embed_image_for_document",
                    AsyncMock(side_effect=[[1.0], [0.5], [0.25]]),
                ) as embed_image,
                patch.object(
                    smoke.embedding_service,
                    "embed_text_for_query",
                    AsyncMock(return_value=[0.75]),
                ),
                patch.object(
                    smoke.embedding_service,
                    "cosine_similarity",
                    side_effect=[1.0, 0.5, 0.4, 0.1],
                ),
                patch.object(
                    smoke.embedding_service,
                    "passes_same_image_gate",
                    return_value=True,
                ),
                patch.object(
                    smoke.embedding_service,
                    "passes_cross_modal_gate",
                    return_value=True,
                ),
            ):
                report = await smoke._run_calibrate(args, llm_client=AsyncMock())

        self.assertEqual(
            [
                call.kwargs["image_path"]
                for call in embed_image.await_args_list
            ],
            [sample_path.resolve(), peer_path.resolve(), random_path.resolve()],
        )
        self.assertEqual(report["sample"], str(sample_path.resolve()))

    async def test_run_calibrate_uses_same_image_gate_for_sample_vector(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            crop_dir = tmp_path / "uploads" / "crops"
            crop_dir.mkdir(parents=True, exist_ok=True)
            sample_path = crop_dir / "sample.jpg"
            peer_path = crop_dir / "peer.jpg"
            sample_path.write_bytes(b"sample")
            peer_path.write_bytes(b"peer")

            args = SimpleNamespace(
                sample=str(sample_path),
                same_food_peer=str(peer_path),
                random_food=None,
                cross_modal_text=None,
                visual_corpus_size=0,
            )
            sample_vector = [1.0] + [0.0] * 1535
            peer_vector = [0.0, 1.0] + [0.0] * 1534

            with (
                patch.object(
                    smoke.embedding_service,
                    "embed_image_for_document",
                    AsyncMock(side_effect=[sample_vector, peer_vector]),
                ),
                patch.object(
                    smoke.embedding_service,
                    "cosine_similarity",
                    side_effect=[1.0, 0.12],
                ),
                patch.object(
                    smoke.embedding_service,
                    "passes_same_image_gate",
                    return_value=True,
                ) as passes_same_image_gate,
            ):
                report = await smoke._run_calibrate(args, llm_client=AsyncMock())

        passes_same_image_gate.assert_called_once_with(1.0)
        self.assertEqual(report["self_similarity"], 1.0)
        self.assertEqual(report["same_food_similarity"], 0.12)
        self.assertEqual(report["sample"], str(sample_path.resolve()))
        self.assertEqual(report["same_food_peer"], str(peer_path.resolve()))

    async def test_run_calibrate_requires_same_food_peer(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            crop_dir = tmp_path / "uploads" / "crops"
            crop_dir.mkdir(parents=True, exist_ok=True)
            sample_path = crop_dir / "sample.jpg"
            sample_path.write_bytes(b"sample")

            args = SimpleNamespace(
                sample=str(sample_path),
                same_food_peer=None,
                random_food=None,
                cross_modal_text=None,
                visual_corpus_size=0,
            )

            with self.assertRaisesRegex(RuntimeError, "--same-food-peer"):
                await smoke._run_calibrate(args, llm_client=AsyncMock())


class SmokeSeedDemoTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_seed_demo_embeds_crop_artifact(self) -> None:
        class FakeEngine:
            async def dispose(self) -> None:
                return None

        class FakeSession:
            def __init__(self) -> None:
                self.added: list[object] = []

            async def __aenter__(self) -> "FakeSession":
                return self

            async def __aexit__(self, exc_type, exc, tb) -> None:
                return None

            async def scalar(self, statement) -> None:
                return None

            def add(self, item: object) -> None:
                self.added.append(item)

            async def commit(self) -> None:
                return None

        fake_engine = FakeEngine()
        fake_session = FakeSession()
        sample_path = Path("/tmp/uploads/crops/sample.jpg")
        args = SimpleNamespace(
            sample=str(sample_path),
            second_sample=None,
            database_url="postgresql://example",
        )

        with (
            patch.object(smoke, "create_async_engine", return_value=fake_engine),
            patch.object(smoke, "async_sessionmaker", return_value=lambda: fake_session),
            patch.object(smoke, "_resolve_crop_path", return_value=sample_path),
            patch.object(
                smoke.embedding_service,
                "embed_image_for_document",
                AsyncMock(return_value=[0.1, 0.2]),
            ) as embed_image,
        ):
            report = await smoke._run_seed_demo(args, llm_client=AsyncMock())

        embed_image.assert_awaited_once()
        self.assertEqual(embed_image.await_args.kwargs["image_path"], sample_path)
        self.assertEqual(report["seeded_food_items"], ["daal-chawal"])
        food_visual = next(
            item for item in fake_session.added if isinstance(item, smoke.FoodVisual)
        )
        self.assertEqual(food_visual.cropped_image_url, str(sample_path))


class SmokeReasoningProbeTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_reasoning_probe_reuses_matching_and_reasoning_services(self) -> None:
        class FakeEngine:
            async def dispose(self) -> None:
                return None

        class FakeSession:
            async def __aenter__(self) -> "FakeSession":
                return self

            async def __aexit__(self, exc_type, exc, tb) -> None:
                return None

        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            sample_path = tmp_path / "sample_images" / "IMG_4583.HEIC"
            sample_path.parent.mkdir(parents=True, exist_ok=True)
            sample_path.write_bytes(b"whole-photo")

            args = SimpleNamespace(
                sample=str(sample_path),
                database_url="postgresql+asyncpg://example",
            )
            fake_session = FakeSession()
            llm_client = object()
            candidate_payloads = [
                {
                    "candidate_id": f"candidate-{idx}",
                    "label": "rice and curry",
                    "identity_confidence": 0.96 - (idx * 0.05),
                    "quantity_confidence": 0.86,
                    "match_consistency_confidence": 0.9,
                    "visual_evidence": ["stored visual candidate"],
                    "missing_evidence": [],
                    "specificity": "high",
                    "nutrition_relevance": "medium",
                    "source": "vector_match",
                    "decision_rationale": "stable match",
                    "nutrition_impact": 0.1,
                }
                for idx in range(3)
            ]
            match_result = smoke.matching_service.SegmentMatchResult(
                food_visual_id="visual-1",
                food_item_id="food-1",
                similarity=0.96,
                food_visual=None,
                query_embedding=[0.1] * smoke.matching_service.EMBEDDING_DIMENSION,
                is_match=True,
                is_below_threshold=False,
                candidate_payloads=candidate_payloads,
            )

            with (
                patch.object(smoke, "create_async_engine", return_value=FakeEngine()),
                patch.object(smoke, "async_sessionmaker", return_value=lambda: fake_session),
                patch.object(
                    smoke,
                    "get_settings",
                    return_value=SimpleNamespace(
                        DATABASE_URL="postgresql+asyncpg://example",
                        REASONING_MODEL="google/gemini-3-flash-preview",
                    ),
                ),
                patch.object(
                    smoke.matching_service,
                    "match_segment_against_visual_corpus",
                    AsyncMock(return_value=match_result),
                ) as match_segment,
                patch.object(
                    smoke.reasoning_service,
                    "run_reasoning_request",
                    AsyncMock(
                        return_value=(
                            {
                                "action": "AUTO_CONFIRM",
                                "meal_state": "READY_TO_WRITE",
                                "gate_reason": "",
                                "decision_rationale": "Auto-confirm pass",
                                "trace_id": "trace-123",
                                "top_3": candidate_payloads,
                            },
                            {"cached_tokens": 42, "trace_id": "trace-123"},
                        )
                    ),
                ) as run_reasoning,
            ):
                report = await smoke._run_reasoning_probe(args, llm_client=llm_client)

        match_segment.assert_awaited_once()
        self.assertEqual(match_segment.await_args.kwargs["llm_client"], llm_client)
        self.assertEqual(
            match_segment.await_args.kwargs["segment"].cropped_image_url,
            str(sample_path.resolve()),
        )
        run_reasoning.assert_awaited_once()
        self.assertEqual(run_reasoning.await_args.kwargs["llm_client"], llm_client)
        self.assertEqual(report["meal_state"], "READY_TO_WRITE")
        self.assertTrue(report["gate_auto_confirmed"])
        self.assertEqual(report["cached_tokens"], 42)
        self.assertEqual(report["match"]["candidate_count"], 3)


class SmokeGroupedUatTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_grouped_uat_skips_segment_label_model_and_uses_detector_hints(self) -> None:
        class FakeEngine:
            async def dispose(self) -> None:
                return None

        class FakeSessionContext:
            def __init__(self) -> None:
                self.added: list[object] = []

            async def __aenter__(self) -> "FakeSessionContext":
                return self

            async def __aexit__(self, exc_type, exc, tb) -> None:
                return None

            def add(self, item: object) -> None:
                self.added.append(item)

            async def flush(self) -> None:
                return None

            async def commit(self) -> None:
                return None

        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            sample_path = tmp_path / "sample_images" / "meal.jpg"
            sample_path.parent.mkdir(parents=True, exist_ok=True)
            sample_path.write_bytes(b"grouped-meal")

            crop_path = tmp_path / "uploads" / "crops" / "seg-1.jpg"
            crop_path.parent.mkdir(parents=True, exist_ok=True)
            crop_path.write_bytes(b"crop")

            args = SimpleNamespace(
                sample=str(sample_path),
                database_url="postgresql+asyncpg://example",
            )
            session = FakeSessionContext()
            match_result = SimpleNamespace(
                food_visual_id=None,
                food_item_id=None,
                similarity=0.41,
                is_match=False,
                is_below_threshold=True,
                query_embedding=[0.1] * 1536,
                top_candidates=[
                    {
                        "candidate_id": "candidate-curry",
                        "label": "chicken curry",
                        "identity_confidence": 0.82,
                        "quantity_confidence": 0.8,
                        "match_consistency_confidence": 0.8,
                        "visual_evidence": ["green herb garnish"],
                        "missing_evidence": [],
                        "specificity": "medium",
                        "nutrition_relevance": "medium",
                        "source": "vector_match",
                        "decision_rationale": "Nearest stored curry variant.",
                        "nutrition_impact": 0.05,
                    }
                ],
            )
            reasoning_payload = {
                "action": "AUTO_CONFIRM",
                "meal_state": "READY_TO_WRITE",
                "trace_id": "trace-grouped-uat",
                "decision_rationale": "Reasoning resolved the curry color and style from the whole plate.",
                "gate_reason": "",
                "segment_count": 1,
                "food_group_count": 1,
                "food_groups": [
                    {
                        "group_id": "group-curry",
                        "group_label": "green chicken curry",
                        "group_action": "AUTO_CONFIRM",
                        "group_state": "READY_TO_WRITE",
                        "primary_segment_id": "segment-grouped",
                        "segment_ids": ["segment-grouped"],
                        "selected_candidate_id": "candidate-curry",
                        "top_3": match_result.top_candidates,
                    }
                ],
            }

            with (
                patch.object(smoke, "create_async_engine", return_value=FakeEngine()),
                patch.object(smoke, "async_sessionmaker", return_value=lambda: session),
                patch.object(
                    smoke,
                    "get_settings",
                    return_value=SimpleNamespace(
                        DATABASE_URL="postgresql+asyncpg://example",
                        DETECT_MODEL="detect-model",
                        SEGMENT_MODEL="segment-model",
                        SEGMENT_RETRY_MODEL="segment-retry-model",
                        VISION_MAX_SEGMENTS=4,
                        LABEL_MODEL="label-model",
                    ),
                ),
                patch.object(
                    smoke,
                    "detect_food_photo",
                    AsyncMock(return_value={"next_action": "segment"}),
                ),
                patch.object(
                    smoke,
                    "segment_food_photo_with_retry",
                    AsyncMock(
                        return_value=[
                            SimpleNamespace(
                                box_2d=[0.1, 0.1, 0.8, 0.9],
                                label_hint="curry",
                            )
                        ]
                    ),
                ),
                patch.object(smoke, "dedupe_overlapping_segments", side_effect=lambda segments: segments),
                patch.object(smoke, "save_segment_crop", return_value=crop_path),
                patch.object(
                    smoke.matching_service,
                    "match_segment_against_visual_corpus",
                    AsyncMock(return_value=match_result),
                ),
                patch.object(smoke.matching_service, "persist_match_candidate_snapshot"),
                patch.object(
                    smoke.reasoning_service,
                    "run_reasoning_request",
                    AsyncMock(return_value=(reasoning_payload, {"trace_id": "trace-grouped-uat"})),
                ),
                patch.object(
                    smoke.reasoning_service,
                    "finalize_meal_from_reasoning",
                    AsyncMock(
                        return_value={
                            "finalized": True,
                            "food_groups": reasoning_payload["food_groups"],
                        }
                    ),
                ),
            ):
                report = await smoke._run_grouped_uat(args, llm_client=object())

        self.assertFalse(hasattr(smoke, "label_food_segment"))
        self.assertEqual(
            report["segment_labels"],
            [
                {
                    "segment_id": report["segment_labels"][0]["segment_id"],
                    "label": "curry",
                    "crop_path": str(crop_path),
                }
            ],
        )
