"""Read an uploaded KML or zipped Shapefile into a GeoDataFrame.

All problems the *user* can cause (bad zip, missing sidecar files, unreadable
data, no CRS) are raised as ``FileProcessingError`` with a readable message.
"""
from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import pandas as pd
from pyproj import CRS

from app import config


class FileProcessingError(Exception):
    """The uploaded file cannot be processed (client-side problem)."""


@dataclass
class ParsedFile:
    gdf: gpd.GeoDataFrame
    file_type: str  # "kml" | "shapefile"
    crs: CRS | None


def parse_file(path: Path, ext: str) -> ParsedFile:
    """Dispatch on extension. ``path`` is the saved upload; extraction happens
    next to it, inside the per-upload directory."""
    if ext == ".kml":
        gdf = _read_kml(path)
        return ParsedFile(gdf, "kml", gdf.crs)
    if ext == ".zip":
        shp = _extract_shapefile(path, path.parent / "extracted")
        gdf = _read_shapefile(shp)
        return ParsedFile(gdf, "shapefile", gdf.crs)
    raise FileProcessingError(f"Unsupported file type: {ext}")


# --- KML ----------------------------------------------------------------------

def _read_kml(path: Path) -> gpd.GeoDataFrame:
    import pyogrio

    try:
        layers = pyogrio.list_layers(str(path))
    except Exception as exc:
        raise FileProcessingError(f"Could not read KML file: {exc}") from exc

    frames = []
    for name, _geometry_type in layers:
        try:
            part = gpd.read_file(path, layer=name, engine="pyogrio")
        except Exception:
            continue  # skip layers GDAL cannot read
        if part.empty:
            continue
        if len(layers) > 1:
            part["_layer"] = name
        frames.append(part)

    if not frames:
        raise FileProcessingError("KML file contains no readable features")

    gdf = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=frames[0].crs)
    if gdf.crs is None:
        gdf = gdf.set_crs(4326)  # the KML specification mandates WGS 84
    return gdf


# --- Shapefile (zip) ----------------------------------------------------------

def _extract_shapefile(zip_path: Path, dest: Path) -> Path:
    """Safely extract the zip and return the path of its single .shp file."""
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    max_bytes = config.MAX_UNZIPPED_MB * 1024 * 1024

    try:
        with zipfile.ZipFile(zip_path) as zf:
            members = [
                m for m in zf.infolist()
                if not m.is_dir()
                and not m.filename.startswith("__MACOSX/")
                and not Path(m.filename).name.startswith("._")
            ]
            if len(members) > config.MAX_ZIP_ENTRIES:
                raise FileProcessingError("Zip contains too many files")
            if sum(m.file_size for m in members) > max_bytes:
                raise FileProcessingError(
                    f"Zip expands to more than {config.MAX_UNZIPPED_MB} MB"
                )
            for m in members:
                target = (root / m.filename).resolve()
                # zip-slip guard: nothing may land outside ``dest``
                if not target.is_relative_to(root):
                    raise FileProcessingError(
                        f"Unsafe path in zip archive: {m.filename}"
                    )
                zf.extract(m, root)
    except zipfile.BadZipFile as exc:
        raise FileProcessingError("File is not a valid zip archive") from exc

    shp_files = sorted(p for p in root.rglob("*") if p.suffix.lower() == ".shp")
    if not shp_files:
        raise FileProcessingError("Zip does not contain a .shp file")
    if len(shp_files) > 1:
        raise FileProcessingError(
            "Zip contains more than one shapefile; upload one shapefile per zip"
        )

    shp = shp_files[0]
    siblings = {p.name.lower() for p in shp.parent.iterdir()}
    missing = [
        ext for ext in (".shx", ".dbf") if f"{shp.stem.lower()}{ext}" not in siblings
    ]
    if missing:
        raise FileProcessingError(
            f"Shapefile is missing required component(s): {', '.join(missing)}"
        )
    return shp


def _read_shapefile(shp: Path) -> gpd.GeoDataFrame:
    try:
        gdf = gpd.read_file(shp, engine="pyogrio")
    except Exception as exc:
        raise FileProcessingError(f"Could not read shapefile: {exc}") from exc

    if gdf.empty:
        raise FileProcessingError("Shapefile contains no features")

    if gdf.crs is None:
        # Policy: no .prj -> accept only if the coordinates look like lon/lat.
        minx, miny, maxx, maxy = gdf.total_bounds
        if -180 <= minx and maxx <= 180 and -90 <= miny and maxy <= 90:
            gdf = gdf.set_crs(4326)
        else:
            raise FileProcessingError(
                "Shapefile has no .prj (CRS) and its coordinates do not look like "
                "latitude/longitude, so the CRS cannot be determined"
            )
    return gdf
