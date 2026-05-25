from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

from fastapi import HTTPException

HEIC_CONTENT_TYPES = {"image/heic", "image/heif", "image/heic+heif"}


def compute_hash(raw_bytes: bytes) -> str:
    return hashlib.sha256(raw_bytes).hexdigest()


def transcode_to_jpeg(raw_bytes: bytes, content_type: str | None) -> bytes:
    if content_type in HEIC_CONTENT_TYPES:
        import pillow_heif
        from PIL import Image

        heif_file = pillow_heif.read_heif(raw_bytes)
        image = Image.frombytes(
            heif_file.mode,
            heif_file.size,
            heif_file.data,
            "raw",
        )
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=85)
        return buffer.getvalue()

    if content_type and content_type.startswith("image/"):
        return raw_bytes

    raise HTTPException(
        status_code=400,
        detail=f"Unsupported content type: {content_type or 'unknown'}",
    )


def save_upload(jpeg_bytes: bytes, dest_path: Path) -> None:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(jpeg_bytes)


def save_and_hash(raw_bytes: bytes, content_type: str | None, dest_path: Path) -> tuple[str, bytes]:
    image_hash = compute_hash(raw_bytes)
    jpeg_bytes = transcode_to_jpeg(raw_bytes, content_type)
    save_upload(jpeg_bytes, dest_path)
    return image_hash, jpeg_bytes
