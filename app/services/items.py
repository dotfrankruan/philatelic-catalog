from sqlalchemy import Select, select
from sqlalchemy.orm import Session, selectinload

from app.models import Asset, Item, Tag, TrackingEvent
from app.schemas import AssetCreate, ItemCreate, ItemUpdate, TagCreate, TrackingEventCreate


def build_item_query(
    country: str | None = None,
    category: str | None = None,
    status: str | None = None,
    q: str | None = None,
) -> Select[tuple[Item]]:
    query = (
        select(Item)
        .options(
            selectinload(Item.assets),
            selectinload(Item.tags),
            selectinload(Item.tracking_events),
        )
        .order_by(Item.created_at.desc())
    )
    if country:
        query = query.where(Item.country == country)
    if category:
        query = query.where(Item.category == category)
    if status:
        query = query.where(Item.status == status)
    if q:
        like = f"%{q}%"
        query = query.where(
            Item.title.ilike(like)
            | Item.tracking_number.ilike(like)
            | Item.origin.ilike(like)
            | Item.destination.ilike(like)
        )
    return query


def create_item(session: Session, payload: ItemCreate) -> Item:
    item = Item(**payload.model_dump())
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def update_item(session: Session, item: Item, payload: ItemUpdate) -> Item:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def attach_tag(session: Session, item: Item, payload: TagCreate) -> Tag:
    tag = session.scalar(select(Tag).where(Tag.name == payload.name))
    if tag is None:
        tag = Tag(name=payload.name)
        session.add(tag)
        session.flush()
    if tag not in item.tags:
        item.tags.append(tag)
    session.add(item)
    session.commit()
    session.refresh(tag)
    return tag


def attach_asset(session: Session, item: Item, payload: AssetCreate) -> Asset:
    asset = Asset(item_id=item.id, **payload.model_dump())
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


def add_tracking_event(
    session: Session, item: Item, payload: TrackingEventCreate
) -> TrackingEvent:
    event = TrackingEvent(item_id=item.id, **payload.model_dump())
    session.add(event)
    session.commit()
    session.refresh(event)
    return event
