from datetime import date, datetime

from pydantic import BaseModel

from app.schemas.asset import AssetRead
from app.schemas.tag import TagRead
from app.schemas.tracking_event import TrackingEventRead


class ItemBase(BaseModel):
    country: str
    category: str
    tracking_number: str | None = None
    title: str
    origin: str | None = None
    destination: str | None = None
    sent_on: date | None = None
    received_on: date | None = None
    status: str | None = None
    notes: str | None = None
    is_returned: bool = False
    is_self_mail: bool = False


class ItemCreate(ItemBase):
    pass


class ItemUpdate(BaseModel):
    country: str | None = None
    category: str | None = None
    tracking_number: str | None = None
    title: str | None = None
    origin: str | None = None
    destination: str | None = None
    sent_on: date | None = None
    received_on: date | None = None
    status: str | None = None
    notes: str | None = None
    is_returned: bool | None = None
    is_self_mail: bool | None = None


class ItemRead(ItemBase):
    id: int
    created_at: datetime
    updated_at: datetime
    assets: list[AssetRead] = []
    tags: list[TagRead] = []
    tracking_events: list[TrackingEventRead] = []

    model_config = {"from_attributes": True}
