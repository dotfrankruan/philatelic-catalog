from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.config import settings
from app.db.database import Base, engine
from app.models import asset, item, tag, tracking_event  # noqa: F401
from app.ui import ui_router

settings.managed_archive_root.mkdir(parents=True, exist_ok=True)

@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(router)
app.include_router(ui_router)
app.mount("/archive", StaticFiles(directory=settings.managed_archive_root), name="archive")
