from __future__ import annotations

import base64
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pgvector.sqlalchemy import cosine_distance
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from app.models import FoodVisual, MealSegment
from app.services import image_service
from app.services.llm_client import OpenRouterClient

MATCH_THRESHOLD: float = 0.85
MATCHING_EMBEDDING_MODEL: str = "google/gemini-embedding-2-preview"
MAX_MATCHING_RETRIES: int = 3
EMBEDDING_DIMENSION: int = 1536


class MatchingError(ValueError):
    """Error raised when a segment cannot be matched."""


@dataclass(frozen=True)
class SegmentMatchResult:
    food_visual_id: str | None
    food_item_id: str | None
    similarity: float | None
    food_visual: FoodVisual | None
    query_embedding: list[float]
    is_match: bool
    is_below_threshold: bool
    match_threshold: float = MATCH_THRESHOLD

    @property
    def resolved(self) -> bool:
        return self.is_match and not self.is_below_threshold


def _prepare_image_payload(image_path: Path) -> dict[str, Any]:
    image_reference = str(image_path)
    if image_reference.startswith(("http://", "https://", "data:")):
        return {
            "type": "image_url",
            "image_url": {"url": image_reference},
        }

    mime_type, _ = mimetypes.guess_type(image_path.name)
    raw_bytes = image_path.read_bytes()
    if mime_type in image_service.HEIC_CONTENT_TYPES:
        converted = image_service.transcode_to_jpeg(raw_bytes, mime_type or "image/heic")
        mime_type = "image/jpeg"
        raw_bytes = converted
    elif mime_type is None:
        mime_type = "image/jpeg"

    encoded = base64.b64encode(raw_bytes).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
    }


def _prepare_query_content(image_path: str | Path) -> list[dict[str, Any]]:
    path = Path(image_path)
    content = [
        {
            "type": "text",
            "text": "Create a deterministic embedding for this food image crop.",
        },
    ]
    content.append(_prepare_image_payload(path))
    return content


def _validate_embedding(embedding: list[float], output_dimensionality: int) -> list[float]:
    if len(embedding) != output_dimensionality:
        raise MatchingError(
            f"embedding length mismatch: expected {output_dimensionality}, got {len(embedding)}"
        )
    parsed: list[float] = []
    for value in embedding:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise MatchingError("embedding values must be numeric")
        parsed.append(float(value))
    return parsed


def _coerce_embedding(values: object | None) -> list[float]:
    if values is None:
        raise MatchingError("segment embedding must be populated before matching")
    if not isinstance(values, list):
        raise MatchingError("segment embedding must be a list of floats")
    return [float(value) for value in values]


async def _embed_with_retry(
    *,
    llm_client: OpenRouterClient,
    model: str,
    content: list[dict[str, Any]],
    task_type: str,
    output_dimensionality: int = EMBEDDING_DIMENSION,
) -> list[float]:
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(MAX_MATCHING_RETRIES),
        wait=wait_exponential_jitter(initial=0.4, max=1.8),
        retry=retry_if_exception_type((TypeError, ValueError, RuntimeError)),
        reraise=True,
    ):
        with attempt:
            embedding = await llm_client.embed_multimodal(
                model=model,
                content=content,
                output_dimensionality=output_dimensionality,
                task_type=task_type,
            )
            return _validate_embedding(embedding, output_dimensionality=output_dimensionality)


def is_below_threshold(similarity: float | None, threshold: float = MATCH_THRESHOLD) -> bool:
    if similarity is None:
        return True
    return similarity < threshold


async def embed_segment_query_embedding(
    *,
    segment: MealSegment,
    llm_client: OpenRouterClient,
    embedding_model: str = MATCHING_EMBEDDING_MODEL,
) -> list[float]:
    if not segment.cropped_image_url:
        raise MatchingError("segment crop URL is required for matching")
    content = _prepare_query_content(segment.cropped_image_url)
    return await _embed_with_retry(
        llm_client=llm_client,
        model=embedding_model,
        content=content,
        task_type="RETRIEVAL_QUERY",
    )


async def _best_food_visual_match(
    *,
    session: AsyncSession,
    query_embedding: list[float],
) -> tuple[FoodVisual | None, float | None]:
    statement = (
        select(FoodVisual, cosine_distance(FoodVisual.embedding, query_embedding).label("distance"))
        .where(FoodVisual.is_invalidated == False)  # noqa: E712
        .order_by(cosine_distance(FoodVisual.embedding, query_embedding))
        .limit(1)
    )
    result = await session.execute(statement)
    row = result.first()
    if row is None:
        return None, None

    food_visual, distance = row
    if food_visual is None or distance is None:
        return None, None

    return food_visual, 1.0 - float(distance)


async def match_segment_with_cached_embedding(
    *,
    segment: MealSegment,
    session: AsyncSession,
    match_threshold: float = MATCH_THRESHOLD,
) -> SegmentMatchResult:
    if segment.embedding is None:
        raise MatchingError("segment embedding is required for cached-match")

    query_embedding = _validate_embedding(_coerce_embedding(segment.embedding), EMBEDDING_DIMENSION)
    segment.embedding = query_embedding
    food_visual, similarity = await _best_food_visual_match(session=session, query_embedding=query_embedding)
    if food_visual is None:
        return SegmentMatchResult(
            food_visual_id=None,
            food_item_id=None,
            similarity=None,
            food_visual=None,
            query_embedding=query_embedding,
            is_match=False,
            is_below_threshold=True,
            match_threshold=match_threshold,
        )

    below_threshold = is_below_threshold(similarity, threshold=match_threshold)
    return SegmentMatchResult(
        food_visual_id=food_visual.id,
        food_item_id=food_visual.food_item_id,
        similarity=similarity,
        food_visual=food_visual,
        query_embedding=query_embedding,
        is_match=not below_threshold,
        is_below_threshold=below_threshold,
        match_threshold=match_threshold,
    )


async def match_segment_against_visual_corpus(
    *,
    segment: MealSegment,
    session: AsyncSession,
    llm_client: OpenRouterClient,
    embedding_model: str = MATCHING_EMBEDDING_MODEL,
    match_threshold: float = MATCH_THRESHOLD,
) -> SegmentMatchResult:
    query_embedding = await embed_segment_query_embedding(
        segment=segment,
        llm_client=llm_client,
        embedding_model=embedding_model,
    )
    segment.embedding = query_embedding
    return await match_segment_with_cached_embedding(
        segment=segment,
        session=session,
        match_threshold=match_threshold,
    )


__all__ = [
    "EMBEDDING_DIMENSION",
    "MATCH_THRESHOLD",
    "MATCHING_EMBEDDING_MODEL",
    "SegmentMatchResult",
    "MatchingError",
    "embed_segment_query_embedding",
    "is_below_threshold",
    "match_segment_against_visual_corpus",
    "match_segment_with_cached_embedding",
]
