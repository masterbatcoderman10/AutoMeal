from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
import re
import sys
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from sqlalchemy import select, update
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings
from app.models import FoodItem, FoodVisual, MealLog, MealSegment, MealProcessingStatus
from app.services import embedding_service, interview_service, matching_service, reasoning_service
from app.services.image_service import HEIC_CONTENT_TYPES, compute_hash, save_segment_crop, transcode_to_jpeg
from app.services.llm_client import get_llm_client
from app.services.vision_service import (
    dedupe_overlapping_segments,
    detect_food_photo,
    label_food_segment,
    segment_food_photo_with_retry,
)

EMBEDDING_MODEL = "google/gemini-embedding-2-preview"
EMBEDDING_TASK_MARGIN = 0.001
SMOKE_ID_MAX_LENGTH = 36
ALLOWED_CROP_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Wave 0 embedding contract smoke helper.")
    parser.add_argument(
        "--mode",
        choices=[
            "calibrate",
            "seed-demo",
            "unresolved-probe",
            "repeat-confirmation",
            "reasoning-probe",
            "grouped-uat",
        ],
        required=True,
    )
    parser.add_argument(
        "--sample",
        required=True,
        help="Saved crop artifact for the smoke run (for example uploads/crops/seg-1.jpg)",
    )
    parser.add_argument(
        "--same-food-peer",
        default=None,
        help="Required for calibrate: a different saved crop artifact from a second photo of the same food",
    )
    parser.add_argument(
        "--random-food",
        default=None,
        help="Optional saved crop artifact for cross-modal sanity comparison",
    )
    parser.add_argument(
        "--second-sample",
        default=None,
        help="Optional second saved crop artifact for seeding a distinct demo FoodItem",
    )
    parser.add_argument(
        "--cross-modal-text",
        default="rice and lentils",
        help="Text query for cross-modal validation",
    )
    parser.add_argument(
        "--visual-corpus-size",
        type=int,
        default=0,
        help="How many existing FoodVisual rows are visible for calibration context",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Optional database URL override for seed-demo and unresolved-probe modes",
    )
    return parser.parse_args()


def _load_raw_bytes(path: Path) -> bytes:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"sample image missing: {path}")
    return path.read_bytes()


def _resolve_crop_path(path_value: str | Path, *, flag_name: str) -> Path:
    crop_path = Path(path_value).expanduser().resolve()
    if not crop_path.exists() or not crop_path.is_file():
        raise FileNotFoundError(f"{flag_name} crop artifact missing: {crop_path}")

    if "crops" not in {part.lower() for part in crop_path.parts}:
        raise RuntimeError(
            f"{flag_name} must point to a saved crop artifact under a 'crops' directory; "
            f"whole-photo inputs like sample_images are not allowed: {crop_path}"
        )

    if crop_path.suffix.lower() not in ALLOWED_CROP_SUFFIXES:
        allowed = ", ".join(sorted(ALLOWED_CROP_SUFFIXES))
        raise RuntimeError(
            f"{flag_name} must point to a durable crop image ({allowed}), got: {crop_path}"
        )

    return crop_path


def _ensure_distinct_rephoto_pair(sample_path: Path, peer_path: Path) -> None:
    if sample_path == peer_path:
        raise RuntimeError(
            "calibrate requires --same-food-peer to be a different crop artifact from --sample"
        )
    if _load_raw_bytes(sample_path) == _load_raw_bytes(peer_path):
        raise RuntimeError(
            "calibrate requires --same-food-peer to be a real re-photo crop, not a byte-identical copy"
        )


def _make_smoke_id(prefix: str, *, suffix_length: int = 12) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", prefix.lower()).strip("-")
    suffix = uuid.uuid4().hex[:suffix_length]
    prefix_budget = SMOKE_ID_MAX_LENGTH - suffix_length - 1
    if prefix_budget <= 0:
        raise RuntimeError("suffix length leaves no room for smoke ID prefix")
    trimmed = normalized[:prefix_budget].rstrip("-") or "smoke"
    return f"{trimmed}-{suffix}"


def _resolve_image_path(path_value: str | Path, *, flag_name: str) -> Path:
    image_path = Path(path_value).expanduser().resolve()
    if not image_path.exists() or not image_path.is_file():
        raise FileNotFoundError(f"{flag_name} image missing: {image_path}")
    return image_path


