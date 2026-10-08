"""HTTP endpoints under /api/files/."""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import config
from app.db import get_db
from app.models import FeatureRecord, FileRecord
from app.schemas import (
    FeatureOut,
    FeaturesResponse,
    FileInfo,
    MeasurementItem,
    MeasurementsResponse,
    MeasurementSummary,
)
from app.services.processing import process_upload

router = APIRouter(prefix="/api/files", tags=["files"])


def _get_file_or_404(db: Session, file_id: str) -> FileRecord:
    record = db.get(FileRecord, file_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"File '{file_id}' not found")
    return record


def _require_completed(record: FileRecord) -> None:
    if record.status != config.STATUS_COMPLETED:
        raise HTTPException(
            status_code=409,
            detail=f"File is not ready (status: {record.status})"
            + (f": {record.error}" if record.error else ""),
        )


@router.post("/", response_model=FileInfo, status_code=201, summary="Upload a KML or zipped Shapefile")
def upload_file(file: UploadFile = File(...), db: Session = Depends(get_db)):
    filename = Path(file.filename or "").name  # drop any client-supplied directories
    ext = Path(filename).suffix.lower()
    if ext not in config.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Upload a .kml file or a .zip containing a Shapefile.",
        )

    file_id = uuid.uuid4().hex
    upload_dir = config.UPLOAD_DIR / file_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    saved_path = upload_dir / f"original{ext}"

    # Stream to disk, enforcing the size limit without loading it all in memory.
    max_bytes = config.MAX_UPLOAD_MB * 1024 * 1024
    size = 0
    try:
        with saved_path.open("wb") as out:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds the {config.MAX_UPLOAD_MB} MB limit",
                    )
                out.write(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")
    except HTTPException:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise

    record = FileRecord(
        id=file_id,
        filename=filename,
        file_type="kml" if ext == ".kml" else "shapefile",
        status=config.STATUS_PROCESSING,
    )
    db.add(record)
    db.commit()

    process_upload(db, record, saved_path, ext)

    if record.status == config.STATUS_FAILED:
        raise HTTPException(
            status_code=422,
            detail={"message": record.error, "file_id": file_id},
        )
    return record


@router.get("/", response_model=list[FileInfo], summary="List uploaded files")
def list_files(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    stmt = select(FileRecord).order_by(FileRecord.created_at.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt))


@router.get("/{file_id}/", response_model=FileInfo, summary="File information")
def get_file(file_id: str, db: Session = Depends(get_db)):
    return _get_file_or_404(db, file_id)


@router.get(
    "/{file_id}/measurements/",
    response_model=MeasurementsResponse,
    summary="Measurements for every feature (paginated)",
)
def get_measurements(
    file_id: str,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    record = _get_file_or_404(db, file_id)
    _require_completed(record)

    rows = db.scalars(
        select(FeatureRecord)
        .where(FeatureRecord.file_id == file_id)
        .order_by(FeatureRecord.feature_index)
        .limit(limit)
        .offset(offset)
    ).all()

    total_area, total_length, n_area, n_length, n_notes = db.execute(
        select(
            func.coalesce(func.sum(FeatureRecord.area_m2), 0.0),
            func.coalesce(func.sum(FeatureRecord.length_m), 0.0),
            func.count(FeatureRecord.area_m2),
            func.count(FeatureRecord.length_m),
            func.count(FeatureRecord.note),
        ).where(FeatureRecord.file_id == file_id)
    ).one()

    return MeasurementsResponse(
        file_id=file_id,
        status=record.status,
        total=record.feature_count,
        limit=limit,
        offset=offset,
        summary=MeasurementSummary(
            total_area_square_meters=round(total_area, 4),
            total_length_meters=round(total_length, 4),
            measured_features=n_area + n_length,
            features_with_notes=n_notes,
        ),
        results=[
            MeasurementItem(
                index=r.feature_index,
                geometry_type=r.geometry_type,
                crs=r.crs,
                measurement=r.measurement,
                note=r.note,
            )
            for r in rows
        ],
    )


@router.get(
    "/{file_id}/features/",
    response_model=FeaturesResponse,
    summary="Full features: geometry, CRS, properties and measurement (paginated)",
)
def get_features(
    file_id: str,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    record = _get_file_or_404(db, file_id)
    _require_completed(record)

    rows = db.scalars(
        select(FeatureRecord)
        .where(FeatureRecord.file_id == file_id)
        .order_by(FeatureRecord.feature_index)
        .limit(limit)
        .offset(offset)
    ).all()

    return FeaturesResponse(
        file_id=file_id,
        total=record.feature_count,
        limit=limit,
        offset=offset,
        results=[
            FeatureOut(
                index=r.feature_index,
                geometry_type=r.geometry_type,
                geometry=r.geometry,
                crs=r.crs,
                properties=r.properties or {},
                measurement=r.measurement,
                note=r.note,
            )
            for r in rows
        ],
    )


@router.delete("/{file_id}/", status_code=204, summary="Delete a file and its features")
def delete_file(file_id: str, db: Session = Depends(get_db)):
    record = _get_file_or_404(db, file_id)
    db.delete(record)
    db.commit()
    shutil.rmtree(config.UPLOAD_DIR / file_id, ignore_errors=True)
    return Response(status_code=204)
