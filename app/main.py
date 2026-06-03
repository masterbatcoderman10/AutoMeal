from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse
from telegram import Bot

from app.config import get_settings
from app.database import create_engine, get_engine, get_session_factory
from app.routers import health, ingest
from app.services import recovery_service, tracing_service


scheduler = AsyncIOScheduler()


async def _run_meal_janitor_job() -> None:
    settings = get_settings()
    async with Bot(token=settings.TELEGRAM_BOT_TOKEN) as bot:
        await recovery_service.run_meal_janitor(
            session_factory=get_session_factory(),
            settings=settings,
            bot=bot,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    tracing_service.validate_langfuse_required()
    create_engine(settings.DATABASE_URL)
    if scheduler.get_job(recovery_service.MEAL_JANITOR_JOB_ID) is None:
        scheduler.add_job(
            _run_meal_janitor_job,
            "interval",
            id=recovery_service.MEAL_JANITOR_JOB_ID,
            minutes=settings.JANITOR_INTERVAL_MINUTES,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=max(60, int(settings.JANITOR_INTERVAL_MINUTES * 60)),
        )
    scheduler.start()

    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        await get_engine().dispose()


app = FastAPI(lifespan=lifespan, default_response_class=ORJSONResponse)
app.include_router(ingest)
app.include_router(health)