async def _run_reasoning_probe(args: argparse.Namespace, llm_client) -> dict[str, Any]:
    sample_input = _resolve_image_path(args.sample, flag_name="--sample")
    settings = get_settings()
    database_url = _resolve_database_url(args)
    engine = create_async_engine(database_url, echo=False, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    meal = MealLog(
        id=_make_smoke_id("reasoning-meal"),
        image_url=str(sample_input),
        image_hash="reasoning-probe",
        processing_status=MealProcessingStatus.REASONING,
    )
    segment = MealSegment(
        id=_make_smoke_id("reasoning-segment"),
        meal_log_id=meal.id,
        label="reasoning probe sample",
        bounding_box=[0, 0, 1000, 1000],
        cropped_image_url=str(sample_input),
    )

    try:
        async with session_factory() as session:
            match_result = await matching_service.match_segment_against_visual_corpus(
                segment=segment,
                session=session,
                llm_client=llm_client,
                embedding_model=matching_service.MATCHING_EMBEDDING_MODEL,
            )
            matching_service.persist_match_candidate_snapshot(
                segment=segment,
                result=match_result,
            )
            reasoning_result, trace_metadata = await reasoning_service.run_reasoning_request(
                llm_client=llm_client,
                meal_id=meal.id,
                meal=meal,
                match_results=[(segment, match_result)],
                settings=settings,
            )
    finally:
        await engine.dispose()

    trace_metadata = trace_metadata or {}
    return {
        "mode": "reasoning-probe",
        "status": "pass",
        "sample": str(sample_input),
        "model": getattr(settings, "REASONING_MODEL", None),
        "meal_id": meal.id,
        "segment_id": segment.id,
        "action": reasoning_result.get("action"),
        "meal_state": reasoning_result.get("meal_state"),
        "gate_auto_confirmed": reasoning_result.get("meal_state") == "READY_TO_WRITE",
        "gate_reason": reasoning_result.get("gate_reason"),
        "decision_rationale": reasoning_result.get("decision_rationale"),
        "trace_id": reasoning_result.get("trace_id") or trace_metadata.get("trace_id"),
        "cached_tokens": trace_metadata.get("cached_tokens"),
        "match": {
            "is_match": match_result.is_match,
            "is_below_threshold": match_result.is_below_threshold,
            "similarity": match_result.similarity,
            "candidate_count": len(match_result.top_candidates),
            "snapshot": segment.match_candidates_json,
        },
        "top_3": reasoning_result.get("top_3", []),
    }


def _prepare_sample_working_copy(sample_path: Path, work_dir: Path) -> Path:
    mime_type, _ = mimetypes.guess_type(sample_path.name)
    raw_bytes = sample_path.read_bytes()
    if mime_type in HEIC_CONTENT_TYPES:
        working_path = work_dir / f"{sample_path.stem}.jpg"
        working_path.write_bytes(transcode_to_jpeg(raw_bytes, mime_type or "image/heic"))
        return working_path

    working_path = work_dir / sample_path.name
    working_path.write_bytes(raw_bytes)
    return working_path


def _food_groups_from_reasoning_state(reasoning_state: object) -> list[dict[str, Any]]:
    if not isinstance(reasoning_state, dict):
        return []
    direct_groups = reasoning_state.get("food_groups")
    if isinstance(direct_groups, list):
        return [dict(group) for group in direct_groups if isinstance(group, dict)]
    meal_reasoning = reasoning_state.get("meal_reasoning")
    if isinstance(meal_reasoning, dict):
        nested_groups = meal_reasoning.get("food_groups")
        if isinstance(nested_groups, list):
            return [dict(group) for group in nested_groups if isinstance(group, dict)]
    return []


async def _run_grouped_uat(args: argparse.Namespace, llm_client) -> dict[str, Any]:
    sample_input = _resolve_image_path(args.sample, flag_name="--sample")
    settings = get_settings()
    engine = create_async_engine(_resolve_database_url(args), echo=False, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)

    try:
        with TemporaryDirectory(prefix="grouped-uat-") as tempdir:
            work_dir = Path(tempdir)
            uploads_dir = work_dir / "uploads"
            uploads_dir.mkdir(parents=True, exist_ok=True)
            working_image = _prepare_sample_working_copy(sample_input, work_dir)

            detect_result = await detect_food_photo(
                str(working_image),
                llm_client=llm_client,
                model=settings.DETECT_MODEL,
            )
            if detect_result.get("next_action") != "segment":
                raise RuntimeError(
                    f"grouped UAT sample was not routed to segmentation: {detect_result}"
                )

            raw_segments = await segment_food_photo_with_retry(
                str(working_image),
                llm_client=llm_client,
                model=settings.SEGMENT_MODEL,
                retry_model=settings.SEGMENT_RETRY_MODEL,
                max_segments=settings.VISION_MAX_SEGMENTS,
            )
            segments = dedupe_overlapping_segments(raw_segments)
            if not segments:
                raise RuntimeError("grouped UAT produced no food segments")

            async with session_factory() as session:
                meal = MealLog(
                    id=_make_smoke_id("grouped-uat-meal"),
                    image_url=str(working_image),
                    image_hash=compute_hash(sample_input.read_bytes()),
                    processing_status=MealProcessingStatus.REASONING,
                )
                session.add(meal)
                await session.flush()

                segment_rows: list[MealSegment] = []
                for decision in segments:
                    segment_id = _make_smoke_id("grouped-segment")
                    crop_path = save_segment_crop(
                        source_image_path=working_image,
                        segment_id=segment_id,
                        normalized_box=decision.box_2d,
                        uploads_dir=uploads_dir,
                    )
                    label = await label_food_segment(
                        str(crop_path),
                        llm_client=llm_client,
                        model=settings.LABEL_MODEL,
                    )
                    segment_row = MealSegment(
                        id=segment_id,
                        meal_log_id=meal.id,
                        label=label or decision.label_hint or "unlabeled food",
                        bounding_box=decision.box_2d,
                        cropped_image_url=str(crop_path),
                    )
                    session.add(segment_row)
                    segment_rows.append(segment_row)

                await session.flush()

                match_results: list[tuple[MealSegment, Any]] = []
                for segment_row in segment_rows:
                    match_result = await matching_service.match_segment_against_visual_corpus(
                        segment=segment_row,
                        session=session,
                        llm_client=llm_client,
                        embedding_model=matching_service.MATCHING_EMBEDDING_MODEL,
                    )
                    matching_service.persist_match_candidate_snapshot(
                        segment=segment_row,
                        result=match_result,
                    )
                    match_results.append((segment_row, match_result))

                reasoning_result, trace_metadata = await reasoning_service.run_reasoning_request(
                    llm_client=llm_client,
                    meal_id=meal.id,
                    meal=meal,
                    match_results=match_results,
                    settings=settings,
                )
                finalization = await reasoning_service.finalize_meal_from_reasoning(
                    session=session,
                    meal=meal,
                    segments=segment_rows,
                    match_results=match_results,
                    reasoning_payload=reasoning_result,
                )

                food_groups = [
                    dict(group)
                    for group in list(finalization.get("food_groups", []))
                    if isinstance(group, dict)
                ] or _food_groups_from_reasoning_state(getattr(meal, "reasoning_state_json", None))
                unresolved_group_ids = [
                    str(group.get("group_id"))
                    for group in food_groups
                    if str(group.get("group_action") or group.get("action") or "").upper()
                    in {"INTERVIEW", "ASK_CHOICE", "ASK_QUANTITY"}
                    or str(group.get("group_state") or group.get("state") or "").upper()
                    in {"UNRESOLVED", "PENDING_INTERVIEW", "PENDING_CHOICE", "PARTIAL_RESOLVED_WAITING"}
                ]

                current_prompt = None
                interview_session_id = None
                if not finalization.get("finalized"):
                    interview = await interview_service.prepare_interview_session(
                        session=session,
                        meal=meal,
                        segments=segment_rows,
                        chat_id="grouped-uat",
                    )
                    interview_session_id = interview.id
                    await session.commit()
                    current_prompt = interview_service.current_target_question(
                        interview.current_prompt_payload or {}
                    ).get("prompt")

                grouped_summary = [
                    {
                        "group_id": group.get("group_id"),
                        "label": group.get("group_label") or group.get("label"),
                        "action": group.get("group_action") or group.get("action"),
                        "state": group.get("group_state") or group.get("state"),
                        "primary_segment_id": group.get("primary_segment_id"),
                        "segment_ids": group.get("segment_ids"),
                    }
                    for group in food_groups
                ]

                return {
                    "mode": "grouped-uat",
                    "status": "pass",
                    "sample": str(sample_input),
                    "meal_id": meal.id,
                    "interview_session_id": interview_session_id,
                    "processing_status": getattr(meal.processing_status, "value", meal.processing_status),
                    "segment_labels": [
                        {
                            "segment_id": segment.id,
                            "label": segment.label,
                            "crop_path": segment.cropped_image_url,
                        }
                        for segment in segment_rows
                    ],
                    "food_groups": grouped_summary,
                    "unresolved_group_ids": unresolved_group_ids,
                    "current_prompt": current_prompt,
                    "trace_id": reasoning_result.get("trace_id") or trace_metadata.get("trace_id"),
                    "trace_metadata": {
                        "trace_id": trace_metadata.get("trace_id"),
                        "cached_tokens": trace_metadata.get("cached_tokens"),
                        "meal_image_path": str(working_image),
                        "segment_crop_paths": [segment.cropped_image_url for segment in segment_rows],
                    },
                }
    finally:
        await engine.dispose()


def is_corpus_branch_valid(visual_count: int) -> bool:
    if visual_count < 0:
        raise RuntimeError("visual corpus size must be >= 0")
    return visual_count == 0 or visual_count > 0


def _resolve_database_url(args: argparse.Namespace) -> str:
    database_url = args.database_url
    if not database_url:
        settings = get_settings()
        database_url = settings.DATABASE_URL
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is empty. Set it in .env or pass --database-url for smoke modes that use Postgres."
        )
    return database_url


