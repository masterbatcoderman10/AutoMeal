from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

from app.config import get_settings
from app.database import create_engine, get_engine
from app.routers import health, ingest


scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    create_engine(settings.DATABASE_URL)
    scheduler.start()

    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        await get_engine().dispose()


app = FastAPI(lifespan=lifespan, default_response_class=ORJSONResponse)
app.include_router(ingest.router)
app.include_router(health.router)
