"""Orchestrates parse -> measure -> persist for one uploaded file."""
from __future__ import annotations

import datetime as dt
import logging
import math
from pathlib import Path

import numpy as np
import pandas as pd
from shapely.geometry import mapping
from sqlalchemy.orm import Session

from app import config
from app.models import FeatureRecord, FileRecord
from app.services.crs import crs_label
from app.services.measurements import measure_geometry
from app.services.parser import FileProcessingError, parse_file

log = logging.getLogger(__name__)


def clean_value(value):
    """Convert pandas/numpy scalars to plain JSON-safe Python values."""
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        f = float(value)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(value, (pd.Timestamp, dt.datetime, dt.date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, str):
        return value
    return str(value)


def process_upload(db: Session, record: FileRecord, saved_path: Path, ext: str) -> FileRecord:
    """Parse the saved upload, measure every feature and store the results.

    Always leaves ``record`` as COMPLETED or FAILED; never raises.
    """
    try:
        parsed = parse_file(saved_path, ext)
        gdf, crs = parsed.gdf, parsed.crs
        crs_text = crs_label(crs)
        is_kml = parsed.file_type == "kml"

        props_df = gdf.drop(columns=[gdf.geometry.name])
        features: list[FeatureRecord] = []
        for position, geom in enumerate(gdf.geometry):
            row = props_df.iloc[position].to_dict()
            props = {str(k): clean_value(v) for k, v in row.items()}
            if is_kml:  # KML carries many empty schema columns; keep only real values
                props = {k: v for k, v in props.items() if v not in (None, "")}

            result = measure_geometry(geom, crs)
            empty = geom is None or geom.is_empty
            features.append(
                FeatureRecord(
                    file_id=record.id,
                    feature_index=position,
                    geometry_type=None if geom is None else geom.geom_type,
                    geometry=None if empty else mapping(geom),
                    crs=crs_text,
                    properties=props,
                    measurement=result.measurement,
                    area_m2=result.area_m2,
                    length_m=result.length_m,
                    note=result.note,
                )
            )

        db.add_all(features)
        record.status = config.STATUS_COMPLETED
        record.crs = crs_text
        record.file_type = parsed.file_type
        record.feature_count = len(features)
        record.error = None
        db.commit()
    except FileProcessingError as exc:
        _mark_failed(db, record, str(exc))
    except Exception:  # unexpected: log details, show a generic message
        log.exception("Unexpected error processing file %s", record.id)
        _mark_failed(db, record, "Unexpected error while processing the file")
    return record


def _mark_failed(db: Session, record: FileRecord, message: str) -> None:
    db.rollback()
    record.status = config.STATUS_FAILED
    record.error = message
    record.feature_count = 0
    db.add(record)
    db.commit()
