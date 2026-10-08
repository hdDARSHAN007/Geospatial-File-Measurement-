import zipfile

import geopandas as gpd
import pytest
from shapely.geometry import Point, Polygon

from tests.helpers import (
    UTM,
    kml_document,
    kml_line,
    kml_point,
    kml_polygon,
    line_utm,
    make_shapefile_zip,
    square_utm,
    to_lonlat,
    upload,
)

AREA_1KM2 = 1_000_000.0


def _measurements(client, file_id, **params):
    r = client.get(f"/api/files/{file_id}/measurements/", params=params)
    assert r.status_code == 200, r.text
    return r.json()


# --- correctness --------------------------------------------------------------

def test_kml_polygon_area_is_in_square_meters(client, tmp_path):
    """A 1 km x 1 km square given in lon/lat must measure ~1,000,000 m2, not ~1e-4 deg2."""
    kml = tmp_path / "square.kml"
    kml.write_text(kml_document({"sq": kml_polygon(to_lonlat(square_utm()))}))

    r = upload(client, kml)
    assert r.status_code == 201, r.text
    info = r.json()
    assert (info["status"], info["feature_count"], info["crs"]) == ("COMPLETED", 1, "EPSG:4326")

    data = _measurements(client, info["id"])
    m = data["results"][0]["measurement"]
    assert m["type"] == "area" and m["unit"] == "square_meters"
    assert m["method"] == "projected" and m["projected_crs"] == "EPSG:32643"
    assert m["value"] == pytest.approx(AREA_1KM2, rel=1e-5)
    # Ellipsoidal cross-check; differs by UTM's 0.9996 scale factor (~0.08% in area).
    assert m["geodesic_value"] == pytest.approx(AREA_1KM2, rel=2e-3)
    assert data["summary"]["total_area_square_meters"] == pytest.approx(AREA_1KM2, rel=1e-5)


def test_projected_shapefile_is_measured_in_its_own_crs(client, tmp_path):
    gdf = gpd.GeoDataFrame({"name": ["plot"]}, geometry=[square_utm()], crs=UTM)
    r = upload(client, make_shapefile_zip(gdf, tmp_path))
    assert r.status_code == 201, r.text
    info = r.json()
    assert "32643" in info["crs"] or "UTM" in info["crs"]

    m = _measurements(client, info["id"])["results"][0]["measurement"]
    assert m["method"] == "native_projected"
    assert m["value"] == pytest.approx(AREA_1KM2, rel=1e-9)


def test_wgs84_shapefile_line_length_and_properties(client, tmp_path):
    gdf = gpd.GeoDataFrame({"road": ["NH44"]}, geometry=[to_lonlat(line_utm())], crs="EPSG:4326")
    r = upload(client, make_shapefile_zip(gdf, tmp_path))
    assert r.status_code == 201, r.text
    file_id = r.json()["id"]

    m = _measurements(client, file_id)["results"][0]["measurement"]
    assert m["type"] == "length" and m["unit"] == "meters"
    assert m["value"] == pytest.approx(5000.0, rel=1e-5)  # 3-4-5 triangle
    assert m["geodesic_value"] == pytest.approx(5000.0, rel=2e-3)

    feat = client.get(f"/api/files/{file_id}/features/").json()["results"][0]
    assert feat["index"] == 0
    assert feat["geometry_type"] == "LineString"
    assert feat["geometry"]["type"] == "LineString"
    assert feat["crs"] == "EPSG:4326"
    assert feat["properties"]["road"] == "NH44"


def test_mixed_geometries_do_not_crash(client, tmp_path):
    line = to_lonlat(line_utm())
    kml = tmp_path / "mixed.kml"
    kml.write_text(kml_document({
        "pt": kml_point(to_lonlat(Point(500_000, 1_400_000))),
        "ln": kml_line(line),
        "poly": kml_polygon(to_lonlat(square_utm())),
        # Mixed MultiGeometry -> GeometryCollection, which we do not measure
        "multi": "<MultiGeometry>"
                 + kml_point(to_lonlat(Point(500_000, 1_400_000))) + kml_line(line)
                 + "</MultiGeometry>",
    }))
    r = upload(client, kml)
    assert r.status_code == 201, r.text
    info = r.json()
    assert info["feature_count"] == 4

    by_type = {x["geometry_type"]: x for x in _measurements(client, info["id"])["results"]}
    assert by_type["Point"]["measurement"] is None and by_type["Point"]["note"] is None
    assert by_type["LineString"]["measurement"]["value"] == pytest.approx(5000.0, rel=1e-5)
    assert by_type["Polygon"]["measurement"]["value"] == pytest.approx(AREA_1KM2, rel=1e-5)
    assert by_type["GeometryCollection"]["measurement"] is None
    assert "unsupported" in by_type["GeometryCollection"]["note"]


