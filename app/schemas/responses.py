from pydantic import BaseModel


class IngestResponse(BaseModel):
    meal_log_id: str
    deduplicated: bool = False


class HealthResponse(BaseModel):
    status: str
