"""Generate sample shapefile zips into sample_data/.

    python scripts/make_sample_data.py

Creates:
  sample_data/parcels_wgs84.zip      polygons + attributes, EPSG:4326
  sample_data/roads_utm43n.zip       lines, already projected (EPSG:32643)
"""
import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, Polygon

OUT = Path(__file__).resolve().parent.parent / "sample_data"


def zip_shapefile(gdf: gpd.GeoDataFrame, name: str) -> Path:
    with tempfile.TemporaryDirectory() as tmp:
        shp = Path(tmp) / f"{name}.shp"
        gdf.to_file(shp)
        zip_path = OUT / f"{name}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for part in sorted(Path(tmp).iterdir()):
                zf.write(part, arcname=part.name)
    return zip_path


def main() -> None:
    OUT.mkdir(exist_ok=True)

    parcels = gpd.GeoDataFrame(
        {"parcel_id": ["P-001", "P-002"], "owner": ["Asha", "Ravi"]},
        geometry=[
            Polygon([(77.590, 12.960), (77.5946, 12.960), (77.5946, 12.9645), (77.590, 12.9645)]),
            Polygon([(77.600, 12.960), (77.605, 12.960), (77.605, 12.965), (77.600, 12.965)]),
        ],
        crs="EPSG:4326",
    )
    print("wrote", zip_shapefile(parcels, "parcels_wgs84"))

    roads = gpd.GeoDataFrame(
        {"road": ["Link Rd"], "lanes": [2]},
        geometry=[LineString([(500000, 1400000), (503000, 1404000)])],  # exactly 5000 m
        crs="EPSG:32643",
    ).to_crs("EPSG:32643")
    print("wrote", zip_shapefile(roads, "roads_utm43n"))


if __name__ == "__main__":
    main()
