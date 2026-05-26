from fastapi import APIRouter
from fastapi.responses import ORJSONResponse

from app.schemas.responses import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> HealthResponse:
    return ORJSONResponse({"status": "ok"})
