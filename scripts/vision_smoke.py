from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
import sys
import tempfile
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Literal

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PIL import Image

from app.config import get_settings
from app.services.image_service import transcode_to_jpeg
from app.services.llm_client import get_llm_client
from app.services.vision_service import (
    dedupe_overlapping_segments,
    detect_food_photo,
    label_food_segment,
    segment_food_photo_with_retry,
)

Mode = Literal["detect", "segment", "label", "all"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Live OpenRouter smoke probe for MealTracker vision stages.")
    parser.add_argument("--mode", choices=["detect", "segment", "label", "all"], required=True)
    parser.add_argument("--sample", required=True, help="Path to sample meal image.")
    return parser.parse_args()


def _prepare_sample_image(sample_path: Path) -> tuple[Path, tempfile.TemporaryDirectory[str] | None]:
    suffix = sample_path.suffix.lower()
    if suffix not in {".heic", ".heif"}:
        return sample_path, None

    mime_type, _ = mimetypes.guess_type(sample_path.name)
    jpeg_bytes = transcode_to_jpeg(sample_path.read_bytes(), mime_type or "image/heic")
    temp_dir = tempfile.TemporaryDirectory()
    prepared_path = Path(temp_dir.name) / f"{sample_path.stem}.jpg"
    prepared_path.write_bytes(jpeg_bytes)
    return prepared_path, temp_dir


def _save_temp_crop(source_image_path: Path, normalized_box: list[float], crops_dir: Path) -> Path:
    image = Image.open(source_image_path)
    width, height = image.size
    y_min, x_min, y_max, x_max = normalized_box
    left = int(x_min * width)
    right = int(x_max * width)
    top = int(y_min * height)
    bottom = int(y_max * height)

    left = max(0, min(left, width - 1))
    right = max(left + 1, min(right, width))
    top = max(0, min(top, height - 1))
    bottom = max(top + 1, min(bottom, height))

    crop_path = crops_dir / f"{uuid.uuid4()}.jpg"
    crop_path.parent.mkdir(parents=True, exist_ok=True)
    image.crop((left, top, right, bottom)).convert("RGB").save(crop_path, format="JPEG", quality=85)
    return crop_path


async def _run_detect(sample_path: Path) -> dict[str, object]:
    settings = get_settings()
    client = get_llm_client()
    decision = await detect_food_photo(
        str(sample_path),
        llm_client=client,
        model=settings.DETECT_MODEL,
    )
    return {
        "mode": "detect",
        "sample": str(sample_path),
        "decision": decision,
    }


async def _run_segment(sample_path: Path) -> tuple[list, dict[str, object]]:
    settings = get_settings()
    client = get_llm_client()
    segments = await segment_food_photo_with_retry(
        str(sample_path),
        llm_client=client,
        model=settings.SEGMENT_MODEL,
        retry_model=settings.SEGMENT_RETRY_MODEL,
        max_segments=settings.VISION_MAX_SEGMENTS,
    )
    segments = dedupe_overlapping_segments(segments)
    payload = {
        "mode": "segment",
        "sample": str(sample_path),
        "segment_count": len(segments),
        "segments": [asdict(segment) for segment in segments],
    }
    return segments, payload


async def _run_label(
    sample_path: Path,
    crops_dir: Path,
    *,
    segments: list | None = None,
    segment_payload: dict[str, object] | None = None,
) -> dict[str, object]:
    settings = get_settings()
    client = get_llm_client()
    if segments is None or segment_payload is None:
        segments, segment_payload = await _run_segment(sample_path)
    if not segments:
        raise RuntimeError("segment mode produced no usable regions")

    labels: list[dict[str, object]] = []
    for segment in segments:
        crop_path = _save_temp_crop(sample_path, normalized_box=segment.box_2d, crops_dir=crops_dir)
        label = await label_food_segment(
            str(crop_path),
            llm_client=client,
            model=settings.LABEL_MODEL,
        )
        if label is None:
            raise RuntimeError(f"label stage returned unusable payload for crop {crop_path}")
        labels.append(
            {
                "crop_path": str(crop_path),
                "label": label,
                "confidence": segment.confidence,
                "box_2d": segment.box_2d,
            }
        )

    return {
        "mode": "label",
        "sample": str(sample_path),
        "segment_summary": segment_payload,
        "labels": labels,
    }


async def run(mode: Mode, sample_path: Path, crops_dir: Path) -> dict[str, object]:
    if mode == "detect":
        return await _run_detect(sample_path)
    if mode == "segment":
        _, payload = await _run_segment(sample_path)
        if payload["segment_count"] == 0:
            raise RuntimeError("segment mode produced no usable regions")
        return payload
    if mode == "label":
        return await _run_label(sample_path, crops_dir)

    detect_payload = await _run_detect(sample_path)
    if detect_payload["decision"]["next_action"] != "segment":
        raise RuntimeError(f"detect stage stopped pipeline: {detect_payload['decision']}")
    segments, segment_payload = await _run_segment(sample_path)
    if segment_payload["segment_count"] == 0:
        raise RuntimeError("segment mode produced no usable regions")
    label_payload = await _run_label(
        sample_path,
        crops_dir,
        segments=segments,
        segment_payload=segment_payload,
    )
    return {
        "mode": "all",
        "sample": str(sample_path),
        "detect": detect_payload["decision"],
        "segment": {
            "segment_count": segment_payload["segment_count"],
            "segments": segment_payload["segments"],
        },
        "label": label_payload["labels"],
    }


async def main() -> int:
    args = parse_args()
    raw_sample_path = Path(args.sample).expanduser().resolve()
    if not raw_sample_path.exists():
        raise FileNotFoundError(f"sample not found: {raw_sample_path}")

    prepared_sample_path, temp_dir = _prepare_sample_image(raw_sample_path)
    crops_temp_dir = tempfile.TemporaryDirectory()
    crops_dir = Path(crops_temp_dir.name) / "crops"
    try:
        payload = await run(args.mode, prepared_sample_path, crops_dir)
        print(json.dumps(payload, indent=2))
        return 0
    finally:
        client = get_llm_client()
        await client.close()
        crops_temp_dir.cleanup()
        temp_dir.cleanup() if temp_dir is not None else None


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
