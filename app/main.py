"""FastAPI application entrypoint:  uvicorn app.main:app --reload"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import config, models  # noqa: F401  (models import registers the tables)
from app.api.files import router as files_router
from app.db import Base, engine


@asynccontextmanager
async def lifespan(_: FastAPI):
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
    yield


app = FastAPI(
    title="Geospatial File Measurement API",
    description=(
        "Upload a KML or zipped Shapefile; get back every feature with its "
        "geometry, CRS, properties and area / length measurements."
    ),
    version="1.0.0",
    lifespan=lifespan,
)
app.include_router(files_router)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}
