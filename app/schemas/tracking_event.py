from datetime import datetime

from pydantic import BaseModel


class TrackingEventCreate(BaseModel):
    occurred_at: datetime
    location: str | None = None
    status: str
    details: str | None = None
    source: str | None = None


class TrackingEventRead(BaseModel):
    id: int
    occurred_at: datetime
    location: str | None
    status: str
    details: str | None
    source: str | None

    model_config = {"from_attributes": True}
