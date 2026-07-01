from pydantic import BaseModel


class TagCreate(BaseModel):
    name: str


class TagRead(BaseModel):
    id: int
    name: str

    model_config = {"from_attributes": True}
