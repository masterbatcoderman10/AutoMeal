from __future__ import annotations

import base64
import mimetypes
import math
from pathlib import Path
from typing import Any

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from app.services import image_service
from app.services.llm_client import OpenRouterClient

EMBEDDING_DIMENSION: int = 1536
RETRIEVAL_DOCUMENT: str = "RETRIEVAL_DOCUMENT"
RETRIEVAL_QUERY: str = "RETRIEVAL_QUERY"
MAX_EMBEDDING_RETRIES: int = 3


class EmbeddingError(ValueError):
    pass


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


def _prepare_image_content(image_path: str | Path) -> list[dict[str, Any]]:
    image_reference: str | Path
    if isinstance(image_path, str) and image_path.startswith(("http://", "https://", "data:")):
        image_reference = image_path
    else:
        image_reference = Path(image_path)
    payload = [
        {
            "type": "text",
            "text": "Create a deterministic embedding for this food image crop.",
        },
    ]
    payload.append(_prepare_image_payload(image_reference))
    return payload


def _validate_similarity_inputs(first: list[float], second: list[float]) -> None:
    if len(first) != len(second):
        raise EmbeddingError("embeddings used for similarity must have matching dimensions")
    if not first or not second:
        raise EmbeddingError("embeddings used for similarity must be non-empty")


def _validate_embedding(embedding: list[float], *, output_dimensionality: int) -> list[float]:
    if len(embedding) != output_dimensionality:
        raise EmbeddingError(
            f"embedding length mismatch: expected {output_dimensionality}, got {len(embedding)}"
        )
    parsed: list[float] = []
    for item in embedding:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise EmbeddingError("embedding values must be numeric")
        parsed.append(float(item))
    return parsed


def cosine_similarity(first: list[float], second: list[float]) -> float:
    _validate_similarity_inputs(first, second)

    numerator = sum(a * b for a, b in zip(first, second, strict=True))
    denominator = math.sqrt(sum(a * a for a in first)) * math.sqrt(sum(b * b for b in second))
    if denominator == 0.0:
        return 0.0
    return float(numerator / denominator)


def passes_same_image_gate(similarity: float, threshold: float = 0.99) -> bool:
    return similarity >= threshold


def passes_cross_modal_gate(query_to_target: float, query_to_random: float, minimum_margin: float) -> bool:
    return (query_to_target - query_to_random) > minimum_margin


def is_corpus_empty_ok(corpus_size: int) -> bool:
    return corpus_size == 0


async def _embed_with_retry(
    *,
    llm_client: OpenRouterClient,
    model: str,
    content: list[dict[str, Any]],
    task_type: str,
    output_dimensionality: int = EMBEDDING_DIMENSION,
    ) -> list[float]:
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(MAX_EMBEDDING_RETRIES),
        wait=wait_exponential_jitter(initial=0.4, max=1.8),
        retry=retry_if_exception_type((httpx.HTTPError,)),
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


async def embed_image_for_document(
    *,
    image_path: str | Path,
    llm_client: OpenRouterClient,
    model: str,
    output_dimensionality: int = EMBEDDING_DIMENSION,
) -> list[float]:
    content = _prepare_image_content(image_path)
    return await _embed_with_retry(
        llm_client=llm_client,
        model=model,
        content=content,
        task_type=RETRIEVAL_DOCUMENT,
        output_dimensionality=output_dimensionality,
    )


async def embed_text_for_query(
    *,
    query_text: str,
    llm_client: OpenRouterClient,
    model: str,
    output_dimensionality: int = EMBEDDING_DIMENSION,
) -> list[float]:
    content = [{"type": "text", "text": query_text}]
    return await _embed_with_retry(
        llm_client=llm_client,
        model=model,
        content=content,
        task_type=RETRIEVAL_QUERY,
        output_dimensionality=output_dimensionality,
    )


__all__ = [
    "EMBEDDING_DIMENSION",
    "EmbeddingError",
    "RETRIEVAL_DOCUMENT",
    "RETRIEVAL_QUERY",
    "cosine_similarity",
    "embed_image_for_document",
    "embed_text_for_query",
    "is_corpus_empty_ok",
    "passes_same_image_gate",
    "passes_cross_modal_gate",
]
