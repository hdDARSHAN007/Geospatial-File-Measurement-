"""Unit tests for the pure CRS / measurement logic (no HTTP, no files)."""
import pytest
from pyproj import CRS
from shapely.geometry import GeometryCollection, LineString, Point, Polygon

from app.services.crs import linear_unit_factor, select_projected_epsg
from app.services.measurements import measure_geometry

WGS84 = CRS.from_epsg(4326)


@pytest.mark.parametrize("lon,lat,epsg", [
    (77.59, 12.97, 32643),    # Bengaluru, zone 43N
    (-0.12, 51.50, 32630),    # London, zone 30N
    (-70.0, -33.0, 32719),    # Santiago, zone 19S
    (180.0, 10.0, 32601),     # date line wraps to zone 1
    (10.0, 87.0, 3413),       # Arctic -> polar stereographic
    (10.0, -85.0, 3031),      # Antarctic -> polar stereographic
])
def test_select_projected_epsg(lon, lat, epsg):
    assert select_projected_epsg(lon, lat) == epsg


def test_linear_unit_factor():
    assert linear_unit_factor(CRS.from_epsg(32643)) == 1.0
    assert linear_unit_factor(CRS.from_epsg(2272)) == pytest.approx(0.3048006, rel=1e-5)  # US ft


def test_point_has_no_measurement_and_no_note():
    r = measure_geometry(Point(77.59, 12.97), WGS84)
    assert r.measurement is None and r.note is None


def test_empty_and_none_geometries_are_noted():
    assert "empty" in measure_geometry(Polygon(), WGS84).note
    assert "empty" in measure_geometry(None, WGS84).note


def test_geometry_collection_is_unsupported():
    r = measure_geometry(GeometryCollection([Point(0, 0), LineString([(0, 0), (1, 1)])]), WGS84)
    assert r.measurement is None and "unsupported" in r.note


def test_unknown_crs_is_noted():
    r = measure_geometry(LineString([(0, 0), (1, 1)]), None)
    assert r.measurement is None and "CRS" in r.note


def test_one_degree_of_longitude_at_equator_is_about_111km():
    r = measure_geometry(LineString([(77.0, 0.0), (78.0, 0.0)]), WGS84)
    assert r.length_m == pytest.approx(111_319.5, rel=2e-3)


def test_feet_based_crs_is_converted_to_meters():
    # 1000 ft x 1000 ft square in a US-foot CRS = 92,903.04 m2 (within survey-foot tolerance)
    sq = Polygon([(0, 0), (1000, 0), (1000, 1000), (0, 1000)])
    r = measure_geometry(sq, CRS.from_epsg(2272))
    assert r.area_m2 == pytest.approx(92_903.04, rel=1e-4)
