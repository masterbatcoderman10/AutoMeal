from app.routers.health import router as health
from app.routers.ingest import router as ingest

__all__ = ["ingest", "health"]