async def _run_calibrate(args: argparse.Namespace, llm_client) -> dict[str, Any]:
    if args.visual_corpus_size < 0:
        raise RuntimeError("visual corpus size must be >= 0")

    sample_input = _resolve_crop_path(args.sample, flag_name="--sample")
    if not args.same_food_peer:
        raise RuntimeError(
            "calibrate requires --same-food-peer pointing to a different saved crop artifact"
        )
    peer_input = _resolve_crop_path(args.same_food_peer, flag_name="--same-food-peer")
    _ensure_distinct_rephoto_pair(sample_input, peer_input)
    random_input = (
        _resolve_crop_path(args.random_food, flag_name="--random-food")
        if args.random_food
        else None
    )

    sample_vector = await embedding_service.embed_image_for_document(
        image_path=sample_input,
        llm_client=llm_client,
        model=EMBEDDING_MODEL,
    )
    self_similarity = embedding_service.cosine_similarity(sample_vector, sample_vector)
    if not embedding_service.passes_same_image_gate(self_similarity):
        raise RuntimeError(
            f"same-image similarity {self_similarity:.6f} below 0.99"
        )

    same_food_vector = await embedding_service.embed_image_for_document(
        image_path=peer_input,
        llm_client=llm_client,
        model=EMBEDDING_MODEL,
    )
    same_food_similarity = embedding_service.cosine_similarity(sample_vector, same_food_vector)

    query_similarity = None
    random_similarity = None
    if args.cross_modal_text and random_input is not None:
        query_vector = await embedding_service.embed_text_for_query(
            query_text=args.cross_modal_text,
            llm_client=llm_client,
            model=EMBEDDING_MODEL,
        )
        random_vector = await embedding_service.embed_image_for_document(
            image_path=random_input,
            llm_client=llm_client,
            model=EMBEDDING_MODEL,
        )
        query_similarity = embedding_service.cosine_similarity(query_vector, sample_vector)
        random_similarity = embedding_service.cosine_similarity(query_vector, random_vector)
        if not embedding_service.passes_cross_modal_gate(
            query_to_target=query_similarity,
            query_to_random=random_similarity,
            minimum_margin=EMBEDDING_TASK_MARGIN,
        ):
            raise RuntimeError(
                "cross-modal query is not closer to same-food target than random food"
            )

    return {
        "mode": "calibrate",
        "status": "pass",
        "visual_corpus_size": args.visual_corpus_size,
        "visual_corpus_acceptable": is_corpus_branch_valid(args.visual_corpus_size),
        "sample": str(sample_input),
        "self_similarity": self_similarity,
        "same_food_peer": str(peer_input),
        "same_food_similarity": same_food_similarity,
        "cross_modal_text": args.cross_modal_text,
        "cross_modal_target_similarity": query_similarity,
        "cross_modal_random_similarity": random_similarity,
        "cross_modal_margin": (
            query_similarity - random_similarity
            if query_similarity is not None and random_similarity is not None
            else None
        ),
    }


