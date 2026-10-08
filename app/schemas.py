"""Pydantic response models."""
from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class FileInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    file_type: str
    feature_count: int
    crs: str | None
    status: Literal["PROCESSING", "COMPLETED", "FAILED"]
    error: str | None = None
    created_at: dt.datetime


class Measurement(BaseModel):
    type: Literal["area", "length"]
    value: float
    unit: Literal["square_meters", "meters"]
    # "projected": reprojected from a geographic CRS to a UTM/polar zone first.
    # "native_projected": the file was already in a projected CRS.
    method: Literal["projected", "native_projected"]
    projected_crs: str | None = None
    # Independent ellipsoidal (WGS84) result, for geographic input only.
    geodesic_value: float | None = None


class FeatureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    index: int
    geometry_type: str | None
    geometry: dict[str, Any] | None
    crs: str | None
    properties: dict[str, Any]
    measurement: Measurement | None
    note: str | None


class MeasurementItem(BaseModel):
    index: int
    geometry_type: str | None
    crs: str | None
    measurement: Measurement | None
    note: str | None


class MeasurementSummary(BaseModel):
    total_area_square_meters: float
    total_length_meters: float
    measured_features: int
    features_with_notes: int


class Page(BaseModel):
    total: int
    limit: int
    offset: int


class MeasurementsResponse(Page):
    file_id: str
    status: str
    summary: MeasurementSummary
    results: list[MeasurementItem]


class FeaturesResponse(Page):
    file_id: str
    results: list[FeatureOut]
