from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from fastapi.responses import ORJSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_session
from app.models import MealLog, MealProcessingStatus
from app.schemas.responses import IngestResponse
from app.services.image_service import save_and_hash

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.post("/photo")
async def ingest_photo(
    picture: UploadFile = File(...),
    x_ingest_secret: str | None = Header(default=None, alias="X-Ingest-Secret"),
    session: AsyncSession = Depends(get_session),
) -> IngestResponse:
    settings = get_settings()

    if x_ingest_secret != settings.INGEST_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        raw_bytes = await picture.read()
        image_hash = hashlib.sha256(raw_bytes).hexdigest()

        cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.DEDUP_WINDOW_SECONDS)
        result = await session.execute(
            select(MealLog)
            .where(MealLog.image_hash == image_hash, MealLog.created_at >= cutoff)
            .order_by(MealLog.created_at.desc())
            .limit(1)
        )
        existing = result.scalar_one_or_none()

        if existing is not None:
            return ORJSONResponse(
                status_code=200,
                content={"meal_log_id": existing.id, "deduplicated": True},
            )

        meal_id = str(uuid.uuid4())
        dest_path = settings.UPLOADS_DIR / "meals" / f"{meal_id}.jpg"
        save_and_hash(raw_bytes=raw_bytes, content_type=picture.content_type or "", dest_path=dest_path)

        meal = MealLog(
            id=meal_id,
            image_url=str(dest_path),
            image_hash=image_hash,
            processing_status=MealProcessingStatus.PENDING,
        )
        session.add(meal)
        await session.commit()

        return ORJSONResponse(status_code=202, content={"meal_log_id": meal_id, "deduplicated": False})
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Ingest failed: {exc}") from exc
