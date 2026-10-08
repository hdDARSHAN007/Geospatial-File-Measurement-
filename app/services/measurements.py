"""Area / length calculation for a single geometry.

Rules
-----
* Polygon, MultiPolygon        -> area   (square metres)
* LineString, MultiLineString  -> length (metres)
* Point, MultiPoint            -> no measurement
* anything else / empty        -> no measurement + an explanatory note

Geographic CRS input (e.g. EPSG:4326) is never measured in degrees: the
geometry is reprojected to the UTM (or polar) zone of its centroid first.
A geodesic (WGS84 ellipsoid) value is returned alongside as a cross-check.
Nothing in here raises: failures become a ``note``.
"""
from __future__ import annotations

from dataclasses import dataclass

from pyproj import CRS, Geod
from shapely.ops import transform

from app.services.crs import (
    crs_label,
    get_transformer,
    linear_unit_factor,
    select_projected_epsg,
)

_GEOD = Geod(ellps="WGS84")

AREA_TYPES = {"Polygon", "MultiPolygon"}
LINE_TYPES = {"LineString", "MultiLineString", "LinearRing"}
POINT_TYPES = {"Point", "MultiPoint"}

_DECIMALS = 4


@dataclass
class MeasurementResult:
    measurement: dict | None = None
    note: str | None = None
    area_m2: float | None = None
    length_m: float | None = None


def measure_geometry(geom, crs: CRS | None) -> MeasurementResult:
    """Measure one shapely geometry that is expressed in ``crs``."""
    if geom is None or geom.is_empty:
        return MeasurementResult(note="empty or missing geometry")

    gtype = geom.geom_type
    if gtype in POINT_TYPES:
        return MeasurementResult()  # nothing to measure, and that is fine
    if gtype not in AREA_TYPES and gtype not in LINE_TYPES:
        return MeasurementResult(note=f"unsupported geometry type: {gtype}")
    if crs is None:
        return MeasurementResult(note="CRS unknown; cannot measure")

    try:
        return _measure(geom, crs, "area" if gtype in AREA_TYPES else "length")
    except Exception as exc:  # never let one bad feature fail the whole file
        return MeasurementResult(note=f"measurement failed: {exc}")


def _measure(geom, crs: CRS, kind: str) -> MeasurementResult:
    note = None
    if kind == "area" and not geom.is_valid:
        note = "geometry is invalid (e.g. self-intersecting); area may be inaccurate"

    geodesic = None
    if crs.is_geographic:
        centroid = geom.centroid
        epsg = select_projected_epsg(centroid.x, centroid.y)
        projected = transform(get_transformer(crs.to_wkt(), epsg).transform, geom)
        value = projected.area if kind == "area" else projected.length
        geodesic = _geodesic_area(geom) if kind == "area" else _geodesic_length(geom)
        method, projected_crs = "projected", f"EPSG:{epsg}"
    else:
        factor = linear_unit_factor(crs)
        raw = geom.area if kind == "area" else geom.length
        value = raw * factor**2 if kind == "area" else raw * factor
        method, projected_crs = "native_projected", crs_label(crs)

    value = round(value, _DECIMALS)
    measurement = {
        "type": kind,
        "value": value,
        "unit": "square_meters" if kind == "area" else "meters",
        "method": method,
        "projected_crs": projected_crs,
        "geodesic_value": round(geodesic, _DECIMALS) if geodesic is not None else None,
    }
    return MeasurementResult(
        measurement=measurement,
        note=note,
        area_m2=value if kind == "area" else None,
        length_m=value if kind == "length" else None,
    )


# --- geodesic helpers (coordinates are lon/lat degrees) -----------------------

def _ring_area(coords) -> float:
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    area, _ = _GEOD.polygon_area_perimeter(lons, lats)
    return abs(area)


def _polygon_area(poly) -> float:
    area = _ring_area(poly.exterior.coords)
    for hole in poly.interiors:
        area -= _ring_area(hole.coords)
    return area


def _geodesic_area(geom) -> float:
    polys = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
    return sum(_polygon_area(p) for p in polys)


def _geodesic_length(geom) -> float:
    lines = geom.geoms if geom.geom_type == "MultiLineString" else [geom]
    total = 0.0
    for line in lines:
        coords = list(line.coords)
        total += _GEOD.line_length([c[0] for c in coords], [c[1] for c in coords])
    return total
