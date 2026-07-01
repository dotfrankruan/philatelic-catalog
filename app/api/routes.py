from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.database import get_session
from app.models import Item, Tag
from app.schemas import (
    AssetCreate,
    AssetRead,
    ItemCreate,
    ItemRead,
    ItemUpdate,
    TagCreate,
    TagRead,
    TrackingEventCreate,
    TrackingEventRead,
)
from app.services.items import (
    add_tracking_event,
    attach_asset,
    attach_tag,
    build_item_query,
    create_item,
    update_item,
)

router = APIRouter()


def get_item_or_404(session: Session, item_id: int) -> Item:
    item = session.scalar(
        select(Item)
        .options(
            selectinload(Item.assets),
            selectinload(Item.tags),
            selectinload(Item.tracking_events),
        )
        .where(Item.id == item_id)
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    return item


@router.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/items", response_model=list[ItemRead])
def list_items(
    country: str | None = None,
    category: str | None = None,
    status_value: str | None = Query(default=None, alias="status"),
    q: str | None = None,
    session: Session = Depends(get_session),
) -> list[Item]:
    query = build_item_query(country=country, category=category, status=status_value, q=q)
    return list(session.scalars(query).all())


@router.post("/items", response_model=ItemRead, status_code=status.HTTP_201_CREATED)
def create_item_endpoint(payload: ItemCreate, session: Session = Depends(get_session)) -> Item:
    return create_item(session, payload)


@router.get("/items/{item_id}", response_model=ItemRead)
def get_item(item_id: int, session: Session = Depends(get_session)) -> Item:
    return get_item_or_404(session, item_id)


@router.patch("/items/{item_id}", response_model=ItemRead)
def update_item_endpoint(
    item_id: int, payload: ItemUpdate, session: Session = Depends(get_session)
) -> Item:
    item = get_item_or_404(session, item_id)
    return update_item(session, item, payload)


@router.post("/items/{item_id}/tags", response_model=TagRead, status_code=status.HTTP_201_CREATED)
def add_tag_to_item(
    item_id: int, payload: TagCreate, session: Session = Depends(get_session)
) -> Tag:
    item = get_item_or_404(session, item_id)
    return attach_tag(session, item, payload)


@router.post(
    "/items/{item_id}/assets",
    response_model=AssetRead,
    status_code=status.HTTP_201_CREATED,
)
def add_asset_to_item(
    item_id: int, payload: AssetCreate, session: Session = Depends(get_session)
):
    item = get_item_or_404(session, item_id)
    return attach_asset(session, item, payload)


@router.post(
    "/items/{item_id}/tracking-events",
    response_model=TrackingEventRead,
    status_code=status.HTTP_201_CREATED,
)
def add_tracking_event_to_item(
    item_id: int, payload: TrackingEventCreate, session: Session = Depends(get_session)
):
    item = get_item_or_404(session, item_id)
    return add_tracking_event(session, item, payload)


@router.get("/tags", response_model=list[TagRead])
def list_tags(session: Session = Depends(get_session)) -> list[Tag]:
    return list(session.scalars(select(Tag).order_by(Tag.name.asc())).all())