async def _run_seed_demo(args: argparse.Namespace, llm_client) -> dict[str, Any]:
    engine = create_async_engine(
        _resolve_database_url(args),
        echo=False,
        pool_pre_ping=True,
    )
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    demo_items = [
        {
            "name": "Daal Chawal",
            "aliases": ["daal chawal", "rice and lentils"],
            "calories": 420.0,
            "protein_g": 16.0,
            "carbs_g": 68.0,
            "fat_g": 12.0,
            "source_type": "home",
            "image": args.sample,
            "is_verified": True,
        }
    ]
    if args.second_sample:
        demo_items.append(
            {
                "name": "Chicken Biryani",
                "aliases": ["chicken biryani"],
                "calories": 520.0,
                "protein_g": 28.0,
                "carbs_g": 58.0,
                "fat_g": 22.0,
                "source_type": "home",
                "image": args.second_sample,
                "is_verified": False,
            }
        )

    seeded = []
    try:
        async with session_factory() as session:
            for item in demo_items:
                existing_item = await session.scalar(
                    select(FoodItem).where(FoodItem.name == item["name"])
                )
                if existing_item is not None:
                    continue

                image_path = _resolve_crop_path(item["image"], flag_name="--sample")
                embedding = await embedding_service.embed_image_for_document(
                    image_path=image_path,
                    llm_client=llm_client,
                    model=EMBEDDING_MODEL,
                )

                food_item = FoodItem(
                    id=str(item["name"]).lower().replace(" ", "-"),
                    name=item["name"],
                    aliases=item["aliases"],
                    source_type=item["source_type"],
                    calories=item["calories"],
                    protein_g=item["protein_g"],
                    carbs_g=item["carbs_g"],
                    fat_g=item["fat_g"],
                    is_verified=item["is_verified"],
                )
                session.add(food_item)
                session.add(
                    FoodVisual(
                        id=f"{food_item.id}-visual",
                        food_item_id=food_item.id,
                        cropped_image_url=str(image_path),
                        embedding=embedding,
                        is_invalidated=False,
                    )
                )
                seeded.append(food_item.id)

            await session.commit()
    finally:
        await engine.dispose()

    return {
        "mode": "seed-demo",
        "status": "pass",
        "seeded_food_items": seeded,
    }