def test_invalid_polygon_is_flagged_not_fatal(client, tmp_path):
    bowtie = Polygon([(77.59, 12.97), (77.60, 12.98), (77.60, 12.97), (77.59, 12.98)])
    kml = tmp_path / "bowtie.kml"
    kml.write_text(kml_document({"bad": kml_polygon(bowtie)}))
    r = upload(client, kml)
    assert r.status_code == 201, r.text
    item = _measurements(client, r.json()["id"])["results"][0]
    assert "invalid" in item["note"]


# --- pagination ---------------------------------------------------------------

def test_measurements_are_paginated(client, tmp_path):
    squares = [square_utm(x0=500_000 + i * 2000) for i in range(5)]
    gdf = gpd.GeoDataFrame({"n": range(5)}, geometry=squares, crs=UTM)
    file_id = upload(client, make_shapefile_zip(gdf, tmp_path)).json()["id"]

    page = _measurements(client, file_id, limit=2, offset=2)
    assert page["total"] == 5 and page["limit"] == 2 and page["offset"] == 2
    assert [x["index"] for x in page["results"]] == [2, 3]
    # The summary always covers the whole file, not just the page.
    assert page["summary"]["total_area_square_meters"] == pytest.approx(5 * AREA_1KM2, rel=1e-9)


# --- CRS policy for shapefiles without .prj --------------------------------

def test_missing_prj_with_lonlat_coordinates_assumes_wgs84(client, tmp_path):
    gdf = gpd.GeoDataFrame({"n": [1]}, geometry=[to_lonlat(square_utm())], crs="EPSG:4326")
    r = upload(client, make_shapefile_zip(gdf, tmp_path, drop_prj=True))
    assert r.status_code == 201, r.text
    assert r.json()["crs"] == "EPSG:4326"


def test_missing_prj_with_projected_coordinates_is_rejected(client, tmp_path):
    gdf = gpd.GeoDataFrame({"n": [1]}, geometry=[square_utm()], crs=UTM)
    r = upload(client, make_shapefile_zip(gdf, tmp_path, drop_prj=True))
    assert r.status_code == 422
    assert "CRS" in r.json()["detail"]["message"]


# --- error handling -----------------------------------------------------------

def test_unsupported_extension_is_400(client):
    r = client.post("/api/files/", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 400


def test_empty_upload_is_400(client):
    r = client.post("/api/files/", files={"file": ("empty.kml", b"", "application/xml")})
    assert r.status_code == 400


def test_corrupt_zip_is_422_and_recorded_as_failed(client):
    r = client.post("/api/files/", files={"file": ("bad.zip", b"not a zip", "application/zip")})
    assert r.status_code == 422
    file_id = r.json()["detail"]["file_id"]

    info = client.get(f"/api/files/{file_id}/").json()
    assert info["status"] == "FAILED" and "zip" in info["error"].lower()
    assert client.get(f"/api/files/{file_id}/measurements/").status_code == 409


def test_shapefile_missing_dbf_is_422(client, tmp_path):
    gdf = gpd.GeoDataFrame({"n": [1]}, geometry=[square_utm()], crs=UTM)
    r = upload(client, make_shapefile_zip(gdf, tmp_path, drop=(".dbf",)))
    assert r.status_code == 422
    assert ".dbf" in r.json()["detail"]["message"]


def test_zip_slip_is_rejected(client, tmp_path):
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../evil.txt", "pwned")
    r = upload(client, evil)
    assert r.status_code == 422
    assert "unsafe" in r.json()["detail"]["message"].lower()


def test_garbage_kml_is_422(client):
    r = client.post("/api/files/", files={"file": ("x.kml", b"<not-kml>", "application/xml")})
    assert r.status_code == 422


@pytest.mark.parametrize("method,path", [
    ("get", "/api/files/nope/"),
    ("get", "/api/files/nope/measurements/"),
    ("get", "/api/files/nope/features/"),
    ("delete", "/api/files/nope/"),
])
def test_unknown_id_is_404(client, method, path):
    assert getattr(client, method)(path).status_code == 404


def test_delete_removes_file(client, tmp_path):
    kml = tmp_path / "s.kml"
    kml.write_text(kml_document({"sq": kml_polygon(to_lonlat(square_utm()))}))
    file_id = upload(client, kml).json()["id"]
    assert client.delete(f"/api/files/{file_id}/").status_code == 204
    assert client.get(f"/api/files/{file_id}/").status_code == 404
