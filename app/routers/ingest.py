from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from fastapi.responses import ORJSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_session
from app.models import MealLog, MealProcessingStatus
from app.services.image_service import compute_hash, save_and_hash

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.post("/photo", status_code=202)
async def ingest_photo(
    picture: UploadFile = File(...),
    x_ingest_secret: str | None = Header(None, alias="X-Ingest-Secret"),
    session: AsyncSession = Depends(get_session),
) -> ORJSONResponse:
    settings = get_settings()
    if x_ingest_secret != settings.INGEST_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        raw_bytes = await picture.read()
        image_hash = compute_hash(raw_bytes)
        window_start = datetime.now(timezone.utc) - timedelta(
            seconds=settings.DEDUP_WINDOW_SECONDS
        )

        existing_result = await session.execute(
            select(MealLog)
            .where(MealLog.image_hash == image_hash, MealLog.created_at >= window_start)
            .order_by(MealLog.created_at.desc())
            .limit(1)
        )
        existing = existing_result.scalar_one_or_none()
        if existing is not None:
            return ORJSONResponse(
                status_code=200,
                content={"meal_log_id": existing.id, "deduplicated": True},
            )

        meal_id = str(uuid.uuid4())
        dest_path = settings.UPLOADS_DIR / "meals" / f"{meal_id}.jpg"
        save_and_hash(raw_bytes, picture.content_type, dest_path)

        meal = MealLog(
            id=meal_id,
            image_url=str(dest_path),
            image_hash=image_hash,
            processing_status=MealProcessingStatus.PENDING,
        )
        session.add(meal)
        await session.commit()

        return ORJSONResponse(
            status_code=202,
            content={"meal_log_id": meal_id, "deduplicated": False},
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error in ingest_photo")
        raise HTTPException(status_code=500, detail="Internal server error") from None
