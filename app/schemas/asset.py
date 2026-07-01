from datetime import datetime

from pydantic import BaseModel


class AssetCreate(BaseModel):
    kind: str
    path: str


class AssetRead(BaseModel):
    id: int
    kind: str
    path: str
    created_at: datetime

    model_config = {"from_attributes": True}
