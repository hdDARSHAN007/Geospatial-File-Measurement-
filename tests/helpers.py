"""Builders for test inputs. Geometry is defined in UTM zone 43N (EPSG:32643) so
the true area/length is known exactly, then converted to lon/lat when needed."""
import zipfile
from pathlib import Path

import geopandas as gpd
from pyproj import Transformer
from shapely.geometry import LineString, Point, Polygon

UTM = "EPSG:32643"  # covers lon 72E-78E (e.g. Bengaluru)
X0, Y0 = 500_000.0, 1_400_000.0  # on the central meridian (75E), ~12.7N

_to_lonlat = Transformer.from_crs(UTM, "EPSG:4326", always_xy=True)


def square_utm(x0=X0, y0=Y0, size=1000.0) -> Polygon:
    """A size x size metre square -> area is exactly size**2 m2."""
    return Polygon([(x0, y0), (x0 + size, y0), (x0 + size, y0 + size), (x0, y0 + size)])


def line_utm(dx=3000.0, dy=4000.0) -> LineString:
    """3-4-5 triangle hypotenuse -> length is exactly 5000 m."""
    return LineString([(X0, Y0), (X0 + dx, Y0 + dy)])


def to_lonlat(geom):
    from shapely.ops import transform

    return transform(_to_lonlat.transform, geom)


def make_shapefile_zip(gdf: gpd.GeoDataFrame, tmp_path: Path, name="data", drop_prj=False,
                       drop=()) -> Path:
    folder = tmp_path / name
    folder.mkdir()
    gdf.to_file(folder / f"{name}.shp")
    zip_path = tmp_path / f"{name}.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for f in sorted(folder.iterdir()):
            if drop_prj and f.suffix == ".prj":
                continue
            if f.suffix in drop:
                continue
            zf.write(f, arcname=f.name)
    return zip_path


def _coords(geom) -> str:
    return " ".join(f"{x},{y},0" for x, y, *_ in geom.coords)


def kml_polygon(poly: Polygon) -> str:
    return (f"<Polygon><outerBoundaryIs><LinearRing><coordinates>{_coords(poly.exterior)}"
            "</coordinates></LinearRing></outerBoundaryIs></Polygon>")


def kml_line(line: LineString) -> str:
    return f"<LineString><coordinates>{_coords(line)}</coordinates></LineString>"


def kml_point(pt: Point) -> str:
    return f"<Point><coordinates>{pt.x},{pt.y},0</coordinates></Point>"


def kml_document(placemarks: dict[str, str]) -> str:
    """placemarks: name -> geometry xml (already in lon/lat)."""
    body = "".join(
        f"<Placemark><name>{name}</name>{xml}</Placemark>" for name, xml in placemarks.items()
    )
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>test</name>'
            f"{body}</Document></kml>")


def upload(client, path: Path):
    return client.post(
        "/api/files/",
        files={"file": (path.name, path.read_bytes(), "application/octet-stream")},
    )
