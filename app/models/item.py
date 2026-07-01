from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    country: Mapped[str] = mapped_column(String(120), index=True)
    category: Mapped[str] = mapped_column(String(120), index=True)
    tracking_number: Mapped[str | None] = mapped_column(String(120), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    origin: Mapped[str | None] = mapped_column(String(255))
    destination: Mapped[str | None] = mapped_column(String(255))
    sent_on: Mapped[date | None] = mapped_column(Date())
    received_on: Mapped[date | None] = mapped_column(Date())
    status: Mapped[str | None] = mapped_column(String(80), index=True)
    notes: Mapped[str | None] = mapped_column(Text())
    is_returned: Mapped[bool] = mapped_column(Boolean(), default=False)
    is_self_mail: Mapped[bool] = mapped_column(Boolean(), default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    assets: Mapped[list["Asset"]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )
    tracking_events: Mapped[list["TrackingEvent"]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )
    tags: Mapped[list["Tag"]] = relationship(
        secondary="item_tags", back_populates="items"
    )
