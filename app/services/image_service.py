from __future__ import annotations

from pathlib import Path
import hashlib
from io import BytesIO
from typing import Sequence

from fastapi import HTTPException

from PIL import Image

HEIC_CONTENT_TYPES = {"image/heic", "image/heif", "image/heic+heif"}


def compute_hash(raw_bytes: bytes) -> str:
    return hashlib.sha256(raw_bytes).hexdigest()


def transcode_to_jpeg(raw_bytes: bytes, content_type: str) -> bytes:
    if content_type in HEIC_CONTENT_TYPES:
        import pillow_heif

        heif_file = pillow_heif.read_heif(raw_bytes)
        image = Image.frombytes(heif_file.mode, heif_file.size, heif_file.data, "raw")
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=85)
        return buffer.getvalue()

    if content_type.startswith("image/"):
        return raw_bytes

    raise HTTPException(status_code=400, detail="Unsupported content type")


def save_upload(jpeg_bytes: bytes, dest_path: Path) -> None:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(jpeg_bytes)


def save_and_hash(
    raw_bytes: bytes,
    content_type: str,
    dest_path: Path,
) -> tuple[str, bytes]:
    image_hash = compute_hash(raw_bytes)
    jpeg_bytes = transcode_to_jpeg(raw_bytes, content_type)
    save_upload(jpeg_bytes, dest_path)
    return image_hash, jpeg_bytes


def save_segment_crop(
    source_image_path: Path,
    segment_id: str,
    normalized_box: Sequence[float],
) -> Path:
    if len(normalized_box) != 4:
        raise ValueError("normalized_box must be four coordinates")

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

    crop = image.crop((left, top, right, bottom))
    if crop.size[0] == 0 or crop.size[1] == 0:
        raise ValueError("invalid crop dimensions")

    crops_dir = Path("/data/uploads/crops")
    crops_dir.mkdir(parents=True, exist_ok=True)
    crop_path = crops_dir / f"{segment_id}.jpg"

    output = BytesIO()
    crop.convert("RGB").save(output, format="JPEG", quality=85)
    save_upload(output.getvalue(), crop_path)
    return crop_path