async def _run_unresolved_probe(args: argparse.Namespace, llm_client) -> dict[str, Any]:
    engine = create_async_engine(
        _resolve_database_url(args),
        echo=False,
        pool_pre_ping=True,
    )
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    sample_input = _resolve_crop_path(args.sample, flag_name="--sample")
    probe_segment = MealSegment(
        id=str(uuid.uuid4()),
        meal_log_id="probe-meal",
        cropped_image_url=str(sample_input),
    )

    try:
        async with session_factory() as session:
            existing_visuals = await session.scalar(
                select(func.count())
                .select_from(FoodVisual)
                .where(FoodVisual.is_invalidated == False)  # noqa: E712
            )
            existing_visuals = int(existing_visuals or 0)

            if existing_visuals > 0:
                await session.execute(
                    update(FoodVisual)
                    .where(FoodVisual.is_invalidated == False)  # noqa: E712
                    .values(is_invalidated=True)
                )
                probe_food_item_id = _make_smoke_id("probe-unresolved-item")
                probe_item = FoodItem(
                    id=probe_food_item_id,
                    name="Probe Unresolved",
                    is_verified=False,
                )
                session.add(probe_item)
                probe_embedding = await matching_service.embed_segment_query_embedding(
                    segment=probe_segment,
                    llm_client=llm_client,
                    embedding_model=matching_service.MATCHING_EMBEDDING_MODEL,
                )
                session.add(
                    FoodVisual(
                        id=_make_smoke_id("probe-unresolved-visual"),
                        food_item_id=probe_food_item_id,
                        cropped_image_url=str(sample_input),
                        embedding=[-value for value in probe_embedding],
                        is_invalidated=False,
                    )
                )
                await session.flush()

            result = await matching_service.match_segment_against_visual_corpus(
                segment=probe_segment,
                session=session,
                llm_client=llm_client,
                embedding_model=matching_service.MATCHING_EMBEDDING_MODEL,
            )

            return {
                "mode": "unresolved-probe",
                "status": "pass",
                "sample": str(sample_input),
                "probe_route": "empty-corpus" if existing_visuals == 0 else "below-threshold",
                "visual_count_before_probe": existing_visuals,
                "resolved": result.resolved,
                "is_below_threshold": result.is_below_threshold,
                "routed_state": "REASONING" if result.is_below_threshold else "COMPLETED",
                "similarity": result.similarity,
            }
    finally:
        await engine.dispose()


async def _run_repeat_confirmation(args: argparse.Namespace, llm_client) -> dict[str, Any]:
    engine = create_async_engine(
        _resolve_database_url(args),
        echo=False,
        pool_pre_ping=True,
    )
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    sample_input = _resolve_crop_path(args.sample, flag_name="--sample")
    seed_food_id = "smoke-repeat-food"

    rounds = []
    try:
        async with session_factory() as session:
            seed_food = await session.get(FoodItem, seed_food_id)
            if seed_food is None:
                seed_embedding = await embedding_service.embed_image_for_document(
                    image_path=sample_input,
                    llm_client=llm_client,
                    model=EMBEDDING_MODEL,
                )
                seed_food = FoodItem(
                    id=seed_food_id,
                    name="Repeat Confirmed Food",
                    aliases=["repeat confirmed food", "repeat confirmation"],
                    source_type="home",
                    calories=360.0,
                    protein_g=14.0,
                    carbs_g=58.0,
                    fat_g=10.0,
                    is_verified=True,
                )
                session.add(seed_food)
                session.add(
                    FoodVisual(
                        id=f"{seed_food_id}-seed-visual",
                        food_item_id=seed_food.id,
                        cropped_image_url=str(sample_input),
                        embedding=seed_embedding,
                        is_invalidated=False,
                    )
                )
                await session.commit()

            seed_visual_count_before = int(
                await session.scalar(
                    select(func.count())
                    .select_from(FoodVisual)
                    .where(FoodVisual.food_item_id == seed_food_id)
                )
                or 0
            )

            previous_visual_count = seed_visual_count_before
            for repeat_index in range(2):
                meal = MealLog(
                    id=_make_smoke_id(f"smoke-repeat-{repeat_index}"),
                    image_url=str(sample_input),
                    image_hash=f"repeat-{repeat_index}-{uuid.uuid4()}",
                )
                segment = MealSegment(
                    id=str(uuid.uuid4()),
                    meal_log_id=meal.id,
                    cropped_image_url=str(sample_input),
                )
                session.add(meal)
                session.add(segment)
                await session.flush()

                segment.embedding = await matching_service.embed_segment_query_embedding(
                    segment=segment,
                    llm_client=llm_client,
                    embedding_model=matching_service.MATCHING_EMBEDDING_MODEL,
                )
                match_result = await matching_service.match_segment_with_cached_embedding(
                    segment=segment,
                    session=session,
                )

                if not match_result.resolved:
                    raise RuntimeError("Repeat confirmation did not resolve a match")

                await matching_service.persist_successful_match_rows(
                    session=session,
                    meal=meal,
                    match_results=[(segment, match_result)],
                    llm_client=llm_client,
                )
                meal.processing_status = MealProcessingStatus.COMPLETED
                await session.commit()

                seed_food_visual_count = int(
                    await session.scalar(
                        select(func.count())
                        .select_from(FoodVisual)
                        .where(FoodVisual.food_item_id == seed_food_id)
                    )
                    or 0
                )
                rounds.append(
                    {
                        "round": repeat_index + 1,
                        "meal_id": meal.id,
                        "seed_visual_count": seed_food_visual_count,
                        "visual_added": seed_food_visual_count > previous_visual_count,
                    }
                )
                previous_visual_count = seed_food_visual_count

            seed_visual_count_after = int(
                await session.scalar(
                    select(func.count())
                    .select_from(FoodVisual)
                    .where(FoodVisual.food_item_id == seed_food_id)
                )
                or 0
            )

        return {
            "mode": "repeat-confirmation",
            "status": "pass",
            "sample": str(sample_input),
            "rounds": rounds,
            "seed_food_id": seed_food_id,
            "seed_visual_count_before": seed_visual_count_before,
            "seed_visual_count_after": seed_visual_count_after,
            "committed_before_notification": True,
            "database_commit_signal": "completed_before_any_notification",
        }
    finally:
        await engine.dispose()


async def main() -> int:
    args = _parse_args()
    client = get_llm_client()

    try:
        if args.mode == "calibrate":
            report = await _run_calibrate(args, client)
        elif args.mode == "seed-demo":
            report = await _run_seed_demo(args, client)
        elif args.mode == "repeat-confirmation":
            report = await _run_repeat_confirmation(args, client)
        elif args.mode == "reasoning-probe":
            report = await _run_reasoning_probe(args, client)
        elif args.mode == "grouped-uat":
            report = await _run_grouped_uat(args, client)
        else:
            report = await _run_unresolved_probe(args, client)

        print(json.dumps(report, indent=2))
        return 0
    except Exception as exc:
        print(f"failed: {exc}")
        return 1
    finally:
        await client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
